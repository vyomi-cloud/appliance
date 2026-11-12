# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""API Gateway v1 (REST) DATA PLANE enforcement — substrate-free, on the shared cross-cloud primitives in core/gateway_common.py.

`core/apigateway_core.invoke()` matches stage -> resource -> method and runs the integration (MOCK / AWS_PROXY / AWS / HTTP /
HTTP_PROXY); this module is the layer in between, called as `enforce(...)`, in the order the real service applies it:

  stage throttle      stage `throttle` {rateLimit, burstLimit} (token bucket per api+stage)                -> 429 "Too Many Requests"
  authorizer          method.authorizationType:
                        CUSTOM               the authorizer's Lambda (TOKEN: identity header + identityValidationExpression;
                                             REQUEST: headers/query/path/stage vars); Allow/Deny policy; `context` -> requestContext.authorizer
                        COGNITO_USER_POOLS   Bearer JWT: gc.jwt_validate with the pool issuer taken from the authorizer's providerARNs;
                                             signature through the injected verify_sig, NONE injected -> fail closed (401)
                        AWS_IAM              the request must carry a SigV4 `Authorization: AWS4-HMAC-SHA256 ...` header (403 otherwise).
                                             The SIGNATURE AND THE IAM POLICY ARE NOT EVALUATED.
  API key             method.apiKeyRequired: `x-api-key` header -> an enabled key that belongs to a usage plan covering this api+stage,
                      else 403 {"message":"Forbidden"}
  usage plan          that plan's throttle (token bucket per plan+key) -> 429 "Too Many Requests"; quota {limit, period DAY|WEEK|MONTH}
                      fixed windows (24h / 7d / 30d) -> 429 "Limit Exceeded"

