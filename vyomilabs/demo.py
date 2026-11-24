"""One-command end-to-end demo: starts a clean in-process simulator (test llm stub), optionally pre-builds the reference app, then serves
the Vyomi Labs UI against it so every Check button does real work.

  python -m vyomilabs.demo --state reference   # layers 2 and 10 will PASS when checked
  python -m vyomilabs.demo --state empty       # nothing built: checks FAIL with hints
The model is a deterministic TEST STUB (not a real model); the demo says so in the log."""
import argparse
import os
import sys
import threading

from . import ROOT, ensure_reference_on_path, workspace


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", choices=["reference", "empty"], default="reference")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    ensure_reference_on_path()
    for k, v in (("AWS_ACCESS_KEY_ID", "test"), ("AWS_SECRET_ACCESS_KEY", "test"), ("AWS_DEFAULT_REGION", "us-east-1"),
                 ("CLOUDLEARN_TIER_ENFORCE", "0"), ("FACILITIES_READ_TIMEOUT", "120")):
        os.environ.setdefault(k, v)
    sys.path.insert(0, os.path.join(ROOT, "tools", "llm_stub"))
    import stub_llm_server
    os.environ.setdefault("VYOMI_LLM_ENDPOINT", stub_llm_server.start())
    from facilities.server import start_in_process
    endpoint = start_in_process()
    print(f"[demo] simulator {endpoint}; model = deterministic TEST STUB", flush=True)
    if a.state == "reference":
        import run_e2e
        from facilities.runtime import Ctx
        ctx = Ctx(endpoint, "us-east-1", lambda s: None)
        for comp, fn in run_e2e.plan("aws"):
            ctx.current = comp
            try:
                fn(ctx)
            except Exception as e:
                print(f"[demo] component {comp}: {type(e).__name__}: {e}")
        print(f"[demo] reference app built ({len(ctx.subs)} steps)", flush=True)
        os.environ["VYOMILABS_WORKSPACE"] = workspace.SOLUTIONS
    else:
        os.environ["VYOMILABS_WORKSPACE"] = workspace.init(os.path.join(os.environ.get("TMPDIR", "/tmp"), "vy-demo-workspace"))
    os.environ.setdefault("VYOMILABS_HOME", os.path.join(os.environ.get("TMPDIR", "/tmp"), "vy-demo-home"))
    import shutil
    shutil.rmtree(os.environ["VYOMILABS_HOME"], ignore_errors=True)
    import uvicorn
    from .server import create_app
    print(f"[demo] open http://127.0.0.1:{a.port}/", flush=True)
    uvicorn.run(create_app(endpoint), host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
