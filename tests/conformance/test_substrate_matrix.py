"""Substrate matrix — the v2.4.0 anti-drift gate.

Runs the SHARED conformance cores against the file-backed (sqlite) substrate and
proves the durability contract: after the core mutates state through the seam, a
FRESH store instance loading the same backend must see that state. This is what
guarantees a core behaves identically on in-memory (Nano) and a real backend
(Pro/Max) — a core change that breaks the backed substrate fails here.

The killer case is KMS: the key material must survive to the fresh store, or the
fresh store cannot decrypt what the first one encrypted.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_substrate_matrix.py
Run in Pyodide: loaded by the wasm/ harness (pure stdlib incl. sqlite3).
"""
import base64
import json

try:
    from core.persistent_store import (
        SqliteStateBackend, PersistentObjectStore, PersistentKvStore,
        PersistentNoSqlStore, PersistentKeyStore, PersistentMessagingStore,
        PersistentIamStore, PersistentFirestoreStore)
    from core import gcp_storage_core as gcs
    from core import gcp_secretmanager_core as sec
    from core import gcp_kms_core as kms
    from core import gcp_pubsub_core as ps
    from core import gcp_iam_core as iam
    from core import dynamodb_core as ddb
    from core import gcp_firestore_core as fs
    from core import azure_servicebus_core as sb
except ImportError:  # pragma: no cover - Pyodide flat layout
    from persistent_store import (  # type: ignore
        SqliteStateBackend, PersistentObjectStore, PersistentKvStore,
        PersistentNoSqlStore, PersistentKeyStore, PersistentMessagingStore,
        PersistentIamStore, PersistentFirestoreStore)
    import gcp_storage_core as gcs  # type: ignore
    import gcp_secretmanager_core as sec  # type: ignore
    import gcp_kms_core as kms  # type: ignore
    import gcp_pubsub_core as ps  # type: ignore
    import gcp_iam_core as iam  # type: ignore
    import dynamodb_core as ddb  # type: ignore
    import gcp_firestore_core as fs  # type: ignore
    import azure_servicebus_core as sb  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _j(resp):
    return json.loads(resp.body.decode("utf-8")) if resp.body else {}


P = "/v1/projects/demo"


