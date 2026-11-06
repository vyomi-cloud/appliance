"""Booster capacity is SYNCHRONOUS and cloud-native: EC2 RunInstances / GCE instances.insert / ARM VM PUT refuse
over-budget launches with the real clouds' error shape BEFORE any record exists; non-booster mode is unchanged."""
import os
import sys
import tempfile

os.environ.setdefault("CLOUDLEARN_STATE_DIR", tempfile.mkdtemp(prefix="booster-cap-"))
os.environ["VYOMI_HOST_MEM_MB"] = "4000"      # cap 2800 -> compute share 1400 MB; one instance = 1024 MB

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
from core import booster as B  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


from core import app_context as _ctx  # noqa: E402
import time as _t  # noqa: E402
_ctx._tier_cache.update({"tier": "max", "verified_at": _t.time(), "ttl": 10 ** 9})
_ctx.STATE["license_claims"] = {"tier": "max"}   # hermetic: never let a developer's local instance count / free-tier quota (tier_quantity_limit) mask the capacity errors
c = TestClient(server.app, base_url="http://127.0.0.1:9000")
c.__enter__()   # run the app lifespan (project registry etc.)
from core import gcp_project  # noqa: E402
GP = gcp_project.project_id()      # the GCP space's own project (others 404 like real GCP)
H = {"content-type": "application/x-www-form-urlencoded"}
SUB = "00000000-0000-0000-0000-cloudlearn01"
VM = f"/subscriptions/{SUB}/resourceGroups/rgb/providers/Microsoft.Compute/virtualMachines"


def run(count, itype="t3.micro"):
    return c.post("/", headers=H, content=f"Action=RunInstances&Version=2016-11-15&ImageId=ami-amzn2023&InstanceType={itype}&MinCount={count}&MaxCount={count}")


def n_ec2():
    return len(server.ec2_state["instances"])


def gce(name, zone="us-central1-a"):
    return c.post(f"/api/gcp/compute/v1/projects/{GP}/zones/{zone}/instances",
                  json={"name": name, "machineType": f"zones/{zone}/machineTypes/e2-small"})


