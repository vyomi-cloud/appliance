"""The Nano<->host tunnel, bundled in the booster (no separate vyomi-tunnel release).

In booster mode the appliance supervises the same relay the standalone `vyomi-tunnel` ran (wasm/relay/local-relay.mjs):
HTTP relay for SDK/CLI, VM SSH bridge, and the /db bridge that publishes in-browser databases on host ports. The Nano tab
auto-detects it on the loopback port; it is NOT started outside booster mode and NOT published to npm/Homebrew as 1.2.0.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from typing import Optional

PORT = int(os.environ.get("VYOMI_RELAY_PORT", "8090"))
_proc: Optional[subprocess.Popen] = None
_lock = threading.Lock()
_stop = False


def _script() -> Optional[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.environ.get("VYOMI_RELAY_SCRIPT", ""), os.path.join(here, "..", "relay", "local-relay.mjs"),
              os.path.join(here, "..", "wasm", "relay", "local-relay.mjs")):
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return None


def _ws_pkg(script: str) -> str:
    base = os.path.dirname(script)
    for p in (os.path.join(base, "node_modules", "ws"), os.path.join(base, "..", "..", "relay-deps", "ws")):
        if os.path.isdir(p):
            return os.path.abspath(p)
    return "ws"


def running() -> bool:
    return _proc is not None and _proc.poll() is None


def start() -> bool:
    """Start (or keep) the relay. Returns whether it is running. Loopback-only; auto-restarts if it dies."""
    global _proc
    node, script = shutil.which("node"), _script()
    if not node or not script:
        return False
    with _lock:
        if running():
            return True
        env = {**os.environ, "RELAY_PORT": str(PORT), "RELAY_HOST": os.environ.get("VYOMI_RELAY_HOST", "127.0.0.1"),
               "WS_PKG": _ws_pkg(script)}
        _proc = subprocess.Popen([node, script], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def _watch() -> None:
    while not _stop:
        time.sleep(10)
        if not running():
            start()


def start_supervised() -> None:
    if start():
        threading.Thread(target=_watch, daemon=True, name="booster-relay").start()


def stop() -> None:
    global _stop
    _stop = True
    if running():
        _proc.terminate()


def info() -> dict:
    return {"bundled": True, "running": running(), "port": PORT, "script": bool(_script())}
