"""v4 C0f — AWS Lambda on the offline appliance: ONE engine, ONE function store.

The native Lambda REST API (`/2015-03-31/functions…`, layers, event-source mappings, aliases,
versions, URLs, policy, concurrency, …) is served by core/lambda_core.py — the engine Nano and
dev_server use — over core/appliance_stores.AppStateLambdaStore (the space's persisted
`lambda` slot). Before v4 the offline appliance answered `GET /2015-03-31/functions` with the
classic console's snake_case `{"functions": […]}` and the v4 Lambda console failed with
"reading 'Description'".

Invoke keeps the appliance's REAL runtime: the store's `run_function` hook (installed here)
writes the handler module + layer code into lambda_functions/<name>/ and runs it in a separate
Python process with the function's environment and timeout — exactly what the pre-v4 handler
did — instead of the in-process sandbox Nano uses.

Every other path that reaches a function goes through this module too (server.py delegates
`_lambda_find_function` / `_lambda_invoke_function` here while "lambda" is unified):
EventBridge / Scheduler targets (AppStateMessagingStore.deliver_lambda), SNS lambda
subscriptions, S3 notifications, the API Gateway V2 gateway, and — through the shared store on
the net-new router — API Gateway v1 AWS_PROXY integrations and Step Functions tasks.

The classic console REST (/api/lambda/functions*, /api/lambda/layers*) is re-implemented on
the same store with its pre-v4 snake_case view. Registered BEFORE the provider routes.
Opt-out: VYOMI_UNIFIED_INGRESS_SERVICES without "lambda" (or VYOMI_LEGACY_WIRE=1).
"""
from __future__ import annotations

import contextvars
import json
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

from core import appliance_stores as _aps
from core import lambda_core as _lc
from core import wire_ingress as _wi

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]


def _store():
    st = _wi.appliance_router().lam
    st.adopt()
    return st


def _fns() -> dict:
    return _lc._functions(_store())


def _find(name: str) -> dict | None:
    """Exact name (or ARN), then the pre-v4 case-insensitive fallback."""
    fns = _fns()
    n = _lc._norm_name(name)
    if n in fns:
        return fns[n]
    low = n.lower()
    return next((f for k, f in fns.items() if k.lower() == low), None)


# ── the real runtime (the pre-v4 subprocess runner, ported) ────────────────────────────
_HELPER = textwrap.dedent(
    """
    import contextlib, importlib.util, io, json, os, sys, traceback
    workdir, module_name, module_file, handler_name = sys.argv[1:5]
    payload = json.loads(sys.stdin.read() or "{}")
    sys.path.insert(0, workdir)

    class Context:
        function_name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "")
        function_version = "$LATEST"
        invoked_function_arn = os.environ.get("VYOMI_LAMBDA_ARN", "")
        memory_limit_in_mb = int(os.environ.get("AWS_LAMBDA_FUNCTION_MEMORY_SIZE", "128") or 128)
        aws_request_id = os.environ.get("VYOMI_LAMBDA_REQUEST_ID", "")
        log_group_name = "/aws/lambda/" + function_name
        log_stream_name = ""
        def get_remaining_time_in_millis(self):
            return int(os.environ.get("VYOMI_LAMBDA_TIMEOUT_MS", "3000") or 3000)

    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            spec = importlib.util.spec_from_file_location(module_name, module_file)
            if spec is None or spec.loader is None:
                raise RuntimeError("Unable to import module '%s'" % module_name)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            handler = getattr(module, handler_name)
            result = handler(payload, Context())
        print(json.dumps({"ok": True, "result": result, "logs": out.getvalue() + err.getvalue()}, default=str))
    except Exception as exc:
        print(json.dumps({"ok": False, "errorType": type(exc).__name__, "error": str(exc),
                          "stackTrace": traceback.format_exc().splitlines()[-8:],
                          "logs": out.getvalue() + err.getvalue()}, default=str))
    """
).strip()


def _workdir(name: str) -> Path:
    import server as _srv
    return Path(_srv.__file__).with_name("lambda_functions") / name


