"""Create the S3 bucket, the two DynamoDB tables and the SQS queue, and load the handbook and the records. Safe to run again."""
import json

from botocore.exceptions import ClientError

from aws import ddb, s3, sqs
from data import ASSETS, BUCKET, DOCS, MEMORY, QUEUE, RECORDS


def put(item):
    out = {}
    for k, v in item.items():
        out[k] = {"N": str(v)} if isinstance(v, (int, float)) else {"S": str(v)}
    ddb.put_item(TableName=RECORDS, Item=out)


def make_table(name, keys):
    try:
        ddb.create_table(TableName=name, BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k, _ in keys],
                         KeySchema=[{"AttributeName": k, "KeyType": t} for k, t in keys])
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise


def seed():
    try:
        s3.create_bucket(Bucket=BUCKET)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise
    for name, text in DOCS.items():
        s3.put_object(Bucket=BUCKET, Key="docs/" + name, Body=text.encode())
    make_table(RECORDS, [("id", "HASH")])
    make_table(MEMORY, [("pk", "HASH"), ("sk", "RANGE")])
    url = sqs.create_queue(QueueName=QUEUE)["QueueUrl"]
    for a in ASSETS:
        put(a)
    return url


if __name__ == "__main__":
    print("queue:", seed())
    print("documents:", len(DOCS), "| records:", len(ASSETS))
