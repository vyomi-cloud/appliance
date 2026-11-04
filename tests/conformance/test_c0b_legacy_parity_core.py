"""v4 C0b — behaviours ported from the retired offline handlers into the shared cores.

The offline appliance's native Azure Blob (core/azure_dataplane.py `_blob_handle`), GCP
Secret Manager and Cloud KMS (core/vault_routes.py, Vault-backed) wire now runs on the
shared conformance cores (core/azure_blob_core.py, core/gcp_secretmanager_core.py,
core/gcp_kms_core.py). Every legacy behaviour the cores lacked was ported; this suite
pins each one on the in-memory substrate AND the file-backed (sqlite) substrate — the
latter proves a fresh store instance sees the state (incl. KMS key rings and Secret
Manager version numbers after a JSON round-trip).

Pure stdlib + cores → runs on host CPython and Pyodide.
Run:  PYTHONPATH=. python3 tests/conformance/test_c0b_legacy_parity_core.py
"""
import base64
import json

from core import azure_blob_core as az
from core import gcp_kms_core as gkms
from core import gcp_secretmanager_core as gsec
from core.kms_keystore import InMemoryKeyStore
from core.kv_store import InMemoryKvStore
from core.persistent_store import (PersistentAzureBlobStore, PersistentKeyStore,
                                   PersistentKvStore, SqliteStateBackend)


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def _j(r):
    return json.loads(r.body or b"{}")


# ── Azure Blob ──────────────────────────────────────────────────────────────
class _ByteStoreBlob(az.AzureBlobStore):
    """A store with an external byte store (the appliance's Azurite mirror)."""

    def __init__(self):
        super().__init__()
        self.mirrored, self.external = {}, {}

    def mirror_put(self, container, blob, entry):
        self.mirrored[(container, blob)] = bytes(entry["data"])

    def mirror_delete(self, container, blob):
        self.mirrored.pop((container, blob), None)

    def fetch_bytes(self, container, blob):
        return self.external.get((container, blob))


def azure_blob(make, label):
    st = make()
    acct = "legacyacct"
    r = az.dispatch(st, "PUT", "/c1", {"restype": "container"}, {}, b"", account=acct)
    _check(f"[{label}] explicit-account container create 201", r.status == 201)
    lst = az.dispatch(st, "GET", "/", {"comp": "list"}, {}, b"", account=acct)
    _check(f"[{label}] container listed under its account", b"<Name>c1</Name>" in lst.body)
    other = az.dispatch(st, "GET", "/", {"comp": "list"}, {}, b"", account="otheracct")
    _check(f"[{label}] other account does not see it", b"<Name>c1</Name>" not in other.body)

    # legacy: x-ms-blob-content-type is the blob's content type (SDK ContentSettings / az --content-type)
    up = az.dispatch(st, "PUT", "/c1/d/x.json", {}, {"x-ms-blob-type": "BlockBlob",
                     "content-type": "application/octet-stream",
                     "x-ms-blob-content-type": "application/json", "x-ms-meta-k": "v"},
                     b'{"a": 1234567890}', account=acct)
    _check(f"[{label}] put 201", up.status == 201)
    h = az.dispatch(st, "HEAD", "/c1/d/x.json", {}, {}, b"", account=acct)
    _check(f"[{label}] x-ms-blob-content-type wins", h.headers.get("content-type") == "application/json")
    _check(f"[{label}] x-ms-creation-time on HEAD", bool(h.headers.get("x-ms-creation-time")))
    _check(f"[{label}] metadata round-trips", h.headers.get("x-ms-meta-k") == "v")

    # legacy: suffix range bytes=-N = the last N bytes
    g = az.dispatch(st, "GET", "/c1/d/x.json", {}, {"x-ms-range": "bytes=-4"}, b"", account=acct)
    _check(f"[{label}] suffix range 206", g.status == 206 and g.body == b'890}',
           repr((g.status, g.body)))
    _check(f"[{label}] suffix Content-Range", g.headers.get("content-range") == "bytes 13-16/17",
           g.headers.get("content-range"))
    g = az.dispatch(st, "GET", "/c1/d/x.json", {}, {"range": "bytes=2-5"}, b"", account=acct)
    _check(f"[{label}] explicit range 206", g.status == 206 and g.body == b'a": ')

    # legacy: lease properties in the blob listing
    lb = az.dispatch(st, "GET", "/c1", {"restype": "container", "comp": "list"}, {}, b"", account=acct)
    _check(f"[{label}] listing carries LeaseState", b"<LeaseState>available</LeaseState>" in lb.body)
    _check(f"[{label}] listing carries Creation-Time", b"<Creation-Time>" in lb.body)

    # a fresh instance (persisted substrates) sees container + blob
    st2 = make(reload=True)
    if st2 is not None:
        g = az.dispatch(st2, "GET", "/c1/d/x.json", {}, {}, b"", account=acct)
        _check(f"[{label}] blob survives a fresh store instance", g.status == 200 and g.body.startswith(b'{"a"'))


