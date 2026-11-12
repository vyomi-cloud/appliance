"""Nano (Pyodide) side of the v4 `/_wire/*` native-wire prefix.

The SW (wasm/sw.js) forwards `<BASE>/_wire/<native path>` here as one dispatch
tuple ("_wire", "wire", <METHOD>, {method, path, query, headers, body_b64}).
We serve it with core.aws_wire_router.AwsWireRouter — the SAME native-wire front
door the relay (relay/nano-endpoint.html, relay/relay-shared-worker.js) uses for
an unmodified SDK/CLI — built over the SAME shared store registry
(core.nano_registry.get(), constructed exactly like the relay does). So:

  * within this page, console `/_wire` calls and the existing /api/* console
    adapters read/write one set of stores;
  * across contexts (this page ↔ relay worker/tab), nano-boot's dispatch bridge
    restores the shared IndexedDB snapshot before each call and persists +
    BroadcastChannel-notifies after it (nano_persist), exactly as for /api/*;
  * nano_persist.restore_registry() mutates the registry stores IN PLACE, so the
    router built once here never holds stale store references.

Bodies cross the SW↔page bridge as base64 (binary-safe both ways).
"""
from __future__ import annotations

import base64
import json

_ROUTER = None


def router():
    global _ROUTER
    if _ROUTER is None:
        from core.aws_wire_router import AwsWireRouter
        from core import nano_registry
        _ROUTER = AwsWireRouter(stores=nano_registry.get())
    return _ROUTER


def _out(r: dict) -> dict:
    out = r.get("body") or b""
    if isinstance(out, str):
        out = out.encode("utf-8")
    return {"status": int(r.get("status") or 200),
            "headers": {str(k): str(v) for k, v in (r.get("headers") or {}).items()},
            "body_b64": base64.b64encode(bytes(out)).decode()}


async def ahandle(p: dict) -> dict:
    """Async twin of handle(): AwsWireRouter.ahandle (RDS snapshots / Parquet exports
    and the RDS Data API await their engines)."""
    try:
        body = base64.b64decode(p.get("body_b64") or "")
        return _out(await router().ahandle(str(p.get("method") or "GET").upper(), p.get("path") or "/",
                                           p.get("query") or {}, p.get("headers") or {}, body))
    except Exception as e:  # surface, never crash the bridge
        msg = json.dumps({"__type": "InternalFailure", "message": f"nano /_wire: {type(e).__name__}: {e}"})
        return {"status": 500, "headers": {"content-type": "application/json"},
                "body_b64": base64.b64encode(msg.encode("utf-8", "replace")).decode()}


def handle(p: dict) -> dict:
    """One native-wire request → {status, headers, body_b64}."""
    try:
        body = base64.b64decode(p.get("body_b64") or "")
        r = router().handle(str(p.get("method") or "GET").upper(), p.get("path") or "/",
                            p.get("query") or {}, p.get("headers") or {}, body)
        out = r.get("body") or b""
        if isinstance(out, str):
            out = out.encode("utf-8")
        return {"status": int(r.get("status") or 200),
                "headers": {str(k): str(v) for k, v in (r.get("headers") or {}).items()},
                "body_b64": base64.b64encode(bytes(out)).decode()}
    except Exception as e:  # surface, never crash the bridge
        msg = json.dumps({"__type": "InternalFailure", "message": f"nano /_wire: {type(e).__name__}: {e}"})
        return {"status": 500, "headers": {"content-type": "application/json"},
                "body_b64": base64.b64encode(msg.encode("utf-8", "replace")).decode()}
