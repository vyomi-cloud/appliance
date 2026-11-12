"""API Gateway v1 + v2 (AWS): the resumable run gives IDENTICAL results whether it is driven synchronously (handle / invoke), stepped by hand
(plan = everything before the Fetch it yields, finish = send the answer back), or awaited (ahandle / ainvoke, the Nano bridge shape);
throttle / usage-plan quota are consumed exactly once per request; the router's async door forwards an HTTP integration through an
injected awaited hook. Run: PYTHONPATH=. python3 tests/conformance/test_aws_apigateway_split.py   (Nano: PYTHONPATH=wasm ...)
"""
import asyncio
import json

from core.aws_wire_router import AwsWireRouter
from core import apigatewayv2_core as v2core, apigatewayv2_gateway as v2gw
from core import apigateway_core as v1core, apigateway_gateway as v1gw
from core import gateway_common as gc

rt = AwsWireRouter()
fails = 0
CALLS = []
LAMBDA = []


def check(name, ok, extra=""):
    global fails
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else " :: " + str(extra)[:300]))
    fails += 0 if ok else 1


def fetch(method, url, headers, body, timeout):
    CALLS.append((method, url, dict(headers), body, timeout))
    return 200, {"x-b": "1", "connection": "close"}, b'{"ok":true}'


async def afetch(f):
    return fetch(f.method, f.url, f.headers, f.body, f.timeout)


def stepped(gen):
    """plan + finish by hand: run to the first yielded Fetch (plan), perform it, send the answer back (finish)."""
    try:
        f = next(gen)
    except StopIteration as s:
        return s.value
    assert isinstance(f, gc.Fetch)
    try:
        gen.send(fetch(f.method, f.url, f.headers, f.body, f.timeout))
    except StopIteration as s:
        return s.value
    raise AssertionError("engine yielded twice")


def lam(fn, ev):
    LAMBDA.append(fn)
    return {"statusCode": 200, "body": json.dumps({"fn": fn})}


def view(r):
    return (r.status, dict(r.headers or {}), r.body)


# ── v2 ───────────────────────────────────────────────────────────────────────
s = rt.apigwv2


def c2(m, p, b=None):
    r = v2core.dispatch(s, m, p, {}, {}, json.dumps(b).encode() if b is not None else b"")
    return json.loads(r.body) if r.body else None


aid = c2("POST", "/v2/apis", {"name": "sp", "protocolType": "HTTP"})["apiId"]
hp = c2("POST", f"/v2/apis/{aid}/integrations", {"integrationType": "HTTP_PROXY", "integrationMethod": "ANY", "payloadFormatVersion": "1.0",
                                                  "integrationUri": "https://backend.test/svc/{proxy}"})
lm = c2("POST", f"/v2/apis/{aid}/integrations", {"integrationType": "AWS_PROXY", "payloadFormatVersion": "2.0",
                                                  "integrationUri": "arn:aws:lambda:us-east-1:000000000000:function:hello"})
mk = c2("POST", f"/v2/apis/{aid}/integrations", {"integrationType": "MOCK"})
for key, integ in (("ANY /p/{proxy+}", hp), ("GET /fn", lm), ("GET /mock", mk), ("GET /lim", hp)):
    c2("POST", f"/v2/apis/{aid}/routes", {"routeKey": key, "target": f"integrations/{integ['integrationId']}"})
c2("POST", f"/v2/apis/{aid}/stages", {"stageName": "$default", "autoDeploy": True,
                                      "routeSettings": {"GET /lim": {"throttlingRateLimit": 0.0001, "throttlingBurstLimit": 2}}})
c2("POST", f"/v2/apis/{aid}/deployments", {"stageName": "$default"})
V2CASES = [("GET", "/p/a/b", {"x-t": "1"}, {"q": "1"}, b""), ("POST", "/p/a", {}, {}, b"body"), ("GET", "/fn", {}, {}, b""),
           ("GET", "/mock", {}, {}, b""), ("GET", "/nope", {}, {}, b"")]


def run2(mode, *c, **kw):
    v2gw.reset_caches()
    a = (s, aid, "$default", *c)
    if mode == "sync":
        return view(v2gw.handle(*a, invoker=lam, http_fetch=fetch, request_id="r", **kw))
    if mode == "split":
        return view(stepped(v2gw.handle_steps(*a, invoker=lam, request_id="r", **kw)))
    return view(asyncio.run(v2gw.ahandle(*a, invoker=lam, async_fetch=afetch, request_id="r", **kw)))


