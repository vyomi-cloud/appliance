"""IAM simulate / analyze APIs over the faithful engine (WP simulate-analyze).

Unit layer: the pure modules (core/iam_engine/analyze_{aws,gcp,azure}.py, access_analyzer.py, analyze_wire.py) with hand-built engine
state. Server layer: the REAL appliance app (server.py middleware + stores), one native call per cloud plus the AWS IAM Query actions.
Nano runs the same modules in a browser: wasm/ui-tests/iam/iam-analyze-e2e.mjs."""
import base64, json, os, re, sys, uuid
import xml.etree.ElementTree as ET

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")

from core import iam_core as ic                                              # noqa: E402
from core.iam_engine import (access_analyzer as AA, analyze_aws, analyze_azure, analyze_gcp, analyze_wire, aws_eval,   # noqa: E402
                             azure_eval, gcp_eval)
from core.iam_store import InMemoryIamStore                                  # noqa: E402

NS = {"i": "https://iam.amazonaws.com/doc/2010-05-08/"}


# ====================================================================== AWS: SimulatePrincipalPolicy / SimulateCustomPolicy
def _store():
    st = InMemoryIamStore()
    return st, (lambda action, **p: ic.dispatch(st, dict(p, Action=action)))


def _results(resp):
    root = ET.fromstring(resp.body)
    out = []
    for m in root.iterfind(".//i:EvaluationResults/i:member", NS):
        g = lambda t: (m.find("i:" + t, NS).text if m.find("i:" + t, NS) is not None else None)
        out.append({"action": g("EvalActionName"), "resource": g("EvalResourceName"), "decision": g("EvalDecision"),
                    "matched": [{"id": s.find("i:SourcePolicyId", NS).text, "type": s.find("i:SourcePolicyType", NS).text,
                                 "start": (int(s.find("i:StartPosition/i:Line", NS).text), int(s.find("i:StartPosition/i:Column", NS).text))
                                 if s.find("i:StartPosition", NS) is not None else None}
                                for s in m.iterfind("i:MatchedStatements/i:member", NS)],
                    "missing": [x.text for x in m.iterfind("i:MissingContextValues/i:member", NS)],
                    "org": g("OrganizationsDecisionDetail/i:AllowedByOrganizations") if m.find("i:OrganizationsDecisionDetail", NS) is not None else None,
                    "boundary": m.find("i:PermissionsBoundaryDecisionDetail/i:AllowedByPermissionsBoundary", NS).text
                    if m.find("i:PermissionsBoundaryDecisionDetail", NS) is not None else None})
    return out


