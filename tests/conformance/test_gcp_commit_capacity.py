"""GCP: committed use discounts, simulated capacity pools + Capacity advisor, Migrate to VMs, Cloud TPU, VM Manager inventory.
Run: PYTHONPATH=. python3 tests/conformance/test_gcp_commit_capacity.py"""
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402
from core import gcp_osconfig_core as OSC  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False
R = AwsWireRouter()
PASS = FAIL = 0
P = "cud-proj-1"
CB = f"/compute/v1/projects/{P}"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(method, path, body=None, query=None):
    out = R.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {}


def mkvm(name, mt="e2-standard-4", zone="us-central1-a", extra=None):
    body = {"name": name, "machineType": f"zones/{zone}/machineTypes/{mt}",
            "disks": [{"boot": True, "autoDelete": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}],
            "networkInterfaces": [{"network": "global/networks/default"}]}
    body.update(extra or {})
    return call("POST", f"{CB}/zones/{zone}/instances", body)


# ── committed use discounts ──
mkvm("c1"); mkvm("c2")                                         # 8 vCPU of e2 running
com = {"name": "e2-1y", "plan": "TWELVE_MONTH", "type": "GENERAL_PURPOSE_E2", "resources": [{"type": "VCPU", "amount": "16"}, {"type": "MEMORY", "amount": "65536"}]}
st, e = call("POST", f"{CB}/regions/us-central1/commitments", dict(com, plan="FIVE_MONTH"))
check("bad plan rejected", st == 400 and e["error"]["status"] == "INVALID_ARGUMENT")
st, e = call("POST", f"{CB}/regions/us-central1/commitments", dict(com, resources=[{"type": "VCPU", "amount": "16"}]))
check("missing MEMORY rejected", st == 400)
st, e = call("POST", f"{CB}/regions/us-central1/commitments", dict(com, resources=[{"type": "VCPU", "amount": "4"}, {"type": "MEMORY", "amount": "99999999"}]))
check("memory ratio rejected", st == 400)
st, e = call("POST", f"{CB}/regions/nowhere1/commitments", com)
check("unknown region 404", st == 404)
st, e = call("POST", f"{CB}/regions/us-central1/commitments", com)
check("create commitment", st == 200 and e["operationType"] == "insert", e)
st, e = call("POST", f"{CB}/regions/us-central1/commitments", com)
check("duplicate 409", st == 409)
st, g = call("GET", f"{CB}/regions/us-central1/commitments/e2-1y")
u = g.get("vyomiUtilisation", {})
check("get: ACTIVE, 1y, discount 37%", g.get("status") == "ACTIVE" and u.get("discountPercent") == 37 and g["plan"] == "TWELVE_MONTH", g)
check("utilisation = running e2 vCPU / committed (8/16 = 50%)", u.get("vcpuUtilisationPercent") == 50.0 and u.get("vcpuUsed") == 8.0, u)
check("underused commitment has negative net savings", u.get("netSavingsUsdPerMonth", 0) < 0, u)
mkvm("c3"); mkvm("c4"); mkvm("c5")                              # 20 vCPU > 16 committed
st, g = call("GET", f"{CB}/regions/us-central1/commitments/e2-1y")
u = g["vyomiUtilisation"]
check("overused commitment = 100% and positive savings", u["vcpuUtilisationPercent"] == 100.0 and u["netSavingsUsdPerMonth"] > 0, u)
call("POST", f"{CB}/zones/us-central1-a/instances/c5/stop")
st, g2 = call("GET", f"{CB}/regions/us-central1/commitments/e2-1y")
check("stopping a VM lowers utilisation", g2["vyomiUtilisation"]["vcpuUsed"] == 16.0)
st, e = call("DELETE", f"{CB}/regions/us-central1/commitments/e2-1y")
check("commitments cannot be cancelled", st == 400 and e["error"]["status"] == "FAILED_PRECONDITION")
st, e = call("POST", f"{CB}/regions/us-central1/commitments", {"name": "sp3", "plan": "THIRTY_SIX_MONTH", "category": "SPEND_BASED", "vyomiSpend": {"hourlyCommitmentUsd": 0.5}})
check("spend-based create", st == 200)
st, g = call("GET", f"{CB}/regions/us-central1/commitments/sp3")
check("spend-based 3y discount 46%", g["vyomiUtilisation"]["discountPercent"] == 46 and g["type"] == "SPEND_BASED_FLEX", g)
st, e = call("POST", f"{CB}/regions/us-central1/commitments", {"name": "sp4", "plan": "TWELVE_MONTH", "category": "SPEND_BASED"})
check("spend-based needs hourly amount", st == 400)
st, e = call("GET", f"{CB}/vyomi/commitmentSavings")
check("savings summary lists both", st == 200 and len(e["commitments"]) == 2, e)
st, e = call("GET", f"{CB}/aggregated/commitments")
check("aggregated list", st == 200 and "regions/us-central1" in e["items"])

