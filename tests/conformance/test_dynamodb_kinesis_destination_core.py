"""DynamoDB Kinesis Data Streams destination conformance (v4 wave 5b) — host + Pyodide.

Asserts EnableKinesisStreamingDestination really requires an existing Kinesis
stream (the two cores share one process so this is checked for real, not
assumed), and that every item write/delete after that is genuinely published
as a change-data-capture record into that REAL Kinesis stream (core/kinesis_core.py)
via GetRecords — not stored config with no effect.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_dynamodb_kinesis_destination_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import base64
import json

try:
    from core.nosql_store import InMemoryNoSqlStore
    from core import dynamodb_core as d
    from core import kinesis_core as k
except ImportError:  # pragma: no cover - Pyodide flat layout
    from nosql_store import InMemoryNoSqlStore  # type: ignore
    import dynamodb_core as d  # type: ignore
    import kinesis_core as k  # type: ignore

P = "DynamoDB_20120810."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None, kinesis_store=None):
    s = store or InMemoryNoSqlStore()
    ks = kinesis_store if kinesis_store is not None else k.KinesisStore()
    s.kinesis_store = ks

    def call(a, p):
        r = d.dispatch(s, P + a, p)
        return r.status, (r.body if isinstance(r.body, dict) else json.loads(r.body))

    call("CreateTable", {"TableName": "cdc", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                         "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
                         "BillingMode": "PAY_PER_REQUEST"})

    # Enabling against a Kinesis stream that doesn't exist is a real, checked failure.
    status, body = call("EnableKinesisStreamingDestination", {"TableName": "cdc",
                        "StreamArn": "arn:aws:kinesis:us-east-1:123456789012:stream/missing"})
    _check("enable against missing stream -> ResourceNotFoundException", status == 400 and body["__type"] == "ResourceNotFoundException")

    k.create_stream(ks, {"StreamName": "ddb-cdc", "ShardCount": 1})
    stream_arn = k._arn(ks, "ddb-cdc")

    status, body = call("EnableKinesisStreamingDestination", {"TableName": "cdc", "StreamArn": stream_arn})
    _check("EnableKinesisStreamingDestination 200", status == 200)
    _check("destination ACTIVE", body["DestinationStatus"] == "ACTIVE")

    status, body = call("DescribeKinesisStreamingDestination", {"TableName": "cdc"})
    _check("DescribeKinesisStreamingDestination lists it", body["KinesisDataStreamDestinations"][0]["StreamArn"] == stream_arn)

    # Enabling a second time (already active) is rejected like real AWS.
    status, body = call("EnableKinesisStreamingDestination", {"TableName": "cdc", "StreamArn": stream_arn})
    _check("double-enable -> ResourceInUseException", status == 400 and body["__type"] == "ResourceInUseException")

    call("PutItem", {"TableName": "cdc", "Item": {"id": {"S": "a"}, "v": {"N": "1"}}})
    call("UpdateItem", {"TableName": "cdc", "Key": {"id": {"S": "a"}},
                        "UpdateExpression": "SET v = :v", "ExpressionAttributeValues": {":v": {"N": "2"}}})
    call("DeleteItem", {"TableName": "cdc", "Key": {"id": {"S": "a"}}})

    # Read the records back from the REAL Kinesis stream.
    shards = k.list_shards(ks, {"StreamName": "ddb-cdc"})["Shards"]
    it = k.get_shard_iterator(ks, {"StreamName": "ddb-cdc", "ShardId": shards[0]["ShardId"], "ShardIteratorType": "TRIM_HORIZON"})["ShardIterator"]
    recs = k.get_records(ks, {"ShardIterator": it})["Records"]
    _check("3 CDC records landed in the real Kinesis stream", len(recs) == 3)
    payloads = [json.loads(base64.b64decode(r["Data"])) for r in recs]
    _check("event names match the writes", [p["eventName"] for p in payloads] == ["INSERT", "MODIFY", "REMOVE"])
    _check("table name carried on each record", all(p["tableName"] == "cdc" for p in payloads))

    status, body = call("DisableKinesisStreamingDestination", {"TableName": "cdc", "StreamArn": stream_arn})
    _check("DisableKinesisStreamingDestination 200", status == 200 and body["DestinationStatus"] == "DISABLED")

    # After disabling, no further records are published.
    call("PutItem", {"TableName": "cdc", "Item": {"id": {"S": "b"}}})
    recs2 = k.get_records(ks, {"ShardIterator": k.get_shard_iterator(
        ks, {"StreamName": "ddb-cdc", "ShardId": shards[0]["ShardId"], "ShardIteratorType": "AFTER_SEQUENCE_NUMBER",
            "StartingSequenceNumber": recs[-1]["SequenceNumber"]})["ShardIterator"]})["Records"]
    _check("disabled destination publishes nothing new", len(recs2) == 0)

    print("\nDynamoDB Kinesis Data Streams destination conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
