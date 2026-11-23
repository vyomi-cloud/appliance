"""Validate the checkers: the learner's checks must PASS on the reference solution (positive control) and must NOT pass on an empty
simulator (negative control). Starts a clean in-process simulator. The model is the deterministic test stub unless --endpoint-llm is set.

  python -m vyomilabs.validate --mode reference     # run the reference app, then every checker: all must PASS
  python -m vyomilabs.validate --mode empty         # nothing built: no checker may PASS
"""
import argparse
import os
import sys

from . import checks, ensure_reference_on_path, ROOT, workspace


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["reference", "empty"], default="reference")
    ap.add_argument("--layers", help="comma list of layer ids (default: every layer that has a checker)")
    ap.add_argument("--no-stub", action="store_true", help="do not start the test llm stub (use VYOMI_LLM_ENDPOINT)")
    a = ap.parse_args(argv)
    ensure_reference_on_path()
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    if not a.no_stub and not os.environ.get("VYOMI_LLM_ENDPOINT"):
        sys.path.insert(0, os.path.join(ROOT, "tools", "llm_stub"))
        import stub_llm_server
        os.environ["VYOMI_LLM_ENDPOINT"] = stub_llm_server.start()
        print(f"[stub] VYOMI_LLM_ENDPOINT={os.environ['VYOMI_LLM_ENDPOINT']} (deterministic test stub, NOT a real model)", flush=True)
    from facilities.server import start_in_process
    endpoint = start_in_process()
    print(f"[sim] in-process simulator at {endpoint}", flush=True)
    if a.mode == "reference":
        import run_e2e
        from facilities.runtime import Ctx, FAIL
        ctx = Ctx(endpoint, "us-east-1", lambda s: None)
        for comp, fn in run_e2e.plan("aws"):
            ctx.current = comp
            try:
                fn(ctx)
            except Exception as e:
                print(f"[ref] component {comp} crashed: {type(e).__name__}: {e}")
        bad = [r for r in ctx.subs if r["status"] == FAIL]
        print(f"[ref] reference app ran: {len(ctx.subs)} steps, {len(bad)} FAIL", flush=True)
    ids = [int(x) for x in a.layers.split(",")] if a.layers else checks.available()
    worst = 0
    print(f"\n{'layer':>5}  {'status':8} {'steps':>5}   (mode: {a.mode})")
    for lid in ids:
        res = checks.run(lid, endpoint, workspace=(workspace.SOLUTIONS if a.mode == "reference" else workspace.STARTER))
        print(f"{lid:>5}  {res['status']:8} {len(res['steps']):>5}")
        for st in res["steps"]:
            if st["status"] != "PASS":
                print(f"         [{st['status']}] {st['name']}  - {st['detail'][:150]}")
        if a.mode == "reference" and res["status"] != "PASS":
            worst = 1
        if a.mode == "empty" and res["status"] == "PASS":
            print(f"         !! layer {lid} PASSED on an empty simulator: the checker proves nothing")
            worst = 1
    return worst


if __name__ == "__main__":
    sys.exit(main())