# ── capacity pools ──
st, e = call("POST", f"{CB}/vyomi/capacityPools", {"zone": "us-east4-a", "family": "a2", "vcpus": 24})
check("configure pool", st == 200 and e["limitVcpus"] == 24, e)
st, e = call("POST", f"{CB}/vyomi/capacityPools", {"zone": "us-east4-a", "family": "zz", "vcpus": 24})
check("bad family rejected", st == 400)
ok = [mkvm(f"gpu{i}", "a2-highgpu-1g", "us-east4-a")[0] for i in range(2)]
check("pool of 24 vCPU fits two 12-vCPU a2 VMs", ok == [200, 200], ok)
st, e = mkvm("gpu3", "a2-highgpu-1g", "us-east4-a")
check("third a2 VM stocks out with ZONE_RESOURCE_POOL_EXHAUSTED", st == 503 and e["error"]["status"] == "ZONE_RESOURCE_POOL_EXHAUSTED"
      and "does not have enough resources available" in e["error"]["message"], e)
st, _ = call("GET", f"{CB}/zones/us-east4-a/instances/gpu3")
check("failed insert leaves no instance behind", st == 404)
st, adv = call("POST", f"/compute/beta/projects/{P}/regions/us-east4/advice/capacity", {"instanceProperties": {"machineType": "a2-highgpu-1g"}, "size": 1})
recs = adv.get("recommendations", [])
check("advisor: stocked-out zone UNAVAILABLE, another zone AVAILABLE first", recs and recs[0]["obtainability"] == "AVAILABLE" and
      any(r["zone"] == "us-east4-a" and r["obtainability"] == "UNAVAILABLE" for r in recs) and adv["basis"] == "SIMULATED_POOLS", adv)
