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

    # 1. insert instance -> 200 sql#operation; get -> sql#instance, RUNNABLE, databaseVersion echoed
    r = csql.dispatch(st, "POST", PROJ, {}, {"content-type": "application/json"},
                      json.dumps({"name": "appdb", "databaseVersion": "POSTGRES_15",
                                  "settings": {"tier": "db-custom-1-3840"}}).encode())
    _check("insert instance 200", r.status == 200)
    op = _jbody(r)   # native instances.insert returns an Operation, not the instance
    _check("insert returns sql#operation", op["kind"] == "sql#operation")
    _check("insert operation DONE/CREATE", op["status"] == "DONE" and op["operationType"] == "CREATE")
    _check("insert operation targetId", op["targetId"] == "appdb")
    r = csql.dispatch(st, "GET", f"{PROJ}/appdb", {}, {}, b"")
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

    # 8. PATCH instance settings -> merged, operation returned
    pt = csql.dispatch(st, "PATCH", PROJ + "/shopdb", {}, {"content-type": "application/json"},
                       json.dumps({"settings": {"tier": "db-custom-2-7680",
                                                "ipConfiguration": {"ipv4Enabled": False}}}).encode())
    _check("patch instance 200", pt.status == 200)
    _check("patch instance op kind", _jbody(pt)["kind"] == "sql#operation")
    shopdb = _jbody(csql.dispatch(st, "GET", PROJ + "/shopdb", {}, {}, b""))
    _check("patch merged tier", shopdb["settings"]["tier"] == "db-custom-2-7680")
    _check("patch merged ipv4Enabled", shopdb["settings"]["ipConfiguration"]["ipv4Enabled"] is False)

    # 8b. stop via activationPolicy=NEVER, start again
    csql.dispatch(st, "PATCH", PROJ + "/shopdb", {}, {"content-type": "application/json"},
                  json.dumps({"settings": {"activationPolicy": "NEVER"}}).encode())
    stopped = _jbody(csql.dispatch(st, "GET", PROJ + "/shopdb", {}, {}, b""))
    _check("stop sets STOPPED", stopped["state"] == "STOPPED")
    csql.dispatch(st, "PATCH", PROJ + "/shopdb", {}, {"content-type": "application/json"},
                  json.dumps({"settings": {"activationPolicy": "ALWAYS"}}).encode())
    started = _jbody(csql.dispatch(st, "GET", PROJ + "/shopdb", {}, {}, b""))
    _check("start sets RUNNABLE", started["state"] == "RUNNABLE")

    # 8c. restart (colon RPC)
    rs = csql.dispatch(st, "POST", PROJ + "/shopdb:restart", {}, {}, b"")
    _check("restart 200", rs.status == 200)
    _check("restart op type", _jbody(rs)["operationType"] == "RESTART")

    # 9. users: insert, list, update password, delete
    uins = csql.dispatch(st, "POST", PROJ + "/shopdb/users", {}, {"content-type": "application/json"},
                         json.dumps({"name": "appuser", "password": "s3cret", "host": "%"}).encode())
    _check("insert user 200", uins.status == 200)
    _check("insert user kind", _jbody(uins)["kind"] == "sql#user")
    dup_u = csql.dispatch(st, "POST", PROJ + "/shopdb/users", {}, {"content-type": "application/json"},
                         json.dumps({"name": "appuser", "host": "%"}).encode())
    _check("duplicate user 409", dup_u.status == 409)
    ulist = csql.dispatch(st, "GET", PROJ + "/shopdb/users", {}, {}, b"")
    _check("list users has appuser", any(u["name"] == "appuser" for u in _jbody(ulist).get("items", [])))
    uupd = csql.dispatch(st, "PUT", PROJ + "/shopdb/users", {"name": "appuser", "host": "%"}, {}, b"{}")
    _check("update user 200", uupd.status == 200)
    udel = csql.dispatch(st, "DELETE", PROJ + "/shopdb/users", {"name": "appuser", "host": "%"}, {}, b"")
    _check("delete user 200", udel.status == 200)
    ulist2 = csql.dispatch(st, "GET", PROJ + "/shopdb/users", {}, {}, b"")
    _check("list users excludes deleted", not any(u["name"] == "appuser" for u in _jbody(ulist2).get("items", [])))
    ndel = csql.dispatch(st, "DELETE", PROJ + "/shopdb/users", {"name": "ghost", "host": "%"}, {}, b"")
    _check("delete missing user 404", ndel.status == 404)

    # 10. backupRuns: insert, list, get, delete
    bins = csql.dispatch(st, "POST", PROJ + "/shopdb/backupRuns", {}, {"content-type": "application/json"},
                         json.dumps({"description": "manual"}).encode())
    _check("insert backup 200", bins.status == 200)
    backup = _jbody(bins)
    _check("insert backup kind", backup["kind"] == "sql#backupRun")
    blist = csql.dispatch(st, "GET", PROJ + "/shopdb/backupRuns", {}, {}, b"")
    _check("list backups has one", len(_jbody(blist).get("items", [])) == 1)
    bget = csql.dispatch(st, "GET", PROJ + f"/shopdb/backupRuns/{backup['id']}", {}, {}, b"")
    _check("get backup 200", bget.status == 200)
    bdel = csql.dispatch(st, "DELETE", PROJ + f"/shopdb/backupRuns/{backup['id']}", {}, {}, b"")
    _check("delete backup 200", bdel.status == 200)
    blist2 = csql.dispatch(st, "GET", PROJ + "/shopdb/backupRuns", {}, {}, b"")
    _check("list backups now empty", not _jbody(blist2).get("items"))
    bmiss = csql.dispatch(st, "GET", PROJ + f"/shopdb/backupRuns/{backup['id']}", {}, {}, b"")
    _check("get deleted backup 404", bmiss.status == 404)

    # 11. operations: project-wide log accumulates, filterable by instance
    ops = csql.dispatch(st, "GET", "/sql/v1beta4/projects/demo-proj/operations", {"instance": "shopdb"}, {}, b"")
    _check("list operations 200", ops.status == 200)
    op_types = [o["operationType"] for o in _jbody(ops).get("items", [])]
    _check("operations include patch/restart/user/backup ops",
           {"UPDATE", "RESTART", "CREATE_USER", "DELETE_USER", "BACKUP_VOLUME", "DELETE_BACKUP"} <= set(op_types))
    one_op = _jbody(ops)["items"][0]
    opget = csql.dispatch(st, "GET", f"/sql/v1beta4/projects/demo-proj/operations/{one_op['name']}", {}, {}, b"")
    _check("get single operation 200", opget.status == 200)

    # 12. read replica: masterInstanceName creates a replica instance
    csql.dispatch(st, "POST", PROJ + "/shopdb/databases", {}, {"content-type": "application/json"},
                  json.dumps({"name": "billing"}).encode())
    rep = csql.dispatch(st, "POST", PROJ, {}, {"content-type": "application/json"},
                        json.dumps({"name": "shopdb-replica", "masterInstanceName": "shopdb"}).encode())
    _check("insert replica 200", rep.status == 200)
    _check("insert replica operation CREATE_REPLICA", _jbody(rep)["operationType"] == "CREATE_REPLICA")
    rep_body = _jbody(csql.dispatch(st, "GET", PROJ + "/shopdb-replica", {}, {}, b""))
    _check("replica instanceType", rep_body["instanceType"] == "READ_REPLICA_INSTANCE")
    _check("replica masterInstanceName", rep_body["masterInstanceName"] == "shopdb")
    rep_missing_master = csql.dispatch(st, "POST", PROJ, {}, {"content-type": "application/json"},
                                       json.dumps({"name": "x", "masterInstanceName": "ghost"}).encode())
    _check("replica of missing master 404", rep_missing_master.status == 404)

    # 12b. replica seeded from the primary's CURRENT databases at creation time
    rep_dbs = sorted(d["name"] for d in _jbody(
        csql.dispatch(st, "GET", PROJ + "/shopdb-replica/databases", {}, {}, b"")).get("items", []))
    _check("replica seeded with primary's existing database", rep_dbs == ["billing"])

    # 12c. a database created on the primary AFTER the replica exists mirrors across
    csql.dispatch(st, "POST", PROJ + "/shopdb/databases", {}, {"content-type": "application/json"},
                  json.dumps({"name": "catalog"}).encode())
    rep_dbs2 = sorted(d["name"] for d in _jbody(
        csql.dispatch(st, "GET", PROJ + "/shopdb-replica/databases", {}, {}, b"")).get("items", []))
    _check("database added on primary mirrors to replica", rep_dbs2 == ["billing", "catalog"])

    # 12d. a user created on the primary mirrors across too; deletes mirror as well
    csql.dispatch(st, "POST", PROJ + "/shopdb/users", {}, {"content-type": "application/json"},
                  json.dumps({"name": "repluser", "host": "%"}).encode())
    rep_users = _jbody(csql.dispatch(st, "GET", PROJ + "/shopdb-replica/users", {}, {}, b"")).get("items", [])
    _check("user added on primary mirrors to replica", any(u["name"] == "repluser" for u in rep_users))
    csql.dispatch(st, "DELETE", PROJ + "/shopdb/databases/catalog", {}, {}, b"")
    rep_dbs3 = sorted(d["name"] for d in _jbody(
        csql.dispatch(st, "GET", PROJ + "/shopdb-replica/databases", {}, {}, b"")).get("items", []))
    _check("database deleted on primary mirrors to replica", rep_dbs3 == ["billing"])

    # 12e. a primary with live replicas can't be deleted until they are deleted first
    blocked = csql.dispatch(st, "DELETE", PROJ + "/shopdb", {}, {}, b"")
    _check("delete primary with replicas 400", blocked.status == 400
           and _jbody(blocked)["error"]["status"] == "FAILED_PRECONDITION")
    csql.dispatch(st, "DELETE", PROJ + "/shopdb-replica", {}, {}, b"")

    # 13. backupRuns capture a snapshot of databases/users; restoreBackup replays it
    csql.dispatch(st, "POST", PROJ + "/shopdb/databases", {},
                  {"content-type": "application/json"}, json.dumps({"name": "willbegone"}).encode())
    bk = _jbody(csql.dispatch(st, "POST", PROJ + "/shopdb/backupRuns", {},
                              {"content-type": "application/json"},
                              json.dumps({"description": "pre-delete"}).encode()))
    csql.dispatch(st, "DELETE", PROJ + "/shopdb/databases/willbegone", {}, {}, b"")
    gone = sorted(d["name"] for d in _jbody(
        csql.dispatch(st, "GET", PROJ + "/shopdb/databases", {}, {}, b"")).get("items", []))
    _check("database gone before restore", "willbegone" not in gone)
    restore = csql.dispatch(st, "POST", PROJ + "/shopdb:restoreBackup", {}, {"content-type": "application/json"},
                            json.dumps({"restoreBackupContext": {"backupRunId": bk["id"]}}).encode())
    _check("restoreBackup 200", restore.status == 200)
    _check("restoreBackup op kind/type", _jbody(restore)["kind"] == "sql#operation"
           and _jbody(restore)["operationType"] == "RESTORE_VOLUME")
    restored = sorted(d["name"] for d in _jbody(
        csql.dispatch(st, "GET", PROJ + "/shopdb/databases", {}, {}, b"")).get("items", []))
    _check("restoreBackup brings back the deleted database", "willbegone" in restored)
    bad_restore = csql.dispatch(st, "POST", PROJ + "/shopdb:restoreBackup", {}, {"content-type": "application/json"},
                                json.dumps({"restoreBackupContext": {"backupRunId": "999999"}}).encode())
    _check("restoreBackup unknown backup 404", bad_restore.status == 404)

    # 14. Connections enforcement (gcp.sql.connections): ipConfiguration drives ipAddresses,
    # not just stores it — a disabled Public IP really removes the PRIMARY address.
    csql.dispatch(st, "POST", PROJ, {}, {"content-type": "application/json"},
                  json.dumps({"name": "netdb"}).encode())
    netdb = _jbody(csql.dispatch(st, "GET", PROJ + "/netdb", {}, {}, b""))
    _check("default instance has a PRIMARY ip", any(a["type"] == "PRIMARY" for a in netdb["ipAddresses"]))
    _check("default instance has no PRIVATE ip", not any(a["type"] == "PRIVATE" for a in netdb["ipAddresses"]))
    csql.dispatch(st, "PATCH", PROJ + "/netdb", {}, {"content-type": "application/json"},
                  json.dumps({"settings": {"ipConfiguration": {"ipv4Enabled": False}}}).encode())
    netdb2 = _jbody(csql.dispatch(st, "GET", PROJ + "/netdb", {}, {}, b""))
    _check("ipv4Enabled=False removes the PRIMARY ip", not any(a["type"] == "PRIMARY" for a in netdb2["ipAddresses"]))
    csql.dispatch(st, "PATCH", PROJ + "/netdb", {}, {"content-type": "application/json"},
                  json.dumps({"settings": {"ipConfiguration": {
                      "privateNetwork": "projects/demo-proj/global/networks/default"}}}).encode())
    netdb3 = _jbody(csql.dispatch(st, "GET", PROJ + "/netdb", {}, {}, b""))
    _check("privateNetwork set adds a PRIVATE ip", any(a["type"] == "PRIVATE" for a in netdb3["ipAddresses"]))
    _check("ipv4Enabled still False -> still no PRIMARY ip", not any(a["type"] == "PRIMARY" for a in netdb3["ipAddresses"]))

    print("\nRESULT: PASS — GCP Cloud SQL control-plane core conforms "
          "(native Cloud SQL Admin REST wire) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
