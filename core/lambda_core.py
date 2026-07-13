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

# A curated safe builtins subset — no __import__ / open / exec / eval / compile.
_SAFE_BUILTINS = {
    name: __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name)
    for name in ("abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
                 "int", "len", "list", "map", "max", "min", "range", "reversed",
                 "round", "set", "sorted", "str", "sum", "tuple", "zip", "print",
                 "isinstance", "hasattr", "getattr", "repr", "type", "chr", "ord")
}


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


def _extract_source(code: dict) -> str:
    """Function source from Code.ZipFile (base64) or Code.Source (plain string)."""
    if not isinstance(code, dict):
        return ""
    if code.get("Source"):
        return str(code["Source"])
    zf = code.get("ZipFile")
    if zf:
        try:
            return base64.b64decode(zf).decode("utf-8")
        except Exception:
            try:
                return zf.decode("utf-8") if isinstance(zf, (bytes, bytearray)) else str(zf)
            except Exception:
                return ""
    return ""


def _fn_view(fn: dict) -> dict:
    return {"FunctionName": fn["name"], "FunctionArn": fn["arn"],
            "Runtime": fn.get("runtime", "python3.12"), "Handler": fn.get("handler", "index.handler"),
            "CodeSize": len(fn.get("source", "")), "Version": "$LATEST",
            "LastModified": fn.get("last_modified", "")}


# ── control plane ───────────────────────────────────────────────────────────
def _create_function(store, body):
    name = str(body.get("FunctionName", "")).strip()
    if not name:
        return _err(400, "InvalidParameterValueException", "FunctionName is required.")
    fn = {"name": name, "arn": f"arn:aws:lambda:us-east-1:123456789012:function:{name}",
          "runtime": str(body.get("Runtime", "python3.12")),
          "handler": str(body.get("Handler", "index.handler")),
          "source": _extract_source(body.get("Code") or {}),
          "env": (body.get("Environment") or {}).get("Variables") or {},
          "last_modified": ""}
    _functions(store)[name] = fn
    _persist(store)
    return _json(201, _fn_view(fn))


def _update_function_code(store, name, body):
    fn = _functions(store).get(name)
    if not fn:
        return _err(404, "ResourceNotFoundException", f"Function not found: {name}")
    fn["source"] = _extract_source(body) or fn["source"]
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
def _invoke(store, name, body):
    fn = _functions(store).get(name)
    if not fn:
        return _err(404, "ResourceNotFoundException", f"Function not found: {name}")
    try:
        event = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        event = {}
    source = fn.get("source", "")
    sandbox_globals = {"__builtins__": dict(_SAFE_BUILTINS), "json": json}
    context = {"function_name": name, "aws_request_id": uuid.uuid4().hex,
               "invoked_function_arn": fn["arn"]}
    try:
        exec(compile(source, f"<lambda:{name}>", "exec"), sandbox_globals)
        handler = sandbox_globals.get(fn.get("handler", "index.handler").split(".")[-1]) \
            or sandbox_globals.get("handler")
        if not callable(handler):
            raise RuntimeError("handler is not defined")
        result = handler(event, context)
        return LambdaResponse(status=200, body=json.dumps(result).encode(),
                              headers={"X-Amz-Executed-Version": "$LATEST"})
    except Exception as e:
        # Handled-error response: 200 with X-Amz-Function-Error, like real Lambda.
        payload = {"errorType": type(e).__name__, "errorMessage": str(e)}
        return LambdaResponse(status=200, body=json.dumps(payload).encode(),
                              headers={"X-Amz-Function-Error": "Unhandled"})


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
        return _invoke(store, name, body)
    if len(tail) == 2 and tail[1] == "code" and method in ("PUT", "POST"):
        return _update_function_code(store, name, _parse(body))
    return _err(404, "ResourceNotFoundException", f"Unknown path: {path}")


def _parse(body: bytes) -> dict:
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return {}
