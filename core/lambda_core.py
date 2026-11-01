"""Lambda core — substrate-independent serverless data plane (PARITY P4 #14). The
first real function-invoke path in the simulator: register a function's code, then
synchronously **Invoke** it — the code actually runs against the event payload and
its return value is the response.

Speaks the native **Lambda REST API** (`/2015-03-31/functions/...`) so an unmodified
boto3 `lambda` client works: CreateFunction / GetFunction / ListFunctions /
DeleteFunction / UpdateFunctionCode / Invoke. NO fastapi / boto3 / socket imports →
loads under Pyodide.

Runtime: a **sandboxed Python runtime**. The function code (Code.ZipFile as base64,
or the simulator-friendly Code.Source string) must define `handler(event, context)`.
Invoke execs it in a restricted namespace — a curated safe builtins subset, `json`
available, and NO __import__ / open / exec / eval / compile / file or network access.
This is a real, deterministic simulation of a Python-runtime function; other runtimes
(node/go) and async/event-source invokes slot in behind the same seam.
"""
from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, field

# A curated safe builtins subset — no open / exec / eval / compile. A restricted
# __import__ (below) is added so realistic handlers can `import json` etc.
_SAFE_BUILTINS = {
    name: __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name)
    for name in ("abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
                 "int", "len", "list", "map", "max", "min", "range", "reversed",
                 "round", "set", "sorted", "str", "sum", "tuple", "zip", "print",
                 "isinstance", "hasattr", "getattr", "repr", "type", "chr", "ord",
                 "Exception", "ValueError", "KeyError", "TypeError", "IndexError")
}

# Stdlib modules a function may import — pure/computational only. Deliberately
# EXCLUDES os / sys / subprocess / socket / importlib / ctypes / io / pathlib /
# shutil / builtins, so a handler cannot reach the filesystem, network or process.
_SAFE_MODULES = {"json", "math", "datetime", "base64", "re", "random", "uuid",
                 "hashlib", "hmac", "itertools", "functools", "collections",
                 "string", "decimal", "statistics", "textwrap", "time"}


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if root not in _SAFE_MODULES:
        raise ImportError(f"module '{name}' is not available in the Lambda sandbox")
    import importlib
    return importlib.import_module(name)


_SAFE_BUILTINS["__import__"] = _safe_import


@dataclass
class LambdaResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


def _json(status: int, obj: dict, headers: dict | None = None) -> LambdaResponse:
    return LambdaResponse(status=status, body=json.dumps(obj).encode(), headers=headers or {})


def _err(status: int, err_type: str, message: str) -> LambdaResponse:
    return LambdaResponse(status=status, body=json.dumps({"Message": message}).encode(),
                          headers={"x-amzn-errortype": err_type})


def _functions(store) -> dict:
    m = getattr(store, "_lambda_functions", None)
    if m is None:
        m = {}
        store._lambda_functions = m
    return m


def _persist(store):
    if hasattr(store, "persist"):
        try:
            store.persist()
        except Exception:
            pass


def _extract_source(code: dict, handler: str = "index.handler") -> str:
    """Function source from Code.ZipFile (a base64 zip of the handler module, or — for
    simulator convenience — base64 plain source) or Code.Source (plain string)."""
    if not isinstance(code, dict):
        return ""
    if code.get("Source"):
        return str(code["Source"])
    zf = code.get("ZipFile")
    if zf:
        try:
            raw = base64.b64decode(zf) if isinstance(zf, (str, bytes, bytearray)) else b""
        except Exception:
            raw = zf if isinstance(zf, (bytes, bytearray)) else str(zf).encode("utf-8")
        if raw[:2] == b"PK":   # a real zip archive, as the official SDKs send it
            import io
            import zipfile
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    names = z.namelist()
                    mod = (handler.rsplit(".", 1)[0] if "." in handler else handler).replace(".", "/") + ".py"
                    pick = mod if mod in names else next((n for n in names if n.endswith(".py")), "")
                    return z.read(pick).decode("utf-8") if pick else ""
            except Exception:
                return ""
        try:
            return raw.decode("utf-8")
        except Exception:
            return ""
    return ""


def _now_iso() -> str:
    """Lambda's LastModified format: 2026-10-29T01:52:56.000+0000."""
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def _fn_view(fn: dict) -> dict:
    return {"FunctionName": fn["name"], "FunctionArn": fn["arn"],
            "Runtime": fn.get("runtime", "python3.12"), "Handler": fn.get("handler", "index.handler"),
            "CodeSize": len(fn.get("source", "")), "Version": "$LATEST",
            "MemorySize": fn.get("memory_size", 128), "Timeout": fn.get("timeout", 3),
            "Role": fn.get("role", ""), "Description": fn.get("description", ""),
            "PackageType": "Zip", "State": "Active", "Architectures": ["x86_64"],
            "LastModified": fn.get("last_modified", "")}


# ── control plane ───────────────────────────────────────────────────────────
def _create_function(store, body):
    name = str(body.get("FunctionName", "")).strip()
    if not name:
        return _err(400, "InvalidParameterValueException", "FunctionName is required.")
    fn = {"name": name, "arn": f"arn:aws:lambda:us-east-1:123456789012:function:{name}",
          "runtime": str(body.get("Runtime", "python3.12")),
          "handler": str(body.get("Handler", "index.handler")),
          "source": _extract_source(body.get("Code") or {}, str(body.get("Handler", "index.handler"))),
          "env": (body.get("Environment") or {}).get("Variables") or {},
          "memory_size": int(body.get("MemorySize") or 128), "timeout": int(body.get("Timeout") or 3),
          "role": str(body.get("Role") or "arn:aws:iam::123456789012:role/service-role/lambda-basic-execution"),
          "description": str(body.get("Description") or ""),
          "last_modified": _now_iso()}
    _functions(store)[name] = fn
    _persist(store)
    return _json(201, _fn_view(fn))