def _layer_sources(fn: dict) -> dict:
    """{module filename: source} of the function's layers (core layers, by ARN name:version)."""
    out = {}
    layers = _lc._layers(_store())
    for arn in fn.get("layers") or []:
        parts = str(arn).split(":")
        name, ver = (parts[parts.index("layer") + 1], parts[-1]) if "layer" in parts and parts.index("layer") + 1 < len(parts) \
            else (str(arn), "")
        entry = layers.get(name) or {}
        versions = entry.get("versions") or {}
        pick = versions.get(int(ver)) if ver.isdigit() else (versions[max(versions)] if versions else None)
        if pick is None and ver.isdigit():
            pick = versions.get(ver)
        src = (pick or {}).get("Source") or ""
        if src:
            out[name.replace("-", "_") + ".py"] = src
    return out


def run_function(fn: dict, event, context: dict) -> dict:
    """lambda_core's runtime seam: run `fn` in a separate Python process."""
    name = fn["name"]
    handler = str(fn.get("handler") or "lambda_function.lambda_handler")
    module, _, hname = handler.rpartition(".")
    module, hname = module or "lambda_function", hname or "lambda_handler"
    wd = _workdir(name)
    wd.mkdir(parents=True, exist_ok=True)
    module_file = wd / (module.replace(".", "/") + ".py")
    module_file.parent.mkdir(parents=True, exist_ok=True)
    module_file.write_text(fn.get("source") or "", encoding="utf-8")
    for fname, src in _layer_sources(fn).items():
        try:
            (wd / fname).write_text(src, encoding="utf-8")
        except Exception:
            pass
    timeout = max(int(fn.get("timeout") or 3), 1)
    env = {**os.environ, **{str(k): str(v) for k, v in (fn.get("env") or {}).items()},
           "AWS_LAMBDA_FUNCTION_NAME": name, "AWS_LAMBDA_FUNCTION_MEMORY_SIZE": str(fn.get("memory_size") or 128),
           "AWS_REGION": _lc.REGION, "AWS_DEFAULT_REGION": _lc.REGION,
           "VYOMI_LAMBDA_ARN": context.get("invoked_function_arn", ""),
           "VYOMI_LAMBDA_REQUEST_ID": context.get("aws_request_id", ""),
           "VYOMI_LAMBDA_TIMEOUT_MS": str(timeout * 1000),
           "PYTHONPATH": str(wd) + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")}
    try:
        proc = subprocess.run([sys.executable, "-c", _HELPER, str(wd), module, str(module_file), hname],
                              input=json.dumps(event if event is not None else {}, default=str),
                              capture_output=True, text=True, timeout=timeout + 1, env=env, cwd=str(wd))
    except subprocess.TimeoutExpired:
        return {"ok": False, "errorType": "Sandbox.Timedout",
                "error": f"Task timed out after {timeout:.2f} seconds"}
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    try:
        out = json.loads(lines[-1]) if lines else None
    except Exception:
        out = None
    if not isinstance(out, dict):
        return {"ok": False, "errorType": "Runtime.ExitError",
                "error": (proc.stderr or proc.stdout or "Lambda runtime error").strip()[-1024:],
                "logs": (proc.stdout or "") + (proc.stderr or "")}
    if proc.stderr:
        out["logs"] = (out.get("logs") or "") + proc.stderr
    return out


_aps.set_lambda_runner(run_function)


def _persist():
    try:
        from core import app_context as ctx
        ctx.persist_state()
    except Exception:
        pass


def _in_background(fn, *args) -> None:
    """Run an async (Event) invocation off the request, in the request's context (space,
    tenant, provider are context variables), then flush the kernel state."""
    cv = contextvars.copy_context()

    def _work():
        try:
            fn(*args)
        finally:
            _persist()
    threading.Thread(target=lambda: cv.run(_work), daemon=True).start()


# ── internal callers (S3 / SNS / EventBridge / Scheduler / API Gateway V2) ─────────────
def _legacy_record(fn: dict, itype: str, event, resp=None, source: str = "", principal: str = "",
                   source_arn: str = "", source_account: str = "") -> dict:
    row = (fn.get("invocations") or [{}])[0] if resp is not None else {}
    status = "accepted"
    payload = None
    if resp is not None:
        failed = bool((resp.headers or {}).get("X-Amz-Function-Error"))
        status = "error" if failed else "success"
        try:
            payload = json.loads(resp.body.decode("utf-8")) if resp.body else None
        except Exception:
            payload = resp.body.decode("utf-8", "replace")
    return {"id": row.get("RequestId", ""), "at": row.get("Timestamp") or _lc._now_iso(),
            "function_name": fn["name"], "function_arn": _lc._fn_arn(fn["name"]),
            "invocation_type": itype, "status": status, "source": source,
            "source_principal": principal, "source_arn": source_arn, "source_account": source_account,
            "request_payload": event, "response_payload": payload if status == "success" else None,
            "stdout": row.get("LogTail", ""), "stderr": "",
            "error": (payload or {}).get("errorMessage", "") if status == "error" and isinstance(payload, dict) else "",
            "traceback": "\n".join((payload or {}).get("stackTrace") or []) if status == "error" and isinstance(payload, dict) else ""}


def invoke(function_name: str, event, invocation_type: str = "RequestResponse", source: str = "",
           source_principal: str = "", source_arn: str = "", source_account: str = "") -> dict:
    """server._lambda_invoke_function on the unified engine (same contract: a pre-v4
    invocation record; HTTPException 404 / 403)."""
    fn = _find(function_name)
    if not fn:
        raise HTTPException(404, detail="ResourceNotFoundException")
    if not _lc.can_invoke(fn, source_principal, source_arn, source_account):
        raise HTTPException(403, detail="AccessDeniedException: Lambda policy does not allow this invocation source.")
    st, name = _store(), fn["name"]
    body = json.dumps(event if event is not None else {}, default=str).encode()
    if (invocation_type or "").strip().lower() == "event":
        _in_background(_lc._invoke, st, name, body)
        return _legacy_record(fn, "Event", event, None, source, source_principal, source_arn, source_account)
    resp = _lc._invoke(st, name, body)
    return _legacy_record(fn, "RequestResponse", event, resp, source, source_principal, source_arn, source_account)


def deliver(arn: str, event: dict, source: str = "events.amazonaws.com") -> bool:
    """EventBridge / Scheduler Lambda target: async invoke by ARN (False if no such function)."""
    fn = _find(arn)
    if not fn:
        return False
    _in_background(_lc._invoke, _store(), fn["name"], json.dumps(event, default=str).encode())
    return True


# ── the pre-v4 console view ────────────────────────────────────────────────────────────
def _stmt_to_perm(st: dict) -> dict:
    cond = st.get("Condition") or {}
    return {"statement_id": st.get("Sid", ""), "action": st.get("Action", "lambda:InvokeFunction"),
            "principal": _lc._statement_principal(st),
            "source_arn": (cond.get("ArnLike") or {}).get("AWS:SourceArn", ""),
            "source_account": (cond.get("StringEquals") or {}).get("AWS:SourceAccount", ""), "created": ""}


def legacy_view(fn: dict) -> dict:
    name = fn["name"]
    versions = [{"version": "$LATEST", "description": fn.get("description", ""), "created": fn.get("last_modified", ""),
                 "code_sha256": fn.get("code_sha256", ""), "runtime": fn.get("runtime"), "handler": fn.get("handler"),
                 "state": "Active", "is_latest": not fn.get("versions")}]
    for v in sorted(fn.get("versions") or {}, key=lambda x: int(x) if str(x).isdigit() else 0, reverse=True):
        s = fn["versions"][v]
        versions.insert(1, {"version": str(v), "description": s.get("description", ""), "created": s.get("last_modified", ""),
                            "code_sha256": s.get("code_sha256", ""), "runtime": s.get("runtime"),
                            "handler": s.get("handler"), "state": "Active", "is_latest": False})
    invocations = [{"id": r.get("RequestId", ""), "at": r.get("Timestamp", ""), "function_name": name,
                    "function_arn": _lc._fn_arn(name), "status": "error" if r.get("Error") else "success",
                    "duration_ms": r.get("DurationInMS", 0), "stdout": r.get("LogTail", ""), "stderr": "",
                    "error": r.get("ErrorMessage", "")} for r in fn.get("invocations") or []]
    perms = [_stmt_to_perm(s) for s in (fn.get("policy_statements") or {}).values()]
    policy = {"Version": "2012-10-17", "Id": f"{name}/policy", "Statement": list((fn.get("policy_statements") or {}).values())}
    view = {
        "function_name": name, "function_arn": _lc._fn_arn(name), "description": fn.get("description", ""),
        "runtime": fn.get("runtime"), "handler": fn.get("handler"), "role": fn.get("role", ""),
        "timeout": fn.get("timeout"), "memory_size": fn.get("memory_size"), "environment": dict(fn.get("env") or {}),
        "package_type": "Zip", "state": "Active", "created": fn.get("created") or fn.get("last_modified", ""),
        "last_modified": fn.get("last_modified", ""), "code": fn.get("source", ""), "code_sha256": fn.get("code_sha256", ""),
        "tags": [{"Key": k, "Value": v} for k, v in (fn.get("tags") or {}).items()], "layers": list(fn.get("layers") or []),
        "versions": versions, "invocations": invocations, "permissions": perms, "policy": policy,
        "policy_revision_id": fn.get("revision_id", ""),
        "invocation_count": len(invocations), "version_count": len(versions), "policy_statement_count": len(perms),
    }
    try:
        import server as _srv
        view["triggers"] = _srv._lambda_triggers_for_function(view)
    except Exception:
        view["triggers"] = []
    view["trigger_count"] = len(view["triggers"])
    return view


# ── native wire ────────────────────────────────────────────────────────────────────────
def _native_path(request: Request) -> str:
    raw = request.scope.get("raw_path")
    p = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) and raw else request.url.path
    p = p.split("?", 1)[0]
    if p.startswith("/_wire/"):
        p = p[len("/_wire"):]
    from urllib.parse import unquote
    return unquote(p)


