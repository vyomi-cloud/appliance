"""Offline appliance: run the real Kubescape CLI against an AKS cluster's Kubernetes objects.

The Microsoft Defender for Cloud engine (core/azure_security_core.py) reads Kubernetes posture
findings from ``rec["_kubescape"]`` on the cluster's ARM record (core/kubescape_core.py). On the
appliance this module fills it, by running the pinned Kubescape CLI container
(core.kubescape_core.IMAGE) as a sibling container through the `docker` CLI:

    docker create --network none … kubescape scan framework nsa,mitre,cis-v1.12.0 /home/nonroot/scan
           --use-artifacts-from /home/nonroot/artifacts --format json --output …/results.json
           --submit=false --keep-local
    docker cp - <ctr>:/home/nonroot          (objects.yaml + the artifacts, as a tar stream)
    docker start -a <ctr>; docker cp <ctr>:/home/nonroot/out/results.json -; docker rm -f <ctr>

* No bind mounts (files go in and out with `docker cp`), so it works the same whether the
  appliance runs on the host or inside its own container with the host's docker socket.
* Air-gapped + no telemetry: the scan container has no network at all; the framework / control
  artifacts are downloaded ONCE (`kubescape download artifacts`, the only networked step) into the
  appliance data dir and passed with --use-artifacts-from; --submit=false --keep-local, and
  KS_SKIP_UPDATE_CHECK / KS_OFFLINE are set.
* Never blocks a request: scans run on one background worker, debounced (DEBOUNCE_S) after object
  changes; the request thread only marks the result "queued".
* Honest degradation: no docker CLI / daemon unreachable / image or artifacts unavailable / scan
  failure -> the result is "unavailable" or "failed" with the reason, and Defender shows that
  instead of findings.

Containers are named ``vyomi-ks-scan-<id>`` and always removed.
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

from core import azure_aks_k8s_core as k8s
from core import k8s_yaml
from core import kubescape_core as ks

DEBOUNCE_S = float(os.environ.get("VYOMI_KUBESCAPE_DEBOUNCE_S", "2"))
SCAN_TIMEOUT_S = int(os.environ.get("VYOMI_KUBESCAPE_TIMEOUT_S", "180"))
ENGINE = f"kubescape-cli {ks.KUBESCAPE_VERSION}"
_ENV = ["KS_SKIP_UPDATE_CHECK=true", "KS_OFFLINE=true", "KS_LOGGER=error"]
_HOME = "/home/nonroot"


def artifacts_dir() -> Path:
    env = os.environ.get("VYOMI_KUBESCAPE_ARTIFACTS")
    if env:
        return Path(env)
    try:
        from core.app_context import STATE_FILE
        base = Path(STATE_FILE).parent
    except Exception:
        base = Path.cwd()
    return base / "kubescape-artifacts" / ks.KUBESCAPE_VERSION


def _docker(args, *, input_bytes=None, timeout=60):
    return subprocess.run(["docker", *args], input=input_bytes, capture_output=True, timeout=timeout)


def _err(p) -> str:
    return (p.stderr or p.stdout or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [""]


def preflight() -> str | None:
    """None when a scan can run; otherwise the human reason it can't."""
    if not shutil.which("docker"):
        return "The docker CLI is not available to the appliance, so the Kubescape scanner container cannot run"
    try:
        p = _docker(["version", "--format", "{{.Server.Version}}"], timeout=15)
    except Exception as e:
        return f"Docker is not reachable ({type(e).__name__})"
    if p.returncode != 0:
        return "Docker daemon is not reachable: " + _err(p)[0]
    p = _docker(["image", "inspect", ks.IMAGE], timeout=20)
    if p.returncode != 0:
        pull = _docker(["pull", ks.IMAGE], timeout=600)
        if pull.returncode != 0:
            return f"The Kubescape image {ks.IMAGE} is not present and could not be pulled: " + _err(pull)[0]
    if not _ensure_artifacts():
        return ("The Kubescape framework artifacts are not in the appliance data dir and could not be "
                "downloaded (one-time, needs network): " + (_LAST_ARTIFACT_ERR or "unknown error"))
    return None


