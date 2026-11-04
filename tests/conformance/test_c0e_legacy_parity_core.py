"""v4 C0e — behaviours ported from the retired offline SQS / EventBridge handlers into the
shared cores, and the upgrade path.

The offline appliance's SQS wire (server.py `_sqs_*`, JSON + Query + ElasticMQ proxy), its
EventBridge wire (core/nats_routes.py, a process-local dict that only published to NATS) and
the classic console REST beside them now run on core/sqs_core.py + core/sns_core.py +
core/eventbridge_core.py over ONE messaging store. Every legacy behaviour the cores lacked —
and that real AWS also has — was ported; this suite pins each one on the in-memory substrate
AND the file-backed (sqlite) substrate (a fresh store instance must see the queues, their
messages, the topics and the rules / targets).

The last section exercises the appliance upgrade path (core/appliance_stores.py: converting
pre-v4 queue records with their messages, adopting pre-v4 EventBridge rules / targets / buses
/ archives and ElasticMQ-only queues) — host only, skipped where the appliance modules don't
import.

Run:  PYTHONPATH=. python3 tests/conformance/test_c0e_legacy_parity_core.py
"""
import hashlib
import json
import struct
import xml.etree.ElementTree as ET

from core import eventbridge_core as eb
from core import sns_core as sns
from core import sqs_core as sqs
from core.messaging_store import InMemoryMessagingStore
from core.persistent_store import PersistentMessagingStore, SqliteStateBackend

Q, E = "AmazonSQS.", "AWSEvents."


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def _call(st, op, body):
    r = sqs.dispatch(st, Q + op, body)
    return r.status, r.body


def _ok(st, op, body):
    s, b = _call(st, op, body)
    if s != 200:
        raise AssertionError((op, b))
    return b


def _ev(st, op, body, **kw):
    return eb.dispatch(st, E + op, body, **kw)


def _ref_md5(attrs):
    """Independent re-statement of the SQS MD5OfMessageAttributes algorithm."""
    out = b""
    for name in sorted(attrs):
        a = attrs[name]
        for part in (name, a["DataType"]):
            b = part.encode()
            out += struct.pack(">I", len(b)) + b
        v = a["StringValue"].encode()
        out += b"\x01" + struct.pack(">I", len(v)) + v
    return hashlib.md5(out).hexdigest()


