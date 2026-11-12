"""API Gateway v1 (REST) wire gaps, served behind core/apigateway_core.dispatch (v4 wire sweep): authorizers (incl.
TestInvokeAuthorizer, which really invokes the authorizer Lambda), models (+ default templates), request validators, gateway
responses, method + integration responses, UpdateMethod / UpdateIntegration / UpdateResource / UpdateDeployment /
DeleteDeployment, custom domain names + base path mappings, VPC links, tags, documentation parts + versions, usage-plan key
lookup + usage, stage cache flush, GetExport (OpenAPI 3 / Swagger 2 generated from the live resources + methods +
integrations) and PutRestApi / ImportRestApi (real OpenAPI 3 / Swagger 2 JSON import: resources, methods, integrations,
method responses, models and request validators come from the document).

Everything reads and writes the same ``_apigateway_apis`` store the console and the invoke path use, so an imported API is
invokable and an exported one reflects console edits. No fastapi / boto3 imports; loads under Pyodide.

Honest limits: YAML documents are not parsed (JSON only); API Gateway extensions other than x-amazon-apigateway-integration,
x-amazon-apigateway-request-validator(s) and the authorizer security schemes are ignored on import; SDK generation
(GetSdk) is not implemented; domain names carry no real certificate or DNS; VPC links are records (no NLB data path)."""
from __future__ import annotations

import json
import re
import urllib.parse
import uuid

_PATCH_OPS = ("add", "remove", "replace", "copy", "move", "test")


def _core(c):
    return c


def _tbl(store, name):
    m = getattr(store, name, None)
    if m is None:
        m = {}
        setattr(store, name, m)
    return m


# ───────────────────────── patch helper ─────────────────────────
def _patch(c, obj, ops, allowed=None, rename=None):
    """RFC-6902-ish patch ops the way API Gateway applies them: `/field` (top level) or `/field/key` (map entry)."""
    rename = rename or {}
    for op in ops or []:
        if op.get("op") not in _PATCH_OPS:
            raise c.BadRequest(f"Invalid patch operation {op.get('op')}")
        path = str(op.get("path", "")).lstrip("/")
        if not path:
            continue
        parts = [p.replace("~1", "/").replace("~0", "~") for p in path.split("/", 1)]
        key = rename.get(parts[0], parts[0])
        if allowed is not None and key not in allowed:
            raise c.BadRequest(f"Invalid patch path '/{path}': {parts[0]} is not patchable")
        verb, val = op["op"], op.get("value")
        if len(parts) == 1:
            if verb == "remove":
                obj.pop(key, None)
            elif isinstance(obj.get(key), bool) and isinstance(val, str):
                obj[key] = val.lower() == "true"
            elif isinstance(obj.get(key), list) and verb == "add":
                obj[key].append(val)
            elif isinstance(obj.get(key), list) and verb == "replace":
                obj[key] = [val]
            else:
                obj[key] = val
        else:
            sub = obj.setdefault(key, {})
            if not isinstance(sub, dict):
                raise c.BadRequest(f"Invalid patch path '/{path}'")
            if verb == "remove":
                sub.pop(parts[1], None)
            else:
                sub[parts[1]] = val


def _json(c, status, obj):
    return c._json(status, obj)


def _empty(c, status=202):
    return c.ApiGwResponse(status=status)


def _page(items, query, key="item"):
    pos = (query or {}).get("position")
    lim = (query or {}).get("limit")
    start = int(pos) if pos not in (None, "") else 0
    lim = int(lim) if lim not in (None, "") else 25
    out = {key: items[start:start + lim]}
    if start + lim < len(items):
        out["position"] = str(start + lim)
    return out


def _first(v):
    return v[0] if isinstance(v, list) else v


# ───────────────────────── authorizers ─────────────────────────
_AUTH_TYPES = ("TOKEN", "REQUEST", "COGNITO_USER_POOLS")


def _authorizers(api):
    return api.setdefault("authorizers", {})


def create_authorizer(c, store, api, q, body):
    t = body.get("type")
    if t not in _AUTH_TYPES:
        raise c.BadRequest(f"Invalid authorizer type '{t}'. Valid types: {list(_AUTH_TYPES)}")
    if not body.get("name"):
        raise c.BadRequest("Authorizer name is required")
    if t in ("TOKEN", "REQUEST") and not body.get("authorizerUri"):
        raise c.BadRequest("authorizerUri is required for TOKEN and REQUEST authorizers")
    if t == "COGNITO_USER_POOLS" and not body.get("providerARNs"):
        raise c.BadRequest("providerARNs is required for COGNITO_USER_POOLS authorizers")
    if t == "TOKEN" and not body.get("identitySource"):
        raise c.BadRequest("identitySource is required for TOKEN authorizers")
    aid = c._new_id()
    a = {"id": aid, "name": body["name"], "type": t}
    for k in ("authType", "authorizerUri", "authorizerCredentials", "identitySource", "identityValidationExpression", "providerARNs"):
        if body.get(k) is not None:
            a[k] = body[k]
    a["authorizerResultTtlInSeconds"] = int(body.get("authorizerResultTtlInSeconds", 300))
    _authorizers(api)[aid] = a
    return _json(c, 201, a)


def _authorizer(c, api, aid):
    a = _authorizers(api).get(aid)
    if a is None:
        raise c.NotFound(f"Invalid Authorizer identifier specified: {aid}")
    return a


def update_authorizer(c, store, api, aid, body):
    a = _authorizer(c, api, aid)
    _patch(c, a, body.get("patchOperations"), {"name", "type", "authType", "authorizerUri", "authorizerCredentials", "identitySource",
                                               "identityValidationExpression", "authorizerResultTtlInSeconds", "providerARNs"})
    if isinstance(a.get("authorizerResultTtlInSeconds"), str):
        a["authorizerResultTtlInSeconds"] = int(a["authorizerResultTtlInSeconds"])
    return _json(c, 200, a)


def delete_authorizer(c, store, api, aid):
    _authorizer(c, api, aid)
    if any(m.get("authorizerId") == aid for r in api["resources"].values() for m in r["methods"].values()):
        raise c.Conflict(f"Authorizer {aid} is in use by one or more methods")
    del _authorizers(api)[aid]
    return _empty(c, 202)


