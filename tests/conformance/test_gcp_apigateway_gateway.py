"""API Gateway (GCP) DATA PLANE on the shared gateway engine: routing, API-key + JWT auth, quota, real backend forwarding.

The backend is a REAL local HTTP server (loopback http:// — the control plane only accepts https addresses, so the test seeds the
backend through an https-looking address and rewrites it in http_fetch to the loopback port).
Run on host:  PYTHONPATH=. python3 tests/conformance/test_gcp_apigateway_gateway.py
"""
import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from core.aws_wire_router import AwsWireRouter
from core import gcp_apigateway_gateway as gw

P = "/v1/projects/nano-project/locations"
rt = AwsWireRouter()
fails = 0
SEEN = []


class H(BaseHTTPRequestHandler):
    def _go(self):
        n = int(self.headers.get("content-length") or 0)
        SEEN.append((self.command, self.path, dict(self.headers), self.rfile.read(n)))
        b = json.dumps({"hit": self.path}).encode()
        self.send_response(201 if self.command == "POST" else 200)
        self.send_header("content-type", "application/json"); self.send_header("x-backend", "real"); self.send_header("content-length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    do_GET = do_POST = do_PUT = _go
    def log_message(self, *a): pass


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]


def fetch(method, url, headers, body, timeout):   # https://backend.test -> the loopback server
    import urllib.request, urllib.error
    url = url.replace("https://backend.test", "http://127.0.0.1:%d" % PORT)
    req = urllib.request.Request(url, data=body or None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def call(m, p, b=None, q=None, h=None):
    o = rt.handle(m, p, q or {}, {"content-type": "application/json", **(h or {})}, json.dumps(b).encode() if b is not None else b"")
    try:
        return o["status"], json.loads(o["body"] or b"{}"), o
    except ValueError:
        return o["status"], o["body"].decode(), o


def check(name, ok, extra=""):
    global fails
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else " :: " + str(extra)[:240]))
    fails += 0 if ok else 1


def b64u(d): return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
def jwt(claims): return "%s.%s.%s" % (b64u({"alg": "RS256", "kid": "k1"}), b64u(claims), "c2ln")


SPEC = {"swagger": "2.0", "info": {"title": "t", "version": "1"},
        "securityDefinitions": {"key": {"type": "apiKey", "name": "key", "in": "query"},
                                "jwt": {"type": "oauth2", "x-google-issuer": "https://iss.test", "x-google-jwks_uri": "https://iss.test/jwks", "x-google-audiences": "my-aud"}},
        "x-google-management": {"metrics": [{"name": "reads", "valueType": "INT64", "metricKind": "DELTA"}],
                                "quota": {"limits": [{"name": "rl", "metric": "reads", "unit": "1/min/{project}", "values": {"STANDARD": 3}}]}},
        "x-google-backend": {"address": "https://backend.test", "path_translation": "APPEND_PATH_TO_ADDRESS"},
        "paths": {"/open": {"get": {"operationId": "open", "responses": {"200": {"description": "ok"}}}},
                  "/items/{id}": {"get": {"operationId": "item", "security": [{"key": []}], "x-google-quota": {"metricCosts": {"reads": 1}}, "responses": {"200": {"description": "ok"}}}},
                  "/secure": {"post": {"operationId": "secure", "security": [{"jwt": []}], "responses": {"200": {"description": "ok"}}}},
                  "/const": {"get": {"operationId": "const", "x-google-backend": {"address": "https://backend.test/fixed", "path_translation": "CONSTANT_ADDRESS"}, "responses": {"200": {"description": "ok"}}}}}}
call("POST", P + "/global/apis", {}, {"apiId": "gwapi"})
st, r, _ = call("POST", P + "/global/apis/gwapi/configs", {"openapiDocuments": [{"document": {"path": "o.json", "contents": base64.b64encode(json.dumps(SPEC).encode()).decode()}}]}, {"apiConfigId": "c1"})
check("config with security + quota + backend accepted", st == 200, r)
CFG = "projects/nano-project/locations/global/apis/gwapi/configs/c1"
st, r, _ = call("POST", P + "/us-central1/gateways", {"apiConfig": CFG}, {"gatewayId": "gw1"})
HOST = r["response"]["defaultHostname"]
st, k, _ = call("POST", "/v2/projects/nano-project/locations/global/keys", {"displayName": "k"}, {"keyId": "k1"})
check("API Keys: create returns an LRO with the key", st == 200 and k["done"] and k["response"]["name"].endswith("/keys/k1"), k)
KEY = call("GET", "/v2/projects/nano-project/locations/global/keys/k1/keyString")[1]["keyString"]
check("API Keys: keyString is retrievable, not in get/list", KEY.startswith("AIza") and "keyString" not in call("GET", "/v2/projects/nano-project/locations/global/keys/k1")[1])

