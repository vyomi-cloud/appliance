"""Vyomi Nano: container-ish workloads and guest data planes on the in-browser VM (v86 Alpine).

Nano has no Docker daemon, and a browser tab cannot run one. What it does have (when the user turns in-browser VMs on,
localStorage nano_vm_compute=1) is a real Linux VM per EC2 / Compute Engine / Azure VM record, reachable through
wasm/vm/nano-vm-host.js. This module maps these offline-only data planes onto that VM, honestly:

  * Azure Container Apps: a replica "container" is a PROCESS started inside a running in-browser VM from the container's
    command/args (nohup, env exported, stdout/stderr -> a log file). Log stream / Console / Events / Diagnose / metrics /
    environment logs read that process; job executions are one-shot commands whose exit code decides Succeeded/Failed.
    The container IMAGE is never pulled or run (no docker daemon, no OCI runtime in the VM): an app without
    command/args is reported as failed to start, and the image name is only recorded.
  * Azure VM guest views (Inventory / Update Manager / Performance diagnostics): the same scripts the appliance runs,
    executed in the VM (guest_command / guest_parse).
  * AWS Systems Manager Session Manager: running in-browser EC2 VMs register as managed nodes and sessions run a
    command-at-a-time shell in the VM (ssm_op / ssm_target). The ssmmessages data channel is not served.

The engines call these hooks SYNCHRONOUSLY (Pyodide, inside one dispatch) while a VM answers asynchronously. So a hook that
needs the VM raises NeedVm (a BaseException, so no engine `except Exception` can swallow it) after queueing the script;
the page (nano-boot.js) runs the queued scripts in the VM, stores the results (set_result) and re-dispatches the SAME request.
Hooks only raise before the engine mutates anything, so the replay is exact. Launching a replica is fire-and-forget (queued in
`post`, run after the dispatch). Without a running VM every hook reports control-plane-only, never invented output.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex

SOURCE = "nano-vm"
NO_VM_NOTE = ("Nano runs container workloads as processes inside an in-browser VM. Turn on in-browser VMs "
              "(localStorage.nano_vm_compute = '1' or open the console with ?nano_vm=1) and launch a virtual machine "
              "(Azure VM or EC2 instance), then start the container app again. There is no Docker daemon in a browser tab, "
              "so the container image itself is never pulled or run.")
IMAGE_NOTE = ("the image is not pulled or run (no Docker daemon in the in-browser VM); the container's command/args run as a "
              "process in the VM instead")
ROOT = "/var/vyomi-ca"


class NeedVm(BaseException):
    """Raised by a hook that needs a VM answer it does not have yet; the page runs the queued scripts and replays the request."""


_S = {"results": {}, "need": [], "post": []}
BRIDGE = {"host": None, "running": None}      # set by attach(): host() -> {"id","cloud","ref"} | None ; running(cloud) -> [{ref,name,ip}]


def _host():
    try:
        h = BRIDGE["host"]() if BRIDGE["host"] else None
    except Exception:
        h = None
    return h if h and h.get("id") else None


def ready() -> bool:
    return _host() is not None


def begin() -> None:
    """Start of a top-level dispatch: forget previous results/queues."""
    _S["results"].clear(); _S["need"].clear(); _S["post"].clear()


def take_need() -> list:
    out = list(_S["need"]); _S["need"].clear()
    return out


def take_post() -> list:
    out = list(_S["post"]); _S["post"].clear()
    return out


def set_result(key: str, result_json: str) -> None:
    _S["results"][key] = json.loads(result_json)


def _key(vm, script):
    return hashlib.sha1((vm + "\0" + script).encode()).hexdigest()[:20]


def run(script: str, timeout: int = 20, vm: str | None = None):
    """Run `script` (sh) in the VM and return (exit_code, output). Raises NeedVm until the page has the answer."""
    h = _host() if vm is None else {"id": vm}
    if not h:
        raise RuntimeError("no running in-browser VM")
    k = _key(h["id"], script)
    r = _S["results"].get(k)
    if r is None:
        _S["need"].append({"key": k, "vm": h["id"], "script": script, "timeout_ms": int(timeout) * 1000 + 5000})
        raise NeedVm(k)
    if r.get("error"):
        raise RuntimeError(str(r["error"])[:300])
    return int(r.get("exit_code", 1)), str(r.get("stdout") or "")


def _post(script: str, vm: str) -> None:
    _S["post"].append({"vm": vm, "script": script, "timeout_ms": 30000})


# ── Container Apps replicas as VM processes ──────────────────────────────────────────────────
def _cid(app_id, revision):
    return "nano-ca-" + hashlib.sha1(f"{app_id}/{revision}".encode()).hexdigest()[:12]


def _q(s):
    return shlex.quote(str(s))


def _env_lines(env):
    return "".join(f"export {k}={_q(v if v is not None else '')}\n" for k, v in (env or {}).items() if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)))


def _launch(cid):
    return _LAUNCH.replace("{root}", ROOT).replace("{cid}", cid)


_LAUNCH = ("export D={root}/{cid}; kill $(cat $D/pid 2>/dev/null) 2>/dev/null; rm -f $D/rc $D/pid; "
           "( nohup sh -c 'sh $D/run.sh; echo $? > $D/rc' >$D/log 2>&1 </dev/null & echo $! > $D/pid ); echo launched")


def _start(app_id, revision, image, env, port, command=None):
    h = _host()
    if not h:
        return None                                     # control plane only (the engine records the note)
    if not command:
        return {"error": f"Cannot start container image '{image}': {IMAGE_NOTE}. Set the container's command (and args) "
                         "so Nano has a process to run."}
    cid = _cid(app_id, revision)
    d = f"{ROOT}/{cid}"
    run_sh = ". " + d + "/env\ncd /\nexec " + " ".join(_q(a) for a in command) + "\n"
    setup = (f"mkdir -p {d}; cat > {d}/env <<'VYOMI_EOF'\n{_env_lines(env)}VYOMI_EOF\n"
             f"cat > {d}/run.sh <<'VYOMI_EOF'\n{run_sh}VYOMI_EOF\n") + _launch(cid)
    _post(setup, h["id"])
    return {"id": cid, "vm": h["id"], "backend": SOURCE, "port": None, "host": None, "image": image, "command": list(command)}


def _vmof(handle):
    return handle.get("vm") or None


def _status(handle) -> str:
    d = f"{ROOT}/{handle['id']}"
    rc, out = run(f"if [ -f {d}/rc ]; then echo exited; elif [ -f {d}/pid ] && kill -0 $(cat {d}/pid) 2>/dev/null; then echo running; else echo gone; fi",
                  5, _vmof(handle))
    return "Running" if out.strip().endswith("running") else "NotRunning"


def _stop(handle) -> None:
    if handle and handle.get("id") and handle.get("vm"):
        d = f"{ROOT}/{handle['id']}"
        _post(f"P=$(cat {d}/pid 2>/dev/null); if [ -n \"$P\" ]; then pkill -P $P 2>/dev/null; kill $P 2>/dev/null; fi; rm -rf {d}", handle["vm"])


def _logs(handle, tail=200) -> str:
    d = f"{ROOT}/{handle['id']}"
    rc, out = run(f"tail -n {int(tail)} {d}/log 2>/dev/null; [ -f {d}/rc ] && echo \"[vyomi] process exited with code $(cat {d}/rc)\"; true", 10, _vmof(handle))
    return out


def _exec(handle, argv, timeout=20):
    d = f"{ROOT}/{handle['id']}"
    cmd = " ".join(_q(a) for a in argv)
    try:
        rc, out = run(f"( . {d}/env 2>/dev/null; cd /; {cmd} ) 2>&1", timeout, _vmof(handle))
    except RuntimeError as e:
        return 124 if "timed out" in str(e) else 125, str(e)
    return rc, out


def _restart(handle) -> None:
    run(_launch(handle["id"]), 10, _vmof(handle))


def _stats(handle) -> dict:
    d = f"{ROOT}/{handle['id']}"
    rc, out = run(f"P=$(cat {d}/pid 2>/dev/null); echo \"pid=$P\"; "
                  f"for p in $P $(pgrep -P $P 2>/dev/null); do awk '/VmRSS/{{print \"rss=\"$2}}' /proc/$p/status 2>/dev/null; done; "
                  "awk '/MemTotal/{print \"total=\"$2}' /proc/meminfo; cat /proc/loadavg", 10, _vmof(handle))
    rss = sum(int(m) for m in re.findall(r"rss=(\d+)", out)); tot = re.search(r"total=(\d+)", out)
    load = out.strip().splitlines()[-1].split()[:3] if out.strip() else []
    return {"cpuPercent": None, "memoryUsage": f"{rss} KiB", "memoryPercent": round(100.0 * rss / int(tot.group(1)), 2) if tot and tot.group(1) != "0" else None,
            "netIO": None, "pids": len(re.findall(r"rss=", out)), "loadAvg": load,
            "note": "CPU percent is not sampled by Nano; memory is the process tree's resident set inside the VM."}


def _run_once(image, argv, env, timeout=1800):
    h = _host()
    if not h:
        raise RuntimeError("no running in-browser VM")
    if not argv:
        return 125, f"[vyomi nano] image '{image}': {IMAGE_NOTE}. This job has no command/args, so nothing was run."
    script = "(\n" + _env_lines(env) + "cd /\n" + " ".join(_q(a) for a in argv) + "\n) 2>&1"
    rc, out = run(script, min(int(timeout), 600), h["id"])
    return rc, f"[vyomi nano] image '{image}' is not pulled; ran the command in VM {h['id']}\n" + out


_start.wants_command = True


def attach(host, running=None) -> None:
    """Plug the VM runtime into Azure Container Apps. host() -> {"id","cloud","ref"} | None (sync); running(cloud) -> [{ref,name,ip}]."""
    from core import azure_app_core as core
    BRIDGE["host"], BRIDGE["running"] = host, running
    core.configure_runtime(_start, _stop, _status, logs=_logs, exec=_exec, restart=_restart, stats=_stats, run_once=_run_once,
                           ready=ready, source=SOURCE, note=NO_VM_NOTE)
    try:
        from core import ssm_core
        ssm_core.INSTANCE_PROVIDER = ssm_instances
    except Exception:
        pass


# ── Azure VM guest views ─────────────────────────────────────────────────────────────────────
def guest_command(kind: str, body_json: str = "{}") -> str:
    from core import ssh_access_core as sa
    b = json.loads(body_json or "{}")
    if kind == "inventory":
        return sa.INVENTORY_CMD
    if kind == "performance":
        return sa.PERF_CMD
    if kind == "updates":
        return sa.updates_command(bool(b.get("refresh")), bool(b.get("install")))
    raise ValueError("unknown guest view " + kind)


def guest_parse(kind: str, out: str) -> str:
    from core import ssh_access_core as sa
    base = {"ok": True, "source": "guest (nano in-browser VM)"}
    if kind == "inventory":
        return json.dumps({**base, **sa.parse_inventory(out)})
    if kind == "performance":
        import time
        return json.dumps({**base, "sampledAt": time.time(), **sa.parse_perf(out)})
    return json.dumps({**base, **sa.parse_updates(out)})


# ── AWS SSM Session Manager ───────────────────────────────────────────────────────────────────
def ssm_instances() -> dict:
    out = {}
    try:
        for r in (BRIDGE["running"]("aws") if BRIDGE["running"] else []) or []:
            out[r["ref"]] = {"state": "running", "az": r.get("az") or "", "ip": r.get("ip") or "", "name": r.get("name") or r["ref"]}
    except Exception:
        pass
    return out


def ssm_op(op: str, body_json: str = "{}") -> str:
    """Console session endpoints (/api/ssm/sessions...): Start / List / Terminate against the shared ssh_access store."""
    from core import ssh_access_core as sa
    b = json.loads(body_json or "{}")
    ss = sa.shared_store()
    try:
        if op == "Start":
            return json.dumps({"ok": True, **sa.start_session(ss, {"Target": b.get("target"), "DocumentName": b.get("document")}, ssm_instances())})
        if op == "List":
            return json.dumps(sa.describe_sessions(ss, {"State": b.get("state") or "Active"}))
        if op == "Terminate":
            return json.dumps({"ok": True, **sa.terminate_session(ss, {"SessionId": b.get("session_id")})})
        if op == "Target":
            s = ss.sessions.get(b.get("session_id"))
            if not s or s.get("Status") != "Connected":
                return json.dumps({"ok": False, "status": 404, "detail": "SessionNotFound"})
            return json.dumps({"ok": True, "target": s["Target"]})
    except sa.SshAccessError as e:
        return json.dumps({"ok": False, "status": e.status, "code": e.code, "message": e.message})
    return json.dumps({"ok": False, "status": 400, "detail": "unknown op " + op})
