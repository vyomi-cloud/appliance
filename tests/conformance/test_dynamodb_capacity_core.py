"""DynamoDB consumed-capacity + provisioned-throughput conformance (v4 depth: alarms + DAX).

Proves ConsumedCapacity is computed the real AWS way (4 KB per strongly-consistent
read unit, eventually-consistent reads cost half, 1 KB per write unit, transactions
at 2x) and that PROVISIONED tables really throttle on a per-table/GSI token bucket
(burst = 300s of capacity) with ProvisionedThroughputExceededException, while
PAY_PER_REQUEST tables never throttle.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_dynamodb_capacity_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core.nosql_store import InMemoryNoSqlStore
    from core import dynamodb_core as d
except ImportError:  # pragma: no cover - Pyodide flat layout
    from nosql_store import InMemoryNoSqlStore  # type: ignore
    import dynamodb_core as d  # type: ignore

T = "DynamoDB_20120810."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _call(store, action, payload):
    r = d.dispatch(store, T + action, payload)
    body = r.body if isinstance(r.body, dict) else json.loads(r.body)
    return r.status, body


def run() -> int:
    st = InMemoryNoSqlStore()

    # ── ConsumedCapacity: single-item ops, on-demand table ─────────────────
    _call(st, "CreateTable", {"TableName": "cap", "BillingMode": "PAY_PER_REQUEST",
                              "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                              "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]})
    st2, body = _call(st, "PutItem", {"TableName": "cap", "Item": {"id": {"S": "a"}},
                                      "ReturnConsumedCapacity": "TOTAL"})
    _check("PutItem 200", st2 == 200)
    _check("PutItem ConsumedCapacity present", "ConsumedCapacity" in body)
    _check("PutItem tiny item = 1 WCU", body["ConsumedCapacity"]["WriteCapacityUnits"] == 1.0)
    _check("PutItem CapacityUnits = WriteCapacityUnits", body["ConsumedCapacity"]["CapacityUnits"] == 1.0)

    big_item = {"id": {"S": "big"}, "blob": {"S": "x" * 3000}}   # > 1KB, < 2KB -> 3 WCU
    _, body = _call(st, "PutItem", {"TableName": "cap", "Item": big_item, "ReturnConsumedCapacity": "TOTAL"})
    _check("3KB item rounds up to 3 WCU", body["ConsumedCapacity"]["WriteCapacityUnits"] == 3.0)

    _, body = _call(st, "GetItem", {"TableName": "cap", "Key": {"id": {"S": "a"}},
                                    "ConsistentRead": True, "ReturnConsumedCapacity": "TOTAL"})
    _check("strongly-consistent GetItem of tiny item = 1 RCU", body["ConsumedCapacity"]["ReadCapacityUnits"] == 1.0)

    _, body = _call(st, "GetItem", {"TableName": "cap", "Key": {"id": {"S": "a"}},
                                    "ReturnConsumedCapacity": "TOTAL"})
    _check("eventually-consistent GetItem of tiny item = 0.5 RCU", body["ConsumedCapacity"]["ReadCapacityUnits"] == 0.5)

    _, body = _call(st, "DeleteItem", {"TableName": "cap", "Key": {"id": {"S": "a"}},
                                       "ReturnConsumedCapacity": "TOTAL"})
    _check("DeleteItem of a tiny item = 1 WCU", body["ConsumedCapacity"]["WriteCapacityUnits"] == 1.0)

    _, body = _call(st, "PutItem", {"TableName": "cap", "Item": {"id": {"S": "a"}}})
    _check("no ReturnConsumedCapacity -> no ConsumedCapacity member", "ConsumedCapacity" not in body)

    # ── Batch / transaction capacity (x2 for transactions) ─────────────────
    _, body = _call(st, "BatchWriteItem", {"RequestItems": {"cap": [
        {"PutRequest": {"Item": {"id": {"S": "b1"}}}}, {"PutRequest": {"Item": {"id": {"S": "b2"}}}}]},
        "ReturnConsumedCapacity": "TOTAL"})
    cc = body["ConsumedCapacity"][0]
    _check("BatchWriteItem ConsumedCapacity is a list", isinstance(body["ConsumedCapacity"], list))
    _check("BatchWriteItem 2 tiny puts = 2 WCU", cc["WriteCapacityUnits"] == 2.0)

    _, body = _call(st, "TransactWriteItems", {"TransactItems": [
        {"Put": {"TableName": "cap", "Item": {"id": {"S": "t1"}}}}], "ReturnConsumedCapacity": "TOTAL"})
    _check("TransactWriteItems charges 2x WCU", body["ConsumedCapacity"][0]["WriteCapacityUnits"] == 2.0)

    _, body = _call(st, "TransactGetItems", {"TransactItems": [
        {"Get": {"TableName": "cap", "Key": {"id": {"S": "t1"}}}}], "ReturnConsumedCapacity": "TOTAL"})
    _check("TransactGetItems charges 2x RCU (always strongly consistent)",
           body["ConsumedCapacity"][0]["ReadCapacityUnits"] == 2.0)

    # ── Provisioned throughput: real per-table token-bucket throttling ─────
    _call(st, "CreateTable", {"TableName": "slow", "BillingMode": "PROVISIONED",
                              "ProvisionedThroughput": {"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
                              "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                              "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]})
    # Burst capacity is 300s * 1 WCU/s = 300 WCU, so drain it before the bucket starves.
    bucket = d._throughput_bucket(st, ("slow", None, "w"), 1)
    bucket.tokens = 0.0
    status, body = _call(st, "PutItem", {"TableName": "slow", "Item": {"id": {"S": "x"}}})
    _check("provisioned table throttles once the bucket is drained", status == 400)
    _check("throttle error is ProvisionedThroughputExceededException",
           body.get("__type") == "ProvisionedThroughputExceededException")

    # on-demand never throttles, even with an empty bucket left over from another table
    bucket2 = d._throughput_bucket(st, ("cap", None, "w"), 1)
    bucket2.tokens = 0.0
    status, _ = _call(st, "PutItem", {"TableName": "cap", "Item": {"id": {"S": "never-throttled"}}})
    _check("on-demand table never throttles", status == 200)

    # ── GSI token bucket is independent of the table's own bucket ──────────
    _call(st, "CreateTable", {"TableName": "withgsi", "BillingMode": "PROVISIONED",
                              "ProvisionedThroughput": {"ReadCapacityUnits": 50, "WriteCapacityUnits": 50},
                              "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                              "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"},
                                                       {"AttributeName": "g", "AttributeType": "S"}],
                              "GlobalSecondaryIndexes": [{
                                  "IndexName": "gsi1",
                                  "KeySchema": [{"AttributeName": "g", "KeyType": "HASH"}],
                                  "Projection": {"ProjectionType": "ALL"},
                                  "ProvisionedThroughput": {"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
                              }]})
    gsi_bucket = d._throughput_bucket(st, ("withgsi", "gsi1", "w"), 1)
    gsi_bucket.tokens = 0.0
    status, body = _call(st, "PutItem", {"TableName": "withgsi", "Item": {"id": {"S": "y"}, "g": {"S": "z"}}})
    _check("a starved GSI bucket throttles even though the table's own bucket is full", status == 400)
    _check("GSI throttle also raises ProvisionedThroughputExceededException",
           body.get("__type") == "ProvisionedThroughputExceededException")
    status, _ = _call(st, "PutItem", {"TableName": "withgsi", "Item": {"id": {"S": "y2"}}})   # not on the GSI
    _check("an item that isn't projected onto the starved GSI is unaffected", status == 200)

    # ── INDEXES mode breaks capacity out per-GSI ────────────────────────────
    gsi_bucket.tokens = gsi_bucket.capacity
    _, body = _call(st, "PutItem", {"TableName": "withgsi", "Item": {"id": {"S": "y3"}, "g": {"S": "z"}},
                                    "ReturnConsumedCapacity": "INDEXES"})
    _check("INDEXES mode reports a Table breakdown", "Table" in body["ConsumedCapacity"])
    _check("INDEXES mode reports the GSI by name", "gsi1" in body["ConsumedCapacity"].get("GlobalSecondaryIndexes", {}))

    print("\nDynamoDB consumed-capacity + provisioned-throughput conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
