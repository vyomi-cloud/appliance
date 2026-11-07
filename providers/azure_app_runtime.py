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
    # Docker compute backend (the appliance default): every VM/app is a real sibling container
    if (os.environ.get("VYOMI_COMPUTE_BACKEND") or os.environ.get("CLOUDLEARN_COMPUTE_BACKEND") or "").lower() == "docker":
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
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)   # idempotent re-sync
    cmd = ["docker", "run", "-d", "--name", name, "--label", "vyomi.azure.app=" + app_id, "--memory", "512m"]
    net = os.environ.get("VYOMI_INSTANCE_NETWORK")
    if net:
        cmd += ["--network", net, "--network-alias", app_id.rstrip("/").rsplit("/", 1)[-1].lower()]
    for k, v in (env or {}).items():
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)):
            cmd += ["-e", f"{k}={v if v is not None else ''}"]
    if port:
        cmd += ["-p", f"127.0.0.1::{int(port)}"]
    cmd.append(image)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode:
        return {"error": (p.stderr or p.stdout or "docker run failed").strip()[-300:]}
    host_port = None
    if port:
        q = subprocess.run(["docker", "port", name, str(int(port))], capture_output=True, text=True, timeout=20)
        m = re.search(r":(\d+)\s*$", q.stdout.strip().splitlines()[0]) if q.stdout.strip() else None
        host_port = int(m.group(1)) if m else None
    return {"id": name, "host": "127.0.0.1", "port": host_port, "network": net}


def _status(handle) -> str:
    """Real replica state from the container, not a constant."""
    p = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", handle["id"]], capture_output=True, text=True, timeout=20)
    st = p.stdout.strip()
    return {"running": "Running", "restarting": "Activating", "created": "Activating", "paused": "NotRunning",
            "exited": "NotRunning", "dead": "NotRunning"}.get(st, "NotRunning" if p.returncode else "Running")


def deprovision_container_app(record: dict) -> None:
    """Remove every container backing a Container App record. Idempotent. Call this before
    dropping the record (e.g. from a resource-group cascade)."""
    if isinstance(record, dict) and str(record.get("_type", "")).lower().endswith("/containerapps"):
        core._stop_runtime(record)
        app_id = str(record.get("id", ""))
        if app_id and shutil.which("docker"):      # also catch containers whose handle was lost (restart)
            ids = subprocess.run(["docker", "ps", "-aq", "--filter", f"label=vyomi.azure.app={app_id}"],
                                 capture_output=True, text=True, timeout=30).stdout.split()
            if ids:
                subprocess.run(["docker", "rm", "-f", *ids], capture_output=True, timeout=60)


def _stop(handle) -> None:
    if handle and handle.get("id"):
        subprocess.run(["docker", "rm", "-f", handle["id"]], capture_output=True, timeout=60)


def _logs(handle, tail=200) -> str:
    p = subprocess.run(["docker", "logs", "--tail", str(int(tail)), handle["id"]], capture_output=True, text=True, timeout=30)
    return (p.stdout or "") + (p.stderr or "")


def _exec(handle, argv, timeout=20):
    """`docker exec` into the replica's container; returns (exit code, combined output)."""
    try:
        p = subprocess.run(["docker", "exec", handle["id"], *[str(a) for a in argv]], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"command timed out after {timeout}s"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _restart(handle) -> None:
    p = subprocess.run(["docker", "restart", handle["id"]], capture_output=True, text=True, timeout=60)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip()[-200:])


def _stats(handle) -> dict:
    p = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", handle["id"]], capture_output=True, text=True, timeout=30)
    import json
    d = json.loads(p.stdout.strip().splitlines()[0]) if p.stdout.strip() else {}
    return {"cpuPercent": d.get("CPUPerc"), "memoryUsage": d.get("MemUsage"), "memoryPercent": d.get("MemPerc"), "netIO": d.get("NetIO"), "pids": d.get("PIDs")}


def _run_once(image, argv, env, timeout=1800):
    """A one-shot container for a Container Apps Job execution (docker run --rm)."""
    if not _enabled():
        raise RuntimeError("container runtime disabled")
    cmd = ["docker", "run", "--rm", "--memory", "512m", "--label", "vyomi.azure.job=1"]
    for k, v in (env or {}).items():
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)):
            cmd += ["-e", f"{k}={v if v is not None else ''}"]
    cmd.append(image)
    cmd += [str(a) for a in (argv or [])]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=min(int(timeout), 600))
    except subprocess.TimeoutExpired:
        return 124, "execution timed out"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def attach() -> None:
    core.configure_runtime(_start, _stop, _status, logs=_logs, exec=_exec, restart=_restart, stats=_stats, run_once=_run_once)
