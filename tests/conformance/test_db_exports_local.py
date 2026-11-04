"""Database backups / exports land in the SIMULATOR's own object stores — nothing goes out.

  * AWS RDS StartExportTask: the snapshot's real table data → Parquet in the simulator's
    S3 store (AWS layout), sync (offline, pyarrow) and async (the Nano path: an awaitable
    writer, like the browser's parquet-wasm), plus the async snapshot of an async engine.
  * The offline wire: core.wire_ingress serves `rds` (Query protocol + the RDS Data API)
    through core/rds_core.py, with exports written into the router's S3 store — the one
    `aws s3 ls` reads — and the pre-v4 RDS records adopted once.
  * GCP Cloud SQL instances.export / .import (sqlFile + csvFile) ↔ the simulator's GCS.
  * Azure SQL database export / import (.bacpac) ↔ the simulator's Azure Blob store; a
    storageUri naming an account the simulator doesn't have FAILS (never resolved).

Run:  PYTHONPATH=. python3 tests/conformance/test_db_exports_local.py
(the Parquet byte-level round-trip needs pyarrow; it is skipped, not faked, without it)
"""
import asyncio
import io
import json
from urllib.parse import urlencode

from core import rds_core as rds
from core import gcp_cloudsql_core as csql
from core import gcp_storage_core as gcs
from core import s3_object_core as s3c
from core.object_store import InMemoryObjectStore
from core.sql_store import InMemorySqlStore


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def _pyarrow():
    try:
        import pyarrow.parquet as pq
        return pq
    except Exception:
        return None


def _seed_rds(st):
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "shop", "DBName": "shopdb"})
    st.execute_sql("shop", "CREATE TABLE items (id INTEGER, name TEXT, price REAL, img BLOB)")
    st.execute_sql("shop", "INSERT INTO items VALUES (1, 'pen', 1.5, x'00ff'), (2, NULL, 2.0, NULL)")
    st.execute_sql("shop", "CREATE TABLE tags (t TEXT)")
    st.execute_sql("shop", "INSERT INTO tags VALUES ('a')")
    r = rds.dispatch(st, {"Action": "CreateDBSnapshot", "DBInstanceIdentifier": "shop",
                          "DBSnapshotIdentifier": "shop-s1"})
    assert r.status == 200, r.body
    return f"arn:aws:rds:us-east-1:{st.account_id}:snapshot:shop-s1"


