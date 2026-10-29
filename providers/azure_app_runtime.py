"""Docker runtime for Azure Container Apps on the offline appliance (Pro / Max tiers).

core/azure_app_core.py is substrate-free; here the appliance plugs in the existing Docker
compute backend so each active revision's image really runs (`docker run`) and stops when the
revision is deactivated, the app is stopped or deleted. Free/Lite tiers (and hosts without
Docker) keep the service control-plane only — the engine reports the same replicas either way.

VYOMI_AZURE_APP_RUNTIME = auto (default: Pro/Max tier + a working docker CLI) | docker | off
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess

from core import azure_app_core as core

PAID_TIERS = {"pro", "max", "developer", "enterprise"}


def _enabled() -> bool:
    mode = os.environ.get("VYOMI_AZURE_APP_RUNTIME", "auto").lower()
    if mode == "off" or not shutil.which("docker"):
        return False
    if mode == "docker":
        return True
    try:
        from core.app_context import active_tier
        return active_tier().lower() in PAID_TIERS
    except Exception:
        return False


def _start(app_id: str, revision: str, image: str, env: dict, port):
    if not _enabled():
        return None
    name = "vyomi-ca-" + hashlib.sha1(f"{app_id}/{revision}".encode()).hexdigest()[:12]
    cmd = ["docker", "run", "-d", "--name", name, "--label", "vyomi.azure.app=" + app_id, "--memory", "512m"]
    for k, v in (env or {}).items():
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)):
            cmd += ["-e", f"{k}={v if v is not None else ''}"]
    if port:
        cmd += ["-p", f"127.0.0.1::{int(port)}"]
    cmd.append(image)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode:
        return None
    host_port = None
    if port:
        q = subprocess.run(["docker", "port", name, str(int(port))], capture_output=True, text=True, timeout=20)
        m = re.search(r":(\d+)\s*$", q.stdout.strip().splitlines()[0]) if q.stdout.strip() else None
        host_port = int(m.group(1)) if m else None
    return {"id": name, "host": "127.0.0.1", "port": host_port}


def _stop(handle) -> None:
    if handle and handle.get("id"):
        subprocess.run(["docker", "rm", "-f", handle["id"]], capture_output=True, timeout=60)


def attach() -> None:
    core.configure_runtime(_start, _stop)
