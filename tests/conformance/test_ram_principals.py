"""RAM security-group sharing cross-checked against AWS Organizations (AWS-06): principal validation, org/OU existence, member vs
external accounts, allowExternalPrincipals=false. Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_ram_principals.py"""
import json
import re

from core.aws_wire_router import AwsWireRouter

A = lambda svc: f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


r = AwsWireRouter()


def j(svc, target, payload):
    o = r.handle("POST", "/", {}, {"authorization": A(svc), "x-amz-target": target, "content-type": "application/x-amz-json-1.1"}, json.dumps(payload).encode())
    return o["status"], (json.loads(o["body"]) if o["body"] else {})


def ram(op, payload):
    return j("ram", f"AWSRAMFrontendService.{op}", payload)


def org(op, payload=None):
    return j("organizations", f"AWSOrganizationsV20161128.{op}", payload or {})


def ec2(action, **params):
    body = "&".join([f"Action={action}", "Version=2016-11-15"] + [f"{k}={v}" for k, v in params.items()])
    return r.handle("POST", "/", {}, {"authorization": A("ec2"), "content-type": "application/x-www-form-urlencoded"}, body.encode())["body"].decode()


def main():
    vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", ec2("CreateVpc", CidrBlock="10.5.0.0/16")).group(1)
    sg = re.search(r"<groupId>(sg-\w+)</groupId>", ec2("CreateSecurityGroup", GroupName="shared", GroupDescription="d", VpcId=vpc)).group(1)
    arn = f"arn:aws:ec2:us-east-1:123456789012:security-group/{sg}"
    s, o = ram("CreateResourceShare", {"name": "sg-share", "resourceArns": [arn]})
    share = o["resourceShare"]["resourceShareArn"]
    assoc = lambda p: ram("AssociateResourceShare", {"resourceShareArn": share, "principals": [p]})
    _check("junk principal rejected", assoc("not-a-principal")[0] == 400 and assoc("1234")[0] == 400)
    _check("external account allowed by default", assoc("210987654321")[0] == 200
           and ram("ListPrincipals", {})[1]["principals"][0]["external"] is True)
    _check("org ARN rejected before an organization exists", assoc("arn:aws:organizations::123456789012:organization/o-abcdefghij")[0] == 400)

    s, o = org("CreateOrganization", {"FeatureSet": "ALL"})
    oid = o["Organization"]["Id"]
    root = org("ListRoots")[1]["Roots"][0]["Id"]
    s, o = org("CreateOrganizationalUnit", {"ParentId": root, "Name": "eng"})
    ou = o["OrganizationalUnit"]["Id"]
    s, o = org("CreateAccount", {"Email": "dev@example.com", "AccountName": "dev"})
    member = (org("ListAccounts")[1]["Accounts"] or [{}])[-1].get("Id")
    _check("organization exists", s == 200 and oid.startswith("o-"))
    _check("org ARN accepted", assoc(f"arn:aws:organizations::123456789012:organization/{oid}")[0] == 200)
    _check("other organization id rejected", assoc("arn:aws:organizations::123456789012:organization/o-zzzzzzzzzz")[0] == 400)
    _check("OU ARN accepted", assoc(f"arn:aws:organizations::123456789012:ou/{oid}/{ou}")[0] == 200)
    _check("unknown OU rejected", assoc(f"arn:aws:organizations::123456789012:ou/{oid}/ou-zzzz-zzzzzzzz")[0] == 400)
    ext = {p["id"]: p["external"] for p in ram("ListPrincipals", {})[1]["principals"]}
    _check("org/OU principals are internal", ext[f"arn:aws:organizations::123456789012:organization/{oid}"] is False)
    if member:
        _check("organization member account is internal", assoc(member)[0] == 200 and {p["id"]: p["external"] for p in ram("ListPrincipals", {})[1]["principals"]}[member] is False)

    s, o = ram("CreateResourceShare", {"name": "org-only", "allowExternalPrincipals": False, "resourceArns": [arn]})
    strict = o["resourceShare"]["resourceShareArn"]
    sa = lambda p: ram("AssociateResourceShare", {"resourceShareArn": strict, "principals": [p]})
    _check("allowExternalPrincipals=false refuses an outside account", sa("333333333333")[0] == 400)
    _check("allowExternalPrincipals=false accepts the org", sa(f"arn:aws:organizations::123456789012:organization/{oid}")[0] == 200)
    print("RAM principals vs Organizations: all green")


if __name__ == "__main__":
    main()
