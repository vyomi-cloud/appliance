"""DynamoDB global tables conformance (v4 wave 5b gap sweep) — host + Pyodide.

Vyomi simulates one AWS region, so a replica can't be reached through its own
regional endpoint the way a real cross-region replica is — but the REPLICATION
itself is real: UpdateTable(ReplicaUpdates) backfills a new replica with the
table's current items and then every subsequent write/delete is mirrored into
it (same synchronous-mirror pattern as core/s3_object_core.py's Cross-Region
Replication), and DeleteTable is genuinely rejected while replicas exist —
exactly like real DynamoDB's "replication group must be empty" guard.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_dynamodb_global_tables_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
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

    call("CreateTable", {"TableName": "global", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                         "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
                         "BillingMode": "PAY_PER_REQUEST"})
    call("PutItem", {"TableName": "global", "Item": {"id": {"S": "a"}, "v": {"N": "1"}}})

    status, body = call("UpdateTable", {"TableName": "global",
                                        "ReplicaUpdates": [{"Create": {"RegionName": "eu-west-1"}}]})
    _check("UpdateTable Create replica 200", status == 200)
    replicas = body["TableDescription"]["Replicas"]
    _check("replica present, transitionally CREATING", len(replicas) == 1 and replicas[0]["ReplicaStatus"] == "CREATING")
    _check("GlobalTableVersion reported", body["TableDescription"]["GlobalTableVersion"] == "2019.11.21")

    status, body = call("DescribeTable", {"TableName": "global"})
    _check("replica settles to ACTIVE on describe", body["Table"]["Replicas"][0]["ReplicaStatus"] == "ACTIVE")

    table = s.get_table("global")
    _check("replica was backfilled with the existing item", list(table["replica_items"]["eu-west-1"].keys()) == list(table["items"].keys()))

    call("PutItem", {"TableName": "global", "Item": {"id": {"S": "b"}}})
    call("UpdateItem", {"TableName": "global", "Key": {"id": {"S": "a"}},
                        "UpdateExpression": "SET v = :v", "ExpressionAttributeValues": {":v": {"N": "2"}}})
    call("DeleteItem", {"TableName": "global", "Key": {"id": {"S": "b"}}})

    replica_items = table["replica_items"]["eu-west-1"]
    _check("replica mirrors writes after creation too", set(replica_items.keys()) == set(table["items"].keys()))
    a_key = next(iter(table["items"]))
    _check("replica's copy reflects the update", replica_items[a_key]["av"]["v"] == table["items"][a_key]["av"]["v"])

    # Adding a replica in the primary's own region is rejected (it already "exists" there).
    status, body = call("UpdateTable", {"TableName": "global", "ReplicaUpdates": [{"Create": {"RegionName": "us-east-1"}}]})
    _check("replica in the primary region rejected", status == 400 and body["__type"] == "ReplicaAlreadyExistsException")

    # Duplicate replica region rejected.
    status, body = call("UpdateTable", {"TableName": "global", "ReplicaUpdates": [{"Create": {"RegionName": "eu-west-1"}}]})
    _check("duplicate replica region rejected", status == 400 and body["__type"] == "ReplicaAlreadyExistsException")

    # DeleteTable is genuinely blocked while a replica exists.
    status, body = call("DeleteTable", {"TableName": "global"})
    _check("DeleteTable blocked with active replicas", status == 400 and body["__type"] == "ValidationException")

    status, body = call("UpdateTable", {"TableName": "global", "ReplicaUpdates": [{"Delete": {"RegionName": "eu-west-1"}}]})
    _check("UpdateTable Delete replica 200", status == 200)
    _check("Replicas list now empty", body["TableDescription"].get("Replicas", []) == [])
    _check("replica item mirror dropped", "eu-west-1" not in table.get("replica_items", {}))

    status, body = call("UpdateTable", {"TableName": "global", "ReplicaUpdates": [{"Delete": {"RegionName": "eu-west-1"}}]})
    _check("deleting a nonexistent replica -> ReplicaNotFoundException", status == 400 and body["__type"] == "ReplicaNotFoundException")

    status, body = call("DeleteTable", {"TableName": "global"})
    _check("DeleteTable now succeeds", status == 200)

    print("\nDynamoDB global tables conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