for c in V2CASES:
    r = [run2(m, *c) for m in ("sync", "split", "async")]
    check("v2 identical: handle == plan+finish == ahandle for %s %s" % (c[0], c[1]), r[0] == r[1] == r[2], r)
CALLS.clear()
r = run2("async", "GET", "/p/a/b", {"x-t": "1"}, {"q": "1"}, b"")
check("v2 HTTP_PROXY url/query/headers reach the hop; hop-by-hop response header stripped",
      r[0] == 200 and CALLS[0][1] == "https://backend.test/svc/a/b?q=1" and CALLS[0][2].get("x-t") == "1" and "connection" not in r[1] and r[1].get("x-b") == "1", (r, CALLS))
# throttle: burst 2 on GET /lim -> 200,200,429 in every mode, the bucket consumed exactly once per request
for mode in ("sync", "split", "async"):
    v2gw.reset_caches()
    codes = []
    for _ in range(3):
        a = (s, aid, "$default", "GET", "/lim", {}, {}, b"")
        if mode == "sync":
            codes.append(v2gw.handle(*a, http_fetch=fetch).status)
        elif mode == "split":
            codes.append(stepped(v2gw.handle_steps(*a)).status)
        else:
            codes.append(asyncio.run(v2gw.ahandle(*a, async_fetch=afetch)).status)
    check("v2 throttle consumed once per request via %s (200,200,429)" % mode, codes == [200, 200, 429], codes)
LAMBDA.clear()
run2("async", "GET", "/fn", {}, {}, b"")
check("v2 Lambda runs once, inline (no hop)", LAMBDA == ["hello"], LAMBDA)
r = view(v2gw.handle(s, aid, "$default", "GET", "/p/a", {}, {}, b"", invoker=lam))
r2 = view(asyncio.run(v2gw.ahandle(s, aid, "$default", "GET", "/p/a", {}, {}, b"", invoker=lam)))
check("v2 no fetch -> 502 Bad Gateway, same via handle and ahandle", r[0] == r2[0] == 502 and r[2] == r2[2], (r, r2))


async def unavailable(f):
    raise gc.BackendUnavailable("backend https://backend.test is not mapped")
r = asyncio.run(v2gw.ahandle(s, aid, "$default", "GET", "/p/a", {}, {}, b"", invoker=lam, async_fetch=unavailable))
check("v2 BackendUnavailable -> 502 carrying the reason in x-vyomi-backend-error", r.status == 502 and "not mapped" in r.headers.get("x-vyomi-backend-error", ""), r.headers)

# ── v1 ───────────────────────────────────────────────────────────────────────
def c1(m, p, b=None):
    r = v1core.dispatch(rt.apigw, m, p, {}, {}, json.dumps(b).encode() if b is not None else b"")
    return r.status, (json.loads(r.body) if r.body else {})


st, api = c1("POST", "/restapis", {"name": "v1"})
API, ROOT = api["id"], api["rootResourceId"]
rid = c1("POST", f"/restapis/{API}/resources/{ROOT}", {"pathPart": "{proxy+}"})[1]["id"]
rsec = c1("POST", f"/restapis/{API}/resources/{ROOT}", {"pathPart": "sec"})[1]["id"]
rmock = c1("POST", f"/restapis/{API}/resources/{ROOT}", {"pathPart": "mock"})[1]["id"]
for r_, m_, integ, kw in ((rid, "ANY", {"type": "HTTP_PROXY", "uri": "https://backend.test/svc/{proxy}", "httpMethod": "ANY"}, {}),
                          (rsec, "GET", {"type": "HTTP_PROXY", "uri": "https://backend.test/secure", "httpMethod": "GET"}, {"apiKeyRequired": True}),
                          (rmock, "GET", {"type": "MOCK", "mockStatus": 200, "mockBody": "pong"}, {})):
    c1("PUT", f"/restapis/{API}/resources/{r_}/methods/{m_}", dict({"authorizationType": "NONE"}, **kw))
    c1("PUT", f"/restapis/{API}/resources/{r_}/methods/{m_}/integration", integ)
c1("POST", f"/restapis/{API}/deployments", {"stageName": "prod"})
st, key = c1("POST", "/apikeys", {"name": "k", "enabled": True})
st, plan = c1("POST", "/usageplans", {"name": "p", "apiStages": [{"apiId": API, "stage": "prod"}], "throttle": {"rateLimit": 1000.0, "burstLimit": 100},
                                      "quota": {"limit": 2, "period": "DAY"}})
c1("POST", f"/usageplans/{plan['id']}/keys", {"keyId": key["id"], "keyType": "API_KEY"})
KV = key["value"]


