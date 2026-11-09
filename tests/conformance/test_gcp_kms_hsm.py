"""GCP KMS: HSM protection level is software-backed in Vyomi (stored + labelled, never FIPS-claimed).
Run: PYTHONPATH=. python3 tests/conformance/test_gcp_kms_hsm.py"""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.kms_keystore import InMemoryKeyStore  # noqa: E402
from core import gcp_kms_core as g  # noqa: E402

st = InMemoryKeyStore()
PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(m, path, body=None, q=None):
    r = g.dispatch(st, m, path, q or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


L = "/v1/projects/p/locations/global"
call("POST", f"{L}/keyRings", {}, {"keyRingId": "r"})
s, d = call("POST", f"{L}/keyRings/r/cryptoKeys", {"purpose": "ENCRYPT_DECRYPT", "versionTemplate": {"protectionLevel": "HSM", "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION"}}, {"cryptoKeyId": "h"})
check("create HSM key", s == 200 and d["versionTemplate"]["protectionLevel"] == "HSM" and d["primary"]["protectionLevel"] == "HSM", d)
check("labelled software-backed, no FIPS claim", "software-backed" in d["vyomiNote"] and "not FIPS" in d["vyomiNote"] and d["vyomiNote"].startswith("Dev Simplified"), d)
s, d = call("GET", f"{L}/keyRings/r/cryptoKeys/h")
check("get returns HSM", d["versionTemplate"]["protectionLevel"] == "HSM", d)
s, e = call("POST", f"{L}/keyRings/r/cryptoKeys/h:encrypt", {"plaintext": base64.b64encode(b"x").decode()})
check("encrypt reports HSM", s == 200 and e["protectionLevel"] == "HSM", e)
s, dd = call("POST", f"{L}/keyRings/r/cryptoKeys/h:decrypt", {"ciphertext": e["ciphertext"]})
check("decrypt round-trips", s == 200 and base64.b64decode(dd["plaintext"]) == b"x" and dd["protectionLevel"] == "HSM", dd)
s, v = call("POST", f"{L}/keyRings/r/cryptoKeys/h/cryptoKeyVersions", {})
check("new version inherits HSM", s == 200 and v["protectionLevel"] == "HSM", v)
s, d = call("POST", f"{L}/keyRings/r/cryptoKeys", {"purpose": "ENCRYPT_DECRYPT"}, {"cryptoKeyId": "s"})
check("default stays SOFTWARE, no note", d["versionTemplate"]["protectionLevel"] == "SOFTWARE" and "vyomiNote" not in d, d)
s, d = call("POST", f"{L}/keyRings/r/cryptoKeys", {"versionTemplate": {"protectionLevel": "EXTERNAL"}}, {"cryptoKeyId": "x"})
check("EXTERNAL rejected honestly", s == 400 and "not simulated" in d["error"]["message"], d)
s, d = call("POST", f"{L}/keyRings/r/cryptoKeys", {"versionTemplate": {"protectionLevel": "BOGUS"}}, {"cryptoKeyId": "y"})
check("bogus level rejected", s == 400, d)
print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
