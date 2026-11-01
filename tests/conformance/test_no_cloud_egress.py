"""No database backup/export path talks to a real cloud — "nothing goes out".

1. Static: the shared cores (the files wasm/build_cores.py vendors into Nano, which the
   offline appliance runs too) import no network client — urllib.request, http.client,
   socket, requests, httpx, boto3, aiohttp, urllib3. The export/import cores are checked
   strictly; the one documented exception is API Gateway's HTTP/HTTP_PROXY integration
   (it proxies to the URL the user configured — by design, and unrelated to backups).
2. Dynamic: with every socket connect / DNS lookup made to raise, each export path runs
   with a destination naming a REAL cloud host (an S3 bucket name, gs://…,
   https://<account>.blob.core.windows.net/…) and still completes against the
   simulator's own stores — or fails cleanly for an account the simulator lacks —
   without ever opening a socket.

Run:  PYTHONPATH=. python3 tests/conformance/test_no_cloud_egress.py
"""
import ast
import json
import os
import socket

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BANNED = ("urllib.request", "http.client", "socket", "requests", "httpx", "boto3", "aiohttp", "urllib3")
EXPORT_CORES = ("sql_store.py", "rds_core.py", "rds_data_core.py", "gcp_cloudsql_core.py", "azure_sql_core.py",
                "azure_arm_core.py", "s3_object_core.py", "gcp_storage_core.py", "azure_blob_core.py",
                "dynamodb_core.py", "gcp_firestore_core.py", "object_store.py", "parquet_pyarrow.py")
ALLOWED = {("apigateway_core.py", "urllib.request")}   # HTTP integration → the user's own endpoint


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def _imports(path):
    out = set()
    for n in ast.walk(ast.parse(open(path).read())):
        if isinstance(n, ast.Import):
            out.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            out.add(n.module)
            out.update(f"{n.module}.{a.name}" for a in n.names)
    return out


def _banned(mod):
    return any(mod == b or mod.startswith(b + ".") for b in BANNED)


def static_imports():
    import importlib.util   # load the vendoring list WITHOUT putting wasm/ (and its stale core/) on sys.path
    spec = importlib.util.spec_from_file_location("_build_cores", os.path.join(ROOT, "wasm", "build_cores.py"))
    build_cores = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_cores)
    cores = sorted(set(build_cores.CORES) | set(EXPORT_CORES))
    bad = []
    for f in cores:
        p = os.path.join(ROOT, "core", f)
        if not os.path.isfile(p):
            continue
        for m in _imports(p):
            if _banned(m) and (f, m) not in ALLOWED:
                bad.append(f"{f}: {m}")
    _check(f"{len(cores)} shared cores import no network client", not bad, bad)
    strict = [f"{f}: {m}" for f in EXPORT_CORES for m in _imports(os.path.join(ROOT, "core", f)) if _banned(m)]
    _check("the export/import cores import none at all (no exceptions)", not strict, strict)


class _Egress(Exception):
    pass


def _deny(*a, **k):
    raise _Egress(f"network access attempted: {a[:2]}")


