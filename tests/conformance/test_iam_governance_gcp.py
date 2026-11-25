"""GCP Organization Policy v2 over the resource hierarchy: constraint catalog, inheritance (reset / inheritFromParent), effective policy,
dry-run, and enforcement through the real server (GCS bucket creation) + the pure core Nano vendors."""
import os, sys, uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")

from core import gcp_orgpolicy_core as op  # noqa: E402
from core import gcp_resourcemanager_core as rm  # noqa: E402

ORG = "organizations/908614232548"


def _store():
    s = rm.ResourceManagerStore()
    rm.get_or_create_default_org(s)
    s.folders["folders/1"] = {"name": "folders/1", "parent": ORG, "state": "ACTIVE", "displayName": "eng"}
    s.folders["folders/2"] = {"name": "folders/2", "parent": "folders/1", "state": "ACTIVE", "displayName": "prod"}
    s.projects["p1"] = {"projectId": "p1", "name": "projects/111", "parent": {"type": "folder", "id": "2"}, "state": "ACTIVE"}
    s.projects["p2"] = {"projectId": "p2", "name": "projects/222", "parent": {"type": "organization", "id": "908614232548"}, "state": "ACTIVE"}
    return s


def put(s, node, cid, spec=None, dry=None):
    pol = {"name": f"{node}/policies/{cid}"}
    if spec is not None:
        pol["spec"] = spec
    if dry is not None:
        pol["dryRunSpec"] = dry
    s.org_policies[pol["name"]] = pol


def test_catalog_is_real_shaped():
    names = {c["name"] for c in op.list_constraints()}
    assert {"constraints/gcp.resourceLocations", "constraints/iam.allowedPolicyMemberDomains", "constraints/compute.vmExternalIpAccess",
            "constraints/storage.publicAccessPrevention", "constraints/iam.disableServiceAccountCreation"} <= names
    c = op.get_constraint("constraints/gcp.resourceLocations")
    assert "listConstraint" in c and c["constraintDefault"] == "ALLOW" and "booleanConstraint" in op.get_constraint("storage.publicAccessPrevention")
    assert len(names) >= 40


def test_boolean_inheritance_nearest_policy_wins_and_reset():
    s = _store()
    put(s, ORG, "storage.publicAccessPrevention", {"rules": [{"enforce": True}]})
    assert op.enforced(s, "projects/p1", "storage.publicAccessPrevention") and op.enforced(s, "projects/p2", "constraints/storage.publicAccessPrevention")
    put(s, "folders/1", "storage.publicAccessPrevention", {"rules": [{"enforce": False}]})        # nearest wins
    assert not op.enforced(s, "projects/p1", "storage.publicAccessPrevention") and op.enforced(s, "projects/p2", "storage.publicAccessPrevention")
    put(s, "projects/p1", "storage.publicAccessPrevention", {"reset": True})                      # reset: parents ignored -> default
    e = op.effective(s, "projects/p1", "storage.publicAccessPrevention")
    assert e["enforce"] is False and e["default"] is True and e["source"] is None


