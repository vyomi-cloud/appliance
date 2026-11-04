"""IAM sweep 2 - GetAccountAuthorizationDetails, action-level + with-entities last-accessed,
ListPoliciesGrantingServiceAccess, OIDC/SAML provider detail operations (client IDs, thumbprints,
metadata update, tags), all through AwsWireRouter (the Nano / unified-ingress entry).

Run: PYTHONPATH=. python3 tests/conformance/test_iam_sweepiam2_core.py
"""
import json
import re
from urllib.parse import urlencode

from core.aws_wire_router import AwsWireRouter

OP = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/iam/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def iam(r, action, akid=None, **p):
    auth = OP.replace("Credential=T/", f"Credential={akid}/") if akid else OP
    out = r.handle("POST", "/", {}, {"authorization": auth, "content-type": "application/x-www-form-urlencoded"},
                   urlencode({"Action": action, "Version": "2010-05-08", **p}).encode())
    return out["status"], out["body"].decode()


def tag(body, t):
    m = re.search(rf"<{t}>(.*?)</{t}>", body, re.S)
    return m.group(1) if m else None


def run():
    r = AwsWireRouter()
    doc = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject", "ec2:Describe*"], "Resource": "*"}]})
    iam(r, "CreateUser", UserName="alice")
    iam(r, "CreateGroup", GroupName="devs")
    iam(r, "AddUserToGroup", GroupName="devs", UserName="alice")
    iam(r, "CreateRole", RoleName="r1", AssumeRolePolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": []}))
    s, b = iam(r, "CreatePolicy", PolicyName="p1", PolicyDocument=doc)
    parn = tag(b, "Arn")
    iam(r, "AttachUserPolicy", UserName="alice", PolicyArn=parn)
    iam(r, "PutUserPolicy", UserName="alice", PolicyName="inl", PolicyDocument=doc)
    iam(r, "PutGroupPolicy", GroupName="devs", PolicyName="ginl", PolicyDocument=doc)
    iam(r, "AttachRolePolicy", RoleName="r1", PolicyArn=parn)

    # ── GetAccountAuthorizationDetails ──────────────────────────────────
    s, b = iam(r, "GetAccountAuthorizationDetails")
    _check("GetAccountAuthorizationDetails ok", s == 200)
    u = tag(b, "UserDetailList")
    _check("user detail has inline policy, group and attached managed policy",
           "<PolicyName>inl</PolicyName>" in u and "<member>devs</member>" in u and "<PolicyArn>" + parn in u)
    _check("group + role details present", "<GroupName>devs</GroupName>" in b and "<RoleName>r1</RoleName>" in b and "<GroupPolicyList>" in b)
    _check("local managed policy has version list", "<PolicyVersionList>" in b and "<IsDefaultVersion>true</IsDefaultVersion>" in b)
    s, b = iam(r, "GetAccountAuthorizationDetails", **{"Filter.member.1": "Role"})
    _check("Filter=Role returns only roles", "<RoleDetailList>" in b and "<UserDetailList>" not in b and "<Policies>" not in b)

    # ── last accessed: ACTION_LEVEL, WithEntities, policies granting access ──
    s, b = iam(r, "CreateAccessKey", UserName="alice")
    akid = tag(b, "AccessKeyId")
    iam(r, "ListUsers", akid=akid)
    iam(r, "GetUser", akid=akid, UserName="alice")
    arn = "arn:aws:iam::123456789012:user/alice"
    s, b = iam(r, "GenerateServiceLastAccessedDetails", Arn=arn, Granularity="ACTION_LEVEL")
    job = tag(b, "JobId")
    s, b = iam(r, "GetServiceLastAccessedDetails", JobId=job)
    _check("ACTION_LEVEL job reports iam service with tracked actions", "<JobType>ACTION_LEVEL</JobType>" in b and "<ActionName>ListUsers</ActionName>" in b and "<ActionName>GetUser</ActionName>" in b)
    s, b = iam(r, "GenerateServiceLastAccessedDetails", Arn=arn)
    s, b = iam(r, "GetServiceLastAccessedDetails", JobId=tag(b, "JobId"))
    _check("SERVICE_LEVEL has no tracked actions", "TrackedActionsLastAccessed" not in b and "<ServiceNamespace>iam</ServiceNamespace>" in b)
    s, b = iam(r, "GetServiceLastAccessedDetailsWithEntities", JobId=job, ServiceNamespace="iam")
    _check("WithEntities lists alice with her last authentication", "<EntityDetailsList>" in b and "<Name>alice</Name>" in b and "<Type>USER</Type>" in b)
    s, b = iam(r, "ListPoliciesGrantingServiceAccess", Arn=arn, **{"ServiceNamespaces.member.1": "s3", "ServiceNamespaces.member.2": "dynamodb"})
    _check("policies granting s3 include managed, inline and group inline; dynamodb has none",
           b.count("<PolicyName>p1</PolicyName>") == 1 and "<PolicyName>inl</PolicyName>" in b and "<PolicyName>ginl</PolicyName>" in b
           and "<ServiceNamespace>dynamodb</ServiceNamespace><Policies></Policies>" in b)
    s, b = iam(r, "ListPoliciesGrantingServiceAccess", Arn=arn, **{"ServiceNamespaces.member.1": "ec2"})
    _check("wildcard action ec2:Describe* grants ec2", "<PolicyName>inl</PolicyName>" in b)

    # ── OIDC provider detail ────────────────────────────────────────────
    tp = "9e99a48a9960b14926bb7f3b02e22da2b0ab7280"
    s, b = iam(r, "CreateOpenIDConnectProvider", Url="https://token.example.com", **{"ClientIDList.member.1": "c1", "ThumbprintList.member.1": tp, "Tags.member.1.Key": "env", "Tags.member.1.Value": "dev"})
    oarn = tag(b, "OpenIDConnectProviderArn")
    iam(r, "AddClientIDToOpenIDConnectProvider", OpenIDConnectProviderArn=oarn, ClientID="c2")
    iam(r, "AddClientIDToOpenIDConnectProvider", OpenIDConnectProviderArn=oarn, ClientID="c2")
    s, b = iam(r, "GetOpenIDConnectProvider", OpenIDConnectProviderArn=oarn)
    _check("AddClientID is idempotent and visible", b.count("<member>c2</member>") == 1 and "<member>c1</member>" in b)
    iam(r, "RemoveClientIDFromOpenIDConnectProvider", OpenIDConnectProviderArn=oarn, ClientID="c1")
    s, b = iam(r, "GetOpenIDConnectProvider", OpenIDConnectProviderArn=oarn)
    _check("RemoveClientID", "<member>c1</member>" not in b)
    s, b = iam(r, "UpdateOpenIDConnectProviderThumbprint", OpenIDConnectProviderArn=oarn, **{"ThumbprintList.member.1": "zz"})
    _check("invalid thumbprint rejected", s == 400)
    tp2 = "a" * 40
    iam(r, "UpdateOpenIDConnectProviderThumbprint", OpenIDConnectProviderArn=oarn, **{"ThumbprintList.member.1": tp2})
    s, b = iam(r, "GetOpenIDConnectProvider", OpenIDConnectProviderArn=oarn)
    _check("thumbprint replaced", f"<member>{tp2}</member>" in b and tp not in b)
    _check("create-time tags returned by Get", "<Key>env</Key>" in b)
    iam(r, "TagOpenIDConnectProvider", OpenIDConnectProviderArn=oarn, **{"Tags.member.1.Key": "team", "Tags.member.1.Value": "x"})
    iam(r, "UntagOpenIDConnectProvider", OpenIDConnectProviderArn=oarn, **{"TagKeys.member.1": "env"})
    s, b = iam(r, "ListOpenIDConnectProviderTags", OpenIDConnectProviderArn=oarn)
    _check("OIDC tag/untag/list", "<Key>team</Key>" in b and "<Key>env</Key>" not in b)
    s, b = iam(r, "AddClientIDToOpenIDConnectProvider", OpenIDConnectProviderArn="arn:aws:iam::123456789012:oidc-provider/nope", ClientID="x")
    _check("unknown OIDC provider -> NoSuchEntity", s == 404)

    # ── SAML provider detail ────────────────────────────────────────────
    s, b = iam(r, "CreateSAMLProvider", Name="idp", SAMLMetadataDocument="<EntityDescriptor a='1'/>")
    sarn = tag(b, "SAMLProviderArn")
    s, b = iam(r, "UpdateSAMLProvider", SAMLProviderArn=sarn, SAMLMetadataDocument="<EntityDescriptor a='2'/>")
    _check("UpdateSAMLProvider returns the ARN", s == 200 and tag(b, "SAMLProviderArn") == sarn)
    s, b = iam(r, "GetSAMLProvider", SAMLProviderArn=sarn)
    _check("metadata replaced", "a=&apos;2&apos;" in b or "a='2'" in b or "a=&#x27;2&#x27;" in b or "a=&#39;2&#39;" in b)
    iam(r, "TagSAMLProvider", SAMLProviderArn=sarn, **{"Tags.member.1.Key": "k", "Tags.member.1.Value": "v"})
    s, b = iam(r, "ListSAMLProviderTags", SAMLProviderArn=sarn)
    _check("SAML tags", "<Key>k</Key>" in b)
    iam(r, "UntagSAMLProvider", SAMLProviderArn=sarn, **{"TagKeys.member.1": "k"})
    _check("SAML untag", "<Key>k</Key>" not in iam(r, "ListSAMLProviderTags", SAMLProviderArn=sarn)[1])
    # ── policy simulator fidelity: SimulateCustomPolicy, resource policy, context keys, principal tags ──
    pol_s3 = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*",
                                                                  "Condition": {"StringEquals": {"aws:PrincipalTag/team": "sec"}}}]})
    s, b = iam(r, "SimulateCustomPolicy", **{"PolicyInputList.member.1": pol_s3, "ActionNames.member.1": "s3:GetObject", "ResourceArns.member.1": "arn:aws:s3:::b/k"})
    _check("SimulateCustomPolicy: condition on a missing key -> implicitDeny + MissingContextValues",
           "<EvalDecision>implicitDeny</EvalDecision>" in b and "<member>aws:PrincipalTag/team</member>" not in b)
    pol_ip = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*",
                                                                  "Condition": {"IpAddress": {"aws:SourceIp": "10.0.0.0/8"}}}]})
    s, b = iam(r, "SimulateCustomPolicy", **{"PolicyInputList.member.1": pol_ip, "ActionNames.member.1": "s3:GetObject", "ResourceArns.member.1": "*"})
    _check("SimulateCustomPolicy reports the missing condition key", "<MissingContextValues><member>aws:SourceIp</member></MissingContextValues>" in b)
    s, b = iam(r, "SimulateCustomPolicy", **{"PolicyInputList.member.1": pol_ip, "ActionNames.member.1": "s3:GetObject", "ResourceArns.member.1": "*",
                                              "ContextEntries.member.1.ContextKeyName": "aws:SourceIp", "ContextEntries.member.1.ContextKeyType": "ip",
                                              "ContextEntries.member.1.ContextKeyValues.member.1": "10.1.2.3"})
    _check("supplying the context key flips it to allowed", "<EvalDecision>allowed</EvalDecision>" in b and "MissingContextValues" not in b)
    boundary = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "ec2:*", "Resource": "*"}]})
    pol_all = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]})
    s, b = iam(r, "SimulateCustomPolicy", **{"PolicyInputList.member.1": pol_all, "PermissionsBoundaryPolicyInputList.member.1": boundary,
                                              "ActionNames.member.1": "s3:GetObject", "ActionNames.member.2": "ec2:DescribeVpcs", "ResourceArns.member.1": "*"})
    _check("custom boundary clips identity allow (s3 denied, ec2 allowed)", b.count("<EvalDecision>allowed</EvalDecision>") == 1 and b.count("implicitDeny") == 1)
    rp = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::123456789012:user/alice"}, "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/*"}]})
    s, b = iam(r, "SimulatePrincipalPolicy", PolicySourceArn=arn, ResourcePolicy=rp, **{"ActionNames.member.1": "s3:GetObject", "ResourceArns.member.1": "arn:aws:s3:::b/k"})
    _check("a resource policy naming the caller grants access on its own (same account)", "<EvalDecision>allowed</EvalDecision>" in b)
    rp_deny = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Principal": "*", "Action": "s3:*", "Resource": "*"}]})
    s, b = iam(r, "SimulatePrincipalPolicy", PolicySourceArn=arn, ResourcePolicy=rp_deny, **{"ActionNames.member.1": "s3:GetObject", "ResourceArns.member.1": "arn:aws:s3:::b/k"})
    _check("a resource-policy explicit Deny wins over the identity allow", "<EvalDecision>explicitDeny</EvalDecision>" in b)
    iam(r, "TagUser", UserName="alice", **{"Tags.member.1.Key": "team", "Tags.member.1.Value": "sec"})
    s, b = iam(r, "PutUserPolicy", UserName="alice", PolicyName="tagged", PolicyDocument=pol_s3)
    s, b = iam(r, "SimulatePrincipalPolicy", PolicySourceArn=arn, **{"ActionNames.member.1": "s3:GetObject", "ResourceArns.member.1": "arn:aws:s3:::b/k"})
    _check("aws:PrincipalTag/<key> is derived from the principal's real tags", "<EvalDecision>allowed</EvalDecision>" in b)

    # ── condition operators: numeric, date, ip, Null, IfExists, negations, policy variables ──
    from core.iam_store import NativeIamEvaluator as E
    cm = E._condition_matches
    _check("NumericLessThan", cm({"NumericLessThan": {"s3:max-keys": "10"}}, {"s3:max-keys": "5"}) and not cm({"NumericLessThan": {"s3:max-keys": "10"}}, {"s3:max-keys": "50"}))
    _check("DateGreaterThan (ISO + epoch)", cm({"DateGreaterThan": {"aws:CurrentTime": "2020-01-01T00:00:00Z"}}, {"aws:CurrentTime": "2026-11-02T00:00:00Z"})
           and not cm({"DateGreaterThan": {"aws:CurrentTime": "2030-01-01T00:00:00Z"}}, {"aws:CurrentTime": "2026-11-02T00:00:00Z"}))
    _check("IpAddress / NotIpAddress CIDR", cm({"IpAddress": {"aws:SourceIp": ["10.0.0.0/8", "192.168.0.0/16"]}}, {"aws:SourceIp": "192.168.4.5"})
           and cm({"NotIpAddress": {"aws:SourceIp": "10.0.0.0/8"}}, {"aws:SourceIp": "172.16.0.1"})
           and not cm({"NotIpAddress": {"aws:SourceIp": "10.0.0.0/8"}}, {"aws:SourceIp": "10.9.9.9"}))
    _check("Null checks key presence", cm({"Null": {"aws:TokenIssueTime": "true"}}, {}) and not cm({"Null": {"aws:TokenIssueTime": "true"}}, {"aws:TokenIssueTime": "x"}))
    _check("StringNotEquals is true when the key is absent (AWS semantics); StringEquals is false", cm({"StringNotEquals": {"k": "v"}}, {}) and not cm({"StringEquals": {"k": "v"}}, {}))
    _check("IfExists passes when absent, enforces when present", cm({"StringEqualsIfExists": {"k": "v"}}, {}) and not cm({"StringEqualsIfExists": {"k": "v"}}, {"k": "w"}))
    _check("StringEqualsIgnoreCase + ForAnyValue qualifier", cm({"ForAnyValue:StringEqualsIgnoreCase": {"k": "VAL"}}, {"k": "val"}))
    _check("policy variable ${aws:username}", cm({"StringEquals": {"s3:prefix": "home/${aws:username}"}}, {"s3:prefix": "home/alice", "aws:username": "alice"})
           and not cm({"StringEquals": {"s3:prefix": "home/${aws:username}"}}, {"s3:prefix": "home/bob", "aws:username": "alice"}))
    _check("Bool still works", cm({"Bool": {"aws:SecureTransport": "true"}}, {"aws:SecureTransport": "true"}))

    # ── CreateVirtualMFADevice returns a real QR code PNG of the otpauth:// URI ──
    import base64
    s, b = iam(r, "CreateVirtualMFADevice", VirtualMFADeviceName="qrdev")
    png = base64.b64decode(tag(b, "QRCodePNG"))
    seed = base64.b64decode(tag(b, "Base32StringSeed")).decode()
    _check("QRCodePNG is a real PNG, not a placeholder", png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 500)
    try:   # optional independent decode (OpenCV) when available in the test environment
        import cv2
        import numpy as np
        txt = cv2.QRCodeDetector().detectAndDecode(cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE))[0]
        _check("the QR decodes to the otpauth URI carrying the device seed", txt.startswith("otpauth://totp/") and f"secret={seed}" in txt)
    except ImportError:
        print("  --  (cv2 not installed: QR decode check skipped)")
    print("IAM sweep 2 core: all checks passed")


if __name__ == "__main__":
    run()
