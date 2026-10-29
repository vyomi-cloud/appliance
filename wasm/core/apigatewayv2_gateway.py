# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""API Gateway V2 data plane — substrate-free request handling + the Caddy route table.

The real HTTP listener is the shared **Caddy gateway** (TLS, host/path routing, live route
changes through its admin API). Caddy forwards every execute-api request to the Vyomi
*integration handler*, which calls `handle()` here:

  CORS · payload limit · route match · throttling (stage/route rate+burst) · JWT authorizers
  (issuer/audience/scopes, signature via an injected JWKS verifier) · Lambda REQUEST
  authorizers (with result caching) · Lambda proxy (payload 1.0 and 2.0) · HTTP proxy ·
  parameter mapping · MOCK.

Everything that touches the world is injected (`invoker` for Lambda, `http_fetch` for HTTP
proxy, `verify_sig` for JWT signatures), so the same code runs offline (real Lambda runtime,
real sockets) and in Nano (in-browser Lambda core). No fastapi / socket / boto3 imports.
"""
from __future__ import annotations

import base64
import json
import re
import time
from urllib.parse import parse_qsl, urlencode

from core import apigatewayv2_core as v2

MAX_PAYLOAD = 10 * 1024 * 1024
GATEWAY_HOST_SUFFIX = "execute-api.localhost"


# ── invoke URLs ──────────────────────────────────────────────────────────────
def invoke_host(api_id: str) -> str:
    return f"{api_id}.{GATEWAY_HOST_SUFFIX}"


def invoke_url(api: dict, stage: str = "$default", port: int | str = v2.GATEWAY_HTTPS_PORT, scheme: str = "https") -> str:
    """`https://{id}.execute-api.localhost:{port}[/{stage}]` — the `$default` stage has no prefix."""
    base = f"{scheme}://{invoke_host(api['apiId'])}:{port}"
    return base if stage in ("", "$default") else f"{base}/{stage}"


# ── Caddy route table ────────────────────────────────────────────────────────
def caddy_config(store, handler: str = "simulator:9000", admin: str = "0.0.0.0:2019") -> dict:
    """Complete Caddy JSON config for every deployed API (POSTed to `/load`: live, no restart).

    Per API: host `{id}.execute-api.localhost` (and the path-style fallback `/apigw/{id}/…`)
    is rewritten to `/_apigw/{id}/{stage}/…` and reverse-proxied to the Vyomi handler. Named
    stages match on their `/{stage}` prefix; `$default` catches the rest. Served over plain
    HTTP (:9080) and TLS from Caddy's internal CA (:9443)."""
    routes, hosts = [], []
    for api_id, api in sorted(store.apis.items()):
        stages = sorted(s for s in api["stages"] if s != "$default")
        sub = [_proxy_route({"path": [f"/{s}", f"/{s}/*"]}, f"/_apigw/{api_id}/{s}", f"/{s}", handler) for s in stages]
        if "$default" in api["stages"]:
            sub.append(_proxy_route({}, f"/_apigw/{api_id}/$default", "", handler))
        if not api.get("disableExecuteApiEndpoint"):
            hosts.append(invoke_host(api_id))
            routes.append({"match": [{"host": [invoke_host(api_id)]}], "handle": [{"handler": "subroute", "routes": sub}],
                           "terminal": True})
        routes.append({"match": [{"path": [f"/apigw/{api_id}", f"/apigw/{api_id}/*"]}],
                       "handle": [{"handler": "rewrite", "strip_path_prefix": f"/apigw/{api_id}"},
                                  {"handler": "subroute", "routes": sub}], "terminal": True})
    routes.append({"handle": [{"handler": "static_response", "status_code": 404,
                               "body": '{"message":"Not Found"}', "headers": {"Content-Type": ["application/json"]}}]})
    cfg = {"admin": {"listen": admin},
           "apps": {"http": {"servers": {
               "apigw": {"listen": [":9080"], "routes": routes, "automatic_https": {"disable": True}},
               "apigws": {"listen": [f":{v2.GATEWAY_HTTPS_PORT}"], "routes": routes, "tls_connection_policies": [{}]}}}}}
    if hosts:
        cfg["apps"]["tls"] = {"automation": {"policies": [{"subjects": hosts, "issuers": [{"module": "internal"}]}]}}
    return cfg


