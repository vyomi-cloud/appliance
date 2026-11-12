"""Wire reachability fixes found by scripts/gen_nano_docs.py (the docs generator probes every operation):
  * STS AssumeRole / GetSessionToken / GetAccessKeyInfo answer (were InvalidAction)
  * RAM answers over rest-json (POST /createresourceshare …), the wire boto3 / aws-cli actually use
  * Cloud SQL Admin v1 at /v1/projects/{p}/instances (no /sql prefix) reaches the Cloud SQL core
"""
import json
import re

from core.aws_wire_router import AwsWireRouter

AUTH = "AWS4-HMAC-SHA256 Credential=test/20260101/us-east-1/%s/aws4_request, SignedHeaders=host, Signature=x"


def _call(r, method, path, headers=None, body=b"", query=None):
    return r.handle(method, path, query or {}, {"host": "x", **(headers or {})}, body)


def test_sts_assume_role_and_session_token():
    r = AwsWireRouter()
    h = {"authorization": AUTH % "sts", "content-type": "application/x-www-form-urlencoded"}
    out = _call(r, "POST", "/", h, b"Action=AssumeRole&Version=2011-06-15&RoleArn=arn:aws:iam::123456789012:role/demo&RoleSessionName=s1")
    assert out["status"] == 200
    b = out["body"].decode()
    assert "<AccessKeyId>ASIA" in b and ":assumed-role/demo/s1" in b
    out = _call(r, "POST", "/", h, b"Action=GetSessionToken&Version=2011-06-15")
    assert out["status"] == 200 and "<SessionToken>" in out["body"].decode()


def test_ram_rest_json_wire():
    r = AwsWireRouter()
    h = {"authorization": AUTH % "ram", "content-type": "application/json"}
    out = _call(r, "POST", "/createresourceshare", h, b'{"name":"share1"}')
    assert out["status"] == 200
    arn = json.loads(out["body"])["resourceShare"]["resourceShareArn"]
    out = _call(r, "POST", "/getresourceshares", h, b'{"resourceOwner":"SELF"}')
    assert out["status"] == 200 and len(json.loads(out["body"])["resourceShares"]) == 1
    out = _call(r, "DELETE", "/deleteresourceshare?resourceShareArn=" + arn, h, b"", query={"resourceShareArn": arn})
    assert out["status"] == 200


def test_cloudsql_v1_root_path_routes_to_core():
    r = AwsWireRouter()
    r.STRICT_GCP_PROJECT = False
    out = _call(r, "GET", "/v1/projects/vyomi-project/instances", {"content-type": "application/json"})
    assert out["status"] == 200 and not re.search(rb"NoSuchBucket", out["body"])
