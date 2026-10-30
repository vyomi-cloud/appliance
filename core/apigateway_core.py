"""API Gateway core — substrate-independent REST-API control + data plane (PARITY P4 #15,
v4 console wave). A deployed REST API actually ROUTES an incoming HTTP request to a
resource + method, executes that method's INTEGRATION, and returns a response. The
headline is the Lambda-proxy path — API Gateway → `lambda_core` sandboxed invoke → HTTP
response = a genuine serverless HTTP API entirely in-core.

Speaks the native **API Gateway (v1 / REST) control-plane wire** (`/restapis/...`,
`/apikeys`, `/usageplans`, `/clientcertificates`, `/account`; JSON) so an unmodified
boto3 `apigateway` client manages APIs; the data-plane invoke is exposed separately (the
real invoke URL is host-based: `{apiId}.execute-api.../{stage}/...`) — `TestInvokeMethod`
below gives the console a real, deployment-independent way to execute a method's
integration chain, exactly like the "Test" feature in the real console's method editor.
NO fastapi / boto3 / socket imports → loads under Pyodide.

Integration types (v1 slice): **MOCK** (returns the integration's configured
status/body) and **AWS_PROXY** (Lambda proxy — builds the API-GW proxy event, calls
`lambda_core`, maps the function's `{statusCode, headers, body}` back to HTTP), and
**HTTP/HTTP_PROXY** (outbound, via urllib — same seam as GCP Cloud Run core's outbound
calls; falls back to a clear error if the target host does not resolve from this
sandbox). Authorizers slot in behind the same seam.

Scope (control): RestApi CRUD, Resource CRUD, Method/Integration CRUD, TestInvokeMethod,
Deployment + Stage CRUD, Account settings, ApiKey CRUD, UsagePlan (+ UsagePlanKey) CRUD,
ClientCertificate CRUD. Data: invoke(api, stage, method, path, ...).
"""
from __future__ import annotations

import datetime
import json
import re
import uuid
from dataclasses import dataclass, field

from core import lambda_core

REGION = "us-east-1"
ACCOUNT = "000000000000"


@dataclass
class ApiGwResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


def _json(status: int, obj) -> ApiGwResponse:
    if obj is None:
        return ApiGwResponse(status=status, body=b"")
    return ApiGwResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, code: str, message: str) -> ApiGwResponse:
    return ApiGwResponse(status=status, body=json.dumps({"__type": code, "message": message}).encode())


