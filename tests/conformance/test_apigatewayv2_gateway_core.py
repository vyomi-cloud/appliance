"""API Gateway V2 data plane (core/apigatewayv2_gateway.py): Lambda proxy 1.0/2.0, JWT and
Lambda REQUEST authorizers, throttling, CORS, parameter mapping, HTTP proxy, Caddy route table."""
import base64
import json
import time

try:
    from core import apigatewayv2_core as core, apigatewayv2_gateway as gw
except ImportError:  # pragma: no cover - Pyodide flat layout
    import apigatewayv2_core as core  # type: ignore
    import apigatewayv2_gateway as gw  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def _jwt(**claims):
    return f"{_b64({'alg': 'RS256', 'kid': 'k'})}.{_b64(claims)}.sig"


def run():
    gw.reset_caches()
    s = core.ApiGwV2Store()

    def call(m, p, b=None):
        r = core.dispatch(s, m, p, {}, {}, json.dumps(b).encode() if b is not None else b"")
        return json.loads(r.body) if r.body else None

    seen = []

    def invoker(fn, ev):
        seen.append((fn, ev))
        if fn == "authz":
            return {"isAuthorized": ev["headers"].get("x-key") == "good", "context": {"user": "u1"}}
        return {"statusCode": 200, "headers": {"x-fn": fn}, "body": json.dumps({"route": ev.get("routeKey") or ev.get("resource")})}

    api = call("POST", "/v2/apis", {"name": "gw", "protocolType": "HTTP",
                                    "corsConfiguration": {"allowOrigins": ["https://app.example"], "allowMethods": ["GET"], "maxAge": 60}})
    aid = api["apiId"]
    lam = call("POST", f"/v2/apis/{aid}/integrations", {"integrationType": "AWS_PROXY", "payloadFormatVersion": "2.0",
                                                      "integrationUri": "arn:aws:lambda:us-east-1:000000000000:function:hello"})
    lam1 = call("POST", f"/v2/apis/{aid}/integrations", {"integrationType": "AWS_PROXY", "payloadFormatVersion": "1.0",
                                                       "integrationUri": "arn:aws:lambda:us-east-1:000000000000:function:old"})
    jwt = call("POST", f"/v2/apis/{aid}/authorizers", {"name": "j", "authorizerType": "JWT", "identitySource": ["$request.header.Authorization"],
                                                      "jwtConfiguration": {"audience": ["app"], "issuer": "https://iss"}})
    req = call("POST", f"/v2/apis/{aid}/authorizers", {"name": "r", "authorizerType": "REQUEST", "authorizerUri": "arn:aws:lambda:x:y:function:authz",
                                                      "identitySource": ["$request.header.x-key"], "authorizerPayloadFormatVersion": "2.0",
                                                      "enableSimpleResponses": True, "authorizerResultTtlInSeconds": 0})
    for key, integ, extra in (("GET /hello", lam, {}), ("GET /old/{id}", lam1, {}),
                              ("GET /secure", lam, {"authorizationType": "JWT", "authorizerId": jwt["authorizerId"], "authorizationScopes": ["read"]}),
                              ("GET /custom", lam, {"authorizationType": "CUSTOM", "authorizerId": req["authorizerId"]}),
                              ("GET /slow", lam, {})):
        call("POST", f"/v2/apis/{aid}/routes", {"routeKey": key, "target": f"integrations/{integ['integrationId']}", **extra})
    call("POST", f"/v2/apis/{aid}/stages", {"stageName": "$default", "autoDeploy": True})
    call("POST", f"/v2/apis/{aid}/deployments", {"stageName": "$default"})

    def hit(path, method="GET", headers=None, **kw):
        return gw.handle(s, aid, "$default", method, path, headers or {}, {}, b"", invoker=invoker,
                         verify_sig=kw.pop("verify_sig", lambda *a: True), **kw)

    r = hit("/hello")
    _check("Lambda proxy 2.0 → 200 + function headers", r.status == 200 and r.headers["x-fn"] == "hello")
    _check("payload 2.0 event shape", seen[-1][1]["version"] == "2.0" and seen[-1][1]["requestContext"]["http"]["method"] == "GET")
    r = hit("/old/42")
    _check("Lambda proxy 1.0 event + pathParameters", seen[-1][1]["version"] == "1.0" and seen[-1][1]["pathParameters"] == {"id": "42"}
           and seen[-1][1]["httpMethod"] == "GET" and r.status == 200)
    _check("unknown route → 404", hit("/nope").status == 404)

    # CORS
    pre = hit("/hello", "OPTIONS", {"Origin": "https://app.example", "Access-Control-Request-Method": "GET"})
    _check("CORS preflight 204 + allow-origin/methods/max-age", pre.status == 204 and pre.headers["access-control-allow-origin"] == "https://app.example"
           and pre.headers["access-control-allow-methods"] == "GET" and pre.headers["access-control-max-age"] == "60")
    _check("CORS header on real responses", hit("/hello", headers={"Origin": "https://app.example"}).headers.get("access-control-allow-origin"))
    _check("CORS: unlisted origin gets no allow-origin", "access-control-allow-origin" not in hit("/hello", headers={"Origin": "https://evil"}).headers)

    # JWT authorizer
    ok = _jwt(iss="https://iss", aud="app", exp=time.time() + 60, scope="read write", sub="u")
    _check("JWT: missing token → 401", hit("/secure").status == 401)
    _check("JWT: garbage token → 401", hit("/secure", headers={"Authorization": "Bearer nope"}).status == 401)
    _check("JWT: wrong issuer → 401", hit("/secure", headers={"Authorization": "Bearer " + _jwt(iss="https://other", aud="app", exp=time.time() + 60, scope="read")}).status == 401)
    _check("JWT: expired → 401", hit("/secure", headers={"Authorization": "Bearer " + _jwt(iss="https://iss", aud="app", exp=time.time() - 5, scope="read")}).status == 401)
    _check("JWT: bad signature → 401", hit("/secure", headers={"Authorization": "Bearer " + ok}, verify_sig=lambda *a: False).status == 401)
    _check("JWT: missing scope → 403", hit("/secure", headers={"Authorization": "Bearer " + _jwt(iss="https://iss", aud="app", exp=time.time() + 60, scope="write")}).status == 403)
    r = hit("/secure", headers={"Authorization": "Bearer " + ok})
    _check("JWT: good token → 200 with claims in requestContext", r.status == 200
           and seen[-1][1]["requestContext"]["authorizer"]["jwt"]["claims"]["sub"] == "u")

    # Lambda REQUEST authorizer
    _check("REQUEST authorizer: no identity → 401", hit("/custom").status == 401)
    _check("REQUEST authorizer: deny → 403", hit("/custom", headers={"x-key": "bad"}).status == 403)
    r = hit("/custom", headers={"x-key": "good"})
    _check("REQUEST authorizer: allow → 200 + context", r.status == 200 and seen[-1][1]["requestContext"]["authorizer"]["lambda"] == {"user": "u1"})

    # throttling: 1 rps / burst 1 → second immediate call is 429
    stg = call("GET", f"/v2/apis/{aid}/stages/$default")
    call("PATCH", f"/v2/apis/{aid}/stages/$default", {"routeSettings": {"GET /slow": {"throttlingRateLimit": 1, "throttlingBurstLimit": 1}}})
    a, b = hit("/slow").status, hit("/slow").status
    _check("throttle 1 rps: first 200, second 429", (a, b) == (200, 429))

    # HTTP proxy + parameter mapping
    http = call("POST", f"/v2/apis/{aid}/integrations", {"integrationType": "HTTP_PROXY", "integrationMethod": "ANY", "payloadFormatVersion": "1.0",
                                                       "integrationUri": "http://backend.test/{proxy}",
                                                       "requestParameters": {"overwrite:header.x-tenant": "$context.apiId"}})
    call("POST", f"/v2/apis/{aid}/routes", {"routeKey": "ANY /p/{proxy+}", "target": f"integrations/{http['integrationId']}"})
    got = {}

    def fetch(m, url, h, body, t):
        got.update(m=m, url=url, h=h)
        return 201, {"x-up": "1"}, b"up"
    r = gw.handle(s, aid, "$default", "POST", "/p/a/b", {}, {"q": "1"}, b"x", invoker=invoker, http_fetch=fetch)
    _check("HTTP proxy forwards method/path/query + mapped header", r.status == 201 and r.body == b"up"
           and got["m"] == "POST" and got["url"] == "http://backend.test/a/b?q=1" and got["h"]["x-tenant"] == aid)

    # Caddy route table: live per-API host routing, named stages and $default
    call("POST", f"/v2/apis/{aid}/stages", {"stageName": "prod"})
    cfg = gw.caddy_config(s)
    routes = cfg["apps"]["http"]["servers"]["apigw"]["routes"]
    _check("Caddy config: host route per API → reverse_proxy to the handler",
           routes[0]["match"][0]["host"] == [f"{aid}.execute-api.localhost"] and "reverse_proxy" in json.dumps(routes[0]))
    _check("Caddy config: TLS server + internal issuer for the API host", "apigws" in cfg["apps"]["http"]["servers"]
           and cfg["apps"]["tls"]["automation"]["policies"][0]["subjects"] == [f"{aid}.execute-api.localhost"])
    _check("invoke URL", gw.invoke_url(api, "prod") == f"https://{aid}.execute-api.localhost:9443/prod")
    seen_cb = []
    core.CHANGE_LISTENERS.append(seen_cb.append)
    call("POST", f"/v2/apis/{aid}/routes", {"routeKey": "GET /late", "target": f"integrations/{lam['integrationId']}"})
    core.CHANGE_LISTENERS.clear()
    _check("route added after deployment fires the live-sync hook and is reachable", seen_cb and hit("/late").status == 200)


if __name__ == "__main__":
    run()
    print("apigatewayv2 gateway: all checks passed")
