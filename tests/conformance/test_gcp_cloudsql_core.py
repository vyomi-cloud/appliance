"""GCP Cloud SQL control-plane conformance — the GCP analogue of test_rds_core.py.

Same test runs on host CPython and under Pyodide/WASM and must be green on both.
It asserts the native **Cloud SQL Admin REST API v1** (v1beta4) wire semantics —
sql#instance / sql#database resources under
`/sql/v1beta4/projects/{project}/instances...`, RUNNABLE state with the
databaseVersion echoed, instance + database insert/list/delete, and the Google
JSON error shape `{"error":{...,"status":"NOT_FOUND"}}` — proving
google-cloud-sql-admin / gcloud sql can drive the control-plane core unchanged.

The data plane (running SQL) is out of scope for this core — it is the shared
SqlStore / PGlite engine (same one rds_core drives), exposed separately.

Run on host:    python3 tests/conformance/test_gcp_cloudsql_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core.sql_store import InMemorySqlStore
    from core import gcp_cloudsql_core as csql
except ImportError:  # pragma: no cover - Pyodide flat layout
    from sql_store import InMemorySqlStore  # type: ignore
    import gcp_cloudsql_core as csql  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


PROJ = "/sql/v1beta4/projects/demo-proj/instances"


def run() -> int:
    st = InMemorySqlStore()

    # 1. insert instance -> 200 sql#instance, RUNNABLE, databaseVersion echoed
    r = csql.dispatch(st, "POST", PROJ, {}, {"content-type": "application/json"},
                      json.dumps({"name": "appdb", "databaseVersion": "POSTGRES_15",
                                  "settings": {"tier": "db-custom-1-3840"}}).encode())
    _check("insert instance 200", r.status == 200)
    inst = _jbody(r)
    _check("insert instance kind", inst["kind"] == "sql#instance")
    _check("insert instance name", inst["name"] == "appdb")
    _check("insert instance RUNNABLE", inst["state"] == "RUNNABLE")
    _check("insert instance databaseVersion echoed", inst["databaseVersion"] == "POSTGRES_15")
    _check("insert instance tier echoed", inst["settings"]["tier"] == "db-custom-1-3840")
    _check("insert instance connectionName", inst["connectionName"] == "demo-proj:us-central1:appdb")

    # 1b. duplicate instance -> 409 ALREADY_EXISTS
    dup = csql.dispatch(st, "POST", PROJ, {}, {"content-type": "application/json"},
                        json.dumps({"name": "appdb"}).encode())
    _check("duplicate instance 409", dup.status == 409)
    _check("duplicate instance status ALREADY_EXISTS", _jbody(dup)["error"]["status"] == "ALREADY_EXISTS")

    # 1c. MySQL databaseVersion echoed
    csql.dispatch(st, "POST", PROJ, {}, {"content-type": "application/json"},
                  json.dumps({"name": "shopdb", "databaseVersion": "MYSQL_8_0"}).encode())

    # 2. get instance
    g = csql.dispatch(st, "GET", PROJ + "/appdb", {}, {}, b"")
    _check("get instance 200", g.status == 200)
    _check("get instance name", _jbody(g)["name"] == "appdb")

    # 3. list instances -> both present
    li = csql.dispatch(st, "GET", PROJ, {}, {}, b"")
    _check("list instances kind", _jbody(li)["kind"] == "sql#instancesList")
    names = sorted(i["name"] for i in _jbody(li).get("items", []))
    _check("list instances has both", names == ["appdb", "shopdb"])
    _check("list mysql version", any(i["databaseVersion"] == "MYSQL_8_0"
                                     for i in _jbody(li)["items"]))

    # 4. insert database -> 200 sql#database
    dbr = csql.dispatch(st, "POST", PROJ + "/appdb/databases", {},
                        {"content-type": "application/json"},
                        json.dumps({"name": "orders"}).encode())
    _check("insert database 200", dbr.status == 200)
    db = _jbody(dbr)
    _check("insert database kind", db["kind"] == "sql#database")
    _check("insert database name", db["name"] == "orders")
    _check("insert database instance", db["instance"] == "appdb")

    # 4b. a second database
    csql.dispatch(st, "POST", PROJ + "/appdb/databases", {},
                  {"content-type": "application/json"},
                  json.dumps({"name": "inventory"}).encode())

    # 4c. insert database on missing instance -> 404 NOT_FOUND
    nf_db = csql.dispatch(st, "POST", PROJ + "/ghost/databases", {},
                          {"content-type": "application/json"},
                          json.dumps({"name": "x"}).encode())
    _check("insert db on missing instance 404", nf_db.status == 404
           and _jbody(nf_db)["error"]["status"] == "NOT_FOUND")

    # 5. list databases -> both present
    ld = csql.dispatch(st, "GET", PROJ + "/appdb/databases", {}, {}, b"")
    _check("list databases kind", _jbody(ld)["kind"] == "sql#databasesList")
    dbnames = sorted(d["name"] for d in _jbody(ld).get("items", []))
    _check("list databases has both", dbnames == ["inventory", "orders"])

    # 6. delete database -> then list excludes it
    deld = csql.dispatch(st, "DELETE", PROJ + "/appdb/databases/orders", {}, {}, b"")
    _check("delete database 200", deld.status == 200)
    ld2 = csql.dispatch(st, "GET", PROJ + "/appdb/databases", {}, {}, b"")
    dbnames2 = sorted(d["name"] for d in _jbody(ld2).get("items", []))
    _check("list databases excludes deleted", dbnames2 == ["inventory"])
    missd = csql.dispatch(st, "DELETE", PROJ + "/appdb/databases/orders", {}, {}, b"")
    _check("delete missing database 404", missd.status == 404
           and _jbody(missd)["error"]["status"] == "NOT_FOUND")

    # 7. delete instance -> then get 404 NOT_FOUND
    deli = csql.dispatch(st, "DELETE", PROJ + "/appdb", {}, {}, b"")
    _check("delete instance 200", deli.status == 200)
    gone = csql.dispatch(st, "GET", PROJ + "/appdb", {}, {}, b"")
    _check("deleted instance get 404", gone.status == 404)
    _check("deleted instance status NOT_FOUND", _jbody(gone)["error"]["status"] == "NOT_FOUND")

    # 7b. list no longer includes it
    li2 = csql.dispatch(st, "GET", PROJ, {}, {}, b"")
    names2 = sorted(i["name"] for i in _jbody(li2).get("items", []))
    _check("list excludes deleted instance", names2 == ["shopdb"])

    print("\nRESULT: PASS — GCP Cloud SQL control-plane core conforms "
          "(native Cloud SQL Admin REST wire) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
