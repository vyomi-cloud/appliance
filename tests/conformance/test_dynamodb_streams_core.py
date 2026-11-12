"""DynamoDB Streams conformance (v4 wave 5b gap sweep) — host + Pyodide.

Asserts the stream is a REAL change-data-capture log driven by actual item
writes (not stored config): CreateTable/UpdateTable StreamSpecification opens
a stream with a real StreamArn, every PutItem/UpdateItem/DeleteItem appends a
record with the correct eventName and image per StreamViewType, GetShardIterator
(TRIM_HORIZON/LATEST/AT_SEQUENCE_NUMBER/AFTER_SEQUENCE_NUMBER) + GetRecords page
through them like real DynamoDB Streams, and disabling + re-enabling the stream
opens a NEW StreamArn while the old one stays describable (closed shard).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_dynamodb_streams_core.py
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

    status, body = call("CreateTable", {
        "TableName": "streamed", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
        "BillingMode": "PAY_PER_REQUEST",
        "StreamSpecification": {"StreamEnabled": True, "StreamViewType": "NEW_AND_OLD_IMAGES"},
    })
    _check("CreateTable 200", status == 200)
    desc = body["TableDescription"]
    _check("StreamSpecification enabled", desc["StreamSpecification"]["StreamEnabled"] is True)
    stream_arn = desc["LatestStreamArn"]
    _check("LatestStreamArn carries /stream/", "/stream/" in stream_arn)

    call("PutItem", {"TableName": "streamed", "Item": {"id": {"S": "a"}, "n": {"N": "1"}}})
    call("UpdateItem", {"TableName": "streamed", "Key": {"id": {"S": "a"}},
                        "UpdateExpression": "SET n = :v", "ExpressionAttributeValues": {":v": {"N": "2"}}})
    call("DeleteItem", {"TableName": "streamed", "Key": {"id": {"S": "a"}}})

    status, body = call("DescribeStream", {"StreamArn": stream_arn})
    _check("DescribeStream 200", status == 200)
    sd = body["StreamDescription"]
    _check("StreamStatus ENABLED", sd["StreamStatus"] == "ENABLED")
    _check("one shard", len(sd["Shards"]) == 1)
    shard_id = sd["Shards"][0]["ShardId"]

    status, body = call("GetShardIterator", {"StreamArn": stream_arn, "ShardId": shard_id, "ShardIteratorType": "TRIM_HORIZON"})
    _check("GetShardIterator 200", status == 200)
    it = body["ShardIterator"]

    status, body = call("GetRecords", {"ShardIterator": it})
    _check("GetRecords 200", status == 200)
    recs = body["Records"]
    _check("3 records (INSERT, MODIFY, REMOVE)", [r["eventName"] for r in recs] == ["INSERT", "MODIFY", "REMOVE"])
    _check("INSERT has NewImage, no OldImage", "NewImage" in recs[0]["dynamodb"] and "OldImage" not in recs[0]["dynamodb"])
    _check("MODIFY has both images", "NewImage" in recs[1]["dynamodb"] and "OldImage" in recs[1]["dynamodb"])
    _check("REMOVE has OldImage only", "OldImage" in recs[2]["dynamodb"] and "NewImage" not in recs[2]["dynamodb"])
    _check("open shard always returns a NextShardIterator", body["NextShardIterator"] is not None)

    # AFTER_SEQUENCE_NUMBER from the first record's seq should skip straight to record 2
    seq0 = recs[0]["dynamodb"]["SequenceNumber"]
    status, body = call("GetShardIterator", {"StreamArn": stream_arn, "ShardId": shard_id,
                                             "ShardIteratorType": "AFTER_SEQUENCE_NUMBER", "SequenceNumber": seq0})
    status, body = call("GetRecords", {"ShardIterator": body["ShardIterator"]})
    _check("AFTER_SEQUENCE_NUMBER skips record 0", [r["eventName"] for r in body["Records"]] == ["MODIFY", "REMOVE"])

    # LATEST sees nothing until a new write happens
    status, body = call("GetShardIterator", {"StreamArn": stream_arn, "ShardId": shard_id, "ShardIteratorType": "LATEST"})
    latest_it = body["ShardIterator"]
    status, body = call("GetRecords", {"ShardIterator": latest_it})
    _check("LATEST starts empty", body["Records"] == [])
    call("PutItem", {"TableName": "streamed", "Item": {"id": {"S": "b"}}})
    status, body = call("GetRecords", {"ShardIterator": latest_it})
    _check("LATEST then sees the new write", [r["eventName"] for r in body["Records"]] == ["INSERT"])

    status, body = call("ListStreams", {"TableName": "streamed"})
    _check("ListStreams lists the one stream", [x["StreamArn"] for x in body["Streams"]] == [stream_arn])

    # Disable -> re-enable opens a NEW stream; the old one is still describable (closed).
    call("UpdateTable", {"TableName": "streamed", "StreamSpecification": {"StreamEnabled": False}})
    status, body = call("DescribeTable", {"TableName": "streamed"})
    _check("stream disabled", body["Table"]["StreamSpecification"]["StreamEnabled"] is False)
    status, body = call("DescribeStream", {"StreamArn": stream_arn})
    _check("old stream still describable", status == 200 and body["StreamDescription"]["StreamStatus"] == "DISABLED")
    _check("old stream shard is closed", "EndingSequenceNumber" in body["StreamDescription"]["Shards"][0]["SequenceNumberRange"])

    status, body = call("UpdateTable", {"TableName": "streamed",
                                        "StreamSpecification": {"StreamEnabled": True, "StreamViewType": "KEYS_ONLY"}})
    new_arn = body["TableDescription"]["LatestStreamArn"]
    _check("re-enabling opens a new StreamArn", new_arn != stream_arn)
    status, body = call("ListStreams", {"TableName": "streamed"})
    _check("ListStreams now lists both generations", sorted(x["StreamArn"] for x in body["Streams"]) == sorted([stream_arn, new_arn]))

    # KEYS_ONLY view carries neither image.
    call("PutItem", {"TableName": "streamed", "Item": {"id": {"S": "c"}, "extra": {"S": "x"}}})
    status, body = call("DescribeStream", {"StreamArn": new_arn})
    shard_id2 = body["StreamDescription"]["Shards"][0]["ShardId"]
    status, body = call("GetShardIterator", {"StreamArn": new_arn, "ShardId": shard_id2, "ShardIteratorType": "TRIM_HORIZON"})
    status, body = call("GetRecords", {"ShardIterator": body["ShardIterator"]})
    _check("KEYS_ONLY record has Keys but no images", body["Records"][0]["dynamodb"]["Keys"] == {"id": {"S": "c"}}
           and "NewImage" not in body["Records"][0]["dynamodb"])

    # Unknown stream arn -> ResourceNotFoundException, not a crash.
    status, body = call("DescribeStream", {"StreamArn": "arn:aws:dynamodb:us-east-1:123456789012:table/nope/stream/nope"})
    _check("unknown stream -> ResourceNotFoundException", status == 400 and body["__type"] == "ResourceNotFoundException")

    print("\nDynamoDB Streams conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
