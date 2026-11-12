"""One-shot container runner for REAL task execution (Azure Tasks, offline appliance only).

``run(image, command, env, timeout)`` executes ``sh -c <command>`` in a throw-away Docker container and returns the real exit code,
the captured output and the duration. Guard rails (a task script is user-supplied code): the image must already exist locally
(``--pull never``, nothing is fetched), no network (``--network none``), read-only root filesystem with a small tmpfs, 256 MB memory,
half a CPU, 128 processes, all capabilities dropped, a hard wall-clock timeout that kills the container.

Not importable in Nano (no subprocess/Docker in the browser): the caller treats ImportError / available() == False as 'no engine'.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
import uuid

_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/:@-]{0,199}$")
MAX_LOG = 16000


def available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=10).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def image_present(image: str) -> bool:
    try:
        return subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=15).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def run(image: str, command: str, env: dict | None = None, timeout: int = 60, stdin: bytes | None = None, tmpfs_mb: int = 32, memory_mb: int = 256) -> dict:
    if not _IMAGE.match(image or ""):
        return {"error": "InvalidImage", "message": f"'{image}' is not a valid image reference."}
    if not image_present(image):
        return {"error": "ImageNotFound", "message": f"Image '{image}' is not present on this host. Tasks never pull images; pull it first (docker pull {image})."}
    timeout = max(1, min(int(timeout or 60), 600))
    name = f"vyomi-task-{uuid.uuid4().hex[:10]}"
    args = ["docker", "run", "--rm"] + (["-i"] if stdin is not None else []) + [ "--name", name, "--pull", "never", "--network", "none", "--read-only", "--tmpfs", f"/tmp:rw,size={int(tmpfs_mb)}m",
            "--memory", f"{int(memory_mb)}m", "--cpus", "0.5", "--pids-limit", "128", "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    for k, v in (env or {}).items():
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)):
            args += ["-e", f"{k}={v}"]
    args += ["--entrypoint", "sh", image, "-c", command]
    t0 = time.time()
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout, input=stdin)
        out = (p.stdout + p.stderr).decode("utf-8", "replace")
        return {"exitCode": p.returncode, "logs": out[-MAX_LOG:], "durationMs": int((time.time() - t0) * 1000), "image": image}
    except subprocess.TimeoutExpired as e:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        out = ((e.stdout or b"") + (e.stderr or b"")).decode("utf-8", "replace")
        return {"exitCode": 124, "logs": out[-MAX_LOG:] + f"\n[killed after {timeout}s]", "durationMs": int((time.time() - t0) * 1000), "image": image, "timedOut": True}
