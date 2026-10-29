"""Unit tests for core/gcp_iamcredentials_core.py (run: python3 tests/conformance/test_gcp_iamcredentials_core.py)."""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_iamcredentials_core as ic  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


SA = "robot@demo.iam.gserviceaccount.com"
P = "/v1/projects/-/serviceAccounts/" + SA
KNOWN = {SA: SA, "123456789012345678901": SA, "other@demo.iam.gserviceaccount.com": "other@demo.iam.gserviceaccount.com"}


def call(st, verb, body=None, path=P, resolver=None, method="POST"):
    r = ic.dispatch(st, method, path + ":" + verb, {}, {}, json.dumps(body).encode() if body is not None else b"", resolver=resolver)
    return r.status, json.loads(r.body or b"{}")


def jwt_ok(tok):
    h, p, s = tok.split(".")
    return ic.rsa_verify((h + "." + p).encode(), base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))


def seg(tok, i):
    s = tok.split(".")[i]
    return json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))


st = ic.IamCredentialsStore()
s, r = call(st, "generateAccessToken", {"scope": ["https://www.googleapis.com/auth/cloud-platform"]})
check("generateAccessToken -> ya29 token + expireTime", s == 200 and r["accessToken"].startswith("ya29.") and r["expireTime"].endswith("Z"), r)
s, r = call(st, "generateAccessToken", {"scope": ["a"], "lifetime": "300s"})
check("lifetime honoured", s == 200 and len(st.issued) == 2 and list(st.issued.values())[-1]["lifetimeSeconds"] == 300, r)
check("missing scope -> 400 INVALID_ARGUMENT", call(st, "generateAccessToken", {})[1]["error"]["status"] == "INVALID_ARGUMENT")
check("lifetime > 12h -> 400", call(st, "generateAccessToken", {"scope": ["a"], "lifetime": "50000s"})[0] == 400)
check("malformed lifetime -> 400", call(st, "generateAccessToken", {"scope": ["a"], "lifetime": "soon"})[0] == 400)
s, r = call(st, "generateIdToken", {"audience": "https://svc.example.com", "includeEmail": True})
check("generateIdToken: RS256 verifies, aud/email claims", s == 200 and jwt_ok(r["token"]) and seg(r["token"], 1)["aud"] == "https://svc.example.com"
      and seg(r["token"], 1)["email"] == SA and seg(r["token"], 0)["alg"] == "RS256", r)
check("id token without includeEmail has no email", "email" not in seg(call(st, "generateIdToken", {"audience": "a"})[1]["token"], 1))
check("missing audience -> 400", call(st, "generateIdToken", {})[0] == 400)
blob = b"sign me"
s, r = call(st, "signBlob", {"payload": base64.b64encode(blob).decode()})
check("signBlob verifies against the public key", s == 200 and ic.rsa_verify(blob, base64.b64decode(r["signedBlob"])) and r["keyId"] == ic.key_id(SA), r)
check("signBlob tampered data fails", not ic.rsa_verify(b"other", base64.b64decode(r["signedBlob"])))
check("signBlob missing bytes -> 400", call(st, "signBlob", {})[0] == 400)
s, r = call(st, "signJwt", {"payload": json.dumps({"iss": SA, "aud": "x", "exp": 9999999999})})
check("signJwt verifies, kid = keyId", s == 200 and jwt_ok(r["signedJwt"]) and seg(r["signedJwt"], 0)["kid"] == r["keyId"] and seg(r["signedJwt"], 1)["iss"] == SA, r)
check("signJwt non-JSON payload -> 400", call(st, "signJwt", {"payload": "not json"})[0] == 400)
check("signJwt non-object payload -> 400", call(st, "signJwt", {"payload": "[1]"})[0] == 400)
check("public JWK shape", ic.public_jwk(SA)["kty"] == "RSA" and ic.public_jwk()["alg"] == "RS256")

# project wildcard, verbs, methods
check("non-wildcard project -> 400", call(st, "signBlob", {"payload": "aGk="}, path="/v1/projects/demo/serviceAccounts/" + SA)[0] == 400)
check("unknown verb -> 404", call(st, "frobnicate", {}, )[0] == 404)
check("GET on a verb -> 405", call(st, "signBlob", None, method="GET")[0] == 405)
check("malformed account -> 400", call(st, "signBlob", {"payload": "aGk="}, path="/v1/projects/-/serviceAccounts/not-an-email")[0] == 400)
check("unique id without resolver -> 403", call(st, "signBlob", {"payload": "aGk="}, path="/v1/projects/-/serviceAccounts/123456789012345678901")[0] == 403)

# resolver / delegates
res = KNOWN.get
check("resolver: known account ok", call(st, "signBlob", {"payload": "aGk="}, resolver=res)[0] == 200)
check("resolver: unique id resolves to the email", call(st, "generateAccessToken", {"scope": ["a"]}, path="/v1/projects/-/serviceAccounts/123456789012345678901", resolver=res)[0] == 200)
s, r = call(st, "signBlob", {"payload": "aGk="}, path="/v1/projects/-/serviceAccounts/ghost@demo.iam.gserviceaccount.com", resolver=res)
check("resolver: unknown account -> 403 PERMISSION_DENIED", s == 403 and r["error"]["status"] == "PERMISSION_DENIED", r)
d = "projects/-/serviceAccounts/other@demo.iam.gserviceaccount.com"
before = len(st.issued)
check("delegates chain recorded", call(st, "generateAccessToken", {"scope": ["a"], "delegates": [d]}, resolver=res)[0] == 200
      and list(st.issued.values())[-1]["delegates"] == ["other@demo.iam.gserviceaccount.com"] and len(st.issued) == before + 1)
check("unknown delegate -> 403", call(st, "generateAccessToken", {"scope": ["a"], "delegates": ["projects/-/serviceAccounts/ghost@demo.iam.gserviceaccount.com"]}, resolver=res)[0] == 403)
check("malformed delegate -> 400", call(st, "generateAccessToken", {"scope": ["a"], "delegates": ["nope"]})[0] == 400)

# console
row = ic.issue_from_form(st, {"serviceAccount": SA, "credentialType": "ID token", "detail": "https://x.example"}, res)
check("console issue: every field filled", all(str(row.get(k, "")).strip() for k in
      ("id", "service_account", "type", "issued", "expires", "lifetime", "scope_or_audience", "delegation", "key_id", "state")), row)
check("console issue accepts the wizard's name field", ic.issue_from_form(st, {"name": SA}, res)["service_account"] == SA)
check("list_all covers the log", len(ic.list_all(st)) == len(st.issued))
for t in ("Access token", "Signed blob", "Signed JWT"):
    check("console issue: " + t, ic.issue_from_form(st, {"serviceAccount": SA, "credentialType": t}, res)["type"] == t)
try:
    ic.issue_from_form(st, {"serviceAccount": SA, "credentialType": "Cookie"})
    check("console issue: bad type rejected", False)
except Exception:
    check("console issue: bad type rejected", True)

print(f"{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
