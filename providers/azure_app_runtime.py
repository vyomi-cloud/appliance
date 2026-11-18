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


def _start(app_id: str, revision: str, image: str, env: dict, port, command=None):
    sb = _sandbox_wanted(image, env)
    if sb:
        return _sandbox_start(app_id, revision, image, env, port, command or [])
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
    cmd += [str(a) for a in (command or [])]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode:
        return {"error": (p.stderr or p.stdout or "docker run failed").strip()[-300:]}
    host_port = None
    if port:
        q = subprocess.run(["docker", "port", name, str(int(port))], capture_output=True, text=True, timeout=20)
        m = re.search(r":(\d+)\s*$", q.stdout.strip().splitlines()[0]) if q.stdout.strip() else None
        host_port = int(m.group(1)) if m else None
    return {"id": name, "host": "127.0.0.1", "port": host_port, "network": net}


# ── sandboxed-process runtime for `vyomi/python-app` (no Docker needed) ────────────────────────────────────────────────
# A Container App whose image is vyomi/python-app*, or whose container env carries VYOMI_APP_SOURCE_B64 (a base64 zip, or one .py file),
# runs its Python HTTP server as a SANDBOXED SUBPROCESS: the same guard as the Cloud Functions runtime (core/gcp_function_runtime):
# scrubbed environment, sockets only to loopback + the simulator, filesystem confined to the app dir, no subprocess/exec. It is a
# guard-rail for trusted reference apps, NOT a container: no image layers, no cgroup limits, no exec, no hostile-code isolation.
# Every other image keeps using Docker (above). VYOMI_AZURE_APP_SANDBOX=off disables it.
SANDBOX_IMAGES = ("vyomi/python-app", "docker.io/vyomi/python-app")
SOURCE_ENV = "VYOMI_APP_SOURCE_B64"
_SB_ENTRIES = ("app.py", "main.py", "server.py")


def _sandbox_wanted(image, env) -> bool:
    if os.environ.get("VYOMI_AZURE_APP_SANDBOX", "on").lower() == "off" or os.sys.platform == "emscripten":
        return False
    im = str(image or "").lower()
    return im.startswith(SANDBOX_IMAGES) or bool((env or {}).get(SOURCE_ENV))


def _free_port(prefer=None):
    import socket
    for p in ([int(prefer)] if prefer else []) + [0]:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            port = s.getsockname()[1]
            return port
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError("no free port")


def _unpack_source(blob_b64: str, workdir: str) -> list:
    import base64, io, zipfile
    raw = base64.b64decode(blob_b64)
    names = []
    if zipfile.is_zipfile(io.BytesIO(raw)):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            for n in z.namelist():
                dest = os.path.normpath(os.path.join(workdir, n))
                if n.endswith("/") or not dest.startswith(workdir + os.sep):
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as fh:
                    fh.write(z.read(n))
                names.append(n)
    else:
        with open(os.path.join(workdir, "app.py"), "wb") as fh:
            fh.write(raw)
        names.append("app.py")
    return names


def _sandbox_cfg(command, files, env):
    """How to run it: python -c CODE | python -m MOD | python FILE [args] | (no command) VYOMI_APP_ENTRY / app.py / main.py / server.py."""
    cmd = [str(c) for c in command]
    if cmd and os.path.basename(cmd[0]) in ("python", "python3", "python3.13", "python3.12", "python3.11"):
        cmd = cmd[1:]
    if cmd and cmd[0] == "-c" and len(cmd) > 1:
        return {"mode": "code", "code": cmd[1], "argv": ["-c"] + cmd[2:]}
    if cmd and cmd[0] == "-m" and len(cmd) > 1:
        return {"mode": "module", "target": cmd[1], "argv": [cmd[1]] + cmd[2:]}
    if cmd and cmd[0].endswith(".py"):
        return {"mode": "file", "target": cmd[0], "argv": cmd}
    entry = (env or {}).get("VYOMI_APP_ENTRY") or next((e for e in _SB_ENTRIES if e in files), None)
    if not entry:
        return None
    return {"mode": "file", "target": entry, "argv": [entry]}