g = call("GET", P + "/us-central1/gateways/gw1")[1]
V = lambda t, claims=None: (lambda *a, **k: True)
def hit(method, path, headers=None, query=None, body=b"", verify=V(0)):
    return gw.handle(rt.gcp_mon, g, method, path, headers, query, body, http_fetch=fetch, verify_sig=verify)

gw.reset_caches()
r = hit("GET", "/open")
check("open route is forwarded to the REAL backend", r.status == 200 and json.loads(r.body)["hit"] == "/open" and r.headers.get("x-backend") == "real", (r.status, r.body))
check("no route -> 404 'not defined by this API'", hit("GET", "/nope").status == 404 and b"not defined" in hit("GET", "/nope").body)
r = hit("GET", "/items/7")
check("apiKey route without a key -> 401 unregistered callers", r.status == 401 and b"unregistered callers" in r.body, r.body)
r = hit("GET", "/items/7", query={"key": "AIzaWRONG"})
check("wrong key -> 400 API key not valid", r.status == 400 and b"API key not valid" in r.body, r.body)
SEEN.clear()
r = hit("GET", "/items/7", query={"key": KEY, "x": "1"})
check("valid key forwards, path appended, key stripped from the backend query", r.status == 200 and SEEN and SEEN[0][1] == "/items/7?x=1", SEEN)
r = hit("GET", "/const", query={"a": "1"})
check("CONSTANT_ADDRESS keeps the backend path", json.loads(r.body)["hit"] == "/fixed?a=1", r.body)
r = hit("GET", "/items/8", query={"key": KEY})
r = hit("GET", "/items/9", query={"key": KEY})
r = hit("GET", "/items/10", query={"key": KEY})
check("quota: 4th call in the minute -> 429 RESOURCE_EXHAUSTED + retry-after", r.status == 429 and b"RESOURCE_EXHAUSTED" in r.body and "retry-after" in r.headers, (r.status, r.body))
r = gw.handle(rt.gcp_mon, g, "GET", "/items/11", {}, {"key": KEY}, b"", http_fetch=fetch, verify_sig=V(0), now=time.time() + 61)
check("quota window resets after a minute", r.status == 200, r.status)
r = hit("POST", "/secure")
check("jwt route without a token -> 401 Jwt is missing", r.status == 401 and b"Jwt is missing" in r.body)
ok_claims = {"iss": "https://iss.test", "aud": "my-aud", "sub": "u1", "exp": time.time() + 600}
SEEN.clear()
r = hit("POST", "/secure", headers={"Authorization": "Bearer " + jwt(ok_claims)}, body=b'{"a":1}')
ui = SEEN and {k.lower(): v for k, v in SEEN[0][2].items()}.get("x-endpoint-api-userinfo")
check("valid JWT forwards (201 from backend) with x-endpoint-api-userinfo", r.status == 201 and ui and json.loads(base64.urlsafe_b64decode(ui + "=="))["sub"] == "u1", (r.status, SEEN))
check("JWT with wrong issuer -> 401", hit("POST", "/secure", headers={"Authorization": "Bearer " + jwt({**ok_claims, "iss": "https://evil"})}).status == 401)
check("JWT with wrong audience -> 401", hit("POST", "/secure", headers={"Authorization": "Bearer " + jwt({**ok_claims, "aud": "other"})}).status == 401)
check("expired JWT -> 401", hit("POST", "/secure", headers={"Authorization": "Bearer " + jwt({**ok_claims, "exp": time.time() - 5})}).status == 401)
check("JWT whose signature fails -> 401", hit("POST", "/secure", headers={"Authorization": "Bearer " + jwt(ok_claims)}, verify=lambda *a: False).status == 401)
check("JWT with NO verifier available fails closed", gw.handle(rt.gcp_mon, g, "POST", "/secure", {"Authorization": "Bearer " + jwt(ok_claims)}, {}, b"", http_fetch=fetch, verify_sig=None).status == 401)
r = gw.handle(rt.gcp_mon, g, "GET", "/open", {}, {}, b"", http_fetch=None)
check("no outbound network (Nano) -> 503 UNAVAILABLE, not a fake 200", r.status == 503 and b"UNAVAILABLE" in r.body)

# through the router: host-style and path-style invoke
o = rt.handle("GET", "/open", {}, {"host": HOST}, b"")
check("router: Host *.gateway.dev reaches the gateway (no network in test runtime may 503/200, never 404 'no gateway')", b"No gateway" not in o["body"], o)
o = rt.handle("GET", "/gcpgw/gw1/nope", {}, {"host": "localhost:9000"}, b"")
check("router: path-style /gcpgw/{id}/... routes + 404s per the API", o["status"] == 404 and b"not defined" in o["body"], o)
o = rt.handle("GET", "/gcpgw/ghost/x", {}, {"host": "localhost:9000"}, b"")
check("router: unknown gateway -> 404", o["status"] == 404 and b"No gateway" in o["body"], o)
print("\nRESULT: " + ("PASS" if not fails else "FAIL") + f" — API Gateway data plane ({fails} failed)")
raise SystemExit(1 if fails else 0)
