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
# langgraph is pure Python, but PyPI's resolver also wants native wheels Pyodide 0.26 lacks (ormsgpack, uuid-utils, xxhash>=3.5, pydantic-core pin,
# zstandard). A pinned set installed with deps=False runs on Pyodide's own pydantic/msgpack/orjson/xxhash; the two native pieces langgraph only
# touches on paths a compiled graph without a checkpointer never takes (ormsgpack = checkpoint serde, uuid-utils = uuid7 ids) get small pure stubs.
# 0.6.x on purpose: <=0.3 rejects a node named like a state key ('analytics'), which the course's agent uses. Verified on Pyodide 0.26.2.
_PYODIDE_PKGS = ["pydantic", "pyyaml", "orjson", "xxhash", "msgpack", "requests", "packaging", "typing-extensions"]
_PIP_PINS = ["langgraph==0.6.11", "langgraph-checkpoint==2.1.2", "langgraph-prebuilt==0.6.5", "langgraph-sdk==0.2.9", "langchain-core==0.3.86",
             "langsmith==0.4.37", "requests-toolbelt", "jsonpointer", "tenacity", "jsonpatch", "httpx", "httpcore", "h11", "certifi", "idna", "sniffio",
             "anyio", "zstandard"]


def _install_native_stubs():
    import os
    import sys
    import time
    import types
    import uuid
    import msgpack
    m = types.ModuleType("ormsgpack")
    m.packb = lambda o, default=None, option=0: msgpack.packb(o, default=default, use_bin_type=True)
    m.unpackb = lambda b, ext_hook=None, option=0: msgpack.unpackb(b, ext_hook=ext_hook or msgpack.ExtType, raw=False, strict_map_key=False)

    def _opt(name):
        if name.startswith("OPT_"):
            return 1
        raise AttributeError(name)
    m.__getattr__ = _opt
    sys.modules.setdefault("ormsgpack", m)

    def uuid7():
        ms = int(time.time() * 1000)
        r = int.from_bytes(os.urandom(10), "big")
        return uuid.UUID(int=(ms << 80) | (0x7 << 76) | (((r >> 62) & 0xFFF) << 64) | (0b10 << 62) | (r & ((1 << 62) - 1)))
    ug, ugc = types.ModuleType("uuid_utils"), types.ModuleType("uuid_utils.compat")
    ug.uuid7 = ugc.uuid7 = uuid7
    ug.compat = ugc
    sys.modules.setdefault("uuid_utils", ug)
    sys.modules.setdefault("uuid_utils.compat", ugc)


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
        await pyodide_js.loadPackage("micropip")
        import micropip
        miss = []
        for pk in _PYODIDE_PKGS:        # Pyodide's own builds (native pieces); anything it lacks falls back to PyPI below
            try:
                await pyodide_js.loadPackage(pk)
            except Exception:  # noqa: BLE001
                miss.append(pk)
        await micropip.install(_PIP_PINS + miss, deps=False)
        _install_native_stubs()
    except Exception as e:  # noqa: BLE001
        _AGENT_DEPS["error"] = f"langgraph could not be installed in this browser ({type(e).__name__}: {str(e)[:160]}). Hosted agents that import langgraph need network access to PyPI."
        _AGENT_DEPS["done"] = False   # retry on the next call (offline now, online later)
    return _AGENT_DEPS["error"]


def _long_job(delta):
    """Tell the service worker a slow request (hosted agent: several model calls; first-use package download) is still alive (nano-boot keepalive)."""
    try:
        import js
        js.globalThis.__vyomiLongJobs = int(js.globalThis.__vyomiLongJobs or 0) + delta
    except Exception:  # noqa: BLE001
        pass


async def ahandle(p: dict) -> dict:
    """Async twin of handle(): AwsWireRouter.ahandle (RDS snapshots / Parquet exports
    and the RDS Data API await their engines)."""
    slow = "/runtimes/" in str(p.get("path") or "") and str(p.get("path") or "").split("?")[0].rstrip("/").endswith("/invocations")
    if slow:
        _long_job(1)
    try:
        if "/runtimes/" in str(p.get("path") or "") and str(p.get("path") or "").split("?")[0].rstrip("/").endswith("/invocations"):
            why = await ensure_agent_deps()
        else:
            why = ""
        body = base64.b64decode(p.get("body_b64") or "")
        r = await router().ahandle(str(p.get("method") or "GET").upper(), p.get("path") or "/", p.get("query") or {}, p.get("headers") or {}, body)
        if why and int(r.get("status") or 200) >= 400:   # the agent died on a missing package: say why it is missing, not just that it is
            rb = r.get("body") or b""
            rb = rb.encode() if isinstance(rb, str) else bytes(rb)
            if b"langgraph" in rb:
                r = {**r, "body": rb + b" -- " + why.encode()}
        return _out(r)
    except Exception as e:  # surface, never crash the bridge
        msg = json.dumps({"__type": "InternalFailure", "message": f"nano /_wire: {type(e).__name__}: {e}"})
        return {"status": 500, "headers": {"content-type": "application/json"},
                "body_b64": base64.b64encode(msg.encode("utf-8", "replace")).decode()}
    finally:
        if slow:
            _long_job(-1)


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