def test_invoke_authorizer(c, store, api, aid, body):
    a = _authorizer(c, api, aid)
    hdrs = {k.lower(): v for k, v in (body.get("headers") or {}).items()}
    token = hdrs.get((a.get("identitySource") or "method.request.header.Authorization").rsplit(".", 1)[-1].lower())
    if a["type"] == "TOKEN" and a.get("identityValidationExpression") and token is not None and not re.search(a["identityValidationExpression"], token):
        return _json(c, 200, {"clientStatus": 401, "latency": 0, "log": "Execution failed due to a TOKEN failing identityValidationExpression", "principalId": None})
    if a["type"] != "COGNITO_USER_POOLS":
        lam = store
        fn = re.search(r"functions/(arn:aws:lambda:[^/]+|[^/]+)/invocations", a.get("authorizerUri", ""))
        if lam is None or not fn:
            raise c.BadRequest("authorizerUri must be a Lambda invocation URI")
        name = fn.group(1).rsplit(":", 1)[-1] if fn.group(1).startswith("arn:") else fn.group(1)
        if a["type"] == "TOKEN":
            event = {"type": "TOKEN", "authorizationToken": token or body.get("authorizationToken", ""), "methodArn": f"arn:aws:execute-api:us-east-1:{c.ACCOUNT}:{api['id']}/test/GET/"}
        else:
            event = {"type": "REQUEST", "methodArn": f"arn:aws:execute-api:us-east-1:{c.ACCOUNT}:{api['id']}/test/GET/", "headers": body.get("headers") or {},
                     "queryStringParameters": body.get("multiValueHeaders") and {} or {}, "pathParameters": body.get("pathWithQueryString") and {} or {},
                     "stageVariables": body.get("stageVariables") or {}, "requestContext": {"apiId": api["id"], "stage": "test"}}
        from core import lambda_core
        out = lambda_core.dispatch(lam, "POST", f"/2015-03-31/functions/{name}/invocations", {}, {}, json.dumps(event).encode())
        if out.headers.get("X-Amz-Function-Error") or out.status >= 300:
            return _json(c, 200, {"clientStatus": 500, "latency": 0, "log": f"Execution failed: authorizer function {name} returned an error", "principalId": None})
        try:
            res = json.loads(out.body.decode("utf-8"))
        except ValueError:
            res = {}
        stmts = (res.get("policyDocument") or {}).get("Statement") or []
        allowed = any(s.get("Effect") == "Allow" for s in stmts) and not any(s.get("Effect") == "Deny" for s in stmts)
        return _json(c, 200, {"clientStatus": 200 if allowed else 403, "latency": 1, "log": "Authorizer invoked: " + ("Allow" if allowed else "Deny"),
                              "principalId": res.get("principalId"), "policy": json.dumps(res.get("policyDocument") or {}),
                              "authorization": {k: [str(v)] for k, v in (res.get("context") or {}).items()}, "claims": {}})
    return _json(c, 200, {"clientStatus": 200, "latency": 0, "log": "Cognito user pool authorizer evaluated", "principalId": None, "claims": {}})


# ───────────────────────── models ─────────────────────────
def _models(api):
    return api.setdefault("models", {})


def create_model(c, store, api, q, body):
    for k in ("name", "contentType"):
        if not body.get(k):
            raise c.BadRequest(f"{k} is required")
    if body["name"] in _models(api):
        raise c.Conflict(f"Model name already exists for this REST API: {body['name']}")
    if body.get("schema"):
        try:
            json.loads(body["schema"])
        except ValueError:
            raise c.BadRequest("Invalid model specified: Validation Result: warnings : [], errors : [Invalid model schema; not valid JSON]")
    m = {"id": c._new_id(), "name": body["name"], "description": body.get("description", ""), "schema": body.get("schema", ""), "contentType": body["contentType"]}
    _models(api)[body["name"]] = m
    return _json(c, 201, m)


def _model(c, api, name):
    m = _models(api).get(name)
    if m is None:
        raise c.NotFound(f"Invalid model name specified: {name}")
    return m


def update_model(c, store, api, name, body):
    m = _model(c, api, name)
    _patch(c, m, body.get("patchOperations"), {"description", "schema"})
    return _json(c, 200, m)


def delete_model(c, store, api, name):
    _model(c, api, name)
    if any(name in (mm.get("requestModels") or {}).values() for r in api["resources"].values() for mm in r["methods"].values()):
        raise c.Conflict(f"Model {name} is referenced by a method")
    del _models(api)[name]
    return _empty(c, 202)


def model_template(c, store, api, name):
    m = _model(c, api, name)
    try:
        schema = json.loads(m["schema"] or "{}")
    except ValueError:
        schema = {}
    lines = ["#set($inputRoot = $input.path('$'))", "{"]
    props = list((schema.get("properties") or {}).keys())
    for i, p in enumerate(props):
        lines.append(f'  "{p}": "$!inputRoot.{p}"' + ("," if i < len(props) - 1 else ""))
    lines.append("}")
    return _json(c, 200, {"value": "\n".join(lines)})


# ───────────────────────── request validators ─────────────────────────
def _validators(api):
    return api.setdefault("validators", {})


def create_validator(c, store, api, q, body):
    v = {"id": c._new_id(), "name": body.get("name", ""), "validateRequestBody": bool(body.get("validateRequestBody", False)),
         "validateRequestParameters": bool(body.get("validateRequestParameters", False))}
    _validators(api)[v["id"]] = v
    return _json(c, 201, v)


def _validator(c, api, vid):
    v = _validators(api).get(vid)
    if v is None:
        raise c.NotFound(f"Invalid Request Validator identifier specified: {vid}")
    return v


def update_validator(c, store, api, vid, body):
    v = _validator(c, api, vid)
    _patch(c, v, body.get("patchOperations"), {"name", "validateRequestBody", "validateRequestParameters"})
    return _json(c, 200, v)


def delete_validator(c, store, api, vid):
    _validator(c, api, vid)
    for r in api["resources"].values():
        for m in r["methods"].values():
            if m.get("requestValidatorId") == vid:
                m["requestValidatorId"] = None
    del _validators(api)[vid]
    return _empty(c, 202)


# ───────────────────────── gateway responses ─────────────────────────
_GW_DEFAULTS = {"DEFAULT_4XX": None, "DEFAULT_5XX": None, "UNAUTHORIZED": "401", "ACCESS_DENIED": "403", "MISSING_AUTHENTICATION_TOKEN": "403", "RESOURCE_NOT_FOUND": "404",
                "THROTTLED": "429", "EXPIRED_TOKEN": "403", "INVALID_API_KEY": "403", "INVALID_SIGNATURE": "403", "AUTHORIZER_FAILURE": "500", "AUTHORIZER_CONFIGURATION_ERROR": "500",
                "BAD_REQUEST_PARAMETERS": "400", "BAD_REQUEST_BODY": "400", "REQUEST_TOO_LARGE": "413", "QUOTA_EXCEEDED": "429", "INTEGRATION_FAILURE": "504",
                "INTEGRATION_TIMEOUT": "504", "API_CONFIGURATION_ERROR": "500", "UNSUPPORTED_MEDIA_TYPE": "415", "WAF_FILTERED": "403"}


def _gwr(api):
    return api.setdefault("gateway_responses", {})


def _gw_type(c, t):
    if t not in _GW_DEFAULTS:
        raise c.BadRequest(f"Invalid gateway response type: {t}. Valid types: {sorted(_GW_DEFAULTS)}")
    return t


def _gw_view(t, g):
    v = {"responseType": t, "defaultResponse": g is None, "responseParameters": {}, "responseTemplates": {"application/json": '{"message":$context.error.messageString}'}}
    if _GW_DEFAULTS[t]:
        v["statusCode"] = _GW_DEFAULTS[t]
    if g:
        v.update(g)
        v["defaultResponse"] = False
    return v


def put_gateway_response(c, store, api, t, body):
    _gw_type(c, t)
    g = {k: body[k] for k in ("statusCode", "responseParameters", "responseTemplates") if k in body}
    _gwr(api)[t] = g
    return _json(c, 201, _gw_view(t, g))


def get_gateway_response(c, store, api, t):
    _gw_type(c, t)
    return _json(c, 200, _gw_view(t, _gwr(api).get(t)))


def get_gateway_responses(c, store, api, q):
    return _json(c, 200, _page([_gw_view(t, _gwr(api).get(t)) for t in sorted(_GW_DEFAULTS)], q))


def update_gateway_response(c, store, api, t, body):
    _gw_type(c, t)
    g = _gwr(api).setdefault(t, {})
    _patch(c, g, body.get("patchOperations"), {"statusCode", "responseParameters", "responseTemplates"})
    return _json(c, 200, _gw_view(t, g))


def delete_gateway_response(c, store, api, t):
    _gw_type(c, t)
    _gwr(api).pop(t, None)
    return _empty(c, 202)


# ───────────────────────── method + integration responses ─────────────────────────
def _status(c, code):
    if not re.fullmatch(r"[1-5]\d\d|default", str(code)):
        raise c.BadRequest(f"Invalid status code specified: {code}")
    return str(code)


