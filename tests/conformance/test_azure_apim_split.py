"""Azure APIM gateway: the resumable run gives IDENTICAL results whether driven synchronously (handle), stepped by hand (plan = everything
before the Fetch it yields, finish = send the answer back) or awaited (ahandle, the Nano bridge shape); subscription / rate-limit counters
are consumed exactly once per request; the router's async door forwards through an injected awaited hook and keeps `vyomi-site://`
backends in-process. Also: validate-jwt RS256 goes through the shared verifier when one exists.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_apim_split.py   (Nano: PYTHONPATH=wasm ...)
"""
import asyncio
import json

from core.aws_wire_router import AwsWireRouter
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
from core import azure_apim_gateway_core as gw
from core import gateway_common as gc

AzureArm.STRICT_SUBSCRIPTION = False
fails = 0
CALLS = []


def check(name, ok, extra=""):
    global fails
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else " :: " + str(extra)[:300]))
    fails += 0 if ok else 1


rt = AwsWireRouter()
a = rt.az_arm
Q = {"api-version": "2022-08-01"}
S = f"/subscriptions/{SUB}/resourceGroups/sp-rg"
base = "/providers/Microsoft.ApiManagement/service/spsvc"
put = lambda p, b: a.handle("PUT", S + p, Q, b)
pol = lambda inbound="": {"properties": {"format": "xml", "value": f"<policies><inbound><base />{inbound}</inbound><backend><base /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>"}}
put("", {"location": "eastus"})
put(base, {"location": "eastus", "sku": {"name": "Developer", "capacity": 1}, "properties": {"publisherEmail": "a@b.c", "publisherName": "x"}})
put(base + "/apis/echo", {"properties": {"displayName": "Echo", "path": "echo", "serviceUrl": "https://backend.test/base", "protocols": ["https"], "subscriptionRequired": True}})
put(base + "/apis/site", {"properties": {"displayName": "Site", "path": "site", "serviceUrl": "vyomi-site://nosuchapp", "subscriptionRequired": False}})
put(base + "/apis/echo/operations/get1", {"properties": {"displayName": "g", "method": "GET", "urlTemplate": "/r/{id}"}})
put(base + "/apis/echo/operations/post1", {"properties": {"displayName": "p", "method": "POST", "urlTemplate": "/w"}})
put(base + "/apis/site/operations/g", {"properties": {"displayName": "g", "method": "GET", "urlTemplate": "/x"}})
put(base + "/apis/echo/operations/mock", {"properties": {"displayName": "m", "method": "GET", "urlTemplate": "/mock",
    "responses": [{"statusCode": 200, "representations": [{"contentType": "application/json", "sample": '{"hello":"mock"}'}]}]}})
put(base + "/subscriptions/s1", {"properties": {"scope": f"{S}{base}/apis", "displayName": "s1"}})
svc = gw.find_service(a.state, "spsvc")
KEY = a.handle("POST", S + base + "/subscriptions/s1/listSecrets", Q)["body"]["primaryKey"]
K = {"Ocp-Apim-Subscription-Key": KEY}


def fetch(m, url, h, d):
    CALLS.append((m, url, dict(h), d))
    return 200, {"content-type": "application/json", "x-backend": "1", "connection": "close"}, b'{"ok":true}'


async def afetch(f):
    return fetch(f.method, f.url, f.headers, f.body)


def stepped(gen):
    try:
        f = next(gen)
    except StopIteration as s:
        return s.value
    assert isinstance(f, gc.Fetch)
    try:
        gen.send(fetch(f.method, f.url, f.headers, f.body))
    except StopIteration as s:
        return s.value
    raise AssertionError("engine yielded twice")


def view(r):
    h = {k: v for k, v in r["headers"].items() if k != "x-vyomi-apim-request-id"}
    return (r["status"], h, r["body"])


def mode(m, method, path, headers=None, query=None, body=b"", now=1000.0):
    args = (a.state, svc, method, path, query or {}, headers or {}, body)
    if m == "sync":
        return view(gw.handle(*args, fetch=fetch, now=now))
    if m == "split":
        return view(stepped(gw.handle_steps(*args, now=now)))
    return view(asyncio.run(gw.ahandle(*args, async_fetch=afetch, now=now)))


CASES = [("GET", "/echo/r/7", K, {}, b""), ("GET", "/echo/r/7", {}, {}, b""), ("GET", "/echo/r/7", {"Ocp-Apim-Subscription-Key": "bad"}, {}, b""),
         ("POST", "/echo/w", dict(K, **{"X-T": "1"}), {"a": "b"}, b"data"), ("GET", "/echo/mock", K, {}, b""), ("GET", "/echo/zzz", K, {}, b""),
         ("GET", "/nope/x", {}, {}, b"")]
for c in CASES:
    r = [mode(m, c[0], c[1], c[2], c[3], c[4]) for m in ("sync", "split", "async")]
    check("identical: handle == plan+finish == ahandle for %s %s" % (c[0], c[1]), r[0] == r[1] == r[2], r)
