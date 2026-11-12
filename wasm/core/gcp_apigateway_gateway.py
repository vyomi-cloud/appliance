# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""API Gateway (GCP) DATA PLANE — substrate-free; runs on the shared gateway engine in core/apigatewayv2_gateway.py.

`handle()` serves one request for a deployed gateway (`https://{id}-{hash}.{code}.gateway.dev/...` or the path-style
`/gcpgw/{gatewayId}/...` the simulator origin offers) the way ESPv2 does, over the gateway's API config (the OpenAPI 2.0 document):

  route match        v2 `_route_match` (exact > param > greedy); no route -> 404 "The current request is not defined by this API."
  authentication     per-operation `security` (else the document's top-level `security`); each requirement is an alternative, the schemes
                     inside one requirement all must pass:
                       apiKey -> `key` query / header named by the definition; the key must exist in the project's API Keys
                                 (core/gcp_apigateway_core keys store) -> else 400 "API key not valid." / 401 "Method doesn't allow
                                 unregistered callers ..."
                       oauth2 -> Bearer JWT: v2 `jwt_validate` (iss / aud via `x-google-audiences` / exp / nbf) + signature through the
                                 injected `verify_sig`. NO verifier injected -> fails closed (a token we could not verify is never admitted).
  quota              `x-google-management.quota.limits` x per-operation `x-google-quota.metricCosts`: fixed 1-minute (`1/min/{project}`) or
                     1-second windows per consumer project; over the limit -> 429 RESOURCE_EXHAUSTED
  backend            `x-google-backend` (operation overrides document): `path_translation` CONSTANT_ADDRESS (path params go to the query)
                     or APPEND_PATH_TO_ADDRESS; forwarded through the injected `http_fetch(method, url, headers, body, timeout)`; a runtime
                     with none (Nano in a browser tab) answers 503 — auth, quota and 404s still work everywhere.

Everything that touches the world is injected, like the v2 engine. No fastapi / socket imports at module level.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time

try:
    from core import apigatewayv2_core as v2
    from core import apigatewayv2_gateway as eng
    from core import gateway_common as gc
    from core import gcp_apigateway_core as ctl
except ImportError:  # pragma: no cover - Pyodide flat layout
    import apigatewayv2_core as v2  # type: ignore
    import apigatewayv2_gateway as eng  # type: ignore
    import gateway_common as gc  # type: ignore
    import gcp_apigateway_core as ctl  # type: ignore

_METHODS = ("get", "put", "post", "delete", "options", "head", "patch")
_COUNTERS: dict = {}
_DOC_CACHE: dict = {}
UNREGISTERED = ("Method doesn't allow unregistered callers (callers without established identity). "
                "Please use API Key or other form of API consumer identity to call this API.")


def _err(status, message, grpc):
    body = {"error": {"code": status, "message": message, "status": grpc}}
    return v2.ApiGwV2Response(status=status, body=json.dumps(body).encode(), headers={"content-type": "application/json"})


def _plain(status, message, headers=None):
    return v2.ApiGwV2Response(status=status, body=message.encode(), headers={"content-type": "text/plain", **(headers or {})}, media_type="text/plain")


def reset_caches():
    _COUNTERS.clear()
    _DOC_CACHE.clear()


# ── gateway / config resolution ──────────────────────────────────────────────
def find_gateway(store, host: str = "", gateway_id: str = ""):
    host = (host or "").split(":", 1)[0].lower()
    for g in ctl._coll(store, "gateways").values():
        if (host and g.get("defaultHostname", "").lower() == host) or (gateway_id and g["name"].rsplit("/", 1)[-1] == gateway_id):
            return g
    return None


def _document(store, cfg_name):
    cfg = ctl._coll(store, "configs").get(cfg_name)
    if not cfg:
        return None, None
    key = (cfg_name, cfg.get("serviceConfigId"))
    if key not in _DOC_CACHE:
        doc = {"swagger": "2.0", "info": {"title": "t"}, "paths": {}}
        for d in cfg.get("openapiDocuments") or []:
            parsed = ctl.parse_openapi(ctl._decode(((d or {}).get("document") or {}).get("contents") or ""))
            doc["paths"].update(parsed.get("paths") or {})
            for k, v in parsed.items():
                if k != "paths":
                    doc.setdefault(k, v)
        _DOC_CACHE[key] = doc
    return cfg, _DOC_CACHE[key]


def _compiled(doc):
    """A v2-shaped route table (`{"routes": {...}}`) so the shared `_route_match` picks the route."""
    routes = {}
    for path, ops in (doc.get("paths") or {}).items():
        for method, op in (ops or {}).items():
            if str(method).lower() in _METHODS and isinstance(op, dict):
                key = "%s %s" % (str(method).upper(), path)
                routes[key] = {"routeKey": key, "op": op}
    return {"routes": routes}


# ── authentication ───────────────────────────────────────────────────────────
def _keys_for(store, project):
    return [k for k in ctl._coll(store, "keys").values() if k["name"].startswith("projects/%s/" % project)]


def _check_scheme(store, project, name, sd, headers, query, verify_sig, state):
    """-> None if the scheme is satisfied, else (response)."""
    t = sd.get("type")
    if t == "apiKey":
        where, kn = sd.get("in"), sd.get("name")
        val = (query or {}).get(kn) if where == "query" else eng._hget(headers, kn)
        if not val:
            return _err(401, UNREGISTERED, "UNAUTHENTICATED")
        if not any(k["keyString"] == val for k in _keys_for(store, project)):
            return _err(400, "API key not valid. Please pass a valid API key.", "INVALID_ARGUMENT")
        state["consumer"] = val
        return None
    if t == "oauth2":
        auth = eng._hget(headers, "authorization") or ""
        tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not tok:
            return _plain(401, "Jwt is missing", {"www-authenticate": 'Bearer realm="gateway"'})
        aud = [a.strip() for a in str(sd.get("x-google-audiences") or "").split(",") if a.strip()]
        cfg = {"issuer": sd.get("x-google-issuer"), "audience": aud, "jwks_uri": sd.get("x-google-jwks_uri")}
        if verify_sig is None:
            return _plain(401, "Jwt verification fails: no signature verifier is available in this runtime", {"www-authenticate": "Bearer"})
        claims, _scopes = eng.jwt_validate(tok, cfg, verify_sig)
        if claims is None:
            return _plain(401, "Jwt verification fails", {"www-authenticate": 'Bearer error="invalid_token"'})
        state["claims"] = claims
        return None
    return _err(401, "Unsupported security definition '%s'." % name, "UNAUTHENTICATED")


def _authenticate(store, project, doc, op, headers, query, verify_sig, state):
    sec = op["security"] if "security" in op else doc.get("security")
    if not sec:
        return None
    defs, last = doc.get("securityDefinitions") or {}, None
    for req in sec:                       # alternatives
        bad = None
        for name in req:                  # all schemes of one requirement
            bad = _check_scheme(store, project, name, defs.get(name) or {}, headers, query, verify_sig, state)
            if bad is not None:
                break
        if bad is None:
            return None
        last = last or bad
    return last


# ── quota ────────────────────────────────────────────────────────────────────
def _quota(doc, op, project, consumer, now):
    costs = (op.get("x-google-quota") or {}).get("metricCosts") or {}
    if not costs:
        return None
    mg = doc.get("x-google-management") or {}
    for lim in (mg.get("quota") or {}).get("limits") or []:
        cost = costs.get(lim.get("metric"))
        if cost is None:
            continue
        cap = (lim.get("values") or {}).get("STANDARD")
        if cap is None:
            continue
        unit = str(lim.get("unit") or "")
        window = 1 if unit.startswith("1/s") else 60
        # per-project limits count the project; per-user limits would need a user dimension — the API key is the nearest one here.
        who = project if "{project}" in unit or not consumer else consumer
        ck = (project, lim["name"], who)
        ok, retry = gc.window_take(_COUNTERS, ck, now, window, cost, cap)
        if not ok:
            return _err(429, "Quota exceeded for quota metric '%s' and limit '%s' of service '%s' for consumer 'project:%s'." % (
                lim["metric"], lim["name"], (doc.get("host") or "gateway.vyomi.local"), project), "RESOURCE_EXHAUSTED"), retry
    return None


# ── backend ──────────────────────────────────────────────────────────────────
def _backend(doc, op):
    b = dict(doc.get("x-google-backend") or {})
    b.update(op.get("x-google-backend") or {})
    return b


def _target_url(b, path, params, query):
    return gc.build_backend_url(str(b["address"]), path, params, query, b.get("path_translation"))


def handle(store, gateway, method, path, headers=None, query=None, body=b"", *, http_fetch=None, verify_sig=None,
           source_ip="127.0.0.1", now=None):
    """Serve one request for `gateway` (a gateway record from the control plane)."""
    now = time.time() if now is None else now
    headers, query, method = dict(headers or {}), dict(query or {}), (method or "GET").upper()
    cfg, doc = _document(store, gateway.get("apiConfig"))
    if doc is None:
        return _err(503, "The gateway's API config is not available.", "UNAVAILABLE")
    project = gateway["name"].split("/")[1]
    route, params = v2._route_match(_compiled(doc), method, path)
    if route is None:
        return v2.ApiGwV2Response(status=404, body=json.dumps({"code": 404, "message": "The current request is not defined by this API."}).encode(),
                                  headers={"content-type": "application/json"})
    op = route["op"]
    state: dict = {}
    bad = _authenticate(store, project, doc, op, headers, query, verify_sig, state)
    if bad is not None:
        return bad
    over = _quota(doc, op, project, state.get("consumer"), now)
    if over is not None:
        resp, retry = over
        resp.headers["retry-after"] = str(retry)
        return resp
    b = _backend(doc, op)
    if not b.get("address"):
        return _err(503, "No backend is configured for this operation.", "UNAVAILABLE")
    if http_fetch is None:
        return _err(503, "The backend cannot be reached from this runtime (no outbound network).", "UNAVAILABLE")
    url = _target_url(b, path, params, {k: v for k, v in query.items() if not (state.get("consumer") and k == "key")})
    out_h = gc.strip_hop(headers)
    out_h["x-forwarded-for"] = source_ip
    if state.get("claims"):
        out_h["x-endpoint-api-userinfo"] = base64.urlsafe_b64encode(json.dumps(state["claims"]).encode()).decode().rstrip("=")
    try:
        status, rh, rb = http_fetch(method, url, out_h, body or b"", float(b.get("deadline") or 15))
    except Exception:
        return _err(503, "The backend is unreachable.", "UNAVAILABLE")
    rh = gc.strip_resp_hop(rh)
    return v2.ApiGwV2Response(status=status, body=rb or b"", headers=rh)


# ── default injectables (appliance / dev server; Nano passes none) ───────────
default_http_fetch = gc.default_http_fetch


def default_verify_sig():
    """RS256 against the definition's `x-google-jwks_uri` (else OIDC discovery of the issuer). Fails closed on anything else."""
    return gc.make_rs256_verifier()
