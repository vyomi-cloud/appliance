"""API Gateway V2 core — substrate-independent HTTP + WebSocket API control plane
(botocore `apigatewayv2`, 2018-11-29, rest-json).

Speaks the native **API Gateway V2 control-plane wire** (`/v2/apis`, `/v2/domainnames`,
`/v2/vpclinks`, `/v2/tags/{arn}`, `/v2/portals`, `/v2/portalproducts`; JSON, lowerCamelCase
members) so an unmodified aws-sdk-java-v2 / aws-sdk-go-v2 / aws CLI `apigatewayv2` client
manages APIs. A deployed HTTP API can also be INVOKED (`invoke`): route-key matching
(`GET /x/{id}`, `ANY /y`, `{proxy+}`, `$default`) → integration (Lambda proxy payload v2.0
through `lambda_core`, or a MOCK-style static response). NO fastapi / boto3 / socket imports →
loads under Pyodide; state lives on a plain store object (`ApiGwV2Store`) so
nano_persist captures it like every other store.

Resources: Api · Route · RouteResponse · Integration · IntegrationResponse · Stage ·
Deployment · Authorizer · Model · VpcLink · DomainName · ApiMapping · Tags · Portal ·
PortalProduct.

Portal / PortalProduct are the real (undocumented-by-console-UI, but fully public in the
`apigatewayv2` botocore model) developer-portal control plane: `CreatePortal`,
`UpdatePortal`, `DeletePortal`, `GetPortal`/`ListPortals`, `PreviewPortal`, `PublishPortal`
(DisablePortal is a DELETE on the same `/publish` path), and the matching `*PortalProduct`
CRUD + sharing-policy calls. Publishing/disabling actually flips `publishStatus` and
`lastPublished`; `includedPortalProductArns` is validated against real PortalProduct ARNs.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import unquote

REGION = "us-east-1"
GATEWAY_HTTPS_PORT = 9443   # shared Caddy gateway: TLS (internal CA); plain HTTP on 9080
ACCOUNT = "000000000000"
_METHODS = {"ANY", "GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}


class ApiGwV2Store:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.apis: dict = {}
        self.domains: dict = {}
        self.vpclinks: dict = {}
        self.domain_associations: dict = {}
        self.portals: dict = {}
        self.portal_products: dict = {}


_SHARED: ApiGwV2Store | None = None


def shared_store() -> ApiGwV2Store:
    """The appliance-wide store: the native wire (/v2/...) and the console REST
    (/api/apigatewayv2/...) both read/write this one instance."""
    global _SHARED
    if _SHARED is None:
        _SHARED = ApiGwV2Store()
    return _SHARED


@dataclass
class ApiGwV2Response:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


class _E(Exception):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def NotFound(msg):
    return _E("NotFoundException", msg, 404)


def BadRequest(msg):
    return _E("BadRequestException", msg, 400)


def Conflict(msg):
    return _E("ConflictException", msg, 409)


def _json(status, obj=None, headers=None):
    body = b"" if obj is None else json.dumps(obj).encode()
    return ApiGwV2Response(status=status, body=body, headers=headers or {})


def _err(e: _E):
    return ApiGwV2Response(status=e.status, body=json.dumps({"message": e.message}).encode(),
                           headers={"x-amzn-ErrorType": e.code})


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id():
    return uuid.uuid4().hex[:10]


def _out(obj):
    """Public view of a stored entity: drop private (`_x`) keys and nulls."""
    return {k: v for k, v in obj.items() if not k.startswith("_") and v is not None}


# ── child-collection specs (everything under /v2/apis/{apiId}) ───────────────
# plural → (id field, noun for errors, required body fields, defaults)
_CHILD = {
    "routes": ("routeId", "Route", ["routeKey"], {"apiKeyRequired": False, "authorizationType": "NONE"}),
    "integrations": ("integrationId", "Integration", ["integrationType"], {}),
    "authorizers": ("authorizerId", "Authorizer", ["authorizerType", "identitySource", "name"], {}),
    "models": ("modelId", "Model", ["schema", "name"], {"contentType": "application/json"}),
    "deployments": ("deploymentId", "Deployment", [], {}),
}
_AUTH_TYPES = {"NONE", "AWS_IAM", "CUSTOM", "JWT"}
_INTEG_TYPES = {"AWS", "AWS_PROXY", "HTTP", "HTTP_PROXY", "MOCK"}


def _require(body, fields):
    missing = [f for f in fields if body.get(f) in (None, "", [])]
    if missing:
        raise BadRequest(f"{missing[0]} is required")


def _api(store, api_id):
    a = store.apis.get(api_id)
    if not a:
        raise NotFound(f"Invalid API identifier specified {api_id}")
    return a


def _page(items, query):
    """maxResults/nextToken pagination (token = offset)."""
    try:
        start = int((query or {}).get("nextToken") or 0)
    except ValueError:
        raise BadRequest("Invalid nextToken")
    try:
        n = int((query or {}).get("maxResults") or 0)
    except ValueError:
        raise BadRequest("Invalid maxResults")
    if n <= 0:
        return {"items": [_out(i) for i in items[start:]]}
    out = {"items": [_out(i) for i in items[start:start + n]]}
    if start + n < len(items):
        out["nextToken"] = str(start + n)
    return out


def _merge(obj, body, protect):
    for k, v in body.items():
        if k in protect or k.startswith("_"):
            continue
        obj[k] = v


# ── Api ──────────────────────────────────────────────────────────────────────
def _validate_route_key(api, key):
    if api["protocolType"] == "HTTP":
        if key == "$default":
            return
        parts = key.split(" ", 1)
        if len(parts) != 2 or parts[0] not in _METHODS or not parts[1].startswith("/"):
            raise BadRequest(f"Invalid route key: {key}. Route keys must be $default or "
                             "'METHOD /path' (e.g. 'GET /items')")


def _create_api(store, b):
    _require(b, ["name", "protocolType"])
    ptype = b["protocolType"]
    if ptype not in ("HTTP", "WEBSOCKET"):
        raise BadRequest(f"Invalid protocolType: {ptype}")
    if ptype == "WEBSOCKET" and not b.get("routeSelectionExpression"):
        raise BadRequest("routeSelectionExpression is required for WEBSOCKET APIs")
    api_id = _new_id()
    scheme = "wss" if ptype == "WEBSOCKET" else "https"
    api = {
        "apiId": api_id, "name": b["name"], "protocolType": ptype,
        "apiEndpoint": f"{scheme}://{api_id}.execute-api.localhost:{GATEWAY_HTTPS_PORT}",   # served by the shared Caddy gateway
        "apiKeySelectionExpression": b.get("apiKeySelectionExpression", "$request.header.x-api-key"),
        "routeSelectionExpression": b.get("routeSelectionExpression", "$request.method $request.path"),
        "createdDate": _now(), "disableExecuteApiEndpoint": bool(b.get("disableExecuteApiEndpoint", False)),
        "ipAddressType": b.get("ipAddressType", "ipv4"),
        "description": b.get("description"), "version": b.get("version"),
        "corsConfiguration": b.get("corsConfiguration"),
        "disableSchemaValidation": b.get("disableSchemaValidation"),
        "tags": dict(b.get("tags") or {}),
        "routes": {}, "integrations": {}, "authorizers": {}, "models": {}, "deployments": {}, "stages": {},
    }
    store.apis[api_id] = api
    if b.get("target"):                       # quick create: $default route + integration + stage
        if ptype != "HTTP":
            raise BadRequest("target is only supported for HTTP APIs")
        target = b["target"]
        is_lambda = ":lambda:" in target or ":function:" in target
        iid = _new_id()
        api["integrations"][iid] = {
            "integrationId": iid, "integrationType": "AWS_PROXY" if is_lambda else "HTTP_PROXY",
            "integrationUri": target, "payloadFormatVersion": "1.0" if not is_lambda else "2.0",
            "integrationMethod": "ANY", "connectionType": "INTERNET", "timeoutInMillis": 30000,
            "apiGatewayManaged": True}
        rid = _new_id()
        api["routes"][rid] = {"routeId": rid, "routeKey": b.get("routeKey") or "$default",
                              "target": f"integrations/{iid}", "apiKeyRequired": False,
                              "authorizationType": "NONE", "apiGatewayManaged": True}
        dep = _new_deployment(api, {"description": "Automatic deployment triggered by changes to the Api configuration"})
        dep["autoDeployed"] = True
        api["stages"]["$default"] = {
            "stageName": "$default", "autoDeploy": True, "deploymentId": dep["deploymentId"],
            "createdDate": _now(), "lastUpdatedDate": _now(), "apiGatewayManaged": True,
            "defaultRouteSettings": {"detailedMetricsEnabled": False}, "routeSettings": {}, "stageVariables": {}, "tags": {}}
    return _json(201, _api_view(api))


def _api_view(api):
    return {k: v for k, v in _out(api).items()
            if k not in ("routes", "integrations", "authorizers", "models", "deployments", "stages")}


def _update_api(store, api_id, b):
    api = _api(store, api_id)
    if "protocolType" in b and b["protocolType"] != api["protocolType"]:
        pass  # protocolType is immutable — ignored like the real service
    _merge(api, b, {"apiId", "protocolType", "apiEndpoint", "createdDate", "tags"})
    return _json(200, _api_view(api))


def _delete_api(store, api_id):
    _api(store, api_id)
    del store.apis[api_id]
    for dom in store.domains.values():
        for mid in [k for k, m in dom["_mappings"].items() if m.get("apiId") == api_id]:
            del dom["_mappings"][mid]
    return _json(204)


# ── generic children ─────────────────────────────────────────────────────────
def _new_deployment(api, b):
    did = _new_id()
    dep = {"deploymentId": did, "createdDate": _now(), "deploymentStatus": "DEPLOYED",
           "description": b.get("description"), "autoDeployed": False}
    api["deployments"][did] = dep
    return dep


def _get_child(api, plural, cid):
    idf, noun, _, _ = _CHILD[plural]
    c = api[plural].get(cid)
    if not c:
        raise NotFound(f"Invalid {noun} identifier specified {cid}")
    return c


def _autodeploy(api):
    for st in api["stages"].values():
        if st.get("autoDeploy"):
            dep = _new_deployment(api, {"description": "Automatic deployment triggered by changes to the Api configuration"})
            dep["autoDeployed"] = True
            st["deploymentId"] = dep["deploymentId"]
            st["lastUpdatedDate"] = _now()


def _check_refs(api, b):
    if b.get("authorizerId") and b["authorizerId"] not in api["authorizers"]:
        raise NotFound(f"Invalid Authorizer identifier specified {b['authorizerId']}")
    tgt = b.get("target")
    if tgt and tgt.startswith("integrations/") and tgt.split("/", 1)[1] not in api["integrations"]:
        raise NotFound(f"Invalid integration identifier specified {tgt.split('/', 1)[1]}")


def _create_child(store, api_id, plural, b):
    api = _api(store, api_id)
    idf, noun, req, defaults = _CHILD[plural]
    _require(b, req)
    if plural == "routes":
        _validate_route_key(api, b["routeKey"])
        _check_refs(api, b)
        if b.get("authorizationType") and b["authorizationType"] not in _AUTH_TYPES:
            raise BadRequest(f"Invalid authorizationType: {b['authorizationType']}")
        if any(r["routeKey"] == b["routeKey"] for r in api["routes"].values()):
            raise Conflict(f"Route with key {b['routeKey']} already exists")
    if plural == "integrations":
        if b["integrationType"] not in _INTEG_TYPES:
            raise BadRequest(f"Invalid integrationType: {b['integrationType']}")
        if b["integrationType"] != "MOCK" and not b.get("integrationUri") and not b.get("integrationSubtype"):
            raise BadRequest("integrationUri is required for non-MOCK integrations")
        if api["protocolType"] == "HTTP":
            defaults = dict(defaults, payloadFormatVersion="1.0" if b["integrationType"] in ("HTTP", "HTTP_PROXY") else "2.0")
        defaults = dict(defaults, connectionType="INTERNET", timeoutInMillis=30000)
    if plural == "authorizers":
        if b["authorizerType"] not in ("REQUEST", "JWT"):
            raise BadRequest(f"Invalid authorizerType: {b['authorizerType']}")
        if b["authorizerType"] == "JWT" and not b.get("jwtConfiguration"):
            raise BadRequest("jwtConfiguration is required for JWT authorizers")
        if b["authorizerType"] == "REQUEST" and not b.get("authorizerUri"):
            raise BadRequest("authorizerUri is required for REQUEST authorizers")
    if plural == "deployments":
        if b.get("stageName") and b["stageName"] not in api["stages"]:
            raise NotFound(f"Invalid Stage identifier specified {b['stageName']}")
        dep = _new_deployment(api, b)
        if b.get("stageName"):
            api["stages"][b["stageName"]]["deploymentId"] = dep["deploymentId"]
            api["stages"][b["stageName"]]["lastUpdatedDate"] = _now()
        return _json(201, _out(dep))
    cid = _new_id()
    obj = dict(defaults)
    obj.update({k: v for k, v in b.items() if v is not None})
    obj[idf] = cid
    obj["_children"] = {}
    api[plural][cid] = obj
    _autodeploy(api)
    return _json(201, _out(obj))


def _update_child(store, api_id, plural, cid, b):
    api = _api(store, api_id)
    idf = _CHILD[plural][0]
    obj = _get_child(api, plural, cid)
    if plural == "routes":
        if "routeKey" in b:
            _validate_route_key(api, b["routeKey"])
        _check_refs(api, b)
    if plural == "integrations" and b.get("integrationType") not in (None, *_INTEG_TYPES):
        raise BadRequest(f"Invalid integrationType: {b['integrationType']}")
    _merge(obj, b, {idf})
    if plural == "deployments":
        return _json(200, _out(obj))
    _autodeploy(api)
    return _json(200, _out(obj))


def _delete_child(store, api_id, plural, cid):
    api = _api(store, api_id)
    _get_child(api, plural, cid)
    del api[plural][cid]
    _autodeploy(api)
    return _json(204)


# ── grandchildren: RouteResponse / IntegrationResponse ───────────────────────
_GRAND = {
    "routeresponses": ("routes", "routeResponseId", "RouteResponse", ["routeResponseKey"]),
    "integrationresponses": ("integrations", "integrationResponseId", "IntegrationResponse", ["integrationResponseKey"]),
}


def _grand_parent(store, api_id, kind, pid):
    api = _api(store, api_id)
    parent_plural, idf, noun, req = _GRAND[kind]
    parent = _get_child(api, parent_plural, pid)
    return api, parent, idf, noun, req


def _create_grand(store, api_id, kind, pid, b):
    api, parent, idf, noun, req = _grand_parent(store, api_id, kind, pid)
    _require(b, req)
    gid = _new_id()
    obj = {k: v for k, v in b.items() if v is not None}
    obj[idf] = gid
    parent["_children"].setdefault(kind, {})[gid] = obj
    return _json(201, _out(obj))


def _get_grand(store, api_id, kind, pid, gid):
    _, parent, idf, noun, _ = _grand_parent(store, api_id, kind, pid)
    g = parent["_children"].get(kind, {}).get(gid)
    if not g:
        raise NotFound(f"Invalid {noun} identifier specified {gid}")
    return g


# ── Stage (keyed by name) ────────────────────────────────────────────────────
def _create_stage(store, api_id, b):
    api = _api(store, api_id)
    _require(b, ["stageName"])
    name = b["stageName"]
    if not re.fullmatch(r"[a-zA-Z0-9_\-]+|\$default", name):
        raise BadRequest(f"Invalid stage name: {name}")
    if name in api["stages"]:
        raise Conflict(f"Stage already exists: {name}")
    if b.get("deploymentId") and b["deploymentId"] not in api["deployments"]:
        raise NotFound(f"Invalid Deployment identifier specified {b['deploymentId']}")
    st = {"stageName": name, "createdDate": _now(), "lastUpdatedDate": _now(),
          "autoDeploy": bool(b.get("autoDeploy", False)), "deploymentId": b.get("deploymentId"),
          "description": b.get("description"), "stageVariables": dict(b.get("stageVariables") or {}),
          "routeSettings": dict(b.get("routeSettings") or {}), "tags": dict(b.get("tags") or {}),
          "defaultRouteSettings": b.get("defaultRouteSettings") or {"detailedMetricsEnabled": False},
          "accessLogSettings": b.get("accessLogSettings"), "clientCertificateId": b.get("clientCertificateId"),
          "apiGatewayManaged": False}
    if st["autoDeploy"] and not st["deploymentId"]:
        dep = _new_deployment(api, {"description": "Automatic deployment triggered by changes to the Api configuration"})
        dep["autoDeployed"] = True
        st["deploymentId"] = dep["deploymentId"]
    api["stages"][name] = st
    return _json(201, _out(st))


def _get_stage(api, name):
    st = api["stages"].get(name)
    if not st:
        raise NotFound(f"Invalid Stage identifier specified {name}")
    return st


# ── DomainName / ApiMapping / VpcLink ────────────────────────────────────────
def _create_domain(store, b):
    _require(b, ["domainName"])
    name = b["domainName"]
    if name in store.domains:
        raise Conflict(f"The domain name resource already exists: {name}")
    configs = b.get("domainNameConfigurations") or []
    for c in configs:
        c.setdefault("endpointType", "REGIONAL")
        c.setdefault("domainNameStatus", "AVAILABLE")
        c.setdefault("apiGatewayDomainName", f"d-{_new_id()}.execute-api.{REGION}.amazonaws.com")
        c.setdefault("hostedZoneId", "Z1UJRXOUMOOFQ8")
        c.setdefault("securityPolicy", "TLS_1_2")
    d = {"domainName": name, "domainNameArn": f"arn:aws:apigateway:{REGION}::/domainnames/{name}",
         "domainNameConfigurations": configs, "apiMappingSelectionExpression": "$request.basepath",
         "mutualTlsAuthentication": b.get("mutualTlsAuthentication"), "routingMode": b.get("routingMode", "API_MAPPING_ONLY"),
         "tags": dict(b.get("tags") or {}), "_mappings": {}}
    store.domains[name] = d
    return _json(201, _out(d))


def _domain(store, name):
    d = store.domains.get(name)
    if not d:
        raise NotFound(f"Invalid domain name identifier specified {name}")
    return d


def _create_mapping(store, name, b):
    d = _domain(store, name)
    _require(b, ["apiId", "stage"])
    _api(store, b["apiId"])
    mid = _new_id()
    m = {"apiMappingId": mid, "apiId": b["apiId"], "stage": b["stage"], "apiMappingKey": b.get("apiMappingKey")}
    d["_mappings"][mid] = m
    return _json(201, _out(m))


def _create_vpclink(store, b):
    _require(b, ["subnetIds", "name"])
    vid = _new_id()
    v = {"vpcLinkId": vid, "name": b["name"], "subnetIds": list(b["subnetIds"]),
         "securityGroupIds": list(b.get("securityGroupIds") or []), "createdDate": _now(),
         "vpcLinkStatus": "AVAILABLE", "vpcLinkStatusMessage": "VPC link is ready to route traffic",
         "vpcLinkVersion": "V2", "tags": dict(b.get("tags") or {})}
    store.vpclinks[vid] = v
    return _json(201, _out(v))


def _vpclink(store, vid):
    v = store.vpclinks.get(vid)
    if not v:
        raise NotFound(f"Invalid VpcLink identifier specified {vid}")
    return v


# ── DomainNameAccessAssociation (VPC-endpoint access to a private custom domain) ─────
def _create_domain_association(store, b):
    _require(b, ["domainNameArn", "accessAssociationSourceType", "accessAssociationSource"])
    if b["accessAssociationSourceType"] != "VPCE":
        raise BadRequest(f"Invalid accessAssociationSourceType: {b['accessAssociationSourceType']}")
    if not any(d["domainNameArn"] == b["domainNameArn"] for d in store.domains.values()):
        raise NotFound(f"Invalid domain name ARN specified {b['domainNameArn']}")
    aid = _new_id()
    a = {"domainNameAccessAssociationArn": f"arn:aws:apigateway:{REGION}::/domainnameaccessassociations/{aid}",
         "domainNameArn": b["domainNameArn"], "accessAssociationSourceType": "VPCE",
         "accessAssociationSource": b["accessAssociationSource"], "tags": dict(b.get("tags") or {})}
    store.domain_associations[aid] = a
    return _json(201, _out(a))


def _domain_association(store, aid):
    a = store.domain_associations.get(aid)
    if not a:
        raise NotFound(f"Invalid domain name access association identifier specified {aid}")
    return a


def _aid_from_arn(arn):
    return arn.rsplit("/", 1)[-1]


# ── Portal / PortalProduct (developer portal control plane) ──────────────────
def _portal(store, pid):
    p = store.portals.get(pid)
    if not p:
        raise NotFound(f"Invalid portal identifier specified {pid}")
    return p


def _portal_product(store, ppid):
    p = store.portal_products.get(ppid)
    if not p:
        raise NotFound(f"Invalid portal product identifier specified {ppid}")
    return p


def _endpoint_config(portal_id, req):
    acm = (req or {}).get("acmManaged") or {}
    return {
        "certificateArn": acm.get("certificateArn"), "domainName": acm.get("domainName"),
        "portalDefaultDomainName": f"{portal_id}.portal.execute-api.{REGION}.localhost",
        "portalDomainHostedZoneId": "Z1UJRXOUMOOFQ8",
    }


def _check_portal_products(store, arns):
    for arn in arns or []:
        if not any(p["portalProductArn"] == arn for p in store.portal_products.values()):
            raise NotFound(f"Invalid portal product ARN specified {arn}")


def _require_portal_content(pc):
    if not pc or not pc.get("displayName"):
        raise BadRequest("portalContent.displayName is required")
    if not (pc.get("theme") or {}).get("customColors"):
        raise BadRequest("portalContent.theme.customColors is required")


def _create_portal(store, b):
    _require(b, ["authorization", "endpointConfiguration", "portalContent"])
    _require_portal_content(b["portalContent"])
    _check_portal_products(store, b.get("includedPortalProductArns"))
    pid = _new_id()
    p = {
        "portalId": pid, "portalArn": f"arn:aws:apigateway:{REGION}::/portals/{pid}",
        "authorization": b["authorization"], "endpointConfiguration": _endpoint_config(pid, b["endpointConfiguration"]),
        "includedPortalProductArns": list(b.get("includedPortalProductArns") or []),
        "lastModified": _now(), "lastPublished": None, "lastPublishedDescription": None,
        "portalContent": b["portalContent"], "publishStatus": "DISABLED", "preview": None,
        "rumAppMonitorName": b.get("rumAppMonitorName"), "statusException": None, "tags": dict(b.get("tags") or {}),
    }
    store.portals[pid] = p
    return _json(201, _out(p))


def _update_portal(store, pid, b):
    p = _portal(store, pid)
    if "includedPortalProductArns" in b:
        _check_portal_products(store, b["includedPortalProductArns"])
    if "portalContent" in b:
        _require_portal_content(b["portalContent"])
    if "endpointConfiguration" in b:
        b = dict(b, endpointConfiguration=_endpoint_config(pid, b["endpointConfiguration"]))
    _merge(p, b, {"portalId", "portalArn", "publishStatus", "lastPublished", "lastPublishedDescription", "preview", "statusException", "tags"})
    p["lastModified"] = _now()
    return _json(200, _out(p))


def _delete_portal(store, pid):
    _portal(store, pid)
    del store.portals[pid]
    return _json(204)


def _preview_portal(store, pid):
    p = _portal(store, pid)
    p["preview"] = {"previewStatus": "PREVIEW_READY",
                    "previewUrl": f"https://{pid}-preview.portal.execute-api.{REGION}.localhost",
                    "statusException": None}
    return _json(202, {})


def _publish_portal(store, pid, b):
    p = _portal(store, pid)
    p["publishStatus"] = "PUBLISHED"
    p["lastPublished"] = _now()
    p["lastPublishedDescription"] = b.get("description")
    p["statusException"] = None
    return _json(202, {})


def _disable_portal(store, pid):
    p = _portal(store, pid)
    p["publishStatus"] = "DISABLED"
    return _json(204)


def _create_portal_product(store, b):
    _require(b, ["displayName"])
    ppid = _new_id()
    pp = {
        "portalProductId": ppid, "portalProductArn": f"arn:aws:apigateway:{REGION}::/portalproducts/{ppid}",
        "description": b.get("description"), "displayName": b["displayName"],
        "displayOrder": {"contents": [], "overviewPageArn": None, "productPageArns": []},
        "lastModified": _now(), "tags": dict(b.get("tags") or {}), "_sharingPolicy": None,
    }
    store.portal_products[ppid] = pp
    return _json(201, _out(pp))


def _update_portal_product(store, ppid, b):
    pp = _portal_product(store, ppid)
    _merge(pp, b, {"portalProductId", "portalProductArn", "tags"})
    pp["lastModified"] = _now()
    return _json(200, _out(pp))


def _delete_portal_product(store, ppid):
    pp = _portal_product(store, ppid)
    if any(arn == pp["portalProductArn"] for p in store.portals.values() for arn in p["includedPortalProductArns"]):
        raise Conflict(f"Portal product {ppid} is included in a portal")
    del store.portal_products[ppid]
    return _json(204)


def _get_sharing_policy(store, ppid):
    pp = _portal_product(store, ppid)
    if pp.get("_sharingPolicy") is None:
        raise NotFound(f"No sharing policy for portal product {ppid}")
    return _json(200, {"portalProductId": ppid, "policyDocument": pp["_sharingPolicy"]})


def _put_sharing_policy(store, ppid, b):
    pp = _portal_product(store, ppid)
    _require(b, ["policyDocument"])
    pp["_sharingPolicy"] = b["policyDocument"]
    return _json(200, {})


def _delete_sharing_policy(store, ppid):
    pp = _portal_product(store, ppid)
    pp["_sharingPolicy"] = None
    return _json(204)


# ── tags ─────────────────────────────────────────────────────────────────────
def _tag_target(store, arn):
    m = re.fullmatch(r"arn:aws:apigateway:[^:]*::/(.+)", arn)
    if not m:
        raise BadRequest(f"Invalid ARN: {arn}")
    parts = m.group(1).split("/")
    if parts[0] == "apis" and len(parts) == 2:
        return _api(store, parts[1])
    if parts[0] == "apis" and len(parts) == 4 and parts[2] == "stages":
        return _get_stage(_api(store, parts[1]), parts[3])
    if parts[0] == "domainnames" and len(parts) == 2:
        return _domain(store, parts[1])
    if parts[0] == "vpclinks" and len(parts) == 2:
        return _vpclink(store, parts[1])
    if parts[0] == "portals" and len(parts) == 2:
        return _portal(store, parts[1])
    if parts[0] == "portalproducts" and len(parts) == 2:
        return _portal_product(store, parts[1])
    raise NotFound(f"Invalid resource ARN: {arn}")


# ── routing table ────────────────────────────────────────────────────────────
def _routes():
    R = []

    def add(method, pattern, fn):
        R.append((method, re.compile("^" + pattern + "$"), fn))

    add("POST", r"apis", lambda s, q, b: _create_api(s, b))
    add("GET", r"apis", lambda s, q, b: _json(200, _page(list(map(_api_view, s.apis.values())), q)))
    add("GET", r"apis/([^/]+)", lambda s, q, b, a: _json(200, _api_view(_api(s, a))))
    add("PATCH", r"apis/([^/]+)", lambda s, q, b, a: _update_api(s, a, b))
    add("DELETE", r"apis/([^/]+)", lambda s, q, b, a: _delete_api(s, a))
    add("DELETE", r"apis/([^/]+)/cors", lambda s, q, b, a: (_api(s, a).update(corsConfiguration=None), _json(204))[1])
    for plural in _CHILD:
        add("POST", rf"apis/([^/]+)/{plural}", lambda s, q, b, a, p=plural: _create_child(s, a, p, b))
        add("GET", rf"apis/([^/]+)/{plural}",
            lambda s, q, b, a, p=plural: _json(200, _page(list(_api(s, a)[p].values()), q)))
        add("GET", rf"apis/([^/]+)/{plural}/([^/]+)",
            lambda s, q, b, a, c, p=plural: _json(200, _out(_get_child(_api(s, a), p, c))))
        add("PATCH", rf"apis/([^/]+)/{plural}/([^/]+)", lambda s, q, b, a, c, p=plural: _update_child(s, a, p, c, b))
        add("DELETE", rf"apis/([^/]+)/{plural}/([^/]+)", lambda s, q, b, a, c, p=plural: _delete_child(s, a, p, c))
    add("GET", r"apis/([^/]+)/models/([^/]+)/template",
        lambda s, q, b, a, m: (_get_child(_api(s, a), "models", m),
                               _json(200, {"value": "#set($inputRoot = $input.path('$'))\n{ }"}))[1])
    add("DELETE", r"apis/([^/]+)/routes/([^/]+)/requestparameters/([^/]+)",
        lambda s, q, b, a, r, k: (_get_child(_api(s, a), "routes", r).get("requestParameters", {}).pop(unquote(k), None),
                                  _json(204))[1])
    for kind, (pp, idf, noun, req) in _GRAND.items():
        base = rf"apis/([^/]+)/{pp}/([^/]+)/{kind}"
        add("POST", base, lambda s, q, b, a, p, k=kind: _create_grand(s, a, k, p, b))
        add("GET", base, lambda s, q, b, a, p, k=kind: _json(200, _page(
            list(_grand_parent(s, a, k, p)[1]["_children"].get(k, {}).values()), q)))
        add("GET", base + "/([^/]+)", lambda s, q, b, a, p, g, k=kind: _json(200, _out(_get_grand(s, a, k, p, g))))
        add("PATCH", base + "/([^/]+)",
            lambda s, q, b, a, p, g, k=kind: (_merge(_get_grand(s, a, k, p, g), b, {_GRAND[k][1]}),
                                              _json(200, _out(_get_grand(s, a, k, p, g))))[1])
        add("DELETE", base + "/([^/]+)",
            lambda s, q, b, a, p, g, k=kind: (_get_grand(s, a, k, p, g),
                                              _grand_parent(s, a, k, p)[1]["_children"][k].pop(g), _json(204))[2])
    # stages
    add("POST", r"apis/([^/]+)/stages", lambda s, q, b, a: _create_stage(s, a, b))
    add("GET", r"apis/([^/]+)/stages", lambda s, q, b, a: _json(200, _page(list(_api(s, a)["stages"].values()), q)))
    add("GET", r"apis/([^/]+)/stages/([^/]+)", lambda s, q, b, a, n: _json(200, _out(_get_stage(_api(s, a), unquote(n)))))
    add("PATCH", r"apis/([^/]+)/stages/([^/]+)", lambda s, q, b, a, n: _update_stage(s, a, unquote(n), b))
    add("DELETE", r"apis/([^/]+)/stages/([^/]+)",
        lambda s, q, b, a, n: (_get_stage(_api(s, a), unquote(n)), _api(s, a)["stages"].pop(unquote(n)), _json(204))[2])
    add("DELETE", r"apis/([^/]+)/stages/([^/]+)/accesslogsettings",
        lambda s, q, b, a, n: (_get_stage(_api(s, a), unquote(n)).update(accessLogSettings=None), _json(204))[1])
    add("DELETE", r"apis/([^/]+)/stages/([^/]+)/routesettings/([^/]+)",
        lambda s, q, b, a, n, k: (_get_stage(_api(s, a), unquote(n)).get("routeSettings", {}).pop(unquote(k), None),
                                  _json(204))[1])
    add("DELETE", r"apis/([^/]+)/stages/([^/]+)/cache/authorizers",
        lambda s, q, b, a, n: (_get_stage(_api(s, a), unquote(n)), _json(204))[1])
    # domain names + api mappings
    add("POST", r"domainnames", lambda s, q, b: _create_domain(s, b))
    add("GET", r"domainnames", lambda s, q, b: _json(200, _page(list(s.domains.values()), q)))
    add("GET", r"domainnames/([^/]+)", lambda s, q, b, n: _json(200, _out(_domain(s, unquote(n)))))
    add("PATCH", r"domainnames/([^/]+)",
        lambda s, q, b, n: (_merge(_domain(s, unquote(n)), b, {"domainName", "domainNameArn"}),
                            _json(200, _out(_domain(s, unquote(n)))))[1])
    add("DELETE", r"domainnames/([^/]+)", lambda s, q, b, n: (_domain(s, unquote(n)), s.domains.pop(unquote(n)), _json(204))[2])
    add("POST", r"domainnames/([^/]+)/apimappings", lambda s, q, b, n: _create_mapping(s, unquote(n), b))
    add("GET", r"domainnames/([^/]+)/apimappings",
        lambda s, q, b, n: _json(200, _page(list(_domain(s, unquote(n))["_mappings"].values()), q)))
    add("GET", r"domainnames/([^/]+)/apimappings/([^/]+)", lambda s, q, b, n, m: _json(200, _out(_get_mapping(s, n, m))))
    add("PATCH", r"domainnames/([^/]+)/apimappings/([^/]+)",
        lambda s, q, b, n, m: (_merge(_get_mapping(s, n, m), b, {"apiMappingId"}), _json(200, _out(_get_mapping(s, n, m))))[1])
    add("DELETE", r"domainnames/([^/]+)/apimappings/([^/]+)",
        lambda s, q, b, n, m: (_get_mapping(s, n, m), _domain(s, unquote(n))["_mappings"].pop(m), _json(204))[2])
    # vpc links
    add("POST", r"vpclinks", lambda s, q, b: _create_vpclink(s, b))
    add("GET", r"vpclinks", lambda s, q, b: _json(200, _page(list(s.vpclinks.values()), q)))
    add("GET", r"vpclinks/([^/]+)", lambda s, q, b, v: _json(200, _out(_vpclink(s, v))))
    add("PATCH", r"vpclinks/([^/]+)",
        lambda s, q, b, v: (_merge(_vpclink(s, v), {"name": b.get("name")} if b.get("name") else {}, {"vpcLinkId"}),
                            _json(200, _out(_vpclink(s, v))))[1])
    add("DELETE", r"vpclinks/([^/]+)", lambda s, q, b, v: (_vpclink(s, v), s.vpclinks.pop(v), _json(202))[2])
    # domain name access associations
    add("POST", r"domainnameaccessassociations", lambda s, q, b: _create_domain_association(s, b))
    add("GET", r"domainnameaccessassociations",
        lambda s, q, b: _json(200, _page([a for a in s.domain_associations.values()
                                           if not (q or {}).get("domainNameArn") or a["domainNameArn"] == q["domainNameArn"]], q)))
    add("GET", r"domainnameaccessassociations/([^/]+)",
        lambda s, q, b, aid: _json(200, _out(_domain_association(s, _aid_from_arn(unquote(aid))))))
    add("DELETE", r"domainnameaccessassociations/([^/]+)",
        lambda s, q, b, aid: (_domain_association(s, _aid_from_arn(unquote(aid))),
                              s.domain_associations.pop(_aid_from_arn(unquote(aid))), _json(202))[2])
    # portals (developer portal control plane)
    add("POST", r"portals", lambda s, q, b: _create_portal(s, b))
    add("GET", r"portals", lambda s, q, b: _json(200, _page(list(s.portals.values()), q)))
    add("GET", r"portals/([^/]+)", lambda s, q, b, p: _json(200, _out(_portal(s, p))))
    add("PATCH", r"portals/([^/]+)", lambda s, q, b, p: _update_portal(s, p, b))
    add("DELETE", r"portals/([^/]+)", lambda s, q, b, p: _delete_portal(s, p))
    add("POST", r"portals/([^/]+)/preview", lambda s, q, b, p: _preview_portal(s, p))
    add("POST", r"portals/([^/]+)/publish", lambda s, q, b, p: _publish_portal(s, p, b))
    add("DELETE", r"portals/([^/]+)/publish", lambda s, q, b, p: _disable_portal(s, p))
    # portal products
    add("POST", r"portalproducts", lambda s, q, b: _create_portal_product(s, b))
    add("GET", r"portalproducts", lambda s, q, b: _json(200, _page(list(s.portal_products.values()), q)))
    add("GET", r"portalproducts/([^/]+)", lambda s, q, b, p: _json(200, _out(_portal_product(s, p))))
    add("PATCH", r"portalproducts/([^/]+)", lambda s, q, b, p: _update_portal_product(s, p, b))
    add("DELETE", r"portalproducts/([^/]+)", lambda s, q, b, p: _delete_portal_product(s, p))
    add("GET", r"portalproducts/([^/]+)/sharingpolicy", lambda s, q, b, p: _get_sharing_policy(s, p))
    add("PUT", r"portalproducts/([^/]+)/sharingpolicy", lambda s, q, b, p: _put_sharing_policy(s, p, b))
    add("DELETE", r"portalproducts/([^/]+)/sharingpolicy", lambda s, q, b, p: _delete_sharing_policy(s, p))
    # tags
    add("GET", r"tags/(.+)", lambda s, q, b, arn: _json(200, {"tags": dict(_tag_target(s, unquote(arn)).get("tags") or {})}))
    add("POST", r"tags/(.+)", lambda s, q, b, arn: _tag(s, unquote(arn), b))
    add("DELETE", r"tags/(.+)", lambda s, q, b, arn: _untag(s, unquote(arn), q))
    return R


def _get_mapping(store, name, mid):
    m = _domain(store, unquote(name))["_mappings"].get(mid)
    if not m:
        raise NotFound(f"Invalid ApiMapping identifier specified {mid}")
    return m


def _update_stage(store, api_id, name, b):
    api = _api(store, api_id)
    st = _get_stage(api, name)
    if b.get("deploymentId") and b["deploymentId"] not in api["deployments"]:
        raise NotFound(f"Invalid Deployment identifier specified {b['deploymentId']}")
    _merge(st, b, {"stageName", "createdDate", "apiGatewayManaged"})
    st["lastUpdatedDate"] = _now()
    return _json(200, _out(st))


def _tag(store, arn, b):
    t = _tag_target(store, arn)
    t.setdefault("tags", {}).update({str(k): str(v) for k, v in (b.get("tags") or {}).items()})
    return _json(201, {})


def _untag(store, arn, query):
    t = _tag_target(store, arn)
    keys = (query or {}).get("tagKeys")
    keys = keys if isinstance(keys, list) else ([keys] if keys else [])
    for k in keys:
        (t.get("tags") or {}).pop(k, None)
    return _json(204)


_ROUTES = _routes()


def console_view(api: dict) -> dict:
    """Console grid/detail row for an API — every grid column is always populated."""
    return {
        "api_id": api["apiId"], "id": api["apiId"], "name": api["name"],
        "protocol_type": api["protocolType"], "api_endpoint": api["apiEndpoint"],
        "route_count": len(api["routes"]), "integration_count": len(api["integrations"]),
        "stage_count": len(api["stages"]), "created": api["createdDate"],
        "description": api.get("description") or "", "version": api.get("version") or "",
        "route_selection_expression": api["routeSelectionExpression"],
        "ip_address_type": api.get("ipAddressType", "ipv4"),
        "status": "AVAILABLE", "tags": dict(api.get("tags") or {}),
        "arn": f"arn:aws:apigateway:{REGION}::/apis/{api['apiId']}",
    }


CHANGE_LISTENERS: list = []   # callables(store) fired after every successful mutation (gateway route sync)


def _notify_changed(store):
    for cb in list(CHANGE_LISTENERS):
        try:
            cb(store)
        except Exception:
            pass


def _parse(body):
    try:
        d = json.loads(body.decode("utf-8")) if body else {}
        return d if isinstance(d, dict) else {}
    except Exception:
        raise BadRequest("Invalid JSON body")


def dispatch(store, method: str, path: str, query: dict | None = None,
             headers: dict | None = None, body: bytes = b"") -> ApiGwV2Response:
    """Native API Gateway V2 control-plane router (`/v2/...`)."""
    method = (method or "GET").upper()
    raw, _, qs = path.partition("?")
    if qs and not query:
        from urllib.parse import parse_qs
        query = {k: (v if len(v) > 1 else v[0]) for k, v in parse_qs(qs).items()}
    rel = raw.strip("/")
    if not rel.startswith("v2/") and rel != "v2":
        return _err(NotFound(f"Unknown path: {path}"))
    rel = rel[3:]
    try:
        for m, rx, fn in _ROUTES:
            if m != method:
                continue
            mt = rx.match(rel)
            if mt:
                b = _parse(body) if method in ("POST", "PUT", "PATCH") else {}
                out = fn(store, query or {}, b, *mt.groups())
                if method != "GET" and out.status < 300:
                    _notify_changed(store)
                return out
        known = any(rx.match(rel) for _, rx, _ in _ROUTES)
        return _err(_E("MethodNotAllowedException" if known else "NotFoundException",
                       f"Unsupported {method} {path}", 405 if known else 404))
    except _E as e:
        return _err(e)


# ── data plane: invoke a deployed HTTP API ───────────────────────────────────
def _route_match(api, method, path):
    """Pick the route for (method, path): exact > param > greedy > ANY > $default."""
    best, best_score, params = None, -1, {}
    req = "/" + path.strip("/")
    for r in api["routes"].values():
        key = r["routeKey"]
        if key == "$default":
            if best is None:
                best, best_score, params = r, 0, {}
            continue
        m, _, tmpl = key.partition(" ")
        if m not in (method, "ANY"):
            continue
        rx, names = "", []
        for part in [p for p in tmpl.split("/") if p]:
            g = re.fullmatch(r"\{([^/}]+?)(\+)?\}", part)
            if g:
                names.append(g.group(1))
                rx += "/(.+)" if g.group(2) else "/([^/]+)"
            else:
                rx += "/" + re.escape(part)
        mt = re.fullmatch(rx or "/", req)
        if not mt:
            continue
        score = 10 + len(tmpl) * 2 - 5 * len(names) + (1 if m == method else 0)
        if score > best_score:
            best, best_score, params = r, score, dict(zip(names, mt.groups()))
    return best, params


def invoke(store, api_id, stage, method, path, headers=None, query=None, body=b"", lambda_store=None):
    """Route a request through a deployed HTTP API (CORS, throttling, authorizers, Lambda
    proxy 1.0/2.0, HTTP proxy — see core/apigatewayv2_gateway.py). Returns an ApiGwV2Response."""
    from core import apigatewayv2_gateway as gw
    invoker = gw._default_invoker(lambda_store if lambda_store is not None else store)
    return gw.handle(store, api_id, stage, method, path, headers, query, body, invoker=invoker)
