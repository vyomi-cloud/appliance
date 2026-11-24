import json
import pytest
from core.iam_engine import gate, audit
from core.iam_engine.types import decision


class Eng:
    def __init__(self, allow=True, reason="allow", boom=False):
        self.allow, self.reason, self.boom, self.seen = allow, reason, boom, []

    def evaluate(self, req, state):
        self.seen.append(req)
        if self.boom:
            raise RuntimeError("kaboom")
        return decision(self.allow, self.reason if not self.allow else "allow", [{"source": "identity", "id": "p", "effect": "Deny" if self.reason == "explicit_deny" else "Allow"}])


class Map:
    def __init__(self, perms):
        self.perms = perms

    def required(self, *a):
        if isinstance(self.perms, Exception):
            raise self.perms
        return self.perms


AWS_P = {"arn": "arn:aws:iam::1:user/bob", "type": "user"}


def run(cloud, hr, settings, eng, perms, log=None):
    log = log or audit.AuditLog()
    r = gate.check(cloud, hr, {}, settings, engines={cloud: eng}, maps={cloud: Map(perms)}, audit=log)
    return r, log


def aws_req(headers=None, path="/bucket/key", **kw):
    return dict({"method": "GET", "path": path, "headers": headers or {}, "principal": AWS_P}, **kw)


P_S3 = [{"action": "s3:GetObject", "resource": "arn:aws:s3:::bucket/key", "service": "s3"}]
ENF = {"space": "enforce"}


def test_off_skips_everything():
    e = Eng(allow=False)
    r, log = run("aws", aws_req(), {"space": "off"}, e, P_S3)
    assert r is None and not e.seen and not log.list()


def test_audit_would_deny_never_blocks():
    r, log = run("aws", aws_req(), {"space": "audit"}, Eng(False, "implicit_deny"), P_S3)
    assert r is None
    rec = log.list()[0]
    assert rec["decision"] == "would_deny" and rec["mode"] == "audit" and rec["action"] == "s3:GetObject"


def test_audit_engine_error_never_raises_or_blocks():
    r, log = run("aws", aws_req(), {"space": "audit"}, Eng(boom=True), P_S3)
    assert r is None and log.list()[0]["decision"] == "error"


def test_audit_map_error_never_blocks():
    r, log = run("aws", aws_req(), {"space": "audit"}, Eng(), RuntimeError("x"))
    assert r is None and log.list()[0]["decision"] == "error"


def test_enforce_allow_records_allow():
    r, log = run("aws", aws_req(), ENF, Eng(True), P_S3)
    assert r is None and log.list()[0]["decision"] == "allow"


def test_enforce_s3_xml_shape():
    r, _ = run("aws", aws_req(), ENF, Eng(False, "implicit_deny"), P_S3)
    assert r["status"] == 403 and "<Code>AccessDenied</Code>" in r["body"] and r["content_type"] == "application/xml"
    assert "arn:aws:iam::1:user/bob is not authorized to perform: s3:GetObject on resource: arn:aws:s3:::bucket/key" in r["body"]
    assert "because no identity-based policy allows the s3:GetObject action" in r["body"]


def test_enforce_explicit_deny_message():
    r, _ = run("aws", aws_req(), ENF, Eng(False, "explicit_deny"), P_S3)
    assert "with an explicit deny in an identity-based policy" in r["body"]


def test_enforce_json_shape():
    h = {"x-amz-target": "DynamoDB_20120810.GetItem", "content-type": "application/x-amz-json-1.0"}
    r, _ = run("aws", aws_req(h, "/"), ENF, Eng(False, "implicit_deny"),
               [{"action": "dynamodb:GetItem", "resource": "arn:aws:dynamodb:::table/t", "service": "dynamodb"}])
    assert r["headers"]["x-amzn-ErrorType"] == "AccessDeniedException" and r["content_type"] == "application/x-amz-json-1.0"
    b = json.loads(r["body"])
    assert b["__type"] == "AccessDeniedException" and "dynamodb:GetItem" in b["message"]


def test_json_11_content_type():
    h = {"x-amz-target": "X.Y", "content-type": "application/x-amz-json-1.1"}
    r, _ = run("aws", aws_req(h, "/"), ENF, Eng(False, "implicit_deny"), [{"action": "kms:Decrypt", "service": "kms"}])
    assert r["content_type"] == "application/x-amz-json-1.1"


def test_enforce_ec2_unauthorized_operation():
    r, _ = run("aws", aws_req({}, "/"), ENF, Eng(False, "implicit_deny"), [{"action": "ec2:RunInstances", "resource": "*", "service": "ec2"}])
    assert "<Code>UnauthorizedOperation</Code>" in r["body"] and "<Errors>" in r["body"]


def test_enforce_query_xml_access_denied():
    r, _ = run("aws", aws_req({}, "/"), ENF, Eng(False, "implicit_deny"), [{"action": "sqs:SendMessage", "service": "sqs"}])
    assert "<ErrorResponse" in r["body"] and "<Code>AccessDenied</Code>" in r["body"]


def test_enforce_gcp_shape():
    hr = {"method": "GET", "path": "/storage/v1/b/x", "headers": {}, "principal": {"member": "user:a@b.c"}}
    r, _ = run("gcp", hr, ENF, Eng(False, "implicit_deny"), [{"action": "storage.buckets.get", "resource": "//storage.googleapis.com/projects/_/buckets/x", "service": "storage"}])
    b = json.loads(r["body"])["error"]
    assert r["status"] == 403 and b["code"] == 403 and b["status"] == "PERMISSION_DENIED"
    assert b["message"] == "Permission 'storage.buckets.get' denied on resource '//storage.googleapis.com/projects/_/buckets/x' (or it may not exist)."


