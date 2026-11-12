"""Workload + Workforce Identity Federation: providers, attribute mapping/condition, STS token exchange
(run: PYTHONPATH=. python3 tests/conformance/test_gcp_wif.py)."""
import base64
import hashlib
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402
from core import gcp_wif_core as W  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False   # engine test: ad-hoc project ids
R = AwsWireRouter()
PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(method, path, body=None, query=None, raw=None, headers=None):
    out = R.handle(method, path, query or {}, headers or {}, raw if raw is not None else (json.dumps(body).encode() if body is not None else b""))
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {"raw": out["body"]}


# ── a throwaway RSA key (pure python) so the test can sign real RS256 JWTs ──
def _prime(bits, rnd):
    while True:
        n = rnd.getrandbits(bits) | (1 << (bits - 1)) | 1
        if all(pow(a, n - 1, n) == 1 for a in (2, 3, 5, 7, 11, 13)) and all(n % q for q in (3, 5, 7, 11, 13)):
            return n


rnd = random.Random(7)
p, q = _prime(512, rnd), _prime(512, rnd)
n, e = p * q, 65537
d = pow(e, -1, (p - 1) * (q - 1))
b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
i2b = lambda i: i.to_bytes((i.bit_length() + 7) // 8, "big")  # noqa: E731
JWKS = json.dumps({"keys": [{"kty": "RSA", "kid": "k1", "n": b64(i2b(n)), "e": b64(i2b(e))}]})


def jwt(claims, tamper=False):
    h, c = b64(json.dumps({"alg": "RS256", "kid": "k1"}).encode()), b64(json.dumps(claims).encode())
    k = (n.bit_length() + 7) // 8
    dg = hashlib.sha256((h + "." + c).encode()).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(W._SHA256_PREFIX) - len(dg) - 3) + b"\x00" + W._SHA256_PREFIX + dg
    sig = pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")
    if tamper:
        c = b64(json.dumps({**claims, "sub": "evil"}).encode())
    return h + "." + c + "." + b64(sig)


POOL = "/v1/projects/wif1/locations/global/workloadIdentityPools"
call("POST", POOL, {"displayName": "ci"}, {"workloadIdentityPoolId": "ci-pool"})
ISS = "https://token.actions.example.com"
prov = {"displayName": "gh", "oidc": {"issuerUri": ISS, "allowedAudiences": ["//iam.googleapis.com/projects/1/locations/global/workloadIdentityPools/ci-pool/providers/gh-actions"], "jwksJson": JWKS},
        "attributeMapping": {"google.subject": "assertion.sub", "attribute.repo": "assertion.repository", "attribute.actor": "assertion.actor.lowerAscii()"},
        "attributeCondition": 'assertion.repository == "acme/app" && attribute.repo.startsWith("acme/")'}
s, r = call("POST", POOL + "/ci-pool/providers", prov, {"workloadIdentityPoolProviderId": "gh-actions"})
check("create OIDC provider", s == 200 and r["state"] == "ACTIVE" and r["oidc"]["issuerUri"] == ISS, r)
s, r = call("POST", POOL + "/ci-pool/providers", prov, {"workloadIdentityPoolProviderId": "gh-actions"})
check("duplicate provider -> 409", s == 409)
check("http issuer rejected", call("POST", POOL + "/ci-pool/providers", {**prov, "oidc": {"issuerUri": "http://x.example"}}, {"workloadIdentityPoolProviderId": "bad1"})[0] == 400)
check("missing google.subject rejected", call("POST", POOL + "/ci-pool/providers", {**prov, "attributeMapping": {"attribute.a": "assertion.a"}}, {"workloadIdentityPoolProviderId": "bad2"})[0] == 400)
check("bad mapping expression rejected", call("POST", POOL + "/ci-pool/providers", {**prov, "attributeMapping": {"google.subject": "assertion..sub("}}, {"workloadIdentityPoolProviderId": "bad3"})[0] == 400)
check("bad attribute condition rejected", call("POST", POOL + "/ci-pool/providers", {**prov, "attributeCondition": "foo.bar =="}, {"workloadIdentityPoolProviderId": "bad4"})[0] == 400)
check("provider id 'gcp-' prefix rejected", call("POST", POOL + "/ci-pool/providers", prov, {"workloadIdentityPoolProviderId": "gcp-x1"})[0] == 400)
check("AWS provider needs a 12-digit account", call("POST", POOL + "/ci-pool/providers", {"aws": {"accountId": "12"}}, {"workloadIdentityPoolProviderId": "aws1"})[0] == 400)
check("SAML provider needs IdP metadata", call("POST", POOL + "/ci-pool/providers", {"saml": {"idpMetadataXml": "<x/>"}, "attributeMapping": {"google.subject": "assertion.subject"}}, {"workloadIdentityPoolProviderId": "saml1"})[0] == 400)
s, lst = call("GET", POOL + "/ci-pool/providers")
check("list providers", s == 200 and len(lst["workloadIdentityPoolProviders"]) == 1)
check("provider on a missing pool -> 404", call("POST", POOL + "/nope/providers", prov, {"workloadIdentityPoolProviderId": "gh-actions"})[0] == 404)

