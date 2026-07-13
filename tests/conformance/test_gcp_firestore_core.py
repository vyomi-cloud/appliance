"""Firestore document-core conformance — the GCP-NoSQL analogue of
test_gcp_storage_core.py.

Same test runs on host CPython and under Pyodide/WASM and must be green on both.
It asserts the native **Firestore REST API v1** wire semantics (typed value
encoding: stringValue / integerValue / booleanValue / doubleValue / mapValue /
arrayValue, document `name`/`fields`/`createTime`/`updateTime` resource shape,
create-with-documentId + auto-id, PATCH merge, list `{"documents":[...]}`,
NOT_FOUND on a deleted doc, and a basic :runQuery), proving the native
google-cloud-firestore client (transport="rest") can drive the core unchanged.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_firestore_core.py
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
DB_PREFIX = f"/v1/projects/{PROJECT}/databases/(default)/documents"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def run() -> int:
    st = FirestoreStore()

    # 1. create document with explicit documentId -> typed fields round-trip
    fields = {
        "name": {"stringValue": "Alice"},
        "age": {"integerValue": "30"},
        "active": {"booleanValue": True},
        "score": {"doubleValue": 9.5},
        "nickname": {"nullValue": None},
        "address": {"mapValue": {"fields": {
            "city": {"stringValue": "Portland"},
            "zip": {"integerValue": "97201"},
        }}},
        "tags": {"arrayValue": {"values": [
            {"stringValue": "admin"}, {"stringValue": "beta"},
        ]}},
    }
    cr = fs.dispatch(st, "POST", f"{DB_PREFIX}/users", {"documentId": "alice"},
                     {"content-type": "application/json"},
                     json.dumps({"fields": fields}).encode())
    _check("create doc 200", cr.status == 200)
    cd = _jbody(cr)
    _check("create doc name",
           cd["name"] == f"projects/{PROJECT}/databases/(default)/documents/users/alice")
    _check("create doc has createTime", "createTime" in cd and cd["createTime"].endswith("Z"))
    _check("create doc has updateTime", "updateTime" in cd)

    # 2. create duplicate documentId -> 409 ALREADY_EXISTS
    dup = fs.dispatch(st, "POST", f"{DB_PREFIX}/users", {"documentId": "alice"},
                      {}, json.dumps({"fields": {"x": {"stringValue": "y"}}}).encode())
    _check("duplicate doc 409", dup.status == 409)
    _check("duplicate doc ALREADY_EXISTS", _jbody(dup)["error"]["status"] == "ALREADY_EXISTS")

    # 3. get document -> same typed values, exact encoding
    gr = fs.dispatch(st, "GET", f"{DB_PREFIX}/users/alice", {}, {}, b"")
    _check("get doc 200", gr.status == 200)
    gf = _jbody(gr)["fields"]
    _check("stringValue encoding", gf["name"] == {"stringValue": "Alice"})
    _check("integerValue encoding (string wire)", gf["age"] == {"integerValue": "30"})
    _check("booleanValue encoding", gf["active"] == {"booleanValue": True})
    _check("doubleValue encoding", gf["score"] == {"doubleValue": 9.5})
    _check("nullValue encoding", gf["nickname"] == {"nullValue": None})
    _check("mapValue nested fields encoding",
           gf["address"]["mapValue"]["fields"]["city"] == {"stringValue": "Portland"})
    _check("mapValue nested integer encoding",
           gf["address"]["mapValue"]["fields"]["zip"] == {"integerValue": "97201"})
    _check("arrayValue encoding",
           gf["tags"]["arrayValue"]["values"] == [{"stringValue": "admin"}, {"stringValue": "beta"}])

    # 4. auto-id create (no documentId) -> server-generated id in the name
    auto = fs.dispatch(st, "POST", f"{DB_PREFIX}/users", {}, {},
                       json.dumps({"fields": {"name": {"stringValue": "Bob"}}}).encode())
    _check("auto-id create 200", auto.status == 200)
    auto_name = _jbody(auto)["name"]
    _check("auto-id name under users/", "/documents/users/" in auto_name)
    auto_id = auto_name.rsplit("/", 1)[-1]
    _check("auto-id is non-empty", len(auto_id) > 0 and auto_id != "alice")

    # 5. PATCH merge -> updates named field, adds new field, keeps others
    pr = fs.dispatch(st, "PATCH", f"{DB_PREFIX}/users/alice", {}, {},
                     json.dumps({"fields": {
                         "age": {"integerValue": "31"},
                         "email": {"stringValue": "alice@example.com"},
                     }}).encode())
    _check("patch 200", pr.status == 200)
    pf = _jbody(pr)["fields"]
    _check("patch updated field", pf["age"] == {"integerValue": "31"})
    _check("patch added field", pf["email"] == {"stringValue": "alice@example.com"})
    _check("patch kept untouched field", pf["name"] == {"stringValue": "Alice"})
    _check("patch bumped updateTime", _jbody(pr)["updateTime"] >= _jbody(pr)["createTime"])

    # 6. list documents -> {"documents": [...]} with both alice and bob
    lr = fs.dispatch(st, "GET", f"{DB_PREFIX}/users", {}, {}, b"")
    _check("list 200", lr.status == 200)
    listed = _jbody(lr).get("documents", [])
    listed_ids = [d["name"].rsplit("/", 1)[-1] for d in listed]
    _check("list has alice + auto-id", "alice" in listed_ids and auto_id in listed_ids)
    _check("list count == 2", len(listed) == 2)

    # 7. basic :runQuery with an EQUAL fieldFilter
    q = {"structuredQuery": {
        "from": [{"collectionId": "users"}],
        "where": {"fieldFilter": {
            "field": {"fieldPath": "name"},
            "op": "EQUAL",
            "value": {"stringValue": "Alice"},
        }},
    }}
    qr = fs.dispatch(st, "POST", f"{DB_PREFIX}:runQuery", {}, {}, json.dumps(q).encode())
    _check("runQuery 200", qr.status == 200)
    qrows = [row for row in _jbody(qr) if "document" in row]
    _check("runQuery returns exactly the matching doc",
           len(qrows) == 1 and qrows[0]["document"]["name"].endswith("/users/alice"))

    # 7b. runQuery with no where -> all docs in the collection
    qall = fs.dispatch(st, "POST", f"{DB_PREFIX}:runQuery", {}, {},
                       json.dumps({"structuredQuery": {"from": [{"collectionId": "users"}]}}).encode())
    _check("runQuery no-filter returns all", len([r for r in _jbody(qall) if "document" in r]) == 2)

    # 8. delete document -> 200, then get -> 404 NOT_FOUND
    dr = fs.dispatch(st, "DELETE", f"{DB_PREFIX}/users/alice", {}, {}, b"")
    _check("delete 200", dr.status == 200 and _jbody(dr) == {})
    miss = fs.dispatch(st, "GET", f"{DB_PREFIX}/users/alice", {}, {}, b"")
    _check("deleted doc 404", miss.status == 404)
    _check("deleted doc NOT_FOUND status", _jbody(miss)["error"]["status"] == "NOT_FOUND")

    # 9. delete is idempotent (Firestore returns 200 {} on a missing doc)
    dr2 = fs.dispatch(st, "DELETE", f"{DB_PREFIX}/users/alice", {}, {}, b"")
    _check("delete idempotent 200", dr2.status == 200)

    print("\nFirestore document-core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
