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


_AGENT_DEPS = {"done": False, "error": ""}
# langgraph is pure Python but PyPI's current release pulls native wheels Pyodide 0.26 does not have (xxhash>=3.5, ormsgpack, uuid-utils,
# pydantic-core==2.50, zstandard). This pinned set is pure Python and loads on Pyodide's own pydantic/msgpack/orjson/xxhash/anyio (verified on 0.26.2).
_PYODIDE_PKGS = ["pydantic", "pyyaml", "orjson", "xxhash", "msgpack", "requests", "anyio", "packaging", "typing-extensions"]
_PIP_PINS = ["langgraph==0.2.60", "langgraph-checkpoint==2.0.9", "langchain-core==0.3.28", "langsmith==0.2.10", "requests-toolbelt", "jsonpointer",
             "tenacity", "jsonpatch", "httpx", "httpcore", "h11", "certifi", "idna", "sniffio"]


async def ensure_agent_deps() -> str:
    """Hosted AgentCore agents import langgraph. Fetch it once, on the first runtime call (needs the browser online); '' when ready, else why not."""
    if _AGENT_DEPS["done"]:
        return _AGENT_DEPS["error"]
    _AGENT_DEPS["done"] = True
    try:
        import langgraph  # noqa: F401
        return ""
    except ImportError:
        pass
    try:
        import pyodide_js
        await pyodide_js.loadPackage(["micropip"] + _PYODIDE_PKGS)
        import micropip
        await micropip.install(_PIP_PINS, deps=False)
    except Exception as e:  # noqa: BLE001
        _AGENT_DEPS["error"] = f"langgraph could not be installed in this browser ({type(e).__name__}: {str(e)[:160]}). Hosted agents that import langgraph need network access to PyPI."
        _AGENT_DEPS["done"] = False   # retry on the next call (offline now, online later)
    return _AGENT_DEPS["error"]


async def ahandle(p: dict) -> dict:
    """Async twin of handle(): AwsWireRouter.ahandle (RDS snapshots / Parquet exports
    and the RDS Data API await their engines)."""
    try:
        if "/runtimes/" in str(p.get("path") or "") and str(p.get("path") or "").split("?")[0].rstrip("/").endswith("/invocations"):
            await ensure_agent_deps()
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


def transport(method, path, query, headers, body):
    """The in-process boto3 transport: (method, path, query, headers, body) -> (status, headers, body_bytes) straight into the router, no HTTP."""
    r = router().handle(str(method).upper(), path, query or {}, headers or {}, body or b"")
    out = r.get("body") or b""
    out = out.encode("utf-8") if isinstance(out, str) else bytes(out)
    return int(r.get("status") or 200), {str(k): str(v) for k, v in (r.get("headers") or {}).items()}, out


def register_lambda_sdk():
    """Give Lambda handlers (core/lambda_core sandbox) and hosted AgentCore agents a boto3 whose calls land in THIS Nano's stores."""
    try:
        import os
        import botocore
        from core import lambda_sdk
        lambda_sdk.set_transport(transport, os.path.join(os.path.dirname(botocore.__file__), "data"))
        return True
    except Exception:  # botocore-lite not loaded (relay worker): handlers keep the restricted sandbox
        return False


register_lambda_sdk()
