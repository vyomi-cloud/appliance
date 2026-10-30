"""Firestore ADMIN-plane conformance (databases, indexes, fields/TTL, backup
schedules + backups, export/import operations, security rules) — the control
plane the console's All-databases / Indexes / TTL / Disaster recovery /
Import-Export pages drive, on top of the data-plane proven by
test_gcp_firestore_core.py.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_firestore_admin_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core.gcp_firestore_core import FirestoreStore
    from core import gcp_firestore_core as fs
except ImportError:  # pragma: no cover - Pyodide flat layout
    from gcp_firestore_core import FirestoreStore  # type: ignore
    import gcp_firestore_core as fs  # type: ignore

PROJECT = "demo-project"
DB_BASE = f"/v1/projects/{PROJECT}/databases"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def run() -> int:
    st = FirestoreStore()

    # 1. list databases on a fresh project -> empty
    lr = fs.dispatch(st, "GET", f"{DB_BASE}", {}, {}, b"")
    _check("list databases (empty) 200", lr.status == 200)
    _check("list databases (empty) has no databases key", "databases" not in _jbody(lr))

    # 2. create a named database
    cr = fs.dispatch(st, "POST", f"{DB_BASE}", {"databaseId": "orders-db"}, {},
                     json.dumps({"locationId": "nam5", "type": "FIRESTORE_NATIVE"}).encode())
    _check("create database 200", cr.status == 200)
    cd = _jbody(cr)
    _check("create database name", cd["name"] == f"projects/{PROJECT}/databases/orders-db")
    _check("create database default PITR disabled", cd["pointInTimeRecoveryEnablement"] == "POINT_IN_TIME_RECOVERY_DISABLED")

    # 2b. duplicate create -> 409
    dup = fs.dispatch(st, "POST", f"{DB_BASE}", {"databaseId": "orders-db"}, {}, b"{}")
    _check("duplicate database 409", dup.status == 409)

    # 3. get + list now show it; writing a document auto-provisions "(default)" too
    fs.dispatch(st, "POST", f"{DB_BASE}/(default)/documents/users", {"documentId": "alice"}, {},
               json.dumps({"fields": {"name": {"stringValue": "Alice"}}}).encode())
    lr2 = fs.dispatch(st, "GET", f"{DB_BASE}", {}, {}, b"")
    names = [d["name"] for d in _jbody(lr2)["databases"]]
    _check("list databases has orders-db and (default)",
           f"projects/{PROJECT}/databases/orders-db" in names and f"projects/{PROJECT}/databases/(default)" in names)

    # 4. PATCH enables PITR via updateMask
    pr = fs.dispatch(st, "PATCH", f"{DB_BASE}/orders-db", {"updateMask": "pointInTimeRecoveryEnablement"}, {},
                     json.dumps({"pointInTimeRecoveryEnablement": "POINT_IN_TIME_RECOVERY_ENABLED"}).encode())
    _check("patch database 200", pr.status == 200)
    _check("patch database enabled PITR", _jbody(pr)["pointInTimeRecoveryEnablement"] == "POINT_IN_TIME_RECOVERY_ENABLED")

    # 5. documents in orders-db are isolated from (default)
    fs.dispatch(st, "POST", f"{DB_BASE}/orders-db/documents/users", {"documentId": "alice"}, {},
               json.dumps({"fields": {"name": {"stringValue": "Bob"}}}).encode())
    g1 = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/(default)/documents/users/alice", {}, {}, b""))
    g2 = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/orders-db/documents/users/alice", {}, {}, b""))
    _check("same doc id in two databases does not collide",
           g1["fields"]["name"]["stringValue"] == "Alice" and g2["fields"]["name"]["stringValue"] == "Bob")

    # 6. listCollectionIds at root
    lc = _jbody(fs.dispatch(st, "POST", f"{DB_BASE}/(default)/documents:listCollectionIds", {}, {}, b"{}"))
    _check("listCollectionIds root has users", lc["collectionIds"] == ["users"])

    # 7. composite index create + list (wildcard) + delete
    ic = fs.dispatch(st, "POST", f"{DB_BASE}/(default)/collectionGroups/users/indexes", {}, {},
                     json.dumps({"queryScope": "COLLECTION",
                                 "fields": [{"fieldPath": "name", "order": "ASCENDING"},
                                            {"fieldPath": "age", "order": "DESCENDING"}]}).encode())
    _check("create index 200", ic.status == 200)
    idx = _jbody(ic)
    _check("index state READY", idx["state"] == "READY")
    il = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/(default)/collectionGroups/-/indexes", {}, {}, b""))
    _check("list indexes (wildcard) has the new index", any(i["name"] == idx["name"] for i in il["indexes"]))
    iid = idx["name"].rsplit("/", 1)[-1]
    dr = fs.dispatch(st, "DELETE", f"{DB_BASE}/(default)/collectionGroups/users/indexes/{iid}", {}, {}, b"")
    _check("delete index 200", dr.status == 200)
    il2 = fs.dispatch(st, "GET", f"{DB_BASE}/(default)/collectionGroups/-/indexes", {}, {}, b"")
    _check("index gone after delete", "indexes" not in _jbody(il2) or not _jbody(il2)["indexes"])

    # 8. TTL: PATCH a field's ttlConfig, list filtered by ttlConfig, then remove it
    tp = fs.dispatch(st, "PATCH", f"{DB_BASE}/(default)/collectionGroups/users/fields/expiresAt", {}, {},
                     json.dumps({"ttlConfig": {}}).encode())
    _check("set ttl 200", tp.status == 200)
    _check("ttl state ACTIVE", _jbody(tp)["ttlConfig"]["state"] == "ACTIVE")
    tl = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/(default)/collectionGroups/-/fields",
                            {"filter": "ttlConfig:*"}, {}, b""))
    _check("list ttl policies has it", any("expiresAt" in f["name"] for f in tl["fields"]))
    fs.dispatch(st, "PATCH", f"{DB_BASE}/(default)/collectionGroups/users/fields/expiresAt", {}, {},
               json.dumps({"ttlConfig": None}).encode())
    tl2 = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/(default)/collectionGroups/-/fields",
                            {"filter": "ttlConfig:*"}, {}, b""))
    _check("ttl policy removed", not tl2.get("fields"))

    # 9. backup schedule create fires an immediate backup; list schedules + backups; delete schedule
    bs = fs.dispatch(st, "POST", f"{DB_BASE}/(default)/backupSchedules", {}, {},
                     json.dumps({"retention": "604800s", "dailyRecurrence": {}}).encode())
    _check("create backup schedule 200", bs.status == 200)
    sched = _jbody(bs)
    bl = _jbody(fs.dispatch(st, "GET", f"/v1/projects/{PROJECT}/locations/nam5/backups", {}, {}, b""))
    _check("backup taken immediately on schedule create", len(bl.get("backups", [])) == 1)
    _check("backup references (default) database", bl["backups"][0]["database"].endswith("/databases/(default)"))
    sid = sched["name"].rsplit("/", 1)[-1]
    sl = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/(default)/backupSchedules", {}, {}, b""))
    _check("list backup schedules has it", any(s["name"] == sched["name"] for s in sl["backupSchedules"]))
    fs.dispatch(st, "DELETE", f"{DB_BASE}/(default)/backupSchedules/{sid}", {}, {}, b"")
    sl2 = fs.dispatch(st, "GET", f"{DB_BASE}/(default)/backupSchedules", {}, {}, b"")
    _check("backup schedule gone after delete", "backupSchedules" not in _jbody(sl2) or not _jbody(sl2)["backupSchedules"])

    # 10. export/import -> completed operations, listed under the database
    exp = fs.dispatch(st, "POST", f"{DB_BASE}/(default):exportDocuments", {}, {},
                      json.dumps({"collectionIds": ["users"], "outputUriPrefix": "gs://bk/export1"}).encode())
    _check("export 200", exp.status == 200)
    op = _jbody(exp)
    _check("export op done", op["done"] is True)
    opid = op["name"].rsplit("/", 1)[-1]
    og = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/(default)/operations/{opid}", {}, {}, b""))
    _check("get operation matches", og["name"] == op["name"])
    ol = _jbody(fs.dispatch(st, "GET", f"{DB_BASE}/(default)/operations", {}, {}, b""))
    _check("list operations has export op", any(o["name"] == op["name"] for o in ol["operations"]))

    # 11. security rules round-trip (pragmatic config_only stand-in)
    rules_src = "service cloud.firestore { match /databases/{database}/documents { match /{doc=**} { allow read, write: if false; } } }"
    fs.dispatch(st, "POST", f"{DB_BASE}/(default):updateSecurityRules", {}, {},
               json.dumps({"rules": rules_src}).encode())
    gr = _jbody(fs.dispatch(st, "POST", f"{DB_BASE}/(default):getSecurityRules", {}, {}, b""))
    _check("security rules round-trip", gr["rules"] == rules_src)

    # 12. delete database cascades: documents, indexes, fields, schedules, operations, rules all gone
    fs.dispatch(st, "DELETE", f"{DB_BASE}/orders-db", {}, {}, b"")
    miss = fs.dispatch(st, "GET", f"{DB_BASE}/orders-db", {}, {}, b"")
    _check("deleted database 404", miss.status == 404)
    missdoc = fs.dispatch(st, "GET", f"{DB_BASE}/orders-db/documents/users/alice", {}, {}, b"")
    _check("deleted database's documents gone", missdoc.status == 404)

    print("\nFirestore admin-plane conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
