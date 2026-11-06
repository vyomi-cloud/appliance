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

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
