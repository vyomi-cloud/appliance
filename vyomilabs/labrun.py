"""Runs the hands-on lab blocks exactly as a learner would: save each file, run each command, check the expected output.
Starts a clean in-process simulator (test LLM stub). Usage:  python -m vyomilabs.labrun aws 10 7
A chapter is only published as verified when this passes."""
import os
import subprocess
import sys
import tempfile

from . import ROOT, ensure_reference_on_path


def main(argv=None):
    argv = argv or sys.argv[1:]
    endpoint_arg = None
    if "--endpoint" in argv:
        i = argv.index("--endpoint"); endpoint_arg = argv[i + 1]; del argv[i:i + 2]
    cloud, layers = argv[0], [int(x) for x in argv[1:]]
    ensure_reference_on_path()
    for k, v in (("AWS_ACCESS_KEY_ID", "test"), ("AWS_SECRET_ACCESS_KEY", "test"), ("AWS_DEFAULT_REGION", "us-east-1"), ("CLOUDLEARN_TIER_ENFORCE", "0")):
        os.environ.setdefault(k, v)
    sys.path.insert(0, os.path.join(ROOT, "tools", "llm_stub"))
    import stub_llm_server
    os.environ.setdefault("VYOMI_LLM_ENDPOINT", stub_llm_server.start())
    from facilities.server import start_in_process
    endpoint = endpoint_arg or start_in_process()
    import importlib
    lab = importlib.import_module(f"vyomilabs.content.labs_{cloud}").LAB
    work = tempfile.mkdtemp(prefix="vy-labrun-")
    env = dict(os.environ, AWS_ENDPOINT_URL=endpoint, PYTHONPATH=work)
    bad = 0
    for lid in layers:
        print(f"== chapter {lid}")
        for blk in lab[lid]:
            with open(os.path.join(work, blk["file"]), "w") as f:
                f.write(blk["code"])
            if not blk["run"]:
                print(f"  saved  {blk['file']}")
                continue
            if blk.get("needs_runtime") and not endpoint_arg:
                print(f"  BLOCKED  {blk['run']}  (needs real function execution: run with --endpoint <appliance or Mesh>)")
                continue
            p = subprocess.run([sys.executable] + blk["run"].split()[1:], cwd=work, env=env, capture_output=True, text=True, timeout=180)
            ok = p.returncode == 0 and (not blk["expect"] or blk["expect"] in p.stdout)
            bad += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {blk['run']}  -> {(p.stdout.strip().splitlines() or [''])[-1][:100]}")
            if not ok:
                print("   ", (p.stderr or p.stdout)[-600:])
    print("ALL PASS" if not bad else f"{bad} FAILED")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