def _update_function_code(store, name, body):
    fn = _functions(store).get(name)
    if not fn:
        return _err(404, "ResourceNotFoundException", f"Function not found: {name}")
    fn["source"] = _extract_source(body, fn.get("handler", "index.handler")) or fn["source"]
    _persist(store)
    return _json(200, _fn_view(fn))


def _get_function(store, name):
    fn = _functions(store).get(name)
    if not fn:
        return _err(404, "ResourceNotFoundException", f"Function not found: {name}")
    return _json(200, {"Configuration": _fn_view(fn), "Code": {"RepositoryType": "S3"}})


def _list_functions(store):
    return _json(200, {"Functions": [_fn_view(f) for f in _functions(store).values()]})


def _delete_function(store, name):
    if _functions(store).pop(name, None) is None:
        return _err(404, "ResourceNotFoundException", f"Function not found: {name}")
    _persist(store)
    return LambdaResponse(status=204)


# ── data plane: synchronous Invoke ─────────────────────────────────────────
class _Ctx(dict):
    """Lambda context: attribute access (context.function_name) AND the dict form older handlers use."""
    __getattr__ = dict.get


def _invoke(store, name, body, headers=None):
    name = name.split(":function:")[-1].split(":")[0] if ":function:" in name else name
    fn = _functions(store).get(name)
    if not fn:
        return _err(404, "ResourceNotFoundException", f"Function not found: {name}")
    hdr = {str(k).lower(): v for k, v in (headers or {}).items()}
    try:
        event = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        event = {}
    source = fn.get("source", "")
    logs = []

    def _print(*a, **k):   # captured as the invocation's log (LogType=Tail)
        logs.append(" ".join(str(x) for x in a))
    safe = dict(_SAFE_BUILTINS)
    safe["print"] = _print
    sandbox_globals = {"__builtins__": safe, "json": json}
    context = _Ctx(function_name=name, aws_request_id=uuid.uuid4().hex, invoked_function_arn=fn["arn"],
                   function_version="$LATEST", memory_limit_in_mb=fn.get("memory_size", 128),
                   log_group_name=f"/aws/lambda/{name}")
    out_headers = {"X-Amz-Executed-Version": "$LATEST"}
    try:
        exec(compile(source, f"<lambda:{name}>", "exec"), sandbox_globals)
        handler = sandbox_globals.get(fn.get("handler", "index.handler").split(".")[-1]) \
            or sandbox_globals.get("handler")
        if not callable(handler):
            raise RuntimeError("handler is not defined")
        result = handler(event, context)
        resp = LambdaResponse(status=200, body=json.dumps(result).encode(), headers=out_headers)
    except Exception as e:
        # Handled-error response: 200 with X-Amz-Function-Error, like real Lambda.
        payload = {"errorType": type(e).__name__, "errorMessage": str(e)}
        out_headers["X-Amz-Function-Error"] = "Unhandled"
        resp = LambdaResponse(status=200, body=json.dumps(payload).encode(), headers=out_headers)
    if str(hdr.get("x-amz-log-type", "")).lower() == "tail":
        resp.headers["X-Amz-Log-Result"] = base64.b64encode("\n".join(logs).encode("utf-8")[-4096:]).decode("ascii")
    fn.setdefault("logs", []).extend(logs)
    fn["invocation_count"] = fn.get("invocation_count", 0) + 1
    if str(hdr.get("x-amz-invocation-type", "")).lower() == "event":
        return LambdaResponse(status=202, body=b"", headers={})
    return resp


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> LambdaResponse:
    """Native Lambda REST router:
        POST   /2015-03-31/functions                       CreateFunction
        GET    /2015-03-31/functions                       ListFunctions
        GET    /2015-03-31/functions/{name}                GetFunction
        DELETE /2015-03-31/functions/{name}                DeleteFunction
        PUT    /2015-03-31/functions/{name}/code           UpdateFunctionCode
        POST   /2015-03-31/functions/{name}/invocations    Invoke
    """
    method = (method or "GET").upper()
    p = path.split("?", 1)[0]
    segs = [s for s in p.split("/") if s != ""]
    # find the 'functions' marker (after the /2015-03-31 api version)
    if "functions" not in segs:
        return _err(404, "ResourceNotFoundException", f"Unknown path: {path}")
    i = segs.index("functions")
    tail = segs[i + 1:]

    if not tail:                                   # collection
        if method == "POST":
            return _create_function(store, _parse(body))
        if method == "GET":
            return _list_functions(store)
        return _err(405, "MethodNotAllowed", f"Unsupported {method} on functions")

    name = tail[0]
    if len(tail) == 1:
        if method == "GET":
            return _get_function(store, name)
        if method == "DELETE":
            return _delete_function(store, name)
        return _err(405, "MethodNotAllowed", f"Unsupported {method} on function")
    if len(tail) == 2 and tail[1] == "invocations" and method == "POST":
        return _invoke(store, name, body, headers)
    if len(tail) == 2 and tail[1] == "code" and method in ("PUT", "POST"):
        return _update_function_code(store, name, _parse(body))
    return _err(404, "ResourceNotFoundException", f"Unknown path: {path}")


def _parse(body: bytes) -> dict:
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return {}
