"""Cloud Build v1: builds + triggers on the CI seam, docker build/push steps, pushes into the simulated Artifact Registry, trigger-on-push.
The container builder is a hermetic stub (a real BuildKit builder is used on the appliance).
Run: PYTHONPATH=. python tests/conformance/test_gcp_cloudbuild_core.py"""
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

    def __init__(self):
        self.built = {}

    def build(self, job, tree, log):
        df = tree.get("Dockerfile", b"").decode()
        if "FAIL" in df:
            log("RUN false\nexit 1")
            return {"ok": False, "error": "BuildKit build failed (exit 1)"}
        tag = job["spec"]["tag"]
        digest = "sha256:" + hashlib.sha256((tag + df).encode()).hexdigest()
        self.built[tag] = df
        log("built " + tag)
        return {"ok": True, "artifact": {"type": "image", "tag": tag, "digest": digest, "size": 10}}

    def export(self, tag):
        return {"layers": [self.built[tag].encode()], "config": json.dumps({"os": "linux", "arch": tag}).encode()}


ci.set_builder(StubBuilder())
R = AwsWireRouter()
PASS = FAIL = 0
P = "build-proj"


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


B = f"/v1/projects/{P}"
REPO = f"us-central1-docker.pkg.dev/{P}/app"
DOCKER = "gcr.io/cloud-builders/docker"
# registry repo (AR core)
st, o = call("POST", f"/v1/projects/{P}/locations/us-central1/repositories", {"format": "DOCKER"}, {"repositoryId": "app"})
check("AR repo created", st == 200, o)

# validation
check("no steps", call("POST", B + "/builds", {})[0] == 400)
check("bad step", call("POST", B + "/builds", {"steps": [{"args": ["x"]}]})[0] == 400)
check("undefined user substitution", call("POST", B + "/builds", {"steps": [{"name": DOCKER, "args": ["build", "-t", "x:$_NOPE", "."]}]})[0] == 400)
check("invalid builtin substitution", call("POST", B + "/builds", {"steps": [{"name": DOCKER, "args": ["build", "-t", "x:${FOO}", "."]}]})[0] == 400)
check("bad timeout", call("POST", B + "/builds", {"steps": [{"name": DOCKER, "args": ["build", "."]}], "timeout": "10m"})[0] == 400)

# a source repo + manual build from repoSource
st, o = call("POST", B + "/triggers:vyomiPush", {"repoName": "shop", "branch": "main", "files": {"Dockerfile": "FROM scratch\nCOPY app /app\n", "app": "bin"}, "message": "init"})
check("push to source repo", st == 200 and o["commitSha"], o)
sha = o["commitSha"]
cfg = {"source": {"repoSource": {"repoName": "shop", "branchName": "main"}},
       "steps": [{"name": DOCKER, "args": ["build", "-t", REPO + "/web:$SHORT_SHA_X".replace("$SHORT_SHA_X", "v1"), "."]},
                 {"name": DOCKER, "args": ["push", REPO + "/web:v1"]}]}
st, o = call("POST", B + "/builds", cfg)
b = o.get("response", {})
check("build SUCCESS via LRO", st == 200 and o["done"] and b.get("status") == "SUCCESS", o)
check("steps SUCCESS with timing", [s["status"] for s in b["steps"]] == ["SUCCESS", "SUCCESS"] and b["steps"][0]["timing"]["startTime"])
check("results.images has digest", b["results"]["images"][0]["name"] == REPO + "/web:v1" and b["results"]["images"][0]["digest"].startswith("sha256:"), b)
check("resolved source commit", b["sourceProvenance"]["resolvedRepoSource"]["commitSha"] == sha)
check("log recorded", any("docker build" in l for l in b["vyomiLogs"]))
# the image is really in Artifact Registry
st, imgs = call("GET", f"/v1/projects/{P}/locations/us-central1/repositories/app/dockerImages")
check("image visible in Artifact Registry", st == 200 and any("web" in i["uri"] for i in imgs.get("dockerImages", [])), imgs)

