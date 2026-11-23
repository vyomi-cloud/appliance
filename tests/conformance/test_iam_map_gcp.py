"""GCP operation map: REST method + path -> permission + full resource name (core/iam_engine/map_gcp.py)."""
import glob
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from core.iam_engine import map_gcp  # noqa: E402

CASES = [
    # (method, url, [(permission, resource-after-service)], service)
    ("GET", "/storage/v1/b/my-bkt/o/a/b.txt", [("storage.objects.get", "projects/_/buckets/my-bkt/objects/a/b.txt")]),
    ("POST", "/upload/storage/v1/b/my-bkt/o?uploadType=media&name=x/y.txt", [("storage.objects.create", "projects/_/buckets/my-bkt/objects/x/y.txt")]),
    ("GET", "/storage/v1/b?project=p1", [("storage.buckets.list", "projects/p1")]),
    ("POST", "/storage/v1/b?project=p1", [("storage.buckets.create", "projects/p1")]),
    ("DELETE", "/storage/v1/b/my-bkt", [("storage.buckets.delete", "projects/_/buckets/my-bkt")]),
    ("GET", "/storage/v1/b/my-bkt/o", [("storage.objects.list", "projects/_/buckets/my-bkt")]),
    ("DELETE", "/storage/v1/b/my-bkt/o/k", [("storage.objects.delete", "projects/_/buckets/my-bkt/objects/k")]),
    ("GET", "/storage/v1/b/my-bkt/iam", [("storage.buckets.getIamPolicy", "projects/_/buckets/my-bkt")]),
    ("PUT", "/storage/v1/b/my-bkt/iam", [("storage.buckets.setIamPolicy", "projects/_/buckets/my-bkt")]),
    ("PATCH", "/storage/v1/b/my-bkt", [("storage.buckets.update", "projects/_/buckets/my-bkt")]),
    ("POST", "/compute/v1/projects/p/zones/z/instances/vm1/start", [("compute.instances.start", "projects/p/zones/z/instances/vm1")]),
    ("POST", "/compute/v1/projects/p/zones/z/instances/vm1/stop", [("compute.instances.stop", "projects/p/zones/z/instances/vm1")]),
    ("POST", "/compute/v1/projects/p/zones/z/instances", [("compute.instances.create", "projects/p/zones/z")]),
    ("DELETE", "/compute/v1/projects/p/zones/z/instances/vm1", [("compute.instances.delete", "projects/p/zones/z/instances/vm1")]),
    ("GET", "/compute/v1/projects/p/zones/z/instances", [("compute.instances.list", "projects/p/zones/z")]),
    ("POST", "/compute/v1/projects/p/global/firewalls", [("compute.firewalls.create", "projects/p/global")]),
    ("PATCH", "/compute/v1/projects/p/global/firewalls/fw", [("compute.firewalls.update", "projects/p/global/firewalls/fw")]),
    ("GET", "/compute/v1/projects/p/regions/r/subnetworks/s", [("compute.subnetworks.get", "projects/p/regions/r/subnetworks/s")]),
    ("POST", "/compute/v1/projects/p/zones/z/instances/vm/setMetadata", [("compute.instances.setMetadata", "projects/p/zones/z/instances/vm")]),
    ("POST", "/compute/v1/projects/p/zones/z/instances/vm/setIamPolicy", [("compute.instances.setIamPolicy", "projects/p/zones/z/instances/vm")]),
    ("GET", "/sql/v1beta4/projects/p/instances/i", [("cloudsql.instances.get", "projects/p/instances/i")]),
    ("POST", "/sql/v1beta4/projects/p/instances", [("cloudsql.instances.create", "projects/p")]),
    ("POST", "/sql/v1beta4/projects/p/instances/i/restart", [("cloudsql.instances.restart", "projects/p/instances/i")]),
    ("DELETE", "/sql/v1beta4/projects/p/instances/i/databases/d", [("cloudsql.databases.delete", "projects/p/instances/i/databases/d")]),
    ("GET", "/v2/projects/p/locations/us/services/s1", [("run.services.get", "projects/p/locations/us/services/s1")]),
    ("POST", "/v2/projects/p/locations/us/services?serviceId=a", [("run.services.create", "projects/p/locations/us")]),
    ("POST", "/v2/projects/p/locations/us/jobs/j:run", [("run.jobs.run", "projects/p/locations/us/jobs/j")]),
    ("GET", "/v1/projects/p/locations/us/functions/f", [("cloudfunctions.functions.get", "projects/p/locations/us/functions/f")]),
    ("POST", "/v1/projects/p/locations/us/clusters", [("container.clusters.create", "projects/p/locations/us")]),
    ("GET", "/v1/projects/p/locations/us/clusters/c", [("container.clusters.get", "projects/p/locations/us/clusters/c")]),
    ("DELETE", "/v1/projects/p/locations/us/clusters/c", [("container.clusters.delete", "projects/p/locations/us/clusters/c")]),
    ("PUT", "/v1/projects/p/topics/t", [("pubsub.topics.create", "projects/p/topics/t")]),
    ("POST", "/v1/projects/p/topics/t:publish", [("pubsub.topics.publish", "projects/p/topics/t")]),
    ("POST", "/v1/projects/p/topics/t:setIamPolicy", [("pubsub.topics.setIamPolicy", "projects/p/topics/t")]),
    ("GET", "/v1/projects/p/topics/t:getIamPolicy", [("pubsub.topics.getIamPolicy", "projects/p/topics/t")]),
    ("POST", "/v1/projects/p/subscriptions/s:pull", [("pubsub.subscriptions.consume", "projects/p/subscriptions/s")]),
    ("DELETE", "/v1/projects/p/topics/t", [("pubsub.topics.delete", "projects/p/topics/t")]),
    ("POST", "/v1/projects/p/serviceAccounts", [("iam.serviceAccounts.create", "projects/p")]),
    ("POST", "/v1/projects/p/serviceAccounts/sa@p.iam.gserviceaccount.com:setIamPolicy", [("iam.serviceAccounts.setIamPolicy", "projects/p/serviceAccounts/sa@p.iam.gserviceaccount.com")]),
    ("POST", "/v1/projects/p/serviceAccounts/sa@p.iam.gserviceaccount.com/keys", [("iam.serviceAccountKeys.create", "projects/p/serviceAccounts/sa@p.iam.gserviceaccount.com")]),
    ("POST", "/v1/projects/p:setIamPolicy", [("resourcemanager.projects.setIamPolicy", "projects/p")]),
    ("POST", "/v1/projects/p:getIamPolicy", [("resourcemanager.projects.getIamPolicy", "projects/p")]),
    ("GET", "/v3/projects/p", [("resourcemanager.projects.get", "projects/p")]),
    ("POST", "/v1/projects/p/locations/l/keyRings/kr/cryptoKeys/k:encrypt", [("cloudkms.cryptoKeyVersions.useToEncrypt", "projects/p/locations/l/keyRings/kr/cryptoKeys/k")]),
    ("POST", "/v1/projects/p/secrets/s:addVersion", [("secretmanager.versions.add", "projects/p/secrets/s")]),
    ("GET", "/v1/projects/p/secrets/s/versions/latest:access", [("secretmanager.versions.access", "projects/p/secrets/s/versions/latest")]),
    ("POST", "/v1/projects/p/secrets?secretId=x", [("secretmanager.secrets.create", "projects/p")]),
    ("POST", "/v1/projects/p/locations/l/repositories?repositoryId=r", [("artifactregistry.repositories.create", "projects/p/locations/l")]),
    ("POST", "/v2/entries:write", [("logging.logEntries.create", None)]),
    ("GET", "/dns/v1/projects/p/managedZones/z/rrsets", [("dns.resourceRecordSets.list", "projects/p/managedZones/z")]),
    ("POST", "/v1/projects/p/locations/us-central1/instances?instanceId=r", [("redis.instances.create", "projects/p/locations/us-central1")]),
    ("GET", "/v1/projects/p/databases/(default)/documents/col/doc", [("datastore.entities.get", "projects/p/databases/(default)/documents/col/doc")]),
    ("GET", "/v1/projects/p/databases/(default)/documents/col", [("datastore.entities.list", "projects/p/databases/(default)/documents/col")]),
    ("PATCH", "/v1/projects/p/databases/(default)/documents/col/doc", [("datastore.entities.update", "projects/p/databases/(default)/documents/col/doc")]),
    ("POST", "/v1/projects/p/locations/us/jobs", [("cloudscheduler.jobs.create", "projects/p/locations/us")]),
    ("POST", "/v1/projects/p/locations/us/endpoints/e:predict", [("aiplatform.endpoints.predict", "projects/p/locations/us/endpoints/e")]),
    ("POST", "/v1/projects/p/locations/l/triggers", [("eventarc.triggers.create", "projects/p/locations/l")]),
    ("GET", "/v1/projects/p/locations/l/apis", [("apigateway.apis.list", "projects/p/locations/l")]),
    ("POST", "/v1/projects/p/locations/l/deliveryPipelines?deliveryPipelineId=x", [("clouddeploy.deliveryPipelines.create", "projects/p/locations/l")]),
    ("POST", "/v1/projects/p/builds", [("cloudbuild.builds.create", "projects/p")]),
    ("POST", "/v3/projects/p/timeSeries", [("monitoring.timeSeries.create", "projects/p")]),
]


