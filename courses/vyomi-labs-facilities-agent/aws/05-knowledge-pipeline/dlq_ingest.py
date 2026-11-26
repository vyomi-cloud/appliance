import json
import time

import boto3

sqs = boto3.client("sqs")
dlq = sqs.create_queue(QueueName="ingest-events-dlq")["QueueUrl"]
dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
q = sqs.create_queue(QueueName="ingest-events", Attributes={
    "VisibilityTimeout": "1", "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "2"})})["QueueUrl"]


def process(body):
    """The consumer: a valid event names an S3 key under docs/; anything else is a poison message."""
    event = json.loads(body)
    if not str(event["key"]).startswith("docs/"):
        raise ValueError("refusing key outside docs/: %r" % event["key"])
    return event["key"]


sqs.send_message(QueueUrl=q, MessageBody=json.dumps({"key": "docs/boiler-sop.md"}))
sqs.send_message(QueueUrl=q, MessageBody=json.dumps({"key": "../../etc/passwd"}))
done, attempts = [], {}
for _ in range(14):
    for m in sqs.receive_message(QueueUrl=q, MaxNumberOfMessages=5, WaitTimeSeconds=1).get("Messages", []):
        attempts[m["Body"]] = attempts.get(m["Body"], 0) + 1
        try:
            done.append(process(m["Body"]))
            sqs.delete_message(QueueUrl=q, ReceiptHandle=m["ReceiptHandle"])
        except Exception as e:
            print("attempt", attempts[m["Body"]], "failed:", e)          # not deleted: it becomes visible again, up to the redrive limit
    time.sleep(1.2)

poison = json.dumps({"key": "../../etc/passwd"})
assert done == ["docs/boiler-sop.md"], "the good message must be processed exactly once, got %s" % done
assert attempts[poison] == 2, "the poison message must be retried exactly maxReceiveCount=2 times, was %d" % attempts[poison]
parked = sqs.receive_message(QueueUrl=dlq, WaitTimeSeconds=2).get("Messages", [])
assert parked and parked[0]["Body"] == poison, "the poison message must be waiting in the dead-letter queue with its body intact"
left = sqs.get_queue_attributes(QueueUrl=q, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"])["Attributes"]
assert left["ApproximateNumberOfMessages"] == "0" and left["ApproximateNumberOfMessagesNotVisible"] == "0", "the main queue must be drained: %s" % left
print("poison retried", attempts[poison], "times, then parked in the DLQ; main queue empty")
print("dead-letter handling verified")