async def _native(request: Request):
    body = await request.body()
    path = _native_path(request)
    headers = dict(request.headers)
    itype = (headers.get("x-amz-invocation-type") or request.query_params.get("InvocationType") or "")
    if request.method == "POST" and itype == "Event" and path.rstrip("/").endswith("/invocations"):
        segs = [s for s in path.split("/") if s]
        fn = _find(segs[2]) if len(segs) >= 4 else None
        if fn is None:
            return _wi.to_response(_wi.dispatch_service("lambda", "POST", path, dict(request.query_params), headers, body))
        hdrs = {k: v for k, v in headers.items() if k.lower() != "x-amz-invocation-type"}
        _in_background(_wi.dispatch_service, "lambda", "POST", path, dict(request.query_params), hdrs, body)
        return Response(status_code=202, headers={"x-amzn-requestid": _lc.uuid.uuid4().hex})
    out = _wi.dispatch_service("lambda", request.method, path, dict(request.query_params), headers, body)
    return _wi.to_response(out)


# ── classic console REST ───────────────────────────────────────────────────────────────
def _call(method: str, path: str, body: dict | None = None, query: dict | None = None):
    out = _wi.dispatch_service("lambda", method, path, query or {}, {"content-type": "application/json"},
                               json.dumps(body).encode() if body is not None else b"")
    try:
        data = json.loads(out["body"] or b"{}")
    except Exception:
        data = {}
    return out["status"], data