# ── SQS ─────────────────────────────────────────────────────────────────────
def sqs_parity(make, label):
    st = make()
    st.set_time(10_000.0)

    # legacy (_sqs_validate_queue_name) + real AWS: invalid names are rejected
    s, b = _call(st, "CreateQueue", {"QueueName": "bad name!"})
    _check(f"[{label}] invalid queue name → InvalidParameterValue", s == 400 and b["__type"].endswith("InvalidParameterValue"))
    s, _ = _call(st, "CreateQueue", {"QueueName": "x" * 81})
    _check(f"[{label}] queue name > 80 chars rejected", s == 400)

    url = _ok(st, "CreateQueue", {"QueueName": "orders", "Attributes": {"VisibilityTimeout": "10"}})["QueueUrl"]
    # real AWS: CreateQueue is idempotent with the same attributes, an error with different ones
    # (pre-v4 JSON CreateQueue answered 409 QueueAlreadyExists even for an identical retry)
    _check(f"[{label}] CreateQueue idempotent with the same attributes",
           _call(st, "CreateQueue", {"QueueName": "orders", "Attributes": {"VisibilityTimeout": "10"}})[0] == 200)
    s, b = _call(st, "CreateQueue", {"QueueName": "orders", "Attributes": {"VisibilityTimeout": "20"}})
    _check(f"[{label}] CreateQueue with different attributes → QueueAlreadyExists",
           s == 400 and b["__type"].endswith("QueueAlreadyExists"))

    # legacy: MaximumMessageSize is enforced on send
    _ok(st, "SetQueueAttributes", {"QueueUrl": url, "Attributes": {"MaximumMessageSize": "1024"}})
    s, b = _call(st, "SendMessage", {"QueueUrl": url, "MessageBody": "x" * 2000})
    _check(f"[{label}] message larger than MaximumMessageSize rejected", s == 400 and "shorter than 1024" in b["message"])

    # legacy: DelaySeconds set on the queue later applies to new messages
    _ok(st, "SetQueueAttributes", {"QueueUrl": url, "Attributes": {"DelaySeconds": "5"}})
    _ok(st, "SendMessage", {"QueueUrl": url, "MessageBody": "delayed"})
    _check(f"[{label}] queue DelaySeconds (set later) delays delivery",
           not _ok(st, "ReceiveMessage", {"QueueUrl": url}).get("Messages"))
    attrs = _ok(st, "GetQueueAttributes", {"QueueUrl": url, "AttributeNames": ["All"]})["Attributes"]
    _check(f"[{label}] delayed message counted in ApproximateNumberOfMessagesDelayed",
           attrs["ApproximateNumberOfMessagesDelayed"] == "1" and attrs["ApproximateNumberOfMessagesNotVisible"] == "0", attrs)
    st.advance(6)
    got = _ok(st, "ReceiveMessage", {"QueueUrl": url, "AttributeNames": ["SentTimestamp"]})["Messages"]
    _check(f"[{label}] … delivered once the delay passed", got[0]["Body"] == "delayed")
    _check(f"[{label}] requested system attribute SentTimestamp returned", got[0]["Attributes"]["SentTimestamp"] == "10000000")
    _ok(st, "DeleteMessage", {"QueueUrl": url, "ReceiptHandle": got[0]["ReceiptHandle"]})
    _ok(st, "SetQueueAttributes", {"QueueUrl": url, "Attributes": {"DelaySeconds": "0"}})

    # real AWS: GetQueueAttributes returns only the requested names
    sel = _ok(st, "GetQueueAttributes", {"QueueUrl": url, "AttributeNames": ["VisibilityTimeout"]})["Attributes"]
    _check(f"[{label}] GetQueueAttributes honours AttributeNames", sel == {"VisibilityTimeout": "10"}, sel)

    # legacy (_sqs_sweep_queue): messages older than MessageRetentionPeriod are dropped
    _ok(st, "SetQueueAttributes", {"QueueUrl": url, "Attributes": {"MessageRetentionPeriod": "60"}})
    _ok(st, "SendMessage", {"QueueUrl": url, "MessageBody": "old"})
    st.advance(61)
    _check(f"[{label}] message past MessageRetentionPeriod expires",
           not _ok(st, "ReceiveMessage", {"QueueUrl": url}).get("Messages"))

    # real AWS (every SDK verifies it): MD5OfMessageAttributes on send and receive
    ma = {"color": {"DataType": "String", "StringValue": "blue"}, "n": {"DataType": "Number", "StringValue": "3"}}
    sent = _ok(st, "SendMessage", {"QueueUrl": url, "MessageBody": "attrs", "MessageAttributes": ma})
    _check(f"[{label}] SendMessage MD5OfMessageAttributes", sent["MD5OfMessageAttributes"] == _ref_md5(ma))
    rec = _ok(st, "ReceiveMessage", {"QueueUrl": url, "MessageAttributeNames": ["color"]})["Messages"][0]
    _check(f"[{label}] MessageAttributeNames filters the returned attributes", list(rec["MessageAttributes"]) == ["color"])
    _check(f"[{label}] ReceiveMessage MD5OfMessageAttributes covers the returned ones",
           rec["MD5OfMessageAttributes"] == _ref_md5({"color": ma["color"]}))
    _ok(st, "DeleteMessage", {"QueueUrl": url, "ReceiptHandle": rec["ReceiptHandle"]})
    s, b = _call(st, "ReceiveMessage", {"QueueUrl": url, "MaxNumberOfMessages": 11})
    _check(f"[{label}] MaxNumberOfMessages > 10 rejected (pre-v4 silently clamped)", s == 400)

    # batch operations (pre-v4 offline: InvalidAction)
    b = _ok(st, "SendMessageBatch", {"QueueUrl": url, "Entries": [
        {"Id": "a", "MessageBody": "1"}, {"Id": "b", "MessageBody": "y" * 2000}]})
    _check(f"[{label}] SendMessageBatch partial failure per entry",
           [e["Id"] for e in b["Successful"]] == ["a"] and b["Failed"][0]["Id"] == "b"
           and b["Failed"][0]["Code"] == "InvalidParameterValue" and b["Failed"][0]["SenderFault"] is True)
    s, b = _call(st, "SendMessageBatch", {"QueueUrl": url, "Entries": [{"Id": "x", "MessageBody": "1"}] * 2})
    _check(f"[{label}] duplicate batch Ids → BatchEntryIdsNotDistinct", s == 400 and b["__type"].endswith("BatchEntryIdsNotDistinct"))
    s, b = _call(st, "SendMessageBatch", {"QueueUrl": url, "Entries": [{"Id": str(i), "MessageBody": "1"} for i in range(11)]})
    _check(f"[{label}] 11 batch entries → TooManyEntriesInBatchRequest", s == 400)
    s, b = _call(st, "DeleteMessageBatch", {"QueueUrl": url, "Entries": []})
    _check(f"[{label}] empty batch → EmptyBatchRequest", s == 400 and b["__type"].endswith("EmptyBatchRequest"))
    msgs = _ok(st, "ReceiveMessage", {"QueueUrl": url, "MaxNumberOfMessages": 10})["Messages"]
    cv = _ok(st, "ChangeMessageVisibilityBatch", {"QueueUrl": url, "Entries": [
        {"Id": "m", "ReceiptHandle": msgs[0]["ReceiptHandle"], "VisibilityTimeout": 0},
        {"Id": "bad", "ReceiptHandle": "nope", "VisibilityTimeout": 0}]})
    _check(f"[{label}] ChangeMessageVisibilityBatch", [e["Id"] for e in cv["Successful"]] == ["m"]
           and cv["Failed"][0]["Code"] == "ReceiptHandleIsInvalid")
    msgs = _ok(st, "ReceiveMessage", {"QueueUrl": url, "MaxNumberOfMessages": 10})["Messages"]
    db = _ok(st, "DeleteMessageBatch", {"QueueUrl": url, "Entries": [{"Id": "d", "ReceiptHandle": msgs[0]["ReceiptHandle"]}]})
    _check(f"[{label}] DeleteMessageBatch", [e["Id"] for e in db["Successful"]] == ["d"])

    # FIFO: legacy 5-minute deduplication window (the core kept dedup ids forever)
    f = _ok(st, "CreateQueue", {"QueueName": "f.fifo", "Attributes": {"FifoQueue": "true"}})["QueueUrl"]
    a = _ok(st, "SendMessage", {"QueueUrl": f, "MessageBody": "x", "MessageGroupId": "g", "MessageDeduplicationId": "d1"})
    b2 = _ok(st, "SendMessage", {"QueueUrl": f, "MessageBody": "x", "MessageGroupId": "g", "MessageDeduplicationId": "d1"})
    _check(f"[{label}] FIFO duplicate inside 5 min → same MessageId + SequenceNumber",
           a["MessageId"] == b2["MessageId"] and a["SequenceNumber"] == b2["SequenceNumber"] and len(a["SequenceNumber"]) == 20)
    st.advance(301)
    c = _ok(st, "SendMessage", {"QueueUrl": f, "MessageBody": "x", "MessageGroupId": "g", "MessageDeduplicationId": "d1"})
    _check(f"[{label}] FIFO same dedup id after 5 min → a new message", c["MessageId"] != a["MessageId"]
           and int(c["SequenceNumber"]) > int(a["SequenceNumber"]))

    # DLQ: legacy redrive after maxReceiveCount + the console's "redrive back" (message move task)
    dlq = _ok(st, "CreateQueue", {"QueueName": "dead"})["QueueUrl"]
    dlq_arn = _ok(st, "GetQueueAttributes", {"QueueUrl": dlq})["Attributes"]["QueueArn"]
    src = _ok(st, "CreateQueue", {"QueueName": "work", "Attributes": {"VisibilityTimeout": "1",
              "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": 1})}})["QueueUrl"]
    _ok(st, "SendMessage", {"QueueUrl": src, "MessageBody": "poison"})
    _ok(st, "ReceiveMessage", {"QueueUrl": src})
    st.advance(2)
    _check(f"[{label}] redrive: poison leaves the source", not _ok(st, "ReceiveMessage", {"QueueUrl": src}).get("Messages"))
    dm = _ok(st, "ReceiveMessage", {"QueueUrl": dlq, "VisibilityTimeout": 0, "AttributeNames": ["All"]})["Messages"]
    _check(f"[{label}] redrive: poison in the DLQ with its source ARN",
           dm[0]["Body"] == "poison" and dm[0]["Attributes"]["DeadLetterQueueSourceArn"].endswith(":work"))
    srcs = _ok(st, "ListDeadLetterSourceQueues", {"QueueUrl": dlq})["queueUrls"]
    _check(f"[{label}] ListDeadLetterSourceQueues", [sqs._name_from_url(u) for u in srcs] == ["work"])
    s, b = _call(st, "StartMessageMoveTask", {"SourceArn": _ok(st, "GetQueueAttributes", {"QueueUrl": src})["Attributes"]["QueueArn"]})
    _check(f"[{label}] StartMessageMoveTask from a non-DLQ rejected", s == 400)
    h = _ok(st, "StartMessageMoveTask", {"SourceArn": dlq_arn})["TaskHandle"]
    back = _ok(st, "ReceiveMessage", {"QueueUrl": src})["Messages"]
    _check(f"[{label}] StartMessageMoveTask redrives back to the original source", back[0]["Body"] == "poison" and h)
    tasks = _ok(st, "ListMessageMoveTasks", {"SourceArn": dlq_arn})["Results"]
    _check(f"[{label}] ListMessageMoveTasks", tasks[0]["Status"] == "COMPLETED" and tasks[0]["ApproximateNumberOfMessagesMoved"] == 1)

    # the legacy Query protocol (pre-v4: ElasticMQ proxy / in-memory XML) on the same engine
    code, xml = sqs.dispatch_query(st, {"Action": "SendMessage", "QueueUrl": url, "MessageBody": "q",
                                        "MessageAttribute.1.Name": "k", "MessageAttribute.1.Value.DataType": "String",
                                        "MessageAttribute.1.Value.StringValue": "v"})
    _check(f"[{label}] Query SendMessage → XML with MD5OfMessageAttributes", code == 200 and "<MD5OfMessageAttributes>"
           + _ref_md5({"k": {"DataType": "String", "StringValue": "v"}}) in xml)
    code, xml = sqs.dispatch_query(st, {"Action": "ReceiveMessage", "QueueUrl": url, "MessageAttributeName.1": "All"})
    root = ET.fromstring(xml)
    ns = {"q": sqs.SQS_XML_NS}
    _check(f"[{label}] Query ReceiveMessage XML", root.find(".//q:Message/q:Body", ns).text == "q"
           and root.find(".//q:MessageAttribute/q:Value/q:StringValue", ns).text == "v")
    code, xml = sqs.dispatch_query(st, {"Action": "GetQueueUrl", "QueueName": "missing"})
    _check(f"[{label}] Query error code = AWS.SimpleQueueService.NonExistentQueue",
           code == 400 and "<Code>AWS.SimpleQueueService.NonExistentQueue</Code>" in xml)
    code, xml = sqs.dispatch_query(st, {"Action": "ListQueues"})
    _check(f"[{label}] Query ListQueues", code == 200 and xml.count("<QueueUrl>") == 4)
    code, xml = sqs.dispatch_query(st, {"Action": "SendMessageBatch", "QueueUrl": url,
                                        "SendMessageBatchRequestEntry.1.Id": "a", "SendMessageBatchRequestEntry.1.MessageBody": "b1",
                                        "SendMessageBatchRequestEntry.2.Id": "b", "SendMessageBatchRequestEntry.2.MessageBody": "b2"})
    _check(f"[{label}] Query SendMessageBatch", code == 200 and xml.count("<SendMessageBatchResultEntry>") == 2)

    # durability: a fresh store over the same substrate sees queues + messages
    again = make(reload=True)
    if again is not None:
        _check(f"[{label}] queues + messages survive a fresh store instance",
               again.get_queue("orders") is not None and again.get_queue("work")["messages"]
               and again.get_queue("f.fifo")["dedup_seen"])


