"""Unit tests for core/gcp_container_core.py (run: python3 tests/conformance/test_gcp_container_core.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_container_core as gk  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


L = "/v1/projects/p1/locations/us-central1"


def call(st, method, path, body=None, query=None):
    r = gk.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


st = gk.ContainerStore()
s, op = call(st, "POST", L + "/clusters", {"cluster": {"name": "c1", "initialNodeCount": 2}})
check("create returns a DONE CREATE_CLUSTER operation", s == 200 and op["status"] == "DONE" and op["operationType"] == "CREATE_CLUSTER", op)
s, c = call(st, "GET", L + "/clusters/c1")
check("get: RUNNING, default-pool, endpoint, version", s == 200 and c["status"] == "RUNNING" and c["nodePools"][0]["name"] == "default-pool"
      and c["endpoint"] and c["currentMasterVersion"] == gk.DEFAULT_VERSION and c["currentNodeCount"] == 2, c)
check("duplicate -> 409 ALREADY_EXISTS", call(st, "POST", L + "/clusters", {"cluster": {"name": "c1"}})[0] == 409)
check("bad name -> 400", call(st, "POST", L + "/clusters", {"cluster": {"name": "Bad_Name"}})[0] == 400)
check("bad location -> 400", call(st, "POST", "/v1/projects/p1/locations/mars-1/clusters", {"cluster": {"name": "x"}})[0] == 400)
check("get missing -> 404 NOT_FOUND", call(st, "GET", L + "/clusters/nope")[1]["error"]["status"] == "NOT_FOUND")
check("list", [x["name"] for x in call(st, "GET", L + "/clusters")[1]["clusters"]] == ["c1"])
check("legacy zonal path serves", call(st, "GET", "/v1/projects/p1/zones/us-central1/clusters/c1")[0] == 200)
s, op = call(st, "POST", L + "/clusters/c1/nodePools", {"nodePool": {"name": "np2", "initialNodeCount": 1, "config": {"machineType": "e2-standard-4"}}})
check("create node pool", s == 200 and op["operationType"] == "CREATE_NODE_POOL")
check("duplicate node pool -> 409", call(st, "POST", L + "/clusters/c1/nodePools", {"nodePool": {"name": "np2"}})[0] == 409)
s, _ = call(st, "POST", L + "/clusters/c1/nodePools/np2:setSize", {"nodeCount": 4})
check("setSize", s == 200 and call(st, "GET", L + "/clusters/c1/nodePools/np2")[1]["initialNodeCount"] == 4)
check("console view totals vCPUs (2*2 + 4*4)", gk.list_all(st)[0]["vcpus"] == "20", gk.list_all(st)[0]["vcpus"])
s, _ = call(st, "POST", L + "/clusters/c1:setResourceLabels", {"resourceLabels": {"env": "dev"}})
check("setResourceLabels", s == 200 and call(st, "GET", L + "/clusters/c1")[1]["resourceLabels"] == {"env": "dev"})
check("stale labelFingerprint -> 409", call(st, "POST", L + "/clusters/c1:setResourceLabels", {"resourceLabels": {}, "labelFingerprint": "x"})[0] == 409)
s, op = call(st, "PUT", L + "/clusters/c1", {"update": {"desiredMasterVersion": "1.31"}})
check("upgrade master", s == 200 and op["operationType"] == "UPGRADE_MASTER" and call(st, "GET", L + "/clusters/c1")[1]["currentMasterVersion"].startswith("1.31"))
check("delete node pool", call(st, "DELETE", L + "/clusters/c1/nodePools/np2")[0] == 200)
check("cannot delete last node pool -> 400", call(st, "DELETE", L + "/clusters/c1/nodePools/default-pool")[0] == 400)
s, ops = call(st, "GET", L + "/operations")
check("operations list + get", s == 200 and len(ops["operations"]) >= 5 and call(st, "GET", L + "/operations/" + ops["operations"][0]["name"])[0] == 200)
check("serverConfig", call(st, "GET", L + "/serverConfig")[1]["defaultClusterVersion"] == gk.DEFAULT_VERSION)
sc = call(st, "GET", L + "/serverConfig")[1]
check("deprecated 1.35.8-gke.1919000 still valid but in no channel",
      "1.35.8-gke.1919000" in sc["validMasterVersions"] and all("1.35.8-gke.1919000" not in c["validVersions"] for c in sc["channels"]) and "1.35.8-gke.1975000" in sc["validMasterVersions"])
s, op = call(st, "POST", L + "/clusters", {"cluster": {"name": "ap", "autopilot": {"enabled": True}}}, {"$alt": "json;enum-encoding=int"})
check("int enums on request (operationType/status)", s == 200 and op["operationType"] == 1 and op["status"] == 3, op)
check("autopilot has no node pools", call(st, "GET", L + "/clusters/ap")[1]["nodePools"] == [])
check("delete cluster", call(st, "DELETE", L + "/clusters/c1")[1]["operationType"] == "DELETE_CLUSTER" and call(st, "GET", L + "/clusters/c1")[0] == 404)

# controlPlaneEndpointsConfig — DNS / IPv4 control plane access (console: "Access using DNS" /
# "Access using IPv4 addresses"). Defaults both on; at least one must stay enabled.
s, _ = call(st, "POST", L + "/clusters", {"cluster": {"name": "cpe-default", "initialNodeCount": 1}})
c = call(st, "GET", L + "/clusters/cpe-default")[1]
check("defaults: both DNS and IPv4 access enabled, public endpoint set",
      c["controlPlaneEndpointsConfig"]["dnsEndpointConfig"]["allowExternalTraffic"] is True
      and c["controlPlaneEndpointsConfig"]["ipEndpointsConfig"]["enabled"] is True and c["endpoint"], c)
check("DNS endpoint hostname ends in .gke.goog", c["controlPlaneEndpointsConfig"]["dnsEndpointConfig"]["endpoint"].endswith(".gke.goog"), c)
s, body = call(st, "POST", L + "/clusters", {"cluster": {"name": "cpe-bad", "initialNodeCount": 1,
    "controlPlaneEndpointsConfig": {"dnsEndpointConfig": {"allowExternalTraffic": False}, "ipEndpointsConfig": {"enabled": False}}}})
check("disabling both DNS and IPv4 access -> 400", s == 400 and body["error"]["status"] == "INVALID_ARGUMENT", body)
s, _ = call(st, "POST", L + "/clusters", {"cluster": {"name": "cpe-dns-only", "initialNodeCount": 1,
    "controlPlaneEndpointsConfig": {"ipEndpointsConfig": {"enabled": False}}}})
c = call(st, "GET", L + "/clusters/cpe-dns-only")[1]
check("IPv4 access disabled -> no public endpoint, DNS endpoint present",
      c["endpoint"] == "" and not c["controlPlaneEndpointsConfig"]["ipEndpointsConfig"].get("publicEndpoint")
      and c["controlPlaneEndpointsConfig"]["dnsEndpointConfig"]["allowExternalTraffic"] is True, c)
s, body = call(st, "PUT", L + "/clusters/cpe-dns-only", {"update": {"desiredControlPlaneEndpointsConfig": {"dnsEndpointConfig": {"allowExternalTraffic": False}}}})
check("flipping DNS off while IPv4 stays off -> 400 (no access method left)", s == 400, body)
s, _ = call(st, "PUT", L + "/clusters/cpe-dns-only", {"update": {"desiredControlPlaneEndpointsConfig": {"ipEndpointsConfig": {"enabled": True}}}})
c = call(st, "GET", L + "/clusters/cpe-dns-only")[1]
check("re-enabling IPv4 access restores the public endpoint", s == 200 and bool(c["endpoint"]), c)

# Backup for GKE (gkebackup shape: backupPlans + backups, served from this core).
s, _ = call(st, "POST", L + "/clusters", {"cluster": {"name": "bc1", "initialNodeCount": 2}})
s, body = call(st, "POST", L + "/backupPlans", {"cluster": "projects/p1/locations/us-central1/clusters/bc1", "description": "nightly"}, query={"backupPlanId": "bp1"})
check("create backup plan: READY, references cluster", s == 200 and body["state"] == "READY" and body["cluster"].endswith("/clusters/bc1"), body)
check("create backup plan for missing cluster -> 400", call(st, "POST", L + "/backupPlans", {"cluster": "projects/p1/locations/us-central1/clusters/nope"}, query={"backupPlanId": "bp2"})[0] == 400)
check("duplicate backup plan id -> 409", call(st, "POST", L + "/backupPlans", {"cluster": "projects/p1/locations/us-central1/clusters/bc1"}, query={"backupPlanId": "bp1"})[0] == 409)
check("get backup plan", call(st, "GET", L + "/backupPlans/bp1")[1]["name"].endswith("/backupPlans/bp1"))
check("list backup plans", [p["name"].rsplit("/", 1)[-1] for p in call(st, "GET", L + "/backupPlans")[1]["backupPlans"]] == ["bp1"])
s, backup = call(st, "POST", L + "/backupPlans/bp1/backups", {}, query={"backupId": "b1"})
check("create backup: SUCCEEDED, sizes derived from the cluster", s == 200 and backup["state"] == "SUCCEEDED"
      and int(backup["sizeBytes"]) > 0 and backup["clusterMetadata"]["cluster"].endswith("/clusters/bc1"), backup)
check("backup plan protectedPodCount updated after a backup", call(st, "GET", L + "/backupPlans/bp1")[1]["protectedPodCount"] == backup["podCount"])
check("list backups under the plan", [b["name"].rsplit("/", 1)[-1] for b in call(st, "GET", L + "/backupPlans/bp1/backups")[1]["backups"]] == ["b1"])
check("get backup", call(st, "GET", L + "/backupPlans/bp1/backups/b1")[1]["state"] == "SUCCEEDED")
check("duplicate backup id -> 409", call(st, "POST", L + "/backupPlans/bp1/backups", {}, query={"backupId": "b1"})[0] == 409)
check("delete backup plan with backups, no force -> 400 FAILED_PRECONDITION",
      call(st, "DELETE", L + "/backupPlans/bp1")[1]["error"]["status"] == "FAILED_PRECONDITION")
check("delete backup plan with force=true cascades", call(st, "DELETE", L + "/backupPlans/bp1", query={"force": "true"})[0] == 200
      and call(st, "GET", L + "/backupPlans/bp1")[0] == 404 and call(st, "GET", L + "/backupPlans/bp1/backups/b1")[0] == 404)
s, _ = call(st, "POST", L + "/backupPlans", {"cluster": "projects/p1/locations/us-central1/clusters/bc1"}, query={"backupPlanId": "bp3"})
check("create second backup plan on bc1", s == 200)
check("delete cluster bc1", call(st, "DELETE", L + "/clusters/bc1")[0] == 200)
s, body = call(st, "POST", L + "/backupPlans/bp3/backups", {}, query={"backupId": "b2"})
check("backup run against a now-deleted cluster -> 400 FAILED_PRECONDITION", s == 400 and body["error"]["status"] == "FAILED_PRECONDITION", body)
print(f"RESULT pass={PASS} fail={FAIL}")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
