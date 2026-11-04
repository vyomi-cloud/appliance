"""SNS per-topic maximum message size (Vyomi extension attribute VyomiMaximumMessageSize) + push-style TTL
(AWS.SNS.MOBILE.<PLATFORM>.TTL message attribute): enforced in the SNS core on publish and in both retry engines
(the offline delivery worker and the Nano synchronous simulation). SQS keeps enforcing the queue's own MaximumMessageSize.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_sns_size_ttl_core.py
"""
import asyncio
import json
import re

from core.messaging_store import InMemoryMessagingStore
from core import sqs_core as sqs, sns_core as sns, sns_delivery

SQS = "AmazonSQS."


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def _v(xml, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
    return m.group(1) if m else ""


def main():
    st = InMemoryMessagingStore()
    call = lambda a, **p: sns.dispatch(st, dict(p, Action=a))
    arn = _v(call("CreateTopic", Name="capped").body, "TopicArn")

    bad = call("SetTopicAttributes", TopicArn=arn, AttributeName="VyomiMaximumMessageSize", AttributeValue="0")
    _check("cap 0 rejected", bad.status == 400)
    bad = call("SetTopicAttributes", TopicArn=arn, AttributeName="VyomiMaximumMessageSize", AttributeValue="9999999")
    _check("cap above the platform limit rejected", bad.status == 400)
    _check("cap set", call("SetTopicAttributes", TopicArn=arn, AttributeName="VyomiMaximumMessageSize", AttributeValue="100").status == 200)
    _check("cap readable back", '"VyomiMaximumMessageSize"' in json.dumps(call("GetTopicAttributes", TopicArn=arn).body) or "VyomiMaximumMessageSize" in call("GetTopicAttributes", TopicArn=arn).body)
    r = call("Publish", TopicArn=arn, Message="x" * 101)
    _check("over the topic cap -> InvalidParameter", r.status == 400 and "Message too long" in r.body and "100 bytes" in r.body, r.body[:200])
    _check("at the cap accepted", call("Publish", TopicArn=arn, Message="x" * 100).status == 200)
    r = call("Publish", TopicArn=arn, Message="ab", **{"MessageAttributes.entry.1.Name": "pad", "MessageAttributes.entry.1.Value.DataType": "String",
                                                         "MessageAttributes.entry.1.Value.StringValue": "y" * 120})
    _check("attributes count towards the cap", r.status == 400)
    call("SetTopicAttributes", TopicArn=arn, AttributeName="VyomiMaximumMessageSize", AttributeValue="")
    _check("cap cleared", call("Publish", TopicArn=arn, Message="x" * 5000).status == 200)
    _check("platform limit still real", call("Publish", TopicArn=arn, Message="x" * 262145).status == 400)

    # TTL attribute validation
    ttl = lambda v, name="AWS.SNS.MOBILE.FCM.TTL": {"MessageAttributes.entry.1.Name": name, "MessageAttributes.entry.1.Value.DataType": "Number", "MessageAttributes.entry.1.Value.StringValue": v}
    _check("negative TTL rejected", call("Publish", TopicArn=arn, Message="m", **ttl("-5")).status == 400)
    _check("TTL above 28 days rejected", call("Publish", TopicArn=arn, Message="m", **ttl("2419201")).status == 400)
    _check("valid TTL accepted", call("Publish", TopicArn=arn, Message="m", **ttl("3600")).status == 200)

    # TTL vs the Nano synchronous retry simulation: 20 s delays, TTL 30 s -> one retry fits, the second does not
    call("Subscribe", TopicArn=arn, Protocol="https", Endpoint="https://example.invalid/hook")
    tok = next(d["token"] for d in st.sns["deliveries"] if d["kind"] == "SubscriptionConfirmation")
    sub = _v(call("ConfirmSubscription", TopicArn=arn, Token=tok).body, "SubscriptionArn")
    call("SetSubscriptionAttributes", SubscriptionArn=sub, AttributeName="DeliveryPolicy",
         AttributeValue=json.dumps({"healthyRetryPolicy": {"numRetries": 3, "minDelayTarget": 20, "maxDelayTarget": 20}}))
    before = len(st.sns["deliveries"])
    call("Publish", TopicArn=arn, Message="short-lived", **ttl("30"))
    fails = [d for d in st.sns["deliveries"][before:] if d["kind"] == "DeliveryFailure" and d["subscription_arn"] == sub]
    _check("TTL stops the retries (attempt 1, retry fits, attempt 2 expires)", len(fails) == 2 and "expired (TTL 30s)" in fails[-1]["error"], [f["error"] for f in fails])
    before = len(st.sns["deliveries"])
    call("Publish", TopicArn=arn, Message="no-ttl")
    fails = [d for d in st.sns["deliveries"][before:] if d["kind"] == "DeliveryFailure" and d["subscription_arn"] == sub]
    _check("without TTL all retries run", len(fails) == 4 and "gave up" in fails[-1]["error"])

    # TTL vs the offline delivery worker: an expired job is dropped without an attempt and redriven
    sqs.dispatch(st, SQS + "CreateQueue", {"QueueName": "dlq"})
    dlq_arn = st.get_queue("dlq")["queue_arn"]
    dlq_url = sqs.dispatch(st, SQS + "GetQueueUrl", {"QueueName": "dlq"}).body["QueueUrl"]
    call("SetSubscriptionAttributes", SubscriptionArn=sub, AttributeName="RedrivePolicy", AttributeValue=json.dumps({"deadLetterTargetArn": dlq_arn}))
    topic = st.get_topic(arn)
    subrec = topic["subscriptions"][sub]

    def deliver_sqs(endpoint_arn, body, attrs, group, dedup):
        q = st.get_queue_by_arn(endpoint_arn)
        if q is None:
            return False
        sqs.enqueue(st, q, body, attrs, message_group_id=group, message_dedup_id=dedup)
        return True
    delivery = sns_delivery.Delivery(st, base_url=lambda: "http://127.0.0.1", invoke_lambda=lambda *a: None, deliver_sqs=deliver_sqs)
    old = "2020-01-01T00:00:00Z"
    job = {"id": "j1", "topic_arn": arn, "subscription_arn": sub, "protocol": "https", "endpoint": "https://example.invalid/hook",
           "retry_policy": sns._retry_policy(topic, subrec), "signature_version": "1", "redrive_arn": sns._redrive_target(subrec), "enqueued": old,
           "kind": "Notification", "subject": "", "message": "stale", "message_id": "m-stale", "raw": True, "envelope": {}, "group": "", "attributes": {}, "ttl": 60}
    asyncio.run(delivery._process(job, 1, None, asyncio.Queue()))
    last = st.sns["deliveries"]
    _check("worker drops an expired job", any(d["kind"] == "DeliveryFailure" and "expired (TTL 60s)" in d.get("error", "") for d in last))
    dead = sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": dlq_url}).body.get("Messages", [])
    _check("expired job lands in the DLQ", len(dead) == 1 and "stale" in dead[0]["Body"])
    print("sns size/ttl: all ok")


if __name__ == "__main__":
    main()