@pytest.mark.parametrize("method,url,expect", CASES, ids=[f"{c[0]} {c[1]}" for c in CASES])
def test_required(method, url, expect):
    got = map_gcp.required(method, url)
    assert [g["action"] for g in got] == [e[0] for e in expect], got
    for g, (_a, res) in zip(got, expect):
        assert g["resource"].startswith("//") and g["service"].endswith(".googleapis.com")
        if res is not None:
            assert g["resource"] == "//%s/%s" % (g["service"], res)


def test_test_iam_permissions_needs_no_permission():
    assert map_gcp.required("POST", "/v1/projects/p/topics/t:testIamPermissions") == []
    assert map_gcp.required("POST", "/v1/projects/p:testIamPermissions") == []


def test_unknown_path_is_unmapped():
    assert map_gcp.required("GET", "/nothing/here") == []
    assert map_gcp.describe("GET", "/nothing/here")["matched"] is False


def test_xml_api_virtual_host_and_path_style():
    r = map_gcp.required("GET", "https://my-bkt.storage.googleapis.com/dir/o.txt")
    assert r[0]["action"] == "storage.objects.get" and r[0]["resource"].endswith("buckets/my-bkt/objects/dir/o.txt")
    r = map_gcp.required("PUT", "https://storage.googleapis.com/my-bkt/o.txt")
    assert r[0]["action"] == "storage.objects.create"
    r = map_gcp.required("DELETE", "https://storage.googleapis.com/my-bkt/o.txt")
    assert r[0]["action"] == "storage.objects.delete"
    r = map_gcp.required("GET", "https://storage.googleapis.com/my-bkt")
    assert r[0]["action"] == "storage.objects.list"
    r = map_gcp.required("GET", "https://storage.googleapis.com/")
    assert r[0]["action"] == "storage.buckets.list"
    r = map_gcp.required("PUT", "https://storage.googleapis.com/my-bkt")
    assert r[0]["action"] == "storage.buckets.create"