def put_method_response(c, store, api, rid, hm, code, body):
    _res, m = c._require_method(api, rid, hm)
    code = _status(c, code)
    if code in m.setdefault("methodResponses", {}):
        raise c.Conflict("Response already exists for this resource")
    r = {"statusCode": code, "responseParameters": dict(body.get("responseParameters") or {}), "responseModels": dict(body.get("responseModels") or {})}
    m["methodResponses"][code] = r
    return _json(c, 201, r)


def _mresp(c, api, rid, hm, code):
    _res, m = c._require_method(api, rid, hm)
    r = (m.get("methodResponses") or {}).get(str(code))
    if r is None:
        raise c.NotFound(f"Invalid Response status code specified: {code}")
    return m, r


def get_method_response(c, store, api, rid, hm, code):
    return _json(c, 200, _mresp(c, api, rid, hm, code)[1])


def update_method_response(c, store, api, rid, hm, code, body):
    _, r = _mresp(c, api, rid, hm, code)
    _patch(c, r, body.get("patchOperations"), {"responseParameters", "responseModels"})
    return _json(c, 200, r)


def delete_method_response(c, store, api, rid, hm, code):
    m, r = _mresp(c, api, rid, hm, code)
    del m["methodResponses"][str(code)]
    if m.get("integration"):
        (m["integration"].get("integrationResponses") or {}).pop(str(code), None)
    return _empty(c, 204)


def _need_integ(c, m):
    if not m.get("integration"):
        raise c.NotFound("Invalid Integration identifier specified")
    return m["integration"]


def put_integration_response(c, store, api, rid, hm, code, body):
    _res, m = c._require_method(api, rid, hm)
    integ = _need_integ(c, m)
    code = _status(c, code)
    if code != "default" and code not in (m.get("methodResponses") or {}):
        raise c.BadRequest(f"Invalid Response status code specified: {code}. Create the method response first.")
    r = {"statusCode": code, "selectionPattern": body.get("selectionPattern"), "responseParameters": dict(body.get("responseParameters") or {}),
         "responseTemplates": dict(body.get("responseTemplates") or {}), "contentHandling": body.get("contentHandling")}
    integ.setdefault("integrationResponses", {})[code] = {k: v for k, v in r.items() if v not in (None, {})} | {"statusCode": code}
    return _json(c, 201, integ["integrationResponses"][code])


def _iresp(c, api, rid, hm, code):
    _res, m = c._require_method(api, rid, hm)
    integ = _need_integ(c, m)
    r = (integ.get("integrationResponses") or {}).get(str(code))
    if r is None:
        raise c.NotFound(f"Invalid Response status code specified: {code}")
    return integ, r


def get_integration_response(c, store, api, rid, hm, code):
    return _json(c, 200, _iresp(c, api, rid, hm, code)[1])


def update_integration_response(c, store, api, rid, hm, code, body):
    _, r = _iresp(c, api, rid, hm, code)
    _patch(c, r, body.get("patchOperations"), {"selectionPattern", "responseParameters", "responseTemplates", "contentHandling"})
    return _json(c, 200, r)


def delete_integration_response(c, store, api, rid, hm, code):
    integ, _ = _iresp(c, api, rid, hm, code)
    del integ["integrationResponses"][str(code)]
    return _empty(c, 204)


# ───────────────────────── update method / integration / resource / deployment ─────────────────────────
def update_method(c, store, api, rid, hm, body):
    _res, m = c._require_method(api, rid, hm)
    _patch(c, m, body.get("patchOperations"), {"authorizationType", "authorizerId", "apiKeyRequired", "operationName", "requestParameters", "requestModels",
                                               "requestValidatorId", "authorizationScopes"})
    if m.get("authorizerId") and m["authorizerId"] not in _authorizers(api):
        raise c.BadRequest(f"Invalid authorizer ID specified. Setting the authorization type to CUSTOM or COGNITO_USER_POOLS requires a valid authorizer: {m['authorizerId']}")
    if m.get("requestValidatorId") and m["requestValidatorId"] not in _validators(api):
        raise c.BadRequest(f"Invalid Request Validator identifier specified: {m['requestValidatorId']}")
    return _json(c, 200, c._method_view(m))


def update_integration(c, store, api, rid, hm, body):
    _res, m = c._require_method(api, rid, hm)
    integ = _need_integ(c, m)
    _patch(c, integ, body.get("patchOperations"), {"type", "uri", "httpMethod", "credentials", "timeoutInMillis", "passthroughBehavior", "cacheNamespace", "cacheKeyParameters",
                                                   "requestTemplates", "requestParameters", "contentHandling", "connectionType", "connectionId"})
    if isinstance(integ.get("timeoutInMillis"), str):
        integ["timeoutInMillis"] = int(integ["timeoutInMillis"])
    return _json(c, 200, c._integration_view(integ))


def update_resource(c, store, api, rid, body):
    res = c._require_resource(api, rid)
    if res["parentId"] is None:
        raise c.BadRequest("The root resource cannot be modified")
    for op in body.get("patchOperations") or []:
        path = str(op.get("path", "")).lstrip("/")
        if path == "pathPart":
            part = str(op.get("value", ""))
            if any(r["parentId"] == res["parentId"] and r["pathPart"] == part and r["id"] != rid for r in api["resources"].values()):
                raise c.Conflict(f"Another resource with the same parent already has this name: {part}")
            res["pathPart"] = part
        elif path == "parentId":
            new = api["resources"].get(str(op.get("value")))
            if new is None:
                raise c.NotFound(f"Invalid resource identifier specified: {op.get('value')}")
            res["parentId"] = new["id"]
        else:
            raise c.BadRequest(f"Invalid patch path '/{path}'")
    _repath(api, res)
    return _json(c, 200, c._resource_view(res))


def _repath(api, res):
    parent = api["resources"][res["parentId"]]
    res["path"] = parent["path"].rstrip("/") + "/" + res["pathPart"]
    for ch in [r for r in api["resources"].values() if r["parentId"] == res["id"]]:
        _repath(api, ch)


def update_deployment(c, store, api, did, body):
    d = api["deployments"].get(did)
    if d is None:
        raise c.NotFound(f"Invalid Deployment identifier specified: {did}")
    _patch(c, d, body.get("patchOperations"), {"description"})
    return _json(c, 200, {"id": d["id"], "description": d["description"], "createdDate": d["createdDate"]})


def delete_deployment(c, store, api, did):
    if did not in api["deployments"]:
        raise c.NotFound(f"Invalid Deployment identifier specified: {did}")
    if any(s.get("deploymentId") == did for s in api["stages"].values()):
        raise c.BadRequest("Active stages pointing to this deployment must be moved or deleted")
    del api["deployments"][did]
    return _empty(c, 202)


def flush_stage_cache(c, store, api, stage, what):
    st = c._require_stage(api, stage)
    if what == "data" and not st.get("cacheClusterEnabled"):
        raise c.BadRequest("Cache cluster is not enabled for this stage")
    return _empty(c, 202)


# ───────────────────────── domain names / base path mappings / vpc links ─────────────────────────
def _domains(store):
    return _tbl(store, "_apigateway_domains")