_LAST_ARTIFACT_ERR = ""
_ARTIFACTS = ["nsa.json", "mitre.json", "cis-v1.12.0.json", "controls-inputs.json", "exceptions.json", "attack-tracks.json"]


def _ensure_artifacts() -> bool:
    global _LAST_ARTIFACT_ERR
    d = artifacts_dir()
    if all((d / f).is_file() for f in _ARTIFACTS):
        return True
    name = f"vyomi-ks-download-{uuid.uuid4().hex[:8]}"
    try:
        p = _docker(["create", "--name", name, *sum((["-e", e] for e in _ENV if not e.startswith("KS_OFFLINE")), []),
                     ks.IMAGE, "download", "artifacts", "--output", f"{_HOME}/artifacts"], timeout=60)
        if p.returncode != 0:
            _LAST_ARTIFACT_ERR = _err(p)[0]
            return False
        p = _docker(["start", "-a", name], timeout=300)
        if p.returncode != 0:
            _LAST_ARTIFACT_ERR = _err(p)[0]
            return False
        p = _docker(["cp", f"{name}:{_HOME}/artifacts", "-"], timeout=120)
        if p.returncode != 0:
            _LAST_ARTIFACT_ERR = _err(p)[0]
            return False
        d.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(p.stdout)) as tf:
            for m in tf.getmembers():
                base = os.path.basename(m.name)
                if m.isfile() and base.endswith(".json") and "/" not in base:
                    (d / base).write_bytes(tf.extractfile(m).read())
        return all((d / f).is_file() for f in _ARTIFACTS)
    except Exception as e:
        _LAST_ARTIFACT_ERR = f"{type(e).__name__}: {e}"
        return False
    finally:
        _docker(["rm", "-f", name], timeout=30)


