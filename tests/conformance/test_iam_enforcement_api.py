import json
import pytest
from core.iam_engine import modes, audit
from core.iam_engine.api import IamApi
from core.iam_engine.types import decision


class Eng:
    def evaluate(self, req, state):
        return decision(req["action"] == "s3:GetObject", "implicit_deny", [{"source": "identity", "id": "p", "effect": "Allow"}], seen_state=state)


def mk(**kw):
    return IamApi(modes.MemorySettingsStore(), state_fn=lambda c: {"cloud": c}, audit_log=audit.AuditLog(),
                  engines={"aws": Eng()}, **kw)


def test_get_default_settings():
    s, b = mk().handle("GET", "/api/iam/aws/enforcement")
    assert s == 200 and b["space"] == "off"


def test_put_then_get():
    a = mk()
    assert a.handle("PUT", "/api/iam/gcp/enforcement", body={"space": "audit"})[0] == 200
    assert a.handle("GET", "/api/iam/gcp/enforcement")[1]["space"] == "audit"


def test_put_invalid_400():
    s, b = mk().handle("PUT", "/api/iam/aws/enforcement", body={"space": "nope"})
    assert s == 400 and "space" in b["error"]


def test_unknown_cloud_404_and_bad_path():
    assert mk().handle("GET", "/api/iam/oracle/enforcement")[0] == 404
    assert mk().handle("GET", "/api/x")[0] == 404


def test_method_not_allowed():
    assert mk().handle("DELETE", "/api/iam/aws/enforcement")[0] == 405


def test_audit_list_limit_and_cloud_filter():
    a = mk()
    for i in range(5):
        a.log.record("aws", "p", f"a{i}", "r", "audit", "allow")
    a.log.record("gcp", "p", "g", "r", "audit", "allow")
    s, b = a.handle("GET", "/api/iam/aws/audit", {"limit": "2"})
    assert s == 200 and [r["action"] for r in b["records"]] == ["a4", "a3"]
    assert len(a.handle("GET", "/api/iam/gcp/audit")[1]["records"]) == 1


def test_audit_clear():
    a = mk()
    a.log.record("aws", "p", "a", "r", "audit", "allow")
    a.handle("DELETE", "/api/iam/aws/audit")
    assert a.handle("GET", "/api/iam/aws/audit")[1]["records"] == []


def test_evaluate_uses_engine_and_state():
    s, b = mk().handle("POST", "/api/iam/aws/evaluate", body={"principal": {"arn": "x"}, "action": "s3:GetObject"})
    assert s == 200 and b["allowed"] is True and b["seen_state"] == {"cloud": "aws"}


def test_evaluate_denied():
    assert mk().handle("POST", "/api/iam/aws/evaluate", body={"action": "s3:PutObject"})[1]["allowed"] is False


def test_evaluate_requires_action():
    assert mk().handle("POST", "/api/iam/aws/evaluate", body={})[0] == 400


def test_evaluate_uses_the_real_engine_when_present_and_501_when_not():
    st, body = mk().handle("POST", "/api/iam/azure/evaluate", body={"action": "Microsoft.Storage/storageAccounts/read"})
    assert st == 200 and body["allowed"] is False and body["reason"] == "implicit_deny"      # real azure_eval, empty state
    from core.iam_engine.api import IamApi
    api = IamApi(settings_store=modes.MemorySettingsStore(), state_fn=lambda c: {}, engines={"azure": object()})   # engine without evaluate()
    assert api.handle("POST", "/api/iam/azure/evaluate", body={"action": "a"})[0] in (500, 501)


def test_catalog_simulated_flag_with_inventory():
    inv = {"services": [{"cloud": "aws", "id": "s3"}]}
    a = mk(catalog_fn=lambda c, s: {"service": s}, inventory_fn=lambda: inv)
    assert a.handle("GET", "/api/iam/aws/catalog/s3")[1]["vyomi"] == {"simulated": True, "inventory": True}
    assert a.handle("GET", "/api/iam/aws/catalog/kms")[1]["vyomi"]["simulated"] is False
    assert a.handle("GET", "/api/iam/gcp/catalog/s3")[1]["vyomi"]["simulated"] is False


def test_catalog_degrades_without_inventory():
    a = mk(catalog_fn=lambda c, s: {"service": s})
    assert a.handle("GET", "/api/iam/aws/catalog/s3")[1]["vyomi"] == {"simulated": None, "inventory": False}


def test_catalog_missing_404():
    assert mk().handle("GET", "/api/iam/aws/catalog/zzz")[0] == 404


def test_fastapi_wrapper_and_real_catalog_files():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import iam_enforcement
    app = FastAPI()
    iam_enforcement.register(app, api=IamApi(modes.MemorySettingsStore(), catalog_fn=iam_enforcement._catalog,
                                            inventory_fn=iam_enforcement._inventory, audit_log=audit.AuditLog()))
    c = TestClient(app)
    assert c.put("/api/iam/aws/enforcement", json={"services": {"s3": "enforce"}}).status_code == 200
    assert c.get("/api/iam/aws/enforcement").json()["services"] == {"s3": "enforce"}
    assert c.put("/api/iam/aws/enforcement", json={"space": "x"}).status_code == 400
    r = c.get("/api/iam/aws/catalog/s3")
    assert r.status_code == 200 and "actions" in r.json() and "vyomi" in r.json()
    assert c.get("/api/iam/aws/catalog/..%2Fx").status_code in (404, 422)
    assert c.get("/api/iam/aws/audit?limit=5").json() == {"records": []}


def test_adapters_aws_principal_and_state():
    from core import iam_state_adapters as ad

    class St:
        account_id = "111122223333"
        users = {"bob": {"arn": "arn:aws:iam::111122223333:user/bob"}}
        groups, roles, policies, org_policies = {}, {}, {}, {}
        access_keys = {"AKIABOB": {"user_name": "bob"}}
        extras = {"sts_sessions": {"ASIAX": {"role_name": "r", "session_name": "s"}}}
    h = {"authorization": "AWS4-HMAC-SHA256 Credential=AKIABOB/20260101/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=x"}
    assert ad.aws_principal(h, "", St)["arn"].endswith("user/bob")
    assert ad.aws_principal({}, "X-Amz-Credential=ASIAX%2F2026%2Fus-east-1%2Fs3%2Faws4_request", St)["arn"].endswith("assumed-role/r/s")
    assert ad.aws_principal({"authorization": "AWS NOPE:sig"}, "", St)["type"] == "unknown"
    assert ad.aws_state(St)["account"] == "111122223333"


def test_adapters_gcp_azure():
    from core import iam_state_adapters as ad
    assert ad.gcp_principal({"x-cloudlearn-principal": "sa@p.iam.gserviceaccount.com"}, {})["member"].startswith("serviceAccount:")
    assert ad.gcp_principal({}, {"active_principal": "root"})["type"] == "root"
    assert ad.azure_principal({"x-cloudlearn-principal": "oid1"}, {})["object_id"] == "oid1"
    st = ad.azure_state({"a": {"type": "Microsoft.Authorization/roleAssignments", "properties": {}}})
    assert len(st["role_assignments"]) == 1
