"""Infrastructure Manager (core/gcp_inframanager_core) through the real wire router, applying via the native Google routes."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402

P = "nano-project"
SA = "projects/%s/serviceAccounts/tf@%s.iam.gserviceaccount.com" % (P, P)
HCL = '''
variable "project_id" {
  type    = string
  default = "nano-project"
}
resource "google_compute_network" "vpc" {
  name                    = "im-vpc"
  auto_create_subnetworks = false
}
resource "google_compute_subnetwork" "sn" {
  name          = "im-sn"
  ip_cidr_range = "10.9.0.0/24"
  region        = "us-central1"
  network       = google_compute_network.vpc.id
}
resource "google_compute_firewall" "fw" {
  name          = "im-fw"
  network       = google_compute_network.vpc.id
  direction     = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  allow {
    protocol = "tcp"
    ports    = ["22", "443"]
  }
}
resource "google_storage_bucket" "b" {
  name     = "im-bucket-1"
  location = "US"
  uniform_bucket_level_access = true
}
resource "google_pubsub_topic" "t" {
  name = "im-topic"
}
resource "google_pubsub_subscription" "s" {
  name  = "im-sub"
  topic = google_pubsub_topic.t.id
  ack_deadline_seconds = 20
}
resource "google_cloud_run_v2_service" "svc" {
  name     = "im-run"
  location = "us-central1"
}
'''


@pytest.fixture()
def r():
    return AwsWireRouter()


def call(r, method, path, body=None, query=None):
    q = dict(query or {})
    if "?" in path:
        path, qs = path.split("?", 1)
        q.update(x.split("=", 1) for x in qs.split("&"))
    res = r.handle(method, path, q, {"content-type": "application/json"}, json.dumps(body).encode() if body is not None else b"")
    b = res["body"]
    return res["status"], (json.loads(b) if b[:1] in (b"{", b"[") else b)


BASE = "/v1/projects/%s/locations/us-central1" % P


def create(r, did="d1", text=HCL):
    return call(r, "POST", BASE + "/deployments?deploymentId=" + did,
                {"serviceAccount": SA, "terraformBlueprint": {"vyomiFiles": {"main.tf": text}}})


def test_create_applies_and_is_idempotent(r):
    s, op = create(r)
    assert s == 200 and op["done"] and op["name"].startswith("projects/%s/locations/us-central1/operations/operation-im-" % P)
    s, dep = call(r, "GET", BASE + "/deployments/d1")
    assert dep["state"] == "ACTIVE" and dep["latestRevision"].endswith("/revisions/r-000001")
    # the resources exist through the NATIVE Google APIs
    assert call(r, "GET", "/compute/v1/projects/%s/global/networks/im-vpc" % P)[0] == 200
    assert call(r, "GET", "/compute/v1/projects/%s/regions/us-central1/subnetworks/im-sn" % P)[0] == 200
    s, fw = call(r, "GET", "/compute/v1/projects/%s/global/firewalls/im-fw" % P)
    assert s == 200 and fw["allowed"][0]["ports"] == ["22", "443"] and fw["network"].endswith("/global/networks/im-vpc")
    assert call(r, "GET", "/storage/v1/b/im-bucket-1")[0] == 200
    assert call(r, "GET", "/v1/projects/%s/topics/im-topic" % P)[0] == 200
    s, sub = call(r, "GET", "/v1/projects/%s/subscriptions/im-sub" % P)
    assert s == 200 and sub["topic"].endswith("/topics/im-topic") and sub["ackDeadlineSeconds"] == 20
    # unsupported resource reported explicitly, not created
    s, rev = call(r, "GET", "/v1/" + dep["latestRevision"])
    assert [u["address"] for u in rev["applyResults"]["vyomiUnsupported"]] == ["google_cloud_run_v2_service.svc"]
    assert "not applied" in rev["stateDetail"]
    s, res = call(r, "GET", "/v1/" + dep["latestRevision"] + "/resources")
    acts = {x["terraformInfo"]["address"]: x["vyomiAction"] for x in res["resources"]}
    assert acts["google_storage_bucket.b"] == "created" and acts["google_cloud_run_v2_service.svc"] == "unsupported"
    # a second revision of the same config changes nothing
    s, op = call(r, "PATCH", BASE + "/deployments/d1?updateMask=terraformBlueprint", {"terraformBlueprint": {"vyomiFiles": {"main.tf": HCL}}})
    assert s == 200
    s, revs = call(r, "GET", BASE + "/deployments/d1/revisions")
    assert len(revs["revisions"]) == 2 and revs["revisions"][0]["action"] == "UPDATE"
    s, res = call(r, "GET", "/v1/" + revs["revisions"][0]["name"] + "/resources")
    assert {x["vyomiAction"] for x in res["resources"]} == {"unchanged", "unsupported"}


def test_preview_does_not_create(r):
    s, op = call(r, "POST", BASE + "/previews?previewId=pv1", {"serviceAccount": SA, "terraformBlueprint": {"vyomiFiles": {"main.tf": HCL}}})
    assert s == 200 and op["response"]["state"] == "SUCCEEDED"
    assert op["response"]["vyomiPlan"]["summary"] == {"create": 6, "unchanged": 0, "unsupported": 1}
    assert call(r, "GET", "/storage/v1/b/im-bucket-1")[0] == 404
    create(r)
    s, op = call(r, "POST", BASE + "/previews?previewId=pv2", {"terraformBlueprint": {"vyomiFiles": {"main.tf": HCL}}})
    assert op["response"]["vyomiPlan"]["summary"]["unchanged"] == 6


def test_validation_and_errors(r):
    s, b = call(r, "POST", BASE + "/deployments?deploymentId=x1", {"terraformBlueprint": {"vyomiFiles": {"main.tf": HCL}}})
    assert s == 400 and "serviceAccount" in b["error"]["message"]
    s, b = call(r, "POST", BASE + "/deployments?deploymentId=Bad_ID", {"serviceAccount": SA, "terraformBlueprint": {"vyomiFiles": {"main.tf": HCL}}})
    assert s == 400
    s, b = call(r, "POST", BASE + "/deployments?deploymentId=x2", {"serviceAccount": SA, "terraformBlueprint": {"gitSource": {"repo": "https://x"}}})
    assert s == 400 and "gitSource" in b["error"]["message"]
    s, b = call(r, "POST", BASE + "/deployments?deploymentId=x3", {"serviceAccount": SA, "terraformBlueprint": {"vyomiFiles": {"main.tf": 'resource "google_storage_bucket" "b" {'}}})
    assert s == 400
    create(r)
    assert create(r)[0] == 409
    assert call(r, "GET", BASE + "/deployments/nope")[0] == 404


def test_gcs_source_and_delete_destroys(r):
    call(r, "POST", "/storage/v1/b?project=" + P, {"name": "cfg-bucket"})
    res = r.handle("POST", "/upload/storage/v1/b/cfg-bucket/o", {"uploadType": "media", "name": "main.tf"}, {"content-type": "text/plain"},
                   b'resource "google_pubsub_topic" "g" {\n  name = "from-gcs"\n}\n')
    assert res["status"] == 200, res
    s, op = call(r, "POST", BASE + "/deployments?deploymentId=g1", {"serviceAccount": SA, "terraformBlueprint": {"gcsSource": {"source": "gs://cfg-bucket/main.tf"}}})
    assert s == 200 and op["response"]["state"] == "ACTIVE", op
    assert call(r, "GET", "/v1/projects/%s/topics/from-gcs" % P)[0] == 200
    s, op = call(r, "DELETE", BASE + "/deployments/g1")
    assert s == 200 and op["done"]
    assert call(r, "GET", "/v1/projects/%s/topics/from-gcs" % P)[0] == 404
    assert call(r, "GET", BASE + "/deployments/g1")[0] == 404


def test_delete_abandon_keeps_resources(r):
    create(r, "d2", 'resource "google_pubsub_topic" "k" {\n  name = "keep-me"\n}\n')
    call(r, "DELETE", BASE + "/deployments/d2?deletePolicy=ABANDON")
    assert call(r, "GET", "/v1/projects/%s/topics/keep-me" % P)[0] == 200


def test_operation_get_and_list(r):
    s, op = create(r)
    s, got = call(r, "GET", "/v1/" + op["name"])
    assert s == 200 and got["done"] is True
    s, lst = call(r, "GET", BASE + "/deployments")
    assert [d["name"].split("/")[-1] for d in lst["deployments"]] == ["d1"]


def test_hcl_parser_subset():
    from core.gcp_inframanager_core import parse_hcl
    p = parse_hcl('# c\nresource "a_b" "x" {\n  tags = ["a", "b"]  // x\n  n = 3\n  on = true\n  ref = a_b.y.id\n  m = { k = "v" }\n  blk {\n    z = "1"\n  }\n}\n')
    r = p["resources"][0]
    assert r["attrs"]["tags"] == ["a", "b"] and r["attrs"]["n"] == 3 and r["attrs"]["on"] is True and r["attrs"]["m"] == {"k": "v"}
    assert str(r["attrs"]["ref"]) == "a_b.y.id" and r["blocks"][0]["attrs"]["z"] == "1"
