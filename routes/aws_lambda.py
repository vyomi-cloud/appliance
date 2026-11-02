"""AWS Lambda function CRUD, invocation, versioning, permissions.

Extracted from server.py — contains both the REST API route handlers and
the underlying helper / business-logic functions.
"""
from __future__ import annotations

import base64
import copy
import io
import json
import uuid
import zipfile
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from core import app_context as ctx
from core.models import (
    LambdaFunctionRequest,
    LambdaFunctionUpdateRequest,
    LambdaInvokeRequest,
    LambdaPermissionRequest,
    LambdaVersionRequest,
)

# ---------------------------------------------------------------------------
# Lazy back-reference to server.py for helper functions that haven't been
# fully extracted yet. Every helper accessed via _srv() is a candidate for
# future inlining into this module.
# ---------------------------------------------------------------------------


def _srv():
    import server as _s
    return _s


# ---------------------------------------------------------------------------
# Helper / business-logic proxies
# ---------------------------------------------------------------------------

def _lambda_state():
    return ctx.lambda_state


def _lambda_find_function(function_name: str):
    return _srv()._lambda_find_function(function_name)


def _lambda_function_view(function: dict) -> dict:
    return _srv()._lambda_function_view(function)


def _lambda_list_functions() -> list[dict]:
    return _srv()._lambda_list_functions()


def _lambda_create_function_record(req):
    return _srv()._lambda_create_function_record(req)


def _lambda_update_function_code(function: dict, code: str) -> dict:
    return _srv()._lambda_update_function_code(function, code)


def _lambda_update_function_configuration(function: dict, req) -> dict:
    return _srv()._lambda_update_function_configuration(function, req)


def _lambda_delete_function(function_name: str):
    return _srv()._lambda_delete_function(function_name)


def _lambda_get_policy(function: dict) -> dict:
    return _srv()._lambda_get_policy(function)


def _lambda_add_permission(function: dict, req):
    return _srv()._lambda_add_permission(function, req)


def _lambda_remove_permission(function: dict, statement_id: str):
    return _srv()._lambda_remove_permission(function, statement_id)


def _lambda_invocations_view(function: dict) -> list[dict]:
    return _srv()._lambda_invocations_view(function)


def _lambda_versions_view(function: dict) -> list[dict]:
    return _srv()._lambda_versions_view(function)


def _lambda_publish_version(function: dict, description: str = "") -> dict:
    return _srv()._lambda_publish_version(function, description)


def _lambda_invoke_response(function_name: str, event_payload: Any, **kw) -> dict:
    return _srv()._lambda_invoke_response(function_name, event_payload, **kw)


def _lambda_invoke_function(function_name: str, event_payload: Any, **kw) -> dict:
    return _srv()._lambda_invoke_function(function_name, event_payload, **kw)


# ---------------------------------------------------------------------------
# Route handler functions (console REST API)
# ---------------------------------------------------------------------------

def api_lambda_list_functions():
    functions = [_lambda_function_view(f) for f in _lambda_list_functions()]
    return {"functions": functions, "count": len(functions)}


def api_lambda_create_function(req: LambdaFunctionRequest):
    ctx.enforce_quantity_cap("lambda_function")
    function = _lambda_create_function_record(req)
    bundle = _srv()._cloudsim_runtime_bundle("lambda")
    function["runtime_bundle_id"] = bundle.get("id", "")
    function["runtime_bundle_name"] = bundle.get("name", "")
    function["runtime_bundle_kind"] = bundle.get("kind", "")
    ctx.record_usage("lambda.create_function", {"function_name": function.get("function_name", "")})
    return _lambda_function_view(function)


def api_lambda_get_function(function_name: str):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    return _lambda_function_view(function)


def api_lambda_update_function_code(function_name: str, payload: dict[str, Any]):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    code = str(payload.get("code", "") or "")
    zip_b64 = payload.get("ZipFile")
    if not code and zip_b64:
        # Official SDK wire: ZipFile is base64 of a zip archive holding the handler module.
        try:
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(zip_b64))) as zf:
                module = str(function.get("handler", "lambda_function.lambda_handler")).rsplit(".", 1)[0].replace(".", "/") + ".py"
                names = zf.namelist()
                pick = module if module in names else next((n for n in names if n.endswith(".py")), "")
                code = zf.read(pick).decode("utf-8") if pick else ""
        except Exception:
            raise HTTPException(400, detail="InvalidParameterValueException: Could not unzip uploaded file.")
    updated = _lambda_update_function_code(function, code)
    ctx.record_usage("lambda.update_function_code", {"function_name": function_name})
    return _lambda_function_view(updated)


