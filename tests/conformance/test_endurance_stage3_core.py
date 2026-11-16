"""vyomi-endurance stage 3 (messaging + events) regressions found by the Terraform estate. Host + Pyodide.

    PYTHONPATH=. python3 tests/conformance/test_endurance_stage3_core.py
"""
import json

from core.messaging_store import InMemoryMessagingStore
from core import eventbridge_core as eb

E = "AWSEvents."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  [PASS] {name}")


def run():
    s = InMemoryMessagingStore()
    eb.dispatch(s, E + "CreateEventBus", {"Name": "bus1"})
    d = eb.dispatch(s, E + "DescribeEventBus", {"Name": "bus1"}).body
    _check("F34 DescribeEventBus times are epoch numbers (Go SDK: 'expected Timestamp to be a JSON Number')",
           isinstance(d["CreationTime"], float) and isinstance(d["LastModifiedTime"], float))
    eb.dispatch(s, E + "PutRule", {"Name": "nightly", "ScheduleExpression": "rate(1 day)"})
    r = eb.dispatch(s, E + "DescribeRule", {"Name": "nightly"}).body
    _check("F35 a schedule-only rule has no EventPattern in DescribeRule", "EventPattern" not in r)
    lr = eb.dispatch(s, E + "ListRules", {}).body["Rules"]
    _check("F35 ...nor in ListRules", all("EventPattern" not in x for x in lr if x["Name"] == "nightly"))
    eb.dispatch(s, E + "PutRule", {"Name": "pat", "EventPattern": json.dumps({"source": ["x"]})})
    _check("F35 a pattern rule still reports its EventPattern",
           json.loads(eb.dispatch(s, E + "DescribeRule", {"Name": "pat"}).body["EventPattern"]) == {"source": ["x"]})
    from core import sqs_core as sqs
    q = sqs.dispatch(s, "AmazonSQS.CreateQueue", {"QueueName": "q1"}).body["QueueUrl"]
    sqs.dispatch(s, "AmazonSQS.SetQueueAttributes", {"QueueUrl": q, "Attributes": {"RedriveAllowPolicy": json.dumps({"redrivePermission": "allowAll"})}})
    sqs.dispatch(s, "AmazonSQS.SetQueueAttributes", {"QueueUrl": q, "Attributes": {"RedriveAllowPolicy": ""}})
    a = sqs.dispatch(s, "AmazonSQS.GetQueueAttributes", {"QueueUrl": q, "AttributeNames": ["All"]}).body.get("Attributes", {})
    _check("F36 an empty RedriveAllowPolicy removes the attribute (provider delete waits for it to disappear)", "RedriveAllowPolicy" not in a)
    print("Endurance stage-3 regressions: ALL GREEN")


if __name__ == "__main__":
    run()
