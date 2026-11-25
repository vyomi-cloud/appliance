import json

import boto3

sns, sqs = boto3.client("sns"), boto3.client("sqs")
topic = sns.create_topic(Name="approver-inbox")["TopicArn"]        # returns the existing topic
qurl = sqs.get_queue_url(QueueName="approver-inbox-queue")["QueueUrl"]
sns.publish(TopicArn=topic, Subject="Channel test", Message=json.dumps({"request_id": "channel-test", "summary": "inbox smoke test"}))
seen = None
for _ in range(10):
    for m in sqs.receive_message(QueueUrl=qurl, MaxNumberOfMessages=10, WaitTimeSeconds=1).get("Messages", []):
        body = json.loads(m["Body"])
        msg = json.loads(body["Message"]) if "Message" in body else body
        sqs.delete_message(QueueUrl=qurl, ReceiptHandle=m["ReceiptHandle"])
        if msg.get("request_id") == "channel-test":
            seen = msg
    if seen:
        break
print("inbox delivered:", seen["summary"] if seen else "nothing received")
