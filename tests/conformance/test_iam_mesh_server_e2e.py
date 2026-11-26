"""Mesh end-to-end: the REAL appliance app (server.py middleware + IAM store + wire handlers) with the faithful-IAM gate.
A limited IAM user is created through the real IAM API; enforcement is switched per space through /api/iam; signed SQS calls go through
the real middleware. (Nano runs the same engine through wasm/nano-iam-hook.js: see wasm/ui-tests/iam/iam-hook-e2e.mjs.)"""
import json, os, re, sys, uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")
pytest.importorskip("fastapi")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    yield c
    c.put("/api/iam/aws/enforcement", json={"space": "off"})


def _sig(akid, svc):
    return f"AWS4-HMAC-SHA256 Credential={akid}/20261123/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=00"


def _call(c, akid, svc, form):
    return c.post("/", data=form, headers={"Authorization": _sig(akid, svc), "X-Amz-Date": "20261123T000000Z",
                                          "Content-Type": "application/x-www-form-urlencoded"})


def test_aws_enforcement_through_the_real_server(client):
    c = client
    uname = "ent-" + uuid.uuid4().hex[:8]      # the appliance persists its IAM store: stay re-runnable
    assert _call(c, "test", "iam", {"Action": "CreateUser", "UserName": uname, "Version": "2010-05-08"}).status_code == 200
    key = _call(c, "test", "iam", {"Action": "CreateAccessKey", "UserName": uname, "Version": "2010-05-08"})
    akid = re.search(r"<AccessKeyId>(.*?)</AccessKeyId>", key.text).group(1)
    pol = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["sqs:CreateQueue"], "Resource": "*"}]}
    _call(c, "test", "iam", {"Action": "PutUserPolicy", "UserName": uname, "PolicyName": "q", "PolicyDocument": json.dumps(pol), "Version": "2010-05-08"})
    lq = {"Action": "ListQueues", "Version": "2012-11-05"}

    assert _call(c, akid, "sqs", lq).status_code == 200                                    # off: nothing changes
    assert c.put("/api/iam/aws/enforcement", json={"space": "enforce"}).status_code == 200
    assert _call(c, akid, "sqs", {"Action": "CreateQueue", "QueueName": "q-" + uname, "Version": "2012-11-05"}).status_code == 200
    den = _call(c, akid, "sqs", lq)
    assert den.status_code == 403 and "AccessDenied" in den.text and uname in den.text and "sqs:ListQueues" in den.text
    assert _call(c, "test", "sqs", lq).status_code == 200                                  # unknown/default key = account root
    assert c.put("/api/iam/aws/enforcement", json={"space": "enforce", "unknownPrincipal": "deny"}).status_code == 200
    assert _call(c, "test", "sqs", lq).status_code == 403                                  # strict mode rejects unregistered keys
    assert c.put("/api/iam/aws/enforcement", json={"space": "audit"}).status_code == 200
    assert _call(c, akid, "sqs", lq).status_code == 200                                    # audit never blocks
    recs = c.get("/api/iam/aws/audit?limit=20").json()["records"]
    assert any(r["action"] == "sqs:ListQueues" and r["mode"] == "audit" and r["principal"].endswith("user/" + uname) for r in recs)
    assert c.put("/api/iam/aws/enforcement", json={"space": "enforce", "services": {"sqs": "off"}}).status_code == 200
    assert _call(c, akid, "sqs", lq).status_code == 200                                    # service-level off beats space enforce
    assert c.get("/_wire/api/iam/aws/enforcement").status_code == 200                      # the console's address works too
    c.put("/api/iam/aws/enforcement", json={"space": "off"})
    for a in ({"Action": "DeleteAccessKey", "UserName": uname, "AccessKeyId": akid}, {"Action": "DeleteUserPolicy", "UserName": uname, "PolicyName": "q"},
              {"Action": "DeleteUser", "UserName": uname}):
        _call(c, "test", "iam", dict(a, Version="2010-05-08"))


def test_aws_request_derived_condition_keys_reach_the_gate(client):
    """Conditions on keys the REQUEST carries (s3:prefix, aws:RequestedRegion) evaluate against the live request, not a missing context
    (found by the Mesh verification run: such policies denied everything)."""
    c = client
    uname = "ctx-" + uuid.uuid4().hex[:8]
    bucket = "ctxb-" + uuid.uuid4().hex[:8]
    assert _call(c, "test", "iam", {"Action": "CreateUser", "UserName": uname, "Version": "2010-05-08"}).status_code == 200
    akid = re.search(r"<AccessKeyId>(.*?)</AccessKeyId>", _call(c, "test", "iam", {"Action": "CreateAccessKey", "UserName": uname, "Version": "2010-05-08"}).text).group(1)
    pol = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": f"arn:aws:s3:::{bucket}", "Condition": {"StringLike": {"s3:prefix": "home/*"}}},
        {"Effect": "Allow", "Action": "sqs:ListQueues", "Resource": "*", "Condition": {"StringEquals": {"aws:RequestedRegion": "us-east-1"}}}]}
    _call(c, "test", "iam", {"Action": "PutUserPolicy", "UserName": uname, "PolicyName": "p", "PolicyDocument": json.dumps(pol), "Version": "2010-05-08"})
    assert c.put(f"/{bucket}", headers={"Authorization": _sig("test", "s3")}).status_code == 200
    try:
        assert c.put("/api/iam/aws/enforcement", json={"space": "enforce"}).status_code == 200
        hdr = {"Authorization": _sig(akid, "s3"), "X-Amz-Date": "20261123T000000Z"}
        assert c.get(f"/{bucket}?list-type=2&prefix=home/", headers=hdr).status_code == 200
        assert c.get(f"/{bucket}?list-type=2&prefix=other/", headers=hdr).status_code == 403
        assert c.get(f"/{bucket}?list-type=2", headers=hdr).status_code == 403
        assert _call(c, akid, "sqs", {"Action": "ListQueues", "Version": "2012-11-05"}).status_code == 200            # signed for us-east-1
        eu = _sig(akid, "sqs").replace("/us-east-1/", "/eu-west-1/")
        assert c.post("/", data={"Action": "ListQueues", "Version": "2012-11-05"}, headers={"Authorization": eu, "X-Amz-Date": "20261123T000000Z"}).status_code == 403
    finally:
        c.put("/api/iam/aws/enforcement", json={"space": "off"})
        c.delete(f"/{bucket}", headers={"Authorization": _sig("test", "s3")})
        for a in ({"Action": "DeleteAccessKey", "UserName": uname, "AccessKeyId": akid}, {"Action": "DeleteUserPolicy", "UserName": uname, "PolicyName": "p"},
                  {"Action": "DeleteUser", "UserName": uname}):
            _call(c, "test", "iam", dict(a, Version="2010-05-08"))
