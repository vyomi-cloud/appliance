"""IAM core conformance — the acceptance gate for the WASM extraction.

This SAME test runs on two substrates and must be green on both:
  - host CPython (proxy for the Pro/Max appliance handler)
  - Pyodide / WASM (the Nano substrate)

It asserts the NATIVE AWS IAM wire semantics — the Query protocol (form-encoded
Action) with XML responses (<CreateUserResult><User>...), ARNs, attachments,
<ErrorResponse><Code>NoSuchEntity> — AND the REAL policy-evaluation decisions via
SimulatePrincipalPolicy (allow / explicit-deny-wins / implicit-deny, wildcard
action+resource matching, conditions, group-inherited policies). The evaluator is
the appliance's real Python IAM-JSON engine, not a stub; a cedar-wasm engine can
swap in behind the AuthzEngine seam. No network, no fastapi/boto3/cedarpy.

Run on host:    python3 tests/conformance/test_iam_core.py
Run in Pyodide: loaded by wasm/ harness (same file).
"""
import json

# Allow running both as a repo script (host) and from a flat FS (Pyodide).
try:
    from core.iam_store import InMemoryIamStore
    from core import iam_core as iam
except ImportError:  # pragma: no cover - Pyodide flat layout
    from iam_store import InMemoryIamStore  # type: ignore
    import iam_core as iam  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _policy(*statements):
    return json.dumps({"Version": "2012-10-17", "Statement": list(statements)})


def _decisions(xml):
    """Crude parse of SimulatePrincipalPolicy XML -> {action: decision}."""
    import re
    out = {}
    for m in re.finditer(r"<EvalActionName>(.*?)</EvalActionName>.*?<EvalDecision>(.*?)</EvalDecision>", xml, re.S):
        out[m.group(1)] = m.group(2)
    return out


