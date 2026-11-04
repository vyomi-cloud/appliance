"""Offline appliance: real BuildKit + (opt-in) real Gitea behind the shared CI seam (core/ci_core.py).

* Builder: ``docker build`` (BuildKit) with the repo tree streamed as a tar context on stdin -- no bind mounts, works
  with the host docker socket. ``--pull=false``: only base images already on the host are used.
* Git host: Gitea, only when VYOMI_CI_GITEA=1 (a ~100MB image; default git host stays the in-state MemoryGit).
  Container ``vyomi-ci-gitea`` (override VYOMI_CI_GITEA_NAME), image pinned below, bound to 127.0.0.1:VYOMI_CI_GITEA_PORT
  (default 13000), data in a named docker volume. Admin user ``vyomi`` with a generated password kept in the data dir.
* Fetcher: urllib HTTPS, used only for the user's own GitHub PAT import.

Everything degrades honestly: no docker -> package builder; Gitea start failure -> MemoryGit (reason logged).
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from core import ci_core as ci

GITEA_IMAGE = "gitea/gitea:1.22.3-rootless"
GITEA_NAME = os.environ.get("VYOMI_CI_GITEA_NAME", "vyomi-ci-gitea")
GITEA_PORT = int(os.environ.get("VYOMI_CI_GITEA_PORT", "13000"))
GITEA_USER = "vyomi"
LAST_ERROR: str | None = None


def docker_run(argv, input_bytes, timeout):
    try:
        p = subprocess.run(argv, input=input_bytes, capture_output=True, timeout=timeout, env={**os.environ, "DOCKER_BUILDKIT": "1"})
        return p.returncode, (p.stdout or b"") + (p.stderr or b"")
    except FileNotFoundError:
        return 127, b"docker CLI not found"
    except subprocess.TimeoutExpired:
        return 124, b"timed out"


def http(method, url, headers, body):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 599, str(e).encode()


def fetcher(url, headers):
    return http("GET", url, headers, None)


def docker_available(run=docker_run) -> bool:
    rc, _ = run(["docker", "version", "--format", "{{.Server.Version}}"], None, 10)
    return rc == 0


def _data_dir() -> Path:
    try:
        from core.app_context import STATE_FILE
        return Path(STATE_FILE).parent
    except Exception:
        return Path.cwd()


def ensure_gitea(run=docker_run, http_fn=http, sleep=time.sleep, data_dir: Path | None = None):
    """Start (or reuse) the Gitea container and return a ready ci.GiteaGit, or raise RuntimeError with the reason."""
    d = data_dir or _data_dir()
    cred = d / "ci-gitea-admin.json"
    pw = json.loads(cred.read_text())["password"] if cred.exists() else secrets.token_urlsafe(18)
    rc, out = run(["docker", "ps", "-a", "--filter", f"name=^{GITEA_NAME}$", "--format", "{{.State}}"], None, 15)
    state = out.decode().strip() if rc == 0 else ""
    if rc != 0:
        raise RuntimeError("docker unavailable: " + out.decode(errors="replace")[:200])
    fresh = state == ""
    if fresh:
        rc, out = run(["docker", "run", "-d", "--name", GITEA_NAME, "-p", f"127.0.0.1:{GITEA_PORT}:3000", "-v", f"{GITEA_NAME}-data:/var/lib/gitea",
                       "-e", "GITEA__security__INSTALL_LOCK=true", "-e", f"GITEA__server__ROOT_URL=http://127.0.0.1:{GITEA_PORT}/",
                       "-e", "GITEA__server__DISABLE_SSH=true", "-e", "GITEA__service__DISABLE_REGISTRATION=true",
                       "-e", "GITEA__database__DB_TYPE=sqlite3", "-e", "GITEA__log__LEVEL=Warn", GITEA_IMAGE], None, 600)
        if rc != 0:
            raise RuntimeError("could not start Gitea: " + out.decode(errors="replace")[-300:])
    elif state != "running":
        run(["docker", "start", GITEA_NAME], None, 30)
    base = f"http://127.0.0.1:{GITEA_PORT}"
    for _ in range(60):
        st, _b = http_fn("GET", base + "/api/healthz", {}, None)
        if st == 200:
            break
        sleep(1)
    else:
        raise RuntimeError("Gitea did not become healthy")
    if fresh or not cred.exists():
        rc, out = run(["docker", "exec", GITEA_NAME, "gitea", "admin", "user", "create", "--admin", "--username", GITEA_USER, "--password", pw,
                       "--email", "ci@vyomi.local", "--must-change-password=false"], None, 60)
        if rc != 0 and b"already exists" not in out:
            raise RuntimeError("could not create Gitea admin: " + out.decode(errors="replace")[-300:])
        cred.write_text(json.dumps({"user": GITEA_USER, "password": pw}))
        try:
            os.chmod(cred, 0o600)
        except OSError:
            pass
    import base64
    hdr = {"Authorization": "Basic " + base64.b64encode(f"{GITEA_USER}:{pw}".encode()).decode(), "Content-Type": "application/json"}
    st, raw = http_fn("POST", f"{base}/api/v1/users/{GITEA_USER}/tokens", hdr,
                      json.dumps({"name": "vyomi-" + secrets.token_hex(3), "scopes": ["all"]}).encode())
    if st != 201:
        raise RuntimeError(f"could not mint a Gitea token (HTTP {st})")
    return ci.GiteaGit(base, GITEA_USER, json.loads(raw)["sha1"], http_fn)


_done = False


def install(run=docker_run):
    """Idempotent. Builder + fetcher always; Gitea only when VYOMI_CI_GITEA=1."""
    global _done, LAST_ERROR
    if _done:
        return ci.backends()
    _done = True
    ci.set_fetcher(fetcher)
    ci.set_http(http)
    try:
        if docker_available(run):
            ci.set_builder(ci.BuildKitBuilder(run))
        else:
            LAST_ERROR = "docker unavailable: builds are package-only"
    except Exception as e:
        LAST_ERROR = str(e)
    if os.environ.get("VYOMI_CI_GITEA") == "1":
        try:
            ci.set_git(ensure_gitea(run))
        except Exception as e:
            LAST_ERROR = "Gitea unavailable, using in-state git: " + str(e)
    return ci.backends()