def _proxy_route(match: dict, target_prefix: str, strip: str, handler: str) -> dict:
    h = []
    if strip:
        h.append({"handler": "rewrite", "strip_path_prefix": strip})
    h.append({"handler": "rewrite", "uri": target_prefix + "{http.request.uri}"})
    h.append({"handler": "reverse_proxy", "upstreams": [{"dial": handler}]})
    return {"match": [match] if match else [], "handle": h, "terminal": True}


# ── helpers ──────────────────────────────────────────────────────────────────
def _resp(status, obj=None, headers=None, body=None):
    if body is None:
        body = json.dumps(obj if obj is not None else {}).encode()
    return v2.ApiGwV2Response(status=status, body=body, headers=dict(headers or {}))


def _hget(headers, name, default=None):
    n = name.lower()
    for k, v in (headers or {}).items():
        if k.lower() == n:
            return v
    return default


def _b64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ── throttling ───────────────────────────────────────────────────────────────
class Throttle:
    """Token bucket per (api, stage, route): `rate` tokens/s, capacity `burst`."""

    def __init__(self, clock=time.monotonic):
        self._b: dict = {}
        self._clock = clock

    def allow(self, key, rate, burst) -> bool:
        if rate is None and burst is None:
            return True
        rate = float(rate if rate is not None else burst)
        cap = float(burst if burst is not None else max(1.0, rate))
        now = self._clock()
        tokens, last = self._b.get(key, (cap, now))
        tokens = min(cap, tokens + (now - last) * rate)
        if tokens < 1.0:
            self._b[key] = (tokens, now)
            return False
        self._b[key] = (tokens - 1.0, now)
        return True


_THROTTLE = Throttle()


def _limits(st: dict, route_key: str):
    d = dict(st.get("defaultRouteSettings") or {})
    d.update((st.get("routeSettings") or {}).get(route_key) or {})
    return d.get("throttlingRateLimit"), d.get("throttlingBurstLimit")


# ── CORS ─────────────────────────────────────────────────────────────────────
def _cors_headers(cfg, origin):
    if not cfg or not origin:
        return None
    allowed = cfg.get("allowOrigins") or []
    if "*" not in allowed and origin not in allowed:
        return None
    h = {"access-control-allow-origin": origin if cfg.get("allowCredentials") or "*" not in allowed else "*"}
    if cfg.get("allowCredentials"):
        h["access-control-allow-credentials"] = "true"
    if cfg.get("exposeHeaders"):
        h["access-control-expose-headers"] = ",".join(cfg["exposeHeaders"])
    return h


def _preflight(cfg, headers):
    origin = _hget(headers, "origin")
    h = _cors_headers(cfg, origin)
    if h is None:
        return _resp(204, body=b"")
    if cfg.get("allowMethods"):
        h["access-control-allow-methods"] = ",".join(cfg["allowMethods"])
    if cfg.get("allowHeaders"):
        h["access-control-allow-headers"] = ",".join(cfg["allowHeaders"])
    else:
        req = _hget(headers, "access-control-request-headers")
        if req:
            h["access-control-allow-headers"] = req
    if cfg.get("maxAge") is not None:
        h["access-control-max-age"] = str(cfg["maxAge"])
    return _resp(204, body=b"", headers=h)


# ── authorizers ──────────────────────────────────────────────────────────────
def _identity_values(sources, headers, query):
    vals = []
    for src in sources or ["$request.header.Authorization"]:
        m = re.fullmatch(r"\$request\.(header|querystring)\.(.+)", src)
        if not m:
            vals.append(None)
        elif m.group(1) == "header":
            vals.append(_hget(headers, m.group(2)))
        else:
            vals.append((query or {}).get(m.group(2)))
    return vals


