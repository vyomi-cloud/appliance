"""Cloud Deploy v1: pipelines/targets/releases/rollouts state machine deploying to the simulator's Cloud Run + GKE.
Run: PYTHONPATH=. python tests/conformance/test_gcp_clouddeploy_core.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False
R = AwsWireRouter()
PASS = FAIL = 0
P, L = "deploy-proj", "us-central1"


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


B = f"/v1/projects/{P}/locations/{L}"
DP, TG = B + "/deliveryPipelines", B + "/targets"
IMG1 = "us-central1-docker.pkg.dev/deploy-proj/app/web:v1"
IMG2 = "us-central1-docker.pkg.dev/deploy-proj/app/web:v2"
IMG3 = "us-central1-docker.pkg.dev/deploy-proj/app/web:v3"

# targets
check("target needs exactly one runtime", call("POST", TG, {}, {"targetId": "dev"})[0] == 400)
check("bad gke cluster path", call("POST", TG, {"gke": {"cluster": "nope"}}, {"targetId": "dev"})[0] == 400)
check("multiTarget not simulated", call("POST", TG, {"multiTarget": {"targetIds": ["a"]}}, {"targetId": "dev"})[0] == 400)
st, o = call("POST", TG, {"run": {"location": f"projects/{P}/locations/{L}"}}, {"targetId": "dev"})
check("create run target", st == 200 and o["done"] and o["response"]["targetId"] == "dev", o)
check("dup target", call("POST", TG, {"run": {"location": f"projects/{P}/locations/{L}"}}, {"targetId": "dev"})[0] == 409)
call("POST", TG, {"run": {"location": f"projects/{P}/locations/{L}"}, "requireApproval": True}, {"targetId": "prod"})
call("POST", TG, {"gke": {"cluster": f"projects/{P}/locations/{L}/clusters/ghost"}}, {"targetId": "gke-missing"})

# pipelines
check("pipeline needs stages", call("POST", DP, {"serialPipeline": {"stages": []}}, {"deliveryPipelineId": "web"})[0] == 400)
check("dup stage target", call("POST", DP, {"serialPipeline": {"stages": [{"targetId": "dev"}, {"targetId": "dev"}]}}, {"deliveryPipelineId": "web"})[0] == 400)
check("predeploy hooks refused", call("POST", DP, {"serialPipeline": {"stages": [{"targetId": "dev", "strategy": {"standard": {"predeploy": {"actions": ["a"]}}}}]}}, {"deliveryPipelineId": "web"})[0] == 400)
st, o = call("POST", DP, {"serialPipeline": {"stages": [{"targetId": "dev"}, {"targetId": "prod"}]}, "deployParameters": {"service": "web"}}, {"deliveryPipelineId": "web"})
check("create pipeline", st == 200, o)
pg = call("GET", DP + "/web")[1]
check("pipeline ready", pg["condition"]["pipelineReadyCondition"]["status"] is True)
call("POST", DP, {"serialPipeline": {"stages": [{"targetId": "ghost"}]}}, {"deliveryPipelineId": "broken"})
check("missing target condition", call("GET", DP + "/broken")[1]["condition"]["targetsPresentCondition"]["missingTargets"][0].endswith("/targets/ghost"))
check("release on broken pipeline", call("POST", DP + "/broken/releases", {"buildArtifacts": [{"image": "web", "tag": IMG1}]}, {"releaseId": "r1"})[0] == 400)
check("target in use cannot be deleted", call("DELETE", TG + "/dev")[0] == 400)

# release renders + first rollout deploys to a REAL Cloud Run service
REL = DP + "/web/releases"
check("release needs artifacts", call("POST", REL, {}, {"releaseId": "r1"})[0] == 400)
check("artifact needs tag", call("POST", REL, {"buildArtifacts": [{"image": "web"}]}, {"releaseId": "r1"})[0] == 400)
st, o = call("POST", REL, {"buildArtifacts": [{"image": "web", "tag": IMG1}]}, {"releaseId": "rel-1"})
check("create release", st == 200 and o["response"]["renderState"] == "SUCCEEDED", o)
ro = call("GET", REL + "/rel-1/rollouts")[1]["rollouts"]
check("first rollout auto-created and SUCCEEDED", len(ro) == 1 and ro[0]["state"] == "SUCCEEDED" and ro[0]["name"].endswith("rel-1-to-dev-0001"), ro)
svc = call("GET", f"/v2/projects/{P}/locations/{L}/services/web")[1]
check("Cloud Run service really deployed", svc.get("template", {}).get("containers", [{}])[0].get("image") == IMG1, svc)
jr = call("GET", REL + "/rel-1/rollouts/" + ro[0]["name"].rsplit("/", 1)[-1] + "/jobRuns")[1]["jobRuns"]
check("job run recorded", len(jr) == 1 and jr[0]["jobId"] == "deploy" and jr[0]["state"] == "SUCCEEDED", jr)

# promote to the approval-gated stage
st, o = call("POST", REL + "/rel-1/rollouts", {"targetId": "prod"}, {"rolloutId": "to-prod"})
check("prod rollout waits for approval", st == 200 and o["response"]["state"] == "PENDING_APPROVAL" and o["response"]["approvalState"] == "NEEDS_APPROVAL", o)
check("not deployed before approval", call("GET", f"/v2/projects/{P}/locations/{L}/services/web")[1]["template"]["containers"][0]["image"] == IMG1)
RP = REL + "/rel-1/rollouts/to-prod"
check("approve needs bool", call("POST", RP + ":approve", {})[0] == 400)
check("approve", call("POST", RP + ":approve", {"approved": True})[0] == 200)
r = call("GET", RP)[1]
check("approved rollout SUCCEEDED", r["state"] == "SUCCEEDED" and r["approvalState"] == "APPROVED", r)
check("approve twice refused", call("POST", RP + ":approve", {"approved": True})[0] == 400)

# rejection
call("POST", REL, {"buildArtifacts": [{"image": "web", "tag": IMG2}]}, {"releaseId": "rel-2"})
call("POST", REL + "/rel-2/rollouts", {"targetId": "prod"}, {"rolloutId": "rej"})
call("POST", REL + "/rel-2/rollouts/rej:approve", {"approved": False})
check("rejected rollout", call("GET", REL + "/rel-2/rollouts/rej")[1]["state"] == "APPROVAL_REJECTED")
check("rel-2 on dev deployed", call("GET", f"/v2/projects/{P}/locations/{L}/services/web")[1]["template"]["containers"][0]["image"] == IMG2)

# rollback to previous release on dev
st, o = call("POST", DP + "/web:rollbackTarget", {"targetId": "dev", "rollbackId": "rb-1"})
check("rollback", st == 200 and o["rollbackConfig"]["rollout"]["name"].endswith("/rel-1/rollouts/rb-1"), o)
check("rollback redeployed rel-1", call("GET", f"/v2/projects/{P}/locations/{L}/services/web")[1]["template"]["containers"][0]["image"] == IMG1)
check("rolledBackBy linked", call("GET", REL + "/rel-2/rollouts/" + "rel-2-to-dev-0001")[1]["rolledBackByRollouts"][0].endswith("/rb-1"))

# abandon
check("abandon", call("POST", REL + "/rel-2:abandon", {})[0] == 200)
check("abandoned release refuses rollouts", call("POST", REL + "/rel-2/rollouts", {"targetId": "dev"}, {"rolloutId": "x"})[0] == 400)

# failure path: GKE cluster missing -> FAILED, then cancel/ignore
call("POST", DP, {"serialPipeline": {"stages": [{"targetId": "gke-missing"}]}}, {"deliveryPipelineId": "g"})
call("POST", DP + "/g/releases", {"buildArtifacts": [{"image": "a", "tag": IMG1}]}, {"releaseId": "g1"})
gr = call("GET", DP + "/g/releases/g1/rollouts")[1]["rollouts"][0]
check("missing cluster -> FAILED with cause", gr["state"] == "FAILED" and "ghost" in gr["failureReason"] and gr["phases"][0]["deploymentJobs"]["deployJob"]["state"] == "FAILED", gr)
check("retry still fails", call("POST", DP + "/g/releases/g1/rollouts/" + gr["name"].rsplit("/", 1)[-1] + ":retryJob", {"phaseId": "stable", "jobId": "deploy"})[0] == 200
      and call("GET", gr["name"].replace("projects", "/v1/projects", 1) if False else "/v1/" + gr["name"])[1]["state"] == "FAILED")
check("ignore job completes rollout", call("POST", "/v1/" + gr["name"] + ":ignoreJob", {"phaseId": "stable", "jobId": "deploy"})[0] == 200
      and call("GET", "/v1/" + gr["name"])[1]["state"] == "SUCCEEDED")

# real GKE deploy + canary
c = {"name": "gke1", "initialNodeCount": 1}
st, o = call("POST", f"/v1/projects/{P}/locations/{L}/clusters", {"cluster": c})
call("POST", TG, {"gke": {"cluster": f"projects/{P}/locations/{L}/clusters/gke1"}}, {"targetId": "gke-t"})
call("POST", DP, {"serialPipeline": {"stages": [{"targetId": "gke-t", "strategy": {"canary": {"canaryDeployment": {"percentages": [25, 50], "verify": True}}}}]},
                  "deployParameters": {"deployment": "api", "namespace": "default"}}, {"deliveryPipelineId": "k"})
st, o = call("POST", DP + "/k/releases", {"buildArtifacts": [{"image": "api", "tag": IMG1}]}, {"releaseId": "k1"})
check("gke release", st == 200, o)
kr = call("GET", DP + "/k/releases/k1/rollouts")[1]["rollouts"][0]
check("canary: first phase done, rollout paused IN_PROGRESS", kr["state"] == "IN_PROGRESS" and [p["state"] for p in kr["phases"]] == ["SUCCEEDED", "PENDING", "PENDING"], kr)
check("canary phase ids", [p["id"] for p in kr["phases"]] == ["canary-25", "canary-50", "stable"])
check("verify job ran", kr["phases"][0]["deploymentJobs"]["verifyJob"]["state"] == "SUCCEEDED")
KR = "/v1/" + kr["name"]
check("advance out of order refused", call("POST", KR + ":advance", {"phaseId": "stable"})[0] == 400)
check("advance canary-50", call("POST", KR + ":advance", {"phaseId": "canary-50"})[0] == 200)
check("advance stable", call("POST", KR + ":advance", {"phaseId": "stable"})[0] == 200)
check("canary rollout SUCCEEDED", call("GET", KR)[1]["state"] == "SUCCEEDED")
st, dep = call("GET", f"/v1/projects/{P}/locations/{L}/clusters/gke1")
dps = R.gcp_gke.k8s[f"projects/{P}/locations/{L}/clusters/gke1"]["deployments"]
check("GKE Deployment really created with image", dps.get("default/api", {}).get("spec", {}).get("template", {}).get("spec", {}).get("containers", [{}])[0].get("image") == IMG1, list(dps))
check("canary deployment cleaned up at stable", "default/api-canary" not in dps)

# verify failure
call("POST", DP, {"serialPipeline": {"stages": [{"targetId": "gke-t", "strategy": {"standard": {"verify": True}}}]}, "deployParameters": {"deployment": "v", "vyomi-verify": "fail"}}, {"deliveryPipelineId": "vp"})
call("POST", DP + "/vp/releases", {"buildArtifacts": [{"image": "a", "tag": IMG3}]}, {"releaseId": "v1"})
vr = call("GET", DP + "/vp/releases/v1/rollouts")[1]["rollouts"][0]
check("verify failure fails rollout", vr["state"] == "FAILED" and vr["phases"][0]["deploymentJobs"]["verifyJob"]["state"] == "FAILED" and vr["phases"][0]["deploymentJobs"]["deployJob"]["state"] == "SUCCEEDED", vr)
check("cancel a failed rollout refused", call("POST", "/v1/" + vr["name"] + ":cancel", {})[0] == 400)

# cancel a paused canary
call("POST", DP + "/k/releases", {"buildArtifacts": [{"image": "api", "tag": IMG2}]}, {"releaseId": "k2"})
k2 = call("GET", DP + "/k/releases/k2/rollouts")[1]["rollouts"][0]
check("cancel paused canary", call("POST", "/v1/" + k2["name"] + ":cancel", {})[0] == 200 and call("GET", "/v1/" + k2["name"])[1]["state"] == "CANCELLED")

# delete rules
check("pipeline with releases needs force", call("DELETE", DP + "/web")[0] == 400)
check("force delete", call("DELETE", DP + "/web", None, {"force": "true"})[0] == 200 and call("GET", DP + "/web")[0] == 404)
check("list pipelines", len(call("GET", DP)[1]["deliveryPipelines"]) >= 3)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