class _E(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def NotFound(msg):
    return _E("NotFoundException", msg, 404)


def BadRequest(msg):
    return _E("BadRequestException", msg, 400)


def Conflict(msg):
    return _E("ConflictException", msg, 409)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _store(obj, attr):
    m = getattr(obj, attr, None)
    if m is None:
        m = {}
        setattr(obj, attr, m)
    return m


def _apis(store) -> dict:
    return _store(store, "_apigateway_apis")


def _api_keys(store) -> dict:
    return _store(store, "_apigateway_api_keys")


def _usage_plans(store) -> dict:
    return _store(store, "_apigateway_usage_plans")


def _client_certs(store) -> dict:
    return _store(store, "_apigateway_client_certs")


def _account(store) -> dict:
    a = getattr(store, "_apigateway_account", None)
    if a is None:
        a = {"cloudwatchRoleArn": None, "throttleSettings": {"rateLimit": 10000.0, "burstLimit": 5000},
             "features": ["UsagePlans"], "apiKeyVersion": "1"}
        store._apigateway_account = a
    return a


# ── RestApi ──────────────────────────────────────────────────────────────────
def _create_rest_api(store, body):
    api_id = _new_id()
    root_id = _new_id()
    types = (body.get("endpointConfiguration") or {}).get("types") or ["EDGE"]
    api = {
        "id": api_id, "name": str(body.get("name", "")),
        "description": str(body.get("description", "") or ""),
        "createdDate": _now(), "version": body.get("version"),
        "apiKeySource": body.get("apiKeySource", "HEADER"),
        "endpointConfiguration": {"types": types},
        "ipAddressType": body.get("ipAddressType", "ipv4"),
        "disableExecuteApiEndpoint": bool(body.get("disableExecuteApiEndpoint", False)),
        "policy": body.get("policy"),
        "tags": dict(body.get("tags") or {}),
        "resources": {root_id: {"id": root_id, "parentId": None, "pathPart": "",
                                 "path": "/", "methods": {}}},
        "deployments": {}, "stages": {},
    }
    _apis(store)[api_id] = api
    return _json(201, {**_api_view(api), "rootResourceId": root_id})


SECURITY_POLICY = "TLS_1_2"


def _api_view(api):
    return {"id": api["id"], "name": api["name"], "description": api["description"],
            "createdDate": api["createdDate"], "version": api.get("version"),
            "apiKeySource": api["apiKeySource"], "endpointConfiguration": api["endpointConfiguration"],
            "ipAddressType": api.get("ipAddressType", "ipv4"), "policy": api.get("policy"),
            "tags": dict(api.get("tags") or {}),
            "disableExecuteApiEndpoint": api.get("disableExecuteApiEndpoint", False)}


def _require_api(store, api_id):
    api = _apis(store).get(api_id)
    if not api:
        raise NotFound(f"Invalid API identifier specified: {api_id}")
    return api


def _get_rest_apis(store):
    return _json(200, {"item": [_api_view(a) for a in _apis(store).values()]})


_PATCHABLE_API = {"name", "description", "policy"}


def _apply_patch(obj, ops, allowed):
    for op in ops or []:
        path = str(op.get("path", "")).lstrip("/")
        if not path:
            continue
        parts = path.split("/")
        if parts[0] not in allowed:
            continue
        verb = op.get("op", "replace")
        if verb == "remove":
            if len(parts) == 1:
                obj.pop(parts[0], None)
            else:
                obj.get(parts[0], {}).pop(parts[1], None)
            continue
        value = op.get("value")
        if len(parts) == 1:
            if parts[0] == "endpointConfiguration.types" or parts[0].startswith("endpointConfiguration"):
                obj.setdefault("endpointConfiguration", {})["types"] = [value]
            else:
                obj[parts[0]] = value
        else:
            obj.setdefault(parts[0], {})[parts[1]] = value


def _update_rest_api(store, api_id, body):
    api = _require_api(store, api_id)
    _apply_patch(api, body.get("patchOperations"), _PATCHABLE_API | {"endpointConfiguration"})
    return _json(200, _api_view(api))


def _delete_rest_api(store, api_id):
    _require_api(store, api_id)
    del _apis(store)[api_id]
    return ApiGwResponse(status=202)


# ── Resource ─────────────────────────────────────────────────────────────────
def _create_resource(store, api_id, parent_id, body):
    api = _require_api(store, api_id)
    parent = api["resources"].get(parent_id)
    if not parent:
        raise NotFound(f"Invalid resource identifier: {parent_id}")
    path_part = str(body.get("pathPart", ""))
    rid = _new_id()
    base = parent["path"].rstrip("/")
    api["resources"][rid] = {"id": rid, "parentId": parent_id, "pathPart": path_part,
                              "path": f"{base}/{path_part}", "methods": {}}
    return _json(201, _resource_view(api["resources"][rid]))


def _resource_view(res):
    return {"id": res["id"], "parentId": res["parentId"], "pathPart": res["pathPart"],
            "path": res["path"],
            "resourceMethods": {m: {"httpMethod": mm["httpMethod"], "authorizationType": mm["authorizationType"],
                                     "apiKeyRequired": mm.get("apiKeyRequired", False)}
                                 for m, mm in res["methods"].items()}}


def _get_resources(store, api_id):
    api = _require_api(store, api_id)
    return _json(200, {"item": [_resource_view(r) for r in api["resources"].values()]})


def _get_resource(store, api_id, res_id):
    api = _require_api(store, api_id)
    res = api["resources"].get(res_id)
    if not res:
        raise NotFound(f"Invalid resource identifier specified: {res_id}")
    return _json(200, _resource_view(res))


def _require_resource(api, res_id):
    res = api["resources"].get(res_id)
    if not res:
        raise NotFound(f"Invalid resource identifier specified: {res_id}")
    return res


def _delete_resource(store, api_id, res_id):
    api = _require_api(store, api_id)
    _require_resource(api, res_id)
    if any(r["parentId"] == res_id for r in api["resources"].values()):
        raise BadRequest("Cannot delete a resource that has child resources")
    del api["resources"][res_id]
    return ApiGwResponse(status=202)


# ── Method / Integration ──────────────────────────────────────────────────────
def _put_method(store, api_id, resource_id, http_method, body):
    api = _require_api(store, api_id)
    res = _require_resource(api, resource_id)
    res["methods"][http_method.upper()] = {
        "httpMethod": http_method.upper(),
        "authorizationType": str(body.get("authorizationType", "NONE")),
        "apiKeyRequired": bool(body.get("apiKeyRequired", False)),
        "requestParameters": dict(body.get("requestParameters") or {}),
        "integration": None}
    return _json(201, _method_view(res["methods"][http_method.upper()]))


def _method_view(m):
    return {"httpMethod": m["httpMethod"], "authorizationType": m["authorizationType"],
            "apiKeyRequired": m.get("apiKeyRequired", False),
            "requestParameters": dict(m.get("requestParameters") or {}),
            "methodIntegration": _integration_view(m["integration"]) if m.get("integration") else None}


def _require_method(api, resource_id, http_method):
    res = _require_resource(api, resource_id)
    m = res["methods"].get(http_method.upper())
    if not m:
        raise NotFound(f"Invalid Method identifier specified: {http_method}")
    return res, m


def _get_method(store, api_id, resource_id, http_method):
    api = _require_api(store, api_id)
    _, m = _require_method(api, resource_id, http_method)
    return _json(200, _method_view(m))


def _delete_method(store, api_id, resource_id, http_method):
    api = _require_api(store, api_id)
    res, _m = _require_method(api, resource_id, http_method)
    del res["methods"][http_method.upper()]
    return ApiGwResponse(status=202)


def _integration_view(integ):
    return {"type": integ["type"], "uri": integ.get("uri", ""),
            "httpMethod": integ.get("httpMethod"), "timeoutInMillis": integ.get("timeoutInMillis", 29000),
            "requestTemplates": dict(integ.get("requestTemplates") or {}),
            "passthroughBehavior": integ.get("passthroughBehavior", "WHEN_NO_MATCH")}


def _put_integration(store, api_id, resource_id, http_method, body):
    api = _require_api(store, api_id)
    res, m = _require_method(api, resource_id, http_method)
    itype = str(body.get("type", "MOCK")).upper()
    if itype not in ("MOCK", "AWS_PROXY", "AWS", "HTTP", "HTTP_PROXY"):
        raise BadRequest(f"Invalid integration type: {itype}")
    integ = {
        "type": itype,
        "uri": str(body.get("uri", "")),
        "httpMethod": str(body.get("integrationHttpMethod", "POST")),
        "timeoutInMillis": int(body.get("timeoutInMillis", 29000)),
        "passthroughBehavior": body.get("passthroughBehavior", "WHEN_NO_MATCH"),
        "requestTemplates": dict(body.get("requestTemplates") or {}),
        # MOCK convenience: the configured response the mock returns.
        "mockStatus": int(body.get("mockStatus", 200)),
        "mockBody": body.get("mockBody", ""),
    }
    m["integration"] = integ
    return _json(201, _integration_view(integ))


def _get_integration(store, api_id, resource_id, http_method):
    api = _require_api(store, api_id)
    _, m = _require_method(api, resource_id, http_method)
    if not m.get("integration"):
        raise NotFound("No integration defined for method")
    return _json(200, _integration_view(m["integration"]))


def _delete_integration(store, api_id, resource_id, http_method):
    api = _require_api(store, api_id)
    _, m = _require_method(api, resource_id, http_method)
    m["integration"] = None
    return ApiGwResponse(status=202)


# ── integration execution (shared by invoke() and TestInvokeMethod) ──────────
def _lambda_name_from_uri(uri: str) -> str:
    """Pull the function name out of a Lambda integration uri
    (arn:aws:apigateway:...:lambda:path/.../functions/{arn}/invocations or a plain name)."""
    m = re.search(r"function:([A-Za-z0-9_-]+)", uri)
    if m:
        return m.group(1)
    m = re.search(r"functions/([^/]+)/invocations", uri)
    if m:
        return m.group(1).split(":")[-1]
    return uri.rsplit("/", 1)[-1]


def _run_integration(integ, method, path, headers, query, path_params, body, lambda_store):
    """Execute one method's integration. Returns (status, headers, body_bytes, log_lines)."""
    log = [f"Starting execution for request", f"HTTP Method: {method}, Resource Path: {path}"]
    if integ["type"] == "MOCK":
        mock_body = integ["mockBody"]
        payload = mock_body if isinstance(mock_body, (bytes, bytearray)) else str(mock_body).encode()
        log.append(f"Mock integration — returning configured status {integ['mockStatus']}")
        return integ["mockStatus"], {}, payload, log

    if integ["type"] in ("AWS_PROXY", "AWS"):
        fn = _lambda_name_from_uri(integ["uri"])
        log.append(f"Invoking Lambda function {fn}")
        try:
            req_body = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body or "")
        except Exception:
            req_body = ""
        event = {
            "resource": path, "path": "/" + path.strip("/"), "httpMethod": (method or "GET").upper(),
            "headers": dict(headers or {}), "queryStringParameters": dict(query or {}) or None,
            "pathParameters": path_params or None, "body": req_body, "isBase64Encoded": False,
        }
        lam_out = lambda_core.dispatch(
            lambda_store, "POST", f"/2015-03-31/functions/{fn}/invocations", {}, {}, json.dumps(event).encode())
        if lam_out.headers.get("X-Amz-Function-Error"):
            log.append("Lambda invocation returned a function error")
            return 502, {}, json.dumps({"message": "Internal server error"}).encode(), log
        try:
            result = json.loads(lam_out.body.decode("utf-8"))
        except Exception:
            result = {}
        status = int(result.get("statusCode", 200))
        out_headers = {str(k): str(v) for k, v in (result.get("headers") or {}).items()}
        out_body = result.get("body", "")
        out_body = out_body.encode() if isinstance(out_body, str) else (out_body or b"")
        log.append(f"Lambda returned statusCode {status}")
        return status, out_headers, out_body, log

    if integ["type"] in ("HTTP", "HTTP_PROXY"):
        log.append(f"Endpoint request URI: {integ['uri']}")
        try:
            import urllib.request
            req = urllib.request.Request(integ["uri"], method=integ.get("httpMethod", "POST"),
                                          data=body if isinstance(body, (bytes, bytearray)) else (body or b"").encode())
            with urllib.request.urlopen(req, timeout=5) as r:
                out_body = r.read()
                log.append(f"Endpoint responded with status {r.status}")
                return r.status, dict(r.headers.items()), out_body, log
        except Exception as e:
            log.append(f"Endpoint request failed: {e}")
            return 502, {}, json.dumps({"message": "Internal server error"}).encode(), log

    log.append(f"Unsupported integration type {integ['type']}")
    return 500, {}, json.dumps({"message": "Internal server error"}).encode(), log


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
    """Route a request through a DEPLOYED API: match resource → method → integration
    → response. Returns an ApiGwResponse."""
    api = _apis(store).get(api_id)
    if not api:
        return _err(403, "ForbiddenException", "Missing Authentication Token")
    if stage not in api["stages"]:
        return _err(403, "ForbiddenException", f"No deployment for stage {stage}")
    res, path_params = _match_resource(api, path)
    if not res:
        return _err(403, "MissingAuthenticationTokenException", "Missing Authentication Token")
    m = res["methods"].get((method or "GET").upper()) or res["methods"].get("ANY")
    if not m or not m.get("integration"):
        return _err(403, "MissingAuthenticationTokenException", "Missing Authentication Token")
    status, out_headers, out_body, _log = _run_integration(
        m["integration"], method, path, headers, query, path_params, body, lambda_store or store)
    return ApiGwResponse(status=status, body=out_body, headers=out_headers)