def run() -> int:
    st = InMemoryIamStore()

    # 1. CreateUser -> XML with User + ARN
    r = iam.dispatch(st, {"Action": "CreateUser", "UserName": "alice"})
    _check("create user 200", r.status == 200)
    _check("create user result", "<CreateUserResult>" in r.body)
    _check("create user name", "<UserName>alice</UserName>" in r.body)
    _check("create user arn", "<Arn>arn:aws:iam::123456789012:user/alice</Arn>" in r.body)
    _check("create user id AIDA", "<UserId>AIDA" in r.body)

    # 2. Duplicate -> EntityAlreadyExists
    dup = iam.dispatch(st, {"Action": "CreateUser", "UserName": "alice"})
    _check("duplicate EntityAlreadyExists", "<Code>EntityAlreadyExists</Code>" in dup.body and dup.status == 409)

    # 3. GetUser / ListUsers / NoSuchEntity
    _check("get user", "<UserName>alice</UserName>" in iam.dispatch(st, {"Action": "GetUser", "UserName": "alice"}).body)
    iam.dispatch(st, {"Action": "CreateUser", "UserName": "bob"})
    lu = iam.dispatch(st, {"Action": "ListUsers"}).body
    _check("list users has both", "<UserName>alice</UserName>" in lu and "<UserName>bob</UserName>" in lu)
    nf = iam.dispatch(st, {"Action": "GetUser", "UserName": "ghost"})
    _check("missing user NoSuchEntity 404", "<Code>NoSuchEntity</Code>" in nf.body and nf.status == 404)

    # 4. CreatePolicy (managed) with a JSON PolicyDocument
    s3ro = _policy({"Effect": "Allow", "Action": "s3:Get*", "Resource": "arn:aws:s3:::data/*"})
    cp = iam.dispatch(st, {"Action": "CreatePolicy", "PolicyName": "S3ReadOnly", "PolicyDocument": s3ro})
    _check("create policy arn", "<Arn>arn:aws:iam::123456789012:policy/S3ReadOnly</Arn>" in cp.body)
    policy_arn = "arn:aws:iam::123456789012:policy/S3ReadOnly"

    # 5. AttachUserPolicy + ListAttachedUserPolicies
    iam.dispatch(st, {"Action": "AttachUserPolicy", "UserName": "alice", "PolicyArn": policy_arn})
    la = iam.dispatch(st, {"Action": "ListAttachedUserPolicies", "UserName": "alice"}).body
    _check("attached policy listed", "<PolicyName>S3ReadOnly</PolicyName>" in la)

    # 6. SimulatePrincipalPolicy — the DECISION path
    sim = iam.dispatch(st, {"Action": "SimulatePrincipalPolicy", "PolicySourceArn": "alice",
                            "ActionNames.member.1": "s3:GetObject",
                            "ActionNames.member.2": "s3:DeleteObject",
                            "ResourceArns.member.1": "arn:aws:s3:::data/report.csv"})
    dec = _decisions(sim.body)
    _check("allow: s3:GetObject matches s3:Get* on data/*", dec.get("s3:GetObject") == "allowed")
    _check("implicit deny: s3:DeleteObject not granted", dec.get("s3:DeleteObject") == "implicitDeny")

    # 6b. Resource scoping: same action, out-of-scope resource -> implicit deny
    sim2 = iam.dispatch(st, {"Action": "SimulatePrincipalPolicy", "PolicySourceArn": "alice",
                             "ActionNames.member.1": "s3:GetObject",
                             "ResourceArns.member.1": "arn:aws:s3:::other/secret"})
    _check("resource scoping denies out-of-scope", _decisions(sim2.body).get("s3:GetObject") == "implicitDeny")

    # 7. Explicit deny wins over allow (and regardless of statement order)
    iam.dispatch(st, {"Action": "CreatePolicy", "PolicyName": "DenyDelete",
                      "PolicyDocument": _policy({"Effect": "Deny", "Action": "s3:Delete*", "Resource": "*"})})
    iam.dispatch(st, {"Action": "CreatePolicy", "PolicyName": "AllowAllS3",
                      "PolicyDocument": _policy({"Effect": "Allow", "Action": "s3:*", "Resource": "*"})})
    iam.dispatch(st, {"Action": "AttachUserPolicy", "UserName": "bob",
                      "PolicyArn": "arn:aws:iam::123456789012:policy/AllowAllS3"})
    iam.dispatch(st, {"Action": "AttachUserPolicy", "UserName": "bob",
                      "PolicyArn": "arn:aws:iam::123456789012:policy/DenyDelete"})
    simb = iam.dispatch(st, {"Action": "SimulatePrincipalPolicy", "PolicySourceArn": "bob",
                             "ActionNames.member.1": "s3:GetObject",
                             "ActionNames.member.2": "s3:DeleteObject",
                             "ResourceArns.member.1": "arn:aws:s3:::any/key"})
    decb = _decisions(simb.body)
    _check("allow-all grants GetObject", decb.get("s3:GetObject") == "allowed")
    _check("explicit deny wins for DeleteObject", decb.get("s3:DeleteObject") == "explicitDeny")

    # 8. Group-inherited policies: user in a group with a policy gets that grant
    iam.dispatch(st, {"Action": "CreateUser", "UserName": "carol"})
    iam.dispatch(st, {"Action": "CreateGroup", "GroupName": "Admins"})
    iam.dispatch(st, {"Action": "CreatePolicy", "PolicyName": "EC2Full",
                      "PolicyDocument": _policy({"Effect": "Allow", "Action": "ec2:*", "Resource": "*"})})
    iam.dispatch(st, {"Action": "AttachGroupPolicy", "GroupName": "Admins",
                      "PolicyArn": "arn:aws:iam::123456789012:policy/EC2Full"})
    iam.dispatch(st, {"Action": "AddUserToGroup", "GroupName": "Admins", "UserName": "carol"})
    simc = iam.dispatch(st, {"Action": "SimulatePrincipalPolicy", "PolicySourceArn": "carol",
                             "ActionNames.member.1": "ec2:RunInstances",
                             "ResourceArns.member.1": "*"})
    _check("group-inherited policy grants access", _decisions(simc.body).get("ec2:RunInstances") == "allowed")

    # 9. is_authorized() convenience probe agrees with the simulation
    probe = iam.is_authorized(st, "carol", "ec2:RunInstances", "*")
    _check("is_authorized allowed", probe["allowed"] is True and probe["decision"] == "allowed")
    probe2 = iam.is_authorized(st, "alice", "s3:DeleteObject", "arn:aws:s3:::data/x")
    _check("is_authorized implicit deny", probe2["allowed"] is False and probe2["decision"] == "implicitDeny")

    # 10. Inline user policy (PutUserPolicy/GetUserPolicy) is evaluated too
    iam.dispatch(st, {"Action": "PutUserPolicy", "UserName": "alice", "PolicyName": "inline-sqs",
                      "PolicyDocument": _policy({"Effect": "Allow", "Action": "sqs:SendMessage", "Resource": "*"})})
    gp = iam.dispatch(st, {"Action": "GetUserPolicy", "UserName": "alice", "PolicyName": "inline-sqs"}).body
    _check("get inline policy", "<PolicyName>inline-sqs</PolicyName>" in gp)
    _check("inline policy is enforced",
           iam.is_authorized(st, "alice", "sqs:SendMessage", "*")["allowed"] is True)

    # 11. Roles: create + attach + evaluate; trust policy round-trips
    iam.dispatch(st, {"Action": "CreateRole", "RoleName": "AppRole",
                      "AssumeRolePolicyDocument": json.dumps({"Version": "2012-10-17",
                          "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"},
                                         "Action": "sts:AssumeRole"}]})})
    gr = iam.dispatch(st, {"Action": "GetRole", "RoleName": "AppRole"}).body
    _check("role created with trust policy", "<RoleName>AppRole</RoleName>" in gr and "AssumeRolePolicyDocument" in gr)
    iam.dispatch(st, {"Action": "AttachRolePolicy", "RoleName": "AppRole", "PolicyArn": policy_arn})
    _check("role policy enforced",
           iam.is_authorized(st, "AppRole", "s3:GetObject", "arn:aws:s3:::data/x")["allowed"] is True)

    # 12. Access keys
    ak = iam.dispatch(st, {"Action": "CreateAccessKey", "UserName": "alice"}).body
    _check("access key created", "<AccessKeyId>AKIA" in ak and "<SecretAccessKey>" in ak)
    lk = iam.dispatch(st, {"Action": "ListAccessKeys", "UserName": "alice"}).body
    _check("access key listed", "<AccessKeyId>AKIA" in lk)

    # 13. Detach removes the grant
    iam.dispatch(st, {"Action": "DetachUserPolicy", "UserName": "alice", "PolicyArn": policy_arn})
    _check("detach revokes access",
           iam.is_authorized(st, "alice", "s3:GetObject", "arn:aws:s3:::data/x")["allowed"] is False)

    # 14. Unknown / missing action
    _check("unknown action InvalidAction", "<Code>InvalidAction</Code>" in iam.dispatch(st, {"Action": "Nope"}).body)
    _check("missing action MissingAction", "<Code>MissingAction</Code>" in iam.dispatch(st, {}).body)

    # 15. Groups: list/get/membership/inline + attached policies, remove, delete
    iam.dispatch(st, {"Action": "AddUserToGroup", "GroupName": "Admins", "UserName": "alice"})
    gg = iam.dispatch(st, {"Action": "GetGroup", "GroupName": "Admins"}).body
    _check("get group shows member", "<UserName>alice</UserName>" in gg)
    lgfu = iam.dispatch(st, {"Action": "ListGroupsForUser", "UserName": "alice"}).body
    _check("list groups for user", "<GroupName>Admins</GroupName>" in lgfu)
    iam.dispatch(st, {"Action": "PutGroupPolicy", "GroupName": "Admins", "PolicyName": "inline-ec2",
                      "PolicyDocument": _policy({"Effect": "Allow", "Action": "ec2:Describe*", "Resource": "*"})})
    _check("group inline policy enforced",
           iam.is_authorized(st, "alice", "ec2:DescribeInstances", "*")["allowed"] is True)
    iam.dispatch(st, {"Action": "RemoveUserFromGroup", "GroupName": "Admins", "UserName": "alice"})
    _check("group inline policy revoked on removal",
           iam.is_authorized(st, "alice", "ec2:DescribeInstances", "*")["allowed"] is False)
    lag = iam.dispatch(st, {"Action": "ListAttachedGroupPolicies", "GroupName": "Admins"}).body
    _check("attached group policy listed", "<PolicyName>EC2Full</PolicyName>" in lag)
    iam.dispatch(st, {"Action": "DetachGroupPolicy", "GroupName": "Admins", "PolicyArn":
                      "arn:aws:iam::123456789012:policy/EC2Full"})
    iam.dispatch(st, {"Action": "DeleteGroupPolicy", "GroupName": "Admins", "PolicyName": "inline-ec2"})
    iam.dispatch(st, {"Action": "RemoveUserFromGroup", "GroupName": "Admins", "UserName": "carol"})
    del_g = iam.dispatch(st, {"Action": "DeleteGroup", "GroupName": "Admins"})
    _check("delete empty group ok", del_g.status == 200)
    lg = iam.dispatch(st, {"Action": "ListGroups"}).body
    _check("deleted group gone", "<GroupName>Admins</GroupName>" not in lg)

    # 16. Access keys: deactivate + delete
    ak2 = iam.dispatch(st, {"Action": "CreateAccessKey", "UserName": "bob"}).body
    akid2 = ak2.split("<AccessKeyId>")[1].split("<")[0]
    iam.dispatch(st, {"Action": "UpdateAccessKey", "UserName": "bob", "AccessKeyId": akid2, "Status": "Inactive"})
    lk2 = iam.dispatch(st, {"Action": "ListAccessKeys", "UserName": "bob"}).body
    _check("access key deactivated", f"<AccessKeyId>{akid2}</AccessKeyId><Status>Inactive</Status>" in lk2)
    iam.dispatch(st, {"Action": "DeleteAccessKey", "UserName": "bob", "AccessKeyId": akid2})
    _check("access key deleted", akid2 not in iam.dispatch(st, {"Action": "ListAccessKeys", "UserName": "bob"}).body)

    # 17. Login profile (console password) — limited: stored, never actually authenticates
    iam.dispatch(st, {"Action": "CreateLoginProfile", "UserName": "alice", "PasswordResetRequired": "true"})
    glp = iam.dispatch(st, {"Action": "GetLoginProfile", "UserName": "alice"}).body
    _check("login profile created", "<PasswordResetRequired>true</PasswordResetRequired>" in glp)
    iam.dispatch(st, {"Action": "DeleteLoginProfile", "UserName": "alice"})
    _check("login profile deleted", "<Code>NoSuchEntity</Code>" in iam.dispatch(st, {"Action": "GetLoginProfile", "UserName": "alice"}).body)

    # 18. Tags on users and roles
    iam.dispatch(st, {"Action": "TagUser", "UserName": "alice", "Tags.member.1.Key": "team", "Tags.member.1.Value": "sec"})
    _check("user tag listed", "<Key>team</Key><Value>sec</Value>" in iam.dispatch(st, {"Action": "ListUserTags", "UserName": "alice"}).body)
    iam.dispatch(st, {"Action": "UntagUser", "UserName": "alice", "TagKeys.member.1": "team"})
    _check("user tag removed", "<Key>team</Key>" not in iam.dispatch(st, {"Action": "ListUserTags", "UserName": "alice"}).body)
    iam.dispatch(st, {"Action": "TagRole", "RoleName": "AppRole", "Tags.member.1.Key": "env", "Tags.member.1.Value": "prod"})
    _check("role tag listed", "<Key>env</Key><Value>prod</Value>" in iam.dispatch(st, {"Action": "ListRoleTags", "RoleName": "AppRole"}).body)

    # 19. Role trust policy edit + max session duration + inline role policy
    iam.dispatch(st, {"Action": "UpdateAssumeRolePolicy", "RoleName": "AppRole",
                      "PolicyDocument": json.dumps({"Version": "2012-10-17",
                          "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
                                         "Action": "sts:AssumeRole"}]})})
    iam.dispatch(st, {"Action": "UpdateRole", "RoleName": "AppRole", "MaxSessionDuration": "7200"})
    gr2 = iam.dispatch(st, {"Action": "GetRole", "RoleName": "AppRole"}).body
    _check("trust policy updated", "lambda.amazonaws.com" in gr2)
    _check("max session duration updated", "<MaxSessionDuration>7200</MaxSessionDuration>" in gr2)
    iam.dispatch(st, {"Action": "PutRolePolicy", "RoleName": "AppRole", "PolicyName": "inline-logs",
                      "PolicyDocument": _policy({"Effect": "Allow", "Action": "logs:*", "Resource": "*"})})
    _check("role inline policy enforced", iam.is_authorized(st, "AppRole", "logs:PutLogEvents", "*")["allowed"] is True)
    iam.dispatch(st, {"Action": "DeleteRolePolicy", "RoleName": "AppRole", "PolicyName": "inline-logs"})
    iam.dispatch(st, {"Action": "ListAttachedRolePolicies", "RoleName": "AppRole"})
    iam.dispatch(st, {"Action": "DetachRolePolicy", "RoleName": "AppRole", "PolicyArn": policy_arn})

    # 20. Permissions boundaries — stored, reflected in ListEntitiesForPolicy, AND enforced by
    # SimulatePrincipalPolicy / is_authorized: the boundary (S3ReadOnly: s3:Get* on data/*)
    # clips bob's identity grant (AllowAllS3, minus DenyDelete) down to its intersection.
    iam.dispatch(st, {"Action": "PutUserPermissionsBoundary", "UserName": "bob", "PermissionsBoundary": policy_arn})
    lep = iam.dispatch(st, {"Action": "ListEntitiesForPolicy", "PolicyArn": policy_arn}).body
    _check("boundary user listed", "<PolicyBoundaryUsers><member><UserName>bob</UserName></member>" in lep)
    simc = iam.dispatch(st, {"Action": "SimulatePrincipalPolicy", "PolicySourceArn": "bob",
                             "ActionNames.member.1": "s3:GetObject", "ActionNames.member.2": "s3:PutObject",
                             "ActionNames.member.3": "s3:DeleteObject",
                             "ResourceArns.member.1": "arn:aws:s3:::data/report.csv"})
    decc = _decisions(simc.body)
    _check("boundary: in-scope action stays allowed (identity allow ∩ boundary allow)", decc.get("s3:GetObject") == "allowed")
    _check("boundary: out-of-boundary action clipped to implicit deny", decc.get("s3:PutObject") == "implicitDeny")
    _check("boundary: identity's explicit deny still wins regardless of the boundary", decc.get("s3:DeleteObject") == "explicitDeny")
    _check("boundary enforced by is_authorized too",
           iam.is_authorized(st, "bob", "s3:PutObject", "arn:aws:s3:::data/report.csv")["allowed"] is False)
    iam.dispatch(st, {"Action": "DeleteUserPermissionsBoundary", "UserName": "bob"})
    _check("boundary removed restores the unclipped grant",
           _decisions(iam.dispatch(st, {"Action": "SimulatePrincipalPolicy", "PolicySourceArn": "bob",
                                        "ActionNames.member.1": "s3:PutObject",
                                        "ResourceArns.member.1": "arn:aws:s3:::data/report.csv"}).body).get("s3:PutObject") == "allowed")

    # 21. Managed policy versions
    v2 = iam.dispatch(st, {"Action": "CreatePolicyVersion", "PolicyArn": policy_arn,
                           "PolicyDocument": _policy({"Effect": "Allow", "Action": "s3:*", "Resource": "*"}),
                           "SetAsDefault": "true"}).body
    _check("policy version created", "<VersionId>v2</VersionId>" in v2)
    lpv = iam.dispatch(st, {"Action": "ListPolicyVersions", "PolicyArn": policy_arn}).body
    _check("both versions listed", "<VersionId>v1</VersionId>" in lpv and "<VersionId>v2</VersionId>" in lpv)
    _check("v2 is default", iam.dispatch(st, {"Action": "GetPolicy", "PolicyArn": policy_arn}).body.count("<DefaultVersionId>v2</DefaultVersionId>") == 1)
    conflict = iam.dispatch(st, {"Action": "DeletePolicyVersion", "PolicyArn": policy_arn, "VersionId": "v2"})
    _check("cannot delete default version", "<Code>DeleteConflict</Code>" in conflict.body)
    iam.dispatch(st, {"Action": "SetDefaultPolicyVersion", "PolicyArn": policy_arn, "VersionId": "v1"})
    iam.dispatch(st, {"Action": "DeletePolicyVersion", "PolicyArn": policy_arn, "VersionId": "v2"})

    # 22. Identity providers (SAML + OIDC)
    samlc = iam.dispatch(st, {"Action": "CreateSAMLProvider", "Name": "okta", "SAMLMetadataDocument": "<meta/>"}).body
    _check("saml provider created", "saml-provider/okta" in samlc)
    _check("saml provider listed", "saml-provider/okta" in iam.dispatch(st, {"Action": "ListSAMLProviders"}).body)
    oidcc = iam.dispatch(st, {"Action": "CreateOpenIDConnectProvider", "Url": "https://token.actions.githubusercontent.com",
                              "ClientIDList.member.1": "sts.amazonaws.com"}).body
    _check("oidc provider created", "oidc-provider/token.actions.githubusercontent.com" in oidcc)
    _check("oidc provider listed", "token.actions.githubusercontent.com" in iam.dispatch(st, {"Action": "ListOpenIDConnectProviders"}).body)

    # 23. Account settings: password policy, account alias, credential report
    iam.dispatch(st, {"Action": "UpdateAccountPasswordPolicy", "MinimumPasswordLength": "14", "RequireSymbols": "true"})
    pp = iam.dispatch(st, {"Action": "GetAccountPasswordPolicy"}).body
    _check("password policy round-trips", "<MinimumPasswordLength>14</MinimumPasswordLength>" in pp and "<RequireSymbols>true</RequireSymbols>" in pp)
    iam.dispatch(st, {"Action": "CreateAccountAlias", "AccountAlias": "vyomi-demo"})
    _check("account alias listed", "<member>vyomi-demo</member>" in iam.dispatch(st, {"Action": "ListAccountAliases"}).body)
    gen = iam.dispatch(st, {"Action": "GenerateCredentialReport"}).body
    _check("credential report generated", "<State>COMPLETE</State>" in gen)
    rep = iam.dispatch(st, {"Action": "GetCredentialReport"}).body
    _check("credential report content present", "<Content>" in rep and "<ReportFormat>text/csv</ReportFormat>" in rep)

    # 24. Vyomi-only: Organizations policies (SCP/RCP) + account access requests —
    # back the IAM console's "Multi-account access" pages without a second service stack.
    scp = iam.dispatch(st, {"Action": "CreateOrgPolicy", "Name": "deny-root", "Type": "SERVICE_CONTROL_POLICY",
                            "Content": _policy({"Effect": "Deny", "Action": "*", "Resource": "*"})}).body
    _check("org policy created", "<Type>SERVICE_CONTROL_POLICY</Type>" in scp and "<Id>p-" in scp)
    scp_id = scp.split("<Id>")[1].split("</Id>")[0]
    rcp = iam.dispatch(st, {"Action": "CreateOrgPolicy", "Name": "deny-cross-account", "Type": "RESOURCE_CONTROL_POLICY",
                            "Content": _policy({"Effect": "Deny", "Action": "*", "Resource": "*"})}).body
    _check("rcp created", "<Type>RESOURCE_CONTROL_POLICY</Type>" in rcp)
    bad_type = iam.dispatch(st, {"Action": "CreateOrgPolicy", "Name": "x", "Type": "TAG_POLICY", "Content": "{}"})
    _check("org policy rejects unsupported type", "<Code>ValidationError</Code>" in bad_type.body)
    lop = iam.dispatch(st, {"Action": "ListOrgPolicies", "Type": "SERVICE_CONTROL_POLICY"}).body
    _check("SCP listed, RCP filtered out", "deny-root" in lop and "deny-cross-account" not in lop)
    dop = iam.dispatch(st, {"Action": "DescribeOrgPolicy", "PolicyId": scp_id}).body
    _check("org policy described", "deny-root" in dop)
    iam.dispatch(st, {"Action": "DeleteOrgPolicy", "PolicyId": scp_id})
    _check("org policy deleted", "deny-root" not in iam.dispatch(st, {"Action": "ListOrgPolicies"}).body)
    missing = iam.dispatch(st, {"Action": "DescribeOrgPolicy", "PolicyId": "p-missing"})
    _check("missing org policy -> NoSuchEntity", "<Code>NoSuchEntity</Code>" in missing.body)

    req = iam.dispatch(st, {"Action": "RequestAccountAccess", "RequestorId": "444455556666", "InitiatedBy": "alice"}).body
    _check("access request created", "<RequestId>ar-" in req and "<RequestorId>444455556666</RequestorId>" in req)
    _check("access request listed", "444455556666" in iam.dispatch(st, {"Action": "ListAccountAccessRequests"}).body)

    # 25. Virtual MFA devices — real assignment/resync/removal; aws:MultiFactorAuthPresent
    # (both the live device state AND a SimulatePrincipalPolicy ContextEntries override) is
    # evaluated by the SAME decision path as every other condition key.
    iam.dispatch(st, {"Action": "CreateUser", "UserName": "erin"})
    cvmd = iam.dispatch(st, {"Action": "CreateVirtualMFADevice", "VirtualMFADeviceName": "erin-phone"}).body
    _check("virtual MFA device created", "<SerialNumber>arn:aws:iam::123456789012:mfa/erin-phone</SerialNumber>" in cvmd
           and "<Base32StringSeed>" in cvmd)
    serial = cvmd.split("<SerialNumber>")[1].split("</SerialNumber>")[0]
    dup = iam.dispatch(st, {"Action": "CreateVirtualMFADevice", "VirtualMFADeviceName": "erin-phone"})
    _check("duplicate virtual MFA device -> EntityAlreadyExists", "<Code>EntityAlreadyExists</Code>" in dup.body)
    _check("unassigned device listed", serial in iam.dispatch(st, {"Action": "ListVirtualMFADevices", "AssignmentStatus": "Unassigned"}).body)
    _check("unassigned device not in Assigned filter", serial not in iam.dispatch(st, {"Action": "ListVirtualMFADevices", "AssignmentStatus": "Assigned"}).body)

    short_codes = iam.dispatch(st, {"Action": "EnableMFADevice", "UserName": "erin", "SerialNumber": serial,
                                    "AuthenticationCode1": "123", "AuthenticationCode2": "456"})
    _check("malformed code rejected", "<Code>InvalidAuthenticationCode</Code>" in short_codes.body)
    same_codes = iam.dispatch(st, {"Action": "EnableMFADevice", "UserName": "erin", "SerialNumber": serial,
                                   "AuthenticationCode1": "111111", "AuthenticationCode2": "111111"})
    _check("identical consecutive codes rejected", "<Code>InvalidAuthenticationCode</Code>" in same_codes.body)
    enabled = iam.dispatch(st, {"Action": "EnableMFADevice", "UserName": "erin", "SerialNumber": serial,
                                "AuthenticationCode1": "111111", "AuthenticationCode2": "222222"})
    _check("MFA device enabled", enabled.status == 200)
    _check("device now listed for erin", serial in iam.dispatch(st, {"Action": "ListMFADevices", "UserName": "erin"}).body)
    _check("device now in Assigned filter", "erin" in iam.dispatch(st, {"Action": "ListVirtualMFADevices", "AssignmentStatus": "Assigned"}).body)
    already = iam.dispatch(st, {"Action": "EnableMFADevice", "UserName": "erin", "SerialNumber": serial,
                                "AuthenticationCode1": "111111", "AuthenticationCode2": "222222"})
    _check("enabling an already-assigned device fails", "<Code>EntityAlreadyExists</Code>" in already.body)
    del_assigned = iam.dispatch(st, {"Action": "DeleteVirtualMFADevice", "SerialNumber": serial})
    _check("deleting an assigned device -> DeleteConflict", "<Code>DeleteConflict</Code>" in del_assigned.body)

    mfa_policy = _policy({"Effect": "Allow", "Action": "s3:*", "Resource": "*",
                          "Condition": {"Bool": {"aws:MultiFactorAuthPresent": "true"}}})
    iam.dispatch(st, {"Action": "CreatePolicy", "PolicyName": "RequireMfa", "PolicyDocument": mfa_policy})
    erin_arn = iam.dispatch(st, {"Action": "GetUser", "UserName": "erin"}).body.split("<Arn>")[1].split("</Arn>")[0]
    iam.dispatch(st, {"Action": "AttachUserPolicy", "UserName": "erin", "PolicyArn": erin_arn.replace(":user/erin", ":policy/RequireMfa")})
    mfa_sim = iam.dispatch(st, {"Action": "SimulatePrincipalPolicy", "PolicySourceArn": "erin", "ActionNames.member.1": "s3:GetObject"})
    _check("MFA-gated action allowed once device is enabled", _decisions(mfa_sim.body).get("s3:GetObject") == "allowed")

    iam.dispatch(st, {"Action": "DeactivateMFADevice", "UserName": "erin", "SerialNumber": serial})
    no_mfa_sim = iam.dispatch(st, {"Action": "SimulatePrincipalPolicy", "PolicySourceArn": "erin", "ActionNames.member.1": "s3:GetObject"})
    _check("MFA-gated action denied once device is deactivated", _decisions(no_mfa_sim.body).get("s3:GetObject") == "implicitDeny")

    override_sim = iam.dispatch(st, {"Action": "SimulatePrincipalPolicy", "PolicySourceArn": "erin", "ActionNames.member.1": "s3:GetObject",
                                     "ContextEntries.member.1.ContextKeyName": "aws:MultiFactorAuthPresent",
                                     "ContextEntries.member.1.ContextKeyValues.member.1": "true"})
    _check("ContextEntries override allows without a live device", _decisions(override_sim.body).get("s3:GetObject") == "allowed")

    not_erins = iam.dispatch(st, {"Action": "DeactivateMFADevice", "UserName": "erin", "SerialNumber": serial})
    _check("deactivating an already-unassigned device -> NoSuchEntity", "<Code>NoSuchEntity</Code>" in not_erins.body)
    resync_bad = iam.dispatch(st, {"Action": "ResyncMFADevice", "UserName": "erin", "SerialNumber": serial, "AuthenticationCode1": "1", "AuthenticationCode2": "2"})
    _check("resync on unassigned device -> NoSuchEntity", "<Code>NoSuchEntity</Code>" in resync_bad.body)
    iam.dispatch(st, {"Action": "EnableMFADevice", "UserName": "erin", "SerialNumber": serial,
                      "AuthenticationCode1": "333333", "AuthenticationCode2": "444444"})
    resync_ok = iam.dispatch(st, {"Action": "ResyncMFADevice", "UserName": "erin", "SerialNumber": serial, "AuthenticationCode1": "333333", "AuthenticationCode2": "444444"})
    _check("resync on assigned device succeeds", resync_ok.status == 200)
    iam.dispatch(st, {"Action": "DeactivateMFADevice", "UserName": "erin", "SerialNumber": serial})
    del_ok = iam.dispatch(st, {"Action": "DeleteVirtualMFADevice", "SerialNumber": serial})
    _check("deleting an unassigned device succeeds", del_ok.status == 200)

    print("\nRESULT: PASS — IAM core conforms (native Query-protocol wire + real policy evaluation) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