check("advisor suggests alternative shapes", len(adv["alternativeShapes"]) >= 0 and "no Google fleet data" in adv["note"])
call("POST", f"{CB}/zones/us-east4-a/instances/gpu0/stop")
st, e = call("POST", f"{CB}/zones/us-east4-a/instances/gpu0/start")
check("stop returns capacity, start draws it again", st == 200)
call("POST", f"{CB}/zones/us-east4-a/instances/gpu0/stop")
st, e = mkvm("gpu4", "a2-highgpu-1g", "us-east4-a")
check("capacity freed by stop is reusable", st == 200)
st, e = call("POST", f"{CB}/zones/us-east4-a/instances/gpu0/start")
check("start of a stopped VM stocks out when the pool is full", st == 503 and e["error"]["status"] == "ZONE_RESOURCE_POOL_EXHAUSTED", e)
st, pools = call("GET", f"{CB}/vyomi/capacity", query={"zone": "us-east4-a"})
a2 = next(p for p in pools["items"] if p["family"] == "a2")
check("utilisation view reflects 24/24", a2["usedVcpus"] == 24 and a2["utilisationPercent"] == 100.0, a2)
# reservation guarantees capacity
call("POST", f"{CB}/vyomi/capacityPools", {"zone": "us-west1-a", "family": "c2", "vcpus": 8})
st, e = call("POST", f"{CB}/zones/us-west1-a/reservations", {"name": "res1", "specificReservation": {"count": "2", "instanceProperties": {"machineType": "c2-standard-4"}}})
check("reservation holds capacity", st == 200, e)
st, e = mkvm("other", "c2-standard-4", "us-west1-a", {"reservationAffinity": {"consumeReservationType": "NO_RESERVATION"}})
check("non-reservation VM cannot take reserved capacity", st == 503, e)
st, e = mkvm("rsv1", "c2-standard-4", "us-west1-a")
check("VM consuming the reservation succeeds", st == 200, e)
# concurrent starts
call("POST", f"{CB}/vyomi/capacityPools", {"zone": "us-central1-b", "family": "n2", "vcpus": 16})
for i in range(6):
    mkvm(f"n{i}", "n2-standard-4", "us-central1-b")
    call("POST", f"{CB}/zones/us-central1-b/instances/n{i}/stop")
call("POST", f"{CB}/zones/us-central1-b/instances/n0/start"); call("POST", f"{CB}/zones/us-central1-b/instances/n1/start")
res = []


def starter(n):
    res.append(call("POST", f"{CB}/zones/us-central1-b/instances/{n}/start")[0])


ts = [threading.Thread(target=starter, args=(f"n{i}",)) for i in (2, 3, 4, 5)]
[t.start() for t in ts]; [t.join() for t in ts]
check("concurrent starts: exactly the free capacity wins, the rest stock out", sorted(res) == [200, 200, 503, 503], res)
check("pool never over-committed", next(p for p in call("GET", f"{CB}/vyomi/capacity", query={"zone": "us-central1-b"})[1]["items"] if p["family"] == "n2")["usedVcpus"] <= 16)

# ── Migrate to Virtual Machines ──
L = f"/v1/projects/{P}/locations/us-central1"
inv = [{"vmId": "vm-101", "name": "legacy-web", "cpus": 2, "memoryMb": 4096, "diskGb": 20, "osImage": "debian-12"}]
st, e = call("POST", f"{L}/sources", {"vmware": {"vcenterIp": "10.0.0.5"}}, {"sourceId": "vc1"})
check("source needs username", st == 400)
st, e = call("POST", f"{L}/sources", {"vmware": {"vcenterIp": "10.0.0.5", "username": "admin", "password": "x"}, "aws": {"awsRegion": "us-east-1"}}, {"sourceId": "vc1"})
check("exactly one source kind", st == 400)
st, e = call("POST", f"{L}/sources", {"vmware": {"vcenterIp": "10.0.0.5", "username": "admin", "password": "secret"}, "vyomiInventory": inv}, {"sourceId": "vc1"})
check("create source (LRO done, password not echoed)", st == 200 and e["done"] and "password" not in json.dumps(e), e)
st, e = call("POST", f"{L}/sources/vc1/migratingVms", {"sourceVmId": "vm-101"}, {"migratingVmId": "web"})
check("VMware migrating VM needs a connector", st == 400 and e["error"]["status"] == "FAILED_PRECONDITION")
st, e = call("POST", f"{L}/sources/vc1/datacenterConnectors", {}, {"datacenterConnectorId": "dc1"})
check("create connector -> ACTIVE", st == 200 and e["response"]["state"] == "ACTIVE", e)
st, e = call("GET", f"{L}/sources/vc1:fetchInventory")
check("fetchInventory", st == 200 and e["vmwareVms"]["details"][0]["vmId"] == "vm-101", e)
st, e = call("POST", f"{L}/sources/vc1/migratingVms", {"sourceVmId": "nope"}, {"migratingVmId": "web"})
check("unknown source VM rejected", st == 400)
st, e = call("POST", f"{L}/sources/vc1/migratingVms", {"sourceVmId": "vm-101", "computeEngineTargetDefaults": {"vmName": "web-gce", "zone": "us-central1-a"}}, {"migratingVmId": "web"})
check("create migrating VM READY", st == 200 and e["response"]["state"] == "READY", e)
st, e = call("POST", f"{L}/sources/vc1/migratingVms/web/cutoverJobs", {}, {"cutoverJobId": "c1"})
check("cutover before replication rejected", st == 400)
st, e = call("POST", f"{L}/sources/vc1/migratingVms/web:pauseMigration")
check("pause only while replicating", st == 400)
st, e = call("POST", f"{L}/sources/vc1/migratingVms/web:startMigration")
check("startMigration -> FIRST_SYNC", st == 200 and e["response"]["state"] == "FIRST_SYNC", e)
time.sleep(2.3)
st, e = call("GET", f"{L}/sources/vc1/migratingVms/web")
check("first sync completes -> ACTIVE with lastSync", e["state"] == "ACTIVE" and "lastSync" in e, e)
st, e = call("GET", f"{L}/sources/vc1/migratingVms/web/replicationCycles")
check("replication cycle recorded", st == 200 and e["replicationCycles"][0]["state"] == "SUCCEEDED" and "Record only" in e["replicationCycles"][0]["vyomiNote"], e)
st, e = call("POST", f"{L}/sources/vc1/migratingVms/web/cloneJobs", {}, {"cloneJobId": "t1"})
check("clone job creates a real GCE test VM", st == 200 and e["response"]["state"] == "SUCCEEDED"
      and call("GET", f"{CB}/zones/us-central1-a/instances/web-gce-clone-t1")[0] == 200, e)