_LAUNCH = r"""
import json, os, sys, runpy
wd = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(wd, "_cfg.json")))
sys.path.insert(0, wd)
import _guard
_guard._install_guard(dict(cfg["sandbox"], workdir=wd))
for _k in ("GCE_METADATA_HOST", "GCE_METADATA_IP"):
    os.environ.pop(_k, None)
sys.argv = cfg["argv"]
if cfg["mode"] == "code":
    exec(compile(cfg["code"], "<command>", "exec"), {"__name__": "__main__"})
elif cfg["mode"] == "module":
    runpy.run_module(cfg["target"], run_name="__main__", alter_sys=True)
else:
    runpy.run_path(os.path.join(wd, cfg["target"]), run_name="__main__")
"""


def _sandbox_start(app_id, revision, image, env, port, command):
    import json, tempfile, time as _t
    from core import gcp_function_runtime as fr
    app_name = app_id.rstrip("/").rsplit("/", 1)[-1]
    workdir = os.path.realpath(tempfile.mkdtemp(prefix="vyomi-ca-"))
    try:
        env = dict(env or {})
        files = _unpack_source(env.pop(SOURCE_ENV), workdir) if env.get(SOURCE_ENV) else []
        cfg = _sandbox_cfg(command, files, env)
        if cfg is None:
            shutil.rmtree(workdir, ignore_errors=True)
            return {"error": "vyomi/python-app has nothing to run: give the container a command (python -c ... / python app.py) "
                             f"and/or a source bundle in the {SOURCE_ENV} env var (base64 zip or single .py; entry app.py|main.py|server.py or VYOMI_APP_ENTRY)."}
        listen = _free_port(port)
        simulator = os.environ.get("VYOMI_SELF_URL") or os.environ.get("VYOMI_SELF_ENDPOINT") or fr.self_url("")
        run_env = {"PORT": str(listen), "WEBSITES_PORT": str(listen), "CONTAINER_APP_NAME": app_name, "CONTAINER_APP_REVISION": revision,
                   "CONTAINER_APP_REPLICA_NAME": revision + "-0", "CONTAINER_APP_HOSTNAME": revision,
                   "CONTAINER_APP_RESOURCE_ID": app_id, "VYOMI_ENDPOINT": simulator, "VYOMI_RUNTIME": "sandbox"}
        run_env.update({k: ("" if v is None else str(v)) for k, v in env.items() if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k))})
        e = fr._sandbox_env(run_env, workdir)
        os.makedirs(os.path.join(workdir, fr.SANDBOX_HOME), exist_ok=True)
        ident = {"sub": "sandbox", "email": "sandbox@vyomi.local", "project": app_name, "number": "0", "region": "local",
                 "instance_id": revision, "hostname": revision, "scopes": [], "token": "vyomi-local"}
        cfg["sandbox"] = {"hosts": fr._hosts(e), "identity": ident}
        with open(os.path.join(workdir, "_guard.py"), "w") as fh:
            fh.write(fr._GUARD_SRC)
        with open(os.path.join(workdir, "_launch.py"), "w") as fh:
            fh.write(_LAUNCH)
        with open(os.path.join(workdir, "_cfg.json"), "w") as fh:
            json.dump(cfg, fh)
        logp = os.path.join(workdir, "console.log")
        out = open(logp, "ab")
        import sys as _sys
        proc = subprocess.Popen([_sys.executable, "-B", os.path.join(workdir, "_launch.py")], cwd=workdir, env=e, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True)
        out.close()
        handle = {"id": f"sandbox-{proc.pid}", "kind": "sandbox", "host": "127.0.0.1", "port": listen, "pid": proc.pid, "workdir": workdir,
                  "log": logp, "image": image, "_spec": [app_id, revision, image, env, port, command]}
        _SB_PROCS[proc.pid] = proc
        # Do NOT wait for the port here: this runs inside the ARM request, on the simulator's event loop, and the app may call the simulator
        # while it starts. Only catch an immediate crash (syntax / import error); the ingress proxy waits for the port when a request arrives.
        t0 = _t.time()
        while _t.time() - t0 < 2.0 and proc.poll() is None:
            _t.sleep(0.1)
        if proc.poll() is not None:
            tail = _sandbox_logs(handle, 30)
            _sandbox_stop(handle)
            return {"error": "the app exited at start-up (exit code %s): %s" % (proc.returncode, tail[-300:])}
        return handle
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(workdir, ignore_errors=True)
        return {"error": f"sandbox start failed: {exc}"}


