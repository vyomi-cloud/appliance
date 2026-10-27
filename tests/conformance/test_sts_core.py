"""STS core — native Query-protocol behaviour, on host CPython and (vendored) Pyodide."""
import base64
import re

from core import sts_core as sts
from core.aws_wire_router import AwsWireRouter

ROLE = "arn:aws:iam::123456789012:role/dev"


def _akid(body):
    return re.search(r"<AccessKeyId>(ASIA\w+)</AccessKeyId>", body).group(1)


def test_assume_role_then_caller_identity():
    st = sts.StsStore()
    r = sts.dispatch(st, {"Action": "AssumeRole", "RoleArn": ROLE, "RoleSessionName": "s1"})
    assert r.status == 200 and "<AssumedRoleUser>" in r.body
    hdr = {"Authorization": f"AWS4-HMAC-SHA256 Credential={_akid(r.body)}/20240101/us-east-1/sts/aws4_request"}
    who = sts.dispatch(st, {"Action": "GetCallerIdentity"}, hdr).body
    assert "arn:aws:sts::123456789012:assumed-role/dev/s1" in who


def test_validation_errors():
    st = sts.StsStore()
    bad = sts.dispatch(st, {"Action": "AssumeRole", "RoleArn": ROLE, "RoleSessionName": "x y"})
    assert bad.status == 400 and "<Code>ValidationError</Code>" in bad.body
    short = sts.dispatch(st, {"Action": "AssumeRole", "RoleArn": ROLE, "RoleSessionName": "ok", "DurationSeconds": "10"})
    assert "ValidationError" in short.body
    pol = sts.dispatch(st, {"Action": "AssumeRole", "RoleArn": ROLE, "RoleSessionName": "ok", "Policy": "{no"})
    assert "MalformedPolicyDocument" in pol.body
    assert "InvalidAction" in sts.dispatch(st, {"Action": "Nope"}).body


def test_federation_session_and_decode():
    st = sts.StsStore()
    assert "federated-user/bob" in sts.dispatch(st, {"Action": "GetFederationToken", "Name": "bob"}).body
    assert "<Credentials>" in sts.dispatch(st, {"Action": "GetSessionToken"}).body
    msg = base64.b64encode(b'{"a":1}').decode()
    assert "DecodedMessage" in sts.dispatch(st, {"Action": "DecodeAuthorizationMessage", "EncodedMessage": msg}).body


def test_console_session_lifecycle():
    st = sts.StsStore()
    out = sts.console_create(st, {"name": "console-session", "role_name": "my-role"})
    assert out["ok"] and out["status"] == "active" and out["role_name"] == "my-role"
    assert len(sts.list_sessions(st)) == 1
    assert sts.console_delete(st, out["access_key_id"])["ok"]
    assert sts.list_sessions(st) == []


def test_wire_router_routes_signed_and_unsigned_sts():
    r = AwsWireRouter()
    signed = {"authorization": "AWS4-HMAC-SHA256 Credential=AKID/20240101/us-east-1/sts/aws4_request"}
    body = b"Action=GetCallerIdentity&Version=2011-06-15"
    out = r.handle("POST", "/", {}, signed, body)
    assert out["status"] == 200 and b"GetCallerIdentityResponse" in out["body"]
    unsigned = r.handle("POST", "/", {}, {"content-type": "application/x-www-form-urlencoded"},
                        b"Action=GetSessionToken&Version=2011-06-15")
    assert unsigned["status"] == 200 and b"<Credentials>" in unsigned["body"]
