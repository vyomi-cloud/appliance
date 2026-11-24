"""Integration: the REAL request map + REAL engine + gate + modes + audit, per cloud (the pieces were built separately against the
contract; this proves they fit). Substrate-neutral: no fastapi, so the same flow is what Nano runs."""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from core.iam_engine import gate, audit

AKID = "AKIAEXAMPLE0000000"
S3_SIG = f"AWS4-HMAC-SHA256 Credential={AKID}/20261123/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=00"


def aws_req(method, path, principal):
    return {"method": method, "path": path, "query": "", "headers": {"Authorization": S3_SIG, "Host": "s3.amazonaws.com"},
            "body": b"", "principal": principal}


AWS_USER = {"arn": "arn:aws:iam::123456789012:user/reader", "type": "user", "account": "123456789012",
            "policies": [{"id": "ro", "document": {"Version": "2012-10-17", "Statement": [
                {"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"], "Resource": ["arn:aws:s3:::b", "arn:aws:s3:::b/*"]}]}}]}


def test_aws_s3_enforce_allows_read_denies_write_with_exact_shape():
    log = audit.AuditLog()
    st = {"account": "123456789012"}
    cfg = {"global": "off", "space": "enforce", "services": {}, "resources": {}}
    assert gate.check("aws", aws_req("GET", "/b/key.txt", AWS_USER), st, cfg, audit=log) is None
    den = gate.check("aws", aws_req("PUT", "/b/key.txt", AWS_USER), st, cfg, audit=log)
    assert den and den["status"] == 403 and "<Code>AccessDenied</Code>" in den["body"] and "s3:PutObject" in den["body"]
    assert den["content_type"].startswith("application/xml")


def test_aws_audit_never_blocks_but_records_would_deny():
    log = audit.AuditLog()
    cfg = {"global": "off", "space": "audit", "services": {}, "resources": {}}
    assert gate.check("aws", aws_req("PUT", "/b/key.txt", AWS_USER), {"account": "123456789012"}, cfg, audit=log) is None
    rec = log.list()[0] if hasattr(log, "list") else log.entries()[0]
    assert "PutObject" in json.dumps(rec) and "audit" in json.dumps(rec)


def test_aws_service_level_override_and_off():
    log = audit.AuditLog()
    cfg = {"global": "off", "space": "enforce", "services": {"s3": "off"}, "resources": {}}
    assert gate.check("aws", aws_req("PUT", "/b/key.txt", AWS_USER), {}, cfg, audit=log) is None      # service beats space
    assert gate.check("aws", aws_req("PUT", "/b/key.txt", AWS_USER), {}, {"space": "off"}, audit=log) is None