def test_list_inheritance_merge_and_replace():
    s = _store()
    put(s, ORG, "gcp.resourceLocations", {"rules": [{"values": {"allowedValues": ["in:us-locations"]}}]})
    assert op.allows(s, "projects/p1", "gcp.resourceLocations", "us-east1")[0]
    assert not op.allows(s, "projects/p1", "gcp.resourceLocations", "europe-west1")[0]
    put(s, "folders/1", "gcp.resourceLocations", {"inheritFromParent": True, "rules": [{"values": {"allowedValues": ["europe-west1"]}}]})
    assert op.allows(s, "projects/p1", "gcp.resourceLocations", "europe-west1")[0] and op.allows(s, "projects/p1", "gcp.resourceLocations", "us-east1")[0]
    assert not op.allows(s, "projects/p2", "gcp.resourceLocations", "europe-west1")[0]            # p2 is not under folders/1
    put(s, "folders/2", "gcp.resourceLocations", {"rules": [{"values": {"allowedValues": ["asia-south1"]}}]})   # no inheritFromParent: replaces
    assert op.allows(s, "projects/p1", "gcp.resourceLocations", "asia-south1")[0] and not op.allows(s, "projects/p1", "gcp.resourceLocations", "us-east1")[0]
    put(s, "projects/p1", "gcp.resourceLocations", {"inheritFromParent": True, "rules": [{"values": {"deniedValues": ["asia-south1"]}}]})
    assert not op.allows(s, "projects/p1", "gcp.resourceLocations", "asia-south1")[0]            # denied beats allowed
    put(s, "projects/p2", "gcp.resourceLocations", {"rules": [{"denyAll": True}]})
    assert not op.allows(s, "projects/p2", "gcp.resourceLocations", "us-east1")[0]
    put(s, "projects/p2", "gcp.resourceLocations", {"rules": [{"allowAll": True}]})
    assert op.allows(s, "projects/p2", "gcp.resourceLocations", "anything")[0]
    assert op.allows(s, "folders/2", "gcp.resourceLocations", "under:x")[0] is False             # folder-level evaluation works too


def test_under_values_follow_the_hierarchy():
    s = _store()
    put(s, ORG, "compute.trustedImageProjects", {"rules": [{"values": {"allowedValues": ["under:folders/1"]}}]})
    assert op.allows(s, "projects/p2", "compute.trustedImageProjects", "projects/p1")[0]          # p1 is under folders/1
    assert not op.allows(s, "projects/p1", "compute.trustedImageProjects", "projects/p2")[0]


def test_dry_run_is_reported_not_enforced():
    s = _store()
    put(s, "folders/1", "storage.uniformBucketLevelAccess", None, {"rules": [{"enforce": True}]})
    assert not op.enforced(s, "projects/p1", "storage.uniformBucketLevelAccess")
    chk = op.check(s, "projects/p1", "storage.uniformBucketLevelAccess")
    assert chk["wouldBlock"] is False and chk["dryRunWouldBlock"] is True
    put(s, "folders/1", "gcp.resourceLocations", {"rules": [{"allowAll": True}]}, {"rules": [{"values": {"allowedValues": ["us"]}}]})
    chk = op.check(s, "projects/p1", "gcp.resourceLocations", "europe-west1")
    assert chk["wouldBlock"] is False and chk["dryRunWouldBlock"] is True and "not in allowedValues" in chk["dryRunReason"]


