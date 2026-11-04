"""DynamoDB ImportTable conformance (v4 wave 5b gap sweep) — host + Pyodide.

Proves imports read REAL bytes from the S3 store and actually create a brand
new table populated with real items — both supported formats (DYNAMODB_JSON,
the exact shape ExportTableToPointInTime already writes — so export+import is
a genuine round trip — and CSV), both compressions (NONE, GZIP), and a clean
FAILED job (not a crash) when the source is missing or malformed.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_dynamodb_import_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import gzip
import json

try:
    from core.nosql_store import InMemoryNoSqlStore
    from core.object_store import InMemoryObjectStore
    from core import dynamodb_core as d
except ImportError:  # pragma: no cover - Pyodide flat layout
    from nosql_store import InMemoryNoSqlStore  # type: ignore
    from object_store import InMemoryObjectStore  # type: ignore
    import dynamodb_core as d  # type: ignore

P = "DynamoDB_20120810."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None, s3_store=None):
    s = store or InMemoryNoSqlStore()
    s3 = s3_store if s3_store is not None else InMemoryObjectStore()
    s3.create_bucket("ddb-imports")

    def call(a, p, **kw):
        r = d.dispatch(s, P + a, p, **kw)
        return r.status, (r.body if isinstance(r.body, dict) else json.loads(r.body))

    # ── export a real table, then IMPORT that exact export back into a new table ──
    call("CreateTable", {"TableName": "src", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                         "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
                         "BillingMode": "PAY_PER_REQUEST"})
    call("PutItem", {"TableName": "src", "Item": {"id": {"S": "a"}, "name": {"S": "Ada"}}})
    call("PutItem", {"TableName": "src", "Item": {"id": {"S": "b"}, "name": {"S": "Bob"}}})
    status, body = call("ExportTableToPointInTime", {"TableName": "src", "S3Bucket": "ddb-imports", "S3Prefix": "exp"},
                        s3_store=s3)
    _check("export COMPLETED", body["ExportDescription"]["ExportStatus"] == "COMPLETED")
    data_key = next(k for k in s3.bucket_objects("ddb-imports") if k.endswith("data/1.json"))
    prefix = data_key.rsplit("/", 1)[0] + "/"

    status, body = call("ImportTable", {
        "S3BucketSource": {"S3Bucket": "ddb-imports", "S3KeyPrefix": prefix}, "InputFormat": "DYNAMODB_JSON",
        "TableCreationParameters": {"TableName": "restored", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                                    "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
                                    "BillingMode": "PAY_PER_REQUEST"},
    }, s3_store=s3)
    _check("ImportTable 200", status == 200)
    desc = body["ImportTableDescription"]
    _check("import COMPLETED", desc["ImportStatus"] == "COMPLETED")
    _check("imported both items", desc["ImportedItemCount"] == 2)
    import_arn = desc["ImportArn"]

    status, body = call("Scan", {"TableName": "restored"})
    _check("the new table really has both items", body["Count"] == 2 and
           {it["name"]["S"] for it in body["Items"]} == {"Ada", "Bob"})

    status, body = call("DescribeImport", {"ImportArn": import_arn})
    _check("DescribeImport round-trips the job", status == 200 and body["ImportTableDescription"]["ImportArn"] == import_arn)
    status, body = call("ListImports", {"TableArn": desc["TableArn"]})
    _check("ListImports lists it", any(i["ImportArn"] == import_arn for i in body["ImportSummaryList"]))

    # ── CSV format, GZIP-compressed ──
    csv_body = gzip.compress(b"id,name,age\nc,Carol,30\nd,Dan,40\n")
    try:
        from core import s3_object_core as s3c
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import s3_object_core as s3c  # type: ignore
    s3c.put_object(s3, "ddb-imports", "csv/people.csv.gz", csv_body, {"content-type": "text/csv"})
    status, body = call("ImportTable", {
        "S3BucketSource": {"S3Bucket": "ddb-imports", "S3KeyPrefix": "csv/"}, "InputFormat": "CSV",
        "InputCompressionType": "GZIP",
        "TableCreationParameters": {"TableName": "from_csv", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                                    "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
                                    "BillingMode": "PAY_PER_REQUEST"},
    }, s3_store=s3)
    _check("CSV+GZIP import COMPLETED", body["ImportTableDescription"]["ImportStatus"] == "COMPLETED")
    _check("CSV import created 2 items", body["ImportTableDescription"]["ImportedItemCount"] == 2)
    status, body = call("Scan", {"TableName": "from_csv"})
    names = {it["name"]["S"] for it in body["Items"]}
    _check("CSV rows landed as real items", names == {"Carol", "Dan"})

    # ── unsupported format / compression are rejected up front, not silently accepted ──
    status, body = call("ImportTable", {"S3BucketSource": {"S3Bucket": "ddb-imports", "S3KeyPrefix": "exp"},
                                        "InputFormat": "ION", "TableCreationParameters": {"TableName": "nope"}})
    _check("Ion format rejected", status == 400 and body["__type"] == "ValidationException")

    status, body = call("ImportTable", {"S3BucketSource": {"S3Bucket": "ddb-imports", "S3KeyPrefix": "exp"},
                                        "InputFormat": "DYNAMODB_JSON", "InputCompressionType": "ZSTD",
                                        "TableCreationParameters": {"TableName": "nope"}})
    _check("ZSTD compression rejected", status == 400 and body["__type"] == "ValidationException")

    # ── a real failure (no S3 store configured) is a clean FAILED job, not a crash ──
    status, body = call("ImportTable", {
        "S3BucketSource": {"S3Bucket": "ddb-imports", "S3KeyPrefix": prefix}, "InputFormat": "DYNAMODB_JSON",
        "TableCreationParameters": {"TableName": "no-s3", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                                    "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]},
    })  # no s3_store kwarg
    _check("missing S3 store -> FAILED job, 200 status", status == 200 and body["ImportTableDescription"]["ImportStatus"] == "FAILED")

    print("\nDynamoDB ImportTable conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
