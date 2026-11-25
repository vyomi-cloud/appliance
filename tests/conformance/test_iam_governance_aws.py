"""AWS governance: S3 Block Public Access (bucket + account) enforced by the engine, Organizations SCP/RCP attachment evaluated per
account, 'effective policies for account', through the real server (signed + anonymous) and the pure engine Nano vendors."""
import json, os, re, sys, types, uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")

from core import iam_resource_policies as rp  # noqa: E402
from core.iam_engine import aws_eval  # noqa: E402

ACCT = "123456789012"
BPA = lambda **kw: "<PublicAccessBlockConfiguration>" + "".join(f"<{k}>{'true' if v else 'false'}</{k}>" for k, v in kw.items()) + "</PublicAccessBlockConfiguration>"
PUBLIC_POLICY = json.dumps({"Version": "2012-10-17", "Statement": [{"Sid": "pub", "Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b1/*"}]})
ACL_PUBLIC = ('<AccessControlPolicy><Owner><ID>o</ID></Owner><AccessControlList><Grant><Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="Group">'
              '<URI>http://acs.amazonaws.com/groups/global/AllUsers</URI></Grantee><Permission>READ</Permission></Grant></AccessControlList></AccessControlPolicy>')


def s3store(cfg=None, acct_pab=None, acl=None, objects=None):
    return types.SimpleNamespace(account_id=ACCT, account={"pab": acct_pab or {}},
                                 buckets={"b1": {"cfg": cfg or {}, "acl": acl}}, objects={"b1": objects or {}})


def state_for(s3):
    return {"account": ACCT, **rp.aws_resource_state({"s3": s3})}


ANON = {"arn": "", "type": "anonymous", "account": ACCT}
OTHER = {"arn": "arn:aws:iam::999999999999:user/m", "type": "user", "account": "999999999999",
         "policies": [{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}]}     # cross-account: identity AND resource must allow
OWNER = {"arn": f"arn:aws:iam::{ACCT}:user/o", "type": "user", "account": ACCT,
         "policies": [{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}]}]}


def ev(state, principal, action="s3:GetObject", res="arn:aws:s3:::b1/k"):
    return aws_eval.evaluate({"action": action, "resource": res, "principal": principal}, state)


def test_public_policy_allows_anonymous_until_restrict_public_buckets():
    s3 = s3store({"policy": PUBLIC_POLICY})
    assert ev(state_for(s3), ANON)["allowed"] is True
    assert ev(state_for(s3), OTHER)["allowed"] is True                                    # cross-account via the public policy
    s3 = s3store({"policy": PUBLIC_POLICY, "publicAccessBlock": BPA(RestrictPublicBuckets=True)})
    d = ev(state_for(s3), ANON)
    assert d["allowed"] is False and d.get("blockPublicAccess") == "RestrictPublicBuckets"
    assert ev(state_for(s3), OTHER)["allowed"] is False
    assert ev(state_for(s3), OWNER)["allowed"] is True                                    # the owner's own principals are unaffected


def test_account_level_block_applies_to_every_bucket():
    s3 = s3store({"policy": PUBLIC_POLICY}, acct_pab={"RestrictPublicBuckets": True})
    assert ev(state_for(s3), ANON)["allowed"] is False
    s3 = s3store({"policy": PUBLIC_POLICY, "publicAccessBlock": BPA(RestrictPublicBuckets=False)}, acct_pab={"RestrictPublicBuckets": False})
    assert ev(state_for(s3), ANON)["allowed"] is True


def test_restrict_does_not_drop_non_public_statements():
    pol = json.dumps({"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b1/*", "Condition": {"StringEquals": {"aws:PrincipalOrgID": "o-1"}}},
        {"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::999999999999:root"}, "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b1/*"}]})
    s3 = s3store({"policy": pol, "publicAccessBlock": BPA(RestrictPublicBuckets=True)})
    assert ev(state_for(s3), OTHER)["allowed"] is True                                    # an explicit account grant is not 'public'