def _test_invoke_method(store, api_id, resource_id, http_method, body, lambda_store=None):
    """TestInvokeMethod — exercises a method's integration right now, with no
    deployment required (exactly like the real console's "Test" tab)."""
    import time
    api = _require_api(store, api_id)
    res, m = _require_method(api, resource_id, http_method)
    if not m.get("integration"):
        raise BadRequest("No integration defined for method")
    req_body = body.get("body", "") or ""
    headers = dict(body.get("headers") or {})
    path_with_qs = str(body.get("pathWithQueryString") or res["path"])
    path, _, qs = path_with_qs.partition("?")
    from urllib.parse import parse_qsl
    query = dict(parse_qsl(qs))
    template = res["path"]
    regex = "^" + re.sub(r"\{[^/}]+\}", r"([^/]+)", template.rstrip("/")) + "/?$"
    mt = re.match(regex, "/" + path.strip("/"))
    names = re.findall(r"\{([^/}]+)\}", template)
    path_params = {n.rstrip("+"): v for n, v in zip(names, mt.groups())} if mt else {}
    t0 = time.time()
    status, _out_headers, out_body, log = _run_integration(
        m["integration"], http_method, path, headers, query, path_params,
        req_body.encode() if isinstance(req_body, str) else req_body,
        lambda_store or store)
    latency = max(1, int((time.time() - t0) * 1000))
    try:
        out_text = out_body.decode("utf-8") if isinstance(out_body, (bytes, bytearray)) else str(out_body)
    except Exception:
        out_text = ""
    return _json(200, {"status": status, "body": out_text, "log": "\n".join(log), "latency": latency,
                        "headers": {}})


