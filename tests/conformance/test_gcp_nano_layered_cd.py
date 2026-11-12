"""Cloud Build continuous deployment with NO container runtime (the Nano / offline-without-Docker builder).

The default ci builder is used on purpose (no stub, no BuildKit): the daemonless LayerBuilder builds real OCI layers for
Dockerfiles it can honestly build (FROM scratch / earlier stage / previously built tag; COPY ADD ENV WORKDIR EXPOSE CMD
ENTRYPOINT LABEL ARG USER), and FAILS - never fakes - for RUN or a base image whose layers cannot be pulled.
A push to the built-in git host fires the trigger -> docker build -> docker push (Artifact Registry) -> gcloud run deploy.

Run: PYTHONPATH=. python tests/conformance/test_gcp_nano_layered_cd.py"""
import gzip
import io
import json
import os
import sys
import tarfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import ci_core as ci  # noqa: E402
from core.aws_wire_router import AwsWireRouter  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False
ci.set_builder(None)                       # the Nano default: no container runtime
R = AwsWireRouter()
PASS = FAIL = 0
P, REG = "nano-cd", "us-central1"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:700] if detail and not ok else ''}")


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
    {"name": SDK, "entrypoint": "gcloud", "args": ["run", "deploy", "shop", "--image", IMG + ":$COMMIT_SHA", "--region", REG, "--quiet"]}]}
st, t = call("POST", B + "/triggers", {"name": "deploy-shop", "triggerTemplate": {"repoName": "shop", "branchName": "^main$"}, "build": cfg})
check("trigger created", st == 200, t)

DF = "FROM scratch\nARG VER=1\nENV APP_VER=$VER PORT=8080\nWORKDIR /srv\nCOPY app.txt ./\nCOPY static/ /srv/static/\nEXPOSE 8080\nLABEL org.opencontainers.image.title=shop\nCMD [\"/srv/app.txt\"]\n"
st, o = call("POST", B + "/triggers:vyomiPush", {"repoName": "shop", "branch": "main", "message": "v1",
                                                 "files": {"Dockerfile": DF, "app.txt": "hello v1", "static/a.css": "body{}", "static/b.js": "1"}})
check("push fired the trigger", st == 200 and len(o["builds"]) == 1, o)
sha1 = o["commitSha"]
b = call("GET", f"{B}/builds/{o['builds'][0]}")[1]
check("build SUCCEEDED on the layer builder, all 3 steps", b["status"] == "SUCCESS" and [s["status"] for s in b["steps"]] == ["SUCCESS"] * 3,
      b.get("failureInfo") or b.get("vyomiLogs"))
check("the build log names the layer builder + real layer count", any("Built vyomi-cb/" in l or "layer(s)" in l for l in b["vyomiLogs"]), b["vyomiLogs"])
st, svc = call("GET", f"/v2/projects/{P}/locations/{REG}/services/shop")
check("Cloud Run revision cut from the AR image", st == 200 and svc["template"]["containers"][0]["image"] == f"{IMG}:{sha1}", svc)
st, imgs = call("GET", f"{B}/locations/{REG}/repositories/cloud-run-source-deploy/dockerImages")
check("image is in Artifact Registry", len(imgs.get("dockerImages", [])) == 1, imgs)

# the image is real: layers contain the COPY'd files, config carries ENV/CMD/EXPOSE/WORKDIR
img = next(v for k, v in ci._layer_builder.images.items())
cfgj = json.loads(img["config"])
check("config: ENV/WORKDIR/CMD/EXPOSE/LABEL populated", cfgj["config"]["Env"] == ["APP_VER=1", "PORT=8080"] and cfgj["config"]["WorkingDir"] == "/srv"
      and cfgj["config"]["Cmd"] == ["/srv/app.txt"] and "8080/tcp" in cfgj["config"]["ExposedPorts"] and cfgj["config"]["Labels"]["org.opencontainers.image.title"] == "shop", cfgj)
check("2 layers (one per COPY) with matching diff_ids", len(img["layers"]) == 2 and len(cfgj["rootfs"]["diff_ids"]) == 2)
import hashlib  # noqa: E402
files = {}
for lb, diff in zip(img["layers"], cfgj["rootfs"]["diff_ids"]):
    raw = gzip.decompress(lb)
    check("diff_id is the sha256 of the uncompressed layer", diff == "sha256:" + hashlib.sha256(raw).hexdigest())
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        for m in tf.getmembers():
            if m.isfile():
                files[m.name] = tf.extractfile(m).read()
check("layer files at the right paths", files.get("srv/app.txt") == b"hello v1" and files.get("srv/static/a.css") == b"body{}" and files.get("srv/static/b.js") == b"1", sorted(files))

# changed source -> new image + new revision
st, o2 = call("POST", B + "/triggers:vyomiPush", {"repoName": "shop", "branch": "main", "message": "v2", "files": {"app.txt": "hello v2"}})
sha2 = o2["commitSha"]
st, svc2 = call("GET", f"/v2/projects/{P}/locations/{REG}/services/shop")
check("next push cuts a NEW revision", svc2["template"]["containers"][0]["image"] == f"{IMG}:{sha2}" and svc2["latestReadyRevision"] != svc["latestReadyRevision"], svc2)

# honest failures
def push_df(df, branch="main"):
    st, o = call("POST", B + "/triggers:vyomiPush", {"repoName": "shop", "branch": branch, "message": "x", "files": {"Dockerfile": df}})
    return call("GET", f"{B}/builds/{o['builds'][0]}")[1]


b = push_df("FROM scratch\nRUN echo hi\n")
check("RUN is refused (no container to run it in), service untouched", b["status"] == "FAILURE" and "RUN echo hi" in json.dumps(b["failureInfo"]) and "No container builder" in json.dumps(b["failureInfo"]), b.get("failureInfo"))
b = push_df("FROM python:3.12-slim\nCOPY app.txt /app.txt\n")
check("a base image that cannot be pulled is refused, not faked", b["status"] == "FAILURE" and "python:3.12-slim" in json.dumps(b["failureInfo"]) and "cannot be pulled" in json.dumps(b["failureInfo"]), b.get("failureInfo"))
st, svc3 = call("GET", f"/v2/projects/{P}/locations/{REG}/services/shop")
check("failed builds leave the service on its previous revision", svc3["template"]["containers"][0]["image"] == f"{IMG}:{sha2}", svc3)
b = push_df("FROM scratch AS build\nCOPY app.txt /out/app\nFROM scratch\nCOPY --from=build /out/app /app\nCMD [\"/app\"]\n")
check("multi-stage COPY --from builds", b["status"] == "SUCCESS", b.get("failureInfo"))
st, svc4 = call("GET", f"/v2/projects/{P}/locations/{REG}/services/shop")
check("and deploys", svc4["latestReadyRevision"] != svc2["latestReadyRevision"])
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
