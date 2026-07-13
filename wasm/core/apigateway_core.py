# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""API Gateway core — substrate-independent REST-API data plane (PARITY P4 #15).
The first real API-gateway data plane in the simulator: a deployed REST API actually
ROUTES an incoming HTTP request to a resource + method, executes that method's
INTEGRATION, and returns a response. The headline is the Lambda-proxy path — API
Gateway → `lambda_core` sandboxed invoke → HTTP response = a genuine serverless HTTP
API entirely in-core.

Speaks the native **API Gateway (v1 / REST) control-plane wire** (`/restapis/...`,
JSON) so an unmodified boto3 `apigateway` client manages APIs; the data-plane invoke
is exposed separately (the real invoke URL is host-based:
`{apiId}.execute-api.../{stage}/...`). NO fastapi / boto3 / socket imports → loads
under Pyodide.

Integration types (v1 slice): **MOCK** (returns the integration's configured
status/body) and **AWS_PROXY** (Lambda proxy — builds the API-GW proxy event, calls
`lambda_core`, maps the function's `{statusCode, headers, body}` back to HTTP).
HTTP/HTTP_PROXY (outbound) and authorizers slot in behind the same seam.

Scope (control): CreateRestApi (auto root `/` resource), GetRestApis, CreateResource,
GetResources, PutMethod, PutIntegration, CreateDeployment. Data: invoke(api, stage,
method, path, ...).
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

from core import lambda_core


@dataclass
class ApiGwResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


def _json(status: int, obj: dict) -> ApiGwResponse:
    return ApiGwResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, code: str, message: str) -> ApiGwResponse:
    return ApiGwResponse(status=status, body=json.dumps({"__type": code, "message": message}).encode())


def _apis(store) -> dict:
    m = getattr(store, "_apigateway_apis", None)
    if m is None:
        m = {}
        store._apigateway_apis = m
    return m


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


# ── control plane ───────────────────────────────────────────────────────────
def _create_rest_api(store, body):
    api_id = _new_id()
    root_id = _new_id()
    _apis(store)[api_id] = {
        "id": api_id, "name": str(body.get("name", "")),
        "resources": {root_id: {"id": root_id, "parentId": None, "pathPart": "",
                                "path": "/", "methods": {}}},
        "deployments": {}}
    return _json(201, {"id": api_id, "name": body.get("name", ""), "rootResourceId": root_id})


def _get_rest_apis(store):
    return _json(200, {"item": [{"id": a["id"], "name": a["name"]} for a in _apis(store).values()]})


def _require_api(store, api_id):
    api = _apis(store).get(api_id)
    if not api:
        raise _E("NotFoundException", f"Invalid API identifier specified: {api_id}")
    return api


def _create_resource(store, api_id, parent_id, body):
    api = _require_api(store, api_id)
    parent = api["resources"].get(parent_id)
    if not parent:
        raise _E("NotFoundException", f"Invalid resource identifier: {parent_id}")
    path_part = str(body.get("pathPart", ""))
    rid = _new_id()
    base = parent["path"].rstrip("/")
    api["resources"][rid] = {"id": rid, "parentId": parent_id, "pathPart": path_part,
                             "path": f"{base}/{path_part}", "methods": {}}
    return _json(201, {"id": rid, "parentId": parent_id, "pathPart": path_part,
                       "path": api["resources"][rid]["path"]})


def _get_resources(store, api_id):
    api = _require_api(store, api_id)
    return _json(200, {"item": [{"id": r["id"], "parentId": r["parentId"],
                                 "pathPart": r["pathPart"], "path": r["path"],
                                 "resourceMethods": {m: {} for m in r["methods"]}}
                                for r in api["resources"].values()]})


def _put_method(store, api_id, resource_id, http_method, body):
    api = _require_api(store, api_id)
    res = api["resources"].get(resource_id)
    if not res:
        raise _E("NotFoundException", f"Invalid resource identifier: {resource_id}")
    res["methods"][http_method.upper()] = {
        "httpMethod": http_method.upper(),
        "authorizationType": str(body.get("authorizationType", "NONE")),
        "integration": None}
    return _json(201, {"httpMethod": http_method.upper(),
                       "authorizationType": body.get("authorizationType", "NONE")})


def _put_integration(store, api_id, resource_id, http_method, body):
    api = _require_api(store, api_id)
    res = api["resources"].get(resource_id)
    if not res or http_method.upper() not in res["methods"]:
        raise _E("NotFoundException", "No method for this resource.")
    integ = {
        "type": str(body.get("type", "MOCK")).upper(),
        "uri": str(body.get("uri", "")),
        "httpMethod": str(body.get("integrationHttpMethod", "POST")),
        # MOCK convenience: the configured response the mock returns.
        "mockStatus": int(body.get("mockStatus", 200)),
        "mockBody": body.get("mockBody", ""),
    }
    res["methods"][http_method.upper()]["integration"] = integ
    return _json(201, {"type": integ["type"], "uri": integ["uri"]})


def _create_deployment(store, api_id, body):
    api = _require_api(store, api_id)
    stage = str(body.get("stageName", ""))
    dep_id = _new_id()
    if stage:
        api["deployments"][stage] = {"deploymentId": dep_id, "stageName": stage}
    return _json(201, {"id": dep_id, "stageName": stage})