Not modelled: apiKeySource AUTHORIZER, authorizer result caching (every request re-invokes the authorizer), per-method usage-plan
throttle, WAF, request validation / mapping templates for non-proxy integrations. No fastapi / socket imports (Pyodide-loadable).
"""
from __future__ import annotations

import json
import re
import time

from core import gateway_common as gc

_THROTTLE = gc.Throttle()
_QUOTA: dict = {}
_PERIODS = {"DAY": 86400, "WEEK": 7 * 86400, "MONTH": 30 * 86400}


def reset_caches():
    _THROTTLE._b.clear()
    _QUOTA.clear()


def _err(status, message, headers=None):
    from core.apigateway_core import ApiGwResponse
    return ApiGwResponse(status=status, body=json.dumps({"message": message}).encode(), headers=dict(headers or {}))


def _lambda_name(uri: str) -> str:
    m = re.search(r"functions/(arn:aws:lambda:[^/]+|[^/]+)/invocations", uri or "")
    if not m:
        return ""
    return m.group(1).rsplit(":", 1)[-1] if m.group(1).startswith("arn:") else m.group(1)


def _policy_allows(res: dict) -> bool:
    stmts = (res.get("policyDocument") or {}).get("Statement") or []
    return any(s.get("Effect") == "Allow" for s in stmts) and not any(s.get("Effect") == "Deny" for s in stmts)


def _custom(api, m, stage, method, path, path_params, headers, query, st, lambda_store):
    """-> (denied_response | None, authorizer_context)."""
    from core import lambda_core
    a = (api.get("authorizers") or {}).get(m.get("authorizerId"))
    if not a:
        return _err(500, "Internal server error"), None
    arn = "arn:aws:execute-api:us-east-1:000000000000:%s/%s/%s/%s" % (api["id"], stage, method, path.strip("/"))
    if a["type"] == "TOKEN":
        src = (a.get("identitySource") or "method.request.header.Authorization").rsplit(".", 1)[-1]
        tok = gc.hget(headers, src)
        if not tok:
            return _err(401, "Unauthorized"), None
        if a.get("identityValidationExpression") and not re.search(a["identityValidationExpression"], tok):
            return _err(401, "Unauthorized"), None
        event = {"type": "TOKEN", "authorizationToken": tok, "methodArn": arn}
    else:
        event = {"type": "REQUEST", "methodArn": arn, "resource": path, "path": "/" + path.strip("/"), "httpMethod": method,
                 "headers": dict(headers), "queryStringParameters": dict(query) or None, "pathParameters": path_params or None,
                 "stageVariables": dict(st.get("variables") or {}) or None,
                 "requestContext": {"apiId": api["id"], "stage": stage, "httpMethod": method}}
    fn = _lambda_name(a.get("authorizerUri", ""))
    out = lambda_core.dispatch(lambda_store, "POST", "/2015-03-31/functions/%s/invocations" % fn, {}, {}, json.dumps(event).encode())
    if out.status >= 300 or (out.headers or {}).get("X-Amz-Function-Error"):
        return _err(500, "Internal server error"), None
    try:
        res = json.loads(out.body.decode("utf-8"))
    except Exception:
        res = {}
    if not _policy_allows(res if isinstance(res, dict) else {}):
        return _err(403, "User is not authorized to access this resource with an explicit deny"), None
    ctx = {k: v for k, v in ((res or {}).get("context") or {}).items()}
    if res.get("principalId") is not None:
        ctx["principalId"] = res["principalId"]
    return None, ctx


def _cognito(api, m, headers, verify_sig, now):
    a = (api.get("authorizers") or {}).get(m.get("authorizerId"))
    if not a:
        return _err(500, "Internal server error"), None
    tok = gc.hget(headers, "authorization") or ""
    tok = tok[7:].strip() if tok.lower().startswith("bearer ") else tok
    if not tok:
        return _err(401, "Unauthorized"), None
    issuers = []
    for arn in a.get("providerARNs") or []:
        mm = re.match(r"arn:aws:cognito-idp:([^:]+):[^:]*:userpool/(.+)$", arn)
        if mm:
            issuers.append("https://cognito-idp.%s.amazonaws.com/%s" % (mm.group(1), mm.group(2)))
    if verify_sig is None:
        return _err(401, "Unauthorized"), None       # a token we cannot verify is never admitted
    for iss in issuers:
        claims, _ = gc.jwt_validate(tok, {"issuer": iss}, verify_sig, now)
        if claims is not None:
            return None, {"claims": claims}
    return _err(401, "Unauthorized"), None


def _plan_for(store, api_id, stage, key_id):
    from core import apigateway_core as core
    for p in core._usage_plans(store).values():
        if p.get("_keys", {}).get(key_id) and any(s.get("apiId") == api_id and s.get("stage") == stage for s in p.get("apiStages") or []):
            return p
    return None


def enforce(store, api, stage, st, res, m, method, path, path_params, headers, query, lambda_store, verify_sig=None, now=None):
    """-> (denied ApiGwResponse | None, authorizer context | None)."""
    now = time.time() if now is None else now
    th = st.get("throttle") or {}
    if th and not _THROTTLE.allow(("stage", api["id"], stage), th.get("rateLimit"), th.get("burstLimit")):
        return _err(429, "Too Many Requests"), None
    atype = m.get("authorizationType") or "NONE"
    authctx = None
    if atype == "CUSTOM":
        bad, authctx = _custom(api, m, stage, method, path, path_params, headers, query, st, lambda_store)
        if bad is not None:
            return bad, None
    elif atype == "COGNITO_USER_POOLS":
        bad, authctx = _cognito(api, m, headers, verify_sig, now)
        if bad is not None:
            return bad, None
    elif atype == "AWS_IAM":
        if not (gc.hget(headers, "authorization") or "").startswith("AWS4-HMAC-SHA256"):
            return _err(403, "Missing Authentication Token"), None
    if m.get("apiKeyRequired"):
        from core import apigateway_core as core
        val = gc.hget(headers, "x-api-key")
        key = next((k for k in core._api_keys(store).values() if val and k.get("value") == val and k.get("enabled", True)), None)
        plan = _plan_for(store, api["id"], stage, key["id"]) if key else None
        if plan is None:
            return _err(403, "Forbidden"), None
        pt = plan.get("throttle") or {}
        if pt and not _THROTTLE.allow(("plan", plan["id"], key["id"]), pt.get("rateLimit"), pt.get("burstLimit")):
            return _err(429, "Too Many Requests"), None
        q = plan.get("quota") or {}
        if q.get("limit"):
            period = _PERIODS.get(str(q.get("period") or "DAY").upper(), 86400)
            ok, wait = gc.window_take(_QUOTA, (plan["id"], key["id"]), now, period, 1, int(q["limit"]))
            if not ok:
                return _err(429, "Limit Exceeded", {"retry-after": str(wait)}), None
    return None, authctx