def jwt_validate(token, cfg, verify_sig=None, now=None):
    """-> (claims | None, scopes). Checks structure, signature (if a verifier is injected),
    exp/nbf, issuer, and audience / client_id."""
    try:
        h, p, _ = token.split(".")
        header, claims = json.loads(_b64u(h)), json.loads(_b64u(p))
    except Exception:
        return None, []
    now = now if now is not None else time.time()
    if verify_sig is not None and not verify_sig(token, header, cfg):
        return None, []
    if "exp" in claims and now >= float(claims["exp"]):
        return None, []
    if "nbf" in claims and now < float(claims["nbf"]):
        return None, []
    if cfg.get("issuer") and claims.get("iss") != cfg["issuer"]:
        return None, []
    aud = cfg.get("audience") or []
    if aud:
        got = claims.get("aud")
        got = got if isinstance(got, list) else [got] if got is not None else []
        if claims.get("client_id") is not None:
            got.append(claims["client_id"])
        if not set(aud) & set(got):
            return None, []
    scopes = claims.get("scope", claims.get("scp", []))
    scopes = scopes.split() if isinstance(scopes, str) else list(scopes or [])
    return claims, scopes


_AUTH_CACHE: dict = {}


def reset_caches():
    _AUTH_CACHE.clear()
    _THROTTLE._b.clear()


def _authorize(api, route, au, ctx):
    """-> (error_response | None, authorizer_context dict)."""
    headers, query = ctx["headers"], ctx["query"]
    ids = _identity_values(au.get("identitySource"), headers, query)
    if au["authorizerType"] == "JWT":
        tok = ids[0] if ids else None
        if not tok:
            return _resp(401, {"message": "Unauthorized"}, {"www-authenticate": "Bearer"}), None
        if tok.lower().startswith("bearer "):
            tok = tok[7:].strip()
        jc = au.get("jwtConfiguration") or {}
        cfg = {"issuer": jc.get("issuer") or jc.get("Issuer"), "audience": jc.get("audience") or jc.get("Audience") or []}
        claims, scopes = jwt_validate(tok, cfg, ctx.get("verify_sig"))
        if claims is None:
            return _resp(401, {"message": "Unauthorized"}, {"www-authenticate": "Bearer"}), None
        need = route.get("authorizationScopes") or []
        if need and not set(need) & set(scopes):
            return _resp(403, {"message": "Forbidden"}), None
        return None, {"jwt": {"claims": {k: (v if isinstance(v, str) else json.dumps(v)) for k, v in claims.items()},
                              "scopes": scopes or None}}
    # REQUEST (Lambda) authorizer
    if any(v in (None, "") for v in ids) and au.get("identitySource"):
        return _resp(401, {"message": "Unauthorized"}), None
    ttl = au.get("authorizerResultTtlInSeconds", 300)
    ck = (api["apiId"], au["authorizerId"], tuple(ids), route["routeKey"] if not ttl else "")
    hit = _AUTH_CACHE.get(ck)
    if ttl and hit and hit[0] > time.time():
        ok, actx = hit[1], hit[2]
    else:
        ok, actx = _run_request_authorizer(api, route, au, ctx)
        if ttl:
            _AUTH_CACHE[ck] = (time.time() + ttl, ok, actx)
    if not ok:
        return _resp(403, {"message": "Forbidden"}), None
    return None, {"lambda": actx or {}}


def _fn_name(uri: str) -> str:
    m = re.search(r"function:([A-Za-z0-9_-]+)", uri or "")
    return m.group(1) if m else (uri or "").rsplit("/", 1)[-1]