def api_lambda_update_function_configuration(function_name: str, req: LambdaFunctionUpdateRequest):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    updated = _lambda_update_function_configuration(function, req)
    ctx.record_usage("lambda.update_function_configuration", {"function_name": function_name})
    return _lambda_function_view(updated)


def api_lambda_delete_function(function_name: str):
    _lambda_delete_function(function_name)
    ctx.record_usage("lambda.delete_function", {"function_name": function_name})
    return {"deleted": True, "function_name": function_name}


def api_lambda_get_policy(function_name: str):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    policy = _lambda_get_policy(function)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], **policy}


def api_lambda_add_permission(function_name: str, req: LambdaPermissionRequest):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    permission = _lambda_add_permission(function, req)
    policy = _lambda_get_policy(function)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], "statement": permission, **policy}


def api_lambda_remove_permission(function_name: str, statement_id: str):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    _lambda_remove_permission(function, statement_id)
    return {"deleted": True, "function_name": function["function_name"], "statement_id": statement_id}


def api_lambda_list_invocations(function_name: str):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    invocations = _lambda_invocations_view(function)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], "invocations": invocations, "count": len(invocations)}


def api_lambda_list_versions(function_name: str):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    versions = _lambda_versions_view(function)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], "versions": versions, "count": len(versions)}


def api_lambda_publish_version(function_name: str, payload: LambdaVersionRequest):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    version = _lambda_publish_version(function, payload.description)
    return {"function_name": function["function_name"], "function_arn": function["function_arn"], "version": version}


def api_lambda_invoke_function(function_name: str, payload: LambdaInvokeRequest):
    return _lambda_invoke_response(function_name, payload.payload, invocation_type=payload.invocation_type)


def _sdk_config(view: dict) -> dict:
    """The FunctionConfiguration shape the official SDKs parse (PascalCase), built from the
    appliance's snake_case function view."""
    env = view.get("environment") or {}
    variables = env.get("Variables", env) if isinstance(env, dict) else {}
    cfg = {
        "FunctionName": view.get("function_name"), "FunctionArn": view.get("function_arn"),
        "Runtime": view.get("runtime"), "Role": view.get("role"), "Handler": view.get("handler"),
        "CodeSize": len((view.get("code") or "").encode("utf-8")), "CodeSha256": view.get("code_sha256") or "",
        "Description": view.get("description", ""), "Timeout": view.get("timeout"),
        "MemorySize": view.get("memory_size"), "LastModified": view.get("last_modified"),
        "Version": "$LATEST", "State": view.get("state", "Active"), "LastUpdateStatus": "Successful",
        "PackageType": view.get("package_type", "Zip"), "Architectures": ["x86_64"],
        "TracingConfig": {"Mode": "PassThrough"}, "RevisionId": view.get("policy_revision_id") or str(uuid.uuid4()),
    }
    if variables:
        cfg["Environment"] = {"Variables": {str(k): str(v) for k, v in variables.items()}}
    return cfg


# AWS SDK-native aliases (2015-03-31 paths)
def api_lambda_list_functions_aws():
    base = api_lambda_list_functions()
    return {**base, "Functions": [_sdk_config(v) for v in base["functions"]]}


def api_lambda_create_function_aws(req: LambdaFunctionRequest):
    view = api_lambda_create_function(req)
    return {**view, **_sdk_config(view)}


def api_lambda_get_function_aws(function_name: str):
    view = api_lambda_get_function(function_name)
    return {**view, "Configuration": _sdk_config(view),
            "Code": {"RepositoryType": "S3", "Location": f"https://awslambda-us-east-1-tasks.s3.us-east-1.amazonaws.com/snapshots/{view.get('function_name')}"},
            "Tags": {t.get("key", ""): t.get("value", "") for t in (view.get("tags") or []) if isinstance(t, dict)}}


