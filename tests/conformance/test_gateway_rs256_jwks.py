"""REAL RS256 verification in the shared gateway code (core/gateway_common.make_rs256_verifier, used by GCP API Gateway
`default_verify_sig`, AWS HTTP API v2 and REST v1 Cognito authorizers): a generated RSA keypair, a JWKS served by a local HTTP
server, tokens signed with the real private key. A correctly signed JWT is admitted; tampered payload, wrong key, wrong kid, wrong alg,
expired token, wrong audience and an unreachable JWKS are all refused. End to end through the GCP gateway handle().
Needs `cryptography` (installed in the appliance image via azure-storage-blob / requirements.txt); SKIPs loudly if absent.
Run on host:  PYTHONPATH=. python3 tests/conformance/test_gateway_rs256_jwks.py
"""
import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
except ImportError:
    print("SKIP: the `cryptography` package is not installed in this interpreter — RS256 verification NOT exercised")
    raise SystemExit(0)

from core.aws_wire_router import AwsWireRouter
from core import gateway_common as gc
from core import gcp_apigateway_gateway as gw

fails = 0


def check(name, ok, extra=""):
    global fails
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else " :: " + str(extra)[:240]))
    fails += 0 if ok else 1


def b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def jb(d):
    return b64(json.dumps(d).encode())


def int_b64(n):
    return b64(n.to_bytes((n.bit_length() + 7) // 8, "big"))


def jwk(pub, kid):
    nums = pub.public_numbers()
    return {"kty": "RSA", "alg": "RS256", "use": "sig", "kid": kid, "n": int_b64(nums.n), "e": int_b64(nums.e)}


def sign(key, claims, kid="k1", alg="RS256"):
    h, p = jb({"alg": alg, "typ": "JWT", "kid": kid}), jb(claims)
    sig = key.sign(("%s.%s" % (h, p)).encode(), padding.PKCS1v15(), hashes.SHA256())
    return "%s.%s.%s" % (h, p, b64(sig))


KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWKS = {"keys": [jwk(KEY.public_key(), "k1")]}
HITS = []


class J(BaseHTTPRequestHandler):
    def do_GET(self):
        HITS.append(self.path)
        b = json.dumps(JWKS).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), J)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URI = "http://127.0.0.1:%d/jwks" % srv.server_port
ISS = "https://iss.test"
CFG = {"issuer": ISS, "audience": ["my-aud"], "jwks_uri": URI}
now = time.time()
CL = {"iss": ISS, "aud": "my-aud", "sub": "u1", "exp": now + 600}

v = gw.default_verify_sig()
check("default_verify_sig builds a verifier when cryptography is present", v is not None)
good = sign(KEY, CL)
hdr = json.loads(gc.b64u(good.split(".")[0]))
check("verifier accepts a correctly RS256-signed token", v(good, hdr, CFG) is True)
check("jwt_validate end to end accepts it (claims returned)", (gc.jwt_validate(good, CFG, v)[0] or {}).get("sub") == "u1")

h, p, s = good.split(".")
tampered = "%s.%s.%s" % (h, jb(dict(CL, sub="admin")), s)
check("tampered payload (signature kept) is rejected", v(tampered, hdr, CFG) is False and gc.jwt_validate(tampered, CFG, v)[0] is None)
forged = sign(OTHER, CL)
check("token signed by a different private key is rejected", v(forged, hdr, CFG) is False)
check("unknown kid is rejected", v(sign(KEY, CL, kid="nope"), {"alg": "RS256", "kid": "nope"}, CFG) is False)
check("alg none / HS256 are rejected", v(sign(KEY, CL, alg="none"), {"alg": "none", "kid": "k1"}, CFG) is False
      and v(sign(KEY, CL, alg="HS256"), {"alg": "HS256", "kid": "k1"}, CFG) is False)
check("expired token is rejected (signature fine, exp past)", gc.jwt_validate(sign(KEY, dict(CL, exp=now - 5)), CFG, v)[0] is None)
check("wrong audience is rejected", gc.jwt_validate(sign(KEY, dict(CL, aud="other")), CFG, v)[0] is None)
check("JWKS is cached (one fetch for all of the above)", len(HITS) == 1, HITS)
gc.reset_jwks_cache()
check("unreachable JWKS fails closed", v(good, hdr, dict(CFG, jwks_uri="http://127.0.0.1:9/none")) is False)

