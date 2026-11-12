"""Offline appliance: scan registry images with the real Trivy CLI container.

core/vuln_scan_core.py scans every image with its bundled advisory snapshot (Nano and offline). On the
appliance, when Docker and the pinned Trivy image are available, this module upgrades individual images to a
REAL Trivy report (`vuln_scan_core.parse_trivy_report`), which then takes over for that image digest:

    docker create --network none trivy image --input /in/image.tar --format json --skip-db-update --offline-scan
    docker cp - <ctr>:/in       (a docker-archive built from the registry's stored manifest + config + layers)
    docker start -a <ctr>; docker cp <ctr>:/out/report.json -; docker rm -f <ctr>

* No bind mounts (tar streams through `docker cp`), the scan container has NO network. The vulnerability DB is
  downloaded once (the only networked step, `trivy image --download-db-only`) into the appliance data dir and
  copied in with every scan.
* The image is NEVER pulled implicitly: it must already be present locally (or VYOMI_TRIVY_PULL=1).
* Never blocks a request: ``cached_reports`` returns what finished; ``request_scan`` queues work on one background
  worker, deduplicated by digest.
* Honest degradation: any failure leaves the bundled engine in charge and ``status()`` says why.
Containers are named ``vyomi-trivy-<id>`` and always removed.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
import threading
import time
import uuid
from pathlib import Path

from core import vuln_scan_core as vs

TRIVY_VERSION = "0.58.1"
IMAGE = os.environ.get("VYOMI_TRIVY_IMAGE", f"aquasec/trivy:{TRIVY_VERSION}")
SCAN_TIMEOUT_S = int(os.environ.get("VYOMI_TRIVY_TIMEOUT_S", "180"))
_ENV = ["TRIVY_NO_PROGRESS=true", "TRIVY_DISABLE_TELEMETRY=true"]
_REPORTS: dict[str, dict] = {}
_PENDING: set[str] = set()
_STATUS = {"state": "idle", "reason": ""}
_LOCK = threading.Lock()
_PRE = {"at": 0.0, "reason": ""}


def _docker(args, *, input_bytes=None, timeout=60):
    return subprocess.run(["docker", *args], input=input_bytes, capture_output=True, timeout=timeout)


def _err(p) -> str:
    return ((p.stderr or p.stdout or b"").decode("utf-8", "replace").strip().splitlines() or [""])[-1]


def db_dir() -> Path:
    env = os.environ.get("VYOMI_TRIVY_CACHE")
    if env:
        return Path(env)
    try:
        from core.app_context import STATE_FILE
        base = Path(STATE_FILE).parent
    except Exception:
        base = Path.cwd()
    return base / "trivy-cache"


def preflight() -> str | None:
    if not shutil.which("docker"):
        return "The docker CLI is not available, so the Trivy container cannot run"
    try:
        p = _docker(["version", "--format", "{{.Server.Version}}"], timeout=15)
    except Exception as e:
        return f"Docker is not reachable ({type(e).__name__})"
    if p.returncode != 0:
        return "Docker daemon is not reachable: " + _err(p)
    if _docker(["image", "inspect", IMAGE], timeout=20).returncode != 0:
        if os.environ.get("VYOMI_TRIVY_PULL") != "1":
            return f"The Trivy image {IMAGE} is not present locally (set VYOMI_TRIVY_PULL=1 to allow a one-time pull)"
        if _docker(["pull", IMAGE], timeout=900).returncode != 0:
            return f"The Trivy image {IMAGE} could not be pulled"
    if not (db_dir() / "db" / "trivy.db").is_file():
        return "The Trivy vulnerability DB is not in the appliance data dir (one-time download needs network; see download_db())"
    return None


def download_db() -> str | None:
    """The only networked step: fetch the Trivy DB into db_dir() (via a throwaway container). None on success."""
    name = f"vyomi-trivy-db-{uuid.uuid4().hex[:8]}"
    try:
        if _docker(["create", "--name", name, *sum((["-e", e] for e in _ENV), []), IMAGE, "image", "--download-db-only", "--cache-dir", "/cache"], timeout=60).returncode != 0:
            return "could not create the DB download container"
        p = _docker(["start", "-a", name], timeout=600)
        if p.returncode != 0:
            return _err(p)
        out = _docker(["cp", f"{name}:/cache", "-"], timeout=300)
        db_dir().mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(out.stdout)) as tf:
            tf.extractall(db_dir().parent, filter="data") if hasattr(tarfile, "data_filter") else tf.extractall(db_dir().parent)
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    finally:
        _docker(["rm", "-f", name], timeout=30)


def build_docker_archive(repo_tag: str, manifest: dict, get_blob) -> bytes | None:
    """A `docker save`-style tar (manifest.json + config + layers) from a stored image manifest. None if a blob is missing."""
    cfg_d = (manifest.get("config") or {}).get("digest")
    cfg = get_blob(cfg_d) if cfg_d else None
    if cfg is None:
        return None
    files = {"config.json": cfg}
    layers = []
    for i, l in enumerate(manifest.get("layers") or []):
        b = get_blob(l.get("digest"))
        if b is None:
            return None
        files[f"layer{i}.tar"] = b
        layers.append(f"layer{i}.tar")
    files["manifest.json"] = json.dumps([{"Config": "config.json", "RepoTags": [repo_tag], "Layers": layers}]).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for n, d in files.items():
            ti = tarfile.TarInfo(n); ti.size = len(d); ti.mtime = int(time.time())
            tf.addfile(ti, io.BytesIO(d))
    return buf.getvalue()


def scan_archive(archive: bytes) -> tuple[dict | None, str]:
    name = f"vyomi-trivy-{uuid.uuid4().hex[:10]}"
    try:
        p = _docker(["create", "--name", name, "--network", "none", *sum((["-e", e] for e in _ENV), []), IMAGE, "image", "--input", "/in/image.tar",
                     "--format", "json", "--output", "/out/report.json", "--skip-db-update", "--offline-scan", "--cache-dir", "/cache"], timeout=60)
        if p.returncode != 0:
            return None, "could not create the Trivy container: " + _err(p)
        if _docker(["cp", "-", f"{name}:/"], input_bytes=_pack(archive), timeout=120).returncode != 0:
            return None, "could not copy the image into the Trivy container"
        _docker(["start", "-a", name], timeout=SCAN_TIMEOUT_S)
        out = _docker(["cp", f"{name}:/out/report.json", "-"], timeout=60)
        if out.returncode != 0:
            return None, "Trivy produced no report"
        with tarfile.open(fileobj=io.BytesIO(out.stdout)) as tf:
            m = next(m for m in tf.getmembers() if m.isfile())
            return json.loads(tf.extractfile(m).read()), ""
    except subprocess.TimeoutExpired:
        return None, f"the Trivy scan timed out after {SCAN_TIMEOUT_S}s"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    finally:
        _docker(["rm", "-f", name], timeout=30)


def _pack(archive: bytes) -> bytes:
    """Tar stream laying down /in/image.tar, /out/ and the DB under /cache."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for d in ("in", "out", "cache"):
            ti = tarfile.TarInfo(d); ti.type = tarfile.DIRTYPE; ti.mode = 0o777; tf.addfile(ti)
        ti = tarfile.TarInfo("in/image.tar"); ti.size = len(archive); tf.addfile(ti, io.BytesIO(archive))
        dbp = db_dir()
        if dbp.is_dir():
            tf.add(str(dbp), arcname="cache")
    return buf.getvalue()


