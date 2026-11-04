"""Azure SQL copy / point-in-time restore / dropped-DB restore / active geo-replication / short+long-term retention over the real
SqlStore data plane. Run: PYTHONPATH=. python tests/conformance/test_azure_sqlbackup_core.py"""
import json
import time
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
    from core.azure_blob_core import AzureBlobStore
    from core import azure_sql_core as az
    from core.sql_store import SqlStore
except ImportError:  # pragma: no cover
    raise


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    a.blob_store = blobs = AzureBlobStore()
    a.sql_store = store = SqlStore()
    h = lambda m, p, b=None, q=None: a.handle(m, p, dict({"api-version": "2023-08-01"}, **(q or {})), b)
    code = lambda r: (r["body"].get("error") or {}).get("code")
    R = f"/subscriptions/{S}/resourceGroups/sqlrg"
    h("PUT", R, {"location": "eastus"}, {"api-version": "2021-04-01"})
    srv = lambda n, loc="eastus": h("PUT", f"{R}/providers/Microsoft.Sql/servers/{n}", {"location": loc, "properties": {"administratorLogin": "a", "administratorLoginPassword": "P@ssw0rd123!"}})
    srv("s1"); srv("s2", "westus")
    D = lambda s, d: f"{R}/providers/Microsoft.Sql/servers/{s}/databases/{d}"
    mk = lambda s, d, **p: h("PUT", D(s, d), {"location": "eastus", "properties": p})
    q = lambda s, d, sql, params=None: az.dispatch(store, "POST", f"/servers/{s}/databases/{d}/query", body=json.dumps({"sql": sql, "params": params}).encode(), arm_state=a.state)
    _check("db", mk("s1", "orders")["status"] in (200, 201))
    az.dispatch(store, "PUT", "/servers/s1", arm_state=a.state)
    az.dispatch(store, "PUT", "/servers/s1/databases/orders", arm_state=a.state)
    _check("create table", q("s1", "orders", "CREATE TABLE t (id INTEGER, v TEXT)").status == 200)
    q("s1", "orders", "INSERT INTO t VALUES (1, 'one')")
    t_mid = time.time()
    time.sleep(1.2)
    q("s1", "orders", "INSERT INTO t VALUES (2, 'two')")
    q("s1", "orders", "UPDATE t SET v='ONE' WHERE id=1")
    cnt = lambda s, d: json.loads(q(s, d, "SELECT COUNT(*) FROM t").body)["rows"][0][0]

    # createMode validation
    _check("bad createMode", code(mk("s1", "x", createMode="Bogus")) == "InvalidCreateMode")
    _check("Copy needs source", mk("s1", "x", createMode="Copy")["status"] == 400)
    _check("Copy source missing", mk("s1", "x", createMode="Copy", sourceDatabaseId=D("s1", "ghost"))["status"] == 404)
    # Copy
    r = mk("s2", "orders_copy", createMode="Copy", sourceDatabaseId=D("s1", "orders"))
    _check("copy created", r["status"] in (200, 201) and r["body"]["properties"]["createMode"] == "Copy")
    _check("copy carries data", cnt("s2", "orders_copy") == 2)
    q("s1", "orders", "INSERT INTO t VALUES (3, 'three')")
    _check("copy is independent", cnt("s2", "orders_copy") == 2 and cnt("s1", "orders") == 3)

    # PITR
    iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + "." + ("%03d" % int((ts % 1) * 1000)) + "Z"
    _check("PITR needs time", code(mk("s1", "p", createMode="PointInTimeRestore", sourceDatabaseId=D("s1", "orders"))) == "MissingRestorePointInTime")
    _check("PITR future", code(mk("s1", "p", createMode="PointInTimeRestore", sourceDatabaseId=D("s1", "orders"), restorePointInTime=iso(time.time() + 3600))) == "InvalidRestorePointInTime")
    _check("PITR before earliest", code(mk("s1", "p", createMode="PointInTimeRestore", sourceDatabaseId=D("s1", "orders"), restorePointInTime="2001-01-01T00:00:00Z")) == "InvalidRestorePointInTime")
    _check("PITR cross-server rejected", code(mk("s2", "p", createMode="PointInTimeRestore", sourceDatabaseId=D("s1", "orders"), restorePointInTime=iso(time.time()))) == "InvalidRestoreTarget")
    r = mk("s1", "orders_pit", createMode="PointInTimeRestore", sourceDatabaseId=D("s1", "orders"), restorePointInTime=iso(t_mid + 0.5))
    _check("PITR created", r["status"] in (200, 201))
    _check("PITR sees only the writes before the instant", cnt("s1", "orders_pit") == 1 and json.loads(q("s1", "orders_pit", "SELECT v FROM t").body)["rows"][0][0] == "one")
    r = mk("s1", "orders_pit_now", createMode="PointInTimeRestore", sourceDatabaseId=D("s1", "orders"), restorePointInTime=iso(time.time()))
    _check("PITR at now has all writes", cnt("s1", "orders_pit_now") == 3)

    # short-term retention
    ST = D("s1", "orders") + "/backupShortTermRetentionPolicies/default"
    _check("STR default 7", h("GET", ST)["body"]["properties"]["retentionDays"] == 7)
    _check("STR bad days", h("PUT", ST, {"properties": {"retentionDays": 40}})["status"] == 400)
    _check("STR set", h("PUT", ST, {"properties": {"retentionDays": 14, "diffBackupIntervalInHours": 24}})["body"]["properties"]["retentionDays"] == 14)

    # drop + restore
    _check("delete db", h("DELETE", D("s1", "orders_pit_now"))["status"] in (200, 204))
    dd = h("GET", f"{R}/providers/Microsoft.Sql/servers/s1/restorableDroppedDatabases")["body"]["value"]
    _check("dropped db listed", len(dd) == 1 and dd[0]["properties"]["databaseName"] == "orders_pit_now")
    _check("dropped artifact is a blob", any(k.startswith("dropped/") for k in blobs.container_blobs("vyomisqlbackup/sqlbackups")))
    _check("restore dropped bad id", mk("s1", "rd", createMode="Restore", restorableDroppedDatabaseId="/x")["status"] == 404)
    r = mk("s1", "revived", createMode="Restore", restorableDroppedDatabaseId=dd[0]["id"])
    _check("restored from dropped snapshot", r["status"] in (200, 201) and cnt("s1", "revived") == 3)

    # geo-replication
    _check("secondary on same server rejected", code(mk("s1", "sec", createMode="Secondary", sourceDatabaseId=D("s1", "orders"))) == "InvalidSecondaryServer")
    r = mk("s2", "orders_geo", createMode="Secondary", sourceDatabaseId=D("s1", "orders"))
    _check("secondary created", r["status"] in (200, 201) and r["body"]["properties"]["secondaryType"] == "Geo")
    _check("secondary seeded", cnt("s2", "orders_geo") == 3)
    q("s1", "orders", "INSERT INTO t VALUES (4, 'four')")
    _check("writes replicate to the secondary", cnt("s2", "orders_geo") == 4)
    rr = q("s2", "orders_geo", "INSERT INTO t VALUES (9, 'nine')")
    _check("secondary is read-only", rr.status == 400 and rr.body and b"read-only" in rr.body)
    links = h("GET", D("s1", "orders") + "/replicaLinks")["body"]["value"]
    _check("primary link", len(links) == 1 and links[0]["properties"]["role"] == "Primary" and links[0]["properties"]["partnerServer"] == "s2")
    _check("delete primary blocked", code(h("DELETE", D("s1", "orders"))) == "DatabaseHasActiveGeoReplicationLinks")
    slink = h("GET", D("s2", "orders_geo") + "/replicaLinks")["body"]["value"][0]
    _check("failover must target the secondary", h("POST", D("s1", "orders") + f"/replicaLinks/{links[0]['name']}/failover")["status"] == 400)
    _check("failover", h("POST", D("s2", "orders_geo") + f"/replicaLinks/{slink['name']}/failover")["status"] == 200)
    _check("roles swapped", q("s2", "orders_geo", "INSERT INTO t VALUES (5, 'five')").status == 200 and q("s1", "orders", "INSERT INTO t VALUES (6, 'six')").status == 400)
    _check("replication now flows s2 -> s1", cnt("s1", "orders") == 5)
    _check("terminate link", h("DELETE", D("s2", "orders_geo") + f"/replicaLinks/{slink['name']}")["status"] == 200)
    _check("terminated secondary is writable", q("s1", "orders", "INSERT INTO t VALUES (7, 'seven')").status == 200 and cnt("s2", "orders_geo") == 5)

    # LTR
    LT = D("s2", "orders_geo") + "/backupLongTermRetentionPolicies/default"
    _check("LTR default", h("GET", LT)["body"]["properties"]["weeklyRetention"] == "PT0S")
    _check("LTR bad duration", h("PUT", LT, {"properties": {"weeklyRetention": "4 weeks"}})["status"] == 400)
    _check("LTR too long", h("PUT", LT, {"properties": {"yearlyRetention": "P11Y", "weekOfYear": 1}})["status"] == 400)
    _check("yearly needs weekOfYear", h("PUT", LT, {"properties": {"yearlyRetention": "P5Y"}})["status"] == 400)
    _check("LTR set", h("PUT", LT, {"properties": {"weeklyRetention": "P4W", "monthlyRetention": "P12M"}})["status"] == 200)
    ltr = h("GET", f"/subscriptions/{S}/providers/Microsoft.Sql/locations/eastus/longTermRetentionServers/s2/longTermRetentionDatabases/orders_geo/longTermRetentionBackups")
    _check("LTR backup listed", len(ltr["body"]["value"]) == 1)
    b = ltr["body"]["value"][0]
    q("s2", "orders_geo", "INSERT INTO t VALUES (8, 'eight')")
    r = mk("s1", "from_ltr", createMode="RestoreLongTermRetentionBackup", recoveryServicesRecoveryPointId=b["id"])
    _check("restore from LTR has the backup-time data", r["status"] in (200, 201) and cnt("s1", "from_ltr") == 5)
    _check("LTR delete", h("DELETE", b["id"])["status"] == 200 and not h("GET", ltr["body"]["value"][0]["id"].rsplit("/", 1)[0])["body"]["value"])
    print("azure sql backup core: all checks passed")


if __name__ == "__main__":
    run()
