"""Booster shell: a PTY into a Docker VM (`vyomi-i-*` container on the vyomi-net network) for the Nano console's "Open shell".

Stream path (end to end):
    Nano tab --WS /shell (relay)--> hub --stream frames over the booster's outbound WSS--> wasm/relay/booster-dial.mjs
        --WS ws://simulator:9000/booster/shell--> THIS module --> `docker exec -it <container> bash` on a PTY.

Why here and not in the dial agent: this process already holds the Docker socket (it created the containers) and the
instance records, so the dial agent (a separate `link` container) needs no extra privileges and the "which container may
this stream touch" decision is made against the simulator's own state, not a client-supplied name.

Hard rules (each covered by tests/test_booster_shell.py):
  * the client sends {cloud, ref} (an instance id / VM name), never a container name; the container is resolved from the
    simulator's instance records by `resolve(cloud, ref)`;
  * the resolved name must match ^vyomi-i-<safe>$ , the container must carry label vyomi.instance=1, be running and be
    attached to the instance network (VYOMI_SHELL_NETWORK, default VYOMI_INSTANCE_NETWORK or "vyomi-net");
  * argv is a fixed list (no shell string built from input), so there is no path to the host or to other containers;
  * only available in the booster role (token enforced by core.booster_session.SessionMiddleware, which also covers websockets),
    or when VYOMI_BOOSTER_SHELL_ALLOW=1 (tests);
  * idle timeout, input-size cap, resize clamps, a cap on concurrent shells, and the PTY child is killed when the socket,
    the session or the idle timer ends.
Wire (this hop): binary frames = terminal bytes both ways; text frames = JSON control. Client -> {"t":"resize","cols":N,"rows":N};
server -> {"t":"opened","container":..} | {"t":"error","code":..,"message":..}.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import re
import signal
import struct
import uuid
import subprocess
import termios
import threading
import time
from typing import Callable, Optional

from fastapi import WebSocket

NAME_RE = re.compile(r"^vyomi-i-[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\Z")
MAX_INPUT = 64 * 1024          # one client frame
MAX_COLS, MAX_ROWS = 500, 200
MAX_SHELLS = int(os.environ.get("VYOMI_SHELL_MAX", "4"))
_active = 0
_active_lock = threading.Lock()


def _docker() -> str:
    return os.environ.get("VYOMI_DOCKER_BIN", "docker")


def _network() -> str:
    return os.environ.get("VYOMI_SHELL_NETWORK") or os.environ.get("VYOMI_INSTANCE_NETWORK") or "vyomi-net"


def idle_seconds() -> float:
    return float(os.environ.get("VYOMI_SHELL_IDLE_S", "900"))


def allowed() -> bool:
    from core import booster_session as bs
    return bs.role_is_booster() or os.environ.get("VYOMI_BOOSTER_SHELL_ALLOW") == "1"


def clamp_size(cols, rows) -> tuple[int, int]:
    try:
        c, r = int(cols), int(rows)
    except Exception:
        c, r = 100, 30
    return max(10, min(MAX_COLS, c)), max(3, min(MAX_ROWS, r))


class ShellError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(f"{code}: {message}")


def verify_container(name: str) -> None:
    """Raise ShellError unless `name` is a running Vyomi instance container on the instance network."""
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ShellError("ContainerNotAllowed", "not a Vyomi instance container")
    try:
        cp = subprocess.run([_docker(), "inspect", "-f",
                             '{{.State.Running}}|{{index .Config.Labels "vyomi.instance"}}|{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}',
                             name], capture_output=True, timeout=15)
    except Exception as e:
        raise ShellError("DockerUnavailable", str(e))
    if cp.returncode != 0:
        raise ShellError("InstanceNotFound", "the VM container does not exist")
    try:
        running, label, nets = cp.stdout.decode().strip().split("|", 2)
    except ValueError:
        raise ShellError("ContainerNotAllowed", "unreadable container record")
    if label.strip() != "1":
        raise ShellError("ContainerNotAllowed", "not a Vyomi instance container")
    if _network() not in nets.split():
        raise ShellError("ContainerNotAllowed", f"container is not on network {_network()}")
    if running.strip() != "true":
        raise ShellError("InstanceNotRunning", "the VM is not running; start it first")


def target_info(resolve: Callable[[str, str], Optional[str]], cloud: str, ref: str) -> dict:
    """Read-only probe used by the tab BEFORE opening a stream: does this instance live here and can it be shelled into?"""
    try:
        if cloud not in ("aws", "gcp", "azure") or not ref or len(ref) > 200:
            raise ShellError("BadRequest", "cloud/ref")
        name = resolve(cloud, ref)
        if not name:
            raise ShellError("InstanceNotFound", "no such instance on this booster")
        verify_container(name)
        return {"ok": True, "container": name, "cloud": cloud, "ref": ref}
    except ShellError as e:
        return {"ok": False, "code": e.code, "reason": e.message}


def _spawn(name: str, cols: int, rows: int, tag: str):
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    argv = [_docker(), "exec", "-it", "-e", "TERM=xterm-256color", "-e", f"VYOMI_SHELL_ID={tag}", name,
            "sh", "-c", "if command -v bash >/dev/null 2>&1; then exec bash -l; else exec sh -l; fi"]
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "VYOMI_FAKE_DOCKER")}   # never pass the session key / token to the CLI
    proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, start_new_session=True, close_fds=True, env=env)
    os.close(slave)
    return proc, master


_TAG_RE = re.compile(r"^[0-9a-f]{32}\Z")


def _kill(proc, master, name: str = "", tag: str = "") -> None:
    """End a shell: drop the docker CLI (and its PTY), then reap what it left INSIDE the container. Killing `docker exec -t` does not
    stop the exec'd shell, so every process of this shell carries VYOMI_SHELL_ID=<tag> in its environment and is HUPed by tag."""
    exited = proc.poll() is not None
    try:
        os.killpg(proc.pid, signal.SIGKILL)       # the CLI holds no state worth flushing; SIGHUP left it lingering for seconds
    except Exception:
        pass
    try:
        os.close(master)
    except Exception:
        pass

    def _reap():
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                pass
        if not exited and _TAG_RE.match(tag) and NAME_RE.match(name):
            script = ('for p in /proc/[0-9]*; do if tr "\\0" "\\n" < $p/environ 2>/dev/null | grep -qx "VYOMI_SHELL_ID=%s"; '
                      'then kill -HUP ${p#/proc/} 2>/dev/null; fi; done' % tag)
            try:
                subprocess.run([_docker(), "exec", name, "sh", "-c", script], capture_output=True, timeout=15, stdin=subprocess.DEVNULL)
            except Exception:
                pass
    threading.Thread(target=_reap, daemon=True).start()