# ── Deployment / Stage ─────────────────────────────────────────────────────────
def _create_deployment(store, api_id, body):
    api = _require_api(store, api_id)
    dep_id = _new_id()
    dep = {"id": dep_id, "description": body.get("description") or "", "createdDate": _now()}
    api["deployments"][dep_id] = dep
    stage_name = body.get("stageName")
    if stage_name:
        _put_stage(api, stage_name, dep_id, body)
    return _json(201, {"id": dep_id, "description": dep["description"], "createdDate": dep["createdDate"]})


def _get_deployments(store, api_id):
    api = _require_api(store, api_id)
    return _json(200, {"item": [{"id": d["id"], "description": d["description"], "createdDate": d["createdDate"]}
                                 for d in api["deployments"].values()]})


def _get_deployment(store, api_id, dep_id):
    api = _require_api(store, api_id)
    d = api["deployments"].get(dep_id)
    if not d:
        raise NotFound(f"Invalid Deployment identifier specified: {dep_id}")
    return _json(200, dict(d))


def _put_stage(api, name, deployment_id, body):
    """Shared by CreateDeployment(stageName=...) and CreateStage — create or move a
    stage to a new deployment, exactly like the real service does."""
    existing = api["stages"].get(name)
    st = existing or {
        "stageName": name, "createdDate": _now(), "variables": {}, "tags": {},
        "throttle": {"rateLimit": 10000.0, "burstLimit": 5000},
        "cacheClusterEnabled": False, "tracingEnabled": False,
        "accessLogSettings": None, "canarySettings": None,
    }
    st["deploymentId"] = deployment_id
    st["lastUpdatedDate"] = _now()
    st["description"] = body.get("description", st.get("description", ""))
    if body.get("variables"):
        st["variables"].update(body["variables"])
    api["stages"][name] = st
    return st


