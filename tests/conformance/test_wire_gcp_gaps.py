"""GCP wire gaps closed by core/gcp_wire_ext (+ gcp_functions_core, gcp_dns_core, gcp_scc_v1_core).

Every call is made with the REAL Google API client (googleapiclient, built from its bundled discovery documents), pointed at the
in-process wire router through a transport shim -- the same request URLs, verbs, query strings and JSON bodies google-api-python-client,
the Cloud client libraries and gcloud put on the wire.  State round-trips (create -> get/list -> mutate -> delete) prove the answers come
from engine state, not canned bodies.
"""
import io
import json
import zipfile
from urllib.parse import parse_qsl, urlparse

import pytest

httplib2 = pytest.importorskip("httplib2")
discovery = pytest.importorskip("googleapiclient.discovery")
from googleapiclient.errors import HttpError  # noqa: E402

from core.aws_wire_router import AwsWireRouter  # noqa: E402

PROJECT = "vyomi-project"


class RouterHttp(httplib2.Http):
    """httplib2 transport that hands every request to the in-process router."""

    def __init__(self, router):
        super().__init__()
        self.router = router

    def request(self, uri, method="GET", body=None, headers=None, redirections=5, connection_type=None):
        u = urlparse(uri)
        q = dict(parse_qsl(u.query, keep_blank_values=True))
        if isinstance(body, str):
            body = body.encode()
        hdrs = {"host": "localhost:8099"}
        hdrs.update({k.lower(): v for k, v in (headers or {}).items()})
        out = self.router.handle(method, u.path + ("?" + u.query if u.query else ""), q, hdrs, body or b"")
        ct = (out.get("headers") or {}).get("content-type", "application/json")
        return httplib2.Response({"status": str(out["status"]), "content-type": ct}), out["body"]


@pytest.fixture()
def router():
    r = AwsWireRouter()
    r.STRICT_GCP_PROJECT = False
    return r


def api(router, name, ver):
    return discovery.build(name, ver, http=RouterHttp(router), static_discovery=True)