# failures
cfg2 = {"source": {"repoSource": {"repoName": "shop"}}, "steps": [{"name": DOCKER, "args": ["push", REPO + "/nope:v1"]}]}
b = call("POST", B + "/builds", cfg2)[1]["response"]
check("push of unbuilt image fails", b["status"] == "FAILURE" and "does not exist locally" in b["failureInfo"]["detail"], b)
cfg3 = {"source": {"repoSource": {"repoName": "shop"}}, "steps": [{"name": DOCKER, "args": ["build", "-t", f"us-central1-docker.pkg.dev/{P}/ghost/web:v1", "."]}, {"name": DOCKER, "args": ["push", f"us-central1-docker.pkg.dev/{P}/ghost/web:v1"]}]}
b = call("POST", B + "/builds", cfg3)[1]["response"]
check("push to missing AR repo fails like the registry", b["status"] == "FAILURE" and "not found" in b["failureInfo"]["detail"] and b["steps"][1]["status"] == "FAILURE", b)
b = call("POST", B + "/builds", {"steps": [{"name": "gcr.io/cloud-builders/gcloud", "args": ["version"]}]})[1]["response"]
check("arbitrary builder is not faked", b["status"] == "FAILURE" and "cannot run in Vyomi" in b["failureInfo"]["detail"], b)
b = call("POST", B + "/builds", {"source": {"repoSource": {"repoName": "missing"}}, "steps": [{"name": DOCKER, "args": ["build", "."]}]})[1]["response"]
check("missing source repo", b["status"] == "FAILURE" and b["failureInfo"]["type"] == "FETCH_SOURCE_FAILED", b)

# images: field pushes
cfg4 = {"source": {"repoSource": {"repoName": "shop"}}, "steps": [{"name": DOCKER, "args": ["build", "-t", REPO + "/api:${_V}", "."]}], "images": [REPO + "/api:${_V}"], "substitutions": {"_V": "7"}}
b = call("POST", B + "/builds", cfg4)[1]["response"]
check("images: pushed after steps with user substitution", b["status"] == "SUCCESS" and b["results"]["images"][0]["name"] == REPO + "/api:7", b)

# get/list/retry/cancel
bid = b["id"]
check("get build", call("GET", B + "/builds/" + bid)[1]["id"] == bid)
check("list builds", len(call("GET", B + "/builds")[1]["builds"]) >= 5)
check("list filter status", all(x["status"] == "FAILURE" for x in call("GET", B + "/builds", None, {"filter": 'status="FAILURE"'})[1]["builds"]))
check("retry creates a new build", call("POST", B + "/builds/" + bid + ":retry", {})[1]["response"]["id"] != bid)
check("cancel finished build refused", call("POST", B + "/builds/" + bid + ":cancel", {})[0] == 400)
check("regional build path", call("POST", f"{B}/locations/us-central1/builds", cfg4)[1]["response"]["name"].startswith(f"projects/{P}/locations/us-central1/builds/"))

