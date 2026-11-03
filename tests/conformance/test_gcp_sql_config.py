"""Cloud SQL custom machine shapes, SSL mode and CMEK (run: PYTHONPATH=. python3 tests/conformance/test_gcp_sql_config.py)."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402

R = AwsWireRouter()
PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(method, path, body=None):
    out = R.handle(method, path, {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {"raw": out["body"]}


P = "/sql/v1beta4/projects/p1/instances"


def mk(name, tier="db-custom-2-7680", **kw):
    b = {"name": name, "region": "us-central1", "databaseVersion": "POSTGRES_15", "settings": {"tier": tier, **kw.pop("settings", {})}}
    b.update(kw)
    return call("POST", P, b)


s, _ = mk("a", "db-custom-2-7680"); check("valid custom shape", s == 200, s)
for t in ("db-custom-3-7680", "db-custom-2-7000", "db-custom-2-1024", "db-custom-2-20000", "db-bogus", "db-custom-100-300000"):
    s, b = mk("x" + t.replace("-", ""), t); check(f"rejects {t}", s == 400, (s, b))
s, b = call("GET", P + "/a"); check("tier reflected", b["settings"]["tier"] == "db-custom-2-7680", b)
s, b = mk("sh", "db-f1-micro"); check("shared core ok", s == 200)
s, b = mk("bad-ssl", settings={"ipConfiguration": {"sslMode": "NOPE"}}); check("bad sslMode 400", s == 400, b)
s, b = mk("ssl1", settings={"ipConfiguration": {"sslMode": "ENCRYPTED_ONLY"}}); check("ENCRYPTED_ONLY ok", s == 200)
s, b = call("GET", P + "/ssl1"); check("requireSsl derived", b["settings"]["ipConfiguration"]["requireSsl"] is True, b)
s, b = call("PATCH", P + "/a", {"settings": {"ipConfiguration": {"sslMode": "TRUSTED_CLIENT_CERTIFICATE_REQUIRED"}}}); check("patch sslMode", s == 200, b)
s, b = call("PATCH", P + "/a", {"settings": {"tier": "db-custom-5-9999"}}); check("patch bad tier 400", s == 400, b)
s, b = call("GET", P + "/a"); check("patched mode stored", b["settings"]["ipConfiguration"]["sslMode"] == "TRUSTED_CLIENT_CERTIFICATE_REQUIRED")

K = "/v1/projects/p1/locations/us-central1/keyRings/kr/cryptoKeys/k1"
call("POST", "/v1/projects/p1/locations/us-central1/keyRings?keyRingId=kr", {})
R.handle("POST", "/v1/projects/p1/locations/us-central1/keyRings", {"keyRingId": "kr"}, {}, b"{}")
R.handle("POST", "/v1/projects/p1/locations/us-central1/keyRings/kr/cryptoKeys", {"cryptoKeyId": "k1"}, {}, json.dumps({"purpose": "ENCRYPT_DECRYPT"}).encode())
key = K[4:]
s, b = mk("cm1", diskEncryptionConfiguration={"kmsKeyName": key}); check("CMEK ok", s == 200, b)
s, b = call("GET", P + "/cm1"); check("CMEK reflected", b.get("diskEncryptionConfiguration", {}).get("kmsKeyName") == key and "diskEncryptionStatus" in b, b)
s, b = mk("cm2", diskEncryptionConfiguration={"kmsKeyName": key.replace("us-central1", "europe-west1")}); check("CMEK region mismatch 400", s == 400, b)
s, b = mk("cm3", diskEncryptionConfiguration={"kmsKeyName": key.replace("k1", "nope")}); check("CMEK missing key 400", s == 400, b)
s, b = mk("cm4", diskEncryptionConfiguration={"kmsKeyName": "garbage"}); check("CMEK malformed 400", s == 400, b)
print(f"\n{PASS} passed, {FAIL} failed"); sys.exit(1 if FAIL else 0)
