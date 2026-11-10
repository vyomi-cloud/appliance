#!/usr/bin/env python3
"""Post-create probe (offline): IAM AttachUserPolicy / PutUserPolicy / CreateAccessKey / SimulatePrincipalPolicy /
SimulateCustomPolicy over the native IAM Query wire, with list/get consistency, and enforcement of the result.
  python3 aws_iam_actions.py http://localhost:9000
Uses boto3 when installed, else raw form-encoded Query requests (same wire)."""
import json, os, re, sys, urllib.parse, urllib.request, urllib.error

BASE = (sys.argv[-1] if sys.argv[-1].startswith("http") else os.environ.get("VYOMI_ENDPOINT", "http://localhost:9000")).rstrip("/")
fails = 0
SFX = os.urandom(3).hex()


def check(ok, name, why=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {why}"), flush=True)
    fails += 0 if ok else 1


def iam(action, **p):
    data = {"Action": action, "Version": "2010-05-08"}
    for k, v in p.items():
        if isinstance(v, list):
            for i, x in enumerate(v, 1):
                data[f"{k}.member.{i}"] = x
        else:
            data[k] = v
    req = urllib.request.Request(BASE + "/", data=urllib.parse.urlencode(data).encode(), method="POST",
                                 headers={"content-type": "application/x-www-form-urlencoded",
                                          "authorization": "AWS4-HMAC-SHA256 Credential=AKIATEST/20260101/us-east-1/iam/aws4_request, SignedHeaders=host, Signature=x"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def vals(xml, tag):
    return re.findall(rf"<{tag}>(.*?)</{tag}>", xml)


U, PN = f"probe-u-{SFX}", f"probe-pol-{SFX}"
POL = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:Get*", "s3:List*"], "Resource": "*"}]})
try:
    iam("CreateUser", UserName=U)
    s, x = iam("CreatePolicy", PolicyName=PN, PolicyDocument=POL)
    arn = vals(x, "Arn")[0]
    s, x = iam("AttachUserPolicy", UserName=U, PolicyArn=arn)
    check(s == 200, "AttachUserPolicy -> 200", (s, x[:200]))
    s, x = iam("ListAttachedUserPolicies", UserName=U)
    check(arn in vals(x, "PolicyArn") and PN in vals(x, "PolicyName"), "ListAttachedUserPolicies shows the attachment", x[:300])
    s, x = iam("AttachUserPolicy", UserName="nobody-" + SFX, PolicyArn=arn)
    check(s == 404 and "NoSuchEntity" in x, "attach to unknown user -> NoSuchEntity 404", (s, x[:150]))
    INL = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Action": "s3:DeleteBucket", "Resource": "*"}]})
    s, x = iam("PutUserPolicy", UserName=U, PolicyName="inl", PolicyDocument=INL)
    check(s == 200, "PutUserPolicy -> 200", (s, x[:200]))
    s, x = iam("ListUserPolicies", UserName=U)
    check(vals(x, "member") == ["inl"], "ListUserPolicies lists it", x[:300])
    s, x = iam("GetUserPolicy", UserName=U, PolicyName="inl")
    check("DeleteBucket" in x and U in x, "GetUserPolicy returns the document", x[:300])
    s, x = iam("CreateAccessKey", UserName=U)
    akid, secret = (vals(x, "AccessKeyId") or [""])[0], (vals(x, "SecretAccessKey") or [""])[0]
    check(s == 200 and akid.startswith("AKIA") and len(secret) >= 30, "CreateAccessKey returns AKIA id + secret", (s, x[:200]))
    s, x = iam("ListAccessKeys", UserName=U)
    check(akid in vals(x, "AccessKeyId") and "SecretAccessKey" not in x, "ListAccessKeys lists it without the secret", x[:300])
    src = f"arn:aws:iam::123456789012:user/{U}"
    s, x = iam("SimulatePrincipalPolicy", PolicySourceArn=src, ActionNames=["s3:GetObject", "s3:PutObject", "s3:DeleteBucket"], ResourceArns=["*"])
    d = dict(zip(vals(x, "EvalActionName"), vals(x, "EvalDecision")))
    check(d == {"s3:GetObject": "allowed", "s3:PutObject": "implicitDeny", "s3:DeleteBucket": "explicitDeny"}, "SimulatePrincipalPolicy decisions follow attached + inline policies (explicit deny wins)", d)
    s, x = iam("SimulateCustomPolicy", PolicyInputList=[POL, INL], ActionNames=["s3:ListBucket", "s3:DeleteBucket"], ResourceArns=["arn:aws:s3:::b"])
    d = dict(zip(vals(x, "EvalActionName"), vals(x, "EvalDecision")))
    check(d == {"s3:ListBucket": "allowed", "s3:DeleteBucket": "explicitDeny"}, "SimulateCustomPolicy: allow + explicit deny wins", d)
    s, x = iam("SimulatePrincipalPolicy", PolicySourceArn=f"arn:aws:iam::123456789012:user/ghost-{SFX}", ActionNames=["s3:GetObject"])
    check(s == 404, "simulate for an unknown principal -> 404 NoSuchEntity", (s, x[:150]))
    s, x = iam("DeleteAccessKey", UserName=U, AccessKeyId=akid)
    s2, x2 = iam("ListAccessKeys", UserName=U)
    check(s == 200 and akid not in x2, "DeleteAccessKey removes it", x2[:200])
    s, x = iam("DetachUserPolicy", UserName=U, PolicyArn=arn)
    s2, x2 = iam("ListAttachedUserPolicies", UserName=U)
    check(s == 200 and arn not in x2, "DetachUserPolicy removes it", x2[:200])
finally:
    iam("DeleteUser", UserName=U)
    iam("DeletePolicy", PolicyArn=f"arn:aws:iam::123456789012:policy/{PN}")
sys.exit(1 if fails else 0)