def _fail(status: int, data: dict):
    code = (data.get("error") or {}).get("code") or "Error"
    msg = data.get("Message") or (data.get("error") or {}).get("message", "")
    if status == 404:
        raise HTTPException(404, detail="ResourceNotFoundException")
    raise HTTPException(status, detail=f"{code}: {msg}")


async def _json(request: Request) -> dict:
    try:
        d = await request.json()
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _pick(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _tags_in(tags) -> dict:
    return _aps._legacy_tags(tags)


def _register_console(app) -> None:
    from core import app_context as ctx

    @app.get("/api/lambda/functions", include_in_schema=False)
    async def list_functions():
        fns = [legacy_view(f) for f in sorted(_fns().values(), key=lambda f: (f.get("created", ""), f["name"]))]
        return {"functions": fns, "count": len(fns)}

    @app.post("/api/lambda/functions", include_in_schema=False)
    async def create_function(request: Request):
        d = await _json(request)
        name = str(_pick(d, "function_name", "FunctionName", "functionName", "name", default="")).strip()
        if not name:
            raise HTTPException(400, detail="MissingParameter: function_name is required.")
        ctx.enforce_quantity_cap("lambda_function")
        handler = str(_pick(d, "handler", "Handler", default="lambda_function.lambda_handler"))
        code = str(_pick(d, "code", default="") or "").strip() or _default_code(name)
        st, data = _call("POST", "/2015-03-31/functions", {
            "FunctionName": name, "Runtime": _pick(d, "runtime", "Runtime", default="python3.12"),
            "Handler": handler, "Role": _pick(d, "role", "Role", default=None),
            "Description": _pick(d, "description", "Description", default=""),
            "Timeout": _pick(d, "timeout", "Timeout", default=3), "MemorySize": _pick(d, "memory_size", "MemorySize", default=128),
            "Environment": {"Variables": dict(_pick(d, "environment", default={}) or {})},
            "Tags": _tags_in(_pick(d, "tags", "Tags", default=None)), "Layers": list(_pick(d, "layers", "Layers", default=[]) or []),
            "Code": {"Source": code}})
        if st >= 300:
            if st == 409:
                raise HTTPException(409, detail="ResourceConflictException: Function already exists.")
            _fail(st, data)
        fn = _fns()[name]
        fn["created"] = fn.get("created") or fn["last_modified"]
        try:
            import server as _srv
            b = _srv._cloudsim_runtime_bundle("lambda")
            fn.update({"runtime_bundle_id": b.get("id", ""), "runtime_bundle_name": b.get("name", ""),
                       "runtime_bundle_kind": b.get("kind", "")})
        except Exception:
            pass
        ctx.record_usage("lambda.create_function", {"function_name": name})
        return legacy_view(fn)

    def _need(name: str) -> dict:
        fn = _find(name)
        if not fn:
            raise HTTPException(404, detail="ResourceNotFoundException")
        return fn

    @app.get("/api/lambda/functions/{function_name}", include_in_schema=False)
    async def get_function(function_name: str):
        return legacy_view(_need(function_name))

    @app.api_route("/api/lambda/functions/{function_name}/code", methods=["PUT", "POST"], include_in_schema=False)
    async def update_code(function_name: str, request: Request):
        fn = _need(function_name)
        d = await _json(request)
        code = str(d.get("code") or "").strip()
        body = {"Source": code} if code else ({"ZipFile": d["ZipFile"]} if d.get("ZipFile") else None)
        if body is None:
            raise HTTPException(400, detail="MissingParameter: code is required.")
        st, data = _call("PUT", f"/2015-03-31/functions/{fn['name']}/code", body)
        if st >= 300:
            _fail(st, data)
        ctx.record_usage("lambda.update_function_code", {"function_name": fn["name"]})
        return legacy_view(_fns()[fn["name"]])

    @app.api_route("/api/lambda/functions/{function_name}/configuration", methods=["PUT", "POST"], include_in_schema=False)
    async def update_config(function_name: str, request: Request):
        fn = _need(function_name)
        d = await _json(request)
        body = {}
        for k, api in (("runtime", "Runtime"), ("handler", "Handler"), ("role", "Role"), ("description", "Description"),
                       ("timeout", "Timeout"), ("memory_size", "MemorySize")):
            if d.get(k) is not None:
                body[api] = d[k]
        if d.get("timeout") is not None:
            body["Timeout"] = max(1, int(d["timeout"]))
        if d.get("memory_size") is not None:
            body["MemorySize"] = max(128, int(d["memory_size"]))
        if d.get("environment") is not None:
            body["Environment"] = {"Variables": dict(d["environment"])}
        st, data = _call("PUT", f"/2015-03-31/functions/{fn['name']}/configuration", body)
        if st >= 300:
            _fail(st, data)
        if d.get("tags") is not None:
            _fns()[fn["name"]]["tags"] = _tags_in(d["tags"])
        if d.get("code"):
            _call("PUT", f"/2015-03-31/functions/{fn['name']}/code", {"Source": str(d["code"])})
        ctx.record_usage("lambda.update_function_configuration", {"function_name": fn["name"]})
        return legacy_view(_fns()[fn["name"]])

    @app.delete("/api/lambda/functions/{function_name}", include_in_schema=False)
    async def delete_function(function_name: str):
        fn = _need(function_name)
        st, data = _call("DELETE", f"/2015-03-31/functions/{fn['name']}")
        if st >= 300:
            _fail(st, data)
        ctx.record_usage("lambda.delete_function", {"function_name": fn["name"]})
        return {"deleted": True, "function_name": fn["name"]}

    @app.get("/api/lambda/functions/{function_name}/policy", include_in_schema=False)
    async def get_policy(function_name: str):
        v = legacy_view(_need(function_name))
        return {"function_name": v["function_name"], "function_arn": v["function_arn"],
                "Policy": json.dumps(v["policy"]), "RevisionId": v["policy_revision_id"]}

    async def _add_perm(function_name: str, request: Request):
        fn = _need(function_name)
        d = await _json(request)
        principal = str(d.get("principal") or "").strip()
        if not principal:
            raise HTTPException(400, detail="MissingParameter: principal is required.")
        sid = str(d.get("statement_id") or "").strip() or f"sid-{_lc.uuid.uuid4().hex[:12]}"
        st, data = _call("POST", f"/2015-03-31/functions/{fn['name']}/policy", {
            "StatementId": sid, "Action": d.get("action") or "lambda:InvokeFunction", "Principal": principal,
            **({"SourceArn": d["source_arn"]} if d.get("source_arn") else {}),
            **({"SourceAccount": d["source_account"]} if d.get("source_account") else {})})
        if st >= 300:
            if st == 409:
                raise HTTPException(409, detail="ResourceConflictException: statement_id already exists.")
            _fail(st, data)
        v = legacy_view(_fns()[fn["name"]])
        perm = next((p for p in v["permissions"] if p["statement_id"] == sid), {})
        return {"function_name": v["function_name"], "function_arn": v["function_arn"], "statement": perm,
                "Policy": json.dumps(v["policy"]), "RevisionId": v["policy_revision_id"]}

    app.add_api_route("/api/lambda/functions/{function_name}/policy", _add_perm, methods=["POST"], include_in_schema=False)
    app.add_api_route("/api/lambda/functions/{function_name}/permission", _add_perm, methods=["POST"], include_in_schema=False)

    @app.delete("/api/lambda/functions/{function_name}/policy/{statement_id}", include_in_schema=False)
    async def remove_permission(function_name: str, statement_id: str):
        fn = _need(function_name)
        st, data = _call("DELETE", f"/2015-03-31/functions/{fn['name']}/policy/{statement_id}")
        if st >= 300:
            _fail(st, data)
        return {"deleted": True, "function_name": fn["name"], "statement_id": statement_id}

    @app.get("/api/lambda/functions/{function_name}/invocations", include_in_schema=False)
    async def list_invocations(function_name: str):
        v = legacy_view(_need(function_name))
        return {"function_name": v["function_name"], "function_arn": v["function_arn"],
                "invocations": v["invocations"], "count": len(v["invocations"])}

    @app.get("/api/lambda/functions/{function_name}/versions", include_in_schema=False)
    async def list_versions(function_name: str):
        v = legacy_view(_need(function_name))
        return {"function_name": v["function_name"], "function_arn": v["function_arn"],
                "versions": v["versions"], "count": len(v["versions"])}

    @app.post("/api/lambda/functions/{function_name}/versions", include_in_schema=False)
    async def publish_version(function_name: str, request: Request):
        fn = _need(function_name)
        d = await _json(request)
        st, data = _call("POST", f"/2015-03-31/functions/{fn['name']}/versions", {"Description": d.get("description", "")})
        if st >= 300:
            _fail(st, data)
        v = legacy_view(_fns()[fn["name"]])
        return {"function_name": v["function_name"], "function_arn": v["function_arn"],
                "version": next((x for x in v["versions"] if x["version"] == data.get("Version")), {})}

    @app.post("/api/lambda/functions/{function_name}/invoke", include_in_schema=False)
    async def invoke_function(function_name: str, request: Request):
        d = await _json(request)
        rec = invoke(function_name, d.get("payload", {}), invocation_type=d.get("invocation_type") or "RequestResponse")
        return {"function_name": rec["function_name"], "function_arn": rec["function_arn"],
                "invocation_type": rec["invocation_type"], "status": rec["status"],
                "payload": rec.get("response_payload") if rec["status"] == "success" else None,
                "stdout": rec.get("stdout", ""), "stderr": rec.get("stderr", ""), "error": rec.get("error", ""),
                "traceback": rec.get("traceback", ""), "at": rec.get("at", "")}

    # layers (the classic console's single-version view of the core's layer versions)
    def _layer_view(name: str, entry: dict) -> dict:
        versions = entry.get("versions") or {}
        latest = max(versions, key=lambda x: int(x)) if versions else 0
        v = versions.get(latest) or {}
        arn = _lc._layer_arn(name)
        return {"layer_name": name, "layer_arn": arn, "layer_version_arn": f"{arn}:{latest}",
                "description": v.get("Description", ""), "runtime": (v.get("CompatibleRuntimes") or [""])[0],
                "code": v.get("Source", ""), "license_info": v.get("LicenseInfo", ""),
                "latest_version": int(latest or 0), "created": v.get("CreatedDate", "")}

    @app.get("/api/lambda/layers", include_in_schema=False)
    async def list_layers():
        layers = [_layer_view(n, e) for n, e in _lc._layers(_store()).items() if (e or {}).get("versions")]
        layers.sort(key=lambda x: x.get("created", ""))
        return {"layers": layers, "count": len(layers)}

    @app.post("/api/lambda/layers", include_in_schema=False)
    async def create_layer(request: Request):
        d = await _json(request)
        name = str(d.get("name") or "").strip()
        if not name:
            raise HTTPException(400, detail="Layer name is required")
        st, data = _call("POST", f"/2015-03-31/layers/{name}/versions", {
            "Description": d.get("description", ""), "CompatibleRuntimes": [d.get("runtime") or "python3.12"],
            "LicenseInfo": d.get("license_info", ""), "Content": {"Source": d.get("code", "")}})
        if st >= 300:
            _fail(st, data)
        ctx.record_usage("lambda.create_layer", {"layer_name": name, "version": data.get("Version")})
        return _layer_view(name, _lc._layers(_store())[name])

    @app.get("/api/lambda/layers/{name}", include_in_schema=False)
    async def get_layer(name: str):
        e = _lc._layers(_store()).get(name)
        if not e or not e.get("versions"):
            raise HTTPException(404, detail="ResourceNotFoundException")
        return _layer_view(name, e)

    @app.delete("/api/lambda/layers/{name}", include_in_schema=False)
    async def delete_layer(name: str):
        layers = _lc._layers(_store())
        if name not in layers:
            raise HTTPException(404, detail="ResourceNotFoundException")
        del layers[name]
        ctx.record_usage("lambda.delete_layer", {"layer_name": name})
        return {"deleted": True}


def _default_code(name: str) -> str:
    return textwrap.dedent(f"""
        def lambda_handler(event, context):
            return {{
                "message": "Hello from Lambda",
                "function_name": "{name}",
                "received_event": event,
            }}
        """).strip() + "\n"


def register(app) -> None:
    """Mount the native Lambda REST + the classic console REST on the shared engine (BEFORE
    the provider routes and the net-new mount — Starlette matches in registration order)."""
    if not _wi.is_unified("lambda"):
        return
    app.add_route("/2015-03-31/{rest:path}", _native, methods=_METHODS)
    _register_console(app)

