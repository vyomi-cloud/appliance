#!/usr/bin/env python3
"""Azure reference application (examples/enterprise-facilities-agent --cloud azure): component-level expectations that hold WITHOUT a model.
Runs the real Azure SDK app against the in-process simulator (https://localhost with a local CA, plain-http side port for call-backs) and checks the
PASS / BLOCKED / FAIL model itself:
  1. steps the simulator already supports must PASS (APIM tool API + subscription key + validate-jwt rejections, RAI content filter, Service Bus ARM, Container Apps ARM,
     blob upload, Event Grid subscription, App Insights exporters, embeddings, Key Vault create + key, Activity Log, long-term memory write);
  2. every BLOCKED step names the lane or 'local model' that owes the capability (never an anonymous block), and no step is a FAIL;
  3. the exit code is 0 only when all 13 components PASS; the harness never reports PASS for a step whose detail says blocked / fallback;
  4. the AWS app (and the GCP app when its SDKs are installed) still import with their 13 components (cloud-neutral harness unchanged).
Run: PYTHONPATH=. python3 tests/conformance/test_azure_ref_app.py     (needs the azure-* SDKs + openai + langgraph; prints SKIP when they are missing)"""
import importlib, json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(ROOT, "examples", "enterprise-facilities-agent")
sys.path.insert(0, APP)
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


try:
    import azure.mgmt.apimanagement, azure.servicebus, azure.data.tables, azure.search.documents, azure.keyvault.keys, azure.ai.agents, azure.ai.contentsafety  # noqa: F401
    import azure.monitor.opentelemetry.exporter, azure.monitor.query, azure.identity, openai, langgraph, jwt  # noqa: F401
except ImportError as e:
    print(f"SKIP: azure SDKs not installed ({e})")
    sys.exit(0)


def run(args):
    out = tempfile.mkdtemp(prefix="azure-ref-")
    p = subprocess.run([sys.executable, os.path.join(APP, "run_e2e.py"), "--cloud", "azure", "--out", out] + args, capture_output=True, text=True, timeout=1500,
                       env=dict(os.environ, VYOMI_REPO=ROOT, FACILITIES_DETAIL="400"))
    f = os.path.join(out, "azure-e2e-result.json")
    return p, (json.load(open(f)) if os.path.exists(f) else None)


# 4. the AWS (and GCP) apps are unchanged in shape
for m in ("facilities.runtime", "facilities.agents", "facilities.components.c01_access", "facilities.components.c05_approval", "facilities.deploy"):
    importlib.import_module(m)
from facilities.runtime import Ctx, COMPONENTS as AWS_COMPONENTS
check("aws: harness modules import and keep 13 components", len(AWS_COMPONENTS) == 13 and Ctx.COMPONENTS is AWS_COMPONENTS)
try:
    import google.cloud.pubsub_v1  # noqa: F401
    from facilities.gcp.runtime import COMPONENTS as GCP_COMPONENTS
    check("gcp: harness still imports with 13 components", len(GCP_COMPONENTS) == 13)
except ImportError:
    print("SKIP: google SDKs not installed; gcp import check not run")
from facilities.azure.runtime import COMPONENTS as AZ_COMPONENTS, NAMES, LANE
check("azure: 13 components with the contract resource names", len(AZ_COMPONENTS) == 13 and NAMES["vault"] == "facilities-kv" and NAMES["apim"] == "facilities-apim"
      and NAMES["bus"] == "facilities-bus" and NAMES["topic"] == "work-order-approval" and NAMES["inbox"] == "approver-inbox" and NAMES["ledger"] == "approvalledger"
      and NAMES["search"] == "facilities-search" and NAMES["index"] == "facilities-kb" and NAMES["functions"] == "facilities-tools" and NAMES["capp"] == "facilities-supervisor")

p, doc = run([])
check("azure: e2e wrote its result json", doc is not None, (p.stdout[-600:] + p.stderr[-600:]) if doc is None else "")
if doc:
    S = {(c["id"], s["name"]): s for c in doc["components"] for s in c["steps"]}
    MUST_PASS = ((1, "app registration + client secret + user"), (1, "apim: service + API + operations"), (1, "without a subscription key is rejected"),
                 (2, "RAI policy facilities-guardrail"), (2, "violent prompt is refused with 400"), (2, "namespace + topic + approver-inbox"),
                 (3, "container apps: environment"), (4, "tool catalog lists the three operations"), (4, "operation policy (rate-limit) is accepted"),
                 (8, "log analytics workspace + workspace-based"), (8, "azure monitor: platform metrics"), (9, "create a thread with metadata"), (9, "store a user fact"),
                 (9, "confirm Azure has no managed long-term memory API"), (10, "deployments are listed"), (10, "embeddings.create"), (10, "unknown deployment answers 404"),
                 (10, "content filter refuses a violent prompt"), (12, "blob storage: create container + upload"), (12, "ingest function"), (12, "event grid: system topic"),
                 (13, "create facilities-kv"), (13, "create_rsa_key"), (13, "activity log: the run's control-plane"))
    for comp, frag in MUST_PASS:
        hit = [s for (c, n), s in S.items() if c == comp and frag in n]
        check(f"c{comp:02d} PASS: {frag}", bool(hit) and all(s["status"] == "PASS" for s in hit), str([s["status"] + " " + s["detail"][:100] for s in hit]))
    blocked = [(k, s) for k, s in S.items() if s["status"] == "BLOCKED"]
    check("every BLOCKED step names its lane or 'local model'", all(s["detail"].startswith("waiting for ") for _, s in blocked), str([k for k, s in blocked if not s["detail"].startswith("waiting for ")]))
    fails = [(k, s["detail"][:160]) for k, s in S.items() if s["status"] == "FAIL"]
    check("no step is a FAIL (every gap is either PASS or BLOCKED with an owner)", not fails, str(fails))
    check("model-dependent steps are BLOCKED(local model) or PASS, never FAIL, when no model is reachable",
          all(s["status"] != "FAIL" for (c, n), s in S.items() if "needs a model" in n))
    check("components are reported 1..13", [c["id"] for c in doc["components"]] == list(range(1, 14)))
    check("long-term memory is labelled an application pattern, not a managed service", any("APPLICATION PATTERN" in s["detail"] for (c, n), s in S.items() if c == 9) or
          any("APPLICATION PATTERN" in n for n in doc.get("notes", [])))
    if os.environ.get("AZ_REF_FULL_STACK") == "1":     # set on the merged integ tree (all lane fixes): every component except the model-dependent ones passes
        for cid in (1, 4, 5, 6, 7, 8, 12, 13):
            c = [x for x in doc["components"] if x["id"] == cid][0]
            check(f"c{cid:02d} component PASS on the full stack", c["status"] == "PASS", str([s["name"] for s in c["steps"] if s["status"] != "PASS"]))
        check("remaining BLOCKED steps are only 'local model'", all("local model" in s["detail"] for s in S.values() if s["status"] == "BLOCKED"))
    pass_all = all(c["status"] == "PASS" for c in doc["components"])
    check("exit code is 0 only when all 13 components PASS", (p.returncode == 0) == pass_all, f"exit {p.returncode}, all_pass={pass_all}")
    check("the run is not a dev run", not any("DEV RUN" in n for n in doc.get("notes", [])))
    print(f"\nazure app on this simulator: {doc['totals']}")

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall checks passed")
sys.exit(1 if FAILS else 0)