def api_lambda_delete_function_aws(function_name: str):
    return api_lambda_delete_function(function_name)


def api_lambda_get_policy_aws(function_name: str):
    return api_lambda_get_policy(function_name)


def api_lambda_add_permission_aws(function_name: str, req: LambdaPermissionRequest):
    return api_lambda_add_permission(function_name, req)


def api_lambda_remove_permission_aws(function_name: str, statement_id: str):
    return api_lambda_remove_permission(function_name, statement_id)


def api_lambda_update_function_code_aws(function_name: str, payload: dict[str, Any]):
    view = api_lambda_update_function_code(function_name, payload)
    # UpdateFunctionCode output (FunctionConfiguration) for the official SDKs.
    return {**view,
            "FunctionName": view.get("function_name"), "FunctionArn": view.get("function_arn"),
            "Runtime": view.get("runtime"), "Role": view.get("role"), "Handler": view.get("handler"),
            "CodeSha256": view.get("code_sha256"), "CodeSize": len((view.get("code") or "").encode("utf-8")),
            "Description": view.get("description", ""), "Timeout": view.get("timeout"),
            "MemorySize": view.get("memory_size"), "LastModified": view.get("last_modified"),
            "Version": "$LATEST", "State": view.get("state", "Active"),
            "PackageType": view.get("package_type", "Zip"), "RevisionId": str(uuid.uuid4())}


def api_lambda_update_function_configuration_aws(function_name: str, req: LambdaFunctionUpdateRequest):
    view = api_lambda_update_function_configuration(function_name, req)
    return {**view, **_sdk_config(view)} if isinstance(view, dict) and view.get("function_name") else view


def api_lambda_publish_version_aws(function_name: str, payload: LambdaVersionRequest):
    return api_lambda_publish_version(function_name, payload)


def api_lambda_list_versions_aws(function_name: str):
    return api_lambda_list_versions(function_name)


async def api_lambda_invoke_function_aws(function_name: str, request: Request):
    function = _lambda_find_function(function_name)
    if not function:
        raise HTTPException(404, detail="ResourceNotFoundException")
    invocation_type = request.headers.get("x-amz-invocation-type") or request.query_params.get("InvocationType", "RequestResponse")
    body = await request.body()
    payload: dict = {}
    if body:
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {"body": body.decode("utf-8", errors="replace")}
    record = _lambda_invoke_function(function_name, payload, invocation_type=invocation_type)
    if invocation_type and invocation_type.lower() == "event":
        return Response(status_code=202)
    log_text = _write_cloudwatch_logs(function, record)
    response_payload = record.get("response_payload")
    if record.get("status") == "error":
        # Real Lambda: 200 + X-Amz-Function-Error, body {errorMessage, errorType, stackTrace}.
        tb = (record.get("traceback") or "").strip().splitlines()
        last = tb[-1] if tb else ""
        etype = last.split(":", 1)[0].strip() if ":" in last else (last or "Error")
        response_payload = {"errorMessage": record.get("error", ""), "errorType": etype.rsplit(".", 1)[-1],
                            "stackTrace": [ln for ln in tb[:-1] if ln.strip()]}
    if isinstance(response_payload, (dict, list)):
        body_bytes = json.dumps(response_payload, default=str).encode("utf-8")
        media_type = "application/json"
    elif isinstance(response_payload, bytes):
        body_bytes = response_payload
        media_type = "application/octet-stream"
    elif response_payload is None:
        body_bytes = b""
        media_type = "application/json"
    else:
        body_bytes = str(response_payload).encode("utf-8")
        media_type = "text/plain"
    headers: dict[str, str] = {
        "X-Amz-Executed-Version": "$LATEST",
    }
    if record.get("status") == "error":
        headers["X-Amz-Function-Error"] = "Unhandled"
    if (request.headers.get("x-amz-log-type") or "").lower() == "tail":
        # last 4 KB of the invocation log, base64 — what boto3 returns as LogResult
        headers["X-Amz-Log-Result"] = base64.b64encode(log_text.encode("utf-8")[-4096:]).decode("ascii")
    return Response(content=body_bytes, media_type=media_type, headers=headers)


