"""GCS turbo replication, Autoclass, CMEK and per-object customer-supplied keys
(run: PYTHONPATH=. python3 tests/conformance/test_gcp_storage_config.py)."""
import base64
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402
from core import gcp_storage_core as G  # noqa: E402

R = AwsWireRouter()
PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def gcs(method, path, body=None, query=None, headers=None, raw=None):
    r = G.dispatch(R.gcs, method, path, query or {}, headers or {}, raw if raw is not None else (json.dumps(body).encode() if body is not None else b""))
    try:
        return r.status, json.loads(r.body or b"{}")
    except Exception:
        return r.status, r.body


# ── turbo replication ──
s, b = gcs("POST", "/storage/v1/b", {"name": "t-dual", "location": "NAM4", "rpo": "ASYNC_TURBO"}, {"project": "p"})
check("turbo replication on a dual-region bucket", s == 200 and b["rpo"] == "ASYNC_TURBO", b)
check("turbo replication on a single-region bucket -> 400", gcs("POST", "/storage/v1/b", {"name": "t-reg", "location": "US-CENTRAL1", "rpo": "ASYNC_TURBO"}, {"project": "p"})[0] == 400)
check("invalid rpo -> 400", gcs("POST", "/storage/v1/b", {"name": "t-bad", "location": "NAM4", "rpo": "FAST"}, {"project": "p"})[0] == 400)
s, b = gcs("PATCH", "/storage/v1/b/t-dual", {"rpo": "DEFAULT"})
s2, ops = gcs("GET", "/storage/v1/b/t-dual/operations")
check("switching back to default replication is recorded as an operation", s == 200 and b["rpo"] == "DEFAULT" and any("Default" in (o.get("metadata", {}).get("type", "") + str(o)) for o in ops.get("items", [])), ops)