def _tar(files: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for dname in ("scan", "artifacts", "out"):
            ti = tarfile.TarInfo(dname); ti.type = tarfile.DIRTYPE; ti.mode = 0o777
            ti.uid = ti.gid = 65532; ti.mtime = int(time.time())
            tf.addfile(ti)
        for path, data in files.items():
            ti = tarfile.TarInfo(path); ti.size = len(data); ti.mode = 0o644
            ti.uid = ti.gid = 65532; ti.mtime = int(time.time())
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


_REAPED = False


def _reap_orphans() -> None:
    """Once per process: remove scan containers a previous appliance process left behind when it
    was stopped mid-scan (its `finally: docker rm -f` never ran)."""
    global _REAPED
    if _REAPED:
        return
    _REAPED = True
    try:
        p = _docker(["ps", "-aq", "--filter", "name=^vyomi-ks-scan-", "--filter", "name=^vyomi-ks-download-"], timeout=20)
        ids = p.stdout.decode().split()
        if ids:
            _docker(["rm", "-f", *ids], timeout=60)
    except Exception:
        pass


def scan_objects(objects: list) -> tuple[dict | None, str]:
    """Run one Kubescape scan over `objects` -> (report json, "") or (None, reason)."""
    reason = preflight()
    if reason:
        return None, "unavailable:" + reason
    _reap_orphans()
    if not objects:
        objects = []
    manifest = "".join("---\n" + k8s_yaml.dump(o) for o in objects) or "---\n"
    files = {"scan/objects.yaml": manifest.encode()}
    for name in _ARTIFACTS:
        files[f"artifacts/{name}"] = (artifacts_dir() / name).read_bytes()
    name = f"vyomi-ks-scan-{uuid.uuid4().hex[:10]}"
    try:
        p = _docker(["create", "--name", name, "--network", "none", *sum((["-e", e] for e in _ENV), []),
                     ks.IMAGE, "scan", "framework", ",".join(ks.FRAMEWORKS), f"{_HOME}/scan",
                     "--use-artifacts-from", f"{_HOME}/artifacts", "--format", "json",
                     "--output", f"{_HOME}/out/results.json", "--submit=false", "--keep-local"], timeout=60)
        if p.returncode != 0:
            return None, "failed:Could not create the Kubescape container: " + _err(p)[0]
        p = _docker(["cp", "-", f"{name}:{_HOME}"], input_bytes=_tar(files), timeout=60)
        if p.returncode != 0:
            return None, "failed:Could not copy the cluster objects into the Kubescape container: " + _err(p)[0]
        p = _docker(["start", "-a", name], timeout=SCAN_TIMEOUT_S)
        out = _docker(["cp", f"{name}:{_HOME}/out/results.json", "-"], timeout=60)
        if out.returncode != 0:
            return None, "failed:Kubescape produced no report (exit %s): %s" % (p.returncode, _err(p)[0])
        with tarfile.open(fileobj=io.BytesIO(out.stdout)) as tf:
            m = next(m for m in tf.getmembers() if m.isfile())
            report = json.loads(tf.extractfile(m).read())
        return report, ""
    except subprocess.TimeoutExpired:
        return None, f"failed:The Kubescape scan timed out after {SCAN_TIMEOUT_S}s"
    except Exception as e:
        return None, f"failed:{type(e).__name__}: {e}"
    finally:
        _docker(["rm", "-f", name], timeout=30)


class OfflineScanner:
    """Debounced background scanner (one worker thread, latest-wins per cluster)."""
    engine = ENGINE

    def __init__(self, persist=None):
        self._lock = threading.Lock()
        self._pending: dict[str, tuple[float, dict]] = {}
        self._wake = threading.Event()
        self._persist = persist
        self._thread = None

    def request(self, rec: dict, rid: str, reason: str = "") -> None:
        ks.store_result(rec, "queued", engine=self.engine)   # creates the key on the request thread
        with self._lock:
            self._pending[rid.lower()] = (time.monotonic() + DEBOUNCE_S, rec)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="vyomi-kubescape", daemon=True)
                self._thread.start()
        self._wake.set()

    def _run(self):
        while True:
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            while True:
                with self._lock:
                    due = [(k, r) for k, (t, r) in self._pending.items() if t <= time.monotonic()]
                    for k, _ in due:
                        self._pending.pop(k, None)
                    idle = not self._pending
                if not due:
                    break
                for rid, rec in due:
                    self._scan(rec)
            if idle:
                with self._lock:
                    if not self._pending:
                        self._thread = None
                        return

    def _scan(self, rec: dict):
        for _ in range(3):                      # snapshot (a request thread may be mutating)
            try:
                v = k8s.version(rec)
                objects = json.loads(json.dumps(k8s.export_objects(rec)))
                break
            except RuntimeError:
                time.sleep(0.05)
        else:
            return
        ks.store_result(rec, "running", engine=self.engine, objects_version=v)
        report, why = scan_objects(objects)
        if report is not None:
            ks.store_result(rec, "succeeded", engine=self.engine, parsed=ks.parse_report(report, self.engine), objects_version=v)
        else:
            status, _, msg = why.partition(":")
            ks.store_result(rec, status, engine=self.engine, reason=msg, objects_version=v)
        if self._persist:
            try:
                self._persist()
            except Exception:
                pass

    def wait_idle(self, timeout: float = 300) -> bool:
        """Test helper: block until nothing is queued or scanning."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                busy = bool(self._pending) or (self._thread is not None and self._thread.is_alive())
            if not busy:
                return True
            time.sleep(0.2)
        return False


_INSTALLED: OfflineScanner | None = None


def install() -> OfflineScanner:
    """Register the offline scanner with the shared core (idempotent)."""
    global _INSTALLED
    if _INSTALLED is None:
        def _persist():
            from core.app_context import persist_state
            persist_state()
        _INSTALLED = OfflineScanner(persist=_persist)
    if ks.scanner() is not _INSTALLED:
        ks.set_scanner(_INSTALLED)
    return _INSTALLED