# ── EventBridge (+ SNS on the same store) ───────────────────────────────────
def events_parity(make, label):
    st = make()
    qurl = _ok(st, "CreateQueue", {"QueueName": "ev-q"})["QueueUrl"]
    qarn = _ok(st, "GetQueueAttributes", {"QueueUrl": qurl})["Attributes"]["QueueArn"]
    r = _ev(st, "PutRule", {"Name": "bad", "EventPattern": "{not json"})
    _check(f"[{label}] malformed EventPattern → InvalidEventPatternException (pre-v4 stored it)",
           r.status == 400 and r.body["__type"] == "InvalidEventPatternException")
    arn = _ev(st, "PutRule", {"Name": "r1", "EventPattern": json.dumps({"source": ["app"], "detail": {"k": ["v"]}})}).body["RuleArn"]
    _check(f"[{label}] rule ARN carries the store's account (pre-v4: 000000000000)", f":{st.account_id}:rule/r1" in arn)
    _ev(st, "PutTargets", {"Rule": "r1", "Targets": [
        {"Id": "whole", "Arn": qarn},
        {"Id": "const", "Arn": qarn, "Input": '{"fixed":1}'},
        {"Id": "path", "Arn": qarn, "InputPath": "$.detail"},
        {"Id": "tmpl", "Arn": qarn, "InputTransformer": {"InputPathsMap": {"k": "$.detail.k", "src": "$.source"},
                                                          "InputTemplate": '{"key": <k>, "msg": "from <src>"}'}}]})
    tg = {t["Id"]: t for t in _ev(st, "ListTargetsByRule", {"Rule": "r1"}).body["Targets"]}
    _check(f"[{label}] targets keep Input / InputPath / InputTransformer (no null fields)",
           tg["path"]["InputPath"] == "$.detail" and "Input" not in tg["whole"] and tg["tmpl"]["InputTransformer"]["InputPathsMap"])
    r = _ev(st, "PutEvents", {"Entries": [{"Source": "app", "DetailType": "t", "Detail": json.dumps({"k": "v"})},
                                          {"Source": "app", "DetailType": "t", "Detail": json.dumps({"k": "other"})}]})
    _check(f"[{label}] PutEvents", r.body["FailedEntryCount"] == 0)
    bodies = sorted(m["Body"] for m in _ok(st, "ReceiveMessage", {"QueueUrl": qurl, "MaxNumberOfMessages": 10})["Messages"])
    whole = [json.loads(b) for b in bodies if b.startswith('{"version"')]
    _check(f"[{label}] pattern on detail matched exactly one event, 4 targets delivered", len(bodies) == 4, bodies)
    _check(f"[{label}] whole-event target: native envelope, time without millis",
           whole[0]["detail"] == {"k": "v"} and whole[0]["time"].endswith("Z") and len(whole[0]["time"]) == 20
           and whole[0]["account"] == st.account_id)
    _check(f"[{label}] Input target got the constant", '{"fixed":1}' in bodies)
    _check(f"[{label}] InputPath target got $.detail", '{"k": "v"}' in bodies)
    _check(f"[{label}] InputTransformer target got the rendered template", '{"key": "v", "msg": "from app"}' in bodies, bodies)

    # FIFO queue target: SqsParameters.MessageGroupId (real AWS requires it for .fifo targets)
    fq = _ok(st, "CreateQueue", {"QueueName": "ev.fifo", "Attributes": {"FifoQueue": "true"}})["QueueUrl"]
    farn = _ok(st, "GetQueueAttributes", {"QueueUrl": fq})["Attributes"]["QueueArn"]
    _ev(st, "PutRule", {"Name": "rf", "EventPattern": json.dumps({"source": ["fifo"]})})
    _ev(st, "PutTargets", {"Rule": "rf", "Targets": [{"Id": "f", "Arn": farn, "SqsParameters": {"MessageGroupId": "grp"}}]})
    _ev(st, "PutEvents", {"Entries": [{"Source": "fifo", "DetailType": "t", "Detail": "{}"}]})
    fm = _ok(st, "ReceiveMessage", {"QueueUrl": fq})["Messages"]
    _check(f"[{label}] FIFO queue target delivered with its MessageGroupId", fm[0]["Attributes"]["MessageGroupId"] == "grp")

    # SNS on the SAME store: EventBridge → SNS topic → SQS subscription
    topic = ET.fromstring(sns.dispatch(st, {"Action": "CreateTopic", "Name": "t"}).body).find(".//{*}TopicArn").text
    sq = _ok(st, "CreateQueue", {"QueueName": "sub-q"})["QueueUrl"]
    sns.dispatch(st, {"Action": "Subscribe", "TopicArn": topic, "Protocol": "sqs",
                      "Endpoint": _ok(st, "GetQueueAttributes", {"QueueUrl": sq})["Attributes"]["QueueArn"]})
    _ev(st, "PutRule", {"Name": "rs", "EventPattern": json.dumps({"source": ["sns"]})})
    _ev(st, "PutTargets", {"Rule": "rs", "Targets": [{"Id": "t", "Arn": topic}]})
    _ev(st, "PutEvents", {"Entries": [{"Source": "sns", "DetailType": "t", "Detail": "{}"}]})
    sm = _ok(st, "ReceiveMessage", {"QueueUrl": sq})["Messages"]
    _check(f"[{label}] EventBridge → SNS → SQS on one store", json.loads(json.loads(sm[0]["Body"])["Message"])["source"] == "sns")

    again = make(reload=True)
    if again is not None:
        _check(f"[{label}] rules + targets + topics + subscriptions survive a fresh store",
               "default|r1" in again.event_rules and len(again.event_rules["default|r1"]["targets"]) == 4
               and again.get_topic(topic)["subscriptions"])
        _ev(again, "PutEvents", {"Entries": [{"Source": "sns", "DetailType": "t", "Detail": "{}"}]})
        _check(f"[{label}] … and still deliver", _ok(again, "ReceiveMessage", {"QueueUrl": sq}).get("Messages"))


