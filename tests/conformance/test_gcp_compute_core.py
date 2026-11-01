"""Compute Engine REST (the wire of `gcloud compute`) over the console's records. Host CPython."""
import json
import sys
import types

from core import gcp_compute_core as c

P = {"projectId": "p1", "projectNumber": "123"}
fails = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL ") + name + ("" if ok else f" :: {detail}"))
    if not ok:
        fails.append(name)


res, root = types.SimpleNamespace(collections={}), {}


def call(m, tail, body=None, project="p1"):
    r = c.dispatch(res, root, P, m, f"/compute/v1/projects/{project}/{tail}", {"host": "h:1"}, json.dumps(body).encode() if body else b"")
    return r["status"], json.loads(r["body"])


st, op = call("POST", "global/networks", {"name": "n1", "autoCreateSubnetworks": False})
check("networks.insert returns a DONE operation", st == 200 and op["status"] == "DONE" and op["targetLink"].endswith("/global/networks/n1"), op)
check("the network is the console's record", "n1" in res.collections["gcp/default/vpc"])
st, _ = call("POST", "global/networks", {"name": "n1"})
check("duplicate → 409", st == 409)
st, op = call("POST", "regions/us-central1/subnetworks", {"name": "s1", "network": "http://h:1/compute/v1/projects/p1/global/networks/n1", "ipCidrRange": "10.0.0.0/24"})
check("subnetworks.insert", st == 200 and op.get("region"), op)
check("subnet stored where the console reads it", "us-central1/s1" in root["vpc/n1/subnets"])
st, e = call("DELETE", "global/networks/n1")
check("delete with a subnet → resourceInUseByAnotherResource", st == 400 and e["error"]["errors"][0]["reason"] == "resourceInUseByAnotherResource", e)
st, e = call("POST", "regions/us-central1/subnetworks", {"name": "s2", "network": "n1", "ipCidrRange": "10.0.0.128/25"})
check("overlapping range refused", st == 400, e)
call("DELETE", "regions/us-central1/subnetworks/s1")
st, _ = call("DELETE", "global/networks/n1")
check("delete once clear", st == 200 and call("GET", "global/networks/n1")[0] == 404)
call("POST", "global/networks", {"name": "auto", "autoCreateSubnetworks": True})
st, a = call("GET", "aggregated/subnetworks")
check("auto-mode creates regional subnets", st == 200 and len(a["items"]) > 3)
check("auto-mode network deletes with its subnets", call("DELETE", "global/networks/auto")[0] == 200 and "vpc/auto/subnets" not in root)
st, op = call("POST", "zones/us-central1-a/instances", {"name": "vm", "machineType": "zones/us-central1-a/machineTypes/e2-small"})
check("instances.insert", st == 200 and op.get("zone"), op)
st, i = call("GET", "zones/us-central1-a/instances/vm")
check("instance view", i["status"] == "RUNNING" and i["machineType"].endswith("/machineTypes/e2-small") and i["networkInterfaces"], i)
call("POST", "zones/us-central1-a/instances/vm/stop")
check("stop → TERMINATED", call("GET", "zones/us-central1-a/instances/vm")[1]["status"] == "TERMINATED")
check("aggregated list", "zones/us-central1-a" in call("GET", "aggregated/instances")[1]["items"])
call("DELETE", "zones/us-central1-a/instances/vm")
check("deleted", call("GET", "zones/us-central1-a/instances/vm")[0] == 404)
check("public image project answers", call("GET", "global/images/family/debian-12", project="debian-cloud")[1]["status"] == "READY")
check("project number accepted", call("GET", "global/networks", project="123")[0] == 200)
check("another project refused", call("GET", "global/networks", project="other")[0] == 404)
sys.exit(1 if fails else 0)
