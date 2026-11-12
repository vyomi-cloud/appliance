"""GCP Compute rollouts (REAL rolling replace over managed instance groups, health check, rollback) + preview features.
Run: PYTHONPATH=. python3 tests/conformance/test_gcp_computesim.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False
R = AwsWireRouter()
PASS = FAIL = 0
P = "rl-proj-1"
G = f"/compute/v1/projects/{P}/global"
Z = f"/compute/v1/projects/{P}/zones/us-central1-a"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:400] if detail and not ok else ''}")


def call(method, path, body=None, query=None):
    out = R.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {}


def tpl(name, mt="e2-medium"):
    return call("POST", f"{G}/instanceTemplates", {"name": name, "properties": {
        "machineType": mt, "disks": [{"boot": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}],
        "networkInterfaces": [{"network": "default"}]}})


def members(mig):
    s, d = call("GET", f"{Z}/instanceGroupManagers/{mig}")
    return d["members"] if "members" in d else None


def mig_tpl(mig):
    return call("GET", f"{Z}/instanceGroupManagers/{mig}")[1]["instanceTemplate"].rsplit("/", 1)[-1]


s, d = tpl("tpl-v1")
check("template v1", s == 200, d)
check("template v2", tpl("tpl-v2", "e2-standard-2")[0] == 200)
s, d = call("POST", f"{Z}/instanceGroupManagers", {"name": "web", "instanceTemplate": f"{G}/instanceTemplates/tpl-v1", "targetSize": 2})
check("MIG web with 2 real members", s == 200 and len(members("web") or []) == 2, d)
check("MIG api with 1 member", call("POST", f"{Z}/instanceGroupManagers", {"name": "api", "instanceTemplate": f"{G}/instanceTemplates/tpl-v1", "targetSize": 1})[0] == 200)
old_web = set(members("web"))

plan = {"name": "plan1", "locationScope": "ZONE", "waves": [
    {"number": 1, "displayName": "canary", "selectors": [{"locationSelector": {"includedLocations": ["us-central1-a"]}}], "vyomiManagedInstanceGroups": ["api"]},
    {"number": 2, "displayName": "rest", "selectors": [{"locationSelector": {"includedLocations": ["us-central1-a"]}}], "vyomiManagedInstanceGroups": ["web"]}]}
s, d = call("POST", f"{G}/rolloutPlans", plan)
check("plan insert returns DONE operation", s == 200 and d["status"] == "DONE", d)
check("duplicate plan 409", call("POST", f"{G}/rolloutPlans", plan)[0] == 409)
check("bad wave numbering 400", call("POST", f"{G}/rolloutPlans", {**plan, "name": "bad", "waves": [{**plan["waves"][0], "number": 2}]})[0] == 400)
check("bad zone for ZONE scope 400", call("POST", f"{G}/rolloutPlans", {"name": "bad2", "waves": [{"selectors": [{"locationSelector": {"includedLocations": ["us-central1"]}}]}]})[0] == 400)
s, d = call("GET", f"{G}/rolloutPlans/plan1")
check("plan get", s == 200 and len(d["waves"]) == 2, d)
check("rollout with unknown template 400", call("POST", f"{G}/rollouts", {"name": "r0", "rolloutPlan": "plan1", "instanceTemplate": "nope"})[0] == 400)
check("rollout whose wave selects no MIG 400", call("POST", f"{G}/rolloutPlans", {"name": "empty", "waves": [{"selectors": [{"locationSelector": {"includedLocations": ["asia-east1-a"]}}]}]})[0] == 200
      and call("POST", f"{G}/rollouts", {"name": "r00", "rolloutPlan": "empty", "instanceTemplate": "tpl-v2"})[0] == 400)

s, d = call("POST", f"{G}/rollouts", {"name": "r1", "rolloutPlan": "plan1", "instanceTemplate": "tpl-v2"})
check("rollout created, nothing touched yet", s == 200 and mig_tpl("web") == "tpl-v1" and set(members("web")) == old_web, d)
s, ro = call("GET", f"{G}/rollouts/r1")
check("RUNNING at wave 1", ro["state"] == "RUNNING" and ro["currentWaveNumber"] == 1, ro)
old_api = set(members("api"))
call("POST", f"{G}/rollouts/r1:advance")
s, ro = call("GET", f"{G}/rollouts/r1")
check("wave 1 really rolled api to tpl-v2 (new instances)", mig_tpl("api") == "tpl-v2" and not (set(members("api")) & old_api) and len(members("api")) == 1, ro)
check("web untouched until wave 2", mig_tpl("web") == "tpl-v1" and set(members("web")) == old_web)
check("now at wave 2, wave 1 SUCCEEDED", ro["currentWaveNumber"] == 2 and ro["waveDetails"][0]["status"] == "SUCCEEDED", ro)
inst = call("GET", f"{Z}/instances/{members('api')[0]}")[1]
check("new member is a real RUNNING instance", inst.get("status") == "RUNNING", inst)
call("POST", f"{G}/rollouts/r1:advance")
s, ro = call("GET", f"{G}/rollouts/r1")
check("wave 2 rolled web, rollout SUCCEEDED", ro["state"] == "SUCCEEDED" and mig_tpl("web") == "tpl-v2" and not (set(members("web")) & old_web) and len(members("web")) == 2, ro)
check("old web instances are gone", all(call("GET", f"{Z}/instances/{m}")[0] == 404 for m in old_web))
check("advance on SUCCEEDED rejected 412", call("POST", f"{G}/rollouts/r1:advance")[0] == 412)
call("POST", f"{G}/rollouts/r1:rollback")
s, ro = call("GET", f"{G}/rollouts/r1")
check("rollback restores both groups to tpl-v1", ro["state"] == "ROLLED_BACK" and mig_tpl("web") == "tpl-v1" and mig_tpl("api") == "tpl-v1" and len(members("web")) == 2, ro)
check("plan in use by no active rollout can be deleted-protected? (ROLLED_BACK allows delete)", call("DELETE", f"{G}/rolloutPlans/plan1")[0] == 200)
check("delete finished rollout", call("DELETE", f"{G}/rollouts/r1")[0] == 200)

call("POST", f"{G}/rolloutPlans", plan)
call("POST", f"{G}/rollouts", {"name": "r2", "rolloutPlan": "plan1", "instanceTemplate": "tpl-v2"})
check("active rollout blocks plan delete", call("DELETE", f"{G}/rolloutPlans/plan1")[0] == 412)
call("POST", f"{G}/rollouts/r2:cancel")
check("cancel -> CANCELLED", call("GET", f"{G}/rollouts/r2")[1]["state"] == "CANCELLED")
check("cancel twice 412", call("POST", f"{G}/rollouts/r2:cancel")[0] == 412)

# failure -> automatic rollback: template deleted from under the rollout
call("POST", f"{G}/rollouts", {"name": "r3", "rolloutPlan": "plan1", "instanceTemplate": "tpl-v2"})
call("DELETE", f"{G}/instanceTemplates/tpl-v2")
call("POST", f"{G}/rollouts/r3:advance")
s, ro = call("GET", f"{G}/rollouts/r3")
check("wave failure auto-rolls back", ro["state"] == "ROLLED_BACK" and ro.get("error") and mig_tpl("api") == "tpl-v1", ro)

# preview features
s, d = call("GET", f"/compute/beta/projects/{P}/global/previewFeatures")
names = [x["name"] for x in d.get("items", [])]
check("catalogue listed, all DISABLED, labelled config-only", s == 200 and names and all(x["activationStatus"] == "DISABLED" and "Config only" in x["vyomiNote"] for x in d["items"]), d)
s, d = call("PATCH", f"/compute/beta/projects/{P}/global/previewFeatures/{names[0]}", {"activationStatus": "ACTIVATED"})
check("enroll", s == 200 and d["status"] == "DONE", d)
s, d = call("GET", f"/compute/beta/projects/{P}/global/previewFeatures/{names[0]}")
check("enrolment persisted", d["activationStatus"] == "ACTIVATED" and d.get("updateTime"), d)
check("other project unaffected", call("GET", f"/compute/beta/projects/other/global/previewFeatures/{names[0]}")[1]["activationStatus"] == "DISABLED")
check("bad status 400", call("PATCH", f"/compute/beta/projects/{P}/global/previewFeatures/{names[0]}", {"activationStatus": "MAYBE"})[0] == 400)
check("unknown feature 404", call("GET", f"/compute/beta/projects/{P}/global/previewFeatures/zzz")[0] == 404)

print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
