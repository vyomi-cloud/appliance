"""Cloud SQL backup runs carrying real row data, restoreBackup (same + other instance), instances.clone incl. point-in-time.
Run: PYTHONPATH=. python tests/conformance/test_gcp_cloudsql_backup.py"""
import json
import time
from core.sql_store import InMemorySqlStore
from core import gcp_cloudsql_core as csql

P = "/sql/v1beta4/projects/demo/instances"


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


st = InMemorySqlStore()
call = lambda m, path, body=None: csql.dispatch(st, m, path, {}, {}, json.dumps(body).encode() if body is not None else b"")
js = lambda r: json.loads(r.body)
q = lambda inst, sql: js(call("POST", f"{P}/{inst}/query", {"sql": sql}))
cnt = lambda inst: q(inst, "SELECT COUNT(*) FROM t")["rows"][0][0]


def main():
    bad = call("POST", P, {"name": "x", "databaseVersion": "POSTGRES_15", "settings": {"tier": "db-custom-1-3840", "backupConfiguration": {"enabled": False, "pointInTimeRecoveryEnabled": True}}})
    _check("PITR needs automated backups", bad.status == 400)
    bad = call("POST", P, {"name": "x", "databaseVersion": "POSTGRES_15", "settings": {"tier": "db-custom-1-3840", "backupConfiguration": {"transactionLogRetentionDays": 99}}})
    _check("log retention range", bad.status == 400)
    call("POST", P, {"name": "main", "databaseVersion": "POSTGRES_15", "settings": {"tier": "db-custom-1-3840", "backupConfiguration": {"enabled": True, "pointInTimeRecoveryEnabled": True}}})
    call("POST", P, {"name": "mysqlx", "databaseVersion": "MYSQL_8_0", "settings": {"tier": "db-custom-1-3840"}})
    call("POST", P, {"name": "rep", "databaseVersion": "POSTGRES_15", "masterInstanceName": "main", "settings": {"tier": "db-custom-1-3840"}})
    _check("create table", q("main", "CREATE TABLE t (id INTEGER)")["ok"])
    q("main", "INSERT INTO t VALUES (1)")
    _check("no backup on replica", call("POST", f"{P}/rep/backupRuns", {}).status == 400)
    b = js(call("POST", f"{P}/main/backupRuns", {"description": "b1"}))
    _check("backup run", b["status"] == "SUCCESSFUL")
    time.sleep(1.1)
    t_mid = time.time()
    time.sleep(1.1)
    q("main", "INSERT INTO t VALUES (2)")
    q("main", "INSERT INTO t VALUES (3)")
    _check("3 rows", cnt("main") == 3)
    r = call("POST", f"{P}/main/restoreBackup", {"restoreBackupContext": {"backupRunId": b["id"]}})
    _check("restore ok", r.status == 200)
    _check("restoreBackup rewinds the DATA", cnt("main") == 1)
    _check("restore onto replica rejected", call("POST", f"{P}/rep/restoreBackup", {"restoreBackupContext": {"backupRunId": b["id"], "instanceId": "main"}}).status == 400)
    _check("cross-engine restore rejected", call("POST", f"{P}/mysqlx/restoreBackup", {"restoreBackupContext": {"backupRunId": b["id"], "instanceId": "main"}}).status == 400)
    call("POST", P, {"name": "other", "databaseVersion": "POSTGRES_15", "settings": {"tier": "db-custom-1-3840"}})
    q("other", "CREATE TABLE junk (x INTEGER)")
    _check("restore into another instance", call("POST", f"{P}/other/restoreBackup", {"restoreBackupContext": {"backupRunId": b["id"], "instanceId": "main"}}).status == 200 and cnt("other") == 1)
    # clone
    _check("clone needs name", call("POST", f"{P}/main/clone", {"cloneContext": {}}).status == 400)
    _check("clone to existing", call("POST", f"{P}/main/clone", {"cloneContext": {"destinationInstanceName": "other"}}).status == 409)
    q("main", "INSERT INTO t VALUES (2)")
    t_mid2 = time.time()
    time.sleep(1.1)
    q("main", "INSERT INTO t VALUES (3)")
    r = call("POST", f"{P}/main/clone", {"cloneContext": {"destinationInstanceName": "c1"}})
    _check("clone", r.status == 200 and js(r)["operationType"] == "CLONE" and cnt("c1") == 3)
    iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
    r = call("POST", f"{P}/main/clone", {"cloneContext": {"destinationInstanceName": "c2", "pointInTime": iso(t_mid2 + 0.5)}})
    _check("PITR clone sees only earlier writes", r.status == 200 and cnt("c2") == 2)
    _check("PITR on non-PITR instance rejected", call("POST", f"{P}/other/clone", {"cloneContext": {"destinationInstanceName": "c3", "pointInTime": iso(time.time())}}).status == 400)
    _check("PITR in the future", call("POST", f"{P}/main/clone", {"cloneContext": {"destinationInstanceName": "c4", "pointInTime": iso(time.time() + 3600)}}).status == 400)
    print("gcp cloudsql backup: all checks passed")


main()
