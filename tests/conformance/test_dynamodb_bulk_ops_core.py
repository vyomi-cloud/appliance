"""DynamoDB bulk operations (upstream #512-#515): StartBulkPutItems,
ListBulkOperations, DescribeBulkOperation, CancelBulkOperation — native wire."""
try:
    from core.nosql_store import InMemoryNoSqlStore
    from core import dynamodb_core as ddb
except ImportError:  # pragma: no cover
    from nosql_store import InMemoryNoSqlStore  # type: ignore
    import dynamodb_core as ddb  # type: ignore

T = "DynamoDB_20120810."
FAILED = []


def check(name, cond):
    print(("[PASS] " if cond else "[FAIL] ") + name)
    if not cond:
        FAILED.append(name)


def main() -> int:
    st = InMemoryNoSqlStore()
    ddb.dispatch(st, T + "CreateTable", {
        "TableName": "Bulk", "BillingMode": "PAY_PER_REQUEST",
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}]})
    cfg = {"InputS3Configuration": {"S3Bucket": "in", "S3KeyPrefix": "d/"},
           "OutputS3Configuration": {"S3Bucket": "out"}}
    r = ddb.dispatch(st, T + "StartBulkPutItems", {"TableName": "Bulk", "ClientToken": "t1", **cfg})
    d = r.body.get("BulkOperationDescription", {})
    check("start 200 with description", r.status == 200 and d.get("TableName") == "Bulk")
    arn = d.get("BulkOperationArn", "")
    check("arn shape", arn.startswith("arn:aws:dynamodb:") and ":table/Bulk/bulk-operation/" in arn)
    check("status in progress", d.get("BulkOperationStatus") == "IN_PROGRESS")
    r2 = ddb.dispatch(st, T + "StartBulkPutItems", {"TableName": "Bulk", "ClientToken": "t1", **cfg})
    check("client token idempotent", r2.body["BulkOperationDescription"]["BulkOperationArn"] == arn)
    check("missing table 400 RNF", ddb.dispatch(st, T + "StartBulkPutItems",
          {"TableName": "Nope", **cfg}).body.get("__type") == "ResourceNotFoundException")
    check("missing input config validation", ddb.dispatch(st, T + "StartBulkPutItems",
          {"TableName": "Bulk"}).body.get("__type") == "ValidationException")
    ddb.dispatch(st, T + "StartBulkPutItems", {"TableName": "Bulk", **cfg})
    ls = ddb.dispatch(st, T + "ListBulkOperations", {}).body
    check("list returns both", len(ls["BulkOperationsSummaryList"]) == 2)
    pg = ddb.dispatch(st, T + "ListBulkOperations", {"MaxResults": 1}).body
    check("list paginates", len(pg["BulkOperationsSummaryList"]) == 1 and "NextToken" in pg)
    pg2 = ddb.dispatch(st, T + "ListBulkOperations", {"MaxResults": 1, "NextToken": pg["NextToken"]}).body
    check("page 2 differs, no token",
          pg2["BulkOperationsSummaryList"][0]["BulkOperationArn"] != pg["BulkOperationsSummaryList"][0]["BulkOperationArn"]
          and "NextToken" not in pg2)
    ds = ddb.dispatch(st, T + "DescribeBulkOperation", {"BulkOperationArn": arn}).body
    check("describe", ds["BulkOperationDescription"]["BulkOperationArn"] == arn)
    check("describe unknown 404", ddb.dispatch(st, T + "DescribeBulkOperation",
          {"BulkOperationArn": arn + "x"}).body.get("__type") == "ResourceNotFoundException")
    c = ddb.dispatch(st, T + "CancelBulkOperation", {"BulkOperationArn": arn}).body
    check("cancel", c == {"BulkOperationArn": arn, "BulkOperationStatus": "CANCELLED"})
    ds = ddb.dispatch(st, T + "DescribeBulkOperation", {"BulkOperationArn": arn}).body
    check("describe after cancel", ds["BulkOperationDescription"]["BulkOperationStatus"] == "CANCELLED")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