def test_enforce_azure_shape():
    hr = {"method": "GET", "path": "/subscriptions/s/resourceGroups/g", "headers": {}, "principal": {"object_id": "oid-1"}}
    r, _ = run("azure", hr, ENF, Eng(False, "implicit_deny"), [{"action": "Microsoft.Resources/subscriptions/resourceGroups/read", "resource": "/subscriptions/s/resourceGroups/g"}])
    e = json.loads(r["body"])["error"]
    assert e["code"] == "AuthorizationFailed" and "does not have authorization to perform action 'Microsoft.Resources/subscriptions/resourceGroups/read' over scope '/subscriptions/s/resourceGroups/g'" in e["message"]


def test_fail_closed_on_engine_error():
    r, log = run("aws", aws_req(), ENF, Eng(boom=True), P_S3)
    assert r["status"] == 403 and "fail closed" in r["body"] and log.list()[0]["decision"] == "error"


def test_fail_closed_on_missing_engine():
    r = gate.check("aws", aws_req(), {}, ENF, engines={}, maps={"aws": Map(P_S3)}, audit=audit.AuditLog()) \
        if False else gate.check("gcp", aws_req(), {}, ENF, maps={"gcp": Map(P_S3)}, audit=audit.AuditLog())
    assert r["status"] == 403


def test_fail_closed_on_map_error():
    r, _ = run("aws", aws_req(), ENF, Eng(), RuntimeError("bad"))
    assert r["status"] == 403 and "could not map" in r["body"]


def test_multi_permission_needs_all():
    class E2(Eng):
        def evaluate(self, req, state):
            return decision(req["action"] != "kms:Decrypt", "implicit_deny")
    perms = [{"action": "s3:GetObject", "service": "s3"}, {"action": "kms:Decrypt", "service": "kms"}]
    r, log = run("aws", aws_req(), ENF, E2(), perms)
    assert r is not None and "kms:Decrypt" in r["body"]
    assert [x["decision"] for x in log.list()] == ["deny", "allow"]


def test_per_service_mode_mix():
    perms = [{"action": "s3:GetObject", "service": "s3"}, {"action": "kms:Decrypt", "service": "kms"}]
    st = {"space": "off", "services": {"s3": "audit", "kms": "enforce"}}
    r, log = run("aws", aws_req(), st, Eng(False, "implicit_deny"), perms)
    assert r is not None and "kms:Decrypt" in r["body"]
    assert {x["action"]: x["decision"] for x in log.list()} == {"s3:GetObject": "would_deny", "kms:Decrypt": "deny"}


def test_resource_off_override_inside_enforce():
    st = {"space": "enforce", "resources": {"arn:aws:s3:::bucket/key": "off"}}
    e = Eng(False, "implicit_deny")
    r, _ = run("aws", aws_req(), st, e, P_S3)
    assert r is None and not e.seen


def test_unmapped_audit_logged_allowed():
    r, log = run("aws", aws_req(), {"space": "audit"}, Eng(), [])
    assert r is None and log.list()[0]["decision"] == "unmapped"


def test_unmapped_enforce_denied_by_default():
    r, log = run("aws", aws_req(), ENF, Eng(), [])
    assert r["status"] == 403 and "no permission mapping" in r["body"] and "allowUnmapped" in r["body"]
    assert log.list()[0]["decision"] == "unmapped"


def test_unmapped_enforce_allowed_with_flag():
    r, _ = run("aws", aws_req(), {"space": "enforce", "allowUnmapped": True}, Eng(), [])
    assert r is None


def test_unmapped_off_silent():
    r, log = run("aws", aws_req(), {}, Eng(), [])
    assert r is None and not log.list()


@pytest.mark.parametrize("path", ["/api/iam/aws/enforcement", "/mesh/status", "/healthz", "/static/x.js", "/ws/x"])
def test_internal_bypass(path):
    e = Eng(False, "implicit_deny")
    r, _ = run("aws", aws_req(path=path), ENF, e, P_S3)
    assert r is None and not e.seen


def test_custom_bypass_hook():
    r = gate.check("aws", aws_req(), {}, ENF, engines={"aws": Eng(False, "implicit_deny")}, maps={"aws": Map(P_S3)},
                   audit=audit.AuditLog(), bypass=lambda hr: True)
    assert r is None


def test_gcp_map_gets_method_url_body():
    seen = []

    class M:
        def required(self, method, url, body=None):
            seen.append((method, url, body))
            return []
    gate.check("gcp", {"method": "POST", "path": "/v1/x", "query": "a=1", "body": b"{}", "headers": {}}, {}, {"space": "audit"},
               engines={"gcp": Eng()}, maps={"gcp": M()}, audit=audit.AuditLog())
    assert seen == [("POST", "/v1/x?a=1", b"{}")]


def test_data_flag_passed_to_engine():
    e = Eng()
    run("azure", {"method": "GET", "path": "/x", "headers": {}, "principal": {"object_id": "o"}}, ENF, e,
        [{"action": "Microsoft.Storage/x", "resource": "/s", "data": True}])
    assert e.seen[0]["data"] is True and e.seen[0]["cloud"] == "azure"