# ── data plane: invoke a deployed API ──────────────────────────────────────
def _lambda_name_from_uri(uri: str) -> str:
    """Pull the function name out of a Lambda integration uri
    (arn:aws:apigateway:...:lambda:path/.../functions/{arn}/invocations or a plain name)."""
    m = re.search(r"function:([A-Za-z0-9_-]+)", uri)
    if m:
        return m.group(1)
    m = re.search(r"functions/([^/]+)/invocations", uri)
    if m:
        # last arn segment is the function name
        return m.group(1).split(":")[-1]
    return uri.rsplit("/", 1)[-1]


def _match_resource(api: dict, path: str):
    """Find the resource whose path template matches `path`, returning
    (resource, path_params) or (None, {})."""
    req = "/" + path.strip("/")
    for res in api["resources"].values():
        template = res["path"]
        regex = "^" + re.sub(r"\{[^/}]+\}", r"([^/]+)", template.rstrip("/")) + "/?$"
        m = re.match(regex, req)
        if not m:
            continue
        names = re.findall(r"\{([^/}]+)\}", template)
        params = {n.rstrip("+"): v for n, v in zip(names, m.groups())}
        return res, params
    return None, {}


def invoke(store, api_id, stage, method, path, headers=None, query=None,
           body=b"", lambda_store=None):
    """Route a request through a deployed API: match resource → method → integration
    → response. Returns an ApiGwResponse."""
    api = _apis(store).get(api_id)
    if not api:
        return _err(403, "ForbiddenException", "Missing Authentication Token")
    if stage not in api["deployments"]:
        return _err(403, "ForbiddenException", f"No deployment for stage {stage}")
    res, path_params = _match_resource(api, path)
    if not res:
        return _err(403, "MissingAuthenticationTokenException", "Missing Authentication Token")
    m = res["methods"].get((method or "GET").upper()) or res["methods"].get("ANY")
    if not m or not m.get("integration"):
        return _err(403, "MissingAuthenticationTokenException", "Missing Authentication Token")
    integ = m["integration"]

    if integ["type"] == "MOCK":
        mock_body = integ["mockBody"]
        payload = mock_body if isinstance(mock_body, (bytes, bytearray)) else str(mock_body).encode()
        return ApiGwResponse(status=integ["mockStatus"], body=payload)

    if integ["type"] in ("AWS_PROXY", "AWS"):
        fn = _lambda_name_from_uri(integ["uri"])
        try:
            req_body = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body or "")
        except Exception:
            req_body = ""
        event = {
            "resource": res["path"], "path": "/" + path.strip("/"),
            "httpMethod": (method or "GET").upper(),
            "headers": dict(headers or {}), "queryStringParameters": dict(query or {}) or None,
            "pathParameters": path_params or None, "body": req_body, "isBase64Encoded": False,
        }
        lam_out = lambda_core.dispatch(
            lambda_store if lambda_store is not None else store, "POST",
            f"/2015-03-31/functions/{fn}/invocations", {}, {}, json.dumps(event).encode())
        if lam_out.headers.get("X-Amz-Function-Error"):
            return _err(502, "BadGateway", "Internal server error")
        try:
            result = json.loads(lam_out.body.decode("utf-8"))
        except Exception:
            result = {}
        # Proxy contract: the function returns {statusCode, headers, body}.
        status = int(result.get("statusCode", 200))
        out_headers = {str(k): str(v) for k, v in (result.get("headers") or {}).items()}
        out_body = result.get("body", "")
        out_body = out_body.encode() if isinstance(out_body, str) else (out_body or b"")
        return ApiGwResponse(status=status, body=out_body, headers=out_headers)

    return _err(500, "InternalServerError", f"Unsupported integration type {integ['type']}")


# ── dispatch (control plane) ────────────────────────────────────────────────
class _E(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _parse(body):
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return {}


def dispatch(store, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> ApiGwResponse:
    """Native API Gateway v1 control-plane router (`/restapis/...`)."""
    method = (method or "GET").upper()
    p = path.split("?", 1)[0]
    segs = [s for s in p.split("/") if s != ""]
    payload = _parse(body)

    if not segs or segs[0] != "restapis":
        return _err(404, "NotFoundException", f"Unknown path: {path}")
    try:
        # /restapis
        if len(segs) == 1:
            if method == "POST":
                return _create_rest_api(store, payload)
            if method == "GET":
                return _get_rest_apis(store)
        api_id = segs[1] if len(segs) > 1 else ""
        # /restapis/{id}/resources ...
        if len(segs) >= 3 and segs[2] == "resources":
            if len(segs) == 3:
                if method == "GET":
                    return _get_resources(store, api_id)
            # /restapis/{id}/resources/{parentId}  (POST create child)
            if len(segs) == 4 and method == "POST":
                return _create_resource(store, api_id, segs[3], payload)
            # /restapis/{id}/resources/{resId}/methods/{httpMethod}[/integration]
            if len(segs) >= 6 and segs[4] == "methods":
                res_id, http_method = segs[3], segs[5]
                if len(segs) == 6 and method == "PUT":
                    return _put_method(store, api_id, res_id, http_method, payload)
                if len(segs) == 7 and segs[6] == "integration" and method == "PUT":
                    return _put_integration(store, api_id, res_id, http_method, payload)
        # /restapis/{id}/deployments
        if len(segs) == 3 and segs[2] == "deployments" and method == "POST":
            return _create_deployment(store, api_id, payload)
        return _err(404, "NotFoundException", f"Unsupported {method} {path}")
    except _E as e:
        return _err(404, e.code, e.message)