def create_domain(c, store, q, body):
    name = (body.get("domainName") or "").lower()
    if not re.fullmatch(r"(\*\.)?([a-z0-9-]+\.)+[a-z]{2,}", name):
        raise c.BadRequest(f"Invalid domain name identifier specified: {body.get('domainName')}")
    if name in _domains(store):
        raise c.Conflict(f"Domain name {name} already exists")
    regional = "REGIONAL" in ((body.get("endpointConfiguration") or {}).get("types") or ["EDGE"])
    d = {"domainName": name, "certificateName": body.get("certificateName"), "certificateArn": body.get("certificateArn"), "regionalCertificateArn": body.get("regionalCertificateArn"),
         "regionalCertificateName": body.get("regionalCertificateName"), "domainNameStatus": "AVAILABLE", "securityPolicy": body.get("securityPolicy", "TLS_1_2"),
         "endpointConfiguration": body.get("endpointConfiguration") or {"types": ["EDGE"]}, "tags": dict(body.get("tags") or {}), "mutualTlsAuthentication": body.get("mutualTlsAuthentication"),
         "_maps": {}}
    h = uuid.uuid5(uuid.NAMESPACE_DNS, name).hex[:12]
    if regional:
        d["regionalDomainName"] = f"d-{h}.execute-api.us-east-1.amazonaws.com"
        d["regionalHostedZoneId"] = "Z1UJRXOUMOOFQ8"
    else:
        d["distributionDomainName"] = f"{h}.cloudfront.net"
        d["distributionHostedZoneId"] = "Z2FDTNDATAQYW2"
    _domains(store)[name] = d
    return _json(c, 201, _dview(d))


def _dview(d):
    return {k: v for k, v in d.items() if not k.startswith("_") and v is not None}


def _domain(c, store, name):
    d = _domains(store).get(name.lower())
    if d is None:
        raise c.NotFound(f"Invalid domain name identifier specified: {name}")
    return d


def get_domains(c, store, q):
    return _json(c, 200, _page([_dview(d) for d in _domains(store).values()], q))


def get_domain(c, store, name):
    return _json(c, 200, _dview(_domain(c, store, name)))


def update_domain(c, store, name, body):
    d = _domain(c, store, name)
    _patch(c, d, body.get("patchOperations"), {"certificateName", "certificateArn", "regionalCertificateArn", "regionalCertificateName", "securityPolicy"})
    return _json(c, 200, _dview(d))


def delete_domain(c, store, name):
    d = _domain(c, store, name)
    del _domains(store)[d["domainName"]]
    return _empty(c, 202)


def _map_view(d, m):
    return {k: v for k, v in {"basePath": m["basePath"] or "(none)", "restApiId": m["restApiId"], "stage": m.get("stage")}.items() if v is not None}


def create_mapping(c, store, name, body):
    d = _domain(c, store, name)
    api = c._require_api(store, body.get("restApiId"))
    bp = body.get("basePath") or ""
    bp = "" if bp == "(none)" else bp
    if bp in d["_maps"]:
        raise c.Conflict(f"Base path {bp or '(none)'} is already mapped")
    if body.get("stage") and body["stage"] not in api["stages"]:
        raise c.BadRequest(f"Invalid stage identifier specified: {body['stage']}")
    d["_maps"][bp] = {"basePath": bp, "restApiId": api["id"], "stage": body.get("stage")}
    return _json(c, 201, _map_view(d, d["_maps"][bp]))


def _mapping(c, store, name, bp):
    d = _domain(c, store, name)
    bp = "" if bp == "(none)" else urllib.parse.unquote(bp)
    m = d["_maps"].get(bp)
    if m is None:
        raise c.NotFound(f"Invalid base path mapping identifier specified: {bp or '(none)'}")
    return d, m


def get_mappings(c, store, name, q):
    d = _domain(c, store, name)
    return _json(c, 200, _page([_map_view(d, m) for m in d["_maps"].values()], q))


def get_mapping(c, store, name, bp):
    d, m = _mapping(c, store, name, bp)
    return _json(c, 200, _map_view(d, m))


def update_mapping(c, store, name, bp, body):
    d, m = _mapping(c, store, name, bp)
    for op in body.get("patchOperations") or []:
        path = str(op.get("path", "")).lstrip("/")
        if path == "basePath":
            new = "" if op.get("value") == "(none)" else str(op.get("value"))
            if new != m["basePath"] and new in d["_maps"]:
                raise c.Conflict(f"Base path {new or '(none)'} is already mapped")
            d["_maps"].pop(m["basePath"])
            m["basePath"] = new
            d["_maps"][new] = m
        elif path == "restapiId":
            c._require_api(store, op.get("value"))
            m["restApiId"] = op["value"]
        elif path == "stage":
            m["stage"] = op.get("value")
        else:
            raise c.BadRequest(f"Invalid patch path '/{path}'")
    return _json(c, 200, _map_view(d, m))


def delete_mapping(c, store, name, bp):
    d, m = _mapping(c, store, name, bp)
    del d["_maps"][m["basePath"]]
    return _empty(c, 202)


def _vpclinks(store):
    return _tbl(store, "_apigateway_vpclinks")


def create_vpclink(c, store, q, body):
    if not body.get("name") or not body.get("targetArns"):
        raise c.BadRequest("name and targetArns are required")
    for a in body["targetArns"]:
        if not re.match(r"^arn:aws:elasticloadbalancing:[^:]+:\d{12}:loadbalancer/net/", a):
            raise c.BadRequest(f"Invalid targetArn '{a}': must be a Network Load Balancer ARN")
    vid = uuid.uuid4().hex[:6]
    _vpclinks(store)[vid] = {"id": vid, "name": body["name"], "description": body.get("description", ""), "targetArns": list(body["targetArns"]), "status": "AVAILABLE",
                             "statusMessage": "", "tags": dict(body.get("tags") or {})}
    return _json(c, 202, _vpclinks(store)[vid])


def _vpclink(c, store, vid):
    v = _vpclinks(store).get(vid)
    if v is None:
        raise c.NotFound(f"Invalid VpcLink identifier specified: {vid}")
    return v


def get_vpclinks(c, store, q):
    return _json(c, 200, _page(list(_vpclinks(store).values()), q))


def get_vpclink(c, store, vid):
    return _json(c, 200, _vpclink(c, store, vid))


def update_vpclink(c, store, vid, body):
    v = _vpclink(c, store, vid)
    _patch(c, v, body.get("patchOperations"), {"name", "description"})
    return _json(c, 200, v)


def delete_vpclink(c, store, vid):
    _vpclink(c, store, vid)
    del _vpclinks(store)[vid]
    return _empty(c, 202)


# ───────────────────────── tags ─────────────────────────
def _tag_target(c, store, arn):
    m = re.match(r"^arn:aws:apigateway:[^:]*::/(restapis|domainnames|vpclinks|apikeys|usageplans|clientcertificates)/(.+?)(?:/stages/(.+))?$", urllib.parse.unquote(arn))
    if not m:
        raise c.BadRequest(f"Invalid ARN specified in the request: {arn}")
    kind, ident, stage = m.groups()
    if kind == "restapis":
        api = c._require_api(store, ident)
        return c._require_stage(api, stage) if stage else api
    if kind == "domainnames":
        return _domain(c, store, ident)
    if kind == "vpclinks":
        return _vpclink(c, store, ident)
    tbl = {"apikeys": c._api_keys, "usageplans": c._usage_plans, "clientcertificates": c._client_certs}[kind](store)
    if ident not in tbl:
        raise c.NotFound(f"Invalid {kind[:-1]} identifier specified: {ident}")
    return tbl[ident]


def tag_resource(c, store, arn, body):
    t = _tag_target(c, store, arn)
    if not body.get("tags"):
        raise c.BadRequest("tags is required")
    t.setdefault("tags", {}).update({k: str(v) for k, v in body["tags"].items()})
    return _empty(c, 204)


def untag_resource(c, store, arn, q):
    t = _tag_target(c, store, arn)
    keys = q.get("tagKeys") or []
    for k in (keys if isinstance(keys, list) else [keys]):
        t.setdefault("tags", {}).pop(k, None)
    return _empty(c, 204)


def get_tags(c, store, arn):
    return _json(c, 200, {"tags": dict(_tag_target(c, store, arn).get("tags") or {})})