AUD = "//iam.googleapis.com/projects/1/locations/global/workloadIdentityPools/ci-pool/providers/gh-actions"
claims = {"iss": ISS, "aud": AUD, "sub": "repo:acme/app:ref:refs/heads/main", "repository": "acme/app", "actor": "OctoCat", "exp": int(time.time()) + 600}
form = lambda tok: ("grant_type=urn:ietf:params:oauth:grant-type:token-exchange&subject_token_type=urn:ietf:params:oauth:token-type:jwt&audience=" + AUD + "&subject_token=" + tok).encode()  # noqa: E731
s, t = call("POST", "/v1/token", raw=form(jwt(claims)), headers={"content-type": "application/x-www-form-urlencoded"})
check("STS exchanges a valid GitHub-style token for a federated access token", s == 200 and t["access_token"].startswith("ya29.") and t["token_type"] == "Bearer", t)
s, i = call("POST", "/v1/introspect", raw=("token=" + t.get("access_token", "")).encode())
check("introspection returns the mapped principal and attributes", s == 200 and i["active"] and i["sub"].endswith("/subject/repo:acme/app:ref:refs/heads/main") and i["attributes"]["attribute.actor"] == "octocat" and i["attributes"]["attribute.repo"] == "acme/app", i)
check("tampered signature -> invalid_grant", call("POST", "/v1/token", raw=form(jwt(claims, tamper=True)))[1].get("error") == "invalid_grant")
check("wrong issuer -> invalid_grant", call("POST", "/v1/token", raw=form(jwt({**claims, "iss": "https://evil.example"})))[1].get("error") == "invalid_grant")
check("wrong audience -> invalid_grant", call("POST", "/v1/token", raw=form(jwt({**claims, "aud": "other"})))[1].get("error") == "invalid_grant")
check("expired token -> invalid_grant", call("POST", "/v1/token", raw=form(jwt({**claims, "exp": int(time.time()) - 3600})))[1].get("error") == "invalid_grant")
s, den = call("POST", "/v1/token", raw=form(jwt({**claims, "repository": "evil/app"})))
check("attribute condition not satisfied -> 403 access_denied", s == 403 and den.get("error") == "access_denied", den)
check("unknown provider audience -> invalid_target", call("POST", "/v1/token", json.dumps({"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange", "audience": "//iam.googleapis.com/projects/1/locations/global/workloadIdentityPools/ci-pool/providers/zzz", "subject_token": "x"}).encode() and None, raw=json.dumps({"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange", "audience": "//iam.googleapis.com/projects/1/locations/global/workloadIdentityPools/ci-pool/providers/zzz", "subject_token": "x"}).encode())[1].get("error") == "invalid_target")
s, up = call("PATCH", POOL + "/ci-pool/providers/gh-actions", {"disabled": True}, {"updateMask": "disabled"})
check("disabled provider refuses exchange", up.get("disabled") is True and call("POST", "/v1/token", raw=form(jwt(claims)))[1].get("error") == "invalid_grant")
check("delete provider", call("DELETE", POOL + "/ci-pool/providers/gh-actions")[0] == 200 and call("GET", POOL + "/ci-pool/providers/gh-actions")[0] == 404)

# Workforce
WF = "/v1/locations/global/workforcePools"
call("POST", WF, {"displayName": "staff"}, {"workforcePoolId": "staff-pool"})
s, r = call("POST", WF + "/staff-pool/providers", {"oidc": {"issuerUri": "https://idp.corp.example", "clientId": "abc"}, "attributeMapping": {"google.subject": "assertion.email"}}, {"workforcePoolProviderId": "okta"})
check("workforce OIDC provider created", s == 200 and r["name"].endswith("/workforcePools/staff-pool/providers/okta"), r)
s, r = call("POST", WF + "/staff-pool/providers", {"saml": {"idpMetadataXml": "<EntityDescriptor entityID='x'/>"}, "attributeMapping": {"google.subject": "assertion.subject"}}, {"workforcePoolProviderId": "adfs"})
check("workforce SAML provider created", s == 200 and "saml" in r, r)
check("workforce providers listed", len(call("GET", WF + "/staff-pool/providers")[1].get("providers", [])) == 2)
check("deleting the pool removes its providers", call("DELETE", WF + "/staff-pool")[0] == 200 and call("GET", WF + "/staff-pool/providers")[0] == 404)
# mapping engine
cl = {"sub": "u1", "groups": ["a", "b"], "email": "Alice@X.com", "team": "core"}
m = W.map_attributes({"attributeMapping": {"google.subject": "assertion.email.lowerAscii()", "attribute.id": "assertion.sub + \"-\" + assertion.team"}}, cl)
check("mapping: lowerAscii and string concatenation", m == {"google.subject": "alice@x.com", "attribute.id": "u1-core"}, m)
check("condition: in-list and negation", W.check_condition({"attributeCondition": "assertion.team in [\"core\", \"infra\"] && !(assertion.sub == \"u2\")"}, cl, {}))
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