def _stage_view(api, st):
    return {
        "stageName": st["stageName"], "apiId": api["id"], "deploymentId": st.get("deploymentId"),
        "createdDate": st["createdDate"], "lastUpdatedDate": st.get("lastUpdatedDate", st["createdDate"]),
        "description": st.get("description", ""), "variables": dict(st.get("variables") or {}),
        "tags": dict(st.get("tags") or {}),
        "throttleSettings": dict(st.get("throttle") or {"rateLimit": 10000.0, "burstLimit": 5000}),
        "cacheClusterEnabled": st.get("cacheClusterEnabled", False),
        "cacheClusterSize": st.get("cacheClusterSize"),
        "tracingEnabled": st.get("tracingEnabled", False),
        "accessLogSettings": st.get("accessLogSettings"),
        "canarySettings": st.get("canarySettings"),
        "invokeUrl": f"https://{api['id']}.execute-api.{REGION}.amazonaws.com/{st['stageName']}",
    }


def _create_stage(store, api_id, body):
    api = _require_api(store, api_id)
    name = str(body.get("stageName", ""))
    if not name:
        raise BadRequest("stageName is required")
    if name in api["stages"]:
        raise Conflict(f"Stage already exists: {name}")
    dep_id = body.get("deploymentId")
    if not dep_id or dep_id not in api["deployments"]:
        raise NotFound(f"Invalid Deployment identifier specified: {dep_id}")
    st = _put_stage(api, name, dep_id, body)
    if body.get("variables"):
        st["variables"] = dict(body["variables"])
    return _json(201, _stage_view(api, st))


def _get_stages(store, api_id):
    api = _require_api(store, api_id)
    return _json(200, {"item": [_stage_view(api, s) for s in api["stages"].values()]})


def _require_stage(api, name):
    st = api["stages"].get(name)
    if not st:
        raise NotFound(f"Invalid Stage identifier specified: {name}")
    return st


def _get_stage(store, api_id, name):
    api = _require_api(store, api_id)
    st = _require_stage(api, name)
    return _json(200, _stage_view(api, st))


_PATCHABLE_STAGE = {"description", "deploymentId", "cacheClusterEnabled", "cacheClusterSize",
                    "tracingEnabled", "variables", "throttle", "accessLogSettings"}


def _update_stage(store, api_id, name, body):
    api = _require_api(store, api_id)
    st = _require_stage(api, name)
    for op in body.get("patchOperations") or []:
        path = str(op.get("path", "")).lstrip("/")
        parts = path.split("/")
        verb = op.get("op", "replace")
        value = op.get("value")
        if parts[0] == "variables" and len(parts) == 2:
            if verb == "remove":
                st["variables"].pop(parts[1], None)
            else:
                st["variables"][parts[1]] = value
        elif parts[0] in ("throttle/rateLimit", "throttle/burstLimit"):
            pass
        elif parts[0] == "throttle" and len(parts) == 2:
            st.setdefault("throttle", {})[parts[1]] = float(value) if value is not None else value
        elif parts[0] in _PATCHABLE_STAGE:
            if parts[0] in ("cacheClusterEnabled", "tracingEnabled"):
                value = str(value).lower() == "true" if isinstance(value, str) else bool(value)
            st[parts[0]] = value
    st["lastUpdatedDate"] = _now()
    return _json(200, _stage_view(api, st))