def _run_request_authorizer(api, route, au, ctx):
    event = {"version": "2.0" if au.get("authorizerPayloadFormatVersion", "2.0") == "2.0" else "1.0",
             "type": "REQUEST", "routeArn": f"arn:aws:execute-api:{v2.REGION}:{v2.ACCOUNT}:{api['apiId']}/{ctx['stage']}/{ctx['method']}{ctx['path']}",
             "identitySource": [v for v in _identity_values(au.get("identitySource"), ctx["headers"], ctx["query"]) if v],
             "routeKey": route["routeKey"], "rawPath": ctx["path"],
             "rawQueryString": urlencode(ctx["query"]), "headers": {k.lower(): v for k, v in ctx["headers"].items()},
             "queryStringParameters": ctx["query"] or None, "pathParameters": ctx["params"] or None,
             "requestContext": {"apiId": api["apiId"], "stage": ctx["stage"], "http": {"method": ctx["method"], "path": ctx["path"]}}}
    res = ctx["invoker"](_fn_name(au.get("authorizerUri", "")), event)
    if not isinstance(res, dict) or res.get("_error"):
        return False, {}
    if "isAuthorized" in res:
        return bool(res["isAuthorized"]), res.get("context") or {}
    stmts = (res.get("policyDocument") or {}).get("Statement") or []
    allow = any(s.get("Effect") == "Allow" for s in stmts) and not any(s.get("Effect") == "Deny" for s in stmts)
    return allow, res.get("context") or {}


# ── parameter mapping ────────────────────────────────────────────────────────
def _mapval(expr, ctx):
    def sub(m):
        kind, _, name = m.group(1).partition(".")
        if kind == "request":
            sect, _, key = name.partition(".")
            if sect == "header":
                return _hget(ctx["headers"], key, "") or ""
            if sect == "querystring":
                return str(ctx["query"].get(key, ""))
            if sect == "path":
                return str(ctx["params"].get(key, ""))
        if kind == "context":
            return str({"apiId": ctx["api_id"], "stage": ctx["stage"], "routeKey": ctx["route_key"],
                        "requestId": ctx["request_id"], "http.method": ctx["method"],
                        "http.path": ctx["path"]}.get(name, ""))
        if kind == "stageVariables":
            return str((ctx.get("stage_vars") or {}).get(name, ""))
        return ""
    return re.sub(r"\$((?:request|context|stageVariables)\.[A-Za-z0-9_.\-$]+)", sub, str(expr))


def _apply_mapping(integ, ctx, headers, query, path):
    for dest, expr in (integ.get("requestParameters") or {}).items():
        op, _, target = dest.partition(":")
        if not target:
            op, target = "overwrite", dest
        sect, _, key = target.partition(".")
        val = _mapval(expr, ctx)
        if sect == "header":
            for k in [k for k in headers if k.lower() == key.lower()]:
                del headers[k]
            if op != "remove":
                headers[key] = val
        elif sect == "querystring":
            query.pop(key, None)
            if op != "remove":
                query[key] = val
        elif sect == "path" and op != "remove":
            path = val
    return headers, query, path


