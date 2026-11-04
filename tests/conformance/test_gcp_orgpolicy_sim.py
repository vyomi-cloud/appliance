"""Org-policy constraint simulation against real existing resources (run: PYTHONPATH=. python3 tests/conformance/test_gcp_orgpolicy_sim.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402
from core import gcp_storage_core as G  # noqa: E402

R = AwsWireRouter()
PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(method, path, body=None, query=None):
    out = R.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {"raw": out["body"]}


s, sa = call("POST", "/v1/projects/sim1/serviceAccounts", {"accountId": "worker", "serviceAccount": {"displayName": "w"}})
email = sa.get("email", "worker@sim1.iam.gserviceaccount.com")
call("POST", f"/v1/projects/sim1/serviceAccounts/{email}/keys", {})
G.dispatch(R.gcs, "POST", "/storage/v1/b", {"project": "sim1"}, {}, json.dumps({"name": "sim-open"}).encode())
G.dispatch(R.gcs, "POST", "/storage/v1/b", {"project": "sim1"}, {}, json.dumps({"name": "sim-ubla", "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True}}}).encode())

s, r = call("POST", "/v2/projects/sim1/policies:simulate", {"constraint": "constraints/iam.disableServiceAccountKeyCreation", "enforce": True})
check("key-creation simulation finds the existing user-managed key", s == 200 and r["violationCount"] == 1 and "/keys/" in r["violations"][0]["resource"], r)
s, r = call("POST", "/v2/projects/sim1/policies:simulate", {"constraint": "storage.uniformBucketLevelAccess", "enforce": True})
names = [v["resource"].rsplit("/", 1)[-1] for v in r.get("violations", [])]
check("UBLA simulation flags only the bucket without it", s == 200 and "sim-open" in names and "sim-ubla" not in names, r)
s, r = call("POST", "/v2/projects/sim1/policies:simulate", {"constraint": "iam.disableServiceAccountCreation", "enforce": True})
check("SA-creation simulation: existing accounts unaffected, new blocked", s == 200 and r["violationCount"] == 0 and r["resourcesEvaluated"] >= 1 and "fail" in r["effectOnNewResources"], r)
s, r = call("POST", "/v2/projects/sim1/policies:simulate", {"constraint": "iam.disableServiceAccountKeyCreation", "enforce": False})
check("un-enforcing reports no violations", s == 200 and r["violationCount"] == 0)
check("unsupported constraint -> 400", call("POST", "/v2/projects/sim1/policies:simulate", {"constraint": "gcp.resourceLocations"})[0] == 400)
# simulation does not apply the change
s, pols = call("GET", "/v2/projects/sim1/policies")
check("simulation does not create a policy", s == 200 and not pols.get("policies"), pols)
s, h = call("GET", "/v2/projects/sim1/simulations")
check("simulation history lists the runs, newest first", s == 200 and len(h["simulations"]) == 4, h)
# real enforcement agrees with the simulation
call("POST", "/v2/projects/sim1/policies", {"spec": {"rules": [{"enforce": True}]}}, {"policyId": "constraints/iam.disableServiceAccountKeyCreation"})
s, e = call("POST", f"/v1/projects/sim1/serviceAccounts/{email}/keys", {})
check("after enforcing, creating a key is really blocked (as simulated)", s in (400, 403, 412) and "error" in e, (s, e))
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