def azure_blob_byte_store():
    st = _ByteStoreBlob()
    az.dispatch(st, "PUT", "/c", {"restype": "container"}, {}, b"", account="a1")
    az.dispatch(st, "PUT", "/c/b.txt", {}, {"x-ms-blob-type": "BlockBlob"}, b"bytes", account="a1")
    _check("[hooks] put mirrored to the byte store", st.mirrored.get(("a1/c", "b.txt")) == b"bytes")
    az.dispatch(st, "DELETE", "/c/b.txt", {}, {}, b"", account="a1")
    _check("[hooks] delete mirrored", ("a1/c", "b.txt") not in st.mirrored)
    # pre-v4 blob: metadata adopted, bytes only in the external store
    st.container_blobs("a1/c")["old.bin"] = {"data": None, "size": 3, "content_type": "x/y",
                                             "blob_type": "BlockBlob", "etag": '"0x1"',
                                             "last_modified": "Thu, 01 Oct 2026 00:00:00 GMT",
                                             "md5": "", "metadata": {}}
    st.external[("a1/c", "old.bin")] = b"old"
    g = az.dispatch(st, "GET", "/c/old.bin", {}, {}, b"", account="a1")
    _check("[hooks] pre-v4 blob bytes fetched from the byte store", g.status == 200 and g.body == b"old")
    _check("[hooks] no empty Content-MD5 header for adopted blobs", "content-md5" not in g.headers)


# ── GCP Secret Manager ──────────────────────────────────────────────────────
def secret_manager(make, label):
    st = make()
    P = "/v1/projects/p1/secrets"
    # legacy: secretId accepted from the JSON body as well as the query string
    r = gsec.dispatch(st, "POST", P, {}, {}, json.dumps({"secretId": "body-id", "replication": {"automatic": {}}}).encode())
    _check(f"[{label}] secretId from the body", r.status == 200 and _j(r)["name"] == "projects/p1/secrets/body-id")
    for v in (b"one", b"two"):
        gsec.dispatch(st, "POST", P + "/body-id:addVersion", {}, {},
                      json.dumps({"payload": {"data": base64.b64encode(v).decode()}}).encode())
    gsec.dispatch(st, "POST", P + "/body-id/versions/1:disable", {}, {}, b"")
    st2 = make(reload=True) or st
    a = gsec.dispatch(st2, "GET", P + "/body-id/versions/latest:access", {}, {}, b"")
    _check(f"[{label}] latest after reload", a.status == 200 and base64.b64decode(_j(a)["payload"]["data"]) == b"two")
    d = gsec.dispatch(st2, "GET", P + "/body-id/versions/1:access", {}, {}, b"")
    _check(f"[{label}] disabled state survives reload", d.status == 400 and "disabled" in _j(d)["error"]["message"])
    n = gsec.dispatch(st2, "POST", P + "/body-id:addVersion", {}, {},
                      json.dumps({"payload": {"data": base64.b64encode(b"three").decode()}}).encode())
    _check(f"[{label}] version numbering continues after reload",
           _j(n)["name"].endswith("/versions/3"), _j(n).get("name"))
    vl = gsec.dispatch(st2, "GET", P + "/body-id/versions", {}, {}, b"")
    _check(f"[{label}] versions listed newest first", [v["name"][-1] for v in _j(vl)["versions"]] == ["3", "2", "1"])


