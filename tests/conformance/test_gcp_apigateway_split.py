"""API Gateway (GCP): the plan()/finish() split gives IDENTICAL results to handle(), quota is counted once, and the router's async
hop (ahandle -> awaited backend hook, the Nano bridge shape) serves the same answers.
Run: PYTHONPATH=. python3 tests/conformance/test_gcp_apigateway_split.py   (Nano: PYTHONPATH=wasm ...)
"""
import asyncio
import base64
import json

from core.aws_wire_router import AwsWireRouter
from core import gcp_apigateway_gateway as gw

P = "/v1/projects/nano-project/locations"
rt = AwsWireRouter()
fails = 0
CALLS = []


def check(name, ok, extra=""):
    global fails
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else " :: " + str(extra)[:240]))
    fails += 0 if ok else 1


def call(m, p, b=None, q=None):
    o = rt.handle(m, p, q or {}, {"content-type": "application/json"}, json.dumps(b).encode() if b is not None else b"")
    return o["status"], json.loads(o["body"] or b"{}")


SPEC = {"swagger": "2.0", "info": {"title": "t", "version": "1"},
        "securityDefinitions": {"key": {"type": "apiKey", "name": "key", "in": "query"}},
        "x-google-management": {"metrics": [{"name": "reads", "valueType": "INT64", "metricKind": "DELTA"}],
                                "quota": {"limits": [{"name": "rl", "metric": "reads", "unit": "1/min/{project}", "values": {"STANDARD": 2}}]}},
        "x-google-backend": {"address": "https://backend.test", "path_translation": "APPEND_PATH_TO_ADDRESS", "deadline": 7},
        "paths": {"/open": {"get": {"operationId": "open", "responses": {"200": {"description": "ok"}}}},
                  "/items/{id}": {"get": {"operationId": "item", "security": [{"key": []}], "x-google-quota": {"metricCosts": {"reads": 1}}, "responses": {"200": {"description": "ok"}}}}}}
call("POST", P + "/global/apis", {}, {"apiId": "sp"})
call("POST", P + "/global/apis/sp/configs", {"openapiDocuments": [{"document": {"path": "o.json", "contents": base64.b64encode(json.dumps(SPEC).encode()).decode()}}]}, {"apiConfigId": "c1"})
call("POST", P + "/us-central1/gateways", {"apiConfig": "projects/nano-project/locations/global/apis/sp/configs/c1"}, {"gatewayId": "gw1"})
call("POST", "/v2/projects/nano-project/locations/global/keys", {"displayName": "k"}, {"keyId": "k1"})
KEY = call("GET", "/v2/projects/nano-project/locations/global/keys/k1/keyString")[1]["keyString"]
G = gw.find_gateway(rt.gcp_mon, "", "gw1")


def fetch(method, url, headers, body, timeout):
    CALLS.append((method, url, dict(headers), body, timeout))
    return 200, {"x-b": "1", "connection": "close"}, b'{"ok":true}'


async def afetch(fwd):
    return fetch(fwd.method, fwd.url, fwd.headers, fwd.body, fwd.timeout)


def view(r):
    return (r.status, dict(r.headers), r.body)


def sync(*a, **k):
    gw.reset_caches(); return view(gw.handle(rt.gcp_mon, G, *a, http_fetch=fetch, now=1000.0, **k))


def split(*a, **k):
    gw.reset_caches()
    f = gw.plan(rt.gcp_mon, G, *a, now=1000.0, **k)
    if not isinstance(f, gw.Forward):
        return view(f)
    return view(gw.finish(f, *fetch(f.method, f.url, f.headers, f.body, f.timeout)))


def asyn(*a, **k):
    gw.reset_caches(); return view(asyncio.run(gw.ahandle(rt.gcp_mon, G, *a, async_fetch=afetch, now=1000.0, **k)))


CASES = [("GET", "/open", {}, {}, b""), ("GET", "/nope", {}, {}, b""), ("GET", "/items/7", {}, {}, b""),
         ("GET", "/items/7", {}, {"key": "bogus"}, b""), ("GET", "/items/7", {}, {"key": KEY}, b""),
         ("GET", "/items/7", {"X-Test": "1", "Connection": "x"}, {"key": KEY, "a": "b"}, b""), ("POST", "/open", {}, {}, b"x")]
