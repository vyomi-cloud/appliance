"""SNS filter-policy conformance (v2.6.0 operation depth) — host + Pyodide.

Asserts native SNS semantics: a subscription's FilterPolicy (set via
SetSubscriptionAttributes) filters Publish delivery per subscription — every
policy key must match (AND), a key matches if any listed condition holds (OR),
supporting exact-string + numeric conditions. Message attributes ride the
flattened Query wire (MessageAttributes.entry.N.*).
"""
import json
import re

try:
    from core.messaging_store import InMemoryMessagingStore
    from core import sqs_core as sqs, sns_core as sns
except ImportError:  # pragma: no cover - Pyodide flat layout
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import sqs_core as sqs  # type: ignore
    import sns_core as sns  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or InMemoryMessagingStore()

    def sns_call(params):
        return sns.dispatch(s, params)

    tarn = re.search(r"<TopicArn>(.*?)</TopicArn>",
                     sns_call({"Action": "CreateTopic", "Name": "events"}).body).group(1)
    qa = sqs.dispatch(s, "AmazonSQS.CreateQueue", {"QueueName": "qa"}).body["QueueUrl"]
    qb = sqs.dispatch(s, "AmazonSQS.CreateQueue", {"QueueName": "qb"}).body["QueueUrl"]
    a_arn = sqs.dispatch(s, "AmazonSQS.GetQueueAttributes", {"QueueUrl": qa}).body["Attributes"]["QueueArn"]
    b_arn = sqs.dispatch(s, "AmazonSQS.GetQueueAttributes", {"QueueUrl": qb}).body["Attributes"]["QueueArn"]
    sub_a = re.search(r"<SubscriptionArn>(.*?)</SubscriptionArn>",
                      sns_call({"Action": "Subscribe", "TopicArn": tarn, "Protocol": "sqs", "Endpoint": a_arn}).body).group(1)
    sns_call({"Action": "Subscribe", "TopicArn": tarn, "Protocol": "sqs", "Endpoint": b_arn})

    r = sns_call({"Action": "SetSubscriptionAttributes", "SubscriptionArn": sub_a,
                  "AttributeName": "FilterPolicy",
                  "AttributeValue": json.dumps({"color": ["red"], "size": [{"numeric": [">", 10]}]})})
    _check("set FilterPolicy 200", r.status == 200)
    _check("get FilterPolicy echoes it",
           "FilterPolicy" in sns_call({"Action": "GetSubscriptionAttributes", "SubscriptionArn": sub_a}).body)

    def publish(attrs):
        p = {"Action": "Publish", "TopicArn": tarn, "Message": "hi"}
        for i, (k, v) in enumerate(attrs.items(), 1):
            p[f"MessageAttributes.entry.{i}.Name"] = k
            p[f"MessageAttributes.entry.{i}.Value.DataType"] = "Number" if isinstance(v, (int, float)) else "String"
            p[f"MessageAttributes.entry.{i}.Value.StringValue"] = str(v)
        sns_call(p)

    def drain(url):
        r = sqs.dispatch(s, "AmazonSQS.ReceiveMessage", {"QueueUrl": url, "MaxNumberOfMessages": 10}).body
        for m in r.get("Messages", []):
            sqs.dispatch(s, "AmazonSQS.DeleteMessage", {"QueueUrl": url, "ReceiptHandle": m["ReceiptHandle"]})
        return len(r.get("Messages", []))

    publish({"color": "red", "size": 20})
    _check("match → A and B both delivered", drain(qa) == 1 and drain(qb) == 1)
    publish({"color": "blue", "size": 20})
    _check("color mismatch → A filtered, B delivered", drain(qa) == 0 and drain(qb) == 1)
    publish({"color": "red", "size": 5})
    _check("numeric fail → A filtered, B delivered", drain(qa) == 0 and drain(qb) == 1)

    print("\nSNS filter-policy conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