def test_aws_explicit_deny_beats_allow():
    p = json.loads(json.dumps(AWS_USER))
    p["policies"].append({"id": "deny", "document": {"Version": "2012-10-17", "Statement": [
        {"Effect": "Deny", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/secret/*"}]}})
    cfg = {"space": "enforce"}
    assert gate.check("aws", aws_req("GET", "/b/ok.txt", p), {}, cfg, audit=audit.AuditLog()) is None
    den = gate.check("aws", aws_req("GET", "/b/secret/x", p), {}, cfg, audit=audit.AuditLog())
    assert den and den["status"] == 403 and "explicit deny" in den["body"]


def test_gcp_enforce_with_inheritance_and_permission_denied_shape():
    st = {"allow_policies": {"projects/p": {"bindings": [{"role": "roles/storage.objectViewer", "members": ["user:a@x.com"]}]}},
          "hierarchy": {"projects/_/buckets/bkt": "projects/p"}}
    me = {"member": "user:a@x.com", "type": "user"}
    cfg = {"space": "enforce"}
    get = {"method": "GET", "path": "https://storage.googleapis.com/storage/v1/b/bkt/o/obj", "headers": {}, "principal": me}
    assert gate.check("gcp", get, st, cfg, audit=audit.AuditLog()) is None
    dele = dict(get, method="DELETE")
    den = gate.check("gcp", dele, st, cfg, audit=audit.AuditLog())
    body = json.loads(den["body"])
    assert den["status"] == 403 and body["error"]["status"] == "PERMISSION_DENIED" and "storage.objects.delete" in body["error"]["message"]


def test_azure_enforce_with_scope_inheritance_and_authorization_failed_shape():
    scope = "/subscriptions/11111111-1111-1111-1111-111111111111"
    st = {"role_assignments": [{"id": "ra1", "principal_id": "oid-1", "role_definition_id": "Reader", "scope": scope}]}
    me = {"object_id": "oid-1", "type": "user"}
    cfg = {"space": "enforce"}
    path = scope + "/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa?api-version=2023-01-01"
    assert gate.check("azure", {"method": "GET", "path": path, "headers": {}, "principal": me}, st, cfg, audit=audit.AuditLog()) is None
    den = gate.check("azure", {"method": "DELETE", "path": path, "headers": {}, "principal": me}, st, cfg, audit=audit.AuditLog())
    assert den["status"] == 403 and json.loads(den["body"])["error"]["code"] == "AuthorizationFailed"


def test_unmapped_request_is_denied_in_enforce_unless_allowed():
    cfg = {"space": "enforce"}
    hr = {"method": "POST", "path": "/", "headers": {"X-Amz-Target": "NoSuchService_20200101.Frobnicate", "Authorization": S3_SIG.replace("/s3/", "/nosuchsvc/")}, "body": b"{}", "principal": AWS_USER}
    assert gate.check("aws", hr, {}, cfg, audit=audit.AuditLog())["status"] == 403
    assert gate.check("aws", hr, {}, dict(cfg, allowUnmapped=True), audit=audit.AuditLog()) is None


# ---- Mesh adapter chain with the REAL IAM store (user + policy + access key created through the IAM API) ----------------------
def _real_store():
    import re
    from core.iam_store import InMemoryIamStore
    from core import iam_core as iam
    st = InMemoryIamStore()
    iam.dispatch(st, {"Action": "CreateUser", "UserName": "carol"})
    iam.dispatch(st, {"Action": "CreateGroup", "GroupName": "readers"})
    iam.dispatch(st, {"Action": "AddUserToGroup", "UserName": "carol", "GroupName": "readers"})
    iam.dispatch(st, {"Action": "PutGroupPolicy", "GroupName": "readers", "PolicyName": "ro", "PolicyDocument": json.dumps(
        {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "arn:aws:s3:::b/*"}]})})
    akid = re.search(r"<AccessKeyId>(.*?)</AccessKeyId>", iam.dispatch(st, {"Action": "CreateAccessKey", "UserName": "carol"}).body).group(1)
    return st, akid


def test_mesh_adapters_with_real_iam_store_group_policy_allows_and_default_denies():
    from core import iam_state_adapters as ad
    st, akid = _real_store()
    sig = S3_SIG.replace(AKID, akid)
    def hr(method, path):
        h = {"Authorization": sig, "Host": "s3.amazonaws.com"}
        r = {"method": method, "path": path, "query": "", "headers": h, "body": b""}
        r["principal"] = ad.aws_principal(h, "", st)
        return r
    cfg = {"space": "enforce"}
    state = ad.aws_state(st)
    assert gate.check("aws", hr("GET", "/b/k"), state, cfg, audit=audit.AuditLog()) is None          # via group inline policy
    den = gate.check("aws", hr("PUT", "/b/k"), state, cfg, audit=audit.AuditLog())
    assert den and den["status"] == 403 and "carol" in den["body"]
    assert gate.check("aws", dict(hr("GET", "/b/k"), principal={"arn": "", "type": "unknown", "account": "123456789012"}),
                      state, cfg, audit=audit.AuditLog())["status"] == 403                             # unknown key -> denied in enforce


def test_mesh_adapters_attached_managed_policy_and_boundary():
    from core import iam_state_adapters as ad, iam_core as iam
    st, akid = _real_store()
    iam.dispatch(st, {"Action": "AttachUserPolicy", "UserName": "carol", "PolicyArn": "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"})
    sig = S3_SIG.replace(AKID, akid); h = {"Authorization": sig, "Host": "s3.amazonaws.com"}
    mk = lambda m, p: {"method": m, "path": p, "query": "", "headers": h, "body": b"", "principal": ad.aws_principal(h, "", st)}
    cfg = {"space": "enforce"}
    assert gate.check("aws", mk("GET", "/other/x"), ad.aws_state(st), cfg, audit=audit.AuditLog()) is None   # managed ReadOnly covers it
    iam.dispatch(st, {"Action": "CreatePolicy", "PolicyName": "bound", "PolicyDocument": json.dumps(
        {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/*"}]})})
    iam.dispatch(st, {"Action": "PutUserPermissionsBoundary", "UserName": "carol", "PermissionsBoundary": f"arn:aws:iam::{st.account_id}:policy/bound"})
    assert gate.check("aws", mk("GET", "/b/x"), ad.aws_state(st), cfg, audit=audit.AuditLog()) is None
    assert gate.check("aws", mk("GET", "/other/x"), ad.aws_state(st), cfg, audit=audit.AuditLog())["status"] == 403   # boundary narrows


def test_signed_s3_requests_to_buckets_named_like_console_paths_are_still_gated():
    cfg = {"space": "enforce"}
    for bucket in ("assets", "static", "api", "console-x", "mesh", "ws"):
        den = gate.check("aws", aws_req("PUT", f"/{bucket}/k", AWS_USER), {}, cfg, audit=audit.AuditLog())
        assert den and den["status"] == 403, bucket
    # the IAM API itself and unsigned console traffic stay reachable
    assert gate.is_internal({"path": "/api/iam/aws/enforcement", "headers": {"Authorization": S3_SIG}})
    assert gate.is_internal({"path": "/_wire/api/iam/aws/enforcement", "headers": {"Authorization": S3_SIG}})
    assert gate.is_internal({"path": "/static/app.js", "headers": {}})