def rds_exports():
    pq = _pyarrow()
    st, s3 = InMemorySqlStore(), InMemoryObjectStore()
    src = _seed_rds(st)
    st.execute_sql("shop", "INSERT INTO items VALUES (3, 'later', 9.0, NULL)")   # after the snapshot
    s3.create_bucket("exports")
    prev = rds._PARQUET_WRITER
    captured = []

    def fake_writer(schema, columns):      # records exactly what the core hands the platform
        captured.append((schema, columns))
        return b"PAR1-test"

    rds.set_parquet_writer(fake_writer)
    try:
        r = rds.dispatch(st, {"Action": "StartExportTask", "ExportTaskIdentifier": "t-only",
                              "SourceArn": src, "S3BucketName": "exports",
                              "ExportOnly.member.1": "shopdb.main.items"}, s3_store=s3)
        _check("ExportOnly exports only the named table", "<Status>COMPLETE</Status>" in r.body
               and len(captured) == 1 and [f["name"] for f in captured[0][0]] == ["id", "name", "price", "img"])
        schema, cols = captured[0]
        _check("Arrow schema typed from the engine (INTEGER/TEXT/REAL/BLOB)",
               [f["type"] for f in schema] == ["int64", "string", "float64", "binary"])
        _check("snapshot-time data only (row inserted after the snapshot is absent)",
               cols[0] == [1, 2] and cols[3] == [b"\x00\xff", None])

        async def async_writer(schema, columns):   # the Nano shape: the browser engine is async
            await asyncio.sleep(0)
            return b"PAR1-async"
        rds.set_parquet_writer(async_writer)
        sync_try = rds.dispatch(st, {"Action": "StartExportTask", "ExportTaskIdentifier": "t-sync-async",
                                     "SourceArn": src, "S3BucketName": "exports"}, s3_store=s3)
        _check("an async-only writer on the sync path FAILS clearly (never a fallback)",
               "<Status>FAILED</Status>" in sync_try.body and "asynchronous" in sync_try.body)
        r = asyncio.run(rds.adispatch(st, {"Action": "StartExportTask", "ExportTaskIdentifier": "t-async",
                                           "SourceArn": src, "S3BucketName": "exports"}, s3_store=s3))
        keys = sorted(k for k in s3.bucket_objects("exports") if k.startswith("t-async/"))
        _check("adispatch awaits the async writer; files land in the simulator bucket",
               "<Status>COMPLETE</Status>" in r.body and
               any(k.startswith("t-async/shopdb/main.items/part-00000-") and k.endswith(".gz.parquet") for k in keys)
               and any(k.startswith("t-async/shopdb/main.tags/part-00000-") for k in keys)
               and "t-async/export_info_t-async.json" in keys
               and "t-async/export_tables_info_t-async_from_1_to_2.json" in keys, keys)
        info = json.loads(s3c.dispatch(s3, "GET", "/exports/t-async/export_info_t-async.json", {}, {}, b"").body)
        _check("export_info names the source + Parquet format", info["sourceArn"] == src and info["format"] == "parquet")

        def broken_writer(schema, columns):
            raise RuntimeError("engine exploded")
        rds.set_parquet_writer(broken_writer)
        r = rds.dispatch(st, {"Action": "StartExportTask", "ExportTaskIdentifier": "t-broken",
                              "SourceArn": src, "S3BucketName": "exports"}, s3_store=s3)
        _check("a failing Parquet engine fails the task with the cause", "<Status>FAILED</Status>" in r.body
               and "engine exploded" in r.body)

        if pq is not None:
            from core import parquet_pyarrow
            parquet_pyarrow.install()
            r = rds.dispatch(st, {"Action": "StartExportTask", "ExportTaskIdentifier": "t-real",
                                  "SourceArn": src, "S3BucketName": "exports", "S3Prefix": "bk/up"}, s3_store=s3)
            key = next(k for k in s3.bucket_objects("exports") if k.startswith("bk/up/t-real/shopdb/main.items/"))
            data = s3c.dispatch(s3, "GET", f"/exports/{key}", {}, {}, b"").body
            f = pq.ParquetFile(io.BytesIO(data))
            _check("pyarrow: real gzip Parquet whose rows equal the snapshot's",
                   f.read().to_pylist() == [{"id": 1, "name": "pen", "price": 1.5, "img": b"\x00\xff"},
                                            {"id": 2, "name": None, "price": 2.0, "img": None}]
                   and f.metadata.row_group(0).column(0).compression == "GZIP")
        else:
            print("  SKIP  pyarrow round-trip (pyarrow not installed in this interpreter)")
    finally:
        rds.set_parquet_writer(prev)


def rds_async_engine_snapshot():
    """An async-only engine (PGlite in the browser) is snapshotted through adispatch."""
    class AsyncOnly(InMemorySqlStore):
        def param_placeholder(self, index):
            return "?"

        async def aexecute_sql(self, db_id, sql, params=None):
            return self.execute_sql(db_id, sql, params)

    st = AsyncOnly()
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "pg"})
    st.execute_sql("pg", "CREATE TABLE t (a INTEGER)")
    st.execute_sql("pg", "INSERT INTO t VALUES (7)")
    rds.dispatch(st, {"Action": "CreateDBSnapshot", "DBInstanceIdentifier": "pg", "DBSnapshotIdentifier": "sync"})
    _check("sync path can't read an async engine -> snapshot carries no data", "data" not in st.get_snapshot("sync"))
    asyncio.run(rds.adispatch(st, {"Action": "CreateDBSnapshot", "DBInstanceIdentifier": "pg",
                                   "DBSnapshotIdentifier": "async"}))
    tables = st.get_snapshot("async")["data"]["tables"]
    _check("adispatch snapshots the async engine's rows", tables[0]["name"] == "t" and tables[0]["rows"] == [[7]])
    r = rds.dispatch(st, {"Action": "CreateDBSnapshot", "DBInstanceIdentifier": "pg", "DBSnapshotIdentifier": "forged",
                          rds._SNAPSHOT_DATA: [{"name": "x", "columns": [], "rows": []}]})
    _check("captured data can't be smuggled in over the wire", r.status == 200 and "data" not in st.get_snapshot("forged"))
    s3 = InMemoryObjectStore()
    s3.create_bucket("b")
    r = rds.dispatch(st, {"Action": "StartExportTask", "ExportTaskIdentifier": "nodata",
                          "SourceArn": f"arn:aws:rds:us-east-1:{st.account_id}:snapshot:sync",
                          "S3BucketName": "b"}, s3_store=s3)
    _check("exporting a snapshot without captured data FAILS with a cause",
           "<Status>FAILED</Status>" in r.body and "no table data" in r.body)