def test_simulate_principal_policy_decisions_matched_statements_and_positions():
    st, iam = _store()
    iam("CreateUser", UserName="bob")
    pol = {"Version": "2012-10-17", "Statement": [
        {"Sid": "ReadAll", "Effect": "Allow", "Action": "s3:Get*", "Resource": "*"},
        {"Sid": "NoSecret", "Effect": "Deny", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::secret/*"}]}
    iam("PutUserPolicy", UserName="bob", PolicyName="p", PolicyDocument=json.dumps(pol))
    arn = f"arn:aws:iam::{st.account_id}:user/bob"
    r = _results(iam("SimulatePrincipalPolicy", PolicySourceArn=arn, **{
        "ActionNames.member.1": "s3:GetObject", "ActionNames.member.2": "s3:PutObject",
        "ResourceArns.member.1": "arn:aws:s3:::secret/x", "ResourceArns.member.2": "arn:aws:s3:::open/x"}))
    by = {(x["action"], x["resource"]): x for x in r}
    assert by[("s3:GetObject", "arn:aws:s3:::open/x")]["decision"] == "allowed"
    assert by[("s3:GetObject", "arn:aws:s3:::secret/x")]["decision"] == "explicitDeny"
    assert by[("s3:PutObject", "arn:aws:s3:::open/x")]["decision"] == "implicitDeny"
    allow = by[("s3:GetObject", "arn:aws:s3:::open/x")]["matched"]
    deny = by[("s3:GetObject", "arn:aws:s3:::secret/x")]["matched"]
    assert allow[0]["id"] == "p" and allow[0]["type"] == "user" and deny[0]["id"] == "p"
    assert allow[0]["start"][0] < deny[0]["start"][0] and allow[0]["start"][0] > 1          # positions come from the statement spans
    assert by[("s3:PutObject", "arn:aws:s3:::open/x")]["matched"] == []
    assert "OrganizationsDecisionDetail" not in iam("SimulatePrincipalPolicy", PolicySourceArn=arn, **{"ActionNames.member.1": "s3:GetObject"}).body
    ghost = iam("SimulatePrincipalPolicy", PolicySourceArn=f"arn:aws:iam::{st.account_id}:user/ghost", **{"ActionNames.member.1": "s3:GetObject"})
    assert ghost.status == 404 and "NoSuchEntity" in ghost.body


def test_simulate_context_entries_missing_context_boundary_and_inputs():
    st, iam = _store()
    iam("CreateUser", UserName="amy")
    pol = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "ec2:*", "Resource": "*",
                                                    "Condition": {"Bool": {"aws:MultiFactorAuthPresent": "true"}, "IpAddress": {"aws:SourceIp": "10.0.0.0/8"}}}]}
    iam("PutUserPolicy", UserName="amy", PolicyName="mfa", PolicyDocument=json.dumps(pol))
    arn = f"arn:aws:iam::{st.account_id}:user/amy"
    base = {"PolicySourceArn": arn, "ActionNames.member.1": "ec2:StartInstances"}
    r = _results(iam("SimulatePrincipalPolicy", **base))[0]
    assert r["decision"] == "implicitDeny" and "aws:SourceIp" in r["missing"]                  # key referenced but not supplied
    ok = _results(iam("SimulatePrincipalPolicy", **base, **{
        "ContextEntries.member.1.ContextKeyName": "aws:MultiFactorAuthPresent", "ContextEntries.member.1.ContextKeyType": "boolean",
        "ContextEntries.member.1.ContextKeyValues.member.1": "true",
        "ContextEntries.member.2.ContextKeyName": "aws:SourceIp", "ContextEntries.member.2.ContextKeyType": "ip",
        "ContextEntries.member.2.ContextKeyValues.member.1": "10.1.2.3"}))[0]
    assert ok["decision"] == "allowed" and ok["missing"] == []
    # a permissions boundary (via PermissionsBoundaryPolicyInputList) that does not allow ec2 -> boundary detail is false, decision implicit deny
    bnd = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]})
    cut = _results(iam("SimulatePrincipalPolicy", **base, **{
        "ContextEntries.member.1.ContextKeyName": "aws:MultiFactorAuthPresent", "ContextEntries.member.1.ContextKeyValues.member.1": "true",
        "ContextEntries.member.2.ContextKeyName": "aws:SourceIp", "ContextEntries.member.2.ContextKeyValues.member.1": "10.1.2.3",
        "PermissionsBoundaryPolicyInputList.member.1": bnd}))[0]
    assert cut["decision"] == "implicitDeny" and cut["boundary"] == "false"
    # PolicyInputList adds identity policies; the matched statement names PolicyInputList.1
    extra = json.dumps({"Version": "2012-10-17", "Statement": [{"Sid": "x", "Effect": "Allow", "Action": "sqs:SendMessage", "Resource": "*"}]})
    r2 = _results(iam("SimulatePrincipalPolicy", PolicySourceArn=arn, **{"ActionNames.member.1": "sqs:SendMessage", "PolicyInputList.member.1": extra}))[0]
    assert r2["decision"] == "allowed" and r2["matched"][0]["id"] == "PolicyInputList.1"


def test_simulate_resource_policy_scp_and_group():
    st, iam = _store()
    iam("CreateUser", UserName="gil")
    iam("CreateGroup", GroupName="devs")
    iam("AddUserToGroup", GroupName="devs", UserName="gil")
    iam("PutGroupPolicy", GroupName="devs", PolicyName="g", PolicyDocument=json.dumps(
        {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "sqs:*", "Resource": "*"}]}))
    arn = f"arn:aws:iam::{st.account_id}:user/gil"
    r = _results(iam("SimulatePrincipalPolicy", PolicySourceArn=arn, **{"ActionNames.member.1": "sqs:SendMessage", "ResourceArns.member.1": "arn:aws:sqs:us-east-1:%s:q" % st.account_id}))[0]
    assert r["decision"] == "allowed" and r["matched"][0]["type"] == "group"
    g = _results(iam("SimulatePrincipalPolicy", PolicySourceArn=f"arn:aws:iam::{st.account_id}:group/devs", **{"ActionNames.member.1": "sqs:SendMessage"}))[0]
    assert g["decision"] == "allowed"
    # an explicit Deny in the supplied resource policy beats the identity allow
    rp = json.dumps({"Version": "2012-10-17", "Statement": [{"Sid": "d", "Effect": "Deny", "Principal": "*", "Action": "sqs:SendMessage", "Resource": "*"}]})
    d = _results(iam("SimulatePrincipalPolicy", PolicySourceArn=arn, ResourcePolicy=rp, **{"ActionNames.member.1": "sqs:SendMessage"}))[0]
    assert d["decision"] == "explicitDeny" and d["matched"][0]["type"] == "resource"
    # the account's real resource policies are consulted too (injected through the host seam, as the live stores do)
    from core import iam_resource_policies as RP
    qarn = "arn:aws:sqs:us-east-1:%s:locked" % st.account_id
    RP.set_host_stores(lambda: {})
    try:
        state = dict(__import__("core.iam_state_adapters", fromlist=["x"]).aws_state(st), resource_policies=RP.ResourcePolicyMap({qarn: json.loads(rp)}))
        rr = analyze_aws.simulate({"arn": arn, "type": "user", "account": st.account_id}, ["sqs:SendMessage"], [qarn], None, state)[0]
        assert rr["EvalDecision"] == "explicitDeny"
    finally:
        RP.set_host_stores(None)
    # SCP / org detail
    pr = {"arn": arn, "type": "user", "account": st.account_id}
    scp = [[{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}]]
    state = dict(__import__("core.iam_state_adapters", fromlist=["x"]).aws_state(st), scps=scp)
    o = analyze_aws.simulate(pr, ["sqs:SendMessage"], ["*"], None, state)[0]
    assert o["EvalDecision"] == "implicitDeny" and o["OrganizationsDecisionDetail"] == {"AllowedByOrganizations": False}


def test_simulate_custom_policy_and_context_keys():
    st, iam = _store()
    pol = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::b",
                                                              "Condition": {"StringLike": {"s3:prefix": "home/${aws:username}/*"}}}]})
    r = _results(iam("SimulateCustomPolicy", **{"PolicyInputList.member.1": pol, "ActionNames.member.1": "s3:ListBucket", "ResourceArns.member.1": "arn:aws:s3:::b",
                                                "ContextEntries.member.1.ContextKeyName": "s3:prefix", "ContextEntries.member.1.ContextKeyValues.member.1": "home/zed/a",
                                                "ContextEntries.member.2.ContextKeyName": "aws:username", "ContextEntries.member.2.ContextKeyValues.member.1": "zed"}))[0]
    assert r["decision"] == "allowed" and r["matched"][0]["id"] == "PolicyInputList.1"
    miss = _results(iam("SimulateCustomPolicy", **{"PolicyInputList.member.1": pol, "ActionNames.member.1": "s3:ListBucket", "ResourceArns.member.1": "arn:aws:s3:::b"}))[0]
    assert miss["decision"] == "implicitDeny" and "s3:prefix" in miss["missing"]
    keys = [m.text for m in ET.fromstring(iam("GetContextKeysForCustomPolicy", **{"PolicyInputList.member.1": pol}).body).iterfind(".//i:ContextKeyNames/i:member", NS)]
    assert keys == ["s3:prefix", "aws:username"]
    iam("CreateUser", UserName="kay")
    iam("PutUserPolicy", UserName="kay", PolicyName="p", PolicyDocument=pol)
    pk = [m.text for m in ET.fromstring(iam("GetContextKeysForPrincipalPolicy", PolicySourceArn=f"arn:aws:iam::{st.account_id}:user/kay").body).iterfind(".//i:ContextKeyNames/i:member", NS)]
    assert pk == ["s3:prefix", "aws:username"]


# ====================================================================== AWS: Access Analyzer
def _aa_ctx(store, policies, audit=None):
    return {"store": store, "state": {"resource_policies": policies, "principals": {}}, "audit": audit or [], "region": "us-east-1", "now": "2026-11-25T00:00:00Z"}


def _call(ctx, method, path, body=None, query=None):
    r = AA.dispatch(method, path, query or {}, json.dumps(body).encode() if body is not None else b"", ctx)
    return r["status"], (json.loads(r["body"]) if r["body"] else None), r["headers"]


def test_access_analyzer_external_access_findings_from_resource_policies():
    st, _ = _store()
    acct = st.account_id
    pol = lambda principal, cond=None, act="s3:GetObject": {"Version": "2012-10-17", "Statement": [dict(
        {"Effect": "Allow", "Principal": principal, "Action": act, "Resource": "*"}, **({"Condition": cond} if cond else {}))]}
    policies = {
        "arn:aws:s3:::pub-bucket": pol("*"),
        "arn:aws:s3:::xacct-bucket": pol({"AWS": "arn:aws:iam::999999999999:root"}),
        "arn:aws:s3:::own-bucket": pol({"AWS": f"arn:aws:iam::{acct}:root"}),
        "arn:aws:s3:::locked-bucket": pol("*", {"StringEquals": {"aws:SourceAccount": acct}}),
        f"arn:aws:sqs:us-east-1:{acct}:q": pol({"AWS": "888888888888"}, act="sqs:SendMessage"),
        f"arn:aws:sns:us-east-1:{acct}:t": pol("*", {"StringEquals": {"AWS:SourceOwner": acct}}, "sns:Publish"),
        f"arn:aws:kms:us-east-1:{acct}:key/k1": pol({"AWS": "arn:aws:iam::777777777777:root"}, act="kms:Decrypt"),
        f"arn:aws:kms:us-east-1:{acct}:alias/dup": pol({"AWS": "arn:aws:iam::777777777777:root"}, act="kms:Decrypt"),
        f"arn:aws:lambda:us-east-1:{acct}:function:fn": pol({"Service": "s3.amazonaws.com"}, act="lambda:InvokeFunction"),
        f"arn:aws:secretsmanager:us-east-1:{acct}:secret:s-AbCdEf": pol({"AWS": "666666666666"}, act="secretsmanager:GetSecretValue"),
        f"arn:aws:secretsmanager:us-east-1:{acct}:secret:s": pol({"AWS": "666666666666"}, act="secretsmanager:GetSecretValue"),
    }
    st.roles["r"] = {"role_name": "r", "arn": f"arn:aws:iam::{acct}:role/r", "created": "2026-01-01T00:00:00.000Z",
                     "assume_role_policy_document": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::555555555555:root"}, "Action": "sts:AssumeRole"}]}}
    ctx = _aa_ctx(st, policies)
    s, out, _ = _call(ctx, "PUT", "/analyzer", {"analyzerName": "acct", "type": "ACCOUNT"})
    assert s == 200 and out["arn"].endswith(":analyzer/acct")
    assert _call(ctx, "PUT", "/analyzer", {"analyzerName": "acct", "type": "ACCOUNT"})[0] == 409
    s, out, _ = _call(ctx, "POST", "/finding", {"analyzerArn": out["arn"]})
    assert s == 200
    rows = {(f["resource"], list(f["principal"].values())[0]): f for f in out["findings"]}
    res_types = {f["resource"].split(":")[2] if not f["resource"].startswith("arn:aws:s3") else "s3": f["resourceType"] for f in out["findings"]}
    assert res_types == {"s3": "AWS::S3::Bucket", "sqs": "AWS::SQS::Queue", "kms": "AWS::KMS::Key", "secretsmanager": "AWS::SecretsManager::Secret", "iam": "AWS::IAM::Role"}
    assert rows[("arn:aws:s3:::pub-bucket", "*")]["isPublic"] is True
    assert rows[("arn:aws:s3:::xacct-bucket", "arn:aws:iam::999999999999:root")]["isPublic"] is False
    resources = {f["resource"] for f in out["findings"]}
    assert "arn:aws:s3:::own-bucket" not in resources and "arn:aws:s3:::locked-bucket" not in resources     # in-account / account-pinned: not external
    assert not any(":sns:" in r or ":lambda:" in r for r in resources)                                       # SourceOwner-pinned SNS, service principal
    assert not any(":alias/" in r for r in resources)                                                        # alias duplicate suppressed
    assert sum(":secret:" in r for r in resources) == 1                                                      # by-name duplicate suppressed
    assert f"arn:aws:iam::{acct}:role/r" in resources                                                        # trust policy naming another account
    # GetFinding + UpdateFindings (archive) round trip
    fid = rows[("arn:aws:s3:::pub-bucket", "*")]["id"]
    arn = f"arn:aws:access-analyzer:us-east-1:{acct}:analyzer/acct"
    s, one, _ = _call(ctx, "GET", f"/finding/{fid}", query={"analyzerArn": arn})
    assert s == 200 and one["finding"]["resource"] == "arn:aws:s3:::pub-bucket"
    s, v2, _ = _call(ctx, "GET", f"/findingv2/{fid}", query={"analyzerArn": arn})
    assert s == 200 and v2["findingDetails"][0]["externalAccessDetails"]["isPublic"] is True and v2["findingType"] == "ExternalAccess"
    assert _call(ctx, "PUT", "/finding", {"analyzerArn": arn, "ids": [fid], "status": "ARCHIVED"})[0] == 200
    s, act, _ = _call(ctx, "POST", "/finding", {"analyzerArn": arn, "filter": {"status": {"eq": ["ACTIVE"]}}})
    assert fid not in {f["id"] for f in act["findings"]}
    s, lst, _ = _call(ctx, "GET", "/analyzer")
    assert lst["analyzers"][0]["name"] == "acct" and _call(ctx, "DELETE", "/analyzer/acct")[0] == 200
    assert _call(ctx, "GET", "/analyzer/acct")[0] == 404


def test_access_analyzer_unused_access_from_activity_and_audit_ring():
    st, iam = _store()
    acct = st.account_id
    iam("CreateUser", UserName="old")
    iam("CreateUser", UserName="busy")
    for u in ("old", "busy"):
        st.users[u]["created"] = "2025-01-01T00:00:00.000Z"
        iam("PutUserPolicy", UserName=u, PolicyName="p", PolicyDocument=json.dumps(
            {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject", "sqs:SendMessage"], "Resource": "*"}]}))
    key = ET.fromstring(iam("CreateAccessKey", UserName="old").body).find(".//i:AccessKeyId", NS).text
    st.access_keys[key]["created"] = "2025-01-01T00:00:00.000Z"
    ring = [{"cloud": "aws", "principal": f"arn:aws:iam::{acct}:user/busy", "action": "s3:GetObject", "decision": "allow", "time": "2026-11-20T00:00:00Z"},
            {"cloud": "aws", "principal": f"arn:aws:iam::{acct}:user/busy", "action": "sqs:SendMessage", "decision": "deny", "time": "2026-11-21T00:00:00Z"}]
    from core import iam_state_adapters as ad
    ctx = {"store": st, "state": ad.aws_state(st), "audit": ring, "region": "us-east-1"}
    s, out, _ = _call(ctx, "PUT", "/analyzer", {"analyzerName": "unused", "type": "ACCOUNT_UNUSED_ACCESS", "configuration": {"unusedAccess": {"unusedAccessAge": 30}}})
    assert s == 200
    arn = out["arn"]
    s, out, _ = _call(ctx, "POST", "/findingv2", {"analyzerArn": arn})
    kinds = {(f["findingType"], f["resource"]) for f in out["findings"]}
    assert ("UnusedIAMUserAccessKey", key) in kinds
    unused_perm = {f["resource"] for f in out["findings"] if f["findingType"] == "UnusedPermission"}
    assert f"arn:aws:iam::{acct}:user/old" in unused_perm
    # busy used s3 (allowed in the ring) but its denied sqs call is not an access: sqs is the unused permission
    det = [f for f in out["findings"] if f["findingType"] == "UnusedPermission" and f["resource"].endswith("user/busy")]
    assert len(det) == 1
    s, d2, _ = _call(ctx, "GET", f"/findingv2/{det[0]['id']}", query={"analyzerArn": arn})
    assert d2["findingDetails"][0]["unusedPermissionDetails"]["serviceNamespace"] == "sqs"
    la = AA.last_accessed(ctx)
    assert "s3" in la[f"arn:aws:iam::{acct}:user/busy"] and "sqs" not in la[f"arn:aws:iam::{acct}:user/busy"]


def test_access_analyzer_last_accessed_over_the_audit_ring_in_iam_wire(monkeypatch):
    """GetServiceLastAccessedDetails reports a ROLE's services from the decision ring (the activity log only attributes IAM users)."""
    from core.iam_engine import audit
    st, iam = _store()
    iam("CreateRole", RoleName="svc", AssumeRolePolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": []}))
    role_arn = f"arn:aws:iam::{st.account_id}:role/svc"
    audit.default_log.record("aws", f"arn:aws:sts::{st.account_id}:assumed-role/svc/sess", "sqs:SendMessage", "*", "audit", "allow")
    try:
        job = ET.fromstring(iam("GenerateServiceLastAccessedDetails", Arn=role_arn).body).find(".//i:JobId", NS).text
        got = ET.fromstring(iam("GetServiceLastAccessedDetails", JobId=job).body)
        assert [x.text for x in got.iterfind(".//i:ServicesLastAccessed/i:member/i:ServiceNamespace", NS)] == ["sqs"]
    finally:
        audit.default_log.clear()


def _vp(doc, ptype="IDENTITY_POLICY"):
    st, _ = _store()
    s, out, _h = _call(_aa_ctx(st, {}), "POST", "/policy/validation", {"policyType": ptype, "policyDocument": json.dumps(doc, indent=2)})
    assert s == 200
    return out["findings"]


def test_validate_policy_issue_codes_and_locations():
    f = _vp({"Statement": [{"Effect": "Allow", "Action": ["s3:GetObjectXX", "s3:GetObject"], "Resource": "*"},
                           {"Effect": "Allow", "Action": "s3:GetObject"},
                           {"Effect": "Allow", "Action": "iam:PassRole", "Resource": "*"},
                           {"Effect": "Allow", "Action": "iam:*", "Resource": "*"}]})
    by = {}
    for x in f:
        by.setdefault(x["issueCode"], []).append(x)
    assert {"MISSING_VERSION", "INVALID_ACTION", "MISSING_RESOURCE", "PASS_ROLE_WITH_STAR_IN_RESOURCE", "PASS_ROLE_WITH_STAR_IN_ACTION_AND_RESOURCE"} <= set(by)
    inv = by["INVALID_ACTION"][0]
    assert inv["findingType"] == "ERROR" and "s3:GetObjectXX" in inv["findingDetails"]
    assert inv["locations"][0]["path"] == [{"value": "Statement"}, {"index": 0}, {"value": "Action"}, {"index": 0}]
    assert inv["locations"][0]["span"]["start"]["line"] >= 3
    assert by["PASS_ROLE_WITH_STAR_IN_RESOURCE"][0]["findingType"] == "SECURITY_WARNING"
    assert by["MISSING_VERSION"][0]["findingType"] == "SUGGESTION"
    assert by["MISSING_RESOURCE"][0]["locations"][0]["path"] == [{"value": "Statement"}, {"index": 1}]
    assert all(x["learnMoreLink"].startswith("https://docs.aws.amazon.com/IAM/") for x in f)
    assert _vp({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:Get*", "unknownsvc:Anything"], "Resource": "*"}]}) == []
    rp = _vp({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}]}, "RESOURCE_POLICY")
    assert [x["issueCode"] for x in rp] == ["MISSING_PRINCIPAL"]
    st, _ = _store()
    s, out, h = _call(_aa_ctx(st, {}), "POST", "/policy/validation", {"policyType": "IDENTITY_POLICY", "policyDocument": "{nope"})
    assert s == 400 and h["x-amzn-errortype"] == "ValidationException"


def test_check_no_new_access_and_check_access_not_granted():
    st, _ = _store()
    ctx = _aa_ctx(st, {})
    doc = lambda *stmts: json.dumps({"Version": "2012-10-17", "Statement": list(stmts)})
    allow = lambda act, res="*", **kw: dict({"Effect": "Allow", "Action": act, "Resource": res}, **kw)
    s, out, _ = _call(ctx, "POST", "/policy/check-no-new-access", {"newPolicyDocument": doc(allow("s3:GetObject", "arn:aws:s3:::b/x")),
                                                                    "existingPolicyDocument": doc(allow("s3:Get*", "arn:aws:s3:::b/*")), "policyType": "IDENTITY_POLICY"})
    assert s == 200 and out["result"] == "PASS" and out["reasons"] == []
    s, out, _ = _call(ctx, "POST", "/policy/check-no-new-access", {"newPolicyDocument": doc(allow(["s3:GetObject", "s3:PutObject"], "arn:aws:s3:::b/x")),
                                                                    "existingPolicyDocument": doc(allow("s3:Get*", "arn:aws:s3:::b/*")), "policyType": "IDENTITY_POLICY"})
    assert out["result"] == "FAIL" and out["reasons"][0]["statementIndex"] == 0 and "s3:PutObject" in out["reasons"][0]["description"]
    # broader resource is new access; an existing Deny cancels what the new policy would add
    s, out, _ = _call(ctx, "POST", "/policy/check-no-new-access", {"newPolicyDocument": doc(allow("s3:GetObject", "*")),
                                                                    "existingPolicyDocument": doc(allow("s3:GetObject", "arn:aws:s3:::b/*")), "policyType": "IDENTITY_POLICY"})
    assert out["result"] == "FAIL"
    cond = {"StringEquals": {"aws:RequestedRegion": "eu-west-1"}}
    s, out, _ = _call(ctx, "POST", "/policy/check-no-new-access", {"newPolicyDocument": doc(allow("s3:GetObject", "*", Condition=cond)),
                                                                    "existingPolicyDocument": doc(allow("s3:Get*", "*", Condition=cond)), "policyType": "IDENTITY_POLICY"})
    assert out["result"] == "PASS"          # same condition on both sides: covered
    # resource policy: a new external principal is new access
    rp = lambda p: doc({"Effect": "Allow", "Principal": p, "Action": "s3:GetObject", "Resource": "*"})
    assert _call(ctx, "POST", "/policy/check-no-new-access", {"newPolicyDocument": rp("*"), "existingPolicyDocument": rp({"AWS": "111122223333"}), "policyType": "RESOURCE_POLICY"})[1]["result"] == "FAIL"
    assert _call(ctx, "POST", "/policy/check-no-new-access", {"newPolicyDocument": rp({"AWS": "111122223333"}), "existingPolicyDocument": rp("*"), "policyType": "RESOURCE_POLICY"})[1]["result"] == "PASS"
    s, out, _ = _call(ctx, "POST", "/policy/check-access-not-granted", {"policyDocument": doc(allow("s3:Get*", "arn:aws:s3:::b/*")),
                                                                         "access": [{"actions": ["s3:DeleteObject"]}], "policyType": "IDENTITY_POLICY"})
    assert out["result"] == "PASS"
    s, out, _ = _call(ctx, "POST", "/policy/check-access-not-granted", {"policyDocument": doc(allow("s3:Get*", "arn:aws:s3:::b/*")),
                                                                         "access": [{"actions": ["s3:GetObject"], "resources": ["arn:aws:s3:::b/k"]}], "policyType": "IDENTITY_POLICY"})
    assert out["result"] == "FAIL" and out["reasons"][0]["statementIndex"] == 0


# ====================================================================== GCP: troubleshooter + analyzeIamPolicy
PROJ = "projects/p1"


def _gstate(bindings=None, deny=None, pab=None):
    st = {"cloud": "gcp", "allow_policies": {PROJ: {"etag": "BwX", "version": 3, "bindings": bindings or []}}, "deny_policies": {},
          "custom_roles": {}, "hierarchy": {"projects/p1": "folders/7", "folders/7": "organizations/1"}, "service_accounts": {}}
    if deny:
        st["deny_policies"][PROJ] = [deny]
    if pab:
        st.update(pab)
    return st


def _tup(member="user:ann@example.com", perm="storage.objects.get", res="//storage.googleapis.com/projects/_/buckets/b1/objects/o", **kw):
    return dict({"principal": member, "fullResourceName": res, "permission": perm}, **kw)


def _gcp_state_with_hier(**kw):
    st = _gstate(**kw)
    st["hierarchy"]["projects/_/buckets/b1"] = PROJ
    return st


def test_troubleshooter_v1_granted_not_granted_and_per_binding_relevance():
    st = _gcp_state_with_hier(bindings=[
        {"role": "roles/storage.objectViewer", "members": ["user:ann@example.com", "user:other@example.com"]},
        {"role": "roles/storage.objectCreator", "members": ["user:ann@example.com"]},
        {"role": "roles/storage.objectViewer", "members": ["user:zoe@example.com"]}])
    out = analyze_gcp.troubleshoot_v1(_tup(), st)
    assert out["access"] == "GRANTED"
    pol = next(p for p in out["explainedPolicies"] if p["fullResourceName"].endswith("projects/p1"))
    b0, b1, b2 = pol["bindingExplanations"]
    assert (b0["access"], b0["rolePermission"], b0["relevance"]) == ("GRANTED", "ROLE_PERMISSION_INCLUDED", "HEURISTIC_RELEVANCE_HIGH")
    assert b0["memberships"]["user:ann@example.com"]["membership"] == "MEMBERSHIP_INCLUDED"
    assert b0["memberships"]["user:other@example.com"]["membership"] == "MEMBERSHIP_NOT_INCLUDED"
    assert (b1["access"], b1["rolePermission"]) == ("NOT_GRANTED", "ROLE_PERMISSION_NOT_INCLUDED")
    assert (b2["access"], b2["rolePermission"], b2["relevance"]) == ("NOT_GRANTED", "ROLE_PERMISSION_INCLUDED", "HEURISTIC_RELEVANCE_NORMAL")
    assert pol["access"] == "GRANTED" and pol["policy"]["bindings"][0]["role"] == "roles/storage.objectViewer"
    none = analyze_gcp.troubleshoot_v1(_tup(member="user:nobody@example.com"), st)
    assert none["access"] == "NOT_GRANTED"
    with pytest.raises(analyze_gcp.GcpError) as e:
        analyze_gcp.troubleshoot_v1(_tup(perm="storage.objects.nonsense"), st)
    assert e.value.status == 400
    # a bare email is accepted like the API does
    assert analyze_gcp.troubleshoot_v1(_tup(member="ann@example.com"), st)["access"] == "GRANTED"


def test_troubleshooter_conditions_true_false_unknown():
    cond = lambda expr: {"title": "c", "expression": expr}
    st = _gcp_state_with_hier(bindings=[
        {"role": "roles/storage.objectViewer", "members": ["user:ann@example.com"], "condition": cond('resource.name.startsWith("projects/_/buckets/b1/")')}])
    assert analyze_gcp.troubleshoot_v1(_tup(), st)["access"] == "GRANTED"
    st["allow_policies"][PROJ]["bindings"][0]["condition"] = cond('resource.name.startsWith("projects/_/buckets/other/")')
    out = analyze_gcp.troubleshoot_v1(_tup(), st)
    b = out["explainedPolicies"][0]["bindingExplanations"][0]
    assert out["access"] == "NOT_GRANTED" and b["conditionExplanation"]["value"] is False
    st["allow_policies"][PROJ]["bindings"][0]["condition"] = cond("request.auth.claims.foo == 'x'")          # not evaluable offline
    out = analyze_gcp.troubleshoot_v1(_tup(), st)
    assert out["access"] == "UNKNOWN_CONDITIONAL" and out["explainedPolicies"][0]["bindingExplanations"][0]["conditionExplanation"]["errors"]
    st["allow_policies"][PROJ]["bindings"][0]["condition"] = cond('request.time < timestamp("2030-01-01T00:00:00Z")')
    assert analyze_gcp.troubleshoot_v1(_tup(conditionContext={"request": {"receiveTime": "2026-11-25T00:00:00Z"}}), st)["access"] == "GRANTED"
    assert analyze_gcp.troubleshoot_v1(_tup(conditionContext={"request": {"receiveTime": "2031-01-01T00:00:00Z"}}), st)["access"] == "NOT_GRANTED"


def test_troubleshooter_v3_deny_pab_and_agreement_with_the_engine():
    base = [{"role": "roles/storage.objectViewer", "members": ["user:ann@example.com"]}]
    deny = {"name": "policies/d1", "rules": [{"denyRule": {"deniedPrincipals": ["principalSet://goog/public:all"],
                                                         "deniedPermissions": ["storage.googleapis.com/objects.get"],
                                                         "exceptionPrincipals": ["user:vip@example.com"]}}]}
    st = _gcp_state_with_hier(bindings=base + [{"role": "roles/storage.objectViewer", "members": ["user:vip@example.com"]}], deny=deny)
    v = analyze_gcp.troubleshoot_v3(_tup(), st)
    assert v["overallAccessState"] == "CANNOT_ACCESS"
    assert v["allowPolicyExplanation"]["allowAccessState"] == "ALLOW_ACCESS_STATE_GRANTED"
    assert v["denyPolicyExplanation"]["denyAccessState"] == "DENY_ACCESS_STATE_DENIED"
    rule = v["denyPolicyExplanation"]["explainedResources"][0]["explainedPolicies"][0]["denyRuleExplanations"][0]
    assert rule["combinedDeniedPermission"]["permissionMatchingState"].endswith("_MATCHED") and rule["combinedExceptionPrincipal"]["membership"] == "MEMBERSHIP_NOT_INCLUDED"
    vip = analyze_gcp.troubleshoot_v3(_tup(member="user:vip@example.com"), st)
    assert vip["overallAccessState"] == "CAN_ACCESS" and vip["denyPolicyExplanation"]["denyAccessState"] == "DENY_ACCESS_STATE_NOT_DENIED"
    # principal access boundary that excludes the bucket's project
    pab = {"pab_policies": {"pab1": {"rules": [{"effect": "ALLOW", "resources": ["//cloudresourcemanager.googleapis.com/projects/other"]}]}},
           "pab_bindings": [{"target": {"principalSet": "user:ann@example.com"}, "policy": "pab1"}]}
    st2 = _gcp_state_with_hier(bindings=base, pab=pab)
    v2 = analyze_gcp.troubleshoot_v3(_tup(), st2)
    assert v2["overallAccessState"] == "CANNOT_ACCESS" and v2["pabPolicyExplanation"]["accessState"] == "PAB_ACCESS_STATE_NOT_ALLOWED"
    assert analyze_gcp.troubleshoot_v1(_tup(), st2)["access"] == "GRANTED"          # v1 evaluates allow policies only, like the real v1
    # the explanation agrees with the engine on a matrix of principals x permissions
    for s in (st, st2, _gcp_state_with_hier(bindings=base)):
        for who in ("user:ann@example.com", "user:vip@example.com", "user:nobody@example.com"):
            for perm in ("storage.objects.get", "storage.objects.create", "storage.buckets.get"):
                eng = gcp_eval.evaluate({"principal": {"member": who}, "action": perm, "resource": "//storage.googleapis.com/projects/_/buckets/b1/objects/o"}, s)["allowed"]
                got = analyze_gcp.troubleshoot_v3(_tup(member=who, perm=perm), s)["overallAccessState"]
                assert (got == "CAN_ACCESS") == eng, (who, perm, got, eng)


def test_analyze_iam_policy_scope_identity_resource_and_conditions():
    st = _gcp_state_with_hier(bindings=[
        {"role": "roles/storage.objectViewer", "members": ["user:ann@example.com", "group:devs@example.com"]},
        {"role": "roles/viewer", "members": ["user:ann@example.com"], "condition": {"title": "t", "expression": 'request.time < timestamp("2040-01-01T00:00:00Z")'}},
        {"role": "roles/storage.admin", "members": ["user:bob@example.com"]}])
    st["groups"] = {"group:devs@example.com": ["user:cy@example.com"]}
    q = "analysisQuery."
    out = analyze_gcp.analyze_iam_policy(PROJ, {q + "identitySelector.identity": "user:ann@example.com"}, st)
    res = out["mainAnalysis"]["analysisResults"]
    assert {r["iamBinding"]["role"] for r in res} == {"roles/storage.objectViewer", "roles/viewer"}
    assert all(r["attachedResourceFullName"] == "//cloudresourcemanager.googleapis.com/projects/p1" and r["fullyExplored"] for r in res)
    cond = next(r for r in res if r["iamBinding"]["role"] == "roles/viewer")
    assert cond["accessControlLists"][0]["conditionEvaluation"]["evaluationValue"] == "CONDITIONAL"       # time-dependent, no accessTime
    assert cond["identityList"]["identities"] == [{"name": "user:ann@example.com", "analysisState": {"code": "OK"}}]
    # permission selector: only roles that contain it; access entries are permissions
    perm = analyze_gcp.analyze_iam_policy(PROJ, {q + "accessSelector.permissions": ["storage.objects.delete"]}, st)["mainAnalysis"]["analysisResults"]
    assert [r["iamBinding"]["role"] for r in perm] == ["roles/storage.admin"]
    assert perm[0]["accessControlLists"][0]["accesses"][0] == {"permission": "storage.objects.delete", "analysisState": {"code": "OK"}}
    # expandGroups: cy only has access through the group
    assert analyze_gcp.analyze_iam_policy(PROJ, {q + "identitySelector.identity": "user:cy@example.com"}, st)["mainAnalysis"]["analysisResults"] == []
    ex = analyze_gcp.analyze_iam_policy(PROJ, {q + "identitySelector.identity": "user:cy@example.com", q + "options.expandGroups": "true"}, st)["mainAnalysis"]["analysisResults"]
    assert [r["iamBinding"]["role"] for r in ex] == ["roles/storage.objectViewer"]
    # a different scope sees nothing; a folder scope contains the project's policy through the hierarchy
    assert analyze_gcp.analyze_iam_policy("projects/other", {q + "identitySelector.identity": "user:ann@example.com"}, st)["mainAnalysis"]["analysisResults"] == []
    assert len(analyze_gcp.analyze_iam_policy("folders/7", {q + "identitySelector.identity": "user:ann@example.com"}, st)["mainAnalysis"]["analysisResults"]) == 2
    with pytest.raises(analyze_gcp.GcpError):
        analyze_gcp.analyze_iam_policy(PROJ, {}, st)


# ====================================================================== Azure
SUB_ = "/subscriptions/s1"
RG = SUB_ + "/resourceGroups/rg1"
SA = RG + "/providers/Microsoft.Storage/storageAccounts/sa1"
READER, CONTRIB, OWNER = "acdd72a7-3385-48ef-bd42-f606fba81ae7", "b24988ac-6180-42a0-ab88-20f7382dd24c", "8e3af657-a8ff-443c-a75c-2fe8c4bcb635"


def _astate():
    ra = lambda i, who, role, scope, **kw: dict({"id": f"{scope}/providers/Microsoft.Authorization/roleAssignments/{i}", "principal_id": who,
                                                  "role_definition_id": f"{SUB_}/providers/Microsoft.Authorization/roleDefinitions/{role}", "scope": scope}, **kw)
    return {"cloud": "azure", "role_assignments": [ra("a1", "u-reader", READER, RG), ra("a2", "u-contrib", CONTRIB, SUB_), ra("a3", "g-ops", OWNER, SA),
                                                   ra("a4", "u-elig", CONTRIB, RG, assignment_type="eligible")],
            "role_definitions": [], "deny_assignments": [{"id": SA + "/providers/Microsoft.Authorization/denyAssignments/d1", "scope": SA,
                                                          "principals": [{"id": "u-contrib", "type": "User"}], "permissions": [{"actions": ["Microsoft.Storage/storageAccounts/delete"]}]}],
            "groups": {"g-ops": ["u-grp"]}, "data_scopes": {}, "storage_accounts": {}, "management_groups": {}, "subscriptions": {}}


def test_azure_check_access_native_shape_with_role_and_deny_assignments():
    st = _astate()
    body = lambda who, *acts, res=SA: {"Subject": {"Attributes": {"ObjectId": who, "xms-pasrp-retrievegroupmemberships": "true"}},
                                      "Actions": [{"Id": a, "IsDataAction": False} for a in acts], "Resource": {"Id": res}}
    out = analyze_azure.check_access(body("u-reader", "Microsoft.Storage/storageAccounts/read", "Microsoft.Storage/storageAccounts/write"), st)
    assert isinstance(out, list) and [o["accessDecision"] for o in out] == ["Allowed", "NotAllowed"]
    ra = out[0]["roleAssignment"]
    assert ra["scope"] == RG and ra["roleDefinitionId"].endswith("/roleDefinitions/" + READER) and ra["principalId"] == "u-reader" and out[1]["roleAssignment"] is None
    assert out[0]["timeToLiveInMs"] == 300000 and out[0]["isDataAction"] is False
    d = analyze_azure.check_access(body("u-contrib", "Microsoft.Storage/storageAccounts/delete", "Microsoft.Storage/storageAccounts/read"), st)
    assert [o["accessDecision"] for o in d] == ["NotAllowed", "Allowed"] and d[0]["denyAssignment"]["id"].endswith("/denyAssignments/d1")
    g = analyze_azure.check_access(body("u-grp", "Microsoft.Storage/storageAccounts/write"), st)       # via group g-ops (Owner on the account)
    assert g[0]["accessDecision"] == "Allowed"
    for o, a in zip(out, ("Microsoft.Storage/storageAccounts/read", "Microsoft.Storage/storageAccounts/write")):
        assert o["accessDecision"] == ("Allowed" if azure_eval.check_access(st, "u-reader", a, SA)["accessDecision"] == "Allowed" else "NotAllowed")
    with pytest.raises(analyze_azure.AzError):
        analyze_azure.check_access({"Actions": []}, st)


def test_azure_effective_permissions_role_assignment_filters_and_schedules():
    st = _astate()
    p = analyze_azure.effective_permissions(SA, {"object_id": "u-reader", "type": "user"}, st)["value"]
    assert len(p) == 1 and p[0]["actions"] == ["*/read"] and set(p[0]) == {"actions", "notActions", "dataActions", "notDataActions"}
    assert analyze_azure.effective_permissions(SA, {"object_id": "u-nobody", "type": "user"}, st)["value"] == []
    root = analyze_azure.effective_permissions(SA, {"object_id": "root", "type": "root"}, st)["value"]
    assert root[0]["actions"] == ["*"]
    contrib = analyze_azure.effective_permissions(SA, {"object_id": "u-contrib"}, st)["value"][0]
    assert "Microsoft.Authorization/*/Delete" in contrib["notActions"]
    at = analyze_azure.role_assignments(SA, "atScope()", st)["value"]
    ids = {x["name"] for x in at}
    assert "a3" in ids and "a2" in ids and "a1" in ids                       # at the scope and ABOVE (rg + subscription)
    below = {x["name"] for x in analyze_azure.role_assignments(SUB_, "principalId eq 'u-reader'", st)["value"]}
    assert below == {"a1"}                                                  # principal filter reaches the assignments below the scope
    assert {x["name"] for x in analyze_azure.role_assignments(SA, "assignedTo('u-grp')", st)["value"]} == {"a3"}
    item = analyze_azure.role_assignments(SA, "atScope()", st)["value"][0]
    assert item["type"] == "Microsoft.Authorization/roleAssignments" and {"roleDefinitionId", "principalId", "scope"} <= set(item["properties"])
    with pytest.raises(analyze_azure.AzError):
        analyze_azure.role_assignments(SA, "roleDefinitionId eq 'x'", st)
    el = analyze_azure.schedules("roleEligibilityScheduleInstances", RG, "atScope()", st)["value"]
    assert [x["name"] for x in el] == ["a4"] and el[0]["type"] == "Microsoft.Authorization/roleEligibilityScheduleInstances"
    assert el[0]["properties"]["status"] == "Provisioned" and el[0]["properties"]["memberType"] == "Direct"
    act = analyze_azure.schedules("roleAssignmentScheduleInstances", RG, "atScope()", st)["value"]
    assert {x["name"] for x in act} == {"a1", "a2"} and act[0]["properties"]["assignmentType"] == "Activated"


def test_wire_match_is_narrow():
    m = analyze_wire.match
    sig = {"authorization": "AWS4-HMAC-SHA256 Credential=AK/20261125/us-east-1/access-analyzer/aws4_request, SignedHeaders=host, Signature=0"}
    assert m("POST", "/policy/validation", {}, sig, b"{}")[:2] == ("aws", "accessanalyzer")
    assert m("POST", "/policy/validation", {}, {}, b"{}") is None                                       # no access-analyzer scope: an S3 bucket path
    assert m("GET", "/finding/abc", {}, {"authorization": sig["authorization"].replace("access-analyzer", "s3")}, b"") is None
    assert m("POST", "/v1/iam:troubleshoot", {}, {}, b"{}") == ("gcp", "troubleshoot", "v1")
    assert m("POST", "/v3/iam:troubleshoot", {}, {}, b"{}")[2] == "v3"
    assert m("GET", "/v1/projects/p:analyzeIamPolicy", {}, {}, b"") == ("gcp", "analyze", "projects/p")
    ca = f"{SA}/providers/Microsoft.Authorization/checkAccess"
    assert m("POST", ca, {}, {}, json.dumps({"Subject": {}, "Actions": [], "Resource": {}}).encode())[:2] == ("azure", "checkAccess")
    assert m("POST", ca, {}, {}, json.dumps({"principalId": "x", "actions": []}).encode()) is None      # legacy lower-case body: the store's own handler
    ra = f"{SA}/providers/Microsoft.Authorization/roleAssignments"
    assert m("GET", ra, {"$filter": "atScope()"}, {}, b"")[:2] == ("azure", "roleAssignments")
    assert m("GET", ra, {}, {}, b"") is None and m("GET", ra, {"$filter": "weird"}, {}, b"") is None
    assert m("GET", f"{RG}/providers/Microsoft.Authorization/permissions", {}, {}, b"")[:2] == ("azure", "permissions")
    assert m("GET", "/_wire/arm" + f"{RG}/providers/Microsoft.Authorization/roleEligibilitySchedules", {}, {}, b"")[1] == "schedules"


def test_engine_package_stays_pure():
    """core/iam_engine must stay free of fastapi / socket (Pyodide-safe): AST scan of the new modules."""
    import ast
    bad = {"fastapi", "starlette", "socket", "requests", "urllib3", "httpx", "sqlite3"}
    for f in ("analyze_aws", "analyze_gcp", "analyze_azure", "analyze_wire", "access_analyzer"):
        tree = ast.parse(open(os.path.join(ROOT, "core", "iam_engine", f + ".py")).read())
        names = {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and not n.level} | \
                {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not (names & bad), (f, names & bad)


# ====================================================================== the REAL appliance (Mesh)
pytest.importorskip("fastapi")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    c.put("/api/iam/aws/enforcement", json={"space": "off"})
    yield c


def _sig(svc, akid="test"):
    return {"Authorization": f"AWS4-HMAC-SHA256 Credential={akid}/20261125/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=00",
            "X-Amz-Date": "20261125T000000Z"}


def _iam(c, form):
    return c.post("/", data=dict(form, Version="2010-05-08"), headers=dict(_sig("iam"), **{"Content-Type": "application/x-www-form-urlencoded"}))


def test_mesh_aws_simulate_and_access_analyzer_through_the_real_server(client):
    c = client
    uname, bucket, aname = "sim-" + uuid.uuid4().hex[:8], "aa-" + uuid.uuid4().hex[:8], "an-" + uuid.uuid4().hex[:8]
    assert _iam(c, {"Action": "CreateUser", "UserName": uname}).status_code == 200
    pol = {"Version": "2012-10-17", "Statement": [{"Sid": "ro", "Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "*"}]}
    _iam(c, {"Action": "PutUserPolicy", "UserName": uname, "PolicyName": "p", "PolicyDocument": json.dumps(pol)})
    acct = re.search(r"arn:aws:iam::(\d+):user", _iam(c, {"Action": "GetUser", "UserName": uname}).text).group(1)
    try:
        r = _iam(c, {"Action": "SimulatePrincipalPolicy", "PolicySourceArn": f"arn:aws:iam::{acct}:user/{uname}",
                     "ActionNames.member.1": "s3:GetObject", "ActionNames.member.2": "s3:DeleteObject", "ResourceArns.member.1": f"arn:aws:s3:::{bucket}/k"})
        assert r.status_code == 200
        dec = {m.find("i:EvalActionName", NS).text: m.find("i:EvalDecision", NS).text for m in ET.fromstring(r.text).iterfind(".//i:EvaluationResults/i:member", NS)}
        assert dec == {"s3:GetObject": "allowed", "s3:DeleteObject": "implicitDeny"}
        # a REAL public bucket policy through the S3 API, then the REAL analyzer finds it
        assert c.put(f"/{bucket}", headers=_sig("s3")).status_code == 200
        public = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/*"}]}
        assert c.put(f"/{bucket}?policy", content=json.dumps(public), headers=_sig("s3")).status_code in (200, 204)
        mk = c.put("/analyzer", content=json.dumps({"analyzerName": aname, "type": "ACCOUNT"}), headers=_sig("access-analyzer"))
        assert mk.status_code == 200, mk.text
        arn = mk.json()["arn"]
        fl = c.post("/finding", content=json.dumps({"analyzerArn": arn}), headers=_sig("access-analyzer"))
        assert fl.status_code == 200, fl.text
        f = next(x for x in fl.json()["findings"] if x["resource"] == f"arn:aws:s3:::{bucket}")
        assert f["isPublic"] is True and f["resourceType"] == "AWS::S3::Bucket" and f["principal"] == {"AWS": "*"}
        # the console's IAM-wire view lists the same finding (one generator)
        lf = _iam(c, {"Action": "ListFindings", "AnalyzerName": aname})
        assert f"arn:aws:s3:::{bucket}" in lf.text
        assert c.post("/policy/validation", content=json.dumps({"policyType": "IDENTITY_POLICY", "policyDocument": json.dumps({"Statement": [{"Effect": "Allow", "Action": "s3:Nope", "Resource": "*"}]})}),
                      headers=_sig("access-analyzer")).json()["findings"][0]["issueCode"] in ("INVALID_ACTION", "MISSING_VERSION")
        # the same path without the access-analyzer credential scope is still an S3 request (bucket named like the route)
        assert "findings" not in c.post("/policy/validation", content=b"{}", headers=_sig("s3")).text      # not claimed by the analyzer
    finally:
        c.delete(f"/analyzer/{aname}", headers=_sig("access-analyzer"))
        c.delete(f"/{bucket}?policy", headers=_sig("s3"))
        c.delete(f"/{bucket}", headers=_sig("s3"))
        _iam(c, {"Action": "DeleteUserPolicy", "UserName": uname, "PolicyName": "p"})
        _iam(c, {"Action": "DeleteUser", "UserName": uname})


def test_mesh_gcp_troubleshooter_and_analyze_iam_policy_through_the_real_server(client):
    from core import gcp_project
    c, pid = client, gcp_project.DEFAULT_PROJECT_ID
    who = f"user:ts-{uuid.uuid4().hex[:8]}@example.com"
    before = c.post(f"/v1/projects/{pid}:getIamPolicy", json={}).json()
    try:
        binds = list(before.get("bindings", [])) + [{"role": "roles/storage.objectViewer", "members": [who]}]
        assert c.post(f"/v1/projects/{pid}:setIamPolicy", json={"policy": {"bindings": binds}}).status_code == 200
        tup = {"accessTuple": {"principal": who, "fullResourceName": f"//cloudresourcemanager.googleapis.com/projects/{pid}", "permission": "storage.objects.get"}}
        v1 = c.post("/v1/iam:troubleshoot", json=tup)
        assert v1.status_code == 200, v1.text
        assert v1.json()["access"] == "GRANTED"
        pol = next(p for p in v1.json()["explainedPolicies"] if p["fullResourceName"].endswith(f"projects/{pid}"))
        assert any(b["role"] == "roles/storage.objectViewer" and b["access"] == "GRANTED" for b in pol["bindingExplanations"])
        tup["accessTuple"]["permission"] = "storage.objects.delete"
        assert c.post("/v1/iam:troubleshoot", json=tup).json()["access"] == "NOT_GRANTED"
        v3 = c.post("/v3/iam:troubleshoot", json=tup)
        assert v3.status_code == 200 and v3.json()["overallAccessState"] == "CANNOT_ACCESS"
        an = c.get(f"/v1/projects/{pid}:analyzeIamPolicy", params={"analysisQuery.identitySelector.identity": who})
        assert an.status_code == 200, an.text
        roles = [r["iamBinding"]["role"] for r in an.json()["mainAnalysis"]["analysisResults"]]
        assert roles == ["roles/storage.objectViewer"]
        assert c.post("/v1/iam:troubleshoot", json={"accessTuple": {"principal": who, "fullResourceName": "//x/y", "permission": "nope.nope.nope"}}).status_code == 400
    finally:
        c.post(f"/v1/projects/{pid}:setIamPolicy", json={"policy": {"bindings": before.get("bindings", [])}})


def test_mesh_azure_check_access_permissions_and_filtered_assignments_through_the_real_server(client):
    c, uid = client, uuid.uuid4().hex[:8]
    sub = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
    rg = f"{sub}/resourceGroups/rg-sa-{uid}"
    who = f"oid-sa-{uid}"
    role = f"{sub}/providers/Microsoft.Authorization/roleDefinitions/{READER}"
    assert c.put(rg + "?api-version=2021-04-01", json={"location": "eastus"}).status_code in (200, 201)
    try:
        r = c.put(f"{rg}/providers/Microsoft.Authorization/roleAssignments/{uuid.uuid4()}?api-version=2022-04-01",
                  json={"properties": {"principalId": who, "roleDefinitionId": role, "scope": rg}})
        assert r.status_code in (200, 201), r.text
        body = {"Subject": {"Attributes": {"ObjectId": who}}, "Actions": [{"Id": "Microsoft.Compute/virtualMachines/read", "IsDataAction": False},
                                                                          {"Id": "Microsoft.Compute/virtualMachines/write", "IsDataAction": False}], "Resource": {"Id": rg}}
        ca = c.post(f"{rg}/providers/Microsoft.Authorization/checkAccess?api-version=2018-09-01-preview", json=body)
        assert ca.status_code == 200, ca.text
        out = ca.json()
        assert isinstance(out, list) and [o["accessDecision"] for o in out] == ["Allowed", "NotAllowed"]
        assert out[0]["roleAssignment"]["scope"] == rg and out[0]["roleAssignment"]["roleDefinitionId"].endswith(READER)
        pm = c.get(f"{rg}/providers/Microsoft.Authorization/permissions?api-version=2022-04-01", headers={"X-Cloudlearn-Principal": who})
        assert pm.status_code == 200 and pm.json()["value"][0]["actions"] == ["*/read"]
        lf = c.get(f"{rg}/providers/Microsoft.Authorization/roleAssignments", params={"$filter": f"principalId eq '{who}'", "api-version": "2022-04-01"})
        assert lf.status_code == 200 and [x["properties"]["principalId"] for x in lf.json()["value"]] == [who]
        sc = c.get(f"{rg}/providers/Microsoft.Authorization/roleAssignments", params={"$filter": "atScope()", "api-version": "2022-04-01"})
        assert sc.status_code == 200 and any(x["properties"]["principalId"] == who for x in sc.json()["value"])
        el = c.get(f"{rg}/providers/Microsoft.Authorization/roleEligibilityScheduleInstances", params={"api-version": "2020-10-01"})
        assert el.status_code == 200 and "value" in el.json()
    finally:
        c.delete(rg + "?api-version=2021-04-01")