def dynamic_no_socket():
    import asyncio
    from core import rds_core as rds, gcp_cloudsql_core as csql, dynamodb_core as ddb
    from core import gcp_firestore_core as fs, gcp_storage_core as gcs
    from core.azure_arm_core import AzureArm
    from core.azure_blob_core import AzureBlobStore
    from core import azure_sql_core as az
    from core.object_store import InMemoryObjectStore
    from core.sql_store import InMemorySqlStore
    from core.nosql_store import InMemoryNoSqlStore

    saved = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo)
    socket.socket.connect = _deny
    socket.socket.connect_ex = _deny
    socket.create_connection = _deny
    socket.getaddrinfo = _deny
    prev_writer = rds._PARQUET_WRITER
    try:
        # AWS RDS → simulator S3 (a bucket named like a real one; the S3 host is never involved)
        st, s3 = InMemorySqlStore(), InMemoryObjectStore()
        rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "e1"})
        st.execute_sql("e1", "CREATE TABLE t (a INTEGER)")
        st.execute_sql("e1", "INSERT INTO t VALUES (1)")
        rds.dispatch(st, {"Action": "CreateDBSnapshot", "DBInstanceIdentifier": "e1", "DBSnapshotIdentifier": "s"})
        s3.create_bucket("prod-backups.s3.amazonaws.com")
        try:
            from core import parquet_pyarrow
            real = parquet_pyarrow.install()
        except Exception:
            real = False
        if not real:
            rds.set_parquet_writer(lambda schema, columns: b"PAR1")
        r = asyncio.run(rds.adispatch(st, {"Action": "StartExportTask", "ExportTaskIdentifier": "x",
                                           "SourceArn": f"arn:aws:rds:us-east-1:{st.account_id}:snapshot:s",
                                           "S3BucketName": "prod-backups.s3.amazonaws.com"}, s3_store=s3))
        _check(f"RDS export (Parquet via {'pyarrow' if real else 'stub'}) completes with sockets denied",
               "<Status>COMPLETE</Status>" in r.body and s3.bucket_objects("prod-backups.s3.amazonaws.com"))

        # DynamoDB → simulator S3
        dstore = InMemoryNoSqlStore()
        ddb.dispatch(dstore, "DynamoDB_20120810.CreateTable", {
            "TableName": "tbl", "KeySchema": [{"AttributeName": "k", "KeyType": "HASH"}],
            "AttributeDefinitions": [{"AttributeName": "k", "AttributeType": "S"}], "BillingMode": "PAY_PER_REQUEST"})
        ddb.dispatch(dstore, "DynamoDB_20120810.PutItem", {"TableName": "tbl", "Item": {"k": {"S": "1"}}})
        ddb.dispatch(dstore, "DynamoDB_20120810.UpdateContinuousBackups", {
            "TableName": "tbl", "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True}})
        s3.create_bucket("ddb-exports")
        resp = ddb.dispatch(dstore, "DynamoDB_20120810.ExportTableToPointInTime", {
            "TableArn": "arn:aws:dynamodb:us-east-1:123456789012:table/tbl", "S3Bucket": "ddb-exports"},
            s3_store=s3)
        _check("DynamoDB export completes with sockets denied",
               resp.status == 200 and s3.bucket_objects("ddb-exports"), resp.body)

        # Cloud SQL → simulator GCS (gs:// is parsed, never fetched)
        cst, gstore = InMemorySqlStore(), InMemoryObjectStore()
        P = "/sql/v1beta4/projects/p/instances"
        csql.dispatch(cst, "POST", P, {}, {}, json.dumps({"name": "i"}).encode())
        gstore.create_bucket("bk")
        r = csql.dispatch(cst, "POST", P + "/i/export", {}, {},
                          json.dumps({"exportContext": {"fileType": "SQL", "uri": "gs://bk/d.sql"}}).encode(),
                          gcs_store=gstore)
        _check("Cloud SQL export completes with sockets denied", "error" not in json.loads(r.body)
               and "d.sql" in gstore.bucket_objects("bk"))
        r = csql.dispatch(cst, "POST", P + "/i/import", {}, {},
                          json.dumps({"importContext": {"fileType": "SQL", "uri": "gs://bk/d.sql"}}).encode(),
                          gcs_store=gstore)
        _check("Cloud SQL import completes with sockets denied", "error" not in json.loads(r.body))

        # Firestore → simulator GCS
        fstore = fs.FirestoreStore()
        fs.dispatch(fstore, "POST", "/v1/projects/p/databases/(default)/documents/c", {"documentId": "d"}, {},
                    json.dumps({"fields": {"a": {"stringValue": "x"}}}).encode())
        r = fs.dispatch(fstore, "POST", "/v1/projects/p/databases/(default):exportDocuments", {}, {},
                        json.dumps({"outputUriPrefix": "gs://bk/fs-export"}).encode(), gcs_store=gstore)
        _check("Firestore export completes with sockets denied",
               r.status == 200 and any(k.startswith("fs-export") for k in gstore.bucket_objects("bk")), r.body[:200])

        # Azure SQL → simulator Blob (a real-looking *.blob.core.windows.net host)
        arm = AzureArm()
        arm.sql_store, arm.blob_store = InMemorySqlStore(), AzureBlobStore()
        B, q = "/subscriptions/s/resourceGroups/rg/providers", {"api-version": "2021-11-01"}
        arm.handle("PUT", B + "/Microsoft.Sql/servers/srv", q, {"location": "eastus", "properties": {}})
        arm.handle("PUT", B + "/Microsoft.Sql/servers/srv/databases/db", q, {"location": "eastus"})
        arm.handle("PUT", B + "/Microsoft.Storage/storageAccounts/contoso", q,
                   {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
        arm.blob_store.create_container("contoso/bak")
        az._create_database(arm.sql_store, "srv", "db")
        r = arm.handle("POST", B + "/Microsoft.Sql/servers/srv/databases/db/export", q,
                       {"storageUri": "https://contoso.blob.core.windows.net/bak/db.bacpac"})
        _check("Azure SQL export completes with sockets denied", r["status"] == 200)
        r = arm.handle("POST", B + "/Microsoft.Sql/servers/srv/databases/db/export", q,
                       {"storageUri": "https://realcompany.blob.core.windows.net/bak/db.bacpac"})
        _check("an account outside the simulator fails WITHOUT a DNS lookup or connect",
               r["status"] == 404 and r["body"]["error"]["code"] == "StorageAccountNotFound")
    finally:
        (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo) = saved
        rds.set_parquet_writer(prev_writer)


def run() -> int:
    static_imports()
    dynamic_no_socket()
    print("RESULT: PASS — no database export/import path opens a network connection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
