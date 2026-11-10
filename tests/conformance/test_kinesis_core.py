"""Kinesis Data Streams core conformance — host + Pyodide.

Stream lifecycle, hash-key routing, PutRecord(s)/GetShardIterator/GetRecords for every
iterator type, shard split/merge/rescale lineage, retention, encryption, monitoring, tags,
enhanced fan-out consumers, resource policy and the real error codes.
"""
import base64
import json

try:
    from core import kinesis_core as k
except ImportError:  # pragma: no cover - Pyodide flat layout
    import kinesis_core as k  # type: ignore

T = "Kinesis_20131202."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def b64(s):
    return base64.b64encode(s.encode()).decode()


def run(store=None):
    s = store or k.KinesisStore()

    def call(a, b=None):
        return k.dispatch(s, T + a, b or {})

    r = call("CreateStream", {"StreamName": "orders", "ShardCount": 2})
    _check("CreateStream", r.status == 200)
    _check("duplicate → ResourceInUseException", call("CreateStream", {"StreamName": "orders", "ShardCount": 1}).body["__type"] == "ResourceInUseException")
    _check("bad name → InvalidArgumentException", call("CreateStream", {"StreamName": "bad name!", "ShardCount": 1}).body["__type"] == "InvalidArgumentException")
    d = call("DescribeStream", {"StreamName": "orders"}).body["StreamDescription"]
    _check("DescribeStream ACTIVE with 2 shards", d["StreamStatus"] == "ACTIVE" and len(d["Shards"]) == 2)
    _check("hash ranges cover the 128-bit space", d["Shards"][0]["HashKeyRange"]["StartingHashKey"] == "0" and d["Shards"][1]["HashKeyRange"]["EndingHashKey"] == str(2 ** 128 - 1))
    _check("ARN shape", d["StreamARN"].startswith("arn:aws:kinesis:us-east-1:") and d["StreamARN"].endswith(":stream/orders"))
    sm = call("DescribeStreamSummary", {"StreamName": "orders"}).body["StreamDescriptionSummary"]
    _check("DescribeStreamSummary", sm["OpenShardCount"] == 2 and sm["RetentionPeriodHours"] == 24)
    _check("DescribeStream missing → ResourceNotFound", call("DescribeStream", {"StreamName": "nope"}).body["__type"] == "ResourceNotFoundException")
    _check("ListStreams", call("ListStreams").body["StreamNames"] == ["orders"])

    seqs = {}
    for i in range(6):
        p = call("PutRecord", {"StreamName": "orders", "PartitionKey": f"pk-{i % 3}", "Data": b64(f"msg-{i}")}).body
        seqs.setdefault(p["ShardId"], []).append(p["SequenceNumber"])
    _check("same partition key → same shard", sum(len(v) for v in seqs.values()) == 6)
    _check("sequence numbers are 56 digits and increasing", all(len(x) == 56 and x.isdigit() for v in seqs.values() for x in v) and all(v == sorted(v) for v in seqs.values()))
    pr = call("PutRecords", {"StreamName": "orders", "Records": [{"PartitionKey": "a", "Data": b64("x")}, {"PartitionKey": "b", "Data": b64("y"), "ExplicitHashKey": "0"}]}).body
    _check("PutRecords", pr["FailedRecordCount"] == 0 and pr["Records"][1]["ShardId"] == "shardId-000000000000")

    got = []
    for sh in d["Shards"]:
        it = call("GetShardIterator", {"StreamName": "orders", "ShardId": sh["ShardId"], "ShardIteratorType": "TRIM_HORIZON"}).body["ShardIterator"]
        g = call("GetRecords", {"ShardIterator": it}).body
        got += [base64.b64decode(r["Data"]).decode() for r in g["Records"]]
        _check("GetRecords has NextShardIterator", bool(g["NextShardIterator"]))
    _check("TRIM_HORIZON reads every record", len(got) == 8)
    sh0 = d["Shards"][0]["ShardId"]
    first = seqs.get(sh0) or [pr["Records"][1]["SequenceNumber"]]
    at = call("GetShardIterator", {"StreamName": "orders", "ShardId": sh0, "ShardIteratorType": "AT_SEQUENCE_NUMBER", "StartingSequenceNumber": first[0]}).body["ShardIterator"]
    after = call("GetShardIterator", {"StreamName": "orders", "ShardId": sh0, "ShardIteratorType": "AFTER_SEQUENCE_NUMBER", "StartingSequenceNumber": first[0]}).body["ShardIterator"]
    _check("AFTER_SEQUENCE_NUMBER skips one", len(call("GetRecords", {"ShardIterator": at}).body["Records"]) - 1 == len(call("GetRecords", {"ShardIterator": after}).body["Records"]))
    latest = call("GetShardIterator", {"StreamName": "orders", "ShardId": sh0, "ShardIteratorType": "LATEST"}).body["ShardIterator"]
    _check("LATEST sees nothing old", call("GetRecords", {"ShardIterator": latest}).body["Records"] == [])
    lim = call("GetRecords", {"ShardIterator": call("GetShardIterator", {"StreamName": "orders", "ShardId": sh0, "ShardIteratorType": "TRIM_HORIZON"}).body["ShardIterator"], "Limit": 1}).body
    _check("GetRecords Limit", len(lim["Records"]) == 1)
    _check("bad iterator → InvalidArgument", call("GetRecords", {"ShardIterator": "garbage"}).body["__type"] == "InvalidArgumentException")
    _check("bad iterator type", call("GetShardIterator", {"StreamName": "orders", "ShardId": sh0, "ShardIteratorType": "SOMETIME"}).body["__type"] == "InvalidArgumentException")
    _check("AT_TIMESTAMP", call("GetShardIterator", {"StreamName": "orders", "ShardId": sh0, "ShardIteratorType": "AT_TIMESTAMP", "Timestamp": 0}).status == 200)

    # reshard lineage
    call("CreateStream", {"StreamName": "rs", "ShardCount": 1})
    mid = str(2 ** 127)
    _check("SplitShard", call("SplitShard", {"StreamName": "rs", "ShardToSplit": "shardId-000000000000", "NewStartingHashKey": mid}).status == 200)
    shards = call("ListShards", {"StreamName": "rs"}).body["Shards"]
    _check("split → parent closed + 2 children", len(shards) == 3 and "EndingSequenceNumber" in shards[0]["SequenceNumberRange"] and shards[1]["ParentShardId"] == shards[0]["ShardId"])
    _check("open shards = 2", call("DescribeStreamSummary", {"StreamName": "rs"}).body["StreamDescriptionSummary"]["OpenShardCount"] == 2)
    _check("MergeShards", call("MergeShards", {"StreamName": "rs", "ShardToMerge": shards[1]["ShardId"], "AdjacentShardToMerge": shards[2]["ShardId"]}).status == 200)
    _check("merge → 1 open", call("DescribeStreamSummary", {"StreamName": "rs"}).body["StreamDescriptionSummary"]["OpenShardCount"] == 1)
    _check("UpdateShardCount", call("UpdateShardCount", {"StreamName": "rs", "TargetShardCount": 2, "ScalingType": "UNIFORM_SCALING"}).body["TargetShardCount"] == 2)
    _check("UpdateShardCount too far", call("UpdateShardCount", {"StreamName": "rs", "TargetShardCount": 9, "ScalingType": "UNIFORM_SCALING"}).body["__type"] == "InvalidArgumentException")
    ls = call("ListShards", {"StreamName": "rs", "MaxResults": 2}).body
    _check("ListShards pagination", len(ls["Shards"]) == 2 and ls["NextToken"] and len(call("ListShards", {"NextToken": ls["NextToken"]}).body["Shards"]) >= 1)

    # config
    _check("IncreaseRetention", call("IncreaseStreamRetentionPeriod", {"StreamName": "orders", "RetentionPeriodHours": 48}).status == 200)
    _check("retention shows in describe", call("DescribeStreamSummary", {"StreamName": "orders"}).body["StreamDescriptionSummary"]["RetentionPeriodHours"] == 48)
    _check("IncreaseRetention must grow", call("IncreaseStreamRetentionPeriod", {"StreamName": "orders", "RetentionPeriodHours": 24}).body["__type"] == "InvalidArgumentException")
    _check("DecreaseRetention", call("DecreaseStreamRetentionPeriod", {"StreamName": "orders", "RetentionPeriodHours": 24}).status == 200)
    call("StartStreamEncryption", {"StreamName": "orders", "EncryptionType": "KMS", "KeyId": "alias/aws/kinesis"})
    _check("StartStreamEncryption", call("DescribeStream", {"StreamName": "orders"}).body["StreamDescription"]["EncryptionType"] == "KMS")
    call("StopStreamEncryption", {"StreamName": "orders", "EncryptionType": "KMS", "KeyId": "alias/aws/kinesis"})
    _check("StopStreamEncryption", call("DescribeStream", {"StreamName": "orders"}).body["StreamDescription"]["EncryptionType"] == "NONE")
    em = call("EnableEnhancedMonitoring", {"StreamName": "orders", "ShardLevelMetrics": ["IncomingBytes"]}).body
    _check("EnableEnhancedMonitoring", em["DesiredShardLevelMetrics"] == ["IncomingBytes"])
    _check("DisableEnhancedMonitoring", call("DisableEnhancedMonitoring", {"StreamName": "orders", "ShardLevelMetrics": ["IncomingBytes"]}).body["DesiredShardLevelMetrics"] == [])
    _check("UpdateStreamMode", call("UpdateStreamMode", {"StreamARN": d["StreamARN"], "StreamModeDetails": {"StreamMode": "ON_DEMAND"}}).status == 200)
    _check("DescribeLimits", call("DescribeLimits").body["ShardLimit"] == 500)

    # tags
    call("AddTagsToStream", {"StreamName": "orders", "Tags": {"env": "dev", "team": "core"}})
    _check("ListTagsForStream", {t["Key"]: t["Value"] for t in call("ListTagsForStream", {"StreamName": "orders"}).body["Tags"]} == {"env": "dev", "team": "core"})
    call("RemoveTagsFromStream", {"StreamName": "orders", "TagKeys": ["team"]})
    _check("RemoveTagsFromStream", [t["Key"] for t in call("ListTagsForStream", {"StreamName": "orders"}).body["Tags"]] == ["env"])
    call("TagResource", {"ResourceARN": d["StreamARN"], "Tags": {"k": "v"}})
    _check("TagResource / ListTagsForResource", len(call("ListTagsForResource", {"ResourceARN": d["StreamARN"]}).body["Tags"]) == 2)
    call("UntagResource", {"ResourceARN": d["StreamARN"], "TagKeys": ["k"]})
    _check("UntagResource", len(call("ListTagsForResource", {"ResourceARN": d["StreamARN"]}).body["Tags"]) == 1)

    # consumers
    c = call("RegisterStreamConsumer", {"StreamARN": d["StreamARN"], "ConsumerName": "analytics"}).body["Consumer"]
    _check("RegisterStreamConsumer", c["ConsumerStatus"] == "ACTIVE")
    _check("duplicate consumer", call("RegisterStreamConsumer", {"StreamARN": d["StreamARN"], "ConsumerName": "analytics"}).body["__type"] == "ResourceInUseException")
    _check("DescribeStreamConsumer", call("DescribeStreamConsumer", {"ConsumerARN": c["ConsumerARN"]}).body["ConsumerDescription"]["StreamARN"] == d["StreamARN"])
    _check("ListStreamConsumers", len(call("ListStreamConsumers", {"StreamARN": d["StreamARN"]}).body["Consumers"]) == 1)
    _check("DeleteStream blocked by consumers", call("DeleteStream", {"StreamName": "orders"}).body["__type"] == "ResourceInUseException")
    call("DeregisterStreamConsumer", {"StreamARN": d["StreamARN"], "ConsumerName": "analytics"})
    _check("DeregisterStreamConsumer", call("ListStreamConsumers", {"StreamARN": d["StreamARN"]}).body["Consumers"] == [])

    # resource policy
    pol = json.dumps({"Version": "2012-10-17", "Statement": []})
    call("PutResourcePolicy", {"ResourceARN": d["StreamARN"], "Policy": pol})
    _check("Get/PutResourcePolicy", call("GetResourcePolicy", {"ResourceARN": d["StreamARN"]}).body["Policy"] == pol)
    call("DeleteResourcePolicy", {"ResourceARN": d["StreamARN"]})
    _check("DeleteResourcePolicy", call("GetResourcePolicy", {"ResourceARN": d["StreamARN"]}).body["Policy"] == "{}")

    # CBOR wire (what the Java SDK sends): same engine, blob Data as a CBOR byte string
    st, hd, out = k.handle_wire(s, T + "CreateStream", k.cbor_dumps({"StreamName": "cb", "ShardCount": 1}), "application/x-amz-cbor-1.1")
    _check("CBOR CreateStream", st == 200 and hd["content-type"] == "application/x-amz-cbor-1.1")
    st, hd, out = k.handle_wire(s, T + "PutRecord", k.cbor_dumps({"StreamName": "cb", "PartitionKey": "p", "Data": b"\x00blob\xff"}), "application/x-amz-cbor-1.1")
    put = k.cbor_loads(out)
    _check("CBOR PutRecord", st == 200 and len(put["SequenceNumber"]) == 56)
    it = k.cbor_loads(k.handle_wire(s, T + "GetShardIterator", k.cbor_dumps({"StreamName": "cb", "ShardId": put["ShardId"], "ShardIteratorType": "TRIM_HORIZON"}), "application/x-amz-cbor-1.1")[2])["ShardIterator"]
    rec = k.cbor_loads(k.handle_wire(s, T + "GetRecords", k.cbor_dumps({"ShardIterator": it}), "application/x-amz-cbor-1.1")[2])["Records"][0]
    _check("CBOR GetRecords returns Data as a byte string", rec["Data"] == b"\x00blob\xff")
    st, hd, out = k.handle_wire(s, T + "DescribeStream", k.cbor_dumps({"StreamName": "missing"}), "application/x-amz-cbor-1.1")
    _check("CBOR error carries __type + x-amzn-ErrorType", st == 400 and hd["x-amzn-ErrorType"] == "ResourceNotFoundException" and k.cbor_loads(out)["__type"] == "ResourceNotFoundException")
    _check("CBOR indefinite-length containers", k.cbor_loads(bytes.fromhex("bf61619f0102ffff")) == {"a": [1, 2]})
    k.dispatch(s, T + "DeleteStream", {"StreamName": "cb"})

    # console facade
    cc = k.console_create(s, {"name": "ui-stream", "shard_count": 2, "retention_hours": 48})
    _check("console_create fills every grid column", all(cc.get(c) not in (None, "", "-") for c in ("name", "status", "capacity_mode", "open_shards", "retention", "encryption", "consumers", "created", "arn")))
    _check("console_list / delete", k.console_list(s)["count"] >= 1 and k.console_delete(s, "ui-stream")["ok"])

    _check("DeleteStream", call("DeleteStream", {"StreamName": "orders"}).status == 200)
    _check("deleted stream is gone", call("DescribeStream", {"StreamName": "orders"}).body["__type"] == "ResourceNotFoundException")
    _check("unknown op", call("Frobnicate").body["__type"] == "UnknownOperationException")
    print("\nKinesis Data Streams conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