def zip_of(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return b.getvalue()


def raw(router, method, url, body=b"", headers=None):
    return RouterHttp(router).request(url, method, body, headers)


MAIN_PY = '''import functions_framework

@functions_framework.http
def hello(request):
    name = request.args.get("name", "world")
    print("greeting " + name)
    return "Hello, " + name + "!"

def on_event(event):
    return {"got": event}
'''


# ───────────────────────────── Cloud DNS ─────────────────────────────
def test_dns_zone_records_changes_policies(router):
    dns = api(router, "dns", "v1")
    z = dns.managedZones().create(project=PROJECT, body={"name": "z1", "dnsName": "example.test.", "description": "d"}).execute()
    assert z["dnsName"] == "example.test." and len(z["nameServers"]) == 4 and z["id"]
    with pytest.raises(HttpError) as e:
        dns.managedZones().create(project=PROJECT, body={"name": "z1", "dnsName": "other.test."}).execute()
    assert e.value.resp.status == 409
    assert [x["name"] for x in dns.managedZones().list(project=PROJECT).execute()["managedZones"]] == ["z1"]
    rr = dns.resourceRecordSets().list(project=PROJECT, managedZone="z1").execute()["rrsets"]
    assert {r["type"] for r in rr} == {"NS", "SOA"}
    soa0 = next(r for r in rr if r["type"] == "SOA")["rrdatas"][0]
    ch = dns.changes().create(project=PROJECT, managedZone="z1", body={"additions": [
        {"name": "www.example.test.", "type": "A", "ttl": 60, "rrdatas": ["10.1.2.3"]}]}).execute()
    assert ch["status"] == "done" and ch["id"] == "1"
    rr = dns.resourceRecordSets().list(project=PROJECT, managedZone="z1", name="www.example.test.", type="A").execute()["rrsets"]
    assert rr[0]["rrdatas"] == ["10.1.2.3"] and rr[0]["ttl"] == 60
    soa1 = next(r for r in dns.resourceRecordSets().list(project=PROJECT, managedZone="z1").execute()["rrsets"] if r["type"] == "SOA")["rrdatas"][0]
    assert soa1 != soa0 and int(soa1.split()[2]) > int(soa0.split()[2])   # every change bumps the SOA serial
    # atomicity: a change whose second part fails changes nothing
    with pytest.raises(HttpError) as e:
        dns.changes().create(project=PROJECT, managedZone="z1", body={"additions": [
            {"name": "ok.example.test.", "type": "A", "ttl": 60, "rrdatas": ["10.0.0.1"]},
            {"name": "www.example.test.", "type": "A", "ttl": 60, "rrdatas": ["10.0.0.2"]}]}).execute()
    assert e.value.resp.status == 409
    names = {r["name"] for r in dns.resourceRecordSets().list(project=PROJECT, managedZone="z1").execute()["rrsets"]}
    assert "ok.example.test." not in names
    with pytest.raises(HttpError) as e:   # deleting a record that does not match exactly
        dns.changes().create(project=PROJECT, managedZone="z1", body={"deletions": [
            {"name": "www.example.test.", "type": "A", "ttl": 60, "rrdatas": ["9.9.9.9"]}]}).execute()
    assert e.value.resp.status == 412
    with pytest.raises(HttpError) as e:   # a zone with records cannot be deleted
        dns.managedZones().delete(project=PROJECT, managedZone="z1").execute()
    assert e.value.resp.status == 400
    assert dns.changes().get(project=PROJECT, managedZone="z1", changeId="1").execute()["additions"][0]["name"] == "www.example.test."
    assert len(dns.changes().list(project=PROJECT, managedZone="z1").execute()["changes"]) == 1
    dns.resourceRecordSets().patch(project=PROJECT, managedZone="z1", name="www.example.test.", type="A", body={"ttl": 120, "rrdatas": ["10.1.2.4"]}).execute()
    assert dns.resourceRecordSets().get(project=PROJECT, managedZone="z1", name="www.example.test.", type="A").execute()["rrdatas"] == ["10.1.2.4"]
    dns.resourceRecordSets().delete(project=PROJECT, managedZone="z1", name="www.example.test.", type="A").execute()
    dns.managedZones().patch(project=PROJECT, managedZone="z1", body={"description": "new"}).execute()
    assert dns.managedZones().get(project=PROJECT, managedZone="z1").execute()["description"] == "new"
    dns.managedZones().delete(project=PROJECT, managedZone="z1").execute()
    assert dns.managedZones().list(project=PROJECT).execute()["managedZones"] == []
    # DNSSEC keys, policies, response policies + rules, project quota
    dns.managedZones().create(project=PROJECT, body={"name": "sec", "dnsName": "sec.test.", "dnssecConfig": {"state": "on"}}).execute()
    keys = dns.dnsKeys().list(project=PROJECT, managedZone="sec").execute()["dnsKeys"]
    assert {k["type"] for k in keys} == {"keySigning", "zoneSigning"}
    assert dns.dnsKeys().get(project=PROJECT, managedZone="sec", dnsKeyId=keys[0]["id"]).execute()["id"] == keys[0]["id"]
    dns.policies().create(project=PROJECT, body={"name": "p1", "enableLogging": True}).execute()
    assert dns.policies().get(project=PROJECT, policy="p1").execute()["enableLogging"] is True
    dns.policies().patch(project=PROJECT, policy="p1", body={"enableLogging": False}).execute()
    assert dns.policies().list(project=PROJECT).execute()["policies"][0]["enableLogging"] is False
    dns.policies().delete(project=PROJECT, policy="p1").execute()
    dns.responsePolicies().create(project=PROJECT, body={"responsePolicyName": "rp1"}).execute()
    dns.responsePolicyRules().create(project=PROJECT, responsePolicy="rp1", body={"ruleName": "r1", "dnsName": "blocked.test.", "behavior": "bypassResponsePolicy"}).execute()
    assert dns.responsePolicyRules().list(project=PROJECT, responsePolicy="rp1").execute()["responsePolicyRules"][0]["ruleName"] == "r1"
    with pytest.raises(HttpError) as e:
        dns.responsePolicies().delete(project=PROJECT, responsePolicy="rp1").execute()
    assert e.value.resp.status == 400
    dns.responsePolicyRules().delete(project=PROJECT, responsePolicy="rp1", responsePolicyRule="r1").execute()
    dns.responsePolicies().delete(project=PROJECT, responsePolicy="rp1").execute()
    assert dns.projects().get(project=PROJECT).execute()["quota"]["managedZones"] > 0
    assert dns.managedZoneOperations().list(project=PROJECT, managedZone="sec").execute()["operations"] is not None


# ───────────────────────────── Cloud Functions ─────────────────────────────
def _upload(router, cf, loc, files):
    up = cf.projects().locations().functions().generateUploadUrl(parent="projects/%s/locations/%s" % (PROJECT, loc), body={}).execute()
    resp, _ = raw(router, "PUT", up["uploadUrl"], zip_of(files), {"content-type": "application/zip"})
    assert resp.status == 200
    return up


def test_functions_v2_deploy_run_patch_delete(router):
    cf = api(router, "cloudfunctions", "v2")
    loc = "us-central1"
    parent = "projects/%s/locations/%s" % (PROJECT, loc)
    up = _upload(router, cf, loc, {"main.py": MAIN_PY, "requirements.txt": ""})
    body = {"environment": "GEN_2", "buildConfig": {"runtime": "python312", "entryPoint": "hello", "source": {"storageSource": up["storageSource"]}},
            "serviceConfig": {"availableMemory": "512M", "timeoutSeconds": 30, "environmentVariables": {"A": "1"}}}
    op = cf.projects().locations().functions().create(parent=parent, functionId="hello", body=body).execute()
    assert op["done"] and op["name"].startswith(parent + "/operations/")
    assert cf.projects().locations().operations().get(name=op["name"]).execute()["done"]
    fn = cf.projects().locations().functions().get(name=parent + "/functions/hello").execute()
    assert fn["state"] == "ACTIVE" and fn["environment"] == "GEN_2" and fn["serviceConfig"]["availableMemory"] == "512M"
    assert fn["buildConfig"]["runtime"] == "python312" and fn["url"].endswith("/gcf/%s/%s/hello" % (PROJECT, loc))
    assert [f["name"] for f in cf.projects().locations().functions().list(parent=parent).execute()["functions"]] == [parent + "/functions/hello"]
    with pytest.raises(HttpError) as e:
        cf.projects().locations().functions().create(parent=parent, functionId="hello", body=body).execute()
    assert e.value.resp.status == 409
    # the function is a Cloud Run service (gen2), listed there too
    assert any(k.endswith("/services/hello") for k in router.gcp_run.services)
    # its HTTPS URL runs the uploaded code -- IAM invoker policy applies
    resp, out = raw(router, "GET", fn["url"] + "?name=Vyomi")
    assert resp.status == 403
    pol = cf.projects().locations().functions().getIamPolicy(resource=parent + "/functions/hello").execute()
    pol["bindings"] = [{"role": "roles/cloudfunctions.invoker", "members": ["allUsers"]}]
    cf.projects().locations().functions().setIamPolicy(resource=parent + "/functions/hello", body={"policy": pol}).execute()
    assert cf.projects().locations().functions().getIamPolicy(resource=parent + "/functions/hello").execute()["bindings"][0]["role"] == "roles/cloudfunctions.invoker"
    resp, out = raw(router, "GET", fn["url"] + "?name=Vyomi")
    assert resp.status == 200 and out == b"Hello, Vyomi!"
    # patch: new source -> new revision runs the new code
    up2 = _upload(router, cf, loc, {"main.py": MAIN_PY.replace("Hello, ", "Bonjour, ")})
    cf.projects().locations().functions().patch(name=parent + "/functions/hello", updateMask="buildConfig",
                                                body={"buildConfig": {"source": {"storageSource": up2["storageSource"]}}}).execute()
    resp, out = raw(router, "GET", fn["url"] + "?name=Z")
    assert out == b"Bonjour, Z!"
    # bad source is rejected like a failed build
    bad = _upload(router, cf, loc, {"main.py": "def other(r):\n  return 1\n"})
    with pytest.raises(HttpError) as e:
        cf.projects().locations().functions().create(parent=parent, functionId="broken", body=dict(body, buildConfig={"runtime": "python312", "entryPoint": "hello", "source": {"storageSource": bad["storageSource"]}})).execute()
    assert e.value.resp.status == 400
    assert cf.projects().locations().functions().generateDownloadUrl(name=parent + "/functions/hello", body={}).execute()["downloadUrl"]
    assert len(cf.projects().locations().runtimes().list(parent=parent).execute()["runtimes"]) > 5
    cf.projects().locations().functions().delete(name=parent + "/functions/hello").execute()
    with pytest.raises(HttpError) as e:
        cf.projects().locations().functions().get(name=parent + "/functions/hello").execute()
    assert e.value.resp.status == 404
    assert not any(k.endswith("/services/hello") for k in router.gcp_run.services)


def test_functions_v1_deploy_call_and_event_trigger(router):
    cf = api(router, "cloudfunctions", "v1")
    cf2 = api(router, "cloudfunctions", "v2")
    parent = "projects/%s/locations/us-central1" % PROJECT
    up = cf.projects().locations().functions().generateUploadUrl(parent=parent, body={}).execute()
    resp, _ = raw(router, "PUT", up["uploadUrl"], zip_of({"main.py": MAIN_PY}), {"content-type": "application/zip"})
    assert resp.status == 200
    op = cf.projects().locations().functions().create(location=parent, body={
        "name": parent + "/functions/v1fn", "runtime": "python311", "entryPoint": "hello", "sourceUploadUrl": up["uploadUrl"], "httpsTrigger": {},
        "availableMemoryMb": 256, "timeout": "20s", "environmentVariables": {"K": "v"}}).execute()
    assert op["done"] and op["name"].startswith("operations/")
    assert cf.operations().get(name=op["name"]).execute()["done"]
    fn = cf.projects().locations().functions().get(name=parent + "/functions/v1fn").execute()
    assert fn["status"] == "ACTIVE" and fn["httpsTrigger"]["url"].endswith("/v1fn") and fn["timeout"] == "20s"
    out = cf.projects().locations().functions().call(name=parent + "/functions/v1fn", body={"data": "{}"}).execute()
    assert out["result"].startswith("Hello, world") and out["executionId"]
    assert [f["name"] for f in cf.projects().locations().functions().list(parent=parent).execute()["functions"]] == [parent + "/functions/v1fn"]
    # the same function is visible through the v2 API (one object, two wires)
    assert cf2.projects().locations().functions().get(name=parent + "/functions/v1fn").execute()["environment"] == "GEN_1"
    cf.projects().locations().functions().patch(name=parent + "/functions/v1fn", updateMask="availableMemoryMb", body={"availableMemoryMb": 512}).execute()
    assert cf.projects().locations().functions().get(name=parent + "/functions/v1fn").execute()["availableMemoryMb"] == 512
    # event trigger: Pub/Sub topic must exist, then it is a real Eventarc trigger on the function's service
    with pytest.raises(HttpError) as e:
        cf.projects().locations().functions().create(location=parent, body={
            "name": parent + "/functions/ev", "runtime": "python311", "entryPoint": "on_event", "sourceUploadUrl": up["uploadUrl"],
            "eventTrigger": {"eventType": "google.pubsub.topic.publish", "resource": "projects/%s/topics/nope" % PROJECT}}).execute()
    assert e.value.resp.status == 400
    resp, _ = raw(router, "PUT", "http://localhost:8099/pubsub/v1/projects/%s/topics/t1" % PROJECT)
    resp, body = raw(router, "PUT", "http://localhost:8099/v1/projects/%s/topics/t1" % PROJECT, b"{}", {"content-type": "application/json"})
    cf.projects().locations().functions().create(location=parent, body={
        "name": parent + "/functions/ev", "runtime": "python311", "entryPoint": "on_event", "sourceUploadUrl": up["uploadUrl"],
        "eventTrigger": {"eventType": "google.pubsub.topic.publish", "resource": "projects/%s/topics/t1" % PROJECT}}).execute()
    assert any("/services/ev/triggers/" in k for k in router.gcp_run.triggers)
    res = cf.projects().locations().functions().call(name=parent + "/functions/ev", body={"data": json.dumps({"a": 1})}).execute()
    assert json.loads(res["result"]) == {"got": {"a": 1}}
    cf.projects().locations().functions().delete(name=parent + "/functions/ev").execute()
    assert not any("/services/ev/triggers/" in k for k in router.gcp_run.triggers)
    cf.projects().locations().functions().delete(name=parent + "/functions/v1fn").execute()
    assert cf.projects().locations().functions().list(parent=parent).execute().get("functions", []) == []


def test_functions_v2_upgrade_state_machine(router):
    cf = api(router, "cloudfunctions", "v2")
    parent = "projects/%s/locations/us-central1" % PROJECT
    up = _upload(router, cf, "us-central1", {"main.py": MAIN_PY})
    cf.projects().locations().functions().create(parent=parent, functionId="old", body={
        "environment": "GEN_1", "buildConfig": {"runtime": "python311", "entryPoint": "hello", "source": {"storageSource": up["storageSource"]}}}).execute()
    name = parent + "/functions/old"
    with pytest.raises(HttpError):   # redirect before setup is refused
        cf.projects().locations().functions().redirectFunctionUpgradeTraffic(name=name, body={}).execute()
    for step in ("setupFunctionUpgradeConfig", "redirectFunctionUpgradeTraffic", "commitFunctionUpgrade"):
        assert getattr(cf.projects().locations().functions(), step)(name=name, body={}).execute()["done"]
    assert cf.projects().locations().functions().get(name=name).execute()["environment"] == "GEN_2"


# ───────────────────────────── Security Command Center v1 ─────────────────────────────
def test_scc_v1_sources_findings_marks_mutes_assets(router):
    scc = api(router, "securitycenter", "v1")
    org = "organizations/1234567890"
    srcs = scc.organizations().sources().list(parent=org).execute()["sources"]
    assert {"Security Health Analytics", "Event Threat Detection"} <= {s["displayName"] for s in srcs}
    s = scc.organizations().sources().create(parent=org, body={"displayName": "my-scanner", "description": "d"}).execute()
    src = s["name"]
    f = scc.organizations().sources().findings().create(parent=src, findingId="f1", body={
        "resourceName": "//compute.googleapis.com/projects/p/zones/z/instances/i", "category": "OPEN_PORT", "state": "ACTIVE",
        "severity": "HIGH", "eventTime": "2026-01-01T00:00:00Z", "findingClass": "MISCONFIGURATION"}).execute()
    assert f["name"] == src + "/findings/f1"
    got = scc.organizations().sources().findings().list(parent=src).execute()
    assert got["totalSize"] == 1 and got["listFindingsResults"][0]["finding"]["category"] == "OPEN_PORT"
    scc.organizations().sources().findings().setState(name=f["name"], body={"state": "INACTIVE"}).execute()
    assert scc.organizations().sources().findings().list(parent=src, filter='state="ACTIVE"').execute()["totalSize"] == 0
    scc.organizations().sources().findings().setMute(name=f["name"], body={"mute": "MUTED"}).execute()
    grp = scc.organizations().sources().findings().group(parent=src, body={"groupBy": "category"}).execute()
    assert grp["groupByResults"][0]["properties"]["category"] == "OPEN_PORT"
    sm = scc.organizations().sources().findings().updateSecurityMarks(name=f["name"] + "/securityMarks", updateMask="marks.owner", body={"marks": {"owner": "me"}}).execute()
    assert sm["marks"] == {"owner": "me"}
    # mute config: v1 names have no /locations/
    mc = scc.organizations().muteConfigs().create(parent=org, muteConfigId="m1", body={"filter": 'category="OPEN_PORT"', "description": "x"}).execute()
    assert mc["name"] == org + "/muteConfigs/m1"
    assert scc.organizations().muteConfigs().get(name=mc["name"]).execute()["filter"] == 'category="OPEN_PORT"'
    assert len(scc.organizations().muteConfigs().list(parent=org).execute()["muteConfigs"]) == 1
    scc.organizations().muteConfigs().patch(name=mc["name"], body={"description": "y"}).execute()
    scc.organizations().muteConfigs().delete(name=mc["name"]).execute()
    # the same finding is visible through the v2 engine (one state)
    _r, v2raw = raw(router, "GET", "https://securitycenter.googleapis.com/v2/%s/findings" % src)
    assert json.loads(v2raw)["listFindingsResults"][0]["finding"]["mute"] == "MUTED"
    # assets come from live simulator state
    raw(router, "POST", "https://storage.googleapis.com/storage/v1/b?project=" + PROJECT, json.dumps({"name": "scc-asset-bucket"}).encode(), {"content-type": "application/json"})
    assets = scc.organizations().assets().list(parent=org).execute()
    names = [a["asset"]["securityCenterProperties"]["resourceName"] for a in assets["listAssetsResults"]]
    assert "//storage.googleapis.com/scc-asset-bucket" in names
    a0 = next(a["asset"] for a in assets["listAssetsResults"] if a["asset"]["securityCenterProperties"]["resourceName"].endswith("scc-asset-bucket"))
    g = scc.organizations().assets().group(parent=org, body={"groupBy": "securityCenterProperties.resourceType"}).execute()
    assert any(r["properties"]["securityCenterProperties.resourceType"] == "google.cloud.storage.Bucket" for r in g["groupByResults"])
    mk = scc.organizations().assets().updateSecurityMarks(name=a0["name"] + "/securityMarks", updateMask="marks.env", body={"marks": {"env": "prod"}}).execute()
    assert mk["marks"] == {"env": "prod"}
    assert scc.organizations().assets().list(parent=org, filter='securityCenterProperties.resourceType="google.cloud.storage.Bucket"').execute()["totalSize"] >= 1
    assert scc.organizations().assets().runDiscovery(parent=org, body={}).execute()["done"]


# ───────────────────────────── schema-driven store: Logging / IAM / Network Management / Compute ─────────────────────────────
def test_logging_folder_org_scopes_crud(router):
    lg = api(router, "logging", "v2")
    for scope in ("folders/111", "organizations/222", "billingAccounts/AAAAAA-BBBBBB-CCCCCC"):
        ex = getattr(lg, scope.split("/")[0])().exclusions()
        e = ex.create(parent=scope, body={"name": "drop-debug", "filter": "severity<INFO"}).execute()
        assert e["name"] == scope + "/exclusions/drop-debug"
        with pytest.raises(HttpError) as err:
            ex.create(parent=scope, body={"name": "drop-debug", "filter": "x"}).execute()
        assert err.value.resp.status == 409
        ex.patch(name=e["name"], updateMask="disabled", body={"disabled": True}).execute()
        assert ex.get(name=e["name"]).execute()["disabled"] is True
        assert [x["name"] for x in ex.list(parent=scope).execute()["exclusions"]] == [e["name"]]
        ex.delete(name=e["name"]).execute()
        with pytest.raises(HttpError) as err:
            ex.get(name=e["name"]).execute()
        assert err.value.resp.status == 404
    sinks = lg.organizations().sinks()
    s = sinks.create(parent="organizations/222", body={"name": "to-bq", "destination": "bigquery.googleapis.com/projects/p/datasets/d", "filter": "severity>=ERROR"}).execute()
    assert sinks.get(sinkName=s["name"]).execute()["filter"] == "severity>=ERROR"
    sinks.update(sinkName=s["name"], body={"destination": s["destination"], "filter": "severity>=WARNING"}).execute()
    assert sinks.list(parent="organizations/222").execute()["sinks"][0]["filter"] == "severity>=WARNING"
    sinks.delete(sinkName=s["name"]).execute()
    # project-level exclusions + saved queries + log scopes + buckets/views at org
    ex = lg.projects().exclusions()
    ex.create(parent="projects/" + PROJECT, body={"name": "px", "filter": "severity<INFO"}).execute()
    assert ex.get(name="projects/%s/exclusions/px" % PROJECT).execute()["filter"] == "severity<INFO"
    q = lg.projects().locations().savedQueries()
    sq = q.create(parent="projects/%s/locations/global" % PROJECT, savedQueryId="sq1", body={"displayName": "errors", "loggingQuery": {"filter": "severity>=ERROR"}, "visibility": "PRIVATE"}).execute()
    assert q.list(parent="projects/%s/locations/global" % PROJECT).execute()["savedQueries"][0]["displayName"] == "errors"
    q.delete(name=sq["name"]).execute()
    b = lg.organizations().locations().buckets()
    bk = b.create(parent="organizations/222/locations/global", bucketId="audit", body={"retentionDays": 90}).execute()
    assert bk["retentionDays"] == 90
    v = lg.organizations().locations().buckets().views()
    v.create(parent=bk["name"], viewId="v1", body={"filter": "severity>=ERROR"}).execute()
    assert v.list(parent=bk["name"]).execute()["views"][0]["filter"] == "severity>=ERROR"
    with pytest.raises(HttpError) as err:
        v.create(parent="organizations/222/locations/global/buckets/ghost", viewId="v1", body={}).execute()
    assert err.value.resp.status == 404
    b.delete(name=bk["name"]).execute()
    assert lg.folders().locations().buckets().list(parent="folders/111/locations/global").execute().get("buckets", []) == []


def test_iam_oauth_clients_and_workload_identity_extras(router):
    iam = api(router, "iam", "v1")
    parent = "projects/%s/locations/global" % PROJECT
    oc = iam.projects().locations().oauthClients()
    c = oc.create(parent=parent, oauthClientId="web1", body={"clientType": "CONFIDENTIAL_CLIENT", "allowedGrantTypes": ["AUTHORIZATION_CODE_GRANT"],
                                                            "allowedScopes": ["https://www.googleapis.com/auth/cloud-platform"], "allowedRedirectUris": ["https://x.test/cb"]}).execute()
    assert c["name"] == parent + "/oauthClients/web1"
    cred = iam.projects().locations().oauthClients().credentials().create(parent=c["name"], oauthClientCredentialId="cred1", body={"displayName": "k"}).execute()
    assert cred["name"].endswith("/credentials/cred1")
    assert len(iam.projects().locations().oauthClients().credentials().list(parent=c["name"]).execute()["oauthClientCredentials"]) == 1
    with pytest.raises(HttpError) as e:
        iam.projects().locations().oauthClients().credentials().create(parent=parent + "/oauthClients/ghost", oauthClientCredentialId="c", body={}).execute()
    assert e.value.resp.status == 404
    oc.patch(name=c["name"], updateMask="displayName", body={"displayName": "Web"}).execute()
    assert oc.get(name=c["name"]).execute()["displayName"] == "Web"
    assert oc.list(parent=parent).execute()["oauthClients"][0]["displayName"] == "Web"
    oc.delete(name=c["name"]).execute()
    # workforce pools + providers + keys (org-level resource, global location)
    wp = iam.locations().workforcePools()
    p = wp.create(location="locations/global", workforcePoolId="wf1", body={"parent": "organizations/222", "displayName": "wf"}).execute()
    assert p.get("done", True)
    got = wp.get(name="locations/global/workforcePools/wf1").execute()
    assert got["parent"] == "organizations/222"
    prov = iam.locations().workforcePools().providers()
    prov.create(parent="locations/global/workforcePools/wf1", workforcePoolProviderId="okta", body={"displayName": "okta", "attributeMapping": {"google.subject": "assertion.sub"},
                                                                                                   "oidc": {"issuerUri": "https://x.okta.test", "clientId": "c"}}).execute()
    assert prov.get(name="locations/global/workforcePools/wf1/providers/okta").execute()["oidc"]["issuerUri"] == "https://x.okta.test"
    assert len(prov.list(parent="locations/global/workforcePools/wf1").execute()["workforcePoolProviders"]) == 1
    prov.delete(name="locations/global/workforcePools/wf1/providers/okta").execute()
    wp.delete(name="locations/global/workforcePools/wf1").execute()


def test_network_management_flow_logs_and_compute_firewall_policies(router):
    nm = api(router, "networkmanagement", "v1")
    parent = "projects/%s/locations/global" % PROJECT
    c = nm.projects().locations().vpcFlowLogsConfigs()
    op = c.create(parent=parent, vpcFlowLogsConfigId="fl1", body={"state": "ENABLED", "aggregationInterval": "INTERVAL_5_SEC",
                                                                   "network": "projects/%s/global/networks/default" % PROJECT}).execute()
    assert op["done"] if "done" in op else True
    assert c.get(name=parent + "/vpcFlowLogsConfigs/fl1").execute()["state"] == "ENABLED"
    c.patch(name=parent + "/vpcFlowLogsConfigs/fl1", updateMask="state", body={"state": "DISABLED"}).execute()
    assert c.list(parent=parent).execute()["vpcFlowLogsConfigs"][0]["state"] == "DISABLED"
    c.delete(name=parent + "/vpcFlowLogsConfigs/fl1").execute()
    comp = api(router, "compute", "v1")
    fp = comp.networkFirewallPolicies()
    op = fp.insert(project=PROJECT, body={"name": "pol1", "description": "d"}).execute()
    assert op["status"] == "DONE" and op["kind"] == "compute#operation"
    assert comp.globalOperations().get(project=PROJECT, operation=op["name"]).execute()["status"] == "DONE"
    assert fp.get(project=PROJECT, firewallPolicy="pol1").execute()["name"] == "pol1"
    fp.patch(project=PROJECT, firewallPolicy="pol1", body={"description": "new"}).execute()
    assert fp.list(project=PROJECT).execute()["items"][0]["description"] == "new"
    fp.setIamPolicy(project=PROJECT, resource="pol1", body={"bindings": [{"role": "roles/viewer", "members": ["user:a@x.test"]}]}).execute()
    assert fp.getIamPolicy(project=PROJECT, resource="pol1").execute()["bindings"][0]["role"] == "roles/viewer"
    with pytest.raises(HttpError) as e:
        fp.get(project=PROJECT, firewallPolicy="ghost").execute()
    assert e.value.resp.status == 404
    fp.delete(project=PROJECT, firewallPolicy="pol1").execute()
    assert fp.list(project=PROJECT).execute().get("items", []) == []


# ───────────────────────────── Compute: real mutations on the VM store ─────────────────────────────
def test_compute_disks_images_snapshots_instances_fill(router):
    c = api(router, "compute", "v1")
    z = "us-central1-a"
    c.disks().insert(project=PROJECT, zone=z, body={"name": "d1", "sizeGb": "10"}).execute()
    c.disks().insert(project=PROJECT, zone=z, body={"name": "d2", "sizeGb": "20"}).execute()
    # resize: grow only, and the record really changes
    c.disks().resize(project=PROJECT, zone=z, disk="d1", body={"sizeGb": "30"}).execute()
    assert c.disks().get(project=PROJECT, zone=z, disk="d1").execute()["sizeGb"] == "30"
    with pytest.raises(HttpError) as e:
        c.disks().resize(project=PROJECT, zone=z, disk="d1", body={"sizeGb": "5"}).execute()
    assert e.value.resp.status == 400
    c.disks().setLabels(project=PROJECT, zone=z, resource="d1", body={"labels": {"env": "dev"}, "labelFingerprint": ""}).execute()
    d1 = c.disks().get(project=PROJECT, zone=z, disk="d1").execute()
    assert d1["labels"] == {"env": "dev"}
    with pytest.raises(HttpError) as e:   # stale fingerprint is refused
        c.disks().setLabels(project=PROJECT, zone=z, resource="d1", body={"labels": {}, "labelFingerprint": "stale"}).execute()
    assert e.value.resp.status == 412
    c.disks().setIamPolicy(project=PROJECT, zone=z, resource="d1", body={"policy": {"bindings": [{"role": "roles/compute.storageAdmin", "members": ["user:a@x.test"]}]}}).execute()
    assert c.disks().getIamPolicy(project=PROJECT, zone=z, resource="d1").execute()["bindings"][0]["members"] == ["user:a@x.test"]
    # snapshot + image of the disk, then labels / deprecate / family
    c.disks().createSnapshot(project=PROJECT, zone=z, disk="d1", body={"name": "s1"}).execute()
    c.snapshots().setLabels(project=PROJECT, resource="s1", body={"labels": {"k": "v"}, "labelFingerprint": ""}).execute()
    assert c.snapshots().get(project=PROJECT, snapshot="s1").execute()["labels"] == {"k": "v"}
    c.images().insert(project=PROJECT, body={"name": "img-v1", "sourceDisk": "zones/%s/disks/d1" % z, "family": "fam"}).execute()
    c.images().insert(project=PROJECT, body={"name": "img-v2", "sourceDisk": "zones/%s/disks/d1" % z, "family": "fam"}).execute()
    assert c.images().getFromFamily(project=PROJECT, family="fam").execute()["name"] == "img-v2"
    c.images().deprecate(project=PROJECT, image="img-v2", body={"state": "DEPRECATED", "replacement": "projects/%s/global/images/img-v1" % PROJECT}).execute()
    assert c.images().getFromFamily(project=PROJECT, family="fam").execute()["name"] == "img-v1"
    assert c.images().get(project=PROJECT, image="img-v2").execute()["deprecated"]["state"] == "DEPRECATED"
    # instances: attach/detach a disk for real, access configs, scheduling, service account (stopped only)
    c.instances().insert(project=PROJECT, zone=z, body={"name": "vm1", "machineType": "zones/%s/machineTypes/e2-micro" % z,
                                                        "disks": [{"boot": True, "autoDelete": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}],
                                                        "networkInterfaces": [{"network": "global/networks/default"}]}).execute()
    c.instances().attachDisk(project=PROJECT, zone=z, instance="vm1", body={"source": "zones/%s/disks/d2" % z, "deviceName": "data"}).execute()
    vm = c.instances().get(project=PROJECT, zone=z, instance="vm1").execute()
    assert any(d.get("deviceName") == "data" for d in vm["disks"])
    with pytest.raises(HttpError) as e:   # a second instance cannot take a disk that is in use
        c.instances().attachDisk(project=PROJECT, zone=z, instance="vm1", body={"source": "zones/%s/disks/d2" % z, "deviceName": "data2"}).execute()
    assert e.value.resp.status in (400, 409)
    with pytest.raises(HttpError) as e:
        c.disks().delete(project=PROJECT, zone=z, disk="d2").execute()   # in use now
    assert e.value.resp.status == 400
    c.instances().setDiskAutoDelete(project=PROJECT, zone=z, instance="vm1", deviceName="data", autoDelete=True).execute()
    c.instances().detachDisk(project=PROJECT, zone=z, instance="vm1", deviceName="data").execute()
    assert not any(d.get("deviceName") == "data" for d in c.instances().get(project=PROJECT, zone=z, instance="vm1").execute()["disks"])
    c.disks().delete(project=PROJECT, zone=z, disk="d2").execute()
    c.instances().addAccessConfig(project=PROJECT, zone=z, instance="vm1", networkInterface="nic0", body={"name": "ext", "type": "ONE_TO_ONE_NAT"}).execute()
    assert any(a["name"] == "ext" for a in c.instances().get(project=PROJECT, zone=z, instance="vm1").execute()["networkInterfaces"][0]["accessConfigs"])
    c.instances().deleteAccessConfig(project=PROJECT, zone=z, instance="vm1", networkInterface="nic0", accessConfig="ext").execute()
    c.instances().setScheduling(project=PROJECT, zone=z, instance="vm1", body={"automaticRestart": False, "onHostMaintenance": "TERMINATE"}).execute()
    assert c.instances().get(project=PROJECT, zone=z, instance="vm1").execute()["scheduling"]["onHostMaintenance"] == "TERMINATE"
    with pytest.raises(HttpError) as e:   # service account can only change while stopped
        c.instances().setServiceAccount(project=PROJECT, zone=z, instance="vm1", body={"email": "a@b.iam.gserviceaccount.com", "scopes": []}).execute()
    assert e.value.resp.status == 400
    c.instances().stop(project=PROJECT, zone=z, instance="vm1").execute()
    c.instances().setServiceAccount(project=PROJECT, zone=z, instance="vm1", body={"email": "a@b.iam.gserviceaccount.com", "scopes": ["https://www.googleapis.com/auth/cloud-platform"]}).execute()
    assert c.instances().get(project=PROJECT, zone=z, instance="vm1").execute()["serviceAccounts"][0]["email"] == "a@b.iam.gserviceaccount.com"
    assert c.diskTypes().get(project=PROJECT, zone=z, diskType="pd-ssd").execute()["name"] == "pd-ssd"
    assert any(a["name"] == "nvidia-l4" for a in c.acceleratorTypes().list(project=PROJECT, zone=z).execute()["items"])
    c.projects().setDefaultNetworkTier(project=PROJECT, body={"networkTier": "STANDARD"}).execute()
    c.projects().setUsageExportBucket(project=PROJECT, body={}).execute()


def test_serviceusage_state_and_deploy_prereqs(router):
    su = api(router, "serviceusage", "v1")
    assert su.services().get(name="projects/%s/services/run.googleapis.com" % PROJECT).execute()["state"] == "ENABLED"
    su.services().disable(name="projects/%s/services/run.googleapis.com" % PROJECT, body={}).execute()
    assert su.services().get(name="projects/%s/services/run.googleapis.com" % PROJECT).execute()["state"] == "DISABLED"
    su.services().enable(name="projects/%s/services/run.googleapis.com" % PROJECT, body={}).execute()
    assert su.services().get(name="projects/%s/services/run.googleapis.com" % PROJECT).execute()["state"] == "ENABLED"
    resp, out = raw(router, "GET", "https://cloudbuild.googleapis.com/v1/projects/%s/locations/us-central1/defaultServiceAccount" % PROJECT)
    assert resp.status == 200 and json.loads(out)["serviceAccountEmail"].endswith("-compute@developer.gserviceaccount.com")
