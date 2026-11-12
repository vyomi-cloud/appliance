"""AWS-13 StackSets service-managed permissions with AWS Organizations: trusted access, SERVICE_MANAGED stack sets, OU-targeted stack instances,
operations. Via AwsWireRouter. Run: PYTHONPATH=. python3 tests/conformance/test_cloudformation_stacksets_orgs.py
"""
import json
import re
import urllib.parse

from core.aws_wire_router import AwsWireRouter


def _auth(svc):
    return f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"


def org(r, op, body=None):
    h = {"authorization": _auth("organizations"), "x-amz-target": "AWSOrganizationsV20161128." + op, "content-type": "application/x-amz-json-1.1"}
    out = r.handle("POST", "/", {}, h, json.dumps(body or {}).encode())
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def cf(r, action, **p):
    body = urllib.parse.urlencode({"Action": action, "Version": "2010-05-15", **p}).encode()
    out = r.handle("POST", "/", {}, {"authorization": _auth("cloudformation"), "content-type": "application/x-www-form-urlencoded"}, body)
    return out["status"], out["body"].decode()


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


T = json.dumps({"Resources": {"B": {"Type": "AWS::S3::Bucket"}}})


def main():
    r = AwsWireRouter()
    st, x = cf(r, "ActivateOrganizationsAccess")
    _check("activate without an organization -> InvalidOperationException", st == 400 and "InvalidOperationException" in x)
    st, x = cf(r, "DescribeOrganizationsAccess")
    _check("access starts DISABLED", "<Status>DISABLED</Status>" in x)
    st, o = org(r, "CreateOrganization", {"FeatureSet": "ALL"})
    root = org(r, "ListRoots")[1]["Roots"][0]["Id"]
    st, o = org(r, "CreateOrganizationalUnit", {"ParentId": root, "Name": "Workloads"})
    ou = o["OrganizationalUnit"]["Id"]
    st, o = org(r, "CreateAccount", {"Email": "dev@example.com", "AccountName": "dev"})
    acct = o["CreateAccountStatus"]["AccountId"]
    org(r, "MoveAccount", {"AccountId": acct, "SourceParentId": root, "DestinationParentId": ou})

    st, x = cf(r, "CreateStackSet", StackSetName="svc", TemplateBody=T, PermissionModel="SERVICE_MANAGED", **{"AutoDeployment.Enabled": "true"})
    _check("SERVICE_MANAGED needs trusted access first", st == 400 and "Trusted access" in x)
    st, x = cf(r, "ActivateOrganizationsAccess")
    _check("ActivateOrganizationsAccess", st == 200)
    st, o = org(r, "ListAWSServiceAccessForOrganization")
    _check("trusted access is REAL service access in Organizations", any(e["ServicePrincipal"] == "member.org.stacksets.cloudformation.amazonaws.com" for e in o["EnabledServicePrincipals"]))
    st, x = cf(r, "DescribeOrganizationsAccess")
    _check("access ENABLED", "<Status>ENABLED</Status>" in x)
    st, x = cf(r, "CreateStackSet", StackSetName="svc", TemplateBody=T, PermissionModel="SERVICE_MANAGED")
    _check("AutoDeployment required for SERVICE_MANAGED", st == 400)
    st, x = cf(r, "CreateStackSet", StackSetName="svc", TemplateBody=T, PermissionModel="SERVICE_MANAGED", **{"AutoDeployment.Enabled": "true"})
    _check("CreateStackSet SERVICE_MANAGED", st == 200)
    st, x = cf(r, "DescribeStackSet", StackSetName="svc")
    _check("PermissionModel stored", "<PermissionModel>SERVICE_MANAGED</PermissionModel>" in x)

    st, x = cf(r, "CreateStackInstances", StackSetName="svc", **{"Regions.member.1": "us-east-1", "Regions.member.2": "eu-west-1", "Accounts.member.1": acct})
    _check("service-managed set rejects explicit Accounts", st == 400)
    st, x = cf(r, "CreateStackInstances", StackSetName="svc", **{"Regions.member.1": "us-east-1", "DeploymentTargets.OrganizationalUnitIds.member.1": "ou-bad-1234"})
    _check("unknown OU rejected", st == 400)
    st, x = cf(r, "CreateStackInstances", StackSetName="svc", **{"Regions.member.1": "us-east-1", "Regions.member.2": "eu-west-1", "DeploymentTargets.OrganizationalUnitIds.member.1": ou})
    _check("CreateStackInstances to an OU returns an OperationId", st == 200 and re.search(r"<OperationId>[0-9a-f-]{36}</OperationId>", x))
    op = re.search(r"<OperationId>(.*?)</OperationId>", x).group(1)
    st, x = cf(r, "ListStackInstances", StackSetName="svc")
    _check("OU resolved to its member account x 2 Regions", x.count("<member>") == 2 and acct in x and f"<OrganizationalUnitId>{ou}</OrganizationalUnitId>" in x)
    st, x = cf(r, "ListStackInstances", StackSetName="svc", StackInstanceRegion="eu-west-1")
    _check("filter by Region", x.count("<member>") == 1)
    st, x = cf(r, "DescribeStackInstance", StackSetName="svc", StackInstanceAccount=acct, StackInstanceRegion="us-east-1")
    _check("DescribeStackInstance has a stack id in the target account", f":{acct}:stack/StackSet-svc-" in x)
    st, x = cf(r, "DescribeStackSetOperation", StackSetName="svc", OperationId=op)
    _check("DescribeStackSetOperation", "<Status>SUCCEEDED</Status>" in x and "<Action>CREATE</Action>" in x)
    st, x = cf(r, "DeleteStackSet", StackSetName="svc")
    _check("StackSet with instances cannot be deleted", st == 400 and "StackSetNotEmptyException" in x)
    st, x = cf(r, "DeactivateOrganizationsAccess")
    _check("cannot deactivate while a SERVICE_MANAGED set exists", st == 400)
    st, x = cf(r, "DeleteStackInstances", StackSetName="svc", **{"Regions.member.1": "us-east-1", "Regions.member.2": "eu-west-1", "DeploymentTargets.OrganizationalUnitIds.member.1": ou}, RetainStacks="false")
    _check("DeleteStackInstances", st == 200)
    st, x = cf(r, "ListStackSetOperations", StackSetName="svc")
    _check("two operations recorded", x.count("<member>") == 2)
    st, x = cf(r, "DeleteStackSet", StackSetName="svc")
    _check("empty set deletes", st == 200)
    st, x = cf(r, "DeactivateOrganizationsAccess")
    _check("DeactivateOrganizationsAccess", st == 200)
    st, x = cf(r, "DescribeOrganizationsAccess")
    _check("access DISABLED again", "<Status>DISABLED</Status>" in x)

    # self-managed
    st, x = cf(r, "CreateStackSet", StackSetName="self", TemplateBody=T)
    st, x = cf(r, "CreateStackInstances", StackSetName="self", **{"Regions.member.1": "us-east-1", "Accounts.member.1": "12"})
    _check("SELF_MANAGED validates account id", st == 400)
    st, x = cf(r, "CreateStackInstances", StackSetName="self", **{"Regions.member.1": "us-east-1", "Accounts.member.1": "111122223333"})
    _check("SELF_MANAGED instance created", st == 200)
    print("PASS stacksets organizations")


if __name__ == "__main__":
    main()