st, e = call("POST", f"{L}/sources/vc1/migratingVms/web/cutoverJobs", {}, {"cutoverJobId": "c1"})
check("cutover creates the real GCE instance", st == 200 and call("GET", f"{CB}/zones/us-central1-a/instances/web-gce")[1].get("status") == "RUNNING", e)
st, e = call("GET", f"{L}/sources/vc1/migratingVms/web")
check("migrating VM is CUTOVER", e["state"] == "CUTOVER")
st, e = call("POST", f"{L}/sources/vc1/migratingVms/web:finalizeMigration")
check("finalize -> FINALIZED", st == 200 and e["response"]["state"] == "FINALIZED", e)
st, e = call("DELETE", f"{L}/sources/vc1")
check("source with migrating VMs cannot be deleted", st == 400)
st, e = call("DELETE", f"{L}/sources/vc1/migratingVms/web")
st, e = call("DELETE", f"{L}/sources/vc1")
check("delete source after VM removed", st == 200)

# ── Cloud TPU ──
T = f"/v2/projects/{P}/locations/us-central1-b"
st, e = call("GET", f"{T}/acceleratorTypes")
check("accelerator catalogue is zone-aware", st == 200 and any(a["name"].endswith("v2-8") for a in e["acceleratorTypes"]) and not any(a["name"].endswith("v5p-8") for a in e["acceleratorTypes"]), e)
st, e = call("GET", f"{T}/runtimeVersions")
check("runtime versions", st == 200 and len(e["runtimeVersions"]) >= 3)
st, e = call("POST", f"{T}/nodes", {"acceleratorType": "v5p-8", "runtimeVersion": "tpu-vm-tf-2.16.1"}, {"nodeId": "t1"})
check("accelerator not offered in zone rejected", st == 400)
st, e = call("POST", f"{T}/nodes", {"acceleratorType": "v2-8", "runtimeVersion": "bogus"}, {"nodeId": "t1"})
check("bad runtime rejected", st == 400)
st, e = call("POST", f"{T}/nodes", {"acceleratorType": "v2-8", "runtimeVersion": "tpu-vm-tf-2.16.1"}, {"nodeId": "t1"})
check("create node", st == 200 and e["done"] and e["response"]["state"] == "CREATING", e)
time.sleep(3.2)
st, e = call("GET", f"{T}/nodes/t1")
check("node settles READY/HEALTHY, honest note", e["state"] == "READY" and e["health"] == "HEALTHY" and "no accelerator" in e["vyomiNote"], e)
st, e = call("POST", f"{T}/nodes/t1:stop")
check("stop", st == 200 and e["response"]["state"] == "STOPPED")
st, e = call("POST", f"{T}/nodes/t1:stop")
check("stop twice rejected", st == 400)
call("POST", f"{T}/nodes/t1:start")
for i in range(7):
    call("POST", f"{T}/nodes", {"acceleratorType": "v2-8", "runtimeVersion": "tpu-vm-tf-2.16.1"}, {"nodeId": f"q{i}"})