def arm(name):
    return c.put(f"{VM}/{name}?api-version=2023-09-01",
                 json={"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}}})


# ---- booster ON
os.environ["VYOMI_BOOSTER"] = "1"
before = n_ec2()
r = run(2)    # 2 x 1024 > 1400: MaxCount counts against the budget
check("AWS MaxCount=2 over budget -> HTTP 500", r.status_code == 500, r.status_code)
check("AWS XML error InsufficientInstanceCapacity", "<Code>InsufficientInstanceCapacity</Code>" in r.text and "<Errors><Error>" in r.text, r.text)
check("AWS: no instance record created", n_ec2() == before)
r = run(1)
check("AWS single instance within budget passes the gate", "InsufficientInstanceCapacity" not in r.text, r.text[:200])

B.allocate("compute", "hog", 1400, enforce=False)        # exhaust the compute share
before = n_ec2()
r = run(1)
check("AWS full pool -> InsufficientInstanceCapacity 500", r.status_code == 500 and "InsufficientInstanceCapacity" in r.text, r.text)
check("AWS full pool: no record", n_ec2() == before)

r = gce("g1")
try:
    e = r.json().get("error", {})
except Exception:
    e = {}
check("GCP full pool -> HTTP 503", r.status_code == 503, f"{r.status_code} {r.text}")
check("GCP error JSON shape", e.get("code") == 503 and e.get("status") == "UNAVAILABLE"
      and e.get("errors", [{}])[0].get("reason") == "zoneResourcePoolExhausted", r.text)
check("GCP ZONE_RESOURCE_POOL_EXHAUSTED ErrorInfo",
      e.get("details", [{}])[0].get("reason") == "ZONE_RESOURCE_POOL_EXHAUSTED" and "zone" in e.get("message", ""), r.text)
check("GCP: no instance created", c.get(f"/api/gcp/compute/v1/projects/{GP}/zones/us-central1-a/instances/g1").status_code == 404)

r = arm("vmb1")
try:
    ae = r.json().get("error") or {}
except Exception:
    ae = {}
check("Azure full pool -> HTTP 409", r.status_code == 409, f"{r.status_code} {r.text}")
check("Azure error JSON AllocationFailed", ae.get("code") == "AllocationFailed", r.text)
check("Azure: no VM record", c.get(f"{VM}/vmb1?api-version=2023-09-01").status_code == 404)

# ---- capacity returned -> launches pass the gate again; booster OFF unchanged
B.release("compute", "hog")
check("GCP within budget not rejected", gce("g2").status_code != 503)
check("Azure within budget not rejected", arm("vmb2").status_code != 409)

B.allocate("compute", "hog", 1400, enforce=False)
os.environ["VYOMI_BOOSTER"] = "0"
check("non-booster: AWS never capacity-limited", "InsufficientInstanceCapacity" not in run(1).text)
check("non-booster: GCP never 503", gce("g3").status_code != 503)
check("non-booster: Azure never 409", arm("vmb3").status_code != 409)


# =============================================================== reservation, real memory, REST, resize, concurrency
import threading  # noqa: E402
from core import booster as B2  # noqa: E402


def reset_ledger():
    with B._LEDGER_LOCK:
        for k in B._LEDGER:
            B._LEDGER[k].clear()
            B._EXPIRES[k].clear()


os.environ["VYOMI_BOOSTER"] = "1"
reset_ledger()
_ctx._tier_cache.update({"tier": "max", "verified_at": _t.time(), "ttl": 10 ** 9})
_ctx.STATE["license_claims"] = {"tier": "max"}
server._ec2_choose_runtime_backend = lambda *a, **k: "docker"      # no host runtime needed: we test admission/accounting
server._enforce_size_cap = lambda *a, **k: None
server._queue_runtime_start = lambda *a, **k: None

# (1) real instance-type memory (catalog), not a flat 1024
check("memory: t3.micro counts 1024", server._docker_instance_memory_mb({"instance_type": "t3.micro", "cloud": "aws"}) == 1024)
check("memory: t3.large counts its real 8192", server._docker_instance_memory_mb({"instance_type": "t3.large", "cloud": "aws"}) == 8192)
check("memory: GCE e2-small counts 2048", server._docker_instance_memory_mb({"machine_type": "e2-small", "instance_id": "gce-1"}) == 2048)
check("memory: Azure B2s counts 4096", server._docker_instance_memory_mb({"instance_type": "Standard_B2s", "cloud": "azure"}) == 4096)
check("memory: explicit memory_mb wins", server._docker_instance_memory_mb({"instance_type": "t3.large", "memory_mb": 300}) == 300)
os.environ["VYOMI_BOOSTER"] = "0"
check("memory: non-booster behaviour unchanged (flat 1024)", server._docker_instance_memory_mb({"instance_type": "t3.large", "cloud": "aws"}) == 1024)
os.environ["VYOMI_BOOSTER"] = "1"
r = run(1, "t3.large")
check("an 8 GB instance type cannot fit the 1400 MB share -> InsufficientInstanceCapacity", r.status_code == 500 and "InsufficientInstanceCapacity" in r.text, r.text[:200])

# (2) admission RESERVES atomically
reset_ledger()
slots = B2.reserve_slots("compute", 1, 1000, cloud="aws")
check("reserve_slots holds the memory", B2.usage()["compute"] == 1000)
try:
    B2.reserve_slots("compute", 1, 1000, cloud="aws")
    check("second reserve over budget refused", False)
except B2.BoosterCapacityError:
    check("second reserve over budget refused", True)
check("a refused reserve does not leak", B2.usage()["compute"] == 1000)
B2.release_slots("compute", slots)
check("release_slots returns the memory", B2.usage()["compute"] == 0)
try:
    B2.reserve_slots("compute", 2, 1000, cloud="aws")
    check("all-or-nothing: 2 x 1000 > 1400 refused", False)
except B2.BoosterCapacityError:
    check("all-or-nothing: 2 x 1000 > 1400 refused", B2.usage()["compute"] == 0)
B2.SLOT_TTL_S, old_ttl = 0.05, B2.SLOT_TTL_S
B2.reserve_slots("compute", 1, 1000, cloud="aws")
import time as _time  # noqa: E402
_time.sleep(0.1)
check("an admission slot never consumed expires (no permanent leak)", B2.usage()["compute"] == 0)
B2.SLOT_TTL_S = old_ttl

# a successful RunInstances leaves the instance holding its reservation; terminate-equivalent release frees it
reset_ledger()
before = n_ec2()
r = run(1)
iids = [i for i in server.ec2_state["instances"] if i not in list(server.ec2_state["instances"])[:before]]
check("RunInstances within budget creates the instance", r.status_code == 200 and n_ec2() == before + 1, r.text[:200])
check("instance holds a reservation under its own id (no stray slot)",
      B2.usage()["compute"] == 1024 and not any(k.startswith("rsv:") for k in B._LEDGER["compute"]), B._LEDGER)
new_id = next(k for k in B._LEDGER["compute"])
check("reservation key is the real instance id", new_id in server.ec2_state["instances"], new_id)
r = run(1)
check("second 1024 MB instance refused while the first holds its share", r.status_code == 500 and "InsufficientInstanceCapacity" in r.text)
B2.release("compute", new_id)
check("terminate/fail release frees capacity", B2.usage()["compute"] == 0)

# (3) REST create path now pre-checked (it used to bypass the gate)
reset_ledger()
B2.allocate("compute", "hog", 1400, enforce=False)
before = n_ec2()
rr = c.post("/api/ec2/instances", json={"name": "rest1", "instance_type": "t3.micro", "ami": "ami-amzn2023"})
check("REST EC2 create over budget -> refused with the capacity code",
      rr.status_code in (500, 503) and "InsufficientInstanceCapacity" in rr.text and n_ec2() == before, f"{rr.status_code} {rr.text[:200]}")
B2.release("compute", "hog")
rr = c.post("/api/ec2/instances", json={"name": "rest2", "instance_type": "t3.micro", "ami": "ami-amzn2023"})
check("REST EC2 create within budget is admitted and reserves", rr.status_code in (200, 201) and B2.usage()["compute"] == 1024, f"{rr.status_code} {rr.text[:200]}")

# Azure resize: new size must fit (it used to bypass the gate)
reset_ledger()
arm("vmr1")                                            # B1s: 1024
vmr = server._azure_state_for_tests() if hasattr(server, "_azure_state_for_tests") else None
resize = c.put(f"{VM}/vmr1?api-version=2023-09-01",
               json={"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B2s"}}})   # 4096 > 1400