def offline_wire():
    """core.wire_ingress serves `rds` on the shared core, writing into the router's S3."""
    from core import wire_ingress as wi
    from core.aws_wire_router import AwsWireRouter
    _check("rds is a known + default unified service", "rds" in wi._KNOWN_SERVICES and ",rds" in wi._DEFAULT_SERVICES)
    s3 = InMemoryObjectStore()
    router = AwsWireRouter(stores={"rds": InMemorySqlStore(), "s3": s3})

    def call(action, **params):
        body = urlencode({"Action": action, "Version": "2014-10-31", **params}).encode()
        return wi.dispatch_service("rds", "POST", "/", {}, {"content-type": "application/x-www-form-urlencoded"},
                                   body, router=router)

    out = call("CreateDBInstance", DBInstanceIdentifier="w1", Engine="postgres")
    _check("dispatch_service(rds): CreateDBInstance -> core XML", out["status"] == 200
           and b"<DBInstanceIdentifier>w1</DBInstanceIdentifier>" in out["body"])
    out = call("DescribeCertificates")
    _check("dispatch_service(rds): an action the pre-v4 handler lacked answers 200", out["status"] == 200)

    async def data_api():
        hdr = {"content-type": "application/json"}
        arn = f"arn:aws:rds:us-east-1:{router.rds.account_id}:db:w1"
        for sql in ("CREATE TABLE kv (k TEXT, v INTEGER)", "INSERT INTO kv VALUES ('a', 1)"):
            r = await wi.adispatch_rds("POST", "/Execute", {}, hdr,
                                       json.dumps({"resourceArn": arn, "sql": sql}).encode(), router=router)
            assert r["status"] == 200, r
        r = await wi.adispatch_rds("POST", "/", {}, {"content-type": "application/x-www-form-urlencoded"},
                                   urlencode({"Action": "CreateDBSnapshot", "DBInstanceIdentifier": "w1",
                                              "DBSnapshotIdentifier": "w1-s"}).encode(), router=router)
        return r
    r = asyncio.run(data_api())
    _check("Data API rows (/Execute) are what the snapshot captures",
           r["status"] == 200 and router.rds.get_snapshot("w1-s")["data"]["tables"][0]["rows"] == [["a", 1]])
    s3.create_bucket("wire-exports")
    prev = rds._PARQUET_WRITER
    rds.set_parquet_writer(lambda schema, columns: b"PAR1")
    try:
        out = call("StartExportTask", ExportTaskIdentifier="wx", S3BucketName="wire-exports",
                   SourceArn=f"arn:aws:rds:us-east-1:{router.rds.account_id}:snapshot:w1-s")
    finally:
        rds.set_parquet_writer(prev)
    _check("StartExportTask over the wire writes into the router's S3 store (what `aws s3 ls` reads)",
           b"<Status>COMPLETE</Status>" in out["body"]
           and any(k.startswith("wx/") and k.endswith(".gz.parquet") for k in s3.bucket_objects("wire-exports")))


