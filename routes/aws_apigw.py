"""AWS API Gateway REST API CRUD, deployment, stages, invocation.

Extracted from server.py — contains all API Gateway helper functions and
route handlers for /api/apigateway/* endpoints.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from core import app_context as ctx
from core.models import (
    APIGatewayDeploymentRequest,
    APIGatewayIntegrationRequest,
    APIGatewayMethodRequest,
    APIGatewayRequest,
    APIGatewayResourceRequest,
    APIGatewayStageRequest,
)

# ---------------------------------------------------------------------------
# Lazy back-reference to server.py
# ---------------------------------------------------------------------------


def _srv():
    import server as _s
    return _s


# ---------------------------------------------------------------------------
# Aliases for shared utilities
# ---------------------------------------------------------------------------

_now = ctx.now
_id = ctx.id_gen
_record_usage = ctx.record_usage

# ---------------------------------------------------------------------------
# State access
# ---------------------------------------------------------------------------

apigw_state = ctx.apigw_state


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _apigw_state() -> dict:
    return apigw_state


def _apigw_api(api_id: str) -> dict | None:
    return _apigw_state().setdefault("apis", {}).get(api_id)


def _apigw_route_key(resource_id: str, method: str) -> str:
    return f"{resource_id}::{method.upper()}"


def _apigw_resource_path(parent_path: str, path_part: str) -> str:
    parent_path = parent_path if parent_path else "/"
    if parent_path == "/":
        return "/" + path_part.strip("/")
    return parent_path.rstrip("/") + "/" + path_part.strip("/")


def _apigw_valid_stage_name(stage_name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]{1,128}", stage_name or ""))


def _apigw_path_regex(path: str) -> str:
    if path == "/":
        return r"^/?$"
    parts = []
    for segment in path.strip("/").split("/"):
        if segment == "{proxy+}":
            parts.append(r".+")
        elif segment.startswith("{") and segment.endswith("}"):
            parts.append(r"[^/]+")
        else:
            parts.append(re.escape(segment))
    return r"^/" + "/".join(parts) + r"/?$"


def _apigw_resource_counts(api: dict) -> tuple[int, int, int]:
    resources = api.get("resources", {})
    methods = api.get("methods", {})
    stages = api.get("stages", {})
    return max(len(resources) - 1, 0), len(methods), len(stages)


def _apigw_invoke_url(api_id: str, stage_name: str = "") -> str:
    base = f"/api/apigateway/invoke/{api_id}"
    return f"{base}/{stage_name}" if stage_name else base


def _apigw_api_view(api: dict) -> dict:
    resource_count, method_count, stage_count = _apigw_resource_counts(api)
    latest_stage = ""
    latest_stage_obj = None
    for stage in api.get("stages", {}).values():
        if latest_stage_obj is None or stage.get("created", "") > latest_stage_obj.get("created", ""):
            latest_stage_obj = stage
            latest_stage = stage.get("stage_name", "")
    invoke_url = _apigw_invoke_url(api["rest_api_id"], latest_stage or "")
    return {
        "rest_api_id": api["rest_api_id"],
        "name": api.get("name", ""),
        "description": api.get("description", ""),
        "endpoint_type": api.get("endpoint_type", "REGIONAL"),
        "created": api.get("created", ""),
        "tags": api.get("tags", []),
        "resource_count": resource_count,
        "method_count": method_count,
        "stage_count": stage_count,
        "deployment_count": len(api.get("deployments", {})),
        "latest_stage": latest_stage,
        "invoke_url": invoke_url,
        "status": "available",
    }


def _apigw_snapshot(api: dict) -> dict:
    return {
        "resources": copy.deepcopy(api.get("resources", {})),
        "methods": copy.deepcopy(api.get("methods", {})),
        "integrations": copy.deepcopy(api.get("integrations", {})),
        "created": _now(),
    }


def _apigw_find_resource(api_view: dict, path: str) -> dict | None:
    normalized = path if path.startswith("/") else f"/{path}"
    normalized = normalized or "/"
    resources = list(api_view.get("resources", {}).values())
    resources.sort(key=lambda item: len(item.get("path", "")), reverse=True)
    for resource in resources:
        pattern = _apigw_path_regex(resource.get("path", "/"))
        if re.fullmatch(pattern, normalized):
            return resource
    return None


def _apigw_method_view(api: dict, resource_id: str, method: str) -> dict | None:
    key = _apigw_route_key(resource_id, method)
    return api.get("methods", {}).get(key)


def _apigw_integration_view(api: dict, resource_id: str, method: str) -> dict | None:
    key = _apigw_route_key(resource_id, method)
    return api.get("integrations", {}).get(key)


def _apigw_route_views(api: dict) -> list[dict]:
    rows = []
    for resource_id, resource in api.get("resources", {}).items():
        if resource_id == api.get("root_resource_id"):
            continue
        for key, method in api.get("methods", {}).items():
            rid, http_method = key.split("::", 1)
            if rid != resource_id:
                continue
            integration = api.get("integrations", {}).get(key, {})
            rows.append({
                "resource_id": resource_id,
                "path": resource.get("path", "/"),
                "path_part": resource.get("path_part", ""),
                "parent_id": resource.get("parent_id", ""),
                "http_method": http_method,
                "authorization_type": method.get("authorization_type", "NONE"),
                "api_key_required": bool(method.get("api_key_required")),
                "integration_type": integration.get("type", "MOCK"),
                "integration_uri": integration.get("uri", ""),
                "integration_http_method": integration.get("integration_http_method", "POST"),
                "response_body": integration.get("response_body", ""),
                "status_code": integration.get("status_code", 200),
                "content_type": integration.get("content_type", "application/json"),
            })
    rows.sort(key=lambda item: (item["path"], item["http_method"]))
    return rows


def _apigw_create_api_record(req: APIGatewayRequest) -> dict:
    api_id = _id("api")
    root_resource_id = _id("res")
    api = {
        "rest_api_id": api_id,
        "name": req.name,
        "description": req.description,
        "endpoint_type": (req.endpoint_type or "REGIONAL").upper(),
        "created": _now(),
        "tags": req.tags or [],
        "root_resource_id": root_resource_id,
        "resources": {
            root_resource_id: {
                "resource_id": root_resource_id,
                "parent_id": "",
                "path_part": "",
                "path": "/",
                "created": _now(),
                "is_root": True,
            }
        },
        "methods": {},
        "integrations": {},
        "deployments": {},
        "stages": {},
        "logs": [],
        "settings": {"minimum_compression_size": None, "binary_media_types": []},
    }
    _apigw_state().setdefault("apis", {})[api_id] = api
    _record_usage("apigateway.create_api", {"rest_api_id": api_id, "name": req.name})
    return api


def _apigw_create_resource_record(api_id: str, req: APIGatewayResourceRequest) -> dict:
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    parent_id = req.parent_id.strip() or api["root_resource_id"]
    parent = api["resources"].get(parent_id)
    if not parent:
        raise HTTPException(404, detail="ParentResourceNotFound")
    path_part = req.path_part.strip().strip("/")
    if not path_part:
        raise HTTPException(400, detail="MissingParameter: path_part is required.")
    if "/" in path_part:
        raise HTTPException(400, detail="InvalidParameterValue: path_part cannot contain '/'.")
    path = _apigw_resource_path(parent.get("path", "/"), path_part)
    if any(resource.get("path") == path for resource in api["resources"].values()):
        raise HTTPException(409, detail="ResourceAlreadyExists")
    resource_id = _id("res")
    resource = {
        "resource_id": resource_id,
        "parent_id": parent_id,
        "path_part": path_part,
        "path": path,
        "created": _now(),
        "is_root": False,
    }
    api["resources"][resource_id] = resource
    _record_usage("apigateway.create_resource", {"rest_api_id": api_id, "resource_id": resource_id, "path": path})
    return resource


def _apigw_put_method_record(api_id: str, req: APIGatewayMethodRequest) -> dict:
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    resource = api["resources"].get(req.resource_id)
    if not resource:
        raise HTTPException(404, detail="ResourceNotFound")
    http_method = (req.http_method or "GET").upper()
    method = {
        "rest_api_id": api_id,
        "resource_id": req.resource_id,
        "http_method": http_method,
        "authorization_type": req.authorization_type or "NONE",
        "api_key_required": bool(req.api_key_required),
        "created": _now(),
    }
    api["methods"][_apigw_route_key(req.resource_id, http_method)] = method
    _record_usage("apigateway.put_method", {"rest_api_id": api_id, "resource_id": req.resource_id, "http_method": http_method})
    return method


def _apigw_put_integration_record(api_id: str, req: APIGatewayIntegrationRequest) -> dict:
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    if req.resource_id not in api["resources"]:
        raise HTTPException(404, detail="ResourceNotFound")
    http_method = (req.http_method or "GET").upper()
    key = _apigw_route_key(req.resource_id, http_method)
    if key not in api["methods"]:
        raise HTTPException(409, detail="MethodNotFound")
    integration = {
        "rest_api_id": api_id,
        "resource_id": req.resource_id,
        "http_method": http_method,
        "type": (req.type or "MOCK").upper(),
        "uri": req.uri,
        "integration_http_method": (req.integration_http_method or "POST").upper(),
        "response_body": req.response_body,
        "status_code": int(req.status_code or 200),
        "content_type": req.content_type or "application/json",
        "created": _now(),
    }
    api["integrations"][key] = integration
    _record_usage("apigateway.put_integration", {"rest_api_id": api_id, "resource_id": req.resource_id, "http_method": http_method, "type": integration["type"]})
    return integration


def _apigw_create_deployment_record(api_id: str, req: APIGatewayDeploymentRequest) -> dict:
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    deployment_id = _id("dep")
    snapshot = _apigw_snapshot(api)
    deployment = {
        "deployment_id": deployment_id,
        "rest_api_id": api_id,
        "description": req.description,
        "created": _now(),
        "snapshot": snapshot,
    }
    api["deployments"][deployment_id] = deployment
    api["latest_deployment_id"] = deployment_id
    if req.stage_name:
        _apigw_create_stage_record(api_id, APIGatewayStageRequest(rest_api_id=api_id, stage_name=req.stage_name, deployment_id=deployment_id, description=req.description, variables=[]), from_deployment=True)
    _record_usage("apigateway.create_deployment", {"rest_api_id": api_id, "deployment_id": deployment_id})
    return deployment


def _apigw_create_stage_record(api_id: str, req: APIGatewayStageRequest, from_deployment: bool = False) -> dict:
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    stage_name = req.stage_name.strip()
    if not _apigw_valid_stage_name(stage_name):
        raise HTTPException(400, detail="InvalidParameterValue: stage_name is invalid.")
    deployment_id = req.deployment_id.strip() or api.get("latest_deployment_id", "")
    if deployment_id and deployment_id not in api["deployments"]:
        raise HTTPException(404, detail="DeploymentNotFound")
    if not deployment_id:
        raise HTTPException(409, detail="DeploymentRequired")
    stage = {
        "rest_api_id": api_id,
        "stage_name": stage_name,
        "deployment_id": deployment_id,
        "description": req.description,
        "variables": req.variables or [],
        "created": _now(),
        "invoke_url": _apigw_invoke_url(api_id, stage_name),
    }
    api["stages"][stage_name] = stage
    if not from_deployment:
        api["latest_deployment_id"] = deployment_id
    _record_usage("apigateway.create_stage", {"rest_api_id": api_id, "stage_name": stage_name, "deployment_id": deployment_id})
    return stage


def _apigw_delete_api_record(api_id: str) -> None:
    apis = _apigw_state().setdefault("apis", {})
    if api_id not in apis:
        raise HTTPException(404, detail="RestApiNotFound")
    del apis[api_id]
    _record_usage("apigateway.delete_api", {"rest_api_id": api_id})


async def _apigw_invoke(api_id: str, stage_name: str, proxy_path: str, request: Request) -> Response:
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    stage = api.get("stages", {}).get(stage_name)
    if not stage:
        raise HTTPException(404, detail="StageNotFound")
    deployment = api["deployments"].get(stage.get("deployment_id", ""))
    if not deployment:
        raise HTTPException(404, detail="DeploymentNotFound")
    snapshot = deployment.get("snapshot", {})
    path = "/" + proxy_path.lstrip("/") if proxy_path else "/"
    resolved_resource = _apigw_find_resource(snapshot, path)
    if not resolved_resource:
        raise HTTPException(404, detail="ResourceNotFound")
    method = request.method.upper()
    method_def = snapshot.get("methods", {}).get(_apigw_route_key(resolved_resource["resource_id"], method)) or snapshot.get("methods", {}).get(_apigw_route_key(resolved_resource["resource_id"], "ANY"))
    if not method_def:
        raise HTTPException(405, detail="MethodNotAllowed")
    integration = snapshot.get("integrations", {}).get(_apigw_route_key(resolved_resource["resource_id"], method)) or snapshot.get("integrations", {}).get(_apigw_route_key(resolved_resource["resource_id"], "ANY"))
    if not integration:
        raise HTTPException(409, detail="IntegrationMissing")

    status_code = int(integration.get("status_code", 200))
    content_type = integration.get("content_type", "application/json")
    headers = {"Content-Type": content_type}
    body_bytes = await request.body()
    result = {"api_id": api_id, "stage": stage_name, "path": path, "method": method, "resource_path": resolved_resource.get("path", path)}

    if integration.get("type", "MOCK").upper() == "MOCK":
        payload = integration.get("response_body") or json.dumps({"message": "Mock integration response", **result})
        api_log = {"at": _now(), "api_id": api_id, "stage": stage_name, "path": path, "method": method, "status": status_code, "integration_type": "MOCK"}
        api.setdefault("logs", []).append(api_log)
        _apigw_state().setdefault("logs", []).append(api_log)
        return Response(content=payload, status_code=status_code, media_type=content_type, headers=headers)

    if integration.get("uri"):
        req = URLRequest(integration["uri"], data=body_bytes or None, method=method)
        if body_bytes and "content-type" not in {k.lower() for k in req.headers}:
            req.add_header("Content-Type", request.headers.get("content-type", "application/json"))
        try:
            with urlopen(req, timeout=30) as resp:
                payload = resp.read()
                status_code = getattr(resp, "status", 200) or 200
                content_type = resp.headers.get("content-type", content_type)
        except HTTPError as exc:
            payload = exc.read()
            status_code = exc.code or 502
            content_type = exc.headers.get("content-type", content_type) if exc.headers else content_type
        except URLError as exc:
            raise HTTPException(502, detail=f"IntegrationError: {exc.reason}")
        api_log = {"at": _now(), "api_id": api_id, "stage": stage_name, "path": path, "method": method, "status": status_code, "integration_type": integration.get("type", "HTTP")}
        api.setdefault("logs", []).append(api_log)
        _apigw_state().setdefault("logs", []).append(api_log)
        return Response(content=payload, status_code=status_code, media_type=content_type, headers={"Content-Type": content_type})

    raise HTTPException(409, detail="IntegrationMissing")


def _apigw_invoke_root(api_id: str, stage_name: str, request: Request) -> Response:
    return _apigw_invoke(api_id, stage_name, "", request)


def _apigw_summary(api: dict) -> dict:
    view = _apigw_api_view(api)
    view["resource_map"] = list(api.get("resources", {}).values())
    view["routes"] = _apigw_route_views(api)
    view["methods"] = list(api.get("methods", {}).values())
    view["integrations"] = list(api.get("integrations", {}).values())
    view["stages"] = list(api.get("stages", {}).values())
    view["deployments"] = list(api.get("deployments", {}).values())
    view["settings"] = copy.deepcopy(api.get("settings", {}))
    view["root_resource_id"] = api.get("root_resource_id", "")
    return view


# ---------------------------------------------------------------------------
# Console REST API route handlers
# ---------------------------------------------------------------------------


def api_apigateway_list_apis():
    apis = [_apigw_api_view(api) for api in _apigw_state().setdefault("apis", {}).values()]
    apis.sort(key=lambda item: (item.get("created", ""), item.get("name", "")))
    return {"apis": apis, "count": len(apis)}


def api_apigateway_create_api(req: APIGatewayRequest):
    if not req.name.strip():
        raise HTTPException(400, detail="MissingParameter: name is required.")
    api = _apigw_create_api_record(req)
    _record_usage("apigateway.create_api", {"rest_api_id": api.get("id", ""), "name": api.get("name", "")})
    return _apigw_summary(api)


def api_apigateway_get_api(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    return _apigw_summary(api)


def api_apigateway_delete_api(api_id: str):
    _apigw_delete_api_record(api_id)
    _record_usage("apigateway.delete_api", {"rest_api_id": api_id})
    return {"message": "API Gateway API deleted", "rest_api_id": api_id}


def api_apigateway_list_resources(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    return {"resources": _apigw_route_views(api), "count": max(len(api.get("resources", {})) - 1, 0)}


def api_apigateway_create_resource(api_id: str, req: APIGatewayResourceRequest):
    resource = _apigw_create_resource_record(api_id, req)
    api = _apigw_api(api_id)
    _record_usage("apigateway.create_resource", {"rest_api_id": api_id, "resource_id": resource.get("id", "")})
    return {"resource": resource, "api": _apigw_api_view(api)}


def api_apigateway_put_method(api_id: str, req: APIGatewayMethodRequest):
    method = _apigw_put_method_record(api_id, req)
    return {"method": method}


def api_apigateway_put_method_rest(api_id: str, resource_id: str, http_method: str, req: APIGatewayMethodRequest):
    """REST-style alias for PUT /apis/{api_id}/resources/{rid}/methods/{verb}.

    The catalog publishes this REST-flat shape; the body carries auth
    settings only, with resource_id / http_method coming from the URL.
    """
    if not req.resource_id:
        req.resource_id = resource_id
    req.http_method = (http_method or req.http_method or "GET").upper()
    method = _apigw_put_method_record(api_id, req)
    return {"method": method}


def api_apigateway_put_integration(api_id: str, req: APIGatewayIntegrationRequest):
    integration = _apigw_put_integration_record(api_id, req)
    return {"integration": integration}


def api_apigateway_create_deployment(api_id: str, req: APIGatewayDeploymentRequest):
    deployment = _apigw_create_deployment_record(api_id, req)
    _record_usage("apigateway.create_deployment", {"rest_api_id": api_id, "deployment_id": deployment.get("id", "")})
    return {"deployment": deployment}


def api_apigateway_list_deployments(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    deployments = list(api.get("deployments", {}).values())
    deployments.sort(key=lambda item: (item.get("created", ""), item.get("deployment_id", "")))
    return {"deployments": deployments, "count": len(deployments)}


def api_apigateway_create_stage(api_id: str, req: APIGatewayStageRequest):
    stage = _apigw_create_stage_record(api_id, req)
    _record_usage("apigateway.create_stage", {"rest_api_id": api_id, "stage_name": stage.get("stage_name", "")})
    return {"stage": stage}


def api_apigateway_list_stages(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    stages = list(api.get("stages", {}).values())
    stages.sort(key=lambda item: (item.get("created", ""), item.get("stage_name", "")))
    return {"stages": stages, "count": len(stages)}


def api_apigateway_list_logs(api_id: str):
    api = _apigw_api(api_id)
    if not api:
        raise HTTPException(404, detail="RestApiNotFound")
    logs = list(api.get("logs", []))
    logs.sort(key=lambda item: item.get("at", ""), reverse=True)
    return {"logs": logs[:100], "count": len(logs)}


async def api_apigateway_invoke_path(api_id: str, stage_name: str, proxy_path: str, request: Request):
    return await _apigw_invoke(api_id, stage_name, proxy_path, request)


async def api_apigateway_invoke_root(api_id: str, stage_name: str, request: Request):
    return await _apigw_invoke(api_id, stage_name, "", request)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(app: FastAPI, **kwargs) -> None:
    """Register API Gateway routes on the FastAPI app.

    NOTE: API Gateway routes are currently registered via providers/aws_routes.py
    using the dynamic _proxy/_add_route mechanism.  This register() function
    is provided for future use when the migration is complete.
    """
    pass  # Routes registered via providers/aws_routes.py spec table