def test_acl_grants_and_ignore_public_acls():
    s3 = s3store({}, acl=ACL_PUBLIC)
    assert ev(state_for(s3), ANON, "s3:ListBucket", "arn:aws:s3:::b1")["allowed"] is True      # AllUsers READ on the bucket ACL
    assert ev(state_for(s3), ANON, "s3:GetObject")["allowed"] is False                         # bucket READ does not grant objects
    s3 = s3store({"publicAccessBlock": BPA(IgnorePublicAcls=True)}, acl=ACL_PUBLIC)
    assert ev(state_for(s3), ANON, "s3:ListBucket", "arn:aws:s3:::b1")["allowed"] is False
    s3 = s3store({}, acl=None, objects={"k": {"acl": ACL_PUBLIC}})
    assert ev(state_for(s3), ANON)["allowed"] is True and ev(state_for(s3), ANON, res="arn:aws:s3:::b1/other")["allowed"] is False
    s3 = s3store({}, acl=None, acct_pab={"IgnorePublicAcls": True}, objects={"k": {"acl": ACL_PUBLIC}})
    assert ev(state_for(s3), ANON)["allowed"] is False                                        # account-level Ignore
    # RestrictPublicBuckets does not touch ACL grants
    s3 = s3store({"publicAccessBlock": BPA(RestrictPublicBuckets=True)}, acl=ACL_PUBLIC)
    assert ev(state_for(s3), ANON, "s3:ListBucket", "arn:aws:s3:::b1")["allowed"] is True


# ---------------------------------------------------------------- real server
@pytest.fixture(scope="module")
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    yield c
    c.put("/api/iam/aws/enforcement", json={"space": "off"})


def _hdr(svc):
    return f"AWS4-HMAC-SHA256 Credential=test/20261123/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=00"


def _s3(c, method, path, **kw):
    return c.request(method, path, headers={"Authorization": _hdr("s3"), "X-Amz-Date": "20261123T000000Z"}, **kw)


def _s3control(c, method, body=None):
    h = {"Authorization": _hdr("s3"), "X-Amz-Date": "20261123T000000Z", "x-amz-account-id": ACCT}
    return c.request(method, "/v20180820/configuration/publicAccessBlock", headers=h, content=body)


