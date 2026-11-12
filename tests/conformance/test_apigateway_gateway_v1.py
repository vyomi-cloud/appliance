"""API Gateway v1 (REST) DATA PLANE through the wire router, on the shared gateway primitives (core/gateway_common).

A real local HTTP backend, real Lambda functions (lambda_core), the real router classifier (host `{id}.execute-api.*` and path-style
`/apigw/{id}/{stage}/...`). Proves: stage routing, greedy `{proxy+}` matching, HTTP_PROXY forwarding, MOCK, Lambda proxy, API key required
(missing / wrong / disabled / not in a plan covering this stage), usage-plan throttle (429) and quota (429), CUSTOM Lambda authorizer
(Allow / Deny / missing token), COGNITO_USER_POOLS (fail closed w/o verifier; accept / reject with an injected verifier), AWS_IAM
(unsigned refused).
Run on host:  PYTHONPATH=. python3 tests/conformance/test_apigateway_gateway_v1.py
"""
import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from core.aws_wire_router import AwsWireRouter
from core import apigateway_gateway as v1gw
from core import apigateway_core as v1core

rt = AwsWireRouter()
fails = 0
SEEN = []


def check(name, cond, extra=""):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else "  -> %s" % (extra,)))
    fails += 0 if cond else 1


class H(BaseHTTPRequestHandler):
    def _go(self):
        n = int(self.headers.get("content-length") or 0)
        SEEN.append((self.command, self.path, dict(self.headers), self.rfile.read(n)))
        b = json.dumps({"hit": self.path}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("x-backend", "real")
        self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
    do_GET = do_POST = _go

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BACK = "http://127.0.0.1:%d" % srv.server_port


def cp(method, path, body=None):
    sig = {"host": "localhost:9000", "authorization": "AWS4-HMAC-SHA256 Credential=AK/20260101/us-east-1/apigateway/aws4_request, SignedHeaders=host, Signature=00"}
    o = rt.handle(method, path, {}, sig, json.dumps(body).encode() if body is not None else b"")
    return o["status"], (json.loads(o["body"]) if o["body"] else {})


def inv(api_id, stage, method, path, headers=None, host_style=True, body=b""):
    h = dict(headers or {})
    path, _, qs = path.partition("?")
    q = dict(x.split("=", 1) for x in qs.split("&")) if qs else {}
    if host_style:
        h["host"] = "%s.execute-api.localhost:9443" % api_id
        return rt.handle(method, "/%s%s" % (stage, path), q, h, body)
    h["host"] = "localhost:9000"
    return rt.handle(method, "/apigw/%s/%s%s" % (api_id, stage, path), q, h, body)


def mk_fn(name, src):
    st, out = cp("POST", "/2015-03-31/functions", {"FunctionName": name, "Code": {"Source": src}})
    check("create lambda %s" % name, st < 300, out)


mk_fn("echoFn", "import json\ndef handler(event, context):\n    return {'statusCode': 201, 'body': json.dumps({'path': event['path'], 'auth': (event.get('requestContext') or {}).get('authorizer')})}\n")
mk_fn("authFn", "def handler(event, context):\n    t = event.get('authorizationToken') or (event.get('headers') or {}).get('x-token', '')\n    eff = 'Allow' if t == 'let-me-in' else 'Deny'\n    return {'principalId': 'u1', 'policyDocument': {'Version': '2012-10-17', 'Statement': [{'Action': 'execute-api:Invoke', 'Effect': eff, 'Resource': event['methodArn']}]}, 'context': {'tenant': 'acme'}}\n")

st, api = cp("POST", "/restapis", {"name": "gw1"})
API, ROOT = api["id"], api["rootResourceId"]


def res(parent, part):
    return cp("POST", "/restapis/%s/resources/%s" % (API, parent), {"pathPart": part})[1]["id"]


def method(rid, m, integ, **mkw):
    cp("PUT", "/restapis/%s/resources/%s/methods/%s" % (API, rid, m), dict({"authorizationType": "NONE"}, **mkw))
    cp("PUT", "/restapis/%s/resources/%s/methods/%s/integration" % (API, rid, m), integ)


r_ping, r_proxy, r_secure, r_auth, r_cog, r_iam, r_lam = (res(ROOT, p) for p in ("ping", "{proxy+}", "secure", "auth", "cog", "iam", "lam"))
r_exact = res(r_ping, "deep")
method(r_ping, "GET", {"type": "MOCK", "mockStatus": 200, "mockBody": "pong"})
method(r_proxy, "ANY", {"type": "HTTP_PROXY", "uri": BACK + "/svc/{proxy}", "httpMethod": "ANY"})
method(r_exact, "GET", {"type": "MOCK", "mockStatus": 200, "mockBody": "exact"})
method(r_secure, "GET", {"type": "MOCK", "mockStatus": 200, "mockBody": "secret-data"}, apiKeyRequired=True)
method(r_lam, "GET", {"type": "AWS_PROXY", "uri": "arn:aws:lambda:us-east-1:000000000000:function:echoFn/invocations"})

# authorizers
st, a1 = cp("POST", "/restapis/%s/authorizers" % API, {"name": "tok", "type": "TOKEN", "identitySource": "method.request.header.Authorization",
            "authorizerUri": "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:000000000000:function:authFn/invocations"})
check("create TOKEN authorizer", st == 201, a1)
st, a2 = cp("POST", "/restapis/%s/authorizers" % API, {"name": "cog", "type": "COGNITO_USER_POOLS", "providerARNs": ["arn:aws:cognito-idp:us-east-1:000000000000:userpool/us-east-1_pool1"]})
check("create COGNITO authorizer", st == 201, a2)
method(r_auth, "GET", {"type": "AWS_PROXY", "uri": "arn:aws:lambda:us-east-1:000000000000:function:echoFn/invocations"}, authorizationType="CUSTOM", authorizerId=a1["id"])
method(r_cog, "GET", {"type": "MOCK", "mockStatus": 200, "mockBody": "cognito-ok"}, authorizationType="COGNITO_USER_POOLS", authorizerId=a2["id"])
method(r_iam, "GET", {"type": "MOCK", "mockStatus": 200, "mockBody": "iam-ok"}, authorizationType="AWS_IAM")

st, dep = cp("POST", "/restapis/%s/deployments" % API, {"stageName": "prod"})
check("deploy stage prod", st == 201, dep)
cp("POST", "/restapis/%s/deployments" % API, {"stageName": "dev"})

# ── routing + integrations ──
o = inv(API, "prod", "GET", "/ping")
check("host-style invoke: MOCK 200", o["status"] == 200 and o["body"] == b"pong", o)
o = inv(API, "prod", "GET", "/ping", host_style=False)
check("path-style /apigw/{id}/{stage}: MOCK 200", o["status"] == 200 and o["body"] == b"pong", o)
o = inv(API, "prod", "GET", "/ping/deep")
check("static child beats {proxy+}", o["body"] == b"exact", o)
o = inv(API, "nostage", "GET", "/ping")
check("unknown stage -> 403", o["status"] == 403, o)
o = inv(API, "prod", "POST", "/a/b/c?x=1", {"x-trace": "t1"}, body=b"payload")
SEEN_LAST = SEEN[-1] if SEEN else None
check("HTTP_PROXY: greedy {proxy+} reaches the real backend with path + body + headers",
      o["status"] == 200 and o["headers"].get("x-backend") == "real" and SEEN_LAST and SEEN_LAST[0] == "POST" and SEEN_LAST[1].startswith("/svc/a/b/c")
      and SEEN_LAST[3] == b"payload" and {k.lower(): v for k, v in SEEN_LAST[2].items()}.get("x-trace") == "t1" and SEEN_LAST[1].endswith("?x=1"), (o, SEEN_LAST))
o = inv(API, "prod", "GET", "/lam")
check("Lambda proxy", o["status"] == 201 and json.loads(o["body"])["path"] == "/lam", o)

# ── API key + usage plan ──
o = inv(API, "prod", "GET", "/secure")
check("apiKeyRequired, no key -> 403 Forbidden", o["status"] == 403 and b"Forbidden" in o["body"], o)
st, key = cp("POST", "/apikeys", {"name": "k1", "enabled": True})
KV = key["value"]
o = inv(API, "prod", "GET", "/secure", {"x-api-key": KV})
check("valid key but in NO usage plan -> 403", o["status"] == 403, o)
st, plan = cp("POST", "/usageplans", {"name": "p1", "apiStages": [{"apiId": API, "stage": "prod"}], "throttle": {"rateLimit": 1000.0, "burstLimit": 3}, "quota": {"limit": 5, "period": "DAY"}})
check("create usage plan", st == 201, plan)
cp("POST", "/usageplans/%s/keys" % plan["id"], {"keyId": key["id"], "keyType": "API_KEY"})
o = inv(API, "prod", "GET", "/secure", {"x-api-key": "x" * 32})
check("unknown key -> 403", o["status"] == 403, o)
o = inv(API, "dev", "GET", "/secure", {"x-api-key": KV})
check("key's plan does not cover stage dev -> 403", o["status"] == 403, o)
v1gw.reset_caches()
codes = [inv(API, "prod", "GET", "/secure", {"x-api-key": KV})["status"] for _ in range(5)]
check("burst 3: first 3 admitted, then 429 Too Many Requests", codes[:3] == [200, 200, 200] and 429 in codes[3:], codes)
v1gw.reset_caches()
time.sleep(0.01)
cp("PATCH", "/usageplans/%s" % plan["id"], {"patchOperations": [{"op": "replace", "path": "/throttle/burstLimit", "value": "100"}]})
codes = [inv(API, "prod", "GET", "/secure", {"x-api-key": KV})["status"] for _ in range(7)]
check("quota 5/DAY: 5 admitted then 429 Limit Exceeded", codes[:5] == [200] * 5 and codes[5] == 429 and b"Limit Exceeded" in inv(API, "prod", "GET", "/secure", {"x-api-key": KV})["body"], codes)
cp("PATCH", "/apikeys/%s" % key["id"], {"patchOperations": [{"op": "replace", "path": "/enabled", "value": "false"}]})
v1gw.reset_caches()
o = inv(API, "prod", "GET", "/secure", {"x-api-key": KV})
check("disabled key -> 403", o["status"] == 403, o)

# ── CUSTOM Lambda authorizer ──
o = inv(API, "prod", "GET", "/auth")
check("CUSTOM authorizer: no token -> 401", o["status"] == 401, o)
o = inv(API, "prod", "GET", "/auth", {"Authorization": "nope"})
check("CUSTOM authorizer: Deny policy -> 403", o["status"] == 403, o)
o = inv(API, "prod", "GET", "/auth", {"Authorization": "let-me-in"})
j = json.loads(o["body"] or b"{}")
check("CUSTOM authorizer: Allow -> integration runs, authorizer context reaches requestContext", o["status"] == 201 and (j.get("auth") or {}).get("tenant") == "acme", o)

# ── Cognito / IAM ──
o = inv(API, "prod", "GET", "/cog", {"Authorization": "Bearer abc.def.ghi"})
check("COGNITO: garbage token -> 401", o["status"] == 401, o)
o = inv(API, "prod", "GET", "/cog")
check("COGNITO: no token -> 401", o["status"] == 401, o)
o = inv(API, "prod", "GET", "/iam")
check("AWS_IAM: unsigned -> 403", o["status"] == 403, o)
o = inv(API, "prod", "GET", "/iam", {"Authorization": "AWS4-HMAC-SHA256 Credential=AK/20260101/us-east-1/execute-api/aws4_request, SignedHeaders=host, Signature=00"})
check("AWS_IAM: SigV4-shaped header admitted (signature NOT verified)", o["status"] == 200, o)


def tok(claims, kid="k", alg="RS256"):
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return "%s.%s.%s" % (b({"alg": alg, "kid": kid}), b(claims), "c2ln")


ISS = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_pool1"
st_, ap = v1core._apis(rt.apigw)[API], None
api_obj = v1core._apis(rt.apigw)[API]
stg = api_obj["stages"]["prod"]
res_c, pp = v1core._match_resource(api_obj, "/cog")
m_c = res_c["methods"]["GET"]
good = tok({"iss": ISS, "exp": time.time() + 600})
bad_iss = tok({"iss": "https://evil.example/x", "exp": time.time() + 600})
den, ctx = v1gw.enforce(rt.apigw, api_obj, "prod", stg, res_c, m_c, "GET", "/cog", {}, {"Authorization": "Bearer " + good}, {}, rt.lam, lambda t, h, c: True)
check("COGNITO: valid JWT (injected verifier accepts) -> admitted, claims exposed", den is None and ctx["claims"]["iss"] == ISS, den)
den, ctx = v1gw.enforce(rt.apigw, api_obj, "prod", stg, res_c, m_c, "GET", "/cog", {}, {"Authorization": "Bearer " + good}, {}, rt.lam, lambda t, h, c: False)
check("COGNITO: verifier rejects signature -> 401", den is not None and den.status == 401)
den, _ = v1gw.enforce(rt.apigw, api_obj, "prod", stg, res_c, m_c, "GET", "/cog", {}, {"Authorization": "Bearer " + bad_iss}, {}, rt.lam, lambda t, h, c: True)
check("COGNITO: wrong issuer -> 401", den is not None and den.status == 401)
den, _ = v1gw.enforce(rt.apigw, api_obj, "prod", stg, res_c, m_c, "GET", "/cog", {}, {"Authorization": "Bearer " + good}, {}, rt.lam, None)
check("COGNITO: no verifier available -> fails closed 401", den is not None and den.status == 401)

# stage throttle
stg["throttle"] = {"rateLimit": 0.001, "burstLimit": 2}
v1gw.reset_caches()
codes = [inv(API, "prod", "GET", "/ping")["status"] for _ in range(4)]
check("stage throttle burst 2 -> 429 after", codes[:2] == [200, 200] and codes[2:] == [429, 429], codes)

srv.shutdown()
print("\nRESULT: " + ("PASS" if not fails else "FAIL") + " — API Gateway v1 data plane (%d failed)" % fails)
raise SystemExit(1 if fails else 0)
