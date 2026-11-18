#!/usr/bin/env python3
"""End-to-end run of the Facilities agent reference application against a Vyomi simulator, through the real cloud SDK (boto3 for AWS,
the google-cloud-* / google-genai / vertexai libraries for GCP).

  python run_e2e.py                      # AWS: starts the simulator in-process (needs the repo checkout)
  python run_e2e.py --cloud gcp          # GCP: same 13 components on the Google SDKs (see README-GCP.md)
  python run_e2e.py --endpoint http://localhost:8099
  python run_e2e.py --only 5,6           # run a subset of components (dependencies not re-run: use for debugging)

Writes results/e2e-result.json and results/report.html (GCP: results/gcp-e2e-result.json and results/gcp-report.html). Exit code 0 only when all 13 components PASS.
Statuses: PASS | BLOCKED (the simulator lacks a capability another lane is building; named) | FAIL (the app or the simulator is wrong)."""
import argparse, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from facilities.runtime import Ctx, PASS, BLOCKED, FAIL


def plan(cloud="aws"):
    if cloud == "gcp":
        from facilities.gcp.plan import plan as gcp_plan
        return gcp_plan()
    from facilities.components import (c01_access, c02_channels, c03_runtime, c04_gateway, c05_approval, c06_knowledge, c07_tools,
                                       c08_observability, c09_memory, c10_models, c11_response, c12_pipeline, c13_governance)
    # dependency order; the number is the architecture component the step belongs to
    return [(1, c01_access.sign_in), (2, c02_channels.run), (12, c12_pipeline.run), (6, c06_knowledge.run), (7, c07_tools.run),
            (1, c01_access.edge), (4, c04_gateway.run), (5, c05_approval.setup), (3, c03_runtime.run), (9, c09_memory.run),
            (5, c05_approval.run), (10, c10_models.run), (11, c11_response.run), (8, c08_observability.run), (13, c13_governance.run)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", help="Vyomi simulator URL (default: start one in-process)")
    ap.add_argument("--cloud", choices=["aws", "gcp"], default="aws", help="which cloud's SDK the 13 components use (default aws)")
    ap.add_argument("--region", default=None, help="default us-east-1 (aws) / us-central1 (gcp)")
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    ap.add_argument("--only", help="comma list of component numbers")
    ap.add_argument("--start-emulators", action="store_true", help="gcp dev helper: start the real Pub/Sub + Firestore emulators in Docker (local image only) and set "
                    "PUBSUB_EMULATOR_HOST / FIRESTORE_EMULATOR_HOST; stands in for VYOMI_GCP_REAL_BACKENDS=1 until the simulator does it")
    ap.add_argument("--llm-stub", action="store_true", help="start the deterministic TEST STUB llm (tools/llm_stub) and point the simulator at it "
                    "(VYOMI_LLM_ENDPOINT). Model-dependent PASSes are then STUB-BACKED, not a real model.")
    a = ap.parse_args()
    if a.llm_stub:
        sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "llm_stub"))
        import stub_llm_server
        os.environ["VYOMI_LLM_ENDPOINT"] = stub_llm_server.start()
        print(f"[llm-stub] VYOMI_LLM_ENDPOINT={os.environ['VYOMI_LLM_ENDPOINT']}  (deterministic test stub, NOT a real model)", flush=True)
    emu = None
    if a.start_emulators:
        from facilities.gcp.emulators import Emulators
        from facilities.gcp.runtime import PROJECT
        emu = Emulators(PROJECT).start()
        print(f"[emulators] pubsub={os.environ['PUBSUB_EMULATOR_HOST']} firestore={os.environ['FIRESTORE_EMULATOR_HOST']} (real Google emulators, own containers {emu.names})", flush=True)
    endpoint = a.endpoint
    if not endpoint:
        from facilities.server import start_in_process
        endpoint = start_in_process()
    only = {int(x) for x in a.only.split(",")} if a.only else None
    lines = []

    def out(s):
        print(s, flush=True); lines.append(s)
    if a.cloud == "gcp":
        from facilities.gcp.runtime import GcpCtx
        ctx = GcpCtx(endpoint, a.region or "us-central1", out)
    else:
        ctx = Ctx(endpoint, a.region or "us-east-1", out)
    COMPONENTS = ctx.COMPONENTS
    out(f"Facilities agent e2e ({a.cloud.upper()})   endpoint={endpoint}   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    out("=" * 100)
    seen = set()
    t0 = time.time()
    for comp, fn in plan(a.cloud):
        if only and comp not in only:
            continue
        if comp not in seen:
            out(f"\n[{comp:02d}] {COMPONENTS[comp]}"); seen.add(comp)
        ctx.current = comp
        try:
            fn(ctx)
        except Exception as e:     # a component crashed outside a step: that is a FAIL, never silently skipped
            ctx.subs.append(dict(component=comp, name=f"{fn.__module__.split('.')[-1]}.{fn.__name__} crashed", status=FAIL, detail=f"{type(e).__name__}: {e}", secs=0))
            out(f"    [FAIL   ] {fn.__module__}.{fn.__name__} crashed: {type(e).__name__}: {e}")
    res = ctx.state.get("result") or {}
    if res:
        out("\n" + "-" * 100 + "\nAgent transcript")
        out(f"  user      : {res.get('user')}\n  question  : {res.get('question')}\n  route     : {res.get('route')}  (routed by {'model' if res.get('llm_used') else 'keyword rules; no model reachable'})")
        for t in res.get("tools", []):
            out(f"  tool      : {t['tool']:<18} via {t['via']}")
        out(f"  answer    : {res.get('answer')}")
        for c in res.get("citations", []):
            out(f"  citation  : [{c['n']}] {c['source']}")
        if res.get("approval"):
            out(f"  approval  : {res['approval']['request_id']} -> work order {ctx.state.get('work_order_id', '(not created)')}")
    table = []
    out("\n" + "=" * 100 + "\nSUMMARY")
    out(f"{'#':>2}  {'component':<62} {'status':<8} steps")
    for c in COMPONENTS:
        if only and c not in only:
            continue
        subs = [s for s in ctx.subs if s["component"] == c]
        v = ctx.verdict(c)
        blocked = sorted({s["detail"].split(":")[0].replace("waiting for ", "") for s in subs if s["status"] == BLOCKED})
        table.append(dict(id=c, name=COMPONENTS[c], status=v, passed=sum(s["status"] == PASS for s in subs), total=len(subs), blocked_by=blocked,
                          steps=subs))
        out(f"{c:>2}  {COMPONENTS[c]:<62} {v:<8} {table[-1]['passed']}/{len(subs)}" + (f"   blocked by: {', '.join(blocked)}" if blocked else ""))
    tot = {k: sum(1 for t in table if t["status"] == k) for k in (PASS, BLOCKED, FAIL)}
    out(f"\n{tot[PASS]} PASS, {tot[BLOCKED]} BLOCKED, {tot[FAIL]} FAIL of {len(table)} components   ({time.time() - t0:.1f}s)")
    if a.llm_stub:
        out("NOTE: run with --llm-stub: components 10/11 (and agent routing/answers) were answered by the deterministic TEST STUB, not a real model: STUB-BACKED PASS.")
    os.makedirs(a.out, exist_ok=True)
    doc = dict(cloud=a.cloud, llm_stub=bool(a.llm_stub), notes=ctx.state.get("notes", []), endpoint=endpoint, when=time.strftime("%Y-%m-%dT%H:%M:%S"), totals=tot, components=table, transcript="\n".join(lines),
               agent={k: res.get(k) for k in ("question", "user", "route", "llm_used", "tools", "answer", "citations", "approval")}, work_order=ctx.state.get("work_order_id"))
    pre = "gcp-" if a.cloud == "gcp" else ""
    with open(os.path.join(a.out, pre + "e2e-result.json"), "w") as f:
        json.dump(doc, f, indent=2, default=str)
    from report import render
    with open(os.path.join(a.out, pre + "report.html"), "w") as f:
        f.write(render(doc))
    out(f"wrote {a.out}/{pre}e2e-result.json and {pre}report.html")
    if emu:
        emu.stop()
    sys.exit(0 if tot[PASS] == len(table) else 1)


if __name__ == "__main__":
    main()
