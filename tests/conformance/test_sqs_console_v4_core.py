"""SQS v4-console conformance — tags CRUD added for the console's Tagging tab, and
the real SNS -> SQS "Subscribe to Amazon SNS topic" console action (SNS Subscribe
with Protocol=sqs really fans a Publish out into the subscribed queue).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_sqs_console_v4_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
try:
    from core.messaging_store import InMemoryMessagingStore
    from core import sqs_core as sqs
    from core import sns_core as sns
except ImportError:  # pragma: no cover - Pyodide flat layout
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import sqs_core as sqs  # type: ignore
    import sns_core as sns  # type: ignore

SQS_T = "AmazonSQS."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    s = InMemoryMessagingStore()
    s.set_time(1000.0)

    def call(a, b):
        r = sqs.dispatch(s, SQS_T + a, b)
        if r.status != 200:
            raise AssertionError((a, r.body))
        return r.body

    # ── tags ────────────────────────────────────────────────────────────
    url = call("CreateQueue", {"QueueName": "console-q", "tags": {"env": "dev"}})["QueueUrl"]
    tags = call("ListQueueTags", {"QueueUrl": url})["Tags"]
    _check("tags set at CreateQueue are visible", tags == {"env": "dev"})
    call("TagQueue", {"QueueUrl": url, "Tags": {"team": "platform"}})
    tags = call("ListQueueTags", {"QueueUrl": url})["Tags"]
    _check("TagQueue adds without clobbering", tags == {"env": "dev", "team": "platform"})
    call("UntagQueue", {"QueueUrl": url, "TagKeys": ["env"]})
    tags = call("ListQueueTags", {"QueueUrl": url})["Tags"]
    _check("UntagQueue removes just that key", tags == {"team": "platform"})

    # ── redrive allow policy / redrive policy round-trip (generic attrs) ──
    call("SetQueueAttributes", {"QueueUrl": url, "Attributes": {
        "RedriveAllowPolicy": '{"redrivePermission":"allowAll"}'}})
    attrs = call("GetQueueAttributes", {"QueueUrl": url})["Attributes"]
    _check("RedriveAllowPolicy round-trips", attrs["RedriveAllowPolicy"] == '{"redrivePermission":"allowAll"}')
    _check("CreatedTimestamp is a real epoch", int(attrs["CreatedTimestamp"]) == 1000)

    # ── real SNS -> SQS fan-out via the console's "Subscribe to Amazon SNS
    #    topic" action (sns:Subscribe, Protocol=sqs, Endpoint=queue ARN) ────
    arn = attrs["QueueArn"]
    topic_arn = sns.dispatch(s, {"Action": "CreateTopic", "Name": "console-topic"}).body
    topic_arn = topic_arn.split("<TopicArn>")[1].split("</TopicArn>")[0]
    sub = sns.dispatch(s, {"Action": "Subscribe", "TopicArn": topic_arn, "Protocol": "sqs", "Endpoint": arn})
    _check("Subscribe (protocol=sqs) succeeds", sub.status == 200)
    pub = sns.dispatch(s, {"Action": "Publish", "TopicArn": topic_arn, "Message": "hello from sns"})
    _check("Publish succeeds", pub.status == 200)
    got = call("ReceiveMessage", {"QueueUrl": url, "MaxNumberOfMessages": 10})
    bodies = [m["Body"] for m in got.get("Messages", [])]
    _check("SNS Publish really fanned out into the subscribed SQS queue",
           any("hello from sns" in b for b in bodies))

    print("\nSQS v4-console conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
