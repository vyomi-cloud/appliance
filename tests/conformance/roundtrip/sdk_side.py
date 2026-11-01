"""SDK side of the UI<->SDK round-trip suite: official boto3, endpoint changed only.

    python3 sdk_side.py <service> <op> <name>      -> one JSON line on stdout
service: sns | sqs      op: create | describe | delete
"""
import json
import os
import sys

import boto3
from botocore.exceptions import ClientError

EP = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
KW = dict(endpoint_url=EP, region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")


def sns(op, name):
    c = boto3.client("sns", **KW)
    if op == "create":
        return {"arn": c.create_topic(Name=name)["TopicArn"]}
    arn = next((t["TopicArn"] for t in c.list_topics()["Topics"] if t["TopicArn"].endswith(":" + name)), None)
    if op == "describe":
        if not arn:
            return {"exists": False}
        a = c.get_topic_attributes(TopicArn=arn)["Attributes"]
        return {"exists": True, "arn": arn, "fifo": a.get("FifoTopic") == "true"}
    if arn:
        c.delete_topic(TopicArn=arn)
    return {"deleted": bool(arn)}


def sqs(op, name):
    c = boto3.client("sqs", **KW)
    if op == "create":
        url = c.create_queue(QueueName=name)["QueueUrl"]
        return {"url": url, "arn": c.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]}
    try:
        url = c.get_queue_url(QueueName=name)["QueueUrl"]
    except ClientError:
        return {"exists": False} if op == "describe" else {"deleted": False}
    if op == "describe":
        a = c.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]
        return {"exists": True, "url": url, "arn": a["QueueArn"], "fifo": a.get("FifoQueue") == "true"}
    c.delete_queue(QueueUrl=url)
    return {"deleted": True}


if __name__ == "__main__":
    svc, op, name = sys.argv[1:4]
    print(json.dumps({"sns": sns, "sqs": sqs}[svc](op, name)))