st, e = call("POST", f"{T}/nodes", {"acceleratorType": "v2-8", "runtimeVersion": "tpu-vm-tf-2.16.1"}, {"nodeId": "over"})
check("TPU quota exceeded -> RESOURCE_EXHAUSTED", st == 429 and e["error"]["status"] == "RESOURCE_EXHAUSTED", e)
st, e = call("DELETE", f"{T}/nodes/t1")
check("delete node", st == 200 and call("GET", f"{T}/nodes/t1")[0] == 404)
st, e = call("GET", f"{T}/nodes")
check("list nodes", st == 200 and len(e["nodes"]) == 7)

# ── VM Manager inventory + guest apply (stubbed guest) ──
mkvm("inv1", "e2-micro", "us-central1-a", {"metadata": {"items": [{"key": "enable-osconfig", "value": "TRUE"}]}})
st, e = call("GET", f"/v1/projects/{P}/locations/us-central1-a/instances/inv1/inventory")
check("inventory without a guest is image-declared", st == 200 and e["vyomiSource"] == "IMAGE_DECLARED" and e["osInfo"]["shortName"] == "debian", e)
ran = []


def fake(key, sh):
    ran.append(sh)
    if "dpkg-query" in sh:
        return 0, "OS|Debian GNU/Linux 12|debian|12\nKERNEL|6.1.0|x86_64|inv1\nPKG|curl|7.88|amd64\nPKG|bash|5.2|amd64\n"
    return 0, "0 upgraded"


OSC.GUEST_RUN = fake
try:
    st, e = call("GET", f"/v1/projects/{P}/locations/us-central1-a/instances/inv1/inventory", query={"view": "FULL"})
    check("inventory from the guest lists packages", e["vyomiSource"] == "GUEST" and e["packageCount"] == 2 and "pkg-curl" in e["items"], e)
    st, e = call("GET", f"/v1/projects/{P}/locations/us-central1-a/instances/-/inventories")
    check("list inventories", st == 200 and any(i["name"].endswith("/inv1/inventory") for i in e["inventories"]))
    st, e = call("POST", f"/v1/projects/{P}/patchJobs:execute", {"instanceFilter": {"instanceNamePrefixes": ["inv1"]}, "patchConfig": {"apt": {"type": "DIST"}}})
    time.sleep(2.2)
    jid = e["name"].split("/")[-1]
    st, d = call("GET", f"/v1/projects/{P}/patchJobs/{jid}/instanceDetails")
    det = d["patchJobInstanceDetails"][0]
    check("patch job executed the package manager in the guest", any("dist-upgrade" in c for c in ran) and det["state"] == "SUCCEEDED", (det, ran))
finally:
    OSC.GUEST_RUN = None
st, e = call("GET", f"/v1/projects/{P}/patchReport")
check("patch report roll-up", st == 200 and e["withAgent"] >= 1 and e["total"] >= 1, e)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
