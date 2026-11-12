"""SQS sweep A: real AWS/SQS CloudWatch metrics (sent/received/deleted counters + depth gauges).

Run: PYTHONPATH=. python3 tests/conformance/test_sqs_sweepa_core.py
"""
import json
import time

from core.aws_wire_router import AwsWireRouter

AUTH = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/%s/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def call(r, svc, target, payload, ver="1.0"):
    h = {"authorization": AUTH % svc, "x-amz-target": target, "content-type": f"application/x-amz-json-{ver}"}
    out = r.handle("POST", "/", {}, h, json.dumps(payload).encode())
    return json.loads(out["body"] or b"{}")


def stat(r, metric, q, stat="Sum"):
    d = call(r, "monitoring", "GraniteServiceVersion20100801.GetMetricStatistics", {
        "Namespace": "AWS/SQS", "MetricName": metric, "Dimensions": [{"Name": "QueueName", "Value": q}],
        "StartTime": time.time() - 3600, "EndTime": time.time() + 60, "Period": 3600, "Statistics": [stat]})["Datapoints"]
    return d[0][stat] if d else None


def run() -> int:
    r = AwsWireRouter()
    url = call(r, "sqs", "AmazonSQS.CreateQueue", {"QueueName": "metq"})["QueueUrl"]
    for i in range(3):
        call(r, "sqs", "AmazonSQS.SendMessage", {"QueueUrl": url, "MessageBody": "x" * 10})
    _check("NumberOfMessagesSent = 3", stat(r, "NumberOfMessagesSent", "metq") == 3)
    _check("SentMessageSize sums the payload bytes", stat(r, "SentMessageSize", "metq") == 30)
    _check("visible gauge = 3", stat(r, "ApproximateNumberOfMessagesVisible", "metq", "Maximum") == 3)
    got = call(r, "sqs", "AmazonSQS.ReceiveMessage", {"QueueUrl": url, "MaxNumberOfMessages": 2})["Messages"]
    _check("NumberOfMessagesReceived = 2", stat(r, "NumberOfMessagesReceived", "metq") == 2)
    _check("not-visible gauge follows the lease", stat(r, "ApproximateNumberOfMessagesNotVisible", "metq", "Maximum") == 2)
    call(r, "sqs", "AmazonSQS.DeleteMessage", {"QueueUrl": url, "ReceiptHandle": got[0]["ReceiptHandle"]})
    _check("NumberOfMessagesDeleted = 1", stat(r, "NumberOfMessagesDeleted", "metq") == 1)
    call(r, "sqs", "AmazonSQS.PurgeQueue", {"QueueUrl": url})
    empty = call(r, "sqs", "AmazonSQS.ReceiveMessage", {"QueueUrl": url})
    _check("empty receive counted", stat(r, "NumberOfEmptyReceives", "metq") == 1)
    _check("oldest-message age gauge published", stat(r, "ApproximateAgeOfOldestMessage", "metq", "Maximum") is not None)
    print("\nRESULT: PASS - SQS sweep A")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