# ── autoclass ──
check("autoclass terminal class validated", gcs("POST", "/storage/v1/b", {"name": "ac-bad", "autoclass": {"enabled": True, "terminalStorageClass": "COLDLINE"}}, {"project": "p"})[0] == 400)
s, b = gcs("POST", "/storage/v1/b", {"name": "ac1", "autoclass": {"enabled": True, "terminalStorageClass": "ARCHIVE"}}, {"project": "p"})
check("bucket created with Autoclass", s == 200 and b["autoclass"]["enabled"] and b["autoclass"]["terminalStorageClass"] == "ARCHIVE" and b["autoclass"]["toggleTime"], b)
check("SetStorageClass lifecycle rule rejected while Autoclass is on", gcs("PATCH", "/storage/v1/b/ac1", {"lifecycle": {"rule": [{"action": {"type": "SetStorageClass", "storageClass": "NEARLINE"}, "condition": {"age": 1}}]}})[0] == 400)
gcs("POST", "/upload/storage/v1/b/ac1/o", query={"uploadType": "media", "name": "cold.txt"}, headers={"content-type": "text/plain"}, raw=b"data")
def age(bucket, name, days):
    """Make the object idle for `days`: move its object clock back (what waiting would do)."""
    e = R.gcs.bucket_objects(bucket)[name]
    t = G.datetime.fromtimestamp(G.datetime.now(G.timezone.utc).timestamp() - days * 86400, G.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    e["updated"] = e["timeCreated"] = t
    e.pop("_atime", None)
def cls(): return gcs("GET", "/storage/v1/b/ac1/o/cold.txt")[1]["storageClass"]
check("new object starts in STANDARD", cls() == "STANDARD")
for days, want in ((31, "NEARLINE"), (95, "COLDLINE"), (400, "ARCHIVE"), (10, "STANDARD"), (40, "NEARLINE")):
    age("ac1", "cold.txt", days)
    check(f"after {days} idle days -> {want}", cls() == want, cls())
gcs("GET", "/storage/v1/b/ac1/o/cold.txt", query={"alt": "media"})
check("reading the object returns it to STANDARD", cls() == "STANDARD")
gcs("POST", "/storage/v1/b", {"name": "ac2", "autoclass": {"enabled": True}}, {"project": "p"})
gcs("POST", "/upload/storage/v1/b/ac2/o", query={"uploadType": "media", "name": "n.txt"}, headers={"content-type": "text/plain"}, raw=b"x")
age("ac2", "n.txt", 400)
check("terminal class NEARLINE (default) stops at NEARLINE", gcs("GET", "/storage/v1/b/ac2/o/n.txt")[1]["storageClass"] == "NEARLINE")

# ── CMEK ──
KEY = "projects/p/locations/us/keyRings/r/cryptoKeys/k"
R.gcs.refs = lambda kind, name: name == KEY if kind == "kms" else None
s, b = gcs("POST", "/storage/v1/b", {"name": "cm1", "location": "US", "encryption": {"defaultKmsKeyName": KEY}}, {"project": "p"})
check("bucket with a default Cloud KMS key", s == 200 and b["encryption"]["defaultKmsKeyName"] == KEY, b)
check("missing KMS key -> 400", gcs("POST", "/storage/v1/b", {"name": "cm2", "location": "US", "encryption": {"defaultKmsKeyName": KEY + "x"}}, {"project": "p"})[0] == 400)
check("KMS key in another location -> 400", gcs("POST", "/storage/v1/b", {"name": "cm3", "location": "EU", "encryption": {"defaultKmsKeyName": KEY}}, {"project": "p"})[0] == 400)
gcs("POST", "/upload/storage/v1/b/cm1/o", query={"uploadType": "media", "name": "o.txt"}, headers={"content-type": "text/plain"}, raw=b"secret")
check("new objects record the bucket's CMEK key", gcs("GET", "/storage/v1/b/cm1/o/o.txt")[1].get("kmsKeyName") == KEY)
R.gcs.refs = None

# ── per-object CSEK ──
gcs("POST", "/storage/v1/b", {"name": "ck1"}, {"project": "p"})
key = bytes(range(32)); k64 = base64.b64encode(key).decode(); h = {"x-goog-encryption-algorithm": "AES256", "x-goog-encryption-key": k64, "x-goog-encryption-key-sha256": base64.b64encode(hashlib.sha256(key).digest()).decode(), "content-type": "text/plain"}
s, b = gcs("POST", "/upload/storage/v1/b/ck1/o", query={"uploadType": "media", "name": "c.txt"}, headers=h, raw=b"top secret payload")
check("upload with a customer-supplied key", s == 200 and b["customerEncryption"]["encryptionAlgorithm"] == "AES256" and "keySha256" in b["customerEncryption"] and "kmsKeyName" not in b, b)
entry = R.gcs.bucket_objects("ck1")["c.txt"]
check("bytes at rest are not the plaintext", bytes(entry["data"]) != b"top secret payload" and len(entry["data"]) == len(b"top secret payload"))
check("the key itself is never stored", k64 not in json.dumps({k: str(v) for k, v in entry.items()}))
s, d = gcs("GET", "/storage/v1/b/ck1/o/c.txt", query={"alt": "media"}, headers={k: v for k, v in h.items() if k != "content-type"})
check("download with the right key returns the plaintext", s == 200 and d == b"top secret payload", (s, d))
check("download without the key -> 400", gcs("GET", "/storage/v1/b/ck1/o/c.txt", query={"alt": "media"})[0] == 400)
other = bytes(range(1, 33)); h2 = {"x-goog-encryption-algorithm": "AES256", "x-goog-encryption-key": base64.b64encode(other).decode(), "x-goog-encryption-key-sha256": base64.b64encode(hashlib.sha256(other).digest()).decode()}
check("download with a different key -> 400", gcs("GET", "/storage/v1/b/ck1/o/c.txt", query={"alt": "media"}, headers=h2)[0] == 400)
check("metadata read needs no key and shows the key hash", gcs("GET", "/storage/v1/b/ck1/o/c.txt")[1]["customerEncryption"]["keySha256"] == h["x-goog-encryption-key-sha256"])
check("wrong key hash on upload -> 400", gcs("POST", "/upload/storage/v1/b/ck1/o", query={"uploadType": "media", "name": "d.txt"}, headers={**h, "x-goog-encryption-key-sha256": "AAAA"}, raw=b"x")[0] == 400)
check("short key on upload -> 400", gcs("POST", "/upload/storage/v1/b/ck1/o", query={"uploadType": "media", "name": "d.txt"}, headers={"x-goog-encryption-algorithm": "AES256", "x-goog-encryption-key": base64.b64encode(b"short").decode(), "x-goog-encryption-key-sha256": base64.b64encode(hashlib.sha256(b"short").digest()).decode()}, raw=b"x")[0] == 400)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