for c in CASES:
    s, p, a = sync(*c), split(*c), asyn(*c)
    check("identical: handle == plan+finish == ahandle for %s %s %s" % (c[0], c[1], c[3]), s == p == a, (s, p, a))

# quota counted ONCE per request through every path: limit 2 -> 3rd is 429, in each path
for name, fn in (("handle", lambda: gw.handle(rt.gcp_mon, G, "GET", "/items/1", {}, {"key": KEY}, http_fetch=fetch, now=2000.0)),
                 ("plan+finish", lambda: (lambda f: f if not isinstance(f, gw.Forward) else gw.finish(f, *fetch(f.method, f.url, f.headers, f.body, f.timeout)))(
                     gw.plan(rt.gcp_mon, G, "GET", "/items/1", {}, {"key": KEY}, now=2000.0))),
                 ("ahandle", lambda: asyncio.run(gw.ahandle(rt.gcp_mon, G, "GET", "/items/1", {}, {"key": KEY}, async_fetch=afetch, now=2000.0)))):
    gw.reset_caches()
    codes = [fn().status for _ in range(3)]
    check("quota counted once per request via %s (200,200,429)" % name, codes == [200, 200, 429], codes)

f = gw.plan(rt.gcp_mon, G, "GET", "/open", {"x": "y"}, {}, now=1.0)
check("plan returns a Forward with url/deadline and no I/O", isinstance(f, gw.Forward) and f.url == "https://backend.test/open" and f.timeout == 7.0, getattr(f, "url", f))
check("plan 404 / 401 are final responses (no Forward)", not isinstance(gw.plan(rt.gcp_mon, G, "GET", "/nope"), gw.Forward) and gw.plan(rt.gcp_mon, G, "GET", "/items/1").status == 401)


def raiser(fwd):
    async def a(_):
        raise gw.BackendUnavailable("backend https://backend.test is not mapped")
    return a
r = asyncio.run(gw.ahandle(rt.gcp_mon, G, "GET", "/open", async_fetch=raiser(None), now=1.0))
check("BackendUnavailable -> 503 carrying the reason", r.status == 503 and b"not mapped" in r.body, r.body)
r = asyncio.run(gw.ahandle(rt.gcp_mon, G, "GET", "/open", async_fetch=None, now=1.0))
check("no hook -> 503 'cannot be reached from this runtime' (as handle() with no fetch)", r.status == 503 and gw.NO_RUNTIME_MSG.encode()[:20] in r.body.replace(b'\\', b''), r.body)
r2 = gw.handle(rt.gcp_mon, G, "GET", "/open", now=1.0)
check("handle with no http_fetch unchanged (503, same body)", r.status == r2.status == 503 and r.body == r2.body)

# the router's async door
CALLS.clear()
rt.async_backend_fetch = afetch
o = asyncio.run(rt.ahandle("GET", "/gcpgw/gw1/open", {}, {"accept": "*/*"}, b""))
check("router.ahandle: /gcpgw/{id}/open reaches the awaited backend hook -> 200", o["status"] == 200 and o["body"] == b'{"ok":true}' and len(CALLS) == 1 and CALLS[0][1] == "https://backend.test/open", (o, CALLS))
check("router.ahandle: hop-by-hop response header stripped", "connection" not in {k.lower() for k in o["headers"]} and o["headers"].get("x-b") == "1", o["headers"])
o = asyncio.run(rt.ahandle("GET", "/gcpgw/gw1/items/1", {}, {}, b""))
check("router.ahandle: auth still enforced before any backend call (401)", o["status"] == 401 and len(CALLS) == 1, o)
o = asyncio.run(rt.ahandle("GET", "/gcpgw/missing/x", {}, {}, b""))
check("router.ahandle: unknown gateway 404", o["status"] == 404)
_gwrec = [e for e in rt.obs.recent if e[2] == "gcp-gateway-invoke"]
check("router.ahandle: gateway requests are recorded in the request telemetry (like handle())", len(_gwrec) >= 3 and {e[5] for e in _gwrec} >= {200, 401, 404}, _gwrec[-3:])
del rt.async_backend_fetch
print("\nRESULT: %s — plan/finish split (%d failed)" % ("PASS" if not fails else "FAIL", fails))
raise SystemExit(1 if fails else 0)