def cached_reports() -> dict:
    with _LOCK:
        return dict(_REPORTS)


def status() -> dict:
    return dict(_STATUS)


def request_scan(store) -> None:
    """Queue Trivy scans for every tagged image digest of an AcrRegistryStore that has no report yet (non-blocking)."""
    todo = []
    for repo_name, repo in (getattr(store, "repos", None) or {}).items():
        for tag, t in (repo.get("tags") or {}).items():
            dg = t.get("digest")
            if dg and dg not in _REPORTS and dg not in _PENDING and dg in (repo.get("manifests") or {}):
                todo.append((repo_name, tag, dg, repo))
    if not todo:
        return
    now = time.time()
    if now - _PRE["at"] < 60 and _PRE["reason"]:        # don't poke docker on every read while it is unavailable
        return
    reason = preflight()
    _PRE.update(at=now, reason=reason or "")
    if reason:
        _STATUS.update(state="unavailable", reason=reason)
        return
    for _, _, dg, _ in todo:
        _PENDING.add(dg)

    def work():
        for repo_name, tag, dg, repo in todo:
            try:
                man = json.loads(repo["manifests"][dg]["body"])
                arc = build_docker_archive(f"{repo_name}:{tag}", man, lambda d, r=repo: (r.get("blobs") or {}).get(d))
                if arc is None:
                    _STATUS.update(state="partial", reason=f"{repo_name}:{tag} has no stored layers/config to export")
                    continue
                rep, why = scan_archive(arc)
                if rep is not None:
                    with _LOCK:
                        _REPORTS[dg] = vs.parse_trivy_report(rep)
                    _STATUS.update(state="ok", reason="")
                else:
                    _STATUS.update(state="failed", reason=why)
            finally:
                _PENDING.discard(dg)

    threading.Thread(target=work, daemon=True, name="vyomi-trivy").start()