def substrate_hooks():
    """A substrate that owns queues / functions elsewhere (the appliance's opted-out SQS
    handler, its Lambda registry) gets EventBridge deliveries through the store hooks."""
    seen = {"sqs": [], "lambda": [], "notify": []}

    class Hooked(InMemoryMessagingStore):
        def deliver_sqs(self, arn, body, attrs, group, dedup):
            seen["sqs"].append(arn)
            return True

        def deliver_lambda(self, arn, event):
            seen["lambda"].append((arn, event["source"]))
            return True

        def eventbridge_notify(self, kind, *args):
            seen["notify"].append(kind)

    st = Hooked()
    _ev(st, "PutRule", {"Name": "h", "EventPattern": json.dumps({"source": ["h"]})})
    _ev(st, "PutTargets", {"Rule": "h", "Targets": [{"Id": "q", "Arn": "arn:aws:sqs:us-east-1:1:elsewhere"},
                                                    {"Id": "l", "Arn": "arn:aws:lambda:us-east-1:1:function:fn"}]})
    _ev(st, "PutEvents", {"Entries": [{"Source": "h", "DetailType": "t", "Detail": "{}"}]})
    _check("[hooks] SQS target → store.deliver_sqs", seen["sqs"] == ["arn:aws:sqs:us-east-1:1:elsewhere"])
    _check("[hooks] Lambda target → store.deliver_lambda (no lam_store needed)", seen["lambda"] == [("arn:aws:lambda:us-east-1:1:function:fn", "h")])
    _check("[hooks] eventbridge_notify per event + per target (pre-v4 NATS subjects)", seen["notify"] == ["put", "target", "target"])


