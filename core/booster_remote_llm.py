"""Remote LLM mode for the booster (SPIKE - OFF unless ``VYOMI_BOOSTER_REMOTE_LLM=1``).

The booster (Codespace, 2 cores / 8 GB) normally runs the AI pack (llama.cpp Qwen2.5-3B + bge-small, ~2.8 GB AI bucket).
In remote mode the LLM runs on a GitHub-Actions runner in the USER's account that dials OUT to the relay hub; the booster
reaches it with plain outbound HTTP through the relay's ``/llm`` plane (wasm/relay/runner-llm-hub.mjs). The booster never
accepts anything from the internet for this.

While a remote LLM is attached:
  * the in-Codespace AI pack does not load: ``booster_ai.admit*`` refuse to reserve RAM, ``booster.resource_budget`` gives the
    whole cap to compute (AI bucket = 0), so VMs/services get the 2.8 GB back;
  * ``llm_core`` is pointed at a loopback gateway (core/booster_llm_gateway in remote mode) that forwards to the relay;
  * status reports ``llm: remote (runner)``;
  * a dropped / expired / not-yet-ready runner is an honest HTTP 503 from the gateway. The local pack is NOT started as a
    fallback unless ``VYOMI_BOOSTER_REMOTE_LLM_FALLBACK=local`` is set, and then only on an explicit ``detach()``.

Design: docs/architecture/v4.0/BOOSTER-RUNNER-LLM.md
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from typing import Optional

PROBE_TTL_S = 3.0
_LOCK = threading.RLock()
_S: dict = {"attached": False, "hub": "", "token": "", "since": 0.0, "srv": None, "endpoint": "", "prev_endpoint": None, "pool": None, "reaper": None, "prev_map": None}
_PROBE = {"at": 0.0, "state": "absent"}


class RemoteLLMError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def enabled() -> bool:
    return os.environ.get("VYOMI_BOOSTER_REMOTE_LLM", "") == "1"


def active() -> bool:
    return bool(_S["attached"])


def fallback_local() -> bool:
    return os.environ.get("VYOMI_BOOSTER_REMOTE_LLM_FALLBACK", "") == "local"


def _target():
    with _LOCK:
        return (_S["hub"], _S["token"]) if _S["attached"] else None


def attach(hub_url: str, token: Optional[str] = None, *, host: str = "127.0.0.1", port: int = 0, pooled: bool = False,
           dispatcher=None, pool_kwargs: Optional[dict] = None) -> dict:
    """Point the AI seam at the runner behind `hub_url` (the relay base, http(s)://relay[:port]). The session token (default
    VYOMI_BOOSTER_SESSION_TOKEN) is verified here and re-presented to the relay on every call; it is never logged."""
    if not enabled():
        raise RemoteLLMError("remote_llm_disabled", "remote LLM mode is off (set VYOMI_BOOSTER_REMOTE_LLM=1)")
    if not (hub_url.startswith("http://") or hub_url.startswith("https://")):
        raise RemoteLLMError("bad_hub_url", "hub_url must be http(s)://", 400)
    token = token or os.environ.get("VYOMI_BOOSTER_SESSION_TOKEN", "")
    from core import booster_session as BS
    try:
        claims = BS.verify(token)
    except BS.SessionError as e:
        raise RemoteLLMError(e.code, e.message, e.status)
    if claims.get("role"):
        raise RemoteLLMError("BoosterSessionWrongRole", "a runner-role token cannot attach a remote LLM", 403)
    from core import booster_ai, booster_llm_gateway as G, llm_core  # noqa: F401
    with _LOCK:
        if _S["attached"]:
            _S.update(hub=hub_url.rstrip("/") + "/llm", token=token)           # re-attach: refresh only
            return info()
        booster_ai.release_all()                                               # free the local AI bucket
        pool = None
        if pooled:                       # one runner per catalogue model (core/booster_runner_pool.py)
            from core.booster_runner_pool import HttpDispatcher, RunnerPool, window_s_for
            tf = lambda: (_S["token"])  # noqa: E731
            kw = {"window_s": window_s_for(claims.get("tier", "pro")), "on_destroy": _on_pool_destroy, **(pool_kwargs or {})}
            pool = RunnerPool(hub_url.rstrip("/") + "/llm", tf, dispatcher or HttpDispatcher(token_fn=tf), **kw)
            _S["prev_map"] = os.environ.get("VYOMI_LLM_MODEL_MAP")
            os.environ["VYOMI_LLM_MODEL_MAP"] = json.dumps(pool.model_map())
            _S["pool"] = pool
            _S["reaper"] = threading.Thread(target=_reaper, args=(pool,), daemon=True, name="runner-pool-reaper")
            _S["reaper"].start()
        srv = G.serve(port, remote=None if pool else _target, host=host, pool=pool)
        threading.Thread(target=srv.serve_forever, daemon=True, name="remote-llm-gateway").start()
        ep = f"http://{host}:{srv.server_address[1]}"
        _S.update(attached=True, hub=hub_url.rstrip("/") + "/llm", token=token, since=time.time(), srv=srv, endpoint=ep,
                  prev_endpoint=os.environ.get("VYOMI_LLM_ENDPOINT"))
    os.environ["VYOMI_LLM_ENDPOINT"] = ep
    if pooled:
        _S["pool"].start_all()               # EAGER: every catalogue runner is dispatched now; the wall-clock window opens
    os.environ.setdefault("VYOMI_LLM_MODEL", booster_ai.selected()["chat"])
    _PROBE["at"] = 0.0
    return info()


def _reaper(pool, every: float = 30.0) -> None:
    while _S["pool"] is pool:
        time.sleep(every)
        try:
            pool.tick()
        except Exception:
            pass


def pool():
    return _S["pool"]


_destroy_hooks: list = []         # callables(why) - the booster registers "stop the booster" here for the idle rule


def _on_pool_destroy(why: str) -> None:
    for h in list(_destroy_hooks):
        try:
            h(why)
        except Exception:
            pass


def touch(kind: str = "console") -> None:
    """Console / VM / inference activity keeps the model pool alive (60-min idle rule). Cheap no-op when not pooled."""
    p = _S["pool"]
    if p is not None:
        p.touch(kind)


def detach() -> dict:
    """Drop the remote LLM. The local AI pack stays off unless VYOMI_BOOSTER_REMOTE_LLM_FALLBACK=local."""
    with _LOCK:
        srv, prev, pl = _S["srv"], _S["prev_endpoint"], _S["pool"]
        if pl:                           # destroy every model runner we started; hours stay in the ledger
            pl.destroy("detach")
            if _S["prev_map"] is None:
                os.environ.pop("VYOMI_LLM_MODEL_MAP", None)
            else:
                os.environ["VYOMI_LLM_MODEL_MAP"] = _S["prev_map"]
        _S.update(attached=False, token="", srv=None, pool=None, reaper=None)
    if srv:
        srv.shutdown(); srv.server_close()
    if fallback_local():
        if prev is None:
            os.environ.pop("VYOMI_LLM_ENDPOINT", None)
        else:
            os.environ["VYOMI_LLM_ENDPOINT"] = prev
        from core import booster_ai
        booster_ai.admit_configured()
    # else: VYOMI_LLM_ENDPOINT keeps naming the (now closed) loopback gateway -> connection refused -> llm_core errors. No silent local model.
    return info()


def runner_state() -> str:
    """absent | starting | ready | stale | unreachable (cached ~3 s). 'absent' when nothing is attached.
    Pooled mode: 'pool' (per-model states are in info()['pool'])."""
    if _S["pool"] is not None:
        return "pool"
    t = _target()
    if not t:
        return "absent"
    now = time.monotonic()
    if now - _PROBE["at"] < PROBE_TTL_S:
        return _PROBE["state"]
    try:
        r = urllib.request.urlopen(urllib.request.Request(t[0] + "/_status", headers={"x-vyomi-session-token": t[1]}), timeout=3)
        st = str(json.loads(r.read()).get("runner", "absent"))
    except Exception:
        st = "unreachable"
    _PROBE.update(at=now, state=st)
    return st


def info() -> dict:
    st = runner_state()
    on = active()
    return {"enabled": enabled(), "attached": on, "mode": "remote" if on else "local", "runner": st,
            "label": ("llm: remote (runner)" + ("" if st in ("ready", "pool") else f" - {st}")) if on else "llm: local (booster)",
            "endpoint": _S["endpoint"] if on else None, "since": _S["since"] or None, "fallback_local": fallback_local(),
            **({"pool": _S["pool"].usage()} if _S["pool"] is not None else {})}


def reset_for_tests() -> None:
    try:
        detach()
    except Exception:
        pass
    _PROBE.update(at=0.0, state="absent")