# ── events ───────────────────────────────────────────────────────────────────
def _event(api, st, r, ctx, version, authctx):
    raw_path = "/" + ctx["path"].strip("/")
    body, b64 = ctx["body_text"]
    now = time.time()
    if version == "1.0":
        hdrs = dict(ctx["headers"])
        return {"version": "1.0", "resource": _tmpl(r["routeKey"]), "path": raw_path, "httpMethod": ctx["method"],
                "headers": hdrs, "multiValueHeaders": {k: [v] for k, v in hdrs.items()},
                "queryStringParameters": ctx["query"] or None,
                "multiValueQueryStringParameters": {k: [v] for k, v in ctx["query"].items()} or None,
                "pathParameters": ctx["params"] or None, "stageVariables": st.get("stageVariables") or None,
                "requestContext": {"accountId": v2.ACCOUNT, "apiId": api["apiId"], "stage": st["stageName"],
                                   "requestId": ctx["request_id"], "resourcePath": _tmpl(r["routeKey"]),
                                   "httpMethod": ctx["method"], "path": raw_path, "protocol": "HTTP/1.1",
                                   "requestTimeEpoch": int(now * 1000), "identity": {"sourceIp": ctx["source_ip"]},
                                   **({"authorizer": _flat(authctx)} if authctx else {})},
                "body": body, "isBase64Encoded": b64}
    rc = {"accountId": v2.ACCOUNT, "apiId": api["apiId"], "domainName": invoke_host(api["apiId"]),
          "domainPrefix": api["apiId"], "requestId": ctx["request_id"], "routeKey": r["routeKey"],
          "stage": st["stageName"], "time": time.strftime("%d/%b/%Y:%H:%M:%S +0000", time.gmtime(now)),
          "timeEpoch": int(now * 1000),
          "http": {"method": ctx["method"], "path": raw_path, "protocol": "HTTP/1.1", "sourceIp": ctx["source_ip"],
                   "userAgent": _hget(ctx["headers"], "user-agent", "")}}
    if authctx:
        rc["authorizer"] = authctx
    ev = {"version": "2.0", "routeKey": r["routeKey"], "rawPath": raw_path, "rawQueryString": urlencode(ctx["query"]),
          "headers": {k.lower(): v for k, v in ctx["headers"].items()},
          "queryStringParameters": ctx["query"] or None, "pathParameters": ctx["params"] or None,
          "requestContext": rc, "body": body or None, "isBase64Encoded": b64,
          "stageVariables": st.get("stageVariables") or None}
    cookie = _hget(ctx["headers"], "cookie")
    if cookie:
        ev["cookies"] = [c.strip() for c in cookie.split(";")]
    return ev


def _tmpl(route_key):
    return route_key.partition(" ")[2] or "/"


def _flat(authctx):
    return authctx.get("lambda") or authctx.get("jwt") or {}


def _lambda_result(res, version):
    if isinstance(res, dict) and res.get("_error"):
        return _resp(500, {"message": "Internal Server Error"})
    if isinstance(res, dict) and "statusCode" in res:
        status = int(res["statusCode"])
        hdrs = {str(k): str(v) for k, v in (res.get("headers") or {}).items()}
        for k, vs in (res.get("multiValueHeaders") or {}).items():
            hdrs[str(k)] = ",".join(map(str, vs))
        if res.get("cookies"):
            hdrs["set-cookie"] = res["cookies"][0]
        ob = res.get("body", "")
        if res.get("isBase64Encoded") and isinstance(ob, str):
            raw = base64.b64decode(ob)
        else:
            raw = ob.encode() if isinstance(ob, str) else (json.dumps(ob).encode() if ob is not None else b"")
        return v2.ApiGwV2Response(status=status, body=raw, headers=hdrs)
    if version == "1.0":
        return _resp(502, {"message": "Internal server error"})
    # 2.0 auto-response: the returned JSON becomes the body, 200 application/json
    return v2.ApiGwV2Response(status=200, body=json.dumps(res).encode() if res is not None else b"null")