def _delete_stage(store, api_id, name):
    api = _require_api(store, api_id)
    _require_stage(api, name)
    del api["stages"][name]
    return ApiGwResponse(status=202)


# ── Account ────────────────────────────────────────────────────────────────
def _get_account(store):
    return _json(200, dict(_account(store)))


def _update_account(store, body):
    acc = _account(store)
    for op in body.get("patchOperations") or []:
        path = str(op.get("path", "")).lstrip("/")
        if path == "cloudwatchRoleArn":
            acc["cloudwatchRoleArn"] = op.get("value") or None
        elif path.startswith("features"):
            if op.get("op") == "add":
                acc.setdefault("features", []).append(op.get("value"))
    return _json(200, dict(acc))


# ── ApiKey ──────────────────────────────────────────────────────────────────
def _gen_key_value() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex[:8]


def _create_api_key(store, body):
    kid = _new_id()
    name = str(body.get("name", ""))
    value = body.get("value") or _gen_key_value()
    if len(value) < 20:
        raise BadRequest("API Key value should be at least 20 characters")
    k = {"id": kid, "name": name, "description": body.get("description", "") or "",
         "enabled": bool(body.get("enabled", True)), "value": value,
         "createdDate": _now(), "lastUpdatedDate": _now(),
         "stageKeys": list(body.get("stageKeys") or []), "tags": dict(body.get("tags") or {}),
         "customerId": body.get("customerId")}
    _api_keys(store)[kid] = k
    return _json(201, _key_view(k, include_value=True))


def _key_view(k, include_value=False):
    v = {"id": k["id"], "name": k["name"], "description": k["description"], "enabled": k["enabled"],
         "createdDate": k["createdDate"], "lastUpdatedDate": k["lastUpdatedDate"],
         "stageKeys": list(k.get("stageKeys") or []), "tags": dict(k.get("tags") or {}),
         "customerId": k.get("customerId")}
    if include_value:
        v["value"] = k["value"]
    return v


def _get_api_keys(store, query):
    include_values = str((query or {}).get("includeValues", "")).lower() == "true"
    return _json(200, {"item": [_key_view(k, include_values) for k in _api_keys(store).values()]})


def _require_key(store, kid):
    k = _api_keys(store).get(kid)
    if not k:
        raise NotFound(f"Invalid API Key identifier specified: {kid}")
    return k


def _get_api_key(store, kid, query):
    k = _require_key(store, kid)
    include_value = str((query or {}).get("includeValue", "")).lower() == "true"
    return _json(200, _key_view(k, include_value))


def _update_api_key(store, kid, body):
    k = _require_key(store, kid)
    for op in body.get("patchOperations") or []:
        path = str(op.get("path", "")).lstrip("/")
        verb, value = op.get("op", "replace"), op.get("value")
        if path == "enabled":
            k["enabled"] = str(value).lower() == "true" if isinstance(value, str) else bool(value)
        elif path in ("name", "description", "customerId"):
            k[path] = value
    k["lastUpdatedDate"] = _now()
    return _json(200, _key_view(k, True))


def _delete_api_key(store, kid):
    _require_key(store, kid)
    del _api_keys(store)[kid]
    for p in _usage_plans(store).values():
        p.get("_keys", {}).pop(kid, None)
    return ApiGwResponse(status=202)


# ── UsagePlan / UsagePlanKey ──────────────────────────────────────────────────
def _create_usage_plan(store, body):
    pid = _new_id()
    p = {"id": pid, "name": str(body.get("name", "")), "description": body.get("description", "") or "",
         "apiStages": list(body.get("apiStages") or []), "throttle": dict(body.get("throttle") or {}),
         "quota": dict(body.get("quota") or {}), "tags": dict(body.get("tags") or {}), "_keys": {}}
    _usage_plans(store)[pid] = p
    return _json(201, _plan_view(p))


def _plan_view(p):
    return {"id": p["id"], "name": p["name"], "description": p["description"],
            "apiStages": list(p.get("apiStages") or []), "throttle": dict(p.get("throttle") or {}),
            "quota": dict(p.get("quota") or {}), "tags": dict(p.get("tags") or {})}


def _get_usage_plans(store):
    return _json(200, {"item": [_plan_view(p) for p in _usage_plans(store).values()]})