# ── Cloud KMS ───────────────────────────────────────────────────────────────
def cloud_kms(make, label):
    st = make()
    R = "/v1/projects/p1/locations/global/keyRings"
    gkms.dispatch(st, "POST", R, {"keyRingId": "r1"}, {}, b"{}")
    # SDKs send enums as numbers (enum-encoding=int); legacy console key settings
    c = gkms.dispatch(st, "POST", R + "/r1/cryptoKeys", {"cryptoKeyId": "k1"}, {},
                      json.dumps({"purpose": 1, "labels": {"team": "x"}, "rotationPeriod": "7776000s"}).encode())
    cj = _j(c)
    _check(f"[{label}] numeric purpose normalised", cj["purpose"] == "ENCRYPT_DECRYPT")
    _check(f"[{label}] labels + rotationPeriod on create", cj.get("labels") == {"team": "x"} and cj.get("rotationPeriod") == "7776000s")
    p = gkms.dispatch(st, "PATCH", R + "/r1/cryptoKeys/k1", {"updateMask": "labels,nextRotationTime"}, {},
                      json.dumps({"labels": {"team": "y"}, "nextRotationTime": "2027-01-01T00:00:00Z"}).encode())
    pj = _j(p)
    _check(f"[{label}] PATCH updateMask labels", p.status == 200 and pj["labels"] == {"team": "y"})
    _check(f"[{label}] PATCH nextRotationTime; rotationPeriod untouched",
           pj.get("nextRotationTime") == "2027-01-01T00:00:00Z" and pj.get("rotationPeriod") == "7776000s")
    bad = gkms.dispatch(st, "PATCH", R + "/r1/cryptoKeys/k1", {"updateMask": "purpose"}, {}, b"{}")
    _check(f"[{label}] PATCH immutable field -> 400", bad.status == 400)
    pt = b"crc me"
    e = gkms.dispatch(st, "POST", R + "/r1/cryptoKeys/k1:encrypt", {}, {},
                      json.dumps({"plaintext": base64.b64encode(pt).decode(),
                                  "plaintextCrc32c": str(gkms.crc32c(pt))}).encode())
    ej = _j(e)
    ct = base64.b64decode(ej["ciphertext"])
    _check(f"[{label}] ciphertextCrc32c is CRC32C of the ciphertext", ej["ciphertextCrc32c"] == str(gkms.crc32c(ct)))
    _check(f"[{label}] verifiedPlaintextCrc32c", ej.get("verifiedPlaintextCrc32c") is True)
    _check("crc32c known vector", gkms.crc32c(b"123456789") == 0xE3069283)
    bad = gkms.dispatch(st, "POST", R + "/r1/cryptoKeys/k1:encrypt", {}, {},
                        json.dumps({"plaintext": base64.b64encode(pt).decode(), "plaintextCrc32c": "1"}).encode())
    _check(f"[{label}] wrong plaintextCrc32c -> 400", bad.status == 400)
    st2 = make(reload=True) or st
    rl = gkms.dispatch(st2, "GET", R, {}, {}, b"")
    _check(f"[{label}] key ring survives reload", [x["name"] for x in _j(rl)["keyRings"]] ==
           ["projects/p1/locations/global/keyRings/r1"])
    d = gkms.dispatch(st2, "POST", R + "/r1/cryptoKeys/k1:decrypt", {}, {},
                      json.dumps({"ciphertext": ej["ciphertext"], "ciphertextCrc32c": ej["ciphertextCrc32c"]}).encode())
    dj = _j(d)
    _check(f"[{label}] decrypt after reload", d.status == 200 and base64.b64decode(dj["plaintext"]) == pt)
    _check(f"[{label}] plaintextCrc32c on decrypt", dj.get("plaintextCrc32c") == str(gkms.crc32c(pt)))


class _LegacyKeyStore(InMemoryKeyStore):
    def legacy_decrypt(self, name, blob):
        return b"from-vault" if blob.startswith(b"vault:v1:") else None


def kms_legacy_ciphertext():
    st = _LegacyKeyStore()
    R = "/v1/projects/p1/locations/global/keyRings"
    gkms.dispatch(st, "POST", R, {"keyRingId": "r"}, {}, b"{}")
    gkms.dispatch(st, "POST", R + "/r/cryptoKeys", {"cryptoKeyId": "k"}, {}, b"{}")
    d = gkms.dispatch(st, "POST", R + "/r/cryptoKeys/k:decrypt", {}, {},
                      json.dumps({"ciphertext": base64.b64encode(b"vault:v1:abcd").decode()}).encode())
    _check("[legacy] pre-v4 Vault-transit ciphertext decrypts via legacy_decrypt",
           d.status == 200 and base64.b64decode(_j(d)["plaintext"]) == b"from-vault")
    junk = gkms.dispatch(st, "POST", R + "/r/cryptoKeys/k:decrypt", {}, {},
                         json.dumps({"ciphertext": base64.b64encode(b"garbage").decode()}).encode())
    _check("[legacy] other garbage still rejected", junk.status == 400)


def _persistent(cls, sid):
    be = SqliteStateBackend(":memory:")

    def make(reload=False):
        return cls(be, store_id=sid)
    return make


def _memory(cls):
    holder = {}

    def make(reload=False):
        if reload:
            return None
        holder["s"] = cls()
        return holder["s"]
    return make


def run() -> int:
    print("Azure Blob:")
    azure_blob(_memory(az.AzureBlobStore), "mem")
    azure_blob(_persistent(PersistentAzureBlobStore, "azb"), "sqlite")
    azure_blob_byte_store()
    print("Secret Manager:")
    secret_manager(_memory(InMemoryKvStore), "mem")
    secret_manager(_persistent(PersistentKvStore, "gsec"), "sqlite")
    print("Cloud KMS:")
    cloud_kms(_memory(InMemoryKeyStore), "mem")
    cloud_kms(_persistent(PersistentKeyStore, "gkms"), "sqlite")
    kms_legacy_ciphertext()
    print("\nC0b legacy-parity (Azure Blob / Secret Manager / Cloud KMS cores): ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
