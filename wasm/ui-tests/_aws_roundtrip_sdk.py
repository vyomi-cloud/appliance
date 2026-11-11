"""SDK side for validate-aws-roundtrip.mjs: official boto3, endpoint only changed.
usage: _aws_roundtrip_sdk.py <svc> <create|describe|delete> <name> -> one JSON line"""
import json, os, sys
import boto3
from botocore.exceptions import ClientError

KW = dict(endpoint_url=os.environ["VYOMI_BASE_URL"].rstrip("/"), region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
svc, op, name = sys.argv[1:4]
c = boto3.client({"secretsmanager": "secretsmanager"}.get(svc, svc), **KW)


def s3():
    if op == "create": c.create_bucket(Bucket=name); return {}
    ex = name in [b["Name"] for b in c.list_buckets()["Buckets"]]
    if op == "describe": return {"exists": ex}
    if ex: c.delete_bucket(Bucket=name)
    return {"deleted": ex}


def sqs():
    if op == "create": return {"url": c.create_queue(QueueName=name)["QueueUrl"]}
    try: url = c.get_queue_url(QueueName=name)["QueueUrl"]
    except ClientError: return {"exists": False, "deleted": False}
    if op == "describe": return {"exists": True, "url": url}
    c.delete_queue(QueueUrl=url); return {"deleted": True}


def sns():
    if op == "create": return {"arn": c.create_topic(Name=name)["TopicArn"]}
    arn = next((t["TopicArn"] for t in c.list_topics()["Topics"] if t["TopicArn"].endswith(":" + name)), None)
    if op == "describe": return {"exists": bool(arn), "arn": arn}
    if arn: c.delete_topic(TopicArn=arn)
    return {"deleted": bool(arn)}


def dynamodb():
    if op == "create":
        c.create_table(TableName=name, KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST"); return {}
    ex = name in c.list_tables()["TableNames"]
    if op == "describe": return {"exists": ex}
    if ex: c.delete_table(TableName=name)
    return {"deleted": ex}


def kms():
    al = "alias/" + name
    if op == "create":
        k = c.create_key(Description=name)["KeyMetadata"]["KeyId"]; c.create_alias(AliasName=al, TargetKeyId=k); return {"key": k}
    tgt = next((a.get("TargetKeyId") for a in c.list_aliases()["Aliases"] if a["AliasName"] == al), None)
    # real KMS: deleting a key = ScheduleKeyDeletion; the key stays (PendingDeletion) so "gone" means state PendingDeletion
    live = bool(tgt) and c.describe_key(KeyId=tgt)["KeyMetadata"]["KeyState"] != "PendingDeletion"
    ex = bool(tgt)
    if op == "describe": return {"exists": live}
    if ex:
        k = next(a["TargetKeyId"] for a in c.list_aliases()["Aliases"] if a["AliasName"] == al)
        c.delete_alias(AliasName=al); c.schedule_key_deletion(KeyId=k, PendingWindowInDays=7)
    return {"deleted": ex}


def secretsmanager():
    if op == "create": return {"arn": c.create_secret(Name=name, SecretString="v")["ARN"]}
    ex = name in [s["Name"] for s in c.list_secrets()["SecretList"]]
    if op == "describe": return {"exists": ex}
    if ex: c.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
    return {"deleted": ex}


print(json.dumps(globals()[svc]()))
