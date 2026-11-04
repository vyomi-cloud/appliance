"""DynamoDB GSI/LSI (secondary index) query conformance (v2.6.0) — host + Pyodide.

Asserts that CreateTable persists a GSI's KeySchema, DescribeTable emits it, and
Query(IndexName=...) resolves the GSI's own partition/sort keys (not the base
table's) — the whole point of a secondary index. Also covers local secondary
indexes (LSI): share the table's partition key, require the table to have a
range key, and are rejected when that's not the case.
"""
import json

try:
    from core.nosql_store import InMemoryNoSqlStore
    from core import dynamodb_core as d
except ImportError:  # pragma: no cover - Pyodide flat layout
    from nosql_store import InMemoryNoSqlStore  # type: ignore
    import dynamodb_core as d  # type: ignore

P = "DynamoDB_20120810."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or InMemoryNoSqlStore()

    def call(a, p):
        r = d.dispatch(s, P + a, p)
        return r.status, (r.body if isinstance(r.body, dict) else json.loads(r.body))

    call("CreateTable", {
        "TableName": "users",
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"},
                                 {"AttributeName": "email", "AttributeType": "S"}],
        "GlobalSecondaryIndexes": [{"IndexName": "email-index",
                                    "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
                                    "Projection": {"ProjectionType": "ALL"}}],
        "BillingMode": "PAY_PER_REQUEST"})

    _, body = call("DescribeTable", {"TableName": "users"})
    gsis = body["Table"].get("GlobalSecondaryIndexes", [])
    _check("DescribeTable emits GSI", gsis and gsis[0]["IndexName"] == "email-index")

    call("PutItem", {"TableName": "users", "Item": {"id": {"S": "u1"}, "email": {"S": "a@x.com"}, "name": {"S": "Alice"}}})
    call("PutItem", {"TableName": "users", "Item": {"id": {"S": "u2"}, "email": {"S": "b@x.com"}, "name": {"S": "Bob"}}})
    call("PutItem", {"TableName": "users", "Item": {"id": {"S": "u3"}, "email": {"S": "a@x.com"}, "name": {"S": "Al2"}}})

    _, body = call("Query", {"TableName": "users", "IndexName": "email-index",
                             "KeyConditionExpression": "email = :e",
                             "ExpressionAttributeValues": {":e": {"S": "a@x.com"}}})
    names = sorted(i["name"]["S"] for i in body["Items"])
    _check("Query GSI by email → 2 items", names == ["Al2", "Alice"])

    st, body = call("Query", {"TableName": "users", "IndexName": "nope",
                              "KeyConditionExpression": "email = :e",
                              "ExpressionAttributeValues": {":e": {"S": "a@x.com"}}})
    _check("unknown index → ValidationException",
           st == 400 and "does not have the specified index" in body.get("message", ""))

    # ── LSI: shares the table's partition key, needs the table's own range key ──
    st, body = call("CreateTable", {
        "TableName": "orders", "KeySchema": [{"AttributeName": "cust", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "cust", "AttributeType": "S"},
                                 {"AttributeName": "status", "AttributeType": "S"}],
        "LocalSecondaryIndexes": [{"IndexName": "by-status",
                                   "KeySchema": [{"AttributeName": "cust", "KeyType": "HASH"},
                                                 {"AttributeName": "status", "KeyType": "RANGE"}],
                                   "Projection": {"ProjectionType": "ALL"}}]})
    _check("LSI on a table without a range key → ValidationException",
           st == 400 and "does not have a range key" in body.get("message", ""))

    call("CreateTable", {
        "TableName": "orders",
        "KeySchema": [{"AttributeName": "cust", "KeyType": "HASH"}, {"AttributeName": "id", "KeyType": "RANGE"}],
        "AttributeDefinitions": [{"AttributeName": "cust", "AttributeType": "S"}, {"AttributeName": "id", "AttributeType": "S"},
                                 {"AttributeName": "status", "AttributeType": "S"}],
        "LocalSecondaryIndexes": [{"IndexName": "by-status",
                                   "KeySchema": [{"AttributeName": "cust", "KeyType": "HASH"},
                                                 {"AttributeName": "status", "KeyType": "RANGE"}],
                                   "Projection": {"ProjectionType": "ALL"}}],
        "BillingMode": "PAY_PER_REQUEST"})

    _, body = call("DescribeTable", {"TableName": "orders"})
    lsis = body["Table"].get("LocalSecondaryIndexes", [])
    _check("DescribeTable emits LSI", lsis and lsis[0]["IndexName"] == "by-status")

    call("PutItem", {"TableName": "orders", "Item": {"cust": {"S": "c1"}, "id": {"S": "o1"}, "status": {"S": "open"}}})
    call("PutItem", {"TableName": "orders", "Item": {"cust": {"S": "c1"}, "id": {"S": "o2"}, "status": {"S": "closed"}}})
    call("PutItem", {"TableName": "orders", "Item": {"cust": {"S": "c2"}, "id": {"S": "o3"}, "status": {"S": "open"}}})

    _, body = call("Query", {"TableName": "orders", "IndexName": "by-status",
                             "KeyConditionExpression": "cust = :c AND #s = :s",
                             "ExpressionAttributeNames": {"#s": "status"},
                             "ExpressionAttributeValues": {":c": {"S": "c1"}, ":s": {"S": "open"}}})
    _check("Query LSI by status (scoped to partition) → 1 item", len(body["Items"]) == 1 and body["Items"][0]["id"] == {"S": "o1"})

    print("\nDynamoDB GSI/LSI query conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
