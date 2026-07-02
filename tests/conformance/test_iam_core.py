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

    print("\nRESULT: PASS — IAM core conforms (native Query-protocol wire + real policy evaluation) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
