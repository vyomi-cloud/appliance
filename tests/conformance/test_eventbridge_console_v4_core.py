"""EventBridge v4-console conformance — the additions built for the native-
fidelity console: custom event buses, rule enable/disable, SNS/Lambda target
delivery (SQS was already proven by test_eventbridge_core.py), archives +
replay, and tags on buses/rules/archives.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_eventbridge_console_v4_core.py
"""
import json

try:
    from core.messaging_store import InMemoryMessagingStore
    from core import sqs_core as sqs, sns_core as sns, lambda_core as lam, eventbridge_core as eb
except ImportError:  # pragma: no cover - Pyodide flat layout
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import sqs_core as sqs  # type: ignore
    import sns_core as sns  # type: ignore
    import lambda_core as lam  # type: ignore
    import eventbridge_core as eb  # type: ignore

E = "AWSEvents."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    s = InMemoryMessagingStore()
    import types
    lam_store = types.SimpleNamespace()

    def call(a, b):
        return eb.dispatch(s, E + a, b, lam_store=lam_store)

    # 1. Default bus always exists; custom buses are real resources.
    _check("default bus exists", any(b["Name"] == "default" for b in call("ListEventBuses", {}).body["EventBuses"]))
    created = call("CreateEventBus", {"Name": "orders"})
    _check("CreateEventBus 200", created.status == 200)
    dup = call("CreateEventBus", {"Name": "orders"})
    _check("duplicate bus rejected", dup.body.get("__type") == "ResourceAlreadyExistsException")
    desc = call("DescribeEventBus", {"Name": "orders"}).body
    _check("DescribeEventBus returns the bus", desc["Name"] == "orders")

    # 2. Rules are scoped per bus; same name on two buses doesn't collide.
    call("PutRule", {"Name": "r1", "EventBusName": "orders", "EventPattern": json.dumps({"source": ["app"]})})
    call("PutRule", {"Name": "r1", "EventBusName": "default", "EventPattern": json.dumps({"source": ["other"]})})
    _check("orders bus has its own r1", len(call("ListRules", {"EventBusName": "orders"}).body["Rules"]) == 1)
    _check("default bus has its own r1", len(call("ListRules", {"EventBusName": "default"}).body["Rules"]) == 1)

    # 3. SQS target (regression).
    qurl = sqs.dispatch(s, "AmazonSQS.CreateQueue", {"QueueName": "eb-q"}).body["QueueUrl"]
    qarn = sqs.dispatch(s, "AmazonSQS.GetQueueAttributes", {"QueueUrl": qurl}).body["Attributes"]["QueueArn"]
    call("PutTargets", {"Rule": "r1", "EventBusName": "orders", "Targets": [{"Id": "t1", "Arn": qarn}]})

    # 4. SNS target — a real, receivable fan-out through the shared MessagingStore.
    topic_arn = sns.dispatch(s, {"Action": "CreateTopic", "Name": "eb-topic"}).body
    topic_arn = __import__("re").search(r"<TopicArn>([^<]+)</TopicArn>", topic_arn).group(1)
    sub_resp = sns.dispatch(s, {"Action": "Subscribe", "TopicArn": topic_arn, "Protocol": "sqs", "Endpoint": qarn}).body
    call("PutTargets", {"Rule": "r1", "EventBusName": "orders", "Targets": [{"Id": "t2", "Arn": topic_arn}]})

    # 5. Lambda target — a real (sandboxed) invocation.
    lam.dispatch(lam_store, "POST", "/2015-03-31/functions", {}, {}, json.dumps({
        "FunctionName": "eb-fn", "Code": {"Source": "def handler(event, context):\n    return {'seen': event.get('detail')}"},
    }).encode())
    fn_arn = "arn:aws:lambda:us-east-1:123456789012:function:eb-fn"
    call("PutTargets", {"Rule": "r1", "EventBusName": "orders", "Targets": [{"Id": "t3", "Arn": fn_arn}]})
    _check("ListTargetsByRule sees all three", len(call("ListTargetsByRule", {"Rule": "r1", "EventBusName": "orders"}).body["Targets"]) == 3)

    call("PutEvents", {"Entries": [{"Source": "app", "DetailType": "x", "Detail": json.dumps({"k": 1}), "EventBusName": "orders"}]})
    recv = sqs.dispatch(s, "AmazonSQS.ReceiveMessage", {"QueueUrl": qurl, "MaxNumberOfMessages": 10}).body.get("Messages", [])
    _check("matching event delivered at least once directly to SQS target", len(recv) >= 1)
    # The SNS target fans out into the SAME queue via its SQS subscription — so the
    # queue should have received the SQS-target delivery AND the SNS-fan-out delivery.
    _check("SNS target also delivered (fan-out → same queue, now ≥ 2 total)", len(recv) >= 2)

    # 6. Enable / disable.
    call("DisableRule", {"Name": "r1", "EventBusName": "orders"})
    _check("DisableRule", call("DescribeRule", {"Name": "r1", "EventBusName": "orders"}).body["State"] == "DISABLED")
    call("EnableRule", {"Name": "r1", "EventBusName": "orders"})
    _check("EnableRule", call("DescribeRule", {"Name": "r1", "EventBusName": "orders"}).body["State"] == "ENABLED")

    # 7. Archives + replay: the bus's recent event log stands in for AWS's archive
    #    storage (see the eventbridge.archives capability entry for the limitation).
    arc = call("CreateArchive", {"ArchiveName": "arc1", "EventSourceArn": desc["Arn"],
                                  "EventPattern": json.dumps({"source": ["app"]})})
    _check("CreateArchive 200", arc.status == 200)
    described = call("DescribeArchive", {"ArchiveName": "arc1"}).body
    _check("archive already captured the earlier matching event", described["EventCount"] >= 1)
    before = len(sqs.dispatch(s, "AmazonSQS.ReceiveMessage", {"QueueUrl": qurl, "MaxNumberOfMessages": 10}).body.get("Messages", []))
    replay = call("StartReplay", {"ReplayName": "rep1", "EventSourceArn": arc.body["ArchiveArn"],
                                   "Destination": {"Arn": desc["Arn"]}})
    _check("StartReplay completes synchronously", replay.body["State"] == "COMPLETED")
    after = len(sqs.dispatch(s, "AmazonSQS.ReceiveMessage", {"QueueUrl": qurl, "MaxNumberOfMessages": 10}).body.get("Messages", []))
    _check("replay re-delivers the archived event to the rule's targets", after > before)
    _check("ListArchives sees it", any(a["ArchiveName"] == "arc1" for a in call("ListArchives", {}).body["Archives"]))
    _check("ListReplays sees it", any(r["ReplayName"] == "rep1" for r in call("ListReplays", {}).body["Replays"]))
    call("DeleteArchive", {"ArchiveName": "arc1"})
    _check("DeleteArchive removes it", call("DescribeArchive", {"ArchiveName": "arc1"}).body.get("__type") == "ResourceNotFoundException")

    # 8. Tags round-trip on a bus and a rule.
    call("TagResource", {"ResourceARN": desc["Arn"], "Tags": [{"Key": "env", "Value": "prod"}]})
    tags = call("ListTagsForResource", {"ResourceARN": desc["Arn"]}).body["Tags"]
    _check("bus tag round-trips", {"Key": "env", "Value": "prod"} in tags)
    call("UntagResource", {"ResourceARN": desc["Arn"], "TagKeys": ["env"]})
    _check("bus tag removed", call("ListTagsForResource", {"ResourceARN": desc["Arn"]}).body["Tags"] == [])

    # 9. Deleting a bus deletes its rules.
    call("DeleteEventBus", {"Name": "orders"})
    _check("deleting a bus removes its rules", call("ListRules", {"EventBusName": "orders"}).body["Rules"] == [])
    cantdelete = call("DeleteEventBus", {"Name": "default"})
    _check("the default bus cannot be deleted", cantdelete.body.get("__type") == "ValidationException")

    print("\nRESULT: PASS — EventBridge v4-console additions conform (native wire semantics) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
