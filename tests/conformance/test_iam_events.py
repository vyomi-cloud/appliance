"""IAM audit / history over the REAL server: CloudTrail-style IAM/STS events, Cloud Audit Logs entries for GCP IAM writes and impersonation, Azure
Activity Log events for role assignments / PIM requests, gate denials merged as denied events, filters and export."""
import json, os, sys, uuid, time
from urllib.parse import urlencode

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")
import tempfile as _tf
os.environ.setdefault("CLOUDLEARN_STATE_FILE", os.path.join(_tf.mkdtemp(prefix="vyomi-iam-"), "state.sqlite3"))   # never leak enforcement settings between runs
pytest.importorskip("fastapi")

from core import gcp_project   # noqa: E402
PID = gcp_project.DEFAULT_PROJECT_ID
SUB = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
AWS = "AWS4-HMAC-SHA256 Credential=AKIATEST/20260101/us-east-1/%s/aws4_request, SignedHeaders=host, Signature=x"


@pytest.fixture(scope="module")
def c():
    from fastapi.testclient import TestClient
    import server
    cl = TestClient(server.app)
    for k in ("aws", "gcp", "azure"):
        cl.put(f"/api/iam/{k}/enforcement", json={"space": "off"})
    yield cl
    for k in ("aws", "gcp", "azure"):
        cl.put(f"/api/iam/{k}/enforcement", json={"space": "off"})


def _events(c, cloud, **q):
    r = c.get(f"/api/iam/{cloud}/events?" + urlencode(q))
    assert r.status_code == 200, r.text
    return r.json()


def _aws(c, svc, **p):
    return c.post("/", content=urlencode(p), headers={"authorization": AWS % svc, "content-type": "application/x-www-form-urlencoded"})


def test_aws_iam_and_sts_events_with_error_codes(c):
    uid = uuid.uuid4().hex[:6]
    trust = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]})
    assert _aws(c, "iam", Action="CreateRole", RoleName="ev" + uid, AssumeRolePolicyDocument=trust, Version="2010-05-08").status_code == 200
    r = _aws(c, "sts", Action="AssumeRole", RoleArn="arn:aws:iam::123456789012:role/ev" + uid, RoleSessionName="s1", Version="2011-06-15")
    assert r.status_code == 403                                                              # the trust policy names ec2, not the caller
    d = _events(c, "aws", resource="ev" + uid)
    names = {e["name"]: e for e in d["events"]}
    assert "CreateRole" in names and names["CreateRole"]["outcome"] == "success" and names["CreateRole"]["native"]["EventSource"] == "iam.amazonaws.com"
    assert "AssumeRole" in names and names["AssumeRole"]["outcome"] == "denied" and names["AssumeRole"]["errorCode"] == "AccessDenied"
    assert names["CreateRole"]["params"]["roleName"] == "ev" + uid                           # CloudTrail requestParameters
    # filters
    assert all(e["name"] == "CreateRole" for e in _events(c, "aws", name="CreateRole", resource="ev" + uid)["events"])
    assert all(e["outcome"] == "denied" for e in _events(c, "aws", outcome="denied")["events"])
    assert all(e["readOnly"] for e in _events(c, "aws", readOnly="true", scope="all")["events"])


def test_gcp_iam_writes_are_cloud_audit_log_entries(c):
    uid = uuid.uuid4().hex[:6]
    h = {"X-Cloudlearn-Principal": "user:ops@example.com"}
    r = c.post(f"/v1/projects/{PID}/serviceAccounts", headers=h, json={"accountId": "svc" + uid, "serviceAccount": {"displayName": "x"}})
    assert r.status_code in (200, 201), r.text
    email = f"svc{uid}@{PID}.iam.gserviceaccount.com"
    r = c.post(f"/v1/projects/{PID}/serviceAccounts/{email}/keys", headers=h, json={})
    assert r.status_code in (200, 201), r.text
    pol = {"policy": {"bindings": [{"role": "roles/viewer", "members": ["user:a@example.com"]}]}}
    r = c.post(f"/v1/projects/{PID}/serviceAccounts/{email}:setIamPolicy", headers=h, json=pol)
    assert r.status_code == 200, r.text
    d = _events(c, "gcp", principal="ops@example.com")
    by = {e["native"]["protoPayload"]["methodName"]: e for e in d["events"]}
    assert "google.iam.admin.v1.CreateServiceAccount" in by and "google.iam.admin.v1.CreateServiceAccountKey" in by and "google.iam.admin.v1.SetIAMPolicy" in by
    e = by["google.iam.admin.v1.CreateServiceAccount"]["native"]
    assert e["logName"] == f"projects/{PID}/logs/cloudaudit.googleapis.com%2Factivity"
    assert e["protoPayload"]["@type"].endswith("google.cloud.audit.AuditLog") and e["protoPayload"]["authenticationInfo"]["principalEmail"] == "user:ops@example.com"
    assert e["protoPayload"]["serviceName"] == "iam.googleapis.com" and e["protoPayload"]["resourceName"] == f"projects/{PID}/serviceAccounts"
    assert by["google.iam.admin.v1.SetIAMPolicy"]["params"]["policy"]["bindings"][0]["role"] == "roles/viewer"
    # impersonation: an IAM Credentials data-access entry
    r = c.post(f"/v1/projects/-/serviceAccounts/{email}:generateAccessToken", headers=h, json={"scope": ["https://www.googleapis.com/auth/cloud-platform"]})
    d = _events(c, "gcp", name="GenerateAccessToken")
    assert d["events"] and d["events"][0]["native"]["logName"].endswith("data_access") and d["events"][0]["readOnly"] is True