def test_e2e_block_public_access_bucket_and_account(client):
    c, bucket = client, "gov-bpa-" + uuid.uuid4().hex[:8]
    pol = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/*"}]}
    try:
        assert _s3(c, "PUT", f"/{bucket}").status_code == 200
        assert _s3(c, "PUT", f"/{bucket}/k.txt", content=b"x").status_code == 200
        assert _s3(c, "PUT", f"/{bucket}?policy", content=json.dumps(pol)).status_code in (200, 204)
        assert c.put("/api/iam/aws/enforcement", json={"space": "enforce"}).status_code == 200
        assert c.get(f"/{bucket}/k.txt").status_code == 200                               # public policy: anonymous allowed
        # bucket-level RestrictPublicBuckets
        assert _s3(c, "PUT", f"/{bucket}?publicAccessBlock", content=BPA(RestrictPublicBuckets=True)).status_code in (200, 204)
        den = c.get(f"/{bucket}/k.txt")
        assert den.status_code == 403 and "AccessDenied" in den.text, den.text
        # the bucket owner (signed) still reads it
        assert _s3(c, "GET", f"/{bucket}/k.txt").status_code == 200
        assert _s3(c, "DELETE", f"/{bucket}?publicAccessBlock").status_code in (200, 204)
        assert c.get(f"/{bucket}/k.txt").status_code == 200
        # account-level (s3control) block reaches the same bucket
        xml = BPA(BlockPublicAcls=False, IgnorePublicAcls=False, BlockPublicPolicy=False, RestrictPublicBuckets=True)
        assert _s3control(c, "PUT", xml).status_code in (200, 204)
        assert c.get(f"/{bucket}/k.txt").status_code == 403
        assert _s3control(c, "DELETE").status_code in (200, 204)
        assert c.get(f"/{bucket}/k.txt").status_code == 200
        # BlockPublicPolicy rejects a NEW public policy at put time (store-level, existing behaviour kept)
        assert _s3(c, "PUT", f"/{bucket}?publicAccessBlock", content=BPA(BlockPublicPolicy=True)).status_code in (200, 204)
        assert _s3(c, "PUT", f"/{bucket}?policy", content=json.dumps(pol)).status_code == 403
    finally:
        c.put("/api/iam/aws/enforcement", json={"space": "off"})
        _s3control(c, "DELETE")
        _s3(c, "DELETE", f"/{bucket}?publicAccessBlock")
        _s3(c, "DELETE", f"/{bucket}/k.txt")
        _s3(c, "DELETE", f"/{bucket}")


# ---------------------------------------------------------------- Organizations: SCP/RCP attach/detach evaluated, effective policies
def _org_call(c, action, body):
    return c.post("/", content=json.dumps(body), headers={"X-Amz-Target": "AWSOrganizationsV20161128." + action, "Content-Type": "application/x-amz-json-1.1",
                                                           "Authorization": _hdr("organizations"), "X-Amz-Date": "20261123T000000Z"})


def test_org_scp_attach_detach_effective_and_enforced(client):
    c, u = client, uuid.uuid4().hex[:6]
    made = {"policies": [], "ous": [], "accounts": [], "attach": []}
    created_org = False
    try:
        r = _org_call(c, "DescribeOrganization", {})
        if r.status_code != 200:
            assert _org_call(c, "CreateOrganization", {"FeatureSet": "ALL"}).status_code == 200
            created_org = True
        root = _org_call(c, "ListRoots", {}).json()["Roots"][0]
        _org_call(c, "EnablePolicyType", {"RootId": root["Id"], "PolicyType": "SERVICE_CONTROL_POLICY"})
        _org_call(c, "EnablePolicyType", {"RootId": root["Id"], "PolicyType": "RESOURCE_CONTROL_POLICY"})
        ou = _org_call(c, "CreateOrganizationalUnit", {"ParentId": root["Id"], "Name": "gov-ou-" + u}).json()["OrganizationalUnit"]
        made["ous"].append(ou["Id"])
        acct = _org_call(c, "CreateAccount", {"AccountName": "gov-acct-" + u, "Email": f"gov-{u}@example.com"})
        assert acct.status_code == 200, acct.text
        st = _org_call(c, "ListAccounts", {}).json()["Accounts"]
        member = next(a for a in st if a["Name"] == "gov-acct-" + u)["Id"]
        made["accounts"].append(member)
        assert _org_call(c, "MoveAccount", {"AccountId": member, "SourceParentId": root["Id"], "DestinationParentId": ou["Id"]}).status_code == 200
        deny = {"Version": "2012-10-17", "Statement": [{"Sid": "NoBucketDelete", "Effect": "Deny", "Action": "s3:DeleteBucket", "Resource": "*"}]}
        pol = _org_call(c, "CreatePolicy", {"Name": "gov-deny-" + u, "Description": "x", "Type": "SERVICE_CONTROL_POLICY", "Content": json.dumps(deny)}).json()["Policy"]["PolicySummary"]
        made["policies"].append(pol["Id"])
        # before attaching: the member account may delete buckets (FullAWSAccess at the root)
        chk = c.post("/api/iam/aws/governance/check", json={"account": member, "action": "s3:DeleteBucket"}).json()
        assert chk["allowed"] is True
        assert _org_call(c, "AttachPolicy", {"PolicyId": pol["Id"], "TargetId": ou["Id"]}).status_code == 200
        made["attach"].append((pol["Id"], ou["Id"]))
        chk = c.post("/api/iam/aws/governance/check", json={"account": member, "action": "s3:DeleteBucket"}).json()
        assert chk["allowed"] is False and chk["reason"] == "explicit_deny" and chk["matched"][0]["source"] == "scp"
        assert c.post("/api/iam/aws/governance/check", json={"account": member, "action": "s3:GetObject"}).json()["allowed"] is True
        eff = c.get(f"/api/iam/aws/governance/effective?account={member}").json()
        assert [l["node"] for l in eff["scp"]] == [root["Id"], ou["Id"], member]
        assert any(d["policy"] == "gov-deny-" + u and d["nodeName"] == "gov-ou-" + u for d in eff["denyStatements"])
        assert [p["id"] for p in eff["path"]] == [root["Id"], ou["Id"], member]
        tree = c.get("/api/iam/aws/governance/organization").json()
        node = next(n for n in tree["nodes"] if n["id"] == ou["Id"])
        assert [p["name"] for p in node["policies"]] == ["FullAWSAccess", "RCPFullAWSAccess", "gov-deny-" + u] or \
            {"FullAWSAccess", "gov-deny-" + u} <= {p["name"] for p in node["policies"]}      # AWS attaches the default Allow to every new OU
        # the management account is exempt (as in AWS)
        mgmt = tree["organization"]["managementAccountId"]
        assert c.post("/api/iam/aws/governance/check", json={"account": mgmt, "action": "s3:DeleteBucket"}).json()["allowed"] is True
        # detach: allowed again (FullAWSAccess is still attached, so the last-SCP rule is satisfied)
        assert _org_call(c, "DetachPolicy", {"PolicyId": pol["Id"], "TargetId": ou["Id"]}).status_code == 200
        made["attach"].pop()
        assert c.post("/api/iam/aws/governance/check", json={"account": member, "action": "s3:DeleteBucket"}).json()["allowed"] is True
        # RCP: deny on the resource side for the account
        rdeny = {"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Principal": "*", "Action": "s3:*", "Resource": "*", "Condition": {"Bool": {"aws:SecureTransport": "false"}}}]}
        rp_ = _org_call(c, "CreatePolicy", {"Name": "gov-rcp-" + u, "Description": "x", "Type": "RESOURCE_CONTROL_POLICY", "Content": json.dumps(rdeny)}).json()["Policy"]["PolicySummary"]
        made["policies"].append(rp_["Id"])
        assert _org_call(c, "AttachPolicy", {"PolicyId": rp_["Id"], "TargetId": ou["Id"]}).status_code == 200
        made["attach"].append((rp_["Id"], ou["Id"]))
        ok = c.post("/api/iam/aws/governance/check", json={"account": member, "action": "s3:GetObject", "resource": "arn:aws:s3:::x/y", "context": {"aws:SecureTransport": "true"}}).json()
        bad = c.post("/api/iam/aws/governance/check", json={"account": member, "action": "s3:GetObject", "resource": "arn:aws:s3:::x/y", "context": {"aws:SecureTransport": "false"}}).json()
        assert ok["allowed"] is True and bad["allowed"] is False and bad["matched"][0]["source"] == "rcp", (ok, bad)
    finally:
        for pid, tid in made["attach"]:
            _org_call(c, "DetachPolicy", {"PolicyId": pid, "TargetId": tid})
        for pid in made["policies"]:
            _org_call(c, "DeletePolicy", {"PolicyId": pid})
        for a in made["accounts"]:
            _org_call(c, "RemoveAccountFromOrganization", {"AccountId": a})
        for o in made["ous"]:
            _org_call(c, "DeleteOrganizationalUnit", {"OrganizationalUnitId": o})


def test_scp_denies_a_live_signed_request_when_applied_to_the_management_account(client):
    c, u = client, uuid.uuid4().hex[:6]
    bucket, made_org = "gov-scp-" + u, False
    pid = None
    try:
        if _org_call(c, "DescribeOrganization", {}).status_code != 200:
            assert _org_call(c, "CreateOrganization", {"FeatureSet": "ALL"}).status_code == 200
            made_org = True
        root = _org_call(c, "ListRoots", {}).json()["Roots"][0]
        _org_call(c, "EnablePolicyType", {"RootId": root["Id"], "PolicyType": "SERVICE_CONTROL_POLICY"})
        assert _s3(c, "PUT", f"/{bucket}").status_code == 200
        pol = {"Version": "2012-10-17", "Statement": [{"Sid": "NoDelete", "Effect": "Deny", "Action": "s3:DeleteBucket", "Resource": "*"}]}
        pid = _org_call(c, "CreatePolicy", {"Name": "gov-live-" + u, "Description": "", "Type": "SERVICE_CONTROL_POLICY", "Content": json.dumps(pol)}).json()["Policy"]["PolicySummary"]["Id"]
        assert _org_call(c, "AttachPolicy", {"PolicyId": pid, "TargetId": root["Id"]}).status_code == 200
        assert c.put("/api/iam/aws/enforcement", json={"space": "enforce"}).status_code == 200
        # real AWS: the management account is never restricted by SCPs -> the delete goes through the gate
        assert c.post("/api/iam/aws/governance/settings", json={"scpAppliesToManagement": False}).status_code == 200
        den_before = c.request("DELETE", f"/{bucket}/nonexistent", headers={"Authorization": _hdr("s3"), "X-Amz-Date": "20261123T000000Z"})
        assert den_before.status_code != 403, den_before.text
        # Vyomi lab opt-in: SCPs apply to the single account's principals
        assert c.post("/api/iam/aws/governance/settings", json={"scpAppliesToManagement": True}).json()["scpAppliesToManagement"] is True
        res = c.request("DELETE", f"/{bucket}", headers={"Authorization": _hdr("s3"), "X-Amz-Date": "20261123T000000Z"})
        assert res.status_code == 403 and "explicit deny in a service control" in res.text, res.text
        assert _s3(c, "GET", f"/{bucket}?location").status_code == 200                      # everything else is still allowed
    finally:
        c.post("/api/iam/aws/governance/settings", json={"scpAppliesToManagement": False})
        c.put("/api/iam/aws/enforcement", json={"space": "off"})
        if pid:
            _org_call(c, "DetachPolicy", {"PolicyId": pid, "TargetId": root["Id"]})
            _org_call(c, "DeletePolicy", {"PolicyId": pid})
        _s3(c, "DELETE", f"/{bucket}")