def _write_cloudwatch_logs(function: dict, record: dict) -> str:
    """Mirror an invocation's output into CloudWatch Logs (/aws/lambda/<fn>), as real Lambda does,
    and return the START/stdout/END/REPORT text used for LogType=Tail."""
    import time as _time
    name = function.get("function_name", "")
    rid = str(record.get("id") or uuid.uuid4())
    out = "".join(str(record.get(k) or "") for k in ("stdout", "stderr"))
    lines = [f"START RequestId: {rid} Version: $LATEST"]
    lines += [ln for ln in out.splitlines() if ln.strip()]
    if record.get("status") == "error" and record.get("error"):
        lines.append(f"[ERROR] {record.get('error')}")
    lines += [f"END RequestId: {rid}",
              f"REPORT RequestId: {rid}\tDuration: 1.00 ms\tBilled Duration: 1 ms\tMemory Size: {function.get('memory_size', 128)} MB\tMax Memory Used: 32 MB"]
    try:
        from routes import aws_logs
        from core import logs_core
        group = f"/aws/lambda/{name}"
        stream = f"{_time.strftime('%Y/%m/%d')}/[$LATEST]{uuid.uuid4().hex}"
        hdr = "Logs_20140328."
        logs_core.dispatch(aws_logs.STORE, hdr + "CreateLogGroup", {"logGroupName": group})   # exists -> benign error
        logs_core.dispatch(aws_logs.STORE, hdr + "CreateLogStream", {"logGroupName": group, "logStreamName": stream})
        now = int(_time.time() * 1000)
        logs_core.dispatch(aws_logs.STORE, hdr + "PutLogEvents", {
            "logGroupName": group, "logStreamName": stream,
            "logEvents": [{"timestamp": now + i, "message": ln + "\n"} for i, ln in enumerate(lines)]})
    except Exception:
        pass
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Function URLs (CreateFunctionUrlConfig & friends; API version 2021-10-31)
# ---------------------------------------------------------------------------

