"""AWS Organizations core — organization/root/OU/account/handshake/policy/service-access/
delegated-admin/tag lifecycles through AwsWireRouter (the Nano / unified-ingress entry), JSON 1.1
with X-Amz-Target AWSOrganizationsV20161128.*. Also checks the SCP chain evaluator.

Run: PYTHONPATH=. python3 tests/conformance/test_organizations_core.py
"""
import json

from core import organizations_core as oc
from core.aws_wire_router import AwsWireRouter

AUTH = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/organizations/aws4_request, SignedHeaders=host, Signature=0"
ALLOW_S3 = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]})
DENY_EC2 = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Action": "ec2:*", "Resource": "*"}]})


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def org(r, action, **p):
    out = r.handle("POST", "/", {}, {"authorization": AUTH, "x-amz-target": f"AWSOrganizationsV20161128.{action}",
                                      "content-type": "application/x-amz-json-1.1"}, json.dumps(p).encode())
    return out["status"], json.loads(out["body"] or b"{}")


def err(r, action, code, **p):
    s, b = org(r, action, **p)
    return s >= 400 and b.get("__type") == code


def run():
    r = AwsWireRouter()
    _check("no org -> AWSOrganizationsNotInUseException", err(r, "DescribeOrganization", "AWSOrganizationsNotInUseException"))
    s, b = org(r, "CreateOrganization", FeatureSet="ALL")
    o = b["Organization"]
    _check("CreateOrganization ALL", s == 200 and o["Id"].startswith("o-") and o["FeatureSet"] == "ALL")
    _check("duplicate org rejected", err(r, "CreateOrganization", "AlreadyInOrganizationException"))
    root = org(r, "ListRoots")[1]["Roots"][0]
    _check("root has SCP enabled", {"Type": "SERVICE_CONTROL_POLICY", "Status": "ENABLED"} in root["PolicyTypes"])
    mgmt = o["MasterAccountId"]
    _check("management account listed", [a["Id"] for a in org(r, "ListAccounts")[1]["Accounts"]] == [mgmt])
    s, b = org(r, "ListPoliciesForTarget", TargetId=root["Id"], Filter="SERVICE_CONTROL_POLICY")
    _check("FullAWSAccess attached to root", [p["Name"] for p in b["Policies"]] == ["FullAWSAccess"] and b["Policies"][0]["AwsManaged"])

    # OUs
    s, b = org(r, "CreateOrganizationalUnit", ParentId=root["Id"], Name="Prod", Tags=[{"Key": "env", "Value": "prod"}])
    prod = b["OrganizationalUnit"]
    _check("CreateOU", s == 200 and prod["Id"].startswith("ou-"))
    _check("duplicate OU", err(r, "CreateOrganizationalUnit", "DuplicateOrganizationalUnitException", ParentId=root["Id"], Name="Prod"))
    _check("bad parent", err(r, "CreateOrganizationalUnit", "ParentNotFoundException", ParentId="ou-nope", Name="X"))
    org(r, "UpdateOrganizationalUnit", OrganizationalUnitId=prod["Id"], Name="Production")
    _check("UpdateOU", org(r, "DescribeOrganizationalUnit", OrganizationalUnitId=prod["Id"])[1]["OrganizationalUnit"]["Name"] == "Production")
    sub = org(r, "CreateOrganizationalUnit", ParentId=prod["Id"], Name="Web")[1]["OrganizationalUnit"]
    _check("ListOUsForParent", [u["Name"] for u in org(r, "ListOrganizationalUnitsForParent", ParentId=root["Id"])[1]["OrganizationalUnits"]] == ["Production"])
    _check("ListParents(OU)", org(r, "ListParents", ChildId=sub["Id"])[1]["Parents"] == [{"Id": prod["Id"], "Type": "ORGANIZATIONAL_UNIT"}])
    _check("OU tags", org(r, "ListTagsForResource", ResourceId=prod["Id"])[1]["Tags"] == [{"Key": "env", "Value": "prod"}])

    # accounts
    s, b = org(r, "CreateAccount", Email="dev@example.com", AccountName="dev")
    st = b["CreateAccountStatus"]
    _check("CreateAccount SUCCEEDED immediately", s == 200 and st["State"] == "SUCCEEDED" and len(st["AccountId"]) == 12)
    dev = st["AccountId"]
    _check("DescribeCreateAccountStatus", org(r, "DescribeCreateAccountStatus", CreateAccountRequestId=st["Id"])[1]["CreateAccountStatus"]["AccountId"] == dev)
    _check("ListCreateAccountStatus", len(org(r, "ListCreateAccountStatus", States=["SUCCEEDED"])[1]["CreateAccountStatuses"]) == 1)
    s, b = org(r, "CreateAccount", Email="dev@example.com", AccountName="dup")
    _check("duplicate email -> FAILED EMAIL_ALREADY_EXISTS", b["CreateAccountStatus"]["State"] == "FAILED")
    a = org(r, "DescribeAccount", AccountId=dev)[1]["Account"]
    _check("account is under root", a["Name"] == "dev" and a["JoinedMethod"] == "CREATED" and a["Status"] == "ACTIVE")
    org(r, "MoveAccount", AccountId=dev, SourceParentId=root["Id"], DestinationParentId=sub["Id"])
    _check("ListAccountsForParent after move", [x["Id"] for x in org(r, "ListAccountsForParent", ParentId=sub["Id"])[1]["Accounts"]] == [dev])
    _check("ListChildren ACCOUNT", org(r, "ListChildren", ParentId=sub["Id"], ChildType="ACCOUNT")[1]["Children"] == [{"Id": dev, "Type": "ACCOUNT"}])
    _check("non-empty OU cannot be deleted", err(r, "DeleteOrganizationalUnit", "OrganizationalUnitNotEmptyException", OrganizationalUnitId=sub["Id"]))
    _check("mgmt cannot be removed", err(r, "RemoveAccountFromOrganization", "MasterCannotLeaveOrganizationException", AccountId=mgmt))

    # handshakes / invite
    s, b = org(r, "InviteAccountToOrganization", Target={"Id": "999988887777", "Type": "ACCOUNT"})
    h = b["Handshake"]
    _check("invite -> OPEN handshake", s == 200 and h["State"] == "OPEN" and h["Action"] == "INVITE")
    _check("duplicate pending invite", err(r, "InviteAccountToOrganization", "DuplicateHandshakeException", Target={"Id": "999988887777", "Type": "ACCOUNT"}))
    _check("invitee not yet a member", "999988887777" not in [x["Id"] for x in org(r, "ListAccounts")[1]["Accounts"]])
    org(r, "AcceptHandshake", HandshakeId=h["Id"])
    inv = org(r, "DescribeAccount", AccountId="999988887777")[1]["Account"]
    _check("accepted invite adds an INVITED account", inv["JoinedMethod"] == "INVITED")
    _check("accepted handshake cannot be declined", err(r, "DeclineHandshake", "InvalidHandshakeTransitionException", HandshakeId=h["Id"]))
    h2 = org(r, "InviteAccountToOrganization", Target={"Id": "x@example.com", "Type": "EMAIL"})[1]["Handshake"]
    org(r, "CancelHandshake", HandshakeId=h2["Id"])
    _check("CancelHandshake", org(r, "DescribeHandshake", HandshakeId=h2["Id"])[1]["Handshake"]["State"] == "CANCELED")
    org(r, "RemoveAccountFromOrganization", AccountId="999988887777")
    _check("RemoveAccountFromOrganization", not err(r, "DescribeAccount", "x", AccountId=dev) and err(r, "DescribeAccount", "AccountNotFoundException", AccountId="999988887777"))

    # policies
    s, b = org(r, "CreatePolicy", Name="allow-s3", Description="d", Type="SERVICE_CONTROL_POLICY", Content=ALLOW_S3, Tags=[{"Key": "k", "Value": "v"}])
    p1 = b["Policy"]["PolicySummary"]
    _check("CreatePolicy SCP", s == 200 and p1["Id"].startswith("p-") and not p1["AwsManaged"] and "/service_control_policy/" in p1["Arn"] and o["Id"] in p1["Arn"])
    p2 = org(r, "CreatePolicy", Name="deny-ec2", Description="", Type="SERVICE_CONTROL_POLICY", Content=DENY_EC2)[1]["Policy"]["PolicySummary"]
    _check("malformed content", err(r, "CreatePolicy", "MalformedPolicyDocumentException", Name="b", Description="", Type="SERVICE_CONTROL_POLICY", Content="not json"))
    _check("duplicate name", err(r, "CreatePolicy", "DuplicatePolicyException", Name="allow-s3", Description="", Type="SERVICE_CONTROL_POLICY", Content=ALLOW_S3))
    _check("ListPolicies SCP", {p["Name"] for p in org(r, "ListPolicies", Filter="SERVICE_CONTROL_POLICY")[1]["Policies"]} == {"FullAWSAccess", "allow-s3", "deny-ec2"})
    _check("policy tags", org(r, "ListTagsForResource", ResourceId=p1["Id"])[1]["Tags"] == [{"Key": "k", "Value": "v"}])
    tp = org(r, "CreatePolicy", Name="tags", Description="", Type="TAG_POLICY", Content='{"tags":{}}')[1]["Policy"]["PolicySummary"]
    _check("attach TAG_POLICY while disabled", err(r, "AttachPolicy", "PolicyTypeNotEnabledException", PolicyId=tp["Id"], TargetId=root["Id"]))
    org(r, "EnablePolicyType", RootId=root["Id"], PolicyType="TAG_POLICY")
    _check("EnablePolicyType twice", err(r, "EnablePolicyType", "PolicyTypeAlreadyEnabledException", RootId=root["Id"], PolicyType="TAG_POLICY"))
    org(r, "AttachPolicy", PolicyId=tp["Id"], TargetId=root["Id"])
    _check("duplicate attachment", err(r, "AttachPolicy", "DuplicatePolicyAttachmentException", PolicyId=tp["Id"], TargetId=root["Id"]))
    _check("policy in use cannot be deleted", err(r, "DeletePolicy", "PolicyInUseException", PolicyId=tp["Id"]))
    org(r, "AttachPolicy", PolicyId=p1["Id"], TargetId=prod["Id"])
    org(r, "AttachPolicy", PolicyId=p2["Id"], TargetId=sub["Id"])
    org(r, "AttachPolicy", PolicyId=oc.FULL_ACCESS_ID, TargetId=sub["Id"])
    tg = org(r, "ListTargetsForPolicy", PolicyId=p1["Id"])[1]["Targets"]
    _check("ListTargetsForPolicy", tg == [{"TargetId": prod["Id"], "Arn": prod["Arn"], "Name": "Production", "Type": "ORGANIZATIONAL_UNIT"}])
    _check("last SCP cannot be detached", err(r, "DetachPolicy", "ConstraintViolationException", PolicyId=p1["Id"], TargetId=prod["Id"]))
    org(r, "UpdatePolicy", PolicyId=p1["Id"], Description="changed")
    _check("UpdatePolicy", org(r, "DescribePolicy", PolicyId=p1["Id"])[1]["Policy"]["PolicySummary"]["Description"] == "changed")
    _check("AWS managed policy is read-only", err(r, "DeletePolicy", "InvalidInputException", PolicyId=oc.FULL_ACCESS_ID))

    # SCP chain evaluation: root(FullAWSAccess) -> Production(allow s3 only) -> Web(FullAWSAccess + deny ec2) -> dev
    st_ = r.iam
    d, _ = oc.effective_scp_decision(st_, dev, "s3:GetObject")
    _check("SCP chain: s3 allowed through every level", d == "allowed")
    d, why = oc.effective_scp_decision(st_, dev, "ec2:RunInstances")
    _check("SCP chain: ec2 denied (no allow in Production + explicit deny)", d != "allowed")
    d, _ = oc.effective_scp_decision(st_, dev, "dynamodb:GetItem")
    _check("SCP chain: dynamodb not in Production allow list", d != "allowed")
    d, _ = oc.effective_scp_decision(st_, mgmt, "ec2:RunInstances")
    _check("SCPs never restrict the management account", d == "allowed")

    # service access + delegated admins
    _check("delegation needs trusted access", err(r, "RegisterDelegatedAdministrator", "ConstraintViolationException", AccountId=dev, ServicePrincipal="iam.amazonaws.com"))
    org(r, "EnableAWSServiceAccess", ServicePrincipal="iam.amazonaws.com")
    _check("ListAWSServiceAccess", [x["ServicePrincipal"] for x in org(r, "ListAWSServiceAccessForOrganization")[1]["EnabledServicePrincipals"]] == ["iam.amazonaws.com"])
    org(r, "RegisterDelegatedAdministrator", AccountId=dev, ServicePrincipal="iam.amazonaws.com")
    da = org(r, "ListDelegatedAdministrators", ServicePrincipal="iam.amazonaws.com")[1]["DelegatedAdministrators"]
    _check("ListDelegatedAdministrators", [x["Id"] for x in da] == [dev])
    _check("ListDelegatedServicesForAccount", org(r, "ListDelegatedServicesForAccount", AccountId=dev)[1]["DelegatedServices"][0]["ServicePrincipal"] == "iam.amazonaws.com")
    _check("cannot disable trusted access while delegated", err(r, "DisableAWSServiceAccess", "ConstraintViolationException", ServicePrincipal="iam.amazonaws.com"))
    org(r, "DeregisterDelegatedAdministrator", AccountId=dev, ServicePrincipal="iam.amazonaws.com")
    _check("Deregister", org(r, "ListDelegatedAdministrators")[1]["DelegatedAdministrators"] == [])
    # IAM centralized root access features ride on the organization
    def iamq(action):
        from urllib.parse import urlencode
        out = r.handle("POST", "/", {}, {"authorization": AUTH.replace("organizations", "iam"), "content-type": "application/x-www-form-urlencoded"},
                       urlencode({"Action": action, "Version": "2010-05-08"}).encode())
        return out["status"], out["body"].decode()
    org(r, "DisableAWSServiceAccess", ServicePrincipal="iam.amazonaws.com")
    s_, b_ = iamq("EnableOrganizationsRootCredentialsManagement")
    _check("IAM features need trusted access", s_ == 409 and "ServiceAccessNotEnabledException" in b_)
    org(r, "EnableAWSServiceAccess", ServicePrincipal="iam.amazonaws.com")
    s_, b_ = iamq("EnableOrganizationsRootCredentialsManagement")
    _check("EnableOrganizationsRootCredentialsManagement", s_ == 200 and "<member>RootCredentialsManagement</member>" in b_)
    s_, b_ = iamq("EnableOrganizationsRootSessions")
    _check("EnableOrganizationsRootSessions", "<member>RootSessions</member>" in b_)
    s_, b_ = iamq("DisableOrganizationsRootCredentialsManagement")
    s_, b_ = iamq("ListOrganizationsFeatures")
    _check("ListOrganizationsFeatures reflects the disable", "RootSessions" in b_ and "RootCredentialsManagement" not in b_)
    org(r, "DisableAWSServiceAccess", ServicePrincipal="iam.amazonaws.com")

    # tags + cleanup
    org(r, "TagResource", ResourceId=dev, Tags=[{"Key": "team", "Value": "a"}])
    org(r, "UntagResource", ResourceId=dev, TagKeys=["team"])
    _check("Tag/Untag account", org(r, "ListTagsForResource", ResourceId=dev)[1]["Tags"] == [])
    org(r, "CloseAccount", AccountId=dev)
    _check("CloseAccount", org(r, "DescribeAccount", AccountId=dev)[1]["Account"]["Status"] == "SUSPENDED")
    _check("double close", err(r, "CloseAccount", "AccountAlreadyClosedException", AccountId=dev))
    _check("org not empty", err(r, "DeleteOrganization", "OrganizationNotEmptyException"))
    org(r, "RemoveAccountFromOrganization", AccountId=dev)
    _check("unknown action", org(r, "Bogus")[1]["__type"] == "UnknownOperationException")
    # sub OU now empty
    org(r, "DeleteOrganizationalUnit", OrganizationalUnitId=sub["Id"])
    org(r, "DeleteOrganizationalUnit", OrganizationalUnitId=prod["Id"])
    _check("OUs deleted", org(r, "ListOrganizationalUnitsForParent", ParentId=root["Id"])[1]["OrganizationalUnits"] == [])
    s, _b = org(r, "DeleteOrganization")
    _check("DeleteOrganization", s == 200 and err(r, "DescribeOrganization", "AWSOrganizationsNotInUseException"))
    print("organizations core: all checks passed")


if __name__ == "__main__":
    run()