def test_request_gate_bucket_create():
    s = _store()
    put(s, ORG, "gcp.resourceLocations", {"rules": [{"values": {"allowedValues": ["in:us-locations"]}}]})
    put(s, "folders/1", "storage.uniformBucketLevelAccess", {"rules": [{"enforce": True}]})
    assert op.request_gate(s, "POST", "/storage/v1/b", {"project": "p2"}, {"name": "b", "location": "US-EAST1"}) is None
    with pytest.raises(op.Violation) as e:
        op.request_gate(s, "POST", "/storage/v1/b", {"project": "p2"}, {"name": "b", "location": "EUROPE-WEST1"})
    assert "constraints/gcp.resourceLocations" in e.value.message()
    with pytest.raises(op.Violation):
        op.request_gate(s, "POST", "/storage/v1/b", {"project": "p1"}, {"name": "b", "location": "US"})                     # p1: UBLA enforced
    assert op.request_gate(s, "POST", "/storage/v1/b", {"project": "p1"}, {"name": "b", "location": "US", "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True}}}) is None


# ---------------------------------------------------------------- native wire on the real server
@pytest.fixture(scope="module")
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import server
    return TestClient(server.app)


def test_mesh_orgpolicy_v2_wire_and_enforcement(client):
    c, u = client, uuid.uuid4().hex[:6]
    org = ORG
    r = c.get(f"/v2/{org}/constraints")
    assert r.status_code == 200 and any(x["name"] == "constraints/gcp.resourceLocations" for x in r.json()["constraints"])
    fid = c.post("/v3/folders", json={"displayName": f"gov-f-{u}", "parent": org}).json()
    assert fid.get("name", fid.get("response", {}).get("name")), fid
    folder = fid.get("name") if str(fid.get("name", "")).startswith("folders/") else fid["response"]["name"]
    pid = "vyomi-project"                      # the space's one GCP project: moved under the folder for the test, back afterwards
    pr = c.post(f"/v3/projects/{pid}:move", json={"destinationParent": folder})
    assert pr.status_code in (200, 201), pr.text
    created = []
    try:
        pol = {"name": f"{folder}/policies/gcp.resourceLocations", "spec": {"rules": [{"values": {"allowedValues": ["in:us-locations"]}}]}}
        r = c.post(f"/v2/{folder}/policies", json=pol)
        assert r.status_code == 200, r.text
        assert c.post(f"/v2/{folder}/policies", json=pol).status_code == 409
        eff = c.get(f"/v2/projects/{pid}/policies/gcp.resourceLocations:getEffectivePolicy").json()
        assert eff["spec"]["rules"][0]["values"]["allowedValues"] == ["in:us-locations"]
        # bucket creation: the nearest policy (on the parent folder) is inherited by the project
        bad = c.post(f"/storage/v1/b?project={pid}", json={"name": f"gov-eu-{u}", "location": "EUROPE-WEST1"})
        assert bad.status_code == 412 and "constraints/gcp.resourceLocations" in bad.json()["error"]["message"], bad.text
        ok = c.post(f"/storage/v1/b?project={pid}", json={"name": f"gov-us-{u}", "location": "US-EAST1"})
        assert ok.status_code in (200, 201), ok.text
        created.append(f"gov-us-{u}")
        c.delete(f"/storage/v1/b/gov-eu-{u}")
        # dry run: PATCH the policy with a dryRunSpec only -> still allowed, reported by :check
        pr2 = c.patch(f"/v2/{folder}/policies/gcp.resourceLocations", json={"spec": {"rules": [{"allowAll": True}]}, "dryRunSpec": {"rules": [{"values": {"allowedValues": ["us"]}}]}})
        assert pr2.status_code == 200 and "dryRunSpec" in pr2.json()
        again = c.post(f"/storage/v1/b?project={pid}", json={"name": f"gov-eu2-{u}", "location": "EUROPE-WEST1"})
        assert again.status_code in (200, 201), again.text
        created.append(f"gov-eu2-{u}")
        chk = c.post(f"/v2/projects/{pid}/policies/gcp.resourceLocations:check", json={"value": "europe-west1"}).json()
        assert chk["wouldBlock"] is False and chk["dryRunWouldBlock"] is True
        # boolean at the folder -> iam.disableServiceAccountCreation reaches the project (hierarchy-aware hook)
        assert c.post(f"/v2/{folder}/policies", json={"name": f"{folder}/policies/iam.disableServiceAccountCreation", "spec": {"rules": [{"enforce": True}]}}).status_code == 200
        sa = c.post(f"/v1/projects/{pid}/serviceAccounts", json={"accountId": "gov-sa-test", "serviceAccount": {"displayName": "x"}})
        assert sa.status_code == 412 and "disableServiceAccountCreation" in sa.text, sa.text
        # a constraint that does not exist is refused; wrong rule shape is refused
        assert c.post(f"/v2/{folder}/policies", json={"name": f"{folder}/policies/nope.nothing", "spec": {"rules": [{"enforce": True}]}}).status_code == 400
        assert c.post(f"/v2/{folder}/policies", json={"name": f"{folder}/policies/compute.vmExternalIpAccess", "spec": {"rules": [{"enforce": True}]}}).status_code == 400
    finally:
        for b in created:
            c.delete(f"/storage/v1/b/{b}")
        for n in ("gcp.resourceLocations", "iam.disableServiceAccountCreation"):
            c.delete(f"/v2/{folder}/policies/{n}")
        c.post(f"/v3/projects/{pid}:move", json={"destinationParent": org})
        c.delete(f"/v3/{folder}")
