"""Cloud Run continuous deployment: a Cloud Build trigger on a (Vyomi/Gitea-seam) source repo builds the Dockerfile, pushes to
Artifact Registry and deploys the image to Cloud Run with the standard `gcloud run deploy|services update` step.
The container builder is a hermetic stub here (BuildKit on the appliance). Run: PYTHONPATH=. python tests/conformance/test_gcp_run_continuous_deployment.py"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import ci_core as ci  # noqa: E402
from core.aws_wire_router import AwsWireRouter  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False


class StubBuilder:
    name, runs_containers = "stub-buildkit", True

    def build(self, job, tree, log):
        tag = job["spec"]["tag"]
        return {"ok": True, "artifact": {"type": "image", "tag": tag, "digest": "sha256:" + hashlib.sha256((tag + tree.get("Dockerfile", b"").decode()).encode()).hexdigest(), "size": 10}}

    def export(self, tag):
        return {"layers": [tag.encode()], "config": json.dumps({"os": "linux"}).encode()}


ci.set_builder(StubBuilder())
R = AwsWireRouter()
PASS = FAIL = 0
P, REG = "cd-proj", "us-central1"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:600] if detail and not ok else ''}")


def call(method, path, body=None, query=None):
    out = R.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {}


B = f"/v1/projects/{P}"
IMG = f"{REG}-docker.pkg.dev/{P}/cloud-run-source-deploy/shop"
DOCKER = "gcr.io/cloud-builders/docker"
SDK = "gcr.io/google.com/cloudsdktool/cloud-sdk:slim"
check("AR repo", call("POST", f"{B}/locations/{REG}/repositories", {"format": "DOCKER"}, {"repositoryId": "cloud-run-source-deploy"})[0] == 200)
cfg = {"steps": [
    {"name": DOCKER, "args": ["build", "-t", IMG + ":$COMMIT_SHA", "."]},
    {"name": DOCKER, "args": ["push", IMG + ":$COMMIT_SHA"]},
    {"name": SDK, "entrypoint": "gcloud", "args": ["run", "deploy", "shop", "--image", IMG + ":$COMMIT_SHA", "--region", REG, "--platform", "managed",
                                                    "--labels", "managed-by=gcp-cloud-build-deploy-cloud-run,commit-sha=$COMMIT_SHA", "--quiet"]}]}
st, t = call("POST", B + "/triggers", {"name": "deploy-shop", "triggerTemplate": {"repoName": "shop", "branchName": "^main$"}, "build": cfg})
check("trigger created", st == 200, t)

st, o = call("POST", B + "/triggers:vyomiPush", {"repoName": "shop", "branch": "main", "files": {"Dockerfile": "FROM scratch\nCOPY app /app\n", "app": "v1"}, "message": "v1"})
check("push fired the trigger", st == 200 and len(o["builds"]) == 1, o)
sha1 = o["commitSha"]
b = call("GET", f"{B}/builds/{o['builds'][0]}")[1]
check("build SUCCEEDED incl. deploy step", b["status"] == "SUCCESS" and [s["status"] for s in b["steps"]] == ["SUCCESS"] * 3, b.get("failureInfo") or b.get("vyomiLogs"))
st, svc = call("GET", f"/v2/projects/{P}/locations/{REG}/services/shop")
check("Cloud Run service created from the repo", st == 200 and svc["template"]["containers"][0]["image"] == f"{IMG}:{sha1}", svc)
check("labels applied", svc["labels"].get("commit-sha") == sha1, svc.get("labels"))
rev1 = svc["latestReadyRevision"]

st, o = call("POST", B + "/triggers:vyomiPush", {"repoName": "shop", "branch": "main", "files": {"app": "v2"}, "message": "v2"})
sha2 = o["commitSha"]
st, svc = call("GET", f"/v2/projects/{P}/locations/{REG}/services/shop")
check("next push cuts a NEW revision with the new image", svc["template"]["containers"][0]["image"] == f"{IMG}:{sha2}" and svc["latestReadyRevision"] != rev1, svc)
st, revs = call("GET", f"/v2/projects/{P}/locations/{REG}/services/shop/revisions")
check("two revisions", st == 200 and len(revs["revisions"]) == 2, revs)
st, imgs = call("GET", f"{B}/locations/{REG}/repositories/cloud-run-source-deploy/dockerImages")
check("both images in Artifact Registry", len(imgs.get("dockerImages", [])) == 2, imgs)

# other branch does not deploy
st, o = call("POST", B + "/triggers:vyomiPush", {"repoName": "shop", "branch": "feature", "files": {"app": "wip"}, "message": "wip"})
check("push to a non-matching branch deploys nothing", st == 200 and not o.get("builds"), o)

# Binary Authorization gates the continuous deployment
ANAME = f"projects/{P}/attestors/prod"
from core import gcp_binauthz_core as ba  # noqa: E402
priv = 12345678901234567890
pem = ba.point_to_pem(ba.public_point(priv))
call("POST", f"{B}/attestors", {"userOwnedGrafeasNote": {"noteReference": f"projects/{P}/notes/n", "publicKeys": [{"pkixPublicKey": {"publicKeyPem": pem, "signatureAlgorithm": "ECDSA_P256_SHA256"}}]}}, {"attestorId": "prod"})
check("enable Binary Authorization (default policy still allows)", call("PATCH", f"/v2/projects/{P}/locations/{REG}/services/shop", {"binaryAuthorization": {"useDefault": True}}, {"updateMask": "binaryAuthorization"})[0] == 200)
call("PUT", B + "/policy", {"defaultAdmissionRule": {"evaluationMode": "REQUIRE_ATTESTATION", "enforcementMode": "ENFORCED_BLOCK_AND_AUDIT_LOG", "requireAttestationsBy": [ANAME]}})
st, o = call("POST", B + "/triggers:vyomiPush", {"repoName": "shop", "branch": "main", "files": {"app": "v3"}, "message": "v3"})
b = call("GET", f"{B}/builds/{o['builds'][0]}")[1]
check("unattested image: deploy step FAILS under Binary Authorization", b["status"] == "FAILURE" and "Binary Authorization" in json.dumps(b["failureInfo"]), b.get("failureInfo"))
st, svc = call("GET", f"/v2/projects/{P}/locations/{REG}/services/shop")
check("service still serves the previous revision", svc["template"]["containers"][0]["image"] == f"{IMG}:{sha2}", svc)

# step validation
def run(args, name=SDK):
    return call("POST", f"{B}/builds", {"steps": [{"name": name, "entrypoint": "gcloud", "args": args}]})[1]["response"]
b = run(["run", "deploy", "x", "--image", "i"])
check("--region is required", b["status"] == "FAILURE" and "--region" in b["failureInfo"]["detail"], b)
b = run(["run", "services", "update", "ghost", "--image", "i", "--region", REG])
check("services update of a missing service fails", b["status"] == "FAILURE" and "could not be found" in b["failureInfo"]["detail"], b)
b = run(["compute", "instances", "list"])
check("other gcloud commands are not faked", b["status"] == "FAILURE" and "cannot run in Vyomi" in b["failureInfo"]["detail"], b)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