def _require_plan(store, pid):
    p = _usage_plans(store).get(pid)
    if not p:
        raise NotFound(f"Invalid Usage Plan ID specified: {pid}")
    return p


def _get_usage_plan(store, pid):
    return _json(200, _plan_view(_require_plan(store, pid)))


def _update_usage_plan(store, pid, body):
    p = _require_plan(store, pid)
    for op in body.get("patchOperations") or []:
        path = str(op.get("path", "")).lstrip("/")
        parts, verb, value = path.split("/"), op.get("op", "replace"), op.get("value")
        if parts[0] == "apiStages":
            ref = value or ""
            if verb == "add":
                api_id, _, stage = ref.partition(":")
                p["apiStages"].append({"apiId": api_id, "stage": stage})
            elif verb == "remove":
                api_id, _, stage = ref.partition(":")
                p["apiStages"] = [s for s in p["apiStages"] if not (s["apiId"] == api_id and s["stage"] == stage)]
        elif parts[0] in ("throttle", "quota") and len(parts) == 2:
            dest = p.setdefault(parts[0], {})
            dest[parts[1]] = float(value) if parts[1] != "period" and value is not None else value
        elif parts[0] in ("name", "description"):
            p[parts[0]] = value
    return _json(200, _plan_view(p))


def _delete_usage_plan(store, pid):
    _require_plan(store, pid)
    del _usage_plans(store)[pid]
    return ApiGwResponse(status=202)


def _create_usage_plan_key(store, pid, body):
    p = _require_plan(store, pid)
    kid = body.get("keyId")
    k = _require_key(store, kid)
    p["_keys"][kid] = True
    return _json(201, {"id": k["id"], "name": k["name"], "type": body.get("keyType", "API_KEY"), "value": k["value"]})


def _get_usage_plan_keys(store, pid):
    p = _require_plan(store, pid)
    out = []
    for kid in p["_keys"]:
        k = _api_keys(store).get(kid)
        if k:
            out.append({"id": k["id"], "name": k["name"], "type": "API_KEY", "value": k["value"]})
    return _json(200, {"item": out})


def _delete_usage_plan_key(store, pid, kid):
    p = _require_plan(store, pid)
    if kid not in p["_keys"]:
        raise NotFound(f"Invalid Usage Plan Key identifier specified: {kid}")
    del p["_keys"][kid]
    return ApiGwResponse(status=202)


# ── ClientCertificate ──────────────────────────────────────────────────────
def _fake_pem(cert_id: str) -> str:
    body = uuid.uuid5(uuid.NAMESPACE_DNS, cert_id).hex.upper()
    return f"-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----"