# ───────────────────────── documentation ─────────────────────────
def _docs(api):
    return api.setdefault("doc_parts", {})


def _docver(api):
    return api.setdefault("doc_versions", {})


def create_doc_part(c, store, api, q, body):
    loc = body.get("location") or {}
    if loc.get("type") not in ("API", "AUTHORIZER", "MODEL", "RESOURCE", "METHOD", "PATH_PARAMETER", "QUERY_PARAMETER", "REQUEST_HEADER", "REQUEST_BODY", "RESPONSE", "RESPONSE_HEADER", "RESPONSE_BODY"):
        raise c.BadRequest("Invalid location type")
    try:
        json.loads(body.get("properties") or "")
    except ValueError:
        raise c.BadRequest("properties must be a valid JSON string")
    if any(p["location"] == loc for p in _docs(api).values()):
        raise c.Conflict("Documentation part already exists for this location")
    pid = c._new_id()
    _docs(api)[pid] = {"id": pid, "location": loc, "properties": body["properties"]}
    return _json(c, 201, _docs(api)[pid])


def _doc(c, api, pid):
    d = _docs(api).get(pid)
    if d is None:
        raise c.NotFound(f"Invalid Documentation part identifier specified: {pid}")
    return d


def get_doc_parts(c, store, api, q):
    items = list(_docs(api).values())
    if q.get("type"):
        items = [p for p in items if p["location"].get("type") == _first(q["type"])]
    if q.get("path"):
        items = [p for p in items if p["location"].get("path") == _first(q["path"])]
    return _json(c, 200, _page(items, q))


def update_doc_part(c, store, api, pid, body):
    d = _doc(c, api, pid)
    _patch(c, d, body.get("patchOperations"), {"properties"})
    return _json(c, 200, d)


def delete_doc_part(c, store, api, pid):
    _doc(c, api, pid)
    del _docs(api)[pid]
    return _empty(c, 202)


def import_doc_parts(c, store, api, q, body):
    ids, warnings = [], []
    mode = _first(q.get("mode")) or "merge"
    doc = body if isinstance(body, dict) else {}
    parts = doc.get("documentation", {}).get("parts") if isinstance(doc.get("documentation"), dict) else doc.get("parts") or []
    if mode == "overwrite":
        _docs(api).clear()
    for p in parts or []:
        loc = p.get("location") or {}
        cur = next((x for x in _docs(api).values() if x["location"] == loc), None)
        props = json.dumps(p.get("properties")) if not isinstance(p.get("properties"), str) else p["properties"]
        if cur:
            cur["properties"] = props
            ids.append(cur["id"])
        else:
            pid = c._new_id()
            _docs(api)[pid] = {"id": pid, "location": loc, "properties": props}
            ids.append(pid)
    return _json(c, 201, {"ids": ids, "warnings": warnings})


def create_doc_version(c, store, api, q, body):
    v = body.get("documentationVersion")
    if not v:
        raise c.BadRequest("documentationVersion is required")
    if v in _docver(api):
        raise c.Conflict(f"Documentation version {v} already exists")
    if body.get("stageName"):
        c._require_stage(api, body["stageName"])
    _docver(api)[v] = {"version": v, "createdDate": c._now(), "description": body.get("description", ""), "_snapshot": json.loads(json.dumps(_docs(api)))}
    return _json(c, 201, {k: x for k, x in _docver(api)[v].items() if not k.startswith("_")})


def _dv(c, api, v):
    d = _docver(api).get(v)
    if d is None:
        raise c.NotFound(f"Invalid Documentation version specified: {v}")
    return d


def get_doc_versions(c, store, api, q):
    return _json(c, 200, _page([{k: x for k, x in d.items() if not k.startswith("_")} for d in _docver(api).values()], q))


def get_doc_version(c, store, api, v):
    return _json(c, 200, {k: x for k, x in _dv(c, api, v).items() if not k.startswith("_")})


def update_doc_version(c, store, api, v, body):
    d = _dv(c, api, v)
    _patch(c, d, body.get("patchOperations"), {"description"})
    return _json(c, 200, {k: x for k, x in d.items() if not k.startswith("_")})


def delete_doc_version(c, store, api, v):
    _dv(c, api, v)
    del _docver(api)[v]
    return _empty(c, 202)


# ───────────────────────── usage ─────────────────────────
def get_usage_plan_key(c, store, pid, kid):
    plan = c._usage_plans(store).get(pid)
    if plan is None:
        raise c.NotFound(f"Invalid Usage Plan ID specified: {pid}")
    keys = plan.get("keys") or plan.get("_keys") or {}
    k = keys.get(kid) if isinstance(keys, dict) else None
    if k is None and isinstance(keys, list):
        k = next((x for x in keys if x.get("id") == kid or x == kid), None)
    if k is None:
        raise c.NotFound(f"Invalid API Key identifier specified: {kid}")
    kk = c._api_keys(store).get(kid) or {}
    return _json(c, 200, {"id": kid, "type": "API_KEY", "name": kk.get("name", ""), "value": kk.get("value", "")})


def get_usage(c, store, pid, q):
    plan = c._usage_plans(store).get(pid)
    if plan is None:
        raise c.NotFound(f"Invalid Usage Plan ID specified: {pid}")
    for k in ("startDate", "endDate"):
        if not _first(q.get(k)) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(_first(q[k]))):
            raise c.BadRequest(f"{k} is required (YYYY-MM-DD)")
    keys = plan.get("keys") or plan.get("_keys") or {}
    ids = list(keys) if isinstance(keys, dict) else [x["id"] if isinstance(x, dict) else x for x in keys]
    used = _tbl(store, "_apigateway_usage")
    return _json(c, 200, {"usagePlanId": pid, "startDate": _first(q["startDate"]), "endDate": _first(q["endDate"]),
                          "items": {k: [[u, r] for u, r in used.get(f"{pid}|{k}", [])] for k in ids if not q.get("keyId") or k == _first(q["keyId"])}})


def update_usage(c, store, pid, kid, body):
    plan = c._usage_plans(store).get(pid)
    if plan is None:
        raise c.NotFound(f"Invalid Usage Plan ID specified: {pid}")
    rows = _tbl(store, "_apigateway_usage").setdefault(f"{pid}|{kid}", [[0, 0]])
    for op in body.get("patchOperations") or []:
        if not re.fullmatch(r"/\d{4}-\d{2}-\d{2}", str(op.get("path", ""))):
            raise c.BadRequest("Invalid patch path; use /<YYYY-MM-DD>")
        rows[0][1] = int(op.get("value", 0))
    return _json(c, 200, {"usagePlanId": pid, "startDate": "", "endDate": "", "items": {kid: rows}})


_SDK_TYPES = ("javascript", "android", "java", "objectivec", "swift", "ruby")


def get_sdk_types(c, store, q):
    return _json(c, 200, _page([{"id": t, "friendlyName": t.capitalize(), "description": f"{t} SDK generator", "configurationProperties": []} for t in _SDK_TYPES], q))


def get_sdk_type(c, store, t):
    if t not in _SDK_TYPES:
        raise c.NotFound(f"Invalid SDK type specified: {t}")
    return _json(c, 200, {"id": t, "friendlyName": t.capitalize(), "description": f"{t} SDK generator", "configurationProperties": []})