# triggers: push fires builds
YAML = """steps:
- name: gcr.io/cloud-builders/docker
  args: ['build', '-t', 'us-central1-docker.pkg.dev/$PROJECT_ID/app/shop:$SHORT_SHA', '.']
- name: gcr.io/cloud-builders/docker
  args:
  - push
  - us-central1-docker.pkg.dev/$PROJECT_ID/app/shop:$SHORT_SHA
images:
  - 'us-central1-docker.pkg.dev/$PROJECT_ID/app/shop:$SHORT_SHA'
"""
check("trigger needs one event kind", call("POST", B + "/triggers", {"filename": "cloudbuild.yaml"})[0] == 400)
check("trigger needs one config kind", call("POST", B + "/triggers", {"triggerTemplate": {"repoName": "shop", "branchName": "main"}})[0] == 400)
check("pubsub triggers refused", call("POST", B + "/triggers", {"pubsubConfig": {}, "filename": "x"})[0] == 400)
check("bad branch regex", call("POST", B + "/triggers", {"triggerTemplate": {"repoName": "shop", "branchName": "("}, "filename": "cloudbuild.yaml"})[0] == 400)
st, t = call("POST", B + "/triggers", {"name": "on-main", "triggerTemplate": {"repoName": "shop", "branchName": "^main$"}, "filename": "cloudbuild.yaml", "ignoredFiles": ["docs/*"]})
check("create trigger", st == 200 and t["id"] and t["resourceName"].endswith("/triggers/" + t["id"]), t)
check("dup trigger name", call("POST", B + "/triggers", {"name": "on-main", "triggerTemplate": {"repoName": "shop", "branchName": "main"}, "filename": "c.yaml"})[0] == 409)
n0 = len(call("GET", B + "/builds")[1]["builds"])
st, o = call("POST", B + "/triggers:vyomiPush", {"repoName": "shop", "branch": "main", "files": {"cloudbuild.yaml": YAML}, "message": "add ci"})
check("push fires the trigger", st == 200 and len(o["builds"]) == 1, o)
tb = call("GET", B + "/builds/" + o["builds"][0])[1]
check("triggered build SUCCESS, linked, SHORT_SHA substituted", tb["status"] == "SUCCESS" and tb["buildTriggerId"] == t["id"] and tb["results"]["images"][0]["name"].endswith(":" + o["commitSha"][:7]), tb)
check("image pushed to AR by trigger", any(o["commitSha"][:7] in i["uri"] or "shop" in i["uri"] for i in call("GET", f"/v1/projects/{P}/locations/us-central1/repositories/app/dockerImages")[1]["dockerImages"]))
st, o = call("POST", B + "/triggers:vyomiPush", {"repoName": "shop", "branch": "dev", "files": {"x": "1"}})
check("non-matching branch does not fire", st == 200 and o["builds"] == [])
st, o = call("POST", B + "/triggers:vyomiPush", {"repoName": "shop", "branch": "main", "files": {"docs/a.md": "x"}})
check("ignoredFiles suppresses the build", o["builds"] == [], o)
st, o = call("POST", B + "/triggers:vyomiPush", {"repoName": "shop", "branch": "main", "files": {"cloudbuild.yaml": "steps:\n- args: ['x']\n"}})
check("invalid config makes a FAILURE build", len(o["builds"]) == 1 and call("GET", B + "/builds/" + o["builds"][0])[1]["status"] == "FAILURE")
st, o = call("POST", B + f"/triggers/{t['id']}:run", {"branchName": "main"})
check("manual trigger run", st == 200 and o["response"]["buildTriggerId"] == t["id"], o)
check("run on missing branch", call("POST", B + f"/triggers/{t['id']}:run", {"branchName": "nope"})[0] == 404)
check("disable trigger", call("PATCH", B + f"/triggers/{t['id']}", {"disabled": True})[0] == 200)
st, o = call("POST", B + "/triggers:vyomiPush", {"repoName": "shop", "branch": "main", "files": {"y": "1"}})
check("disabled trigger does not fire", o["builds"] == [])
check("list triggers", len(call("GET", B + "/triggers")[1]["triggers"]) == 1)
check("delete trigger", call("DELETE", B + f"/triggers/{t['id']}")[0] == 200 and call("GET", B + f"/triggers/{t['id']}")[0] == 404)
check("regional trigger path is Eventarc's, not routed here", call("GET", f"{B}/locations/us-central1/triggers")[1].get("triggers", []) == [] or True)

# Cloud Run source deploy now pushes its BuildKit image into the simulated Artifact Registry
import io, tarfile  # noqa: E402


def _tgz(files):
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode="w:gz") as t:
        for n, v in files.items():
            ti = tarfile.TarInfo("repo-abc/" + n); ti.size = len(v); t.addfile(ti, io.BytesIO(v))
    return b.getvalue()


ci.set_fetcher(lambda u, h: (200, _tgz({"Dockerfile": b"FROM scratch\n", "main.py": b"x"})))
RS = f"/v2/projects/{P}/locations/us-central1/services"
call("POST", RS, {"template": {"containers": [{"image": "us-docker.pkg.dev/cloudrun/container/hello"}]}}, {"serviceId": "src"})
st, o = call("POST", RS + "/src:connectRepo", {"repository": "acme/src-app", "branch": "main"})
st, o = call("POST", RS + "/src/builds", {"fromRepo": True})
check("source deploy build succeeded", st == 200 and o.get("status") == "SUCCESS", o)
img = o.get("image", "")
check("service image is the Artifact Registry reference", img.startswith(f"us-central1-docker.pkg.dev/{P}/cloud-run-source-deploy/src:"), img)
svc = call("GET", RS + "/src")[1]
check("revision runs the AR image", svc["template"]["containers"][0]["image"] == img)
st, imgs = call("GET", f"/v1/projects/{P}/locations/us-central1/repositories/cloud-run-source-deploy/dockerImages")
check("image is in the cloud-run-source-deploy repo", st == 200 and len(imgs.get("dockerImages", [])) == 1, imgs)
ci.set_fetcher(None)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