CALLS.clear()
r = mode("async", "POST", "/echo/w", dict(K, **{"X-T": "1"}), {"a": "b"}, b"data")
check("url + body + headers reach the hop; subscription key and hop-by-hop headers stripped",
      CALLS and CALLS[0][1] == "https://backend.test/base/w?a=b" and CALLS[0][3] == b"data" and CALLS[0][2].get("x-t") == "1"
      and not any(k.lower() == "ocp-apim-subscription-key" for k in CALLS[0][2]) and "connection" not in r[1], (r, CALLS))

# rate-limit 2/60s: counted once per request in every driver
put(base + "/apis/echo/operations/get1/policies/policy", pol('<rate-limit calls="2" renewal-period="60" />'))
for m in ("sync", "split", "async"):
    svc["_gw"]["rl"].clear()
    codes = [mode(m, "GET", "/echo/r/1", K, now=2000.0)[0] for _ in range(3)]
    check("rate-limit consumed once per request via %s (200,200,429)" % m, codes == [200, 200, 429], codes)
svc["_gw"]["rl"].clear()
put(base + "/apis/echo/operations/get1/policies/policy", pol(""))

r = mode("sync", "GET", "/echo/r/1", K)
nofetch = view(gw.handle(a.state, svc, "GET", "/echo/r/1", {}, K, b"", now=1000.0))
nofetch_a = view(asyncio.run(gw.ahandle(a.state, svc, "GET", "/echo/r/1", {}, K, b"", now=1000.0)))
check("no fetch -> 502 'no outbound network', same via handle and ahandle", nofetch[0] == nofetch_a[0] == 502 and nofetch[2] == nofetch_a[2], (nofetch, nofetch_a))


async def unavailable(f):
    raise gc.BackendUnavailable("backend https://backend.test is not mapped")
r = view(asyncio.run(gw.ahandle(a.state, svc, "GET", "/echo/r/1", {}, K, b"", async_fetch=unavailable, now=1000.0)))
check("BackendUnavailable -> 502 carrying the reason", r[0] == 502 and b"not mapped" in r[2], r)

# the router's async door
CALLS.clear()
rt.async_backend_fetch = afetch
H = dict(K, host="localhost:9000")
o = asyncio.run(rt.ahandle("GET", "/azure-data/apim/spsvc/echo/r/9", {}, H, b""))
check("router.ahandle: /azure-data/apim/{svc}/... forwarded through the awaited hook -> 200", o["status"] == 200 and CALLS and CALLS[-1][1] == "https://backend.test/base/r/9", (o, CALLS))
n = len(CALLS)
o = asyncio.run(rt.ahandle("GET", "/azure-data/apim/spsvc/echo/r/9", {}, {"host": "localhost:9000"}, b""))
check("router.ahandle: missing subscription key 401 before any hop", o["status"] == 401 and len(CALLS) == n, o)
o = asyncio.run(rt.ahandle("GET", "/azure-data/apim/spsvc/site/x", {}, {"host": "localhost:9000"}, b""))
check("router.ahandle: vyomi-site:// backend stays in-process (404 app, hook not called)", o["status"] == 502 and len(CALLS) == n and b"not found" in o["body"], o)
o = asyncio.run(rt.ahandle("GET", "/azure-data/apim/missing/echo/r/9", {}, H, b""))
check("router.ahandle: unknown service -> 404 (sync branch)", o["status"] == 404, o)
del rt.async_backend_fetch

# validate-jwt RS256 through the shared verifier
import base64, time
b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
tok = "%s.%s.%s" % (b64({"alg": "RS256", "kid": "k"}), b64({"iss": "https://iss.test", "exp": time.time() + 600}), "sig")
put(base + "/apis/echo/operations/get1/policies/policy",
    pol('<validate-jwt header-name="Authorization"><openid-config url="https://iss.test/.well-known/openid-configuration" /><issuers><issuer>https://iss.test</issuer></issuers></validate-jwt>'))
gw._rs256_verifier = lambda: (lambda t, h, cfg: cfg["issuer"] == "https://iss.test" and t.endswith(".good"))
bad = view(gw.handle(a.state, svc, "GET", "/echo/r/1", {}, dict(K, Authorization="Bearer " + tok), b"", fetch=fetch, now=1000.0))
good = view(gw.handle(a.state, svc, "GET", "/echo/r/1", {}, dict(K, Authorization="Bearer " + tok[:-3] + "good"), b"", fetch=fetch, now=1000.0))
check("RS256 with a verifier: bad signature -> 401, good -> 200 and no unverified warning", bad[0] == 401 and good[0] == 200 and "x-vyomi-apim-warning" not in good[1], (bad, good))
gw._rs256_verifier = lambda: None
nov = view(gw.handle(a.state, svc, "GET", "/echo/r/1", {}, dict(K, Authorization="Bearer " + tok), b"", fetch=fetch, now=1000.0))
check("RS256 with no verifier (Nano): claims-only + jwt-signature-unverified warning (unchanged)", nov[0] == 200 and nov[1].get("x-vyomi-apim-warning") == "jwt-signature-unverified", nov)
print("\nRESULT: %s — APIM resumable run (%d failed)" % ("PASS" if not fails else "FAIL", fails))
raise SystemExit(1 if fails else 0)