def _origin(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:9000"
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    return f"{proto}://{host}"


def _url_view(function: dict, request: Request) -> dict:
    cfg = function["function_url"]
    return {"FunctionUrl": f"{_origin(request)}/lambda-url/{cfg['url_id']}/", "FunctionArn": function.get("function_arn"),
            "AuthType": cfg.get("auth_type", "NONE"), "Cors": cfg.get("cors") or {},
            "CreationTime": cfg.get("created"), "LastModifiedTime": cfg.get("modified"),
            "InvokeMode": cfg.get("invoke_mode", "BUFFERED")}


def _err(status: int, code: str, message: str) -> Response:
    return Response(content=json.dumps({"Message": message}), status_code=status,
                    media_type="application/json", headers={"x-amzn-errortype": code})


def _fn_or_404(function_name: str):
    function = _lambda_find_function(function_name)
    return function


async def _body(request: Request) -> dict:
    try:
        d = await request.json()
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def register_function_urls(app: FastAPI) -> None:
    import datetime as _dt

    def _ts():
        return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")

    @app.post("/2021-10-31/functions/{function_name}/url")
    async def lambda_create_url(function_name: str, request: Request):
        fn = _fn_or_404(function_name)
        if not fn:
            return _err(404, "ResourceNotFoundException", f"Function not found: {function_name}")
        if fn.get("function_url"):
            return _err(409, "ResourceConflictException", "Failed to create function url config: it already exists.")
        b = await _body(request)
        if b.get("AuthType") not in ("NONE", "AWS_IAM"):
            return _err(400, "InvalidParameterValueException", "AuthType must be NONE or AWS_IAM.")
        fn["function_url"] = {"url_id": uuid.uuid4().hex[:32], "auth_type": b["AuthType"], "cors": b.get("Cors") or {},
                              "invoke_mode": b.get("InvokeMode", "BUFFERED"), "created": _ts(), "modified": _ts()}
        _srv()._persist_state()
        return Response(content=json.dumps(_url_view(fn, request)), status_code=201, media_type="application/json")

    @app.get("/2021-10-31/functions/{function_name}/url")
    async def lambda_get_url(function_name: str, request: Request):
        fn = _fn_or_404(function_name)
        if not fn or not fn.get("function_url"):
            return _err(404, "ResourceNotFoundException", f"The resource you requested does not exist: {function_name}")
        return Response(content=json.dumps(_url_view(fn, request)), media_type="application/json")

    @app.put("/2021-10-31/functions/{function_name}/url")
    async def lambda_update_url(function_name: str, request: Request):
        fn = _fn_or_404(function_name)
        if not fn or not fn.get("function_url"):
            return _err(404, "ResourceNotFoundException", f"The resource you requested does not exist: {function_name}")
        b = await _body(request)
        cfg = fn["function_url"]
        cfg["auth_type"] = b.get("AuthType", cfg["auth_type"])
        cfg["cors"] = b.get("Cors", cfg.get("cors") or {})
        cfg["invoke_mode"] = b.get("InvokeMode", cfg.get("invoke_mode", "BUFFERED"))
        cfg["modified"] = _ts()
        _srv()._persist_state()
        return Response(content=json.dumps(_url_view(fn, request)), media_type="application/json")

    @app.delete("/2021-10-31/functions/{function_name}/url")
    async def lambda_delete_url(function_name: str):
        fn = _fn_or_404(function_name)
        if not fn or not fn.get("function_url"):
            return _err(404, "ResourceNotFoundException", f"The resource you requested does not exist: {function_name}")
        fn.pop("function_url", None)
        _srv()._persist_state()
        return Response(status_code=204)

    @app.get("/2021-10-31/functions/{function_name}/urls")
    async def lambda_list_urls(function_name: str, request: Request):
        fn = _fn_or_404(function_name)
        if not fn:
            return _err(404, "ResourceNotFoundException", f"Function not found: {function_name}")
        return Response(content=json.dumps({"FunctionUrlConfigs": [_url_view(fn, request)] if fn.get("function_url") else []}),
                        media_type="application/json")

    @app.api_route("/lambda-url/{url_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
    @app.api_route("/lambda-url/{url_id}/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
    async def lambda_url_invoke(url_id: str, request: Request, rest: str = ""):
        fn = next((f for f in _lambda_state().setdefault("functions", {}).values()
                   if isinstance(f, dict) and (f.get("function_url") or {}).get("url_id") == url_id), None)
        if not fn:
            return _err(404, "ResourceNotFoundException", "Function URL not found.")
        raw = (await request.body()).decode("utf-8", errors="replace")
        event = {"version": "2.0", "routeKey": "$default", "rawPath": "/" + rest,
                 "rawQueryString": request.url.query,
                 "headers": {k.lower(): v for k, v in request.headers.items()},
                 "requestContext": {"http": {"method": request.method, "path": "/" + rest,
                                             "sourceIp": request.client.host if request.client else "127.0.0.1"}},
                 "body": raw, "isBase64Encoded": False}
        record = _lambda_invoke_function(fn["function_name"], event, invocation_type="RequestResponse")
        _write_cloudwatch_logs(fn, record)
        out = record.get("response_payload")
        if record.get("status") == "error":
            return Response(content=json.dumps({"Message": "Internal Server Error"}), status_code=502, media_type="application/json")
        if isinstance(out, dict) and "statusCode" in out:
            hdrs = {str(k): str(v) for k, v in (out.get("headers") or {}).items()}
            body = out.get("body", "")
            if out.get("isBase64Encoded"):
                body = base64.b64decode(body or "")
            elif not isinstance(body, (bytes, str)):
                body = json.dumps(body)
            ctype = next((v for k, v in hdrs.items() if k.lower() == "content-type"), "application/json")
            hdrs = {k: v for k, v in hdrs.items() if k.lower() != "content-type"}
            return Response(content=body, status_code=int(out["statusCode"]), media_type=ctype, headers=hdrs)
        return Response(content=json.dumps(out, default=str), media_type="application/json")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(app: FastAPI) -> None:
    """Register Lambda routes on the FastAPI app.

    NOTE: Lambda routes are currently registered via providers/aws_routes.py
    using the dynamic _proxy/_add_route mechanism.  This register() function
    is provided for future use when the migration is complete and aws_routes
    can delegate here instead.
    """
    pass  # Routes registered via providers/aws_routes.py spec table