# ── the handler ──────────────────────────────────────────────────────────────
def handle(store, api_id, stage, method, path, headers=None, query=None, body=b"", *,
           invoker=None, http_fetch=None, verify_sig=None, source_ip="127.0.0.1", request_id=None):
    """Serve one execute-api request against a deployed HTTP API."""
    api = store.apis.get(api_id)
    if not api or api["protocolType"] != "HTTP" or api.get("disableExecuteApiEndpoint"):
        return _resp(404, {"message": "Not Found"})
    st = api["stages"].get(stage) or api["stages"].get("$default")
    if st is None or not st.get("deploymentId"):
        return _resp(404, {"message": "Not Found"})
    headers, query = dict(headers or {}), dict(query or {})
    method = (method or "GET").upper()
    cors = api.get("corsConfiguration")
    if method == "OPTIONS" and cors and _hget(headers, "access-control-request-method"):
        return _preflight(cors, headers)
    if len(body or b"") > MAX_PAYLOAD:
        return _resp(413, {"message": "Request Entity Too Large"})
    r, params = v2._route_match(api, method, path)
    cors_h = _cors_headers(cors, _hget(headers, "origin")) or {}

    def done(resp):
        resp.headers = {**resp.headers, **{k: v for k, v in cors_h.items() if k not in resp.headers}}
        resp.headers.setdefault("apigw-requestid", request_id or "")
        return resp

    if r is None:
        return done(_resp(404, {"message": "Not Found"}))
    request_id = request_id or v2._new_id() + "="
    rate, burst = _limits(st, r["routeKey"])
    if not _THROTTLE.allow((api_id, st["stageName"], r["routeKey"]), rate, burst):
        return done(_resp(429, {"message": "Too Many Requests"}))
    if invoker is None:
        invoker = _default_invoker(store)
    try:
        text = (body or b"").decode("utf-8")
        body_text = (text, False)
    except UnicodeDecodeError:
        body_text = (base64.b64encode(body).decode(), True)
    ctx = {"headers": headers, "query": query, "params": params, "method": method, "path": "/" + path.strip("/"),
           "stage": st["stageName"], "api_id": api_id, "route_key": r["routeKey"], "request_id": request_id,
           "source_ip": source_ip, "body_text": body_text, "invoker": invoker, "verify_sig": verify_sig,
           "stage_vars": st.get("stageVariables") or {}}
    authctx = None
    if r.get("authorizationType") in ("JWT", "CUSTOM") and r.get("authorizerId"):
        au = api["authorizers"].get(r["authorizerId"])
        if au is not None:
            err, authctx = _authorize(api, r, au, ctx)
            if err is not None:
                return done(err)
    elif r.get("authorizationType") == "AWS_IAM":
        if not _hget(headers, "authorization"):
            return done(_resp(403, {"message": "Missing Authentication Token"}))
    tgt = r.get("target") or ""
    integ = api["integrations"].get(tgt.split("/", 1)[1]) if tgt.startswith("integrations/") else None
    if integ is None:
        return done(_resp(500, {"message": "Internal Server Error"}))
    itype = integ["integrationType"]
    if itype == "MOCK":
        return done(v2.ApiGwV2Response(status=200, body=b""))
    version = integ.get("payloadFormatVersion", "2.0")
    if itype in ("AWS_PROXY", "AWS"):
        ev = _event(api, st, r, ctx, version, authctx)
        res = invoker(_fn_name(integ.get("integrationUri", "")), ev)
        return done(_lambda_result(res, version))
    if itype in ("HTTP_PROXY", "HTTP"):
        h2, q2, p2 = _apply_mapping(integ, ctx, dict(headers), dict(query), ctx["path"])
        uri = integ.get("integrationUri", "")
        for k, v in params.items():
            uri = uri.replace("{" + k + "+}", v).replace("{" + k + "}", v)
        if q2:
            uri += ("&" if "?" in uri else "?") + urlencode(q2)
        m = integ.get("integrationMethod") or "ANY"
        m = method if m == "ANY" else m
        if http_fetch is None:
            return done(_resp(502, {"message": "Bad Gateway"}))
        try:
            status, rh, rb = http_fetch(m, uri, {k: v for k, v in h2.items() if k.lower() not in ("host", "content-length")},
                                        body or b"", (integ.get("timeoutInMillis") or 30000) / 1000)
        except Exception:
            return done(_resp(502, {"message": "Bad Gateway"}))
        rh = {k: v for k, v in (rh or {}).items() if k.lower() not in ("transfer-encoding", "connection", "content-length")}
        return done(v2.ApiGwV2Response(status=status, body=rb or b"", headers=rh))
    return done(_resp(502, {"message": "Bad Gateway"}))


def _default_invoker(store):
    """Nano / fallback: run Lambda through the in-process lambda_core."""
    def run(fn, event):
        from core import lambda_core
        out = lambda_core.dispatch(store, "POST", f"/2015-03-31/functions/{fn}/invocations", {}, {},
                                   json.dumps(event).encode())
        if out.headers.get("X-Amz-Function-Error"):
            return {"_error": True}
        try:
            return json.loads(out.body.decode("utf-8"))
        except Exception:
            return None
    return run
