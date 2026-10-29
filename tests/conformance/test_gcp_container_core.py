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
s, op = call(st, "POST", L + "/clusters", {"cluster": {"name": "ap", "autopilot": {"enabled": True}}}, {"$alt": "json;enum-encoding=int"})
check("int enums on request (operationType/status)", s == 200 and op["operationType"] == 1 and op["status"] == 3, op)
check("autopilot has no node pools", call(st, "GET", L + "/clusters/ap")[1]["nodePools"] == [])
check("delete cluster", call(st, "DELETE", L + "/clusters/c1")[1]["operationType"] == "DELETE_CLUSTER" and call(st, "GET", L + "/clusters/c1")[0] == 404)
print(f"RESULT pass={PASS} fail={FAIL}")
sys.exit(1 if FAIL else 0)