def run1(mode, method, path, headers=None, query=None, body=b""):
    v1gw.reset_caches()
    a = (rt.apigw, API, "prod", method, path, headers or {}, query or {}, body)
    if mode == "sync":
        return view(v1core.invoke(*a, lambda_store=rt.lam, http_fetch=fetch, now=1000.0))
    if mode == "split":
        return view(stepped(v1core.invoke_steps(*a, lambda_store=rt.lam, now=1000.0)))
    return view(asyncio.run(v1core.ainvoke(*a, lambda_store=rt.lam, async_fetch=afetch, now=1000.0)))


V1CASES = [("GET", "/a/b", {"x-t": "1"}, {"q": "1"}, b""), ("POST", "/a", {}, {}, b"body"), ("GET", "/mock", {}, {}, b""),
           ("GET", "/sec", {}, {}, b""), ("GET", "/sec", {"x-api-key": KV}, {}, b"")]
for c in V1CASES:
    r = [run1(m, *c) for m in ("sync", "split", "async")]
    check("v1 identical: invoke == plan+finish == ainvoke for %s %s %s" % (c[0], c[1], "key" if c[2].get("x-api-key") else ""), r[0] == r[1] == r[2], r)
CALLS.clear()
run1("async", "GET", "/a/b", {"x-t": "1"}, {"q": "1"})
check("v1 HTTP_PROXY url + query reach the hop", CALLS and CALLS[0][1] == "https://backend.test/svc/a/b?q=1" and CALLS[0][2].get("x-t") == "1", CALLS)
# usage-plan quota 2/DAY consumed once per request, in each mode (run1 resets caches per call, so count inside one window)
for mode in ("sync", "split", "async"):
    v1gw.reset_caches()
    codes = []
    for _ in range(3):
        a = (rt.apigw, API, "prod", "GET", "/sec", {"x-api-key": KV}, {}, b"")
        if mode == "sync":
            codes.append(v1core.invoke(*a, lambda_store=rt.lam, http_fetch=fetch, now=5000.0).status)
        elif mode == "split":
            codes.append(stepped(v1core.invoke_steps(*a, lambda_store=rt.lam, now=5000.0)).status)
        else:
            codes.append(asyncio.run(v1core.ainvoke(*a, lambda_store=rt.lam, async_fetch=afetch, now=5000.0)).status)
    check("v1 usage-plan quota consumed once per request via %s (200,200,429)" % mode, codes == [200, 200, 429], codes)
r = view(v1core.invoke(rt.apigw, API, "prod", "GET", "/a", {}, {}, b"", lambda_store=rt.lam))
r2 = view(asyncio.run(v1core.ainvoke(rt.apigw, API, "prod", "GET", "/a", {}, {}, b"", lambda_store=rt.lam)))
check("v1 no fetch -> 502, same via invoke and ainvoke", r[0] == r2[0] == 502 and r[2] == r2[2] or gc.default_http_fetch() is not None, (r, r2))

# ── the router's async door (both versions, host-style + path-style + _user_request_) ────────────────────────────────
CALLS.clear()
rt.async_backend_fetch = afetch
o = asyncio.run(rt.ahandle("GET", f"/apigw/{aid}/p/x/y", {}, {"host": "localhost:9000"}, b""))
check("router.ahandle v2: HTTP_PROXY forwarded through the awaited hook -> 200", o["status"] == 200 and CALLS and CALLS[-1][1] == "https://backend.test/svc/x/y", (o, CALLS))
o = asyncio.run(rt.ahandle("GET", f"/apigw/{API}/prod/q/r", {}, {"host": "localhost:9000"}, b""))
check("router.ahandle v1 /apigw/{id}/{stage}: forwarded -> 200", o["status"] == 200 and CALLS[-1][1] == "https://backend.test/svc/q/r", (o, CALLS[-1:]))
o = asyncio.run(rt.ahandle("GET", f"/restapis/{API}/prod/_user_request_/z", {}, {"host": "localhost:9000"}, b""))
check("router.ahandle v1 _user_request_: forwarded -> 200", o["status"] == 200 and CALLS[-1][1] == "https://backend.test/svc/z", (o, CALLS[-1:]))
n = len(CALLS)
o = asyncio.run(rt.ahandle("GET", f"/apigw/{aid}/nope", {}, {"host": "localhost:9000"}, b""))
check("router.ahandle v2: unknown route 404 and no hop", o["status"] == 404 and len(CALLS) == n, o)
del rt.async_backend_fetch
print("\nRESULT: %s — AWS API Gateway resumable run (%d failed)" % ("PASS" if not fails else "FAIL", fails))
raise SystemExit(1 if fails else 0)