ae = (resize.json().get("error") or {}) if resize.headers.get("content-type", "").startswith("application/json") else {}
check("Azure VM resize beyond the share -> 409 AllocationFailed", resize.status_code == 409 and ae.get("code") == "AllocationFailed", f"{resize.status_code} {resize.text[:200]}")
resize = c.put(f"{VM}/vmr1?api-version=2023-09-01",
               json={"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}}})
check("Azure VM same-size update still allowed", resize.status_code != 409, resize.status_code)

# (4) concurrency: N simultaneous admissions can never oversubscribe
reset_ledger()
results, lock = [], threading.Lock()
start = threading.Barrier(16)


def worker():
    start.wait()
    try:
        ids = B2.reserve_slots("compute", 1, 400, cloud="aws")
        with lock:
            results.append(("ok", ids))
    except B2.BoosterCapacityError:
        with lock:
            results.append(("full", None))


ts = [threading.Thread(target=worker) for _ in range(16)]
[t.start() for t in ts]
[t.join() for t in ts]
ok = sum(1 for r_ in results if r_[0] == "ok")
check("16 concurrent 400 MB reservations vs 1400 MB: exactly 3 admitted", ok == 3 and B2.usage()["compute"] == 1200, f"ok={ok} used={B2.usage()}")

reset_ledger()
before = n_ec2()
codes = []
gate = threading.Barrier(6)


def conc_run():
    gate.wait()
    cc = TestClient(server.app, base_url="http://127.0.0.1:9000")
    codes.append(run_with(cc))


def run_with(cl):
    r_ = cl.post("/", headers=H, content="Action=RunInstances&Version=2016-11-15&ImageId=ami-amzn2023&InstanceType=t3.micro&MinCount=1&MaxCount=1")
    return r_.status_code if "InsufficientInstanceCapacity" not in r_.text else 500


ts = [threading.Thread(target=conc_run) for _ in range(6)]
[t.start() for t in ts]
[t.join() for t in ts]
created = n_ec2() - before
check("6 concurrent RunInstances (1024 MB each, 1400 MB share): at most one instance is created", created <= 1, f"created={created} codes={codes}")
check("ledger never exceeds the share after the race", B2.usage()["compute"] <= 1400, B2.usage())

# budget override env
os.environ["VYOMI_BOOSTER_CAP_MB"] = "8192"
check("VYOMI_BOOSTER_CAP_MB sets the cap", B2.resource_budget()["memory_cap_mb"] == 8192)
del os.environ["VYOMI_BOOSTER_CAP_MB"]
reset_ledger()

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