_SB_PROCS: dict = {}


def _sandbox_alive(handle) -> bool:
    proc = _SB_PROCS.get(handle.get("pid"))
    if proc is not None:
        return proc.poll() is None
    try:
        os.kill(int(handle["pid"]), 0)       # a process from before this simulator restart (no Popen object)
        return True
    except Exception:
        return False


def _port_open(handle) -> bool:
    import socket
    try:
        socket.create_connection((handle.get("host", "127.0.0.1"), int(handle["port"])), timeout=0.3).close()
        return True
    except OSError:
        return False


def _sandbox_status(handle) -> str:
    if not _sandbox_alive(handle):
        return "NotRunning"
    return "Running" if _port_open(handle) else "Activating"


def _sandbox_stop(handle) -> None:
    import signal
    pid = handle.get("pid")
    proc = _SB_PROCS.pop(pid, None)
    try:
        if pid:
            os.killpg(int(pid), signal.SIGTERM)
        if proc is not None:
            try:
                proc.wait(timeout=5)
            except Exception:
                os.killpg(int(pid), signal.SIGKILL)
    except Exception:
        pass
    wd = handle.get("workdir")
    if wd and os.path.basename(wd).startswith("vyomi-ca-"):
        shutil.rmtree(wd, ignore_errors=True)


def _sandbox_logs(handle, tail=200) -> str:
    try:
        with open(handle["log"], "rb") as fh:
            return "\n".join(fh.read().decode("utf-8", "replace").splitlines()[-int(tail):])
    except OSError:
        return ""


def _sandbox_restart(handle) -> None:
    spec = handle.get("_spec")
    _sandbox_stop(handle)
    h = _sandbox_start(*spec)
    if h.get("error"):
        raise RuntimeError(h["error"])
    handle.clear()
    handle.update(h)


def _sandbox_stats(handle) -> dict:
    p = subprocess.run(["ps", "-o", "rss=,pcpu=", "-p", str(handle.get("pid"))], capture_output=True, text=True, timeout=10)
    parts = p.stdout.split()
    return {"cpuPercent": (parts[1] + "%") if len(parts) > 1 else None, "memoryUsage": (str(int(parts[0]) // 1024) + "MiB") if parts else None,
            "memoryPercent": None, "netIO": None, "pids": 1}


def _status(handle) -> str:
    """Real replica state from the container, not a constant."""
    if handle.get("kind") == "sandbox":
        return _sandbox_status(handle)
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
    if handle and handle.get("kind") == "sandbox":
        return _sandbox_stop(handle)
    if handle and handle.get("id"):
        subprocess.run(["docker", "rm", "-f", handle["id"]], capture_output=True, timeout=60)


def _logs(handle, tail=200) -> str:
    if handle.get("kind") == "sandbox":
        return _sandbox_logs(handle, tail)
    p = subprocess.run(["docker", "logs", "--tail", str(int(tail)), handle["id"]], capture_output=True, text=True, timeout=30)
    return (p.stdout or "") + (p.stderr or "")


def _exec(handle, argv, timeout=20):
    """`docker exec` into the replica's container; returns (exit code, combined output)."""
    if handle.get("kind") == "sandbox":
        return 126, "exec is not available in the sandboxed-process runtime (a replica of a vyomi/python-app is a sandboxed Python process, not a container)"
    try:
        p = subprocess.run(["docker", "exec", handle["id"], *[str(a) for a in argv]], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"command timed out after {timeout}s"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _restart(handle) -> None:
    if handle.get("kind") == "sandbox":
        return _sandbox_restart(handle)
    p = subprocess.run(["docker", "restart", handle["id"]], capture_output=True, text=True, timeout=60)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip()[-200:])


def _stats(handle) -> dict:
    if handle.get("kind") == "sandbox":
        return _sandbox_stats(handle)
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


_start.wants_command = True        # core passes command + args (the sandbox runs `python -c ...` / a script from them)


def attach() -> None:
    core.configure_runtime(_start, _stop, _status, logs=_logs, exec=_exec, restart=_restart, stats=_stats, run_once=_run_once)