# OIDC discovery path (no jwks_uri): issuer/.well-known/openid-configuration -> jwks_uri
gc.reset_jwks_cache()
docs = {}
vd = gc.make_rs256_verifier(fetch_json=lambda url: ({"jwks_uri": "https://iss.test/jwks"} if url.endswith("openid-configuration") else (docs.setdefault(url, JWKS))))
check("OIDC discovery finds the JWKS and verifies", vd(good, hdr, {"issuer": ISS}) is True)

# ── end to end through the GCP gateway handle() ──
rt = AwsWireRouter()
P = "/v1/projects/nano-project/locations"


def call(m, pth, b=None, q=None):
    o = rt.handle(m, pth, q or {}, {"content-type": "application/json"}, json.dumps(b).encode() if b is not None else b"")
    return o["status"], json.loads(o["body"] or b"{}")


SPEC = {"swagger": "2.0", "info": {"title": "t", "version": "1"},
        "securityDefinitions": {"jwt": {"type": "oauth2", "x-google-issuer": ISS, "x-google-jwks_uri": "https://iss.test/jwks", "x-google-audiences": "my-aud"}},
        "x-google-backend": {"address": "https://backend.test", "path_translation": "APPEND_PATH_TO_ADDRESS"},
        "paths": {"/secure": {"post": {"operationId": "secure", "security": [{"jwt": []}], "responses": {"200": {"description": "ok"}}}}}}
call("POST", P + "/global/apis", {}, {"apiId": "rsapi"})
st, r = call("POST", P + "/global/apis/rsapi/configs", {"openapiDocuments": [{"document": {"path": "o.json", "contents": base64.b64encode(json.dumps(SPEC).encode()).decode()}}]}, {"apiConfigId": "c1"})
check("config with a real jwks_uri accepted", st == 200, r)
call("POST", P + "/us-central1/gateways", {"apiConfig": "projects/nano-project/locations/global/apis/rsapi/configs/c1"}, {"gatewayId": "g1"})
g = call("GET", P + "/us-central1/gateways/g1")[1]
fetched = []


def fetch(method, url, headers, body, timeout):
    fetched.append(url)
    return 200, {"x-backend": "real"}, b'{"ok":true}'


gc.reset_jwks_cache()
gw.reset_caches()
import urllib.request   # the control plane only accepts an https jwks_uri: send that host to the local JWKS server, through the REAL urlopen
_real_urlopen = urllib.request.urlopen
urllib.request.urlopen = lambda u, *a, **k: _real_urlopen(str(u).replace("https://iss.test/jwks", URI), *a, **k)


def hit(tok):
    return gw.handle(rt.gcp_mon, g, "POST", "/secure", {"authorization": "Bearer " + tok} if tok else {}, {}, b"{}", http_fetch=fetch, verify_sig=gw.default_verify_sig())


r = hit(good)
check("gateway: correctly signed JWT -> forwarded to backend (200)", r.status == 200 and fetched, (r.status, r.body))
n = len(fetched)
r = hit(tampered)
check("gateway: tampered JWT -> 401, backend NOT called", r.status == 401 and len(fetched) == n, (r.status, r.body))
r = hit(forged)
check("gateway: JWT signed by another key -> 401", r.status == 401 and len(fetched) == n, (r.status, r.body))
r = hit(None)
check("gateway: no token -> 401", r.status == 401 and len(fetched) == n, (r.status, r.body))
r = gw.handle(rt.gcp_mon, g, "POST", "/secure", {"authorization": "Bearer " + good}, {}, b"{}", http_fetch=fetch, verify_sig=None)
check("gateway: no verifier injected -> fails closed 401 even for a good token", r.status == 401 and len(fetched) == n, (r.status, r.body))

urllib.request.urlopen = _real_urlopen
srv.shutdown()
print("\nRESULT: " + ("PASS" if not fails else "FAIL") + " — gateway RS256/JWKS (%d failed)" % fails)
raise SystemExit(1 if fails else 0)
