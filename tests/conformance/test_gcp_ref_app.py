#!/usr/bin/env python3
"""GCP reference application (examples/enterprise-facilities-agent --cloud gcp): component-level expectations that hold WITHOUT a model.
Runs the real Google SDK app against the in-process simulator and checks the PASS / BLOCKED / FAIL model itself:
  1. steps the simulator already supports must PASS (RAG corpus/import/retrieve, Model Armor sanitize, Cloud Armor, KMS envelope, agent gateway, functions deploy);
  2. every BLOCKED step names the lane or 'local model' that owes the capability (never an anonymous block);
  3. nothing is reported PASS for a step whose detail says it was blocked / fallback; the exit code is 0 only when all 13 PASS;
  4. with the real Pub/Sub + Firestore emulators (docker, local image only) and the DEV local-function mode, components 5 and 7 PASS completely
     (the approval loop and the tool functions are correct); that run is never a conformance result;
  5. the AWS app still imports (cloud-neutral refactor) and its step list is unchanged in shape.
Run: PYTHONPATH=. python3 tests/conformance/test_gcp_ref_app.py        (needs the google-cloud-* libraries; prints SKIP when they are missing)"""
import json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(ROOT, "examples", "enterprise-facilities-agent")
sys.path.insert(0, APP)
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


try:
    import google.cloud.pubsub_v1, google.cloud.firestore, google.genai, vertexai, langgraph  # noqa: F401
except ImportError as e:
    print(f"SKIP: google SDKs not installed ({e})")
    sys.exit(0)


def run(args):
    out = tempfile.mkdtemp(prefix="gcp-ref-")
    p = subprocess.run([sys.executable, os.path.join(APP, "run_e2e.py"), "--cloud", "gcp", "--out", out] + args, capture_output=True, text=True, timeout=900,
                       env=dict(os.environ, VYOMI_REPO=ROOT))
    f = os.path.join(out, "gcp-e2e-result.json")
    return p, (json.load(open(f)) if os.path.exists(f) else None)


def steps(doc):
    return {(c["id"], s["name"]): s for c in doc["components"] for s in c["steps"]}


def docker_ok():
    try:
        return (subprocess.run(["docker", "image", "inspect", "gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators"], capture_output=True, timeout=20).returncode == 0)
    except Exception:
        return False


# 5. AWS app unchanged in shape
import importlib
for m in ("facilities.runtime", "facilities.agents", "facilities.components.c01_access", "facilities.components.c05_approval", "facilities.deploy"):
    importlib.import_module(m)
from facilities.runtime import Ctx, COMPONENTS as AWS_COMPONENTS
check("aws: harness modules import without boto3-at-import and keep 13 components", len(AWS_COMPONENTS) == 13 and Ctx.COMPONENTS is AWS_COMPONENTS)

# 1-3: honest run, no emulators needed
p, doc = run(["--start-emulators"] if docker_ok() else [])
check("gcp: e2e wrote its result json", doc is not None, (p.stdout[-400:] + p.stderr[-400:]) if doc is None else "")
if doc:
    S = steps(doc)
    for comp, frag in ((6, "retrieveContexts ranks the boiler SOP first"), (6, "carry source URIs"), (12, "create corpus"), (12, "import_rag_files from"), (12, "re-upload a revised SOP"),
                       (2, "prompt injection blocked"), (2, "benign question allowed"), (1, "cloud armor"), (13, "envelope-encrypt"), (4, "attach the MCP server"),
                       (4, "Cedar permit"), (7, "CreateFunction x5"), (10, "embedContent")):
        hit = [s for (c, n), s in S.items() if c == comp and frag in n]
        check(f"c{comp:02d} PASS: {frag}", bool(hit) and all(s["status"] == "PASS" for s in hit), str([s["status"] + " " + s["detail"][:80] for s in hit]))
    blocked = [(k, s) for k, s in S.items() if s["status"] == "BLOCKED"]
    check("every BLOCKED step names its lane or 'local model'", all(s["detail"].startswith("waiting for ") for _, s in blocked), str([k for k, s in blocked if not s["detail"].startswith("waiting for ")]))
    check("model-dependent steps are BLOCKED(local model), never PASS, when no model is reachable",
          all(s["status"] == "BLOCKED" for (c, n), s in S.items() if c == 10 and n.endswith("generateContent (chat model)")))
    check("components are reported with the 13 GCP titles", [c["id"] for c in doc["components"]] == list(range(1, 14)))
    pass_all = all(c["status"] == "PASS" for c in doc["components"])
    check("exit code is 0 only when all 13 components PASS", (p.returncode == 0) == pass_all, f"exit {p.returncode}, all_pass={pass_all}")
    check("the run is not a dev run", not any("DEV RUN" in n for n in doc.get("notes", [])))

# 4: emulators + dev local functions: the approval loop and the tool functions are correct
if docker_ok():
    p2, doc2 = run(["--start-emulators", "--dev-local-functions"])
    check("gcp dev run (real emulators, local function handlers) wrote its result", doc2 is not None, p2.stdout[-300:] if doc2 is None else "")
    if doc2:
        check("dev run is flagged and exits non-zero", any("DEV RUN" in n for n in doc2.get("notes", [])) and p2.returncode != 0)
        for cid in (5, 7):
            c = [x for x in doc2["components"] if x["id"] == cid][0]
            check(f"c{cid:02d} PASS in the dev run ({c['passed']}/{c['total']})", c["status"] == "PASS" and c["passed"] == c["total"] and c["total"] >= 4, str([s for s in c["steps"] if s["status"] != "PASS"]))
        check("the agent ran the 3 sub-agents and created a work order after approval", bool(doc2.get("work_order")) and set(doc2["agent"]["route"]) == {"facilities", "maintenance", "analytics"})
else:
    print("SKIP: docker emulator image not present; emulator-backed checks not run")

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall checks passed")
sys.exit(1 if FAILS else 0)