# ── the appliance upgrade path ──────────────────────────────────────────────
def upgrade_path():
    try:
        from core import appliance_stores as aps
    except Exception:   # pragma: no cover
        print("  skip  upgrade path (appliance modules not importable)")
        return
    st = InMemoryMessagingStore()
    now = st.now()
    import time as _t
    iso = lambda off: _t.strftime("%Y-%m-%dT%H:%M:%S.000Z", _t.gmtime(now + off))   # noqa: E731
    st.queues["legacy-dlq"] = {"queue_name": "legacy-dlq", "queue_arn": f"arn:aws:sqs:us-east-1:{st.account_id}:legacy-dlq",
                               "messages": [], "created": iso(-100)}
    st.queues["legacy"] = {
        "queue_name": "legacy", "queue_url": "http://127.0.0.1:9000/api/sqs/queues/legacy",
        "queue_arn": f"arn:aws:sqs:us-east-1:{st.account_id}:legacy", "queue_type": "standard", "fifo_queue": False,
        "visibility_timeout": 45, "delay_seconds": 0, "message_retention_period": 345600, "max_message_size": 262144,
        "receive_wait_time_seconds": 0, "content_based_deduplication": False, "tags": {"team": "a"}, "attributes": {},
        "redrive_policy": {"deadLetterTargetQueueArn": f"arn:aws:sqs:us-east-1:{st.account_id}:legacy-dlq", "maxReceiveCount": 2},
        "created": iso(-100), "last_modified": iso(-50),
        "messages": [
            {"message_id": "msg-1", "body": "ready", "md5_of_body": hashlib.md5(b"ready").hexdigest(), "sent_at": iso(-60),
             "visible_at": iso(-60), "receive_count": 0, "receipt_handle": "", "in_flight": False, "deleted": False,
             "group_id": "", "dedup_id": "", "attributes": {}, "message_attributes": {"a": {"DataType": "String", "StringValue": "b"}}},
            {"message_id": "msg-2", "body": "leased", "md5_of_body": "", "sent_at": iso(-60), "visible_at": iso(+600),
             "receive_count": 2, "receipt_handle": "rh-old", "in_flight": True, "deleted": False},
            {"message_id": "msg-3", "body": "gone", "deleted": True}]}
    for n in ("legacy-dlq", "legacy"):
        aps.adopt_legacy_queue(st, n, st.queues[n])
    q = st.get_queue("legacy")
    _check("[upgrade] pre-v4 queue converted in place (attributes, redrive key normalised)",
           q["attributes"]["VisibilityTimeout"] == "45" and json.loads(q["attributes"]["RedrivePolicy"])["deadLetterTargetArn"].endswith(":legacy-dlq")
           and q["tags"] == {"team": "a"} and q["created_epoch"] < now)
    _check("[upgrade] deleted messages dropped, live ones kept", [m["message_id"] for m in q["messages"]] == ["msg-1", "msg-2"])
    got = _ok(st, "ReceiveMessage", {"QueueUrl": "http://127.0.0.1:9000/api/sqs/queues/legacy", "MaxNumberOfMessages": 10,
                                     "MessageAttributeNames": ["All"]})["Messages"]
    _check("[upgrade] a pre-v4 queue URL still resolves; only the visible message is delivered",
           [m["Body"] for m in got] == ["ready"] and got[0]["MessageAttributes"]["a"]["StringValue"] == "b")
    _ok(st, "DeleteMessage", {"QueueUrl": "legacy", "ReceiptHandle": got[0]["ReceiptHandle"]})
    _ok(st, "ChangeMessageVisibility", {"QueueUrl": "legacy", "ReceiptHandle": "rh-old", "VisibilityTimeout": 0})
    _check("[upgrade] a running lease's receipt handle stays valid", True)
    # it was received twice before the upgrade (maxReceiveCount 2): now available again → dead-lettered
    _check("[upgrade] … the source no longer delivers it", not _ok(st, "ReceiveMessage", {"QueueUrl": "legacy"}).get("Messages"))
    dl = _ok(st, "ReceiveMessage", {"QueueUrl": "legacy-dlq"}).get("Messages") or []
    _check("[upgrade] the adopted redrive policy dead-letters (receive count carried over)", dl and dl[0]["Body"] == "leased")
    _check("[upgrade] a converted record carries the core marker (AppStateMessagingStore skips it next time)",
           "created_epoch" in q and "created_epoch" in st.get_queue("legacy-dlq"))

    # EventBridge: the classic console's rows + the pre-v4 wire's in-process rules
    extras = {"eventbridge/event-buses": {"orders-bus": {"name": "orders-bus", "type": "Custom"}},
              "eventbridge/rules": {"console-rule": {"name": "console-rule", "event_bus_name": "orders-bus", "rule_type": "EventPattern",
                                                     "state": "ENABLED", "target_arn": f"arn:aws:sqs:us-east-1:{st.account_id}:legacy"},
                                    "nightly": {"name": "nightly", "event_bus_name": "default", "rule_type": "Schedule", "state": "DISABLED"}},
              "eventbridge/archives": {"arch": {"name": "arch", "event_source": "—", "retention_days": 3}}}
    nats = ({"wire-rule": {"Name": "wire-rule", "EventBusName": "default", "State": "ENABLED",
                           "EventPattern": json.dumps({"source": ["legacy.app"]})}},
            {"wire-rule": [{"Id": "t1", "Arn": f"arn:aws:sqs:us-east-1:{st.account_id}:legacy"}]})
    n = aps.adopt_legacy_eventbridge(st, extras, nats)
    _check("[upgrade] EventBridge buses / rules / targets / archives adopted", n == {"buses": 1, "rules": 3, "targets": 2, "archives": 1}, n)
    rules = {k: r for k, r in st.event_rules.items()}
    _check("[upgrade] console rule kept its bus, state, target; schedule rule its type",
           rules["orders-bus|console-rule"]["targets"]["Target0"]["Arn"].endswith(":legacy")
           and rules["default|nightly"]["state"] == "DISABLED" and rules["default|nightly"]["schedule"])
    _ok(st, "PurgeQueue", {"QueueUrl": "legacy"})
    _ev(st, "PutEvents", {"Entries": [{"Source": "legacy.app", "DetailType": "t", "Detail": "{}"}]})
    _check("[upgrade] an adopted pre-v4 wire rule + target now really delivers",
           _ok(st, "ReceiveMessage", {"QueueUrl": "legacy"}).get("Messages"))

    # ElasticMQ-only queues (pre-v4 Query-protocol calls went there when it ran)
    def fake_fetch(params):
        if params["Action"] == "ListQueues":
            return (b'<ListQueuesResponse xmlns="http://queue.amazonaws.com/doc/2012-11-05/"><ListQueuesResult>'
                    b"<QueueUrl>http://elasticmq:9324/000000000000/emq-only</QueueUrl>"
                    b"<QueueUrl>http://elasticmq:9324/000000000000/legacy</QueueUrl></ListQueuesResult></ListQueuesResponse>")
        return (b'<GetQueueAttributesResponse><GetQueueAttributesResult><Attribute><Name>VisibilityTimeout</Name>'
                b"<Value>12</Value></Attribute><Attribute><Name>QueueArn</Name><Value>x</Value></Attribute>"
                b"</GetQueueAttributesResult></GetQueueAttributesResponse>")
    added = aps._adopt_elasticmq_queues(st, fetch=fake_fetch)
    _check("[upgrade] ElasticMQ-only queue definitions adopted (existing ones untouched)",
           added == 1 and st.get_queue("emq-only")["attributes"]["VisibilityTimeout"] == "12"
           and st.get_queue("legacy")["attributes"]["VisibilityTimeout"] == "45")


def _persistent(sid):
    be = SqliteStateBackend(":memory:")

    def make(reload=False):
        return PersistentMessagingStore(be, store_id=sid)
    return make


def _memory():
    def make(reload=False):
        return None if reload else InMemoryMessagingStore()
    return make


def run() -> int:
    print("SQS:")
    sqs_parity(_memory(), "mem")
    sqs_parity(_persistent("c0e-sqs"), "sqlite")
    print("EventBridge + SNS on one store:")
    events_parity(_memory(), "mem")
    events_parity(_persistent("c0e-ev"), "sqlite")
    substrate_hooks()
    print("Upgrade path:")
    upgrade_path()
    print("\nC0e legacy-parity (SQS / SNS / EventBridge cores): ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