async def serve(ws, resolve: Callable[[str, str], Optional[str]]) -> None:
    """Starlette/FastAPI WebSocket handler body."""
    global _active
    from core import booster_session as bs
    qp = ws.query_params
    await ws.accept()

    async def fail(code: str, msg: str, ws_code: int = 4403):
        try:
            await ws.send_text(json.dumps({"t": "error", "code": code, "message": msg}))
            await ws.close(code=ws_code)
        except Exception:
            pass

    if not allowed():
        return await fail("ShellNotAvailable", "this appliance is not a booster", 1008)
    cloud, ref = str(qp.get("cloud", "")), str(qp.get("ref", ""))
    cols, rows = clamp_size(qp.get("cols"), qp.get("rows"))
    loop = asyncio.get_running_loop()
    try:
        info = await loop.run_in_executor(None, target_info, resolve, cloud, ref)
    except Exception as e:                              # a resolver bug must not leak a stack trace to the client
        info = {"ok": False, "code": "InternalError", "reason": type(e).__name__}
    if not info.get("ok"):
        return await fail(info["code"], info["reason"])
    with _active_lock:
        if _active >= MAX_SHELLS:
            over = True
        else:
            _active += 1
            over = False
    if over:
        return await fail("TooManyShells", f"at most {MAX_SHELLS} shells at once", 4429)
    proc = master = None
    tag = uuid.uuid4().hex
    try:
        proc, master = _spawn(info["container"], cols, rows, tag)
        await ws.send_text(json.dumps({"t": "opened", "container": info["container"]}))
        state = {"last": time.monotonic(), "closing": False}

        def pump():                                        # PTY -> websocket; .result() gives backpressure
            while not state["closing"]:
                try:
                    data = os.read(master, 16384)
                except OSError:
                    break
                if not data:
                    break
                state["last"] = time.monotonic()
                try:
                    asyncio.run_coroutine_threadsafe(ws.send_bytes(data), loop).result(timeout=30)
                except Exception:
                    break
            state["closing"] = True
            asyncio.run_coroutine_threadsafe(_close_ws(ws, 1000), loop)

        threading.Thread(target=pump, daemon=True, name="booster-shell-pump").start()

        async def watchdog():
            while not state["closing"]:
                await asyncio.sleep(0.5)
                if bs.session_ended():
                    await fail("BoosterSessionExpired", "the booster session has ended", 4410); break
                if time.monotonic() - state["last"] > idle_seconds():
                    await fail("IdleTimeout", "shell closed after being idle", 4408); break
                if proc.poll() is not None:
                    await asyncio.sleep(0.3)                # let the pump flush the tail
                    break
            state["closing"] = True
            await _close_ws(ws, 1000)

        wd = asyncio.create_task(watchdog())
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    b = msg["bytes"]
                    if len(b) > MAX_INPUT:
                        await fail("FrameTooLarge", "input frame too large", 1009); break
                    state["last"] = time.monotonic()
                    await loop.run_in_executor(None, os.write, master, b)
                elif msg.get("text") is not None:
                    state["last"] = time.monotonic()
                    try:
                        c = json.loads(msg["text"])
                    except Exception:
                        continue
                    if c.get("t") == "resize":
                        cc, rr = clamp_size(c.get("cols"), c.get("rows"))
                        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rr, cc, 0, 0))
                        try:
                            os.killpg(proc.pid, signal.SIGWINCH)
                        except Exception:
                            pass
                    elif c.get("t") == "close":
                        break
        finally:
            state["closing"] = True
            wd.cancel()
    finally:
        if proc is not None:
            _kill(proc, master, info["container"], tag)
        with _active_lock:
            _active -= 1


async def _close_ws(ws, code: int) -> None:
    try:
        await ws.close(code=code)
    except Exception:
        pass


def register(app, resolve: Callable[[str, str], Optional[str]]) -> None:
    @app.websocket("/booster/shell")
    async def _booster_shell_ws(ws: WebSocket):
        await serve(ws, resolve)

    @app.get("/booster/shell/target", include_in_schema=False)
    def _booster_shell_target(cloud: str = "", ref: str = ""):
        if not allowed():
            return {"ok": False, "code": "ShellNotAvailable", "reason": "this appliance is not a booster"}
        return target_info(resolve, cloud, ref)
