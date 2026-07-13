"""DynamoDB GSI (global secondary index) query conformance (v2.6.0) — host + Pyodide.

Asserts that CreateTable persists a GSI's KeySchema, DescribeTable emits it, and
Query(IndexName=...) resolves the GSI's own partition/sort keys (not the base
table's) — the whole point of a secondary index.
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

    print("\nDynamoDB GSI query conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
