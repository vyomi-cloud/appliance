"""Azure Cosmos DB (SQL / Core API) data-plane conformance — the Azure NoSQL
analogue of test_gcp_storage_core.py / test_dynamodb_core.py.

Same file runs on host CPython and under Pyodide/WASM and must be green on both.
It asserts the native **Cosmos DB REST API (SQL / Core API)** wire semantics
(database / collection / document CRUD, Cosmos system props _rid/_self/_etag/_ts,
SQL SELECT queries, NotFound/Conflict errors) so the native `azure-cosmos` SDK
can drive the core unchanged.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_azure_cosmos_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core import azure_cosmos_core as cosmos
except ImportError:  # pragma: no cover - Pyodide flat layout
    import azure_cosmos_core as cosmos  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def run() -> int:
    st = cosmos.CosmosStore()

    # 1. create database -> 201 with system props
    r = cosmos.dispatch(st, "POST", "/dbs", {},
                        {"content-type": "application/json"},
                        json.dumps({"id": "appdb"}).encode())
    _check("create db 201", r.status == 201)
    db = _jbody(r)
    _check("create db id", db["id"] == "appdb")
    _check("create db _rid", bool(db.get("_rid")))
    _check("create db _self", db.get("_self", "").startswith("dbs/"))
    _check("create db _etag", bool(db.get("_etag")))
    _check("create db _ts int", isinstance(db.get("_ts"), int))

    # 1b. duplicate database -> 409 Conflict
    dup = cosmos.dispatch(st, "POST", "/dbs", {},
                          {"content-type": "application/json"},
                          json.dumps({"id": "appdb"}).encode())
    _check("duplicate db 409", dup.status == 409)
    _check("duplicate db code", _jbody(dup)["code"] == "Conflict")

    # 2. list databases -> {"Databases", "_count"}
    lb = cosmos.dispatch(st, "GET", "/dbs", {}, {}, b"")
    _check("list dbs _count", _jbody(lb)["_count"] == 1)
    _check("list dbs has appdb", any(d["id"] == "appdb" for d in _jbody(lb)["Databases"]))

    # 3. read database
    gd = cosmos.dispatch(st, "GET", "/dbs/appdb", {}, {}, b"")
    _check("read db 200", gd.status == 200 and _jbody(gd)["id"] == "appdb")

    # 4. create collection with partitionKey
    coll_body = {"id": "items", "partitionKey": {"paths": ["/pk"], "kind": "Hash"}}
    cr = cosmos.dispatch(st, "POST", "/dbs/appdb/colls", {},
                         {"content-type": "application/json"},
                         json.dumps(coll_body).encode())
    _check("create coll 201", cr.status == 201)
    coll = _jbody(cr)
    _check("create coll id", coll["id"] == "items")
    _check("create coll partitionKey paths", coll["partitionKey"]["paths"] == ["/pk"])
    _check("create coll _rid", bool(coll.get("_rid")))
    _check("create coll _ts int", isinstance(coll.get("_ts"), int))

    # 5. list collections -> {"DocumentCollections", "_count"}
    lc = cosmos.dispatch(st, "GET", "/dbs/appdb/colls", {}, {}, b"")
    _check("list colls _count", _jbody(lc)["_count"] == 1)
    _check("list colls has items",
           any(c["id"] == "items" for c in _jbody(lc)["DocumentCollections"]))

    # 6. create document -> echoes id + system props
    doc_body = {"id": "doc1", "pk": "p1", "name": "widget", "qty": 7}
    dr = cosmos.dispatch(st, "POST", "/dbs/appdb/colls/items/docs", {},
                         {"content-type": "application/json"},
                         json.dumps(doc_body).encode())
    _check("create doc 201", dr.status == 201)
    doc = _jbody(dr)
    _check("create doc echoes id", doc["id"] == "doc1")
    _check("create doc echoes fields", doc["name"] == "widget" and doc["qty"] == 7)
    _check("create doc _rid", bool(doc.get("_rid")))
    _check("create doc _self", doc.get("_self", "").startswith("dbs/"))
    _check("create doc _etag", bool(doc.get("_etag")))
    _check("create doc _ts int", isinstance(doc.get("_ts"), int))

    # 6b. duplicate document -> 409
    ddup = cosmos.dispatch(st, "POST", "/dbs/appdb/colls/items/docs", {},
                           {"content-type": "application/json"},
                           json.dumps(doc_body).encode())
    _check("duplicate doc 409", ddup.status == 409)

    # 7. read document round-trips
    gdoc = cosmos.dispatch(st, "GET", "/dbs/appdb/colls/items/docs/doc1", {}, {}, b"")
    _check("read doc 200", gdoc.status == 200)
    rd = _jbody(gdoc)
    _check("read doc round-trip id", rd["id"] == "doc1")
    _check("read doc round-trip name", rd["name"] == "widget")
    _check("read doc round-trip qty", rd["qty"] == 7)

    # 8. list documents -> _count
    ld = cosmos.dispatch(st, "GET", "/dbs/appdb/colls/items/docs", {}, {}, b"")
    _check("list docs _count", _jbody(ld)["_count"] == 1)
    _check("list docs has doc1",
           any(d["id"] == "doc1" for d in _jbody(ld)["Documents"]))

    # 9. query SELECT * FROM c returns the doc
    q = cosmos.dispatch(st, "POST", "/dbs/appdb/colls/items/docs", {},
                        {"content-type": "application/query+json",
                         "x-ms-documentdb-isquery": "true"},
                        json.dumps({"query": "SELECT * FROM c"}).encode())
    _check("query 200", q.status == 200)
    qb = _jbody(q)
    _check("query _count 1", qb["_count"] == 1)
    _check("query returns doc1", qb["Documents"][0]["id"] == "doc1")

    # 9b. query with WHERE predicate filters
    cosmos.dispatch(st, "POST", "/dbs/appdb/colls/items/docs", {},
                    {"content-type": "application/json"},
                    json.dumps({"id": "doc2", "pk": "p2", "name": "gadget", "qty": 3}).encode())
    qw = cosmos.dispatch(st, "POST", "/dbs/appdb/colls/items/docs", {},
                         {"x-ms-documentdb-isquery": "true"},
                         json.dumps({"query": "SELECT * FROM c WHERE c.name = 'gadget'"}).encode())
    qwb = _jbody(qw)
    _check("query WHERE _count 1", qwb["_count"] == 1)
    _check("query WHERE match", qwb["Documents"][0]["id"] == "doc2")

    # 9c. expanded SELECT grammar: AND/OR, CONTAINS/STARTSWITH/ENDSWITH, TOP,
    # OFFSET/LIMIT, COUNT/VALUE COUNT aggregate, SELECT VALUE projection.
    cosmos.dispatch(st, "POST", "/dbs/appdb/colls/items/docs", {},
                    {"content-type": "application/json"},
                    json.dumps({"id": "doc3", "pk": "p1", "name": "widget-pro", "qty": 12}).encode())

    def _query(qtext):
        r = cosmos.dispatch(st, "POST", "/dbs/appdb/colls/items/docs", {},
                            {"x-ms-documentdb-isquery": "true"},
                            json.dumps({"query": qtext}).encode())
        return _jbody(r)["Documents"]

    and_ids = sorted(d["id"] for d in _query("SELECT * FROM c WHERE c.pk = 'p1' AND c.qty > 5"))
    _check("query AND", and_ids == ["doc1", "doc3"])

    or_ids = sorted(d["id"] for d in _query("SELECT * FROM c WHERE c.name = 'gadget' OR c.qty = 12"))
    _check("query OR", or_ids == ["doc2", "doc3"])

    contains_ids = sorted(d["id"] for d in _query("SELECT * FROM c WHERE CONTAINS(c.name, 'widget')"))
    _check("query CONTAINS", contains_ids == ["doc1", "doc3"])

    endswith_ids = [d["id"] for d in _query("SELECT * FROM c WHERE ENDSWITH(c.name, 'pro')")]
    _check("query ENDSWITH", endswith_ids == ["doc3"])

    startswith_ids = sorted(d["id"] for d in _query("SELECT * FROM c WHERE STARTSWITH(c.name, 'widget')"))
    _check("query STARTSWITH", startswith_ids == ["doc1", "doc3"])

    top_ids = [d["id"] for d in _query("SELECT TOP 2 * FROM c ORDER BY c.qty DESC")]
    _check("query TOP + ORDER BY", top_ids == ["doc3", "doc1"])

    page_ids = [d["id"] for d in _query("SELECT * FROM c ORDER BY c.qty ASC OFFSET 1 LIMIT 1")]
    _check("query OFFSET/LIMIT", page_ids == ["doc1"])

    count_rows = _query("SELECT COUNT(1) FROM c WHERE c.pk = 'p1'")
    _check("query COUNT", count_rows == [{"$1": 2}])

    value_count_rows = _query("SELECT VALUE COUNT(1) FROM c")
    _check("query VALUE COUNT", value_count_rows == [3])

    value_rows = sorted(_query("SELECT VALUE c.qty FROM c WHERE c.pk = 'p1'"))
    _check("query SELECT VALUE projection", value_rows == [7, 12])

    delpro = cosmos.dispatch(st, "DELETE", "/dbs/appdb/colls/items/docs/doc3", {}, {}, b"")
    _check("cleanup doc3 204", delpro.status == 204)

    # 10. delete document -> 204, then read 404
    deld = cosmos.dispatch(st, "DELETE", "/dbs/appdb/colls/items/docs/doc1", {}, {}, b"")
    _check("delete doc 204", deld.status == 204)
    miss = cosmos.dispatch(st, "GET", "/dbs/appdb/colls/items/docs/doc1", {}, {}, b"")
    _check("deleted doc 404", miss.status == 404 and _jbody(miss)["code"] == "NotFound")

    # 11. delete collection -> 204, then read 404
    delc = cosmos.dispatch(st, "DELETE", "/dbs/appdb/colls/items", {}, {}, b"")
    _check("delete coll 204", delc.status == 204)
    missc = cosmos.dispatch(st, "GET", "/dbs/appdb/colls/items", {}, {}, b"")
    _check("deleted coll 404", missc.status == 404)

    # 12. delete database -> 204, then read 404
    deldb = cosmos.dispatch(st, "DELETE", "/dbs/appdb", {}, {}, b"")
    _check("delete db 204", deldb.status == 204)
    missdb = cosmos.dispatch(st, "GET", "/dbs/appdb", {}, {}, b"")
    _check("deleted db 404", missdb.status == 404 and _jbody(missdb)["code"] == "NotFound")

    print("\nAzure Cosmos DB (SQL API) core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
