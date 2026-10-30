"""DynamoDB table-settings conformance (v2.6.0) — host + Pyodide.

Asserts that CreateTable persists TableClass, DeletionProtectionEnabled and
SSESpecification, and that DescribeTable echoes them back — the fields the
v4 console's "Customize settings" branch of Create table now sets for real.
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
        "TableName": "archive",
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
        "BillingMode": "PAY_PER_REQUEST",
        "TableClass": "STANDARD_INFREQUENT_ACCESS",
        "DeletionProtectionEnabled": True,
        "SSESpecification": {"Enabled": True, "SSEType": "KMS"},
    })

    _, body = call("DescribeTable", {"TableName": "archive"})
    table = body["Table"]
    _check("TableClassSummary reflects STANDARD_INFREQUENT_ACCESS",
           table.get("TableClassSummary", {}).get("TableClass") == "STANDARD_INFREQUENT_ACCESS")
    _check("DeletionProtectionEnabled reflects True", table.get("DeletionProtectionEnabled") is True)
    _check("SSEDescription reflects KMS", table.get("SSEDescription", {}).get("SSEType") == "KMS")

    call("CreateTable", {
        "TableName": "plain",
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
        "BillingMode": "PAY_PER_REQUEST",
    })
    _, body = call("DescribeTable", {"TableName": "plain"})
    table = body["Table"]
    _check("default TableClass is STANDARD", table.get("TableClassSummary", {}).get("TableClass") == "STANDARD")
    _check("default DeletionProtectionEnabled is False", table.get("DeletionProtectionEnabled") is False)
    _check("default SSEDescription is absent", "SSEDescription" not in table)

    print("\nDynamoDB table-settings conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