def test_service_account_attachment_adds_actas():
    body = {"serviceAccounts": [{"email": "app@p.iam.gserviceaccount.com"}]}
    r = map_gcp.required("POST", "/compute/v1/projects/p/zones/z/instances", body)
    assert [g["action"] for g in r] == ["compute.instances.create", "iam.serviceAccounts.actAs"]
    assert r[1]["resource"].endswith("serviceAccounts/app@p.iam.gserviceaccount.com")


def test_every_emitted_permission_is_in_the_catalog():
    perms = set()
    for f in glob.glob(os.path.join(ROOT, "core/iam_catalog/gcp/*.json")):
        if not os.path.basename(f).startswith("_"):
            perms |= set(json.load(open(f))["permissions"])
    table = json.load(open(os.path.join(ROOT, "core/iam_catalog/gcp/_methods.json")))
    assert table["overrides_not_in_catalog"] == []
    emitted = {p for e in table["methods"] for p in e["perm"]}
    assert emitted <= perms and len(emitted) > 800
    for ov in table["overrides"].values():
        assert ov["reason"]


def test_coverage_report(capsys):
    table = json.load(open(os.path.join(ROOT, "core/iam_catalog/gcp/_methods.json")))
    ids = {e["id"] for e in table["methods"]}
    total = len(ids) + len(table["unmatched"])
    print("GCP methods mapped %d / %d (%.1f%%), heuristic fallbacks %d" % (len(ids), total, 100.0 * len(ids) / total, len(table["fallback_ids"])))
    assert len(ids) / total > 0.7