# ───────────────────────── export / import ─────────────────────────
def _oa_integration(integ):
    out = {"type": integ["type"].lower(), "passthroughBehavior": integ.get("passthroughBehavior", "WHEN_NO_MATCH").lower()}
    if integ.get("uri"):
        out["uri"] = integ["uri"]
    if integ["type"] not in ("MOCK",):
        out["httpMethod"] = integ.get("httpMethod", "POST")
    if integ.get("requestTemplates"):
        out["requestTemplates"] = integ["requestTemplates"]
    if integ.get("credentials"):
        out["credentials"] = integ["credentials"]
    if integ.get("integrationResponses"):
        out["responses"] = {("default" if k == "default" else (v.get("selectionPattern") or k)): {k2: v2 for k2, v2 in {"statusCode": v["statusCode"], "responseParameters": v.get("responseParameters"),
                                                                                                                         "responseTemplates": v.get("responseTemplates")}.items() if v2}
                            for k, v in integ["integrationResponses"].items()}
    return out


def export_api(c, store, api, stage, kind, q):
    oas3 = kind == "oas30"
    if kind not in ("oas30", "swagger"):
        raise c.BadRequest(f"Invalid export type {kind}; use swagger or oas30")
    c._require_stage(api, stage)
    paths = {}
    for r in sorted(api["resources"].values(), key=lambda x: x["path"]):
        if not r["methods"]:
            continue
        item = {}
        for hm, m in sorted(r["methods"].items()):
            op = {"responses": {}}
            if m.get("operationName"):
                op["operationId"] = m["operationName"]
            params = []
            for pk, req in (m.get("requestParameters") or {}).items():
                mm = re.match(r"method\.request\.(querystring|header|path)\.(.+)", pk)
                if mm:
                    params.append({"name": mm.group(2), "in": {"querystring": "query"}.get(mm.group(1), mm.group(1)), "required": bool(req) or mm.group(1) == "path", **({"schema": {"type": "string"}} if oas3 else {"type": "string"})})
            if params:
                op["parameters"] = params
            for code, mr in (m.get("methodResponses") or {}).items():
                resp = {"description": f"{code} response"}
                if mr.get("responseModels"):
                    key = "content" if oas3 else "schema"
                    mod = next(iter(mr["responseModels"].values()))
                    resp["content" if oas3 else "schema"] = ({ct: {"schema": {"$ref": f"#/components/schemas/{mn}"}} for ct, mn in mr["responseModels"].items()} if oas3 else {"$ref": f"#/definitions/{mod}"})
                op["responses"][code] = resp
            if not op["responses"]:
                op["responses"] = {"200": {"description": "200 response"}}
            if m.get("authorizerId") and m["authorizerId"] in _authorizers(api):
                op["security"] = [{_authorizers(api)[m["authorizerId"]]["name"]: []}]
            if m.get("apiKeyRequired"):
                op.setdefault("security", []).append({"api_key": []})
            if m.get("integration"):
                op["x-amazon-apigateway-integration"] = _oa_integration(m["integration"])
            item[hm.lower() if hm != "ANY" else "x-amazon-apigateway-any-method"] = op
        paths[r["path"]] = item
    doc = {("openapi" if oas3 else "swagger"): "3.0.1" if oas3 else "2.0",
           "info": {"title": api["name"], "version": api.get("version") or "1", "description": api.get("description", "")} if api.get("description") else {"title": api["name"], "version": api.get("version") or "1"},
           "paths": paths}
    if oas3:
        doc["servers"] = [{"url": f"https://{api['id']}.execute-api.us-east-1.amazonaws.com/{{basePath}}", "variables": {"basePath": {"default": stage}}}]
    else:
        doc["host"] = f"{api['id']}.execute-api.us-east-1.amazonaws.com"
        doc["basePath"] = "/" + stage
        doc["schemes"] = ["https"]
    models = {n: (json.loads(m["schema"]) if m["schema"] else {"type": "object"}) for n, m in _models(api).items()}
    sec = {}
    for a in _authorizers(api).values():
        sec[a["name"]] = {"type": "apiKey", "name": "Authorization", "in": "header", "x-amazon-apigateway-authtype": "custom" if a["type"] != "COGNITO_USER_POOLS" else "cognito_user_pools",
                          **({"x-amazon-apigateway-authorizer": {"type": a["type"].lower(), "authorizerUri": a.get("authorizerUri", "")}} if a["type"] != "COGNITO_USER_POOLS" else {})}
    if any(m.get("apiKeyRequired") for r in api["resources"].values() for m in r["methods"].values()):
        sec["api_key"] = {"type": "apiKey", "name": "x-api-key", "in": "header"}
    if oas3:
        if models or sec:
            doc["components"] = {k: v for k, v in (("schemas", models), ("securitySchemes", sec)) if v}
    else:
        if models:
            doc["definitions"] = models
        if sec:
            doc["securityDefinitions"] = sec
    body = json.dumps(doc, indent=2 if _first(q.get("parameters", {}).get("extensions") if isinstance(q.get("parameters"), dict) else None) else None, sort_keys=True).encode()
    return c.ApiGwResponse(status=200, body=body, headers={"content-type": "application/json", "content-disposition": f'attachment; filename="{api["name"]}-{stage}-{kind}.json"'})


def _resolve_ref(doc, node):
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 10:
        cur = doc
        for part in node["$ref"].lstrip("#/").split("/"):
            cur = cur.get(part.replace("~1", "/"), {}) if isinstance(cur, dict) else {}
        node, seen = cur, seen + 1
    return node