def legacy_adoption():
    try:
        from core import appliance_stores as aps
    except Exception as exc:   # pragma: no cover - not on Pyodide
        print(f"  skip adoption ({exc})")
        return
    legacy = {
        "db_instances": {"olddb": {"db_instance_identifier": "olddb", "engine": "mysql", "engine_version": "8.0",
                                   "db_instance_status": "available", "allocated_storage": 30,
                                   "tags": [{"key": "team", "value": "core"}]}},
        "db_snapshots": {"old-snap": {"db_snapshot_identifier": "old-snap", "db_instance_identifier": "olddb",
                                      "engine": "mysql", "snapshot_type": "manual"}},
        "db_subnet_groups": {"sg1": {"db_subnet_group_name": "sg1", "subnet_ids": ["subnet-a", "subnet-b"],
                                     "vpc_id": "vpc-1"}},
        "db_parameter_groups": {"pg1": {"db_parameter_group_name": "pg1", "db_parameter_group_family": "mysql8.0"}},
    }
    st = InMemorySqlStore()
    n = aps.adopt_legacy_rds(st, legacy)
    _check("pre-v4 RDS records adopted (instance, snapshot, subnet group, parameter group)", n == 4)
    _check("adopted instance in the core shape", st.get_instance("olddb")["engine"] == "mysql"
           and st.get_instance("olddb")["endpoint_port"] == 3306)
    _check("adopted tags", st.get_tags(rds._instance_arn(st, "olddb")) == {"team": "core"})
    _check("adopted subnet group subnets", [s["subnet_identifier"] for s in st.get_subnet_group("sg1")["subnets"]]
           == ["subnet-a", "subnet-b"])
    r = rds.dispatch(st, {"Action": "DescribeDBSnapshots"})
    _check("adopted snapshot visible on the core wire", "<DBSnapshotIdentifier>old-snap<" in r.body)
    _check("re-adoption is idempotent (existing records win)", aps.adopt_legacy_rds(st, legacy) == 0)


def cloudsql():
    st, store = InMemorySqlStore(), InMemoryObjectStore()
    P = "/sql/v1beta4/projects/p1/instances"

    def call(path, body):
        r = csql.dispatch(st, "POST", P + path, {}, {}, json.dumps(body).encode(), gcs_store=store)
        return r.status, json.loads(r.body)

    csql.dispatch(st, "POST", P, {}, {}, json.dumps({"name": "i1"}).encode())
    store.create_bucket("bk")
    gcs.dispatch(store, "POST", "/upload/storage/v1/b/bk/o", {"uploadType": "media", "name": "seed.sql"}, {},
                 b"CREATE TABLE t (id INTEGER, n TEXT); INSERT INTO t VALUES (1, 'x'), (2, 'it''s; ok');")
    s, op = call("/i1/import", {"importContext": {"fileType": "SQL", "uri": "gs://bk/seed.sql", "database": "d"}})
    _check("instances.import (sqlFile from simulator GCS) is a DONE IMPORT operation",
           s == 200 and op["operationType"] == "IMPORT" and "error" not in op)
    s, op = call("/i1/export", {"exportContext": {"fileType": "SQL", "uri": "gs://bk/out/i1.sql"}})
    dump = gcs.dispatch(store, "GET", "/storage/v1/b/bk/o/out%2Fi1.sql", {"alt": "media"}, {}, b"").body.decode()
    _check("instances.export (sqlFile) writes a replayable dump into the simulator bucket",
           op["operationType"] == "EXPORT" and "error" not in op and "INSERT INTO \"t\"" in dump and "'it''s; ok'" in dump)
    s, op = call("/i1/export", {"exportContext": {"fileType": "CSV", "uri": "gs://bk/out/t.csv",
                                                  "csvExportOptions": {"selectQuery": "SELECT * FROM t"}}})
    csv_body = gcs.dispatch(store, "GET", "/storage/v1/b/bk/o/out%2Ft.csv", {"alt": "media"}, {}, b"").body
    _check("instances.export (csvFile + selectQuery)", "error" not in op and csv_body == b"1,x\n2,it's; ok\n")
    s, op = call("/i1/import", {"importContext": {"fileType": "CSV", "uri": "gs://bk/out/t.csv",
                                                  "csvImportOptions": {"table": "t"}}})
    rows = st.execute_sql("cloudsql:p1/i1", "SELECT COUNT(*) FROM t")["rows"][0][0]
    _check("instances.import (csvFile) appends the rows", "error" not in op and rows == 4)
    s, op = call("/i1/export", {"exportContext": {"fileType": "SQL", "uri": "gs://missing-bucket/x.sql"}})
    _check("missing bucket -> the operation carries an error", "missing-bucket" in json.dumps(op.get("error")))
    s, op = call("/i1/export", {"exportContext": {"fileType": "SQL", "uri": "https://storage.googleapis.com/bk/x"}})
    _check("a non-gs:// URI is rejected (INVALID_ARGUMENT), never fetched", s == 400)