def _create_client_certificate(store, body):
    cid = _new_id()
    created = datetime.datetime.now(datetime.timezone.utc)
    cert = {"clientCertificateId": cid, "description": body.get("description", "") or "",
            "pemEncodedCertificate": _fake_pem(cid),
            "createdDate": created.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "expirationDate": (created + datetime.timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "tags": dict(body.get("tags") or {})}
    _client_certs(store)[cid] = cert
    return _json(201, dict(cert))


def _get_client_certificates(store):
    return _json(200, {"item": [dict(c) for c in _client_certs(store).values()]})


def _require_cert(store, cid):
    c = _client_certs(store).get(cid)
    if not c:
        raise NotFound(f"Invalid Client Certificate identifier specified: {cid}")
    return c


def _get_client_certificate(store, cid):
    return _json(200, dict(_require_cert(store, cid)))


def _update_client_certificate(store, cid, body):
    c = _require_cert(store, cid)
    for op in body.get("patchOperations") or []:
        if str(op.get("path", "")).lstrip("/") == "description":
            c["description"] = op.get("value")
    return _json(200, dict(c))


def _delete_client_certificate(store, cid):
    _require_cert(store, cid)
    del _client_certs(store)[cid]
    return ApiGwResponse(status=202)


# ── routing table ────────────────────────────────────────────────────────────
def _parse(body):
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return {}


def dispatch(store, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> ApiGwResponse:
    """Native API Gateway v1 control-plane router (`/restapis/...`, `/apikeys`,
    `/usageplans`, `/clientcertificates`, `/account`)."""
    method = (method or "GET").upper()
    p = path.split("?", 1)[0]
    segs = [s for s in p.split("/") if s != ""]
    payload = _parse(body)

    try:
        if not segs:
            return _err(404, "NotFoundException", f"Unknown path: {path}")

        if segs[0] == "account":
            if method == "GET":
                return _get_account(store)
            if method == "PATCH":
                return _update_account(store, payload)

        if segs[0] == "apikeys":
            if len(segs) == 1:
                if method == "POST":
                    return _create_api_key(store, payload)
                if method == "GET":
                    return _get_api_keys(store, query)
            elif len(segs) == 2:
                kid = segs[1]
                if method == "GET":
                    return _get_api_key(store, kid, query)
                if method == "PATCH":
                    return _update_api_key(store, kid, payload)
                if method == "DELETE":
                    return _delete_api_key(store, kid)

        if segs[0] == "usageplans":
            if len(segs) == 1:
                if method == "POST":
                    return _create_usage_plan(store, payload)
                if method == "GET":
                    return _get_usage_plans(store)
            elif len(segs) == 2:
                pid = segs[1]
                if method == "GET":
                    return _get_usage_plan(store, pid)
                if method == "PATCH":
                    return _update_usage_plan(store, pid, payload)
                if method == "DELETE":
                    return _delete_usage_plan(store, pid)
            elif len(segs) == 3 and segs[2] == "keys":
                pid = segs[1]
                if method == "POST":
                    return _create_usage_plan_key(store, pid, payload)
                if method == "GET":
                    return _get_usage_plan_keys(store, pid)
            elif len(segs) == 4 and segs[2] == "keys":
                pid, kid = segs[1], segs[3]
                if method == "DELETE":
                    return _delete_usage_plan_key(store, pid, kid)

        if segs[0] == "clientcertificates":
            if len(segs) == 1:
                if method == "POST":
                    return _create_client_certificate(store, payload)
                if method == "GET":
                    return _get_client_certificates(store)
            elif len(segs) == 2:
                cid = segs[1]
                if method == "GET":
                    return _get_client_certificate(store, cid)
                if method == "PATCH":
                    return _update_client_certificate(store, cid, payload)
                if method == "DELETE":
                    return _delete_client_certificate(store, cid)

        if segs[0] != "restapis":
            return _err(404, "NotFoundException", f"Unknown path: {path}")

        if len(segs) == 1:
            if method == "POST":
                return _create_rest_api(store, payload)
            if method == "GET":
                return _get_rest_apis(store)

        api_id = segs[1] if len(segs) > 1 else ""
        if len(segs) == 2:
            if method == "GET":
                return _json(200, _api_view(_require_api(store, api_id)))
            if method == "PATCH":
                return _update_rest_api(store, api_id, payload)
            if method == "DELETE":
                return _delete_rest_api(store, api_id)

        if len(segs) >= 3 and segs[2] == "resources":
            if len(segs) == 3 and method == "GET":
                return _get_resources(store, api_id)
            if len(segs) == 4:
                res_id = segs[3]
                if method == "POST":
                    return _create_resource(store, api_id, res_id, payload)
                if method == "GET":
                    return _get_resource(store, api_id, res_id)
                if method == "DELETE":
                    return _delete_resource(store, api_id, res_id)
            if len(segs) >= 6 and segs[4] == "methods":
                res_id, http_method = segs[3], segs[5]
                if len(segs) == 6:
                    if method == "PUT":
                        return _put_method(store, api_id, res_id, http_method, payload)
                    if method == "GET":
                        return _get_method(store, api_id, res_id, http_method)
                    if method == "DELETE":
                        return _delete_method(store, api_id, res_id, http_method)
                    if method == "POST":
                        return _test_invoke_method(store, api_id, res_id, http_method, payload)
                if len(segs) == 7 and segs[6] == "integration":
                    if method == "PUT":
                        return _put_integration(store, api_id, res_id, http_method, payload)
                    if method == "GET":
                        return _get_integration(store, api_id, res_id, http_method)
                    if method == "DELETE":
                        return _delete_integration(store, api_id, res_id, http_method)

        if len(segs) >= 3 and segs[2] == "deployments":
            if len(segs) == 3:
                if method == "POST":
                    return _create_deployment(store, api_id, payload)
                if method == "GET":
                    return _get_deployments(store, api_id)
            if len(segs) == 4 and method == "GET":
                return _get_deployment(store, api_id, segs[3])

        if len(segs) >= 3 and segs[2] == "stages":
            if len(segs) == 3:
                if method == "POST":
                    return _create_stage(store, api_id, payload)
                if method == "GET":
                    return _get_stages(store, api_id)
            if len(segs) == 4:
                name = segs[3]
                if method == "GET":
                    return _get_stage(store, api_id, name)
                if method == "PATCH":
                    return _update_stage(store, api_id, name, payload)
                if method == "DELETE":
                    return _delete_stage(store, api_id, name)

        return _err(404, "NotFoundException", f"Unsupported {method} {path}")
    except _E as e:
        return _err(e.status, e.code, e.message)