def _import_into(c, api, doc, overwrite, fail_on_warnings):
    warnings = []
    if not isinstance(doc, dict) or not (doc.get("openapi") or doc.get("swagger")) or not isinstance(doc.get("paths"), dict):
        raise c.BadRequest("Failed to parse the uploaded OpenAPI document: expected a JSON OpenAPI 3 / Swagger 2 document with a 'paths' object")
    root = next(r["id"] for r in api["resources"].values() if r["parentId"] is None)
    if overwrite:
        for rid in [r for r in api["resources"] if r != root]:
            del api["resources"][rid]
        api["resources"][root]["methods"] = {}
        _models(api).clear()
        _authorizers(api).clear()
        _validators(api).clear()
    schemas = (doc.get("components") or {}).get("schemas") or doc.get("definitions") or {}
    for n, sch in schemas.items():
        _models(api)[n] = {"id": c._new_id(), "name": n, "description": "", "schema": json.dumps(sch), "contentType": "application/json"}
    secdefs = (doc.get("components") or {}).get("securitySchemes") or doc.get("securityDefinitions") or {}
    by_name = {}
    for n, s in secdefs.items():
        az = s.get("x-amazon-apigateway-authorizer")
        if az:
            aid = c._new_id()
            ty = (az.get("type") or "token").upper()
            _authorizers(api)[aid] = {"id": aid, "name": n, "type": ty if ty in _AUTH_TYPES else "TOKEN", "authorizerUri": az.get("authorizerUri", ""),
                                      "identitySource": f"method.request.header.{s.get('name', 'Authorization')}", "authorizerResultTtlInSeconds": int(az.get("authorizerResultTtlInSeconds", 300))}
            by_name[n] = aid
    validators = doc.get("x-amazon-apigateway-request-validators") or {}
    vid_by_name = {}
    for n, v in validators.items():
        vid = c._new_id()
        _validators(api)[vid] = {"id": vid, "name": n, "validateRequestBody": bool(v.get("validateRequestBody")), "validateRequestParameters": bool(v.get("validateRequestParameters"))}
        vid_by_name[n] = vid

    def ensure(path):
        cur = root
        built = ""
        for part in [p for p in path.split("/") if p]:
            built += "/" + part
            nxt = next((r for r in api["resources"].values() if r["parentId"] == cur and r["pathPart"] == part), None)
            if nxt is None:
                rid = c._new_id()
                api["resources"][rid] = {"id": rid, "parentId": cur, "pathPart": part, "path": built, "methods": {}}
                nxt = api["resources"][rid]
            cur = nxt["id"]
        return api["resources"][cur]
    for path, item in doc["paths"].items():
        res = ensure(path)
        for verb, op in item.items():
            hm = "ANY" if verb == "x-amazon-apigateway-any-method" else verb.upper()
            if hm not in ("GET", "PUT", "POST", "DELETE", "PATCH", "HEAD", "OPTIONS", "ANY"):
                continue
            m = {"httpMethod": hm, "authorizationType": "NONE", "apiKeyRequired": False, "requestParameters": {}, "requestModels": {}, "authorizerId": None,
                 "requestValidatorId": None, "operationName": op.get("operationId"), "authorizationScopes": [], "methodResponses": {}, "integration": None}
            for prm in op.get("parameters") or []:
                prm = _resolve_ref(doc, prm)
                loc = {"query": "querystring"}.get(prm.get("in"), prm.get("in"))
                if loc in ("querystring", "header", "path"):
                    m["requestParameters"][f"method.request.{loc}.{prm['name']}"] = bool(prm.get("required"))
            for sec in op.get("security") or []:
                for sn in sec:
                    if sn in by_name:
                        m["authorizerId"], m["authorizationType"] = by_name[sn], "CUSTOM" if _authorizers(api)[by_name[sn]]["type"] != "COGNITO_USER_POOLS" else "COGNITO_USER_POOLS"
                    elif sn == "api_key":
                        m["apiKeyRequired"] = True
            rv = op.get("x-amazon-apigateway-request-validator") or doc.get("x-amazon-apigateway-request-validator")
            if rv in vid_by_name:
                m["requestValidatorId"] = vid_by_name[rv]
            body = _resolve_ref(doc, op.get("requestBody") or {})
            for ct, spec in (body.get("content") or {}).items():
                ref = (spec.get("schema") or {}).get("$ref", "")
                if ref.split("/")[-1] in _models(api):
                    m["requestModels"][ct] = ref.split("/")[-1]
            for code, resp in (op.get("responses") or {}).items():
                resp = _resolve_ref(doc, resp)
                mr = {"statusCode": str(code), "responseParameters": {f"method.response.header.{h}": False for h in (resp.get("headers") or {})}, "responseModels": {}}
                for ct, spec in (resp.get("content") or {}).items():
                    ref = (spec.get("schema") or {}).get("$ref", "")
                    if ref.split("/")[-1] in _models(api):
                        mr["responseModels"][ct] = ref.split("/")[-1]
                m["methodResponses"][str(code)] = mr
            ig = op.get("x-amazon-apigateway-integration")
            if ig:
                it = str(ig.get("type", "mock")).upper()
                if it not in ("MOCK", "AWS", "AWS_PROXY", "HTTP", "HTTP_PROXY"):
                    raise c.BadRequest(f"Unsupported integration type '{ig.get('type')}' at {verb.upper()} {path}")
                integ = {"type": it, "uri": ig.get("uri", ""), "httpMethod": ig.get("httpMethod", "POST"), "timeoutInMillis": int(ig.get("timeoutInMillis", 29000)),
                         "passthroughBehavior": str(ig.get("passthroughBehavior", "when_no_match")).upper(), "requestTemplates": dict(ig.get("requestTemplates") or {}),
                         "mockStatus": 200, "mockBody": "", "credentials": ig.get("credentials"), "cacheNamespace": None, "cacheKeyParameters": [],
                         "contentHandling": ig.get("contentHandling"), "requestParameters": dict(ig.get("requestParameters") or {}), "connectionType": ig.get("connectionType"),
                         "connectionId": ig.get("connectionId"), "integrationResponses": {}}
                for sel, r in (ig.get("responses") or {}).items():
                    code = str(r.get("statusCode", "200"))
                    key = "default" if sel == "default" else code
                    integ["integrationResponses"][key] = {k: v for k, v in {"statusCode": code, "selectionPattern": None if sel == "default" else sel, "responseParameters": r.get("responseParameters"),
                                                                            "responseTemplates": r.get("responseTemplates")}.items() if v}
                    if it == "MOCK":
                        integ["mockStatus"] = int(code) if key == "default" or True else 200
                if it == "MOCK" and (ig.get("requestTemplates") or {}).get("application/json"):
                    mm = re.search(r'"statusCode"\s*:\s*(\d+)', ig["requestTemplates"]["application/json"])
                    integ["mockStatus"] = int(mm.group(1)) if mm else integ["mockStatus"]
                m["integration"] = integ
            elif fail_on_warnings:
                raise c.BadRequest(f"No integration defined for method {hm} {path}")
            else:
                warnings.append(f"No integration defined for method {hm} {path}")
            res["methods"][hm] = m
    return warnings


def import_api(c, store, q, raw):
    try:
        doc = json.loads(raw.decode("utf-8"))
    except Exception:
        raise c.BadRequest("Failed to parse the uploaded OpenAPI document: only JSON documents are supported")
    r = c._create_rest_api(store, {"name": (doc.get("info") or {}).get("title") or "imported-api", "description": (doc.get("info") or {}).get("description", ""),
                                   "version": (doc.get("info") or {}).get("version"), "endpointConfiguration": {"types": ["EDGE"]}})
    api_id = json.loads(r.body)["id"]
    api = c._require_api(store, api_id)
    try:
        warnings = _import_into(c, api, doc, True, _first(q.get("failonwarnings")) == "true")
    except Exception:
        c._apis(store).pop(api_id, None)
        raise
    view = c._api_view(api)
    view["rootResourceId"] = next(r_["id"] for r_ in api["resources"].values() if r_["parentId"] is None)
    if warnings:
        view["warnings"] = warnings
    return _json(c, 201, view)


def put_rest_api(c, store, api, q, raw):
    try:
        doc = json.loads(raw.decode("utf-8"))
    except Exception:
        raise c.BadRequest("Failed to parse the uploaded OpenAPI document: only JSON documents are supported")
    mode = _first(q.get("mode")) or "merge"
    if mode not in ("merge", "overwrite"):
        raise c.BadRequest("mode must be merge or overwrite")
    warnings = _import_into(c, api, doc, mode == "overwrite", _first(q.get("failonwarnings")) == "true")
    view = c._api_view(api)
    view["rootResourceId"] = next(r_["id"] for r_ in api["resources"].values() if r_["parentId"] is None)
    if warnings:
        view["warnings"] = warnings
    return _json(c, 200, view)


# ───────────────────────── routing ─────────────────────────
def _match(pattern, segs):
    if len(pattern) != len(segs):
        return None
    out = []
    for p, s in zip(pattern, segs):
        if p == "*":
            out.append(s)
        elif p != s:
            return None
    return out