def run() -> int:
    be = SqliteStateBackend(":memory:")   # one shared file-backed DB

    # ── OBJECT STORE (GCS core) — write on store A, read on fresh store B ──
    a = PersistentObjectStore(be)
    gcs.dispatch(a, "POST", "/storage/v1/b", {}, {}, json.dumps({"name": "b1"}).encode())
    gcs.dispatch(a, "POST", "/upload/storage/v1/b/b1/o", {"uploadType": "media", "name": "k"},
                 {"content-type": "text/plain"}, b"durable-bytes")
    b = PersistentObjectStore(be)   # fresh instance, same backend
    dl = gcs.dispatch(b, "GET", "/storage/v1/b/b1/o/k", {"alt": "media"}, {}, b"")
    _check("object: bytes survive a fresh backed store", dl.body == b"durable-bytes")

    # ── KV / SECRETS (Secret Manager core) ──
    a = PersistentKvStore(be)
    sec.dispatch(a, "POST", f"{P}/secrets", {"secretId": "s1"}, {}, json.dumps({"replication": {"automatic": {}}}).encode())
    sec.dispatch(a, "POST", f"{P}/secrets/s1:addVersion", {}, {},
                 json.dumps({"payload": {"data": base64.b64encode(b"topsecret").decode()}}).encode())
    b = PersistentKvStore(be)
    acc = _j(sec.dispatch(b, "GET", f"{P}/secrets/s1/versions/latest:access", {}, {}, b""))
    _check("secret: value survives a fresh backed store",
           base64.b64decode(acc["payload"]["data"]) == b"topsecret")

    # ── KMS (the killer: key material + crypto must survive) ──
    a = PersistentKeyStore(be)
    kms.dispatch(a, "POST", f"{P}/locations/global/keyRings", {"keyRingId": "r"}, {}, b"{}")
    kms.dispatch(a, "POST", f"{P}/locations/global/keyRings/r/cryptoKeys", {"cryptoKeyId": "k"},
                 {}, json.dumps({"purpose": "ENCRYPT_DECRYPT"}).encode())
    enc = _j(kms.dispatch(a, "POST", f"{P}/locations/global/keyRings/r/cryptoKeys/k:encrypt", {}, {},
                          json.dumps({"plaintext": base64.b64encode(b"cipher-me").decode()}).encode()))
    b = PersistentKeyStore(be)   # fresh store — must still be able to decrypt
    dec = _j(kms.dispatch(b, "POST", f"{P}/locations/global/keyRings/r/cryptoKeys/k:decrypt", {}, {},
                          json.dumps({"ciphertext": enc["ciphertext"]}).encode()))
    _check("kms: fresh backed store decrypts (key material persisted)",
           base64.b64decode(dec["plaintext"]) == b"cipher-me")

    # ── MESSAGING (Pub/Sub core) ──
    a = PersistentMessagingStore(be)
    ps.dispatch(a, "PUT", f"{P}/topics/t", {}, {}, b"{}")
    ps.dispatch(a, "PUT", f"{P}/subscriptions/sub", {}, {}, json.dumps({"topic": "projects/demo/topics/t"}).encode())
    ps.dispatch(a, "POST", f"{P}/topics/t:publish", {}, {},
                json.dumps({"messages": [{"data": base64.b64encode(b"msg1").decode()}]}).encode())
    b = PersistentMessagingStore(be)
    pull = _j(ps.dispatch(b, "POST", f"{P}/subscriptions/sub:pull", {}, {}, json.dumps({"maxMessages": 10}).encode()))
    msgs = pull.get("receivedMessages", [])
    _check("messaging: published message survives a fresh backed store",
           msgs and base64.b64decode(msgs[0]["message"]["data"]) == b"msg1")

    # ── IAM (service accounts + policy) ──
    a = PersistentIamStore(be)
    iam.dispatch(a, "POST", f"{P}/serviceAccounts", {}, {},
                 json.dumps({"accountId": "svc", "serviceAccount": {"displayName": "S"}}).encode())
    b = PersistentIamStore(be)
    sa = iam.dispatch(b, "GET", f"{P}/serviceAccounts/svc@demo.iam.gserviceaccount.com", {}, {}, b"")
    _check("iam: service account survives a fresh backed store", sa.status == 200)

    # ── NOSQL (DynamoDB core, X-Amz-Target wire) ──
    a = PersistentNoSqlStore(be)
    ddb.dispatch(a, "DynamoDB_20120810.CreateTable",
                 {"TableName": "T", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                  "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]})
    ddb.dispatch(a, "DynamoDB_20120810.PutItem", {"TableName": "T", "Item": {"id": {"S": "1"}, "v": {"N": "42"}}})
    b = PersistentNoSqlStore(be)
    got = ddb.dispatch(b, "DynamoDB_20120810.GetItem", {"TableName": "T", "Key": {"id": {"S": "1"}}})
    gb = got.body
    gb = json.loads(gb.decode("utf-8")) if isinstance(gb, (bytes, bytearray)) else gb
    item = (gb or {}).get("Item", {})
    _check("nosql: item survives a fresh backed store", item.get("v", {}).get("N") == "42")

    # ── FIRESTORE (documents) — Phase 4: durable on the accepted backing ──
    fdb = "/v1/projects/demo/databases/(default)/documents"
    a = PersistentFirestoreStore(be)
    fs.dispatch(a, "POST", f"{fdb}/users", {"documentId": "alice"},
                {"content-type": "application/json"},
                json.dumps({"fields": {"age": {"integerValue": "30"}}}).encode())
    b = PersistentFirestoreStore(be)   # fresh instance, same backend
    doc = _j(fs.dispatch(b, "GET", f"{fdb}/users/alice", {}, {}, b""))
    _check("firestore: document survives a fresh backed store",
           doc.get("fields", {}).get("age", {}).get("integerValue") == "30")

    # ── SERVICE BUS (Azure topics) — Phase 6: durable fan-out on the backing ──
    a = PersistentMessagingStore(be, store_id="azsb")
    sb.dispatch(a, "PUT", "/orders", {}, {}, b"")
    sb.dispatch(a, "PUT", "/orders/subscriptions/billing", {}, {}, b"")
    sb.dispatch(a, "POST", "/orders/messages", {}, {"content-type": "text/plain"}, b"sb-durable")
    b = PersistentMessagingStore(be, store_id="azsb")
    got = sb.dispatch(b, "DELETE", "/orders/subscriptions/billing/messages/head", {}, {}, b"")
    _check("servicebus: topic message survives a fresh backed store",
           got.status == 200 and got.body == b"sb-durable")

    print("\nSUBSTRATE MATRIX: ALL GREEN — shared cores are durable on the backed substrate")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
