"""v4 offline durability — every service the offline appliance serves through a shared core
keeps its state in the persisted kernel state (core/appliance_stores._CoreSlotStore), so an
appliance restart no longer wipes it. Pre-fix these stores were process-local singletons
(the cores' `shared_store()`) or the net-new router's in-memory defaults: create a GCP custom
role or a Cloud Monitoring service, restart → both lists empty.

Each test: create through the native wire offline (TestClient on server.app) → simulated
restart (the kernel state replaced by a FRESH load of the state file, the live store objects
rebuilt, Azure SQL connections dropped) → list through the native wire → still there.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vyomi-durable-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.setdefault("CLOUDLEARN_VAULT_URL", "http://127.0.0.1:1")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

P = "/v1/projects/vyomi-project"
L = P + "/locations/us-central1"


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def _restart() -> None:
    """What a process restart does to these stores: the kernel state is whatever the state
    file holds, and nothing process-local survives."""
    from core import app_context as ctx
    from core import appliance_stores as aps
    from core import wire_ingress as wi
    from core.vyomi_platform import SQLiteStateStore
    loaded = SQLiteStateStore(Path(os.environ["CLOUDLEARN_STATE_FILE"])).load_state(dict)
    assert loaded, "nothing was saved"
    ctx.STATE.clear()
    ctx.STATE.update(loaded)
    for mod, _cls in aps._SHARED_CORE_STORES:
        mod._SHARED = None
    aps.install_core_slot_stores()
    for mod, cls in aps._SHARED_CORE_STORES:
        assert type(mod.shared_store()) is cls
    r = wi.new_services_router()
    if r is not None:   # the router keeps its store objects; they hold no state but connections
        for name in ("apigwv2", "sfn", "gcp_sched", "gcp_gke", "gcp_iamc", "gcp_redis", "gcp_mon"):
            mod = {"apigwv2": "apigatewayv2_core", "sfn": "stepfunctions_core", "gcp_sched": "gcp_cloudscheduler_core",
                   "gcp_gke": "gcp_container_core", "gcp_iamc": "gcp_iamcredentials_core",
                   "gcp_redis": "gcp_redis_core", "gcp_mon": "gcp_monitoring_core"}[name]
            setattr(r, name, __import__(f"core.{mod}", fromlist=["x"]).shared_store())
        r.rds.__dict__.pop("_conns_by_space", None)


def _ok(r, *codes):
    assert r.status_code in (codes or (200,)), f"{r.request.method} {r.request.url} -> {r.status_code} {r.text[:400]}"
    return r.json() if r.content else {}


def _names(items, key="name"):
    return {str(x.get(key, "")).rsplit("/", 1)[-1] for x in items or []}


# ── GCP: IAM custom roles, Workload Identity pools, Org Policy v2 (net-new router) ─────────

def test_gcp_iam_roles_wif_orgpolicy_survive_restart(client):
    rid = "durRole" + uuid.uuid4().hex[:6]
    _ok(client.post(P + "/roles", json={"roleId": rid, "role": {
        "title": "Durable", "includedPermissions": ["storage.buckets.get"]}}))
    pool = "pool-" + uuid.uuid4().hex[:6]
    _ok(client.post(P + "/locations/global/workloadIdentityPools",
                    params={"workloadIdentityPoolId": pool}, json={"displayName": "Durable pool"}))
    pol = "custom.dur" + uuid.uuid4().hex[:6]
    _ok(client.post("/v2/projects/vyomi-project/policies", params={"policyId": pol},
                    json={"spec": {"rules": [{"enforce": True}]}}))
    _restart()
    assert rid in _names(_ok(client.get(P + "/roles")).get("roles"))
    assert pool in _names(_ok(client.get(P + "/locations/global/workloadIdentityPools")).get("workloadIdentityPools"))
    assert pol in _names(_ok(client.get("/v2/projects/vyomi-project/policies")).get("policies"))


# ── GCP: Cloud Monitoring (services, SLOs, alert policies, time series) ───────────────

def test_gcp_monitoring_survives_restart(client):
    M = "/v3/projects/vyomi-project"
    svc = _ok(client.post(M + "/services", json={"displayName": "checkout-" + uuid.uuid4().hex[:4]}))
    sid = svc["name"].rsplit("/", 1)[-1]
    slo = _ok(client.post(f"{M}/services/{sid}/serviceLevelObjectives", json={
        "displayName": "99%", "goal": 0.99, "rollingPeriod": "2592000s",
        "serviceLevelIndicator": {"basicSli": {"availability": {}}}}))
    pol = _ok(client.post(M + "/alertPolicies", json={"displayName": "cpu-high", "combiner": "OR", "conditions": [{
        "displayName": "cpu > 80%", "conditionThreshold": {
            "filter": 'metric.type = "compute.googleapis.com/instance/cpu/utilization" AND resource.type = "gce_instance"',
            "comparison": "COMPARISON_GT", "thresholdValue": 0.8, "duration": "300s"}}]}))
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    _ok(client.post(M + "/timeSeries", json={"timeSeries": [{
        "metric": {"type": "custom.googleapis.com/durable/latency", "labels": {"route": "/a"}},
        "resource": {"type": "global", "labels": {"project_id": "vyomi-project"}},
        "points": [{"interval": {"endTime": now.strftime("%Y-%m-%dT%H:%M:%SZ")}, "value": {"doubleValue": 1.5}}]}]}))
    _restart()
    assert sid in _names(_ok(client.get(M + "/services")).get("services"))
    assert slo["name"] in {s["name"] for s in _ok(client.get(f"{M}/services/{sid}/serviceLevelObjectives"))
                           .get("serviceLevelObjectives", [])}
    assert pol["name"] in {p["name"] for p in _ok(client.get(M + "/alertPolicies")).get("alertPolicies", [])}
    start = (now - _dt.timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (now + _dt.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts = _ok(client.get(M + "/timeSeries", params={
        "filter": 'metric.type = "custom.googleapis.com/durable/latency"',
        "interval.startTime": start, "interval.endTime": end})).get("timeSeries", [])
    assert ts and ts[0]["points"][0]["value"]["doubleValue"] == 1.5


# ── GCP: GKE, Memorystore, Cloud Scheduler, IAM Credentials ────────────────────────────

def test_gcp_gke_redis_scheduler_survive_restart(client):
    cl = "c" + uuid.uuid4().hex[:6]
    _ok(client.post(L + "/clusters", json={"cluster": {"name": cl, "initialNodeCount": 1}}))
    ri = "r" + uuid.uuid4().hex[:6]
    _ok(client.post(L + "/instances", params={"instanceId": ri}, json={"tier": "BASIC", "memorySizeGb": 1}))
    job = "j" + uuid.uuid4().hex[:6]
    _ok(client.post(L + "/jobs", json={"name": f"projects/vyomi-project/locations/us-central1/jobs/{job}",
                                       "schedule": "0 0 1 1 *",
                                       "httpTarget": {"uri": "https://example.com/hook", "httpMethod": "POST"}}))
    _restart()
    assert cl in _names(_ok(client.get(L + "/clusters")).get("clusters"))
    assert ri in _names(_ok(client.get(L + "/instances")).get("instances"))
    assert job in _names(_ok(client.get(L + "/jobs")).get("jobs"))


def test_gcp_iamcredentials_issue_log_survives_restart(client):
    acct = "robot" + uuid.uuid4().hex[:6]
    sa = _ok(client.post(P + "/serviceAccounts", json={"accountId": acct, "serviceAccount": {"displayName": "r"}}))
    email = sa.get("email") or f"{acct}@vyomi-project.iam.gserviceaccount.com"
    tok = _ok(client.post(f"/v1/projects/-/serviceAccounts/{email}:generateAccessToken",
                          json={"scope": ["https://www.googleapis.com/auth/cloud-platform"]}))
    assert tok["accessToken"].startswith("ya29.")
    before = {c["name"] for c in _ok(client.get("/api/gcp/iamcredentials/credentials")).get("items", [])}
    assert before
    _restart()
    after = {c["name"] for c in _ok(client.get("/api/gcp/iamcredentials/credentials")).get("items", [])}
    assert before <= after


# ── AWS: Step Functions, API Gateway V2, SSM, API Gateway v1 ───────────────────────────

def _xamz(client, target, body, ctype="application/x-amz-json-1.0"):
    return client.post("/", content=json.dumps(body), headers={"x-amz-target": target, "content-type": ctype})


def test_aws_stepfunctions_apigwv2_ssm_apigw_survive_restart(client):
    sm = "sm" + uuid.uuid4().hex[:6]
    _ok(_xamz(client, "AWSStepFunctions.CreateStateMachine", {
        "name": sm, "roleArn": "arn:aws:iam::123456789012:role/sfn",
        "definition": json.dumps({"StartAt": "P", "States": {"P": {"Type": "Pass", "End": True}}})}))
    api = _ok(client.post("/v2/apis", json={"name": "dur-" + uuid.uuid4().hex[:4], "protocolType": "HTTP"}), 200, 201)
    pname = "/dur/" + uuid.uuid4().hex[:6]
    _ok(_xamz(client, "AmazonSSM.PutParameter", {"Name": pname, "Value": "v1", "Type": "String"},
              "application/x-amz-json-1.1"))
    rest = _ok(client.post("/restapis", json={"name": "dur-rest-" + uuid.uuid4().hex[:4]}), 200, 201)
    _restart()
    sms = _ok(_xamz(client, "AWSStepFunctions.ListStateMachines", {})).get("stateMachines", [])
    assert sm in {m["name"] for m in sms}
    assert api["apiId"] in {a["apiId"] for a in _ok(client.get("/v2/apis")).get("items", [])}
    got = _ok(_xamz(client, "AmazonSSM.GetParameter", {"Name": pname}, "application/x-amz-json-1.1"))
    assert got["Parameter"]["Value"] == "v1"
    assert rest["id"] in {a["id"] for a in _ok(client.get("/restapis")).get("item", [])}


def _signed(svc):
    return {"authorization": f"AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/{svc}/aws4_request, "
                             "SignedHeaders=host, Signature=0"}


def test_aws_dax_dlm_ram_cfn_pipes_survive_restart(client):
    """The cores the offline appliance used to leave on the router's IN-MEMORY defaults (or not
    route at all): DAX, DLM, RAM, CloudFormation and EventBridge Pipes."""
    tag = uuid.uuid4().hex[:6]
    j11 = "application/x-amz-json-1.1"
    _ok(client.post("/", content=json.dumps({"SubnetGroupName": "dax" + tag, "SubnetIds": ["subnet-1"]}),
                    headers={"x-amz-target": "AmazonDAXV3.CreateSubnetGroup", "content-type": j11, **_signed("dax")}))
    share = _ok(client.post("/", content=json.dumps({"name": "share" + tag}),
                            headers={"x-amz-target": "AWSRAMFrontendService.CreateResourceShare",
                                     "content-type": j11, **_signed("ram")}))["resourceShare"]["resourceShareArn"]
    pol = _ok(client.post("/policies", content=json.dumps({"Description": "d" + tag, "State": "DISABLED", "PolicyDetails": {
        "ResourceTypes": ["VOLUME"], "TargetTags": [{"Key": "k", "Value": tag}],
        "Schedules": [{"Name": "s", "CreateRule": {"Interval": 12, "IntervalUnit": "HOURS"}, "RetainRule": {"Count": 1}}]}}),
        headers={"content-type": "application/json", **_signed("dlm")}))["PolicyId"]
    stack = "st" + tag
    tpl = json.dumps({"Resources": {"Q": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": "cfnq" + tag}}}})
    r = client.post("/", content=f"Action=CreateStack&StackName={stack}&TemplateBody={tpl}",
                    headers={"content-type": "application/x-www-form-urlencoded", **_signed("cloudformation")})
    assert r.status_code == 200, r.text[:300]
    pipe = "pipe" + tag
    _ok(client.post(f"/v1/pipes/{pipe}", content=json.dumps({
        "Source": "arn:aws:sqs:us-east-1:000000000000:a", "Target": "arn:aws:sqs:us-east-1:000000000000:b"}),
        headers={"content-type": "application/json", **_signed("pipes")}))
    _restart()
    sgs = _ok(client.post("/", content="{}", headers={"x-amz-target": "AmazonDAXV3.DescribeSubnetGroups",
                                                      "content-type": j11, **_signed("dax")}))["SubnetGroups"]
    assert "dax" + tag in {g["SubnetGroupName"] for g in sgs}
    shares = _ok(client.post("/", content=json.dumps({"resourceOwner": "SELF"}), headers={
        "x-amz-target": "AWSRAMFrontendService.GetResourceShares", "content-type": j11, **_signed("ram")}))["resourceShares"]
    assert share in {x["resourceShareArn"] for x in shares}
    pols = _ok(client.get("/policies", headers=_signed("dlm")))["Policies"]
    assert pol in {x["PolicyId"] for x in pols}
    r = client.post("/", content="Action=ListStacks", headers={"content-type": "application/x-www-form-urlencoded",
                                                               **_signed("cloudformation")})
    assert f"<StackName>{stack}</StackName>" in r.text
    pipes = _ok(client.get("/v1/pipes", headers=_signed("pipes")))["Pipes"]
    assert pipe in {x["Name"] for x in pipes}


# ── Azure: RBAC (role assignments) + Azure SQL (catalog AND rows) ──────────────────────

def test_azure_rbac_and_sql_survive_restart(client):
    ra = str(uuid.uuid4())
    _ok(client.put(f"/providers/Microsoft.Authorization/roleAssignments/{ra}", json={"properties": {
        "principalId": "user-1", "roleName": "Reader", "scope": "/"}}), 200, 201)
    srv, db = "srv" + uuid.uuid4().hex[:6], "appdb"
    _ok(client.put(f"/azure-sql/servers/{srv}"), 200, 201)
    _ok(client.put(f"/azure-sql/servers/{srv}/databases/{db}"), 200, 201)
    q = f"/azure-sql/servers/{srv}/databases/{db}/query"
    _ok(client.post(q, json={"sql": "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)"}))
    _ok(client.post(q, json={"sql": "INSERT INTO t (name) VALUES (?)", "params": ["alice"]}))
    _restart()
    ras = _ok(client.get("/providers/Microsoft.Authorization/roleAssignments")).get("value", [])
    assert ra in {a.get("name") for a in ras}
    assert db in _names(_ok(client.get(f"/azure-sql/servers/{srv}/databases")).get("value"))
    rows = _ok(client.post(q, json={"sql": "SELECT name FROM t"}))
    assert "alice" in json.dumps(rows)


def test_whole_state_stays_serializable(client):
    """One non-JSON object anywhere in the state breaks every save."""
    from core import app_context as ctx
    from core.vyomi_platform import _encode_state_value
    json.dumps(_encode_state_value(ctx.STATE), sort_keys=True)


def test_inventory_reads_each_space_slot(client):
    """The CloudSim inventory lists a space's core resources from THAT space's slot."""
    cl = "inv" + uuid.uuid4().hex[:6]
    _ok(client.post(L + "/clusters", json={"cluster": {"name": cl, "initialNodeCount": 1}}))
    from core import app_context as ctx
    spaces = (ctx.STATE.get("spaces") or {}).get("spaces") or {}
    gcp = [s for s in spaces.values() if isinstance(s, dict) and (s.get("service_states") or {}).get("gcp_container_core")]
    assert gcp, "the cluster is not in a GCP space's slot"
    found = {r.get("name") for sp in gcp for r in server._cloudsim_collect_resources(sp)[0]}
    assert cl in found
    others = [s for s in spaces.values() if isinstance(s, dict) and s not in gcp]
    assert all(cl not in {r.get("name") for r in server._cloudsim_collect_resources(sp)[0]} for sp in others)
