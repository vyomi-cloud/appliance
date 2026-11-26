"""STS trust evaluation + federation over the real wire router (AwsWireRouter, the same code Nano runs):
AssumeRole / AssumeRoleWithWebIdentity / AssumeRoleWithSAML, session principals, IAM Roles Anywhere CreateSession, CloudTrail events."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]

from core.aws_wire_router import AwsWireRouter  # noqa: E402

AUTH = "AWS4-HMAC-SHA256 Credential=%s/20260101/us-east-1/%s/aws4_request, SignedHeaders=host, Signature=x"


class W:
    def __init__(self):
        self.r = AwsWireRouter()
        self.acct = self.r.iam.account_id

    def call(self, svc, akid="AKIATEST", **p):
        h = {"authorization": AUTH % (akid, svc), "content-type": "application/x-www-form-urlencoded"}
        o = self.r._handle_raw("POST", "/", {}, h, urlencode(p).encode())
        return o["status"], o["body"].decode()

    def role(self, name, trust, **kw):
        s, b = self.call("iam", Action="CreateRole", RoleName=name, AssumeRolePolicyDocument=json.dumps(trust), Version="2010-05-08", **kw)
        assert s == 200, b

    def sts(self, action, **p):
        return self.call("sts", Action=action, Version="2011-06-15", **p)


def _tag(body, name):
    a = body.index(f"<{name}>") + len(name) + 2
    return body[a:body.index(f"</{name}>", a)]


def _jwt(**claims):
    e = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")      # noqa: E731
    return e({"alg": "RS256", "typ": "JWT"}) + "." + e(claims) + ".sig"


def _trust(principal, action, cond=None):
    st = {"Effect": "Allow", "Principal": principal, "Action": action}
    if cond:
        st["Condition"] = cond
    return {"Version": "2012-10-17", "Statement": [st]}


@pytest.fixture
def w():
    return W()


# ------------------------------------------------------------------ AssumeRole
def test_assume_role_trust_allow_deny_and_unknown_role(w):
    root = f"arn:aws:iam::{w.acct}:root"
    w.role("ok", _trust({"AWS": root}, "sts:AssumeRole"))
    w.role("svc", _trust({"Service": "lambda.amazonaws.com"}, "sts:AssumeRole"))
    s, b = w.sts("AssumeRole", RoleArn=f"arn:aws:iam::{w.acct}:role/ok", RoleSessionName="s1")
    assert s == 200 and _tag(b, "AccessKeyId").startswith("ASIA") and f"assumed-role/ok/s1" in b
    s, b = w.sts("AssumeRole", RoleArn=f"arn:aws:iam::{w.acct}:role/svc", RoleSessionName="s1")
    assert s == 403 and "<Code>AccessDenied</Code>" in b and "is not authorized to perform: sts:AssumeRole on resource" in b
    s, b = w.sts("AssumeRole", RoleArn=f"arn:aws:iam::{w.acct}:role/none", RoleSessionName="s1")
    assert s == 403 and "AccessDenied" in b


def test_assume_role_conditions_externalid_and_session_name(w):
    root = f"arn:aws:iam::{w.acct}:root"
    w.role("ext", _trust({"AWS": root}, "sts:AssumeRole", {"StringEquals": {"sts:ExternalId": "abc"}, "StringLike": {"sts:RoleSessionName": "ci-*"}}))
    arn = f"arn:aws:iam::{w.acct}:role/ext"
    assert w.sts("AssumeRole", RoleArn=arn, RoleSessionName="ci-1")[0] == 403                          # no ExternalId
    assert w.sts("AssumeRole", RoleArn=arn, RoleSessionName="ci-1", ExternalId="zzz")[0] == 403
    assert w.sts("AssumeRole", RoleArn=arn, RoleSessionName="other", ExternalId="abc")[0] == 403      # session name pattern
    assert w.sts("AssumeRole", RoleArn=arn, RoleSessionName="ci-1", ExternalId="abc")[0] == 200


def test_assume_role_explicit_deny_and_duration_bounds(w):
    root = f"arn:aws:iam::{w.acct}:root"
    doc = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": {"AWS": root}, "Action": "sts:AssumeRole"},
        {"Effect": "Deny", "Principal": {"AWS": root}, "Action": "sts:AssumeRole", "Condition": {"Null": {"sts:ExternalId": "true"}}}]}
    w.role("d", doc)
    arn = f"arn:aws:iam::{w.acct}:role/d"
    assert w.sts("AssumeRole", RoleArn=arn, RoleSessionName="s1")[0] == 403                                      # explicit deny wins
    assert w.sts("AssumeRole", RoleArn=arn, RoleSessionName="s1", ExternalId="x")[0] == 200
    s, b = w.sts("AssumeRole", RoleArn=arn, RoleSessionName="s1", ExternalId="x", DurationSeconds="7200")
    assert s == 400 and "MaxSessionDuration" in b
    s, b = w.sts("AssumeRole", RoleArn=arn, RoleSessionName="s1", ExternalId="x", DurationSeconds="100")
    assert s == 400 and "ValidationError" in b


def test_same_account_root_principal_needs_identity_policy_for_an_iam_user(w):
    root = f"arn:aws:iam::{w.acct}:root"
    w.role("viaroot", _trust({"AWS": root}, "sts:AssumeRole"))
    s, b = w.call("iam", Action="CreateUser", UserName="bob", Version="2010-05-08")
    assert s == 200
    s, b = w.call("iam", Action="CreateAccessKey", UserName="bob", Version="2010-05-08")
    akid = _tag(b, "AccessKeyId")
    arn = f"arn:aws:iam::{w.acct}:role/viaroot"
    s, b = w.call("sts", akid=akid, Action="AssumeRole", Version="2011-06-15", RoleArn=arn, RoleSessionName="b1") if False else \
        w.call("sts", akid, Action="AssumeRole", Version="2011-06-15", RoleArn=arn, RoleSessionName="b1")
    assert s == 403                                                                           # trust allows the account, bob's identity policy does not
    pol = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "sts:AssumeRole", "Resource": arn}]})
    assert w.call("iam", Action="PutUserPolicy", UserName="bob", PolicyName="p", PolicyDocument=pol, Version="2010-05-08")[0] == 200
    s, b = w.call("sts", akid, Action="AssumeRole", Version="2011-06-15", RoleArn=arn, RoleSessionName="b1")
    assert s == 200


def test_session_credentials_become_the_assumed_role_principal(w):
    from core import iam_state_adapters as ad
    root = f"arn:aws:iam::{w.acct}:root"
    w.role("sess", _trust({"AWS": root}, "sts:AssumeRole"), **{"Tags.member.1.Key": "team", "Tags.member.1.Value": "blue"})
    s, b = w.sts("AssumeRole", RoleArn=f"arn:aws:iam::{w.acct}:role/sess", RoleSessionName="s1", **{"Tags.member.1.Key": "env", "Tags.member.1.Value": "dev"})
    akid = _tag(b, "AccessKeyId")
    p = ad.aws_principal({"authorization": AUTH % (akid, "s3")}, "", w.r.iam)
    assert p["arn"] == f"arn:aws:sts::{w.acct}:assumed-role/sess/s1" and p["tags"]["env"] == "dev" and p["tags"]["team"] == "blue"
    w.r.iam.extras["sts_sessions"][akid]["expires"] = time.time() - 5            # expired -> no longer a principal
    assert ad.aws_principal({"authorization": AUTH % (akid, "s3")}, "", w.r.iam)["type"] == "unknown"


# ------------------------------------------------------------------ web identity
def _gh(w):
    s, b = w.call("iam", Action="CreateOpenIDConnectProvider", Url="https://token.actions.githubusercontent.com", Version="2010-05-08",
                  **{"ClientIDList.member.1": "sts.amazonaws.com", "ThumbprintList.member.1": "a" * 40})
    assert s == 200, b
    arn = f"arn:aws:iam::{w.acct}:oidc-provider/token.actions.githubusercontent.com"
    host = "token.actions.githubusercontent.com"
    w.role("gh", _trust({"Federated": arn}, "sts:AssumeRoleWithWebIdentity",
                        {"StringEquals": {f"{host}:aud": "sts.amazonaws.com"}, "StringLike": {f"{host}:sub": "repo:acme/*:ref:refs/heads/main"}}))
    return f"arn:aws:iam::{w.acct}:role/gh"


def test_web_identity_happy_path_and_condition_failures(w):
    role = _gh(w)
    iss = "https://token.actions.githubusercontent.com"
    ok = _jwt(iss=iss, aud="sts.amazonaws.com", sub="repo:acme/app:ref:refs/heads/main", exp=time.time() + 600)
    s, b = w.sts("AssumeRoleWithWebIdentity", RoleArn=role, RoleSessionName="ci", WebIdentityToken=ok)
    assert s == 200 and _tag(b, "SubjectFromWebIdentityToken") == "repo:acme/app:ref:refs/heads/main" and "<Provider>token.actions.githubusercontent.com" in b
    wrong_sub = _jwt(iss=iss, aud="sts.amazonaws.com", sub="repo:acme/app:ref:refs/heads/dev", exp=time.time() + 600)
    s, b = w.sts("AssumeRoleWithWebIdentity", RoleArn=role, RoleSessionName="ci", WebIdentityToken=wrong_sub)
    assert s == 403 and "AccessDenied" in b
    s, b = w.sts("AssumeRoleWithWebIdentity", RoleArn=role, RoleSessionName="ci",
                 WebIdentityToken=_jwt(iss=iss, aud="other", sub="repo:acme/app:ref:refs/heads/main", exp=time.time() + 600))
    assert s == 400 and "Incorrect token audience" in b
    s, b = w.sts("AssumeRoleWithWebIdentity", RoleArn=role, RoleSessionName="ci",
                 WebIdentityToken=_jwt(iss=iss, aud="sts.amazonaws.com", sub="x", exp=time.time() - 60))
    assert s == 400 and "ExpiredTokenException" in b
    s, b = w.sts("AssumeRoleWithWebIdentity", RoleArn=role, RoleSessionName="ci",
                 WebIdentityToken=_jwt(iss="https://nobody.example", aud="a", sub="x", exp=time.time() + 60))
    assert s == 400 and "No OpenIDConnect provider found in your account for https://nobody.example" in b
    s, b = w.sts("AssumeRoleWithWebIdentity", RoleArn=role, RoleSessionName="ci", WebIdentityToken="not-a-jwt")
    assert s == 400 and "InvalidIdentityToken" in b


def test_web_identity_works_unsigned_like_the_sdk(w):
    role = _gh(w)
    tok = _jwt(iss="https://token.actions.githubusercontent.com", aud="sts.amazonaws.com", sub="repo:acme/x:ref:refs/heads/main", exp=time.time() + 600)
    body = urlencode({"Action": "AssumeRoleWithWebIdentity", "Version": "2011-06-15", "RoleArn": role, "RoleSessionName": "u", "WebIdentityToken": tok}).encode()
    o = w.r._handle_raw("POST", "/", {}, {"content-type": "application/x-www-form-urlencoded"}, body)      # no Authorization header at all
    assert o["status"] == 200 and b"<AccessKeyId>ASIA" in o["body"]


# ------------------------------------------------------------------ SAML
def _assertion(issuer, role_arn, prov_arn, *, aud="https://signin.aws.amazon.com/saml", name="alice@corp", fmt="persistent", expired=False, session="alice"):
    nb = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + (-3600 if expired else 600)))
    xml = f"""<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">
