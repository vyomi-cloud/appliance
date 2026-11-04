"""DynamoDB exports-to-S3 conformance (v4 depth wave 5) — host + Pyodide.

Asserts ExportTableToPointInTime writes REAL item data (newline-delimited
DynamoDB JSON) plus a manifest into the S3 store, DescribeExport/ListExports
read it back, and a missing destination bucket makes the export genuinely FAIL
(the way a bad bucket/IAM role does in AWS) rather than silently "succeeding".

Run on host:    PYTHONPATH=. python3 tests/conformance/test_dynamodb_export_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core.nosql_store import InMemoryNoSqlStore
    from core.object_store import InMemoryObjectStore
    from core import dynamodb_core as d
    from core import s3_object_core as s3c
except ImportError:  # pragma: no cover - Pyodide flat layout
    from nosql_store import InMemoryNoSqlStore  # type: ignore
    from object_store import InMemoryObjectStore  # type: ignore
    import dynamodb_core as d  # type: ignore
    import s3_object_core as s3c  # type: ignore

P = "DynamoDB_20120810."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None, s3_store=None):
    s = store or InMemoryNoSqlStore()
    s3 = s3_store if s3_store is not None else InMemoryObjectStore()

    def call(a, p, **kw):
        r = d.dispatch(s, P + a, p, **kw)
        return r.status, (r.body if isinstance(r.body, dict) else json.loads(r.body))

    call("CreateTable", {
        "TableName": "export-me",
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
        "BillingMode": "PAY_PER_REQUEST",
    })
    call("PutItem", {"TableName": "export-me", "Item": {"id": {"S": "a"}, "name": {"S": "Ada"}}})
    call("PutItem", {"TableName": "export-me", "Item": {"id": {"S": "b"}, "name": {"S": "Bob"}}})

    # ── no s3_store at all → a clean FAILED job, never a crash or silent success ──
    status, body = call("ExportTableToPointInTime", {"TableName": "export-me", "S3Bucket": "ddb-exports"})
    _check("ExportTableToPointInTime without s3_store 200", status == 200)
    _check("export status FAILED (no S3 store)", body["ExportDescription"]["ExportStatus"] == "FAILED")

    # ── destination bucket doesn't exist → FAILED (a real cross-service check) ──
    status, body = call("ExportTableToPointInTime", {"TableName": "export-me", "S3Bucket": "ddb-exports"},
                        s3_store=s3)
    _check("ExportTableToPointInTime missing bucket 200", status == 200)
    _check("export status FAILED (bucket missing)", body["ExportDescription"]["ExportStatus"] == "FAILED")
    _check("FailureCode present", body["ExportDescription"]["FailureCode"] == "S3AccessDenied")

    # ── real export: bucket exists → COMPLETED, real bytes land in the bucket ──
    s3.create_bucket("ddb-exports")
    status, body = call("ExportTableToPointInTime",
                        {"TableName": "export-me", "S3Bucket": "ddb-exports", "S3Prefix": "nightly"},
                        s3_store=s3)
    _check("ExportTableToPointInTime 200", status == 200)
    desc = body["ExportDescription"]
    _check("export status COMPLETED", desc["ExportStatus"] == "COMPLETED")
    _check("item count 2", desc["ItemCount"] == 2)
    export_arn = desc["ExportArn"]
    _check("export ARN carries /export/", "/export/" in export_arn)

    objs = s3.bucket_objects("ddb-exports")
    data_keys = [k for k in objs if k.endswith("data/1.json")]
    manifest_keys = [k for k in objs if k.endswith("manifest-summary.json")]
    _check("data file written", len(data_keys) == 1 and data_keys[0].startswith("nightly/"))
    _check("manifest file written", len(manifest_keys) == 1)

    get_status, get_body = (lambda r: (r.status, r.body))(s3c.dispatch(s3, "GET", f"/ddb-exports/{data_keys[0]}", {}, {}, b""))
    _check("data file GET 200", get_status == 200)
    lines = [json.loads(ln) for ln in get_body.decode().splitlines() if ln]
    _check("data file has both items", len(lines) == 2
           and {ln["Item"]["id"]["S"] for ln in lines} == {"a", "b"})

    # ── DescribeExport / ListExports read the job record back ──
    status, body = call("DescribeExport", {"ExportArn": export_arn})
    _check("DescribeExport 200", status == 200 and body["ExportDescription"]["ExportArn"] == export_arn)

    status, body = call("ListExports", {"TableName": "export-me"})
    _check("ListExports lists it", any(e["ExportArn"] == export_arn for e in body["ExportSummaries"]))

    status, body = call("DescribeExport", {"ExportArn": "nope"})
    _check("DescribeExport unknown -> ExportNotFoundException", status == 400 and body["__type"] == "ExportNotFoundException")

    print("\nDynamoDB exports-to-S3 conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
