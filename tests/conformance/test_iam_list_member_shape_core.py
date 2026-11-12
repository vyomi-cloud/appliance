"""IAM list responses use real AWS's `<member>` item wrapper, so official SDKs see the items.

Before: `<Users><User>..</User></Users>` -> boto3 / the Go SDK parsed ListUsers as EMPTY (the SDK reads `Users/member`).
Checks the wire XML directly (no network) AND, when boto3 is installed, parses it with the real botocore response parser.

Run: PYTHONPATH=. python3 tests/conformance/test_iam_list_member_shape_core.py
"""
import json
import re
from urllib.parse import urlencode

from core.aws_wire_router import AwsWireRouter

AUTH = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/iam/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def iam(r, action, **p):
    out = r.handle("POST", "/", {}, {"authorization": AUTH, "content-type": "application/x-www-form-urlencoded"},
                   urlencode({"Action": action, "Version": "2010-05-08", **p}).encode())
    return out["status"], out["body"].decode()


def items(body, wrapper):
    """The direct children tags of <wrapper> that hold list items."""
    m = re.search(rf"<{wrapper}>(.*?)</{wrapper}>", body, re.S)
    return re.findall(r"<(\w+)>", re.sub(r"<(\w+)>(?:(?!</\1>).)*</\1>", lambda x: "<" + x.group(1) + ">", m.group(1), flags=re.S)) if m else None


def run():
    r = AwsWireRouter()
    iam(r, "CreateUser", UserName="alice")
    iam(r, "CreateGroup", GroupName="devs")
    iam(r, "AddUserToGroup", GroupName="devs", UserName="alice")
    iam(r, "CreateRole", RoleName="r1", AssumeRolePolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": []}))
    iam(r, "CreatePolicy", PolicyName="p1", PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}))

    cases = [("ListUsers", {}, "Users"), ("ListRoles", {}, "Roles"), ("ListGroups", {}, "Groups"), ("ListPolicies", {"Scope": "Local"}, "Policies"),
             ("ListGroupsForUser", {"UserName": "alice"}, "Groups")]
    for action, p, wrap in cases:
        st, body = iam(r, action, **p)
        _check(f"{action} 200", st == 200)
        kids = items(body, wrap)
        _check(f"{action}: items are <member> (got {kids})", kids and set(kids) == {"member"})
        _check(f"{action}: IsTruncated present", "<IsTruncated>false</IsTruncated>" in body)
    st, body = iam(r, "GetGroup", GroupName="devs")
    _check("GetGroup: <Users> items are <member>", set(items(body, "Users") or []) == {"member"})
    _check("GetGroup: the Group itself stays a single <Group> element", "<Group>" in body)
    st, body = iam(r, "GetUser", UserName="alice")
    _check("GetUser (single resource) keeps <User>", "<User>" in body and "<member>" not in body)

    # the real SDK parser
    try:
        import boto3  # noqa: F401
        from botocore.model import ServiceModel
        from botocore.loaders import Loader
        from botocore.parsers import QueryParser
    except ImportError:
        print("  (boto3 not installed: SDK-parser check skipped)")
        print("IAM LIST MEMBER SHAPE OK")
        return
    sm = ServiceModel(Loader().load_service_model("iam", "service-2"))
    parse = lambda op, body: QueryParser().parse({"body": body.encode(), "headers": {}, "status_code": 200}, sm.operation_model(op).output_shape)  # noqa: E731
    _check("botocore parses ListUsers -> alice", [u["UserName"] for u in parse("ListUsers", iam(r, "ListUsers")[1])["Users"]] == ["alice"])
    _check("botocore parses ListRoles -> r1", [x["RoleName"] for x in parse("ListRoles", iam(r, "ListRoles")[1])["Roles"]] == ["r1"])
    _check("botocore parses ListGroups -> devs", [x["GroupName"] for x in parse("ListGroups", iam(r, "ListGroups")[1])["Groups"]] == ["devs"])
    _check("botocore parses ListPolicies(Local) -> p1", "p1" in [x["PolicyName"] for x in parse("ListPolicies", iam(r, "ListPolicies", Scope="Local")[1])["Policies"]])
    _check("botocore parses ListGroupsForUser -> devs", [x["GroupName"] for x in parse("ListGroupsForUser", iam(r, "ListGroupsForUser", UserName="alice")[1])["Groups"]] == ["devs"])
    _check("botocore parses GetGroup -> users [alice]", [u["UserName"] for u in parse("GetGroup", iam(r, "GetGroup", GroupName="devs")[1])["Users"]] == ["alice"])
    print("IAM LIST MEMBER SHAPE OK")


if __name__ == "__main__":
    run()
