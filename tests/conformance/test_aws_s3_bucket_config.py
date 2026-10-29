"""S3 bucket configuration through the official boto3 SDK (endpoint changed only):
default encryption, public access block, bucket policy, CORS, lifecycle.

    VYOMI_BASE_URL=http://localhost:9000 python3 -m pytest tests/conformance/test_aws_s3_bucket_config.py -q
"""
import json
import os
import uuid

import boto3
import pytest
from botocore.exceptions import ClientError

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")


@pytest.fixture(scope="module")
def s3():
    return boto3.client("s3", endpoint_url=BASE, region_name="us-east-1",
                        aws_access_key_id="test", aws_secret_access_key="test")


@pytest.fixture()
def bucket(s3):
    name = "cfg-" + uuid.uuid4().hex[:10]
    s3.create_bucket(Bucket=name)
    yield name
    s3.delete_bucket(Bucket=name)


def code(exc):
    return exc.value.response["Error"]["Code"]


def test_default_encryption_is_sse_s3_and_round_trips(s3, bucket):
    rule = s3.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"][0]
    assert rule["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256"
    s3.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={"Rules": [{
        "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID": "alias/k"},
        "BucketKeyEnabled": True}]})
    rule = s3.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"][0]
    assert rule["ApplyServerSideEncryptionByDefault"]["KMSMasterKeyID"] == "alias/k"
    assert rule["BucketKeyEnabled"] is True
    s3.delete_bucket_encryption(Bucket=bucket)
    rule = s3.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"][0]
    assert rule["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256"


def test_public_access_block(s3, bucket):
    assert all(s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"].values())
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": False, "IgnorePublicAcls": True, "BlockPublicPolicy": False, "RestrictPublicBuckets": True})
    cfg = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
    assert cfg == {"BlockPublicAcls": False, "IgnorePublicAcls": True, "BlockPublicPolicy": False, "RestrictPublicBuckets": True}
    s3.delete_public_access_block(Bucket=bucket)
    with pytest.raises(ClientError) as e:
        s3.get_public_access_block(Bucket=bucket)
    assert code(e) == "NoSuchPublicAccessBlockConfiguration"


def test_bucket_policy(s3, bucket):
    with pytest.raises(ClientError) as e:
        s3.get_bucket_policy(Bucket=bucket)
    assert code(e) == "NoSuchBucketPolicy"
    doc = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*",
           "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/*"}]}
    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(doc))
    assert json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"]) == doc
    with pytest.raises(ClientError) as e:
        s3.put_bucket_policy(Bucket=bucket, Policy="{not json")
    assert code(e) == "MalformedPolicy"
    s3.delete_bucket_policy(Bucket=bucket)
    with pytest.raises(ClientError) as e:
        s3.get_bucket_policy(Bucket=bucket)
    assert code(e) == "NoSuchBucketPolicy"


def test_cors_and_lifecycle(s3, bucket):
    s3.put_bucket_cors(Bucket=bucket, CORSConfiguration={"CORSRules": [
        {"AllowedOrigins": ["https://a.example"], "AllowedMethods": ["GET", "PUT"], "MaxAgeSeconds": 60}]})
    rule = s3.get_bucket_cors(Bucket=bucket)["CORSRules"][0]
    assert rule["AllowedOrigins"] == ["https://a.example"] and rule["AllowedMethods"] == ["GET", "PUT"]
    s3.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration={"Rules": [
        {"ID": "r1", "Status": "Enabled", "Filter": {"Prefix": "logs/"}, "Expiration": {"Days": 30}}]})
    r = s3.get_bucket_lifecycle_configuration(Bucket=bucket)["Rules"][0]
    assert r["ID"] == "r1" and r["Expiration"]["Days"] == 30
    # the console JSON API reads the same record
    import requests
    j = requests.get(f"{BASE}/api/s3/buckets/{bucket}/config/lifecycle").json()
    assert j["rules"][0]["id"] == "r1" and j["rules"][0]["expiration_days"] == 30
    j = requests.get(f"{BASE}/api/s3/buckets/{bucket}/config/cors").json()
    assert j["rules"][0]["allowed_methods"] == ["GET", "PUT"]
