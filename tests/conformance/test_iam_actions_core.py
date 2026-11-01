"""IAM Attach/Put/AccessKey/Simulate* on the shared core (== Nano): python3 tests/conformance/test_iam_actions_core.py"""
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.iam_store import InMemoryIamStore  # noqa: E402
from core import iam_core as iam  # noqa: E402

st = InMemoryIamStore()
fails = 0


def check(name, ok):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    fails += 0 if ok else 1


def call(**p):
    return iam.dispatch(st, p)


def vals(x, t):
    return re.findall(rf"<{t}>(.*?)</{t}>", x)


POL = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:Get*", "Resource": "*"}]})
DENY = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Action": "s3:DeleteBucket", "Resource": "*"}]})
call(Action="CreateUser", UserName="u")
arn = vals(call(Action="CreatePolicy", PolicyName="p", PolicyDocument=POL).body, "Arn")[0]
check("AttachUserPolicy + ListAttached", call(Action="AttachUserPolicy", UserName="u", PolicyArn=arn).status == 200
      and arn in vals(call(Action="ListAttachedUserPolicies", UserName="u").body, "PolicyArn"))
check("PutUserPolicy/ListUserPolicies/GetUserPolicy", call(Action="PutUserPolicy", UserName="u", PolicyName="i", PolicyDocument=DENY).status == 200
      and vals(call(Action="ListUserPolicies", UserName="u").body, "member") == ["i"] and "DeleteBucket" in call(Action="GetUserPolicy", UserName="u", PolicyName="i").body)
k = call(Action="CreateAccessKey", UserName="u").body
akid = vals(k, "AccessKeyId")[0]
check("CreateAccessKey + ListAccessKeys", akid.startswith("AKIA") and akid in vals(call(Action="ListAccessKeys", UserName="u").body, "AccessKeyId"))
r = call(**{"Action": "SimulatePrincipalPolicy", "PolicySourceArn": "arn:aws:iam::123456789012:user/u", "ActionNames.member.1": "s3:GetObject",
            "ActionNames.member.2": "s3:DeleteBucket", "ActionNames.member.3": "ec2:RunInstances"})
check("SimulatePrincipalPolicy: allowed / explicitDeny / implicitDeny",
      dict(zip(vals(r.body, "EvalActionName"), vals(r.body, "EvalDecision"))) == {"s3:GetObject": "allowed", "s3:DeleteBucket": "explicitDeny", "ec2:RunInstances": "implicitDeny"})
r = call(**{"Action": "SimulateCustomPolicy", "PolicyInputList.member.1": POL, "ActionNames.member.1": "s3:GetObject", "ActionNames.member.2": "s3:PutObject"})
check("SimulateCustomPolicy", dict(zip(vals(r.body, "EvalActionName"), vals(r.body, "EvalDecision"))) == {"s3:GetObject": "allowed", "s3:PutObject": "implicitDeny"})
check("unknown principal -> 404", call(**{"Action": "SimulatePrincipalPolicy", "PolicySourceArn": "arn:aws:iam::1:user/zz", "ActionNames.member.1": "a:b"}).status == 404)
check("DeleteAccessKey / DeleteUserPolicy", call(Action="DeleteAccessKey", UserName="u", AccessKeyId=akid).status == 200
      and call(Action="DeleteUserPolicy", UserName="u", PolicyName="i").status == 200 and not vals(call(Action="ListUserPolicies", UserName="u").body, "member"))
sys.exit(1 if fails else 0)