<saml:Assertion><saml:Issuer>{issuer}</saml:Issuer>
<saml:Subject><saml:NameID Format="urn:oasis:names:tc:SAML:2.0:nameid-format:{fmt}">{name}</saml:NameID>
<saml:SubjectConfirmation><saml:SubjectConfirmationData NotOnOrAfter="{nb}" Recipient="https://signin.aws.amazon.com/saml"/></saml:SubjectConfirmation></saml:Subject>
<saml:Conditions NotOnOrAfter="{nb}"><saml:AudienceRestriction><saml:Audience>{aud}</saml:Audience></saml:AudienceRestriction></saml:Conditions>
<saml:AttributeStatement>
<saml:Attribute Name="https://aws.amazon.com/SAML/Attributes/Role"><saml:AttributeValue>{role_arn},{prov_arn}</saml:AttributeValue></saml:Attribute>
<saml:Attribute Name="https://aws.amazon.com/SAML/Attributes/RoleSessionName"><saml:AttributeValue>{session}</saml:AttributeValue></saml:Attribute>
</saml:AttributeStatement></saml:Assertion></samlp:Response>"""
    return base64.b64encode(xml.encode()).decode()


def test_saml_trust_issuer_audience_and_conditions(w):
    meta = '<EntityDescriptor entityID="https://idp.corp.example/saml"><IDPSSODescriptor/></EntityDescriptor>'
    s, b = w.call("iam", Action="CreateSAMLProvider", Name="corp", SAMLMetadataDocument=meta, Version="2010-05-08")
    assert s == 200, b
    parn = f"arn:aws:iam::{w.acct}:saml-provider/corp"
    w.role("saml", _trust({"Federated": parn}, "sts:AssumeRoleWithSAML", {"StringEquals": {"saml:aud": "https://signin.aws.amazon.com/saml", "saml:iss": "https://idp.corp.example/saml"}}))
    rarn = f"arn:aws:iam::{w.acct}:role/saml"
    s, b = w.sts("AssumeRoleWithSAML", RoleArn=rarn, PrincipalArn=parn, SAMLAssertion=_assertion("https://idp.corp.example/saml", rarn, parn))
    assert s == 200 and _tag(b, "Subject") == "alice@corp" and "assumed-role/saml/alice" in b and _tag(b, "SubjectType") == "persistent"
    s, b = w.sts("AssumeRoleWithSAML", RoleArn=rarn, PrincipalArn=parn, SAMLAssertion=_assertion("https://evil.example", rarn, parn))
    assert s == 400 and "not present in specified SAML provider" in b
    s, b = w.sts("AssumeRoleWithSAML", RoleArn=rarn, PrincipalArn=parn, SAMLAssertion=_assertion("https://idp.corp.example/saml", rarn, parn, expired=True))
    assert s == 400 and "ExpiredTokenException" in b
    s, b = w.sts("AssumeRoleWithSAML", RoleArn=rarn, PrincipalArn=parn, SAMLAssertion=_assertion("https://idp.corp.example/saml", rarn, parn, aud="https://x"))
    assert s == 400 and "Audience" in b
    other = f"arn:aws:iam::{w.acct}:role/other"
    s, b = w.sts("AssumeRoleWithSAML", RoleArn=rarn, PrincipalArn=parn, SAMLAssertion=_assertion("https://idp.corp.example/saml", other, parn))
    assert s == 403                                                                           # the assertion does not grant this role


# ------------------------------------------------------------------ Roles Anywhere
def _make_ca_and_leaf(tmp):
    def sh(*a):
        subprocess.run(a, check=True, capture_output=True, cwd=tmp)
    sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem", "-subj", "/CN=Vyomi Test CA", "-days", "30")
    sh("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", "leaf.key", "-out", "leaf.csr", "-subj", "/CN=workload-7")
    sh("openssl", "x509", "-req", "-in", "leaf.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial", "-out", "leaf.pem", "-days", "30")
    return open(os.path.join(tmp, "ca.pem")).read(), open(os.path.join(tmp, "leaf.pem")).read()


@pytest.mark.skipif(not subprocess.run(["which", "openssl"], capture_output=True).stdout, reason="openssl not available")
def test_roles_anywhere_create_session(w):
    with tempfile.TemporaryDirectory() as tmp:
        ca, leaf = _make_ca_and_leaf(tmp)
    s, b = w.call("iam", Action="CreateTrustAnchor", Name="ta", SourceData=ca, Version="2010-05-08")
    assert s == 200, b
    anchor = _tag(b, "TrustAnchorArn")
    w.role("ra", _trust({"Service": "rolesanywhere.amazonaws.com"}, ["sts:AssumeRole", "sts:TagSession", "sts:SetSourceIdentity"],
                        {"ArnEquals": {"aws:SourceArn": anchor}, "StringEquals": {"aws:PrincipalTag/x509Subject/CN": "workload-7"}}))
    rarn = f"arn:aws:iam::{w.acct}:role/ra"
    s, b = w.call("iam", Action="CreateProfile", Name="prof", **{"RoleArns.member.1": rarn}, Version="2010-05-08")
    assert s == 200, b
    prof = _tag(b, "ProfileArn")
    der = "".join(leaf.strip().splitlines()[1:-1])
    h = {"authorization": "AWS4-X509-RSA-SHA256 Credential=1234/20260101/us-east-1/rolesanywhere/aws4_request, SignedHeaders=host, Signature=x",
         "x-amz-x509": der, "content-type": "application/json"}
    body = json.dumps({"profileArn": prof, "roleArn": rarn, "trustAnchorArn": anchor, "durationSeconds": 3600}).encode()
    o = w.r._handle_raw("POST", "/sessions", {}, h, body)
    doc = json.loads(o["body"])
    assert o["status"] == 201, doc
    c = doc["credentialSet"][0]
    assert c["credentials"]["accessKeyId"].startswith("ASIA") and c["assumedRoleUser"]["arn"].startswith(f"arn:aws:sts::{w.acct}:assumed-role/ra/")
    from core import iam_state_adapters as ad
    p = ad.aws_principal({"authorization": AUTH % (c["credentials"]["accessKeyId"], "s3")}, "", w.r.iam)
    assert p["tags"]["x509Subject/CN"] == "workload-7"
    w.role("ra2", _trust({"Service": "rolesanywhere.amazonaws.com"}, "sts:AssumeRole", {"StringEquals": {"aws:PrincipalTag/x509Subject/CN": "someone-else"}}))
    r2 = f"arn:aws:iam::{w.acct}:role/ra2"
    s, b = w.call("iam", Action="CreateProfile", Name="prof2", **{"RoleArns.member.1": r2}, Version="2010-05-08")
    p2 = _tag(b, "ProfileArn")
    o = w.r._handle_raw("POST", "/sessions", {}, h, json.dumps({"profileArn": p2, "roleArn": r2, "trustAnchorArn": anchor}).encode())
    assert o["status"] == 403
    o = w.r._handle_raw("POST", "/sessions", {}, h, json.dumps({"profileArn": prof, "roleArn": r2, "trustAnchorArn": anchor}).encode())
    assert o["status"] == 403                                                                  # role not in the profile


# ------------------------------------------------------------------ CloudTrail
def test_sts_calls_land_in_cloudtrail_with_error_codes(w):
    role = _gh(w)
    w.sts("AssumeRoleWithWebIdentity", RoleArn=role, RoleSessionName="ci",
          WebIdentityToken=_jwt(iss="https://token.actions.githubusercontent.com", aud="sts.amazonaws.com", sub="nope", exp=time.time() + 60))
    ev = [e for e in w.r.trail_events if e["EventName"] == "AssumeRoleWithWebIdentity"][-1]
    d = json.loads(ev["CloudTrailEvent"])
    assert d["errorCode"] == "AccessDenied" and d["userIdentity"]["type"] == "WebIdentityUser"
    assert "webIdentityToken" not in json.dumps(d)                                      # tokens are never logged
    w.call("iam", Action="CreateRole", RoleName="traced", AssumeRolePolicyDocument=json.dumps(_trust({"Service": "ec2.amazonaws.com"}, "sts:AssumeRole")),
           Version="2010-05-08")
    ev = [e for e in w.r.trail_events if e["EventName"] == "CreateRole"][-1]
    assert {"ResourceType": "AWS::IAM::Role", "ResourceName": "traced"} in ev["Resources"]