def route(c, store, method, segs, query, payload, raw_body=b""):
    """-> ApiGwResponse | None (None = not one of ours -> the caller 404s)."""
    seg = [urllib.parse.unquote(s) for s in segs]
    R = "restapis"

    def api_of(i):
        return c._require_api(store, seg[i])

    # top level
    if seg[0] == "domainnames":
        if len(seg) == 1:
            return create_domain(c, store, query, payload) if method == "POST" else get_domains(c, store, query) if method == "GET" else None
        if len(seg) == 2:
            return {"GET": lambda: get_domain(c, store, seg[1]), "PATCH": lambda: update_domain(c, store, seg[1], payload), "DELETE": lambda: delete_domain(c, store, seg[1])}.get(method, lambda: None)()
        if len(seg) == 3 and seg[2] == "basepathmappings":
            return create_mapping(c, store, seg[1], payload) if method == "POST" else get_mappings(c, store, seg[1], query) if method == "GET" else None
        if len(seg) == 4 and seg[2] == "basepathmappings":
            return {"GET": lambda: get_mapping(c, store, seg[1], seg[3]), "PATCH": lambda: update_mapping(c, store, seg[1], seg[3], payload),
                    "DELETE": lambda: delete_mapping(c, store, seg[1], seg[3])}.get(method, lambda: None)()
        return None
    if seg[0] == "vpclinks":
        if len(seg) == 1:
            return create_vpclink(c, store, query, payload) if method == "POST" else get_vpclinks(c, store, query) if method == "GET" else None
        if len(seg) == 2:
            return {"GET": lambda: get_vpclink(c, store, seg[1]), "PATCH": lambda: update_vpclink(c, store, seg[1], payload), "DELETE": lambda: delete_vpclink(c, store, seg[1])}.get(method, lambda: None)()
        return None
    if seg[0] == "tags" and len(seg) >= 2:
        arn = "/".join(seg[1:])
        return {"PUT": lambda: tag_resource(c, store, arn, payload), "DELETE": lambda: untag_resource(c, store, arn, query), "GET": lambda: get_tags(c, store, arn)}.get(method, lambda: None)()
    if seg[0] == "sdktypes":
        if len(seg) == 1 and method == "GET":
            return get_sdk_types(c, store, query)
        if len(seg) == 2 and method == "GET":
            return get_sdk_type(c, store, seg[1])
        return None
    if seg[0] == "usageplans":
        if len(seg) == 4 and seg[2] == "keys" and method == "GET":
            return get_usage_plan_key(c, store, seg[1], seg[3])
        if len(seg) == 3 and seg[2] == "usage" and method == "GET":
            return get_usage(c, store, seg[1], query)
        return None
    if seg[0] == "apikeys" and len(seg) == 3 and seg[2] == "usage":
        return None
    if seg[0] == "apikeys" and len(seg) == 2:
        return None
    if seg[0] == "usageplans" and len(seg) == 5 and seg[2] == "keys" and seg[4] == "usage" and method == "PATCH":
        return update_usage(c, store, seg[1], seg[3], payload)
    if seg[0] != R:
        return None

    # /restapis (import)
    if len(seg) == 1:
        return import_api(c, store, query, raw_body) if method == "POST" and _first(query.get("mode")) == "import" else None
    if len(seg) == 2 and method == "PUT":
        return put_rest_api(c, store, api_of(1), query, raw_body)
    if len(seg) < 3:
        return None
    api, sub = None, seg[2]
    n = len(seg)
    if sub == "authorizers":
        api = api_of(1)
        if n == 3:
            return create_authorizer(c, store, api, query, payload) if method == "POST" else _json(c, 200, _page(list(_authorizers(api).values()), query)) if method == "GET" else None
        if n == 4:
            return {"GET": lambda: _json(c, 200, _authorizer(c, api, seg[3])), "PATCH": lambda: update_authorizer(c, store, api, seg[3], payload),
                    "DELETE": lambda: delete_authorizer(c, store, api, seg[3]), "POST": lambda: test_invoke_authorizer(c, store, api, seg[3], payload)}.get(method, lambda: None)()
        return None
    if sub == "models":
        api = api_of(1)
        if n == 3:
            return create_model(c, store, api, query, payload) if method == "POST" else _json(c, 200, _page(list(_models(api).values()), query)) if method == "GET" else None
        if n == 4:
            return {"GET": lambda: _json(c, 200, _model(c, api, seg[3])), "PATCH": lambda: update_model(c, store, api, seg[3], payload),
                    "DELETE": lambda: delete_model(c, store, api, seg[3])}.get(method, lambda: None)()
        if n == 5 and seg[4] == "default_template" and method == "GET":
            return model_template(c, store, api, seg[3])
        return None
    if sub == "requestvalidators":
        api = api_of(1)
        if n == 3:
            return create_validator(c, store, api, query, payload) if method == "POST" else _json(c, 200, _page(list(_validators(api).values()), query)) if method == "GET" else None
        if n == 4:
            return {"GET": lambda: _json(c, 200, _validator(c, api, seg[3])), "PATCH": lambda: update_validator(c, store, api, seg[3], payload),
                    "DELETE": lambda: delete_validator(c, store, api, seg[3])}.get(method, lambda: None)()
        return None
    if sub == "gatewayresponses":
        api = api_of(1)
        if n == 3 and method == "GET":
            return get_gateway_responses(c, store, api, query)
        if n == 4:
            return {"PUT": lambda: put_gateway_response(c, store, api, seg[3], payload), "GET": lambda: get_gateway_response(c, store, api, seg[3]),
                    "PATCH": lambda: update_gateway_response(c, store, api, seg[3], payload), "DELETE": lambda: delete_gateway_response(c, store, api, seg[3])}.get(method, lambda: None)()
        return None
    if sub == "documentation":
        api = api_of(1)
        if n == 4 and seg[3] == "parts":
            if method == "POST":
                return create_doc_part(c, store, api, query, payload)
            if method == "GET":
                return get_doc_parts(c, store, api, query)
            if method == "PUT":
                return import_doc_parts(c, store, api, query, payload)
        if n == 5 and seg[3] == "parts":
            return {"GET": lambda: _json(c, 200, _doc(c, api, seg[4])), "PATCH": lambda: update_doc_part(c, store, api, seg[4], payload),
                    "DELETE": lambda: delete_doc_part(c, store, api, seg[4])}.get(method, lambda: None)()
        if n == 4 and seg[3] == "versions":
            return create_doc_version(c, store, api, query, payload) if method == "POST" else get_doc_versions(c, store, api, query) if method == "GET" else None
        if n == 5 and seg[3] == "versions":
            return {"GET": lambda: get_doc_version(c, store, api, seg[4]), "PATCH": lambda: update_doc_version(c, store, api, seg[4], payload),
                    "DELETE": lambda: delete_doc_version(c, store, api, seg[4])}.get(method, lambda: None)()
        return None
    if sub == "resources":
        api = api_of(1)
        if n == 4 and method == "PATCH":
            return update_resource(c, store, api, seg[3], payload)
        if n >= 6 and seg[4] == "methods":
            rid, hm = seg[3], seg[5]
            if n == 6 and method == "PATCH":
                return update_method(c, store, api, rid, hm, payload)
            if n == 8 and seg[6] == "responses":
                return {"PUT": lambda: put_method_response(c, store, api, rid, hm, seg[7], payload), "GET": lambda: get_method_response(c, store, api, rid, hm, seg[7]),
                        "PATCH": lambda: update_method_response(c, store, api, rid, hm, seg[7], payload), "DELETE": lambda: delete_method_response(c, store, api, rid, hm, seg[7])}.get(method, lambda: None)()
            if n == 7 and seg[6] == "integration" and method == "PATCH":
                return update_integration(c, store, api, rid, hm, payload)
            if n == 9 and seg[6] == "integration" and seg[7] == "responses":
                return {"PUT": lambda: put_integration_response(c, store, api, rid, hm, seg[8], payload), "GET": lambda: get_integration_response(c, store, api, rid, hm, seg[8]),
                        "PATCH": lambda: update_integration_response(c, store, api, rid, hm, seg[8], payload), "DELETE": lambda: delete_integration_response(c, store, api, rid, hm, seg[8])}.get(method, lambda: None)()
        return None
    if sub == "deployments" and n == 4:
        api = api_of(1)
        if method == "PATCH":
            return update_deployment(c, store, api, seg[3], payload)
        if method == "DELETE":
            return delete_deployment(c, store, api, seg[3])
        return None
    if sub == "stages" and n >= 4:
        api = api_of(1)
        if n == 6 and seg[4] == "cache" and method == "DELETE" and seg[5] in ("data", "authorizers"):
            return flush_stage_cache(c, store, api, seg[3], seg[5])
        if n == 6 and seg[4] == "exports" and method == "GET":
            return export_api(c, store, api, seg[3], seg[5], query)
        return None
    return None