def test_gcp_denied_call_shows_as_permission_denied(c):
    c.put("/api/iam/gcp/enforcement", json={"space": "enforce", "allowUnmapped": True})
    r = c.post(f"/v1/projects/{PID}/serviceAccounts", headers={"X-Cloudlearn-Principal": "user:nobody@example.com"}, json={"accountId": "denied1", "serviceAccount": {}})
    for k in ("aws", "gcp", "azure"):          # one settings document per space: put every cloud's view back to off
        c.put(f"/api/iam/{k}/enforcement", json={"space": "off"})
    assert r.status_code == 403
    d = _events(c, "gcp", principal="nobody@example.com", outcome="denied")
    assert d["events"] and d["events"][0]["errorCode"] == "PERMISSION_DENIED" and d["events"][0]["native"]["protoPayload"]["status"]["code"] == 7


def test_azure_role_assignment_and_pim_events_in_activity_log_shape(c):
    uid = uuid.uuid4().hex[:6]
    rg = f"{SUB}/resourceGroups/rg-ev-{uid}"
    assert c.put(rg + "?api-version=2021-04-01", json={"location": "eastus"}).status_code in (200, 201)
    ra = c.put(f"{rg}/providers/Microsoft.Authorization/roleAssignments/{uuid.uuid4()}?api-version=2022-04-01", headers={"X-Cloudlearn-Principal": "admin-" + uid},
               json={"properties": {"principalId": "p-" + uid, "roleDefinitionId": f"{SUB}/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7", "scope": rg}})
    assert ra.status_code in (200, 201), ra.text
    pim = c.put(f"{rg}/providers/Microsoft.Authorization/roleEligibilityScheduleRequests/{uuid.uuid4()}?api-version=2020-10-01",
                json={"properties": {"requestType": "AdminAssign", "principalId": "p-" + uid, "roleDefinitionId": "/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7"}})
    assert pim.status_code == 201
    d = _events(c, "azure", resource=rg)
    ops = {e["name"]: e for e in d["events"]}
    assert "Microsoft.Authorization/roleAssignments/write" in ops and "Microsoft.Authorization/roleEligibilityScheduleRequests/write" in ops
    n = ops["Microsoft.Authorization/roleAssignments/write"]["native"]
    assert n["operationName"]["value"] == "Microsoft.Authorization/roleAssignments/write" and n["status"]["value"] == "Succeeded"
    assert n["caller"] == "admin-" + uid and n["category"]["value"] == "Administrative"
    c.delete(rg + "?api-version=2021-04-01")


def test_export_json_and_csv_and_filters(c):
    r = c.get("/api/iam/gcp/events/export?format=csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and r.text.splitlines()[0].startswith("time,cloud,service,name,principal")
    assert "attachment" in r.headers["content-disposition"]
    r = c.get("/api/iam/azure/events/export")
    assert r.status_code == 200 and isinstance(r.json(), list)
    d = _events(c, "gcp", limit=1)
    assert len(d["events"]) == 1 and d["total"] >= 1 and d["truncated"] is (d["total"] > 1)
    assert _events(c, "gcp", q="no-such-text-anywhere-zzz")["events"] == []
    assert _events(c, "gcp", start=str(time.time() + 3600))["events"] == []


def test_gcp_sts_exchange_is_recorded_and_impersonation_of_unknown_sa_fails_audited(c):
    """An STS token exchange (rejected: no such pool) lands in the audit feed as google.identity.sts.v1.SecurityTokenService.ExchangeToken."""
    form = "grant_type=urn:ietf:params:oauth:grant-type:token-exchange&subject_token_type=urn:ietf:params:oauth:token-type:jwt&audience=//iam.googleapis.com/projects/1/locations/global/workloadIdentityPools/nope/providers/x&subject_token=a.b.c"
    r = c.post("/v1/token", content=form, headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code >= 400
    d = _events(c, "gcp", name="ExchangeToken", scope="all")
    assert d["events"] and d["events"][0]["native"]["protoPayload"]["methodName"].endswith("SecurityTokenService.ExchangeToken")
    assert d["events"][0]["outcome"] in ("denied", "error")
