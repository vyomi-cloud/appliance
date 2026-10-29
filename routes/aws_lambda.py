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


# AWS SDK-native aliases (2015-03-31 paths)
def api_lambda_list_functions_aws():
    return api_lambda_list_functions()


def api_lambda_create_function_aws(req: LambdaFunctionRequest):
    return api_lambda_create_function(req)


def api_lambda_get_function_aws(function_name: str):
    return api_lambda_get_function(function_name)


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
    return api_lambda_update_function_configuration(function_name, req)


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
    response_payload = record.get("response_payload")
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
        headers["X-Amz-Function-Error"] = "Handled"
    return Response(content=body_bytes, media_type=media_type, headers=headers)


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