def azure_sql():
    from core.azure_arm_core import AzureArm
    from core.azure_blob_core import AzureBlobStore
    from core import azure_sql_core as az
    arm = AzureArm()
    arm.sql_store, arm.blob_store = InMemorySqlStore(), AzureBlobStore()
    B, q = "/subscriptions/s1/resourceGroups/rg/providers", {"api-version": "2021-11-01"}
    arm.handle("PUT", B + "/Microsoft.Sql/servers/srv", q, {"location": "eastus", "properties": {}})
    arm.handle("PUT", B + "/Microsoft.Sql/servers/srv/databases/db1", q, {"location": "eastus"})
    arm.handle("PUT", B + "/Microsoft.Storage/storageAccounts/acct", q,
               {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
    az._create_database(arm.sql_store, "srv", "db1")
    az.execute_sql(arm.sql_store, "srv", "db1", "CREATE TABLE t (a INTEGER, b TEXT)")
    az.execute_sql(arm.sql_store, "srv", "db1", "INSERT INTO t VALUES (1, 'x')")
    uri = "https://acct.blob.core.windows.net/backups/db1.bacpac"
    r = arm.handle("POST", B + "/Microsoft.Sql/servers/srv/databases/db1/export", q, {"storageUri": uri})
    _check("export into a container that doesn't exist fails", r["status"] == 404
           and r["body"]["error"]["code"] == "ContainerNotFound")
    arm.blob_store.create_container("acct/backups")
    r = arm.handle("POST", B + "/Microsoft.Sql/servers/srv/databases/db1/export", q, {"storageUri": uri})
    _check("database export -> .bacpac in the simulator's Blob store",
           r["status"] == 200 and r["body"]["properties"]["status"] == "Succeeded"
           and "db1.bacpac" in arm.blob_store.blobs["acct/backups"])
    r = arm.handle("POST", B + "/Microsoft.Sql/servers/srv/import", q, {"storageUri": uri, "databaseName": "db2"})
    out = az.execute_sql(arm.sql_store, "srv", "db2", "SELECT * FROM t")
    _check("server import (new database) restores the rows + creates the database resource",
           r["status"] == 200 and out["rows"] == [[1, "x"]]
           and arm.handle("GET", B + "/Microsoft.Sql/servers/srv/databases/db2", q, None)["status"] == 200)
    r = arm.handle("POST", B + "/Microsoft.Sql/servers/srv/databases/db1/export", q,
                   {"storageUri": "https://notinsim.blob.core.windows.net/c/x.bacpac"})
    _check("an account the simulator doesn't have FAILS (never resolved)", r["status"] == 404
           and r["body"]["error"]["code"] == "StorageAccountNotFound")
    r = arm.handle("POST", B + "/Microsoft.Sql/servers/srv/databases/db1/export", q,
                   {"storageUri": "https://example.com/c/x.bacpac"})
    _check("a non-Blob host is rejected", r["status"] == 400 and r["body"]["error"]["code"] == "InvalidStorageUri")


def run() -> int:
    for fn in (rds_exports, rds_async_engine_snapshot, offline_wire, legacy_adoption, cloudsql, azure_sql):
        print(f"── {fn.__name__}")
        fn()
    print("RESULT: PASS — database exports/imports land in the simulator's own object stores.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
