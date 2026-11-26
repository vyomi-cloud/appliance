"""Runs the hands-on lab blocks exactly as a learner would: save each file, run each command, check the expected output.
Starts a clean in-process simulator (test LLM stub). Usage:  python -m vyomilabs.labrun aws 10 7
A chapter is only published as verified when this passes."""
import os
import subprocess
import sys
import tempfile



def main(argv=None):
    argv = argv or sys.argv[1:]
    endpoint_arg = None
    if "--endpoint" in argv:
        i = argv.index("--endpoint"); endpoint_arg = argv[i + 1]; del argv[i:i + 2]
    skip = set()
    if "--skip" in argv:       # comma-separated block files to save but not run (e.g. blocks a given endpoint cannot execute)
        i = argv.index("--skip"); skip = set(argv[i + 1].split(",")); del argv[i:i + 2]
    no_prereqs = "--no-prereqs" in argv     # run exactly the chapters named (the old behaviour)
    argv = [a for a in argv if a != "--no-prereqs"]
    cloud, layers = argv[0], [int(x) for x in argv[1:]]
    from vyomilabs import prereqs
    plan, seen = [], set()      # a chapter's prerequisites (resources it consumes, files it imports) are deployed first, once, like the Deploy button does
    for lid in layers:
        for need in ([] if no_prereqs else prereqs.requires(cloud, lid)) + [lid]:
            if need not in seen:
                seen.add(need)
                plan.append((need, need != lid))
    import importlib
    endpoint, env = importlib.import_module(f"vyomilabs.labenv_{cloud}").start(endpoint_arg)
    lab = importlib.import_module(f"vyomilabs.content.labs_{cloud}").LAB
    work = tempfile.mkdtemp(prefix="vy-labrun-")
    env = dict(env, PYTHONPATH=work)
    bad = 0
    for lid, is_prereq in plan:
        print(f"== chapter {lid}" + (" (prerequisite)" if is_prereq else ""))
        for blk in lab[lid]:
            with open(os.path.join(work, blk["file"]), "w") as f:
                f.write(blk["code"])
            if not blk["run"] or blk["file"] in skip:
                print(f"  saved  {blk['file']}")
                continue
            if blk.get("needs_appliance") and not endpoint_arg:
                print(f"  BLOCKED  {blk['run']}  (needs the full appliance for IAM Enforce / audit: run with --endpoint <appliance or Mesh>)")
                continue
            if blk.get("needs_runtime") and not endpoint_arg and os.environ.get("VYOMILABS_HAS_RUNTIME") != "1":
                print(f"  BLOCKED  {blk['run']}  (needs real function execution: run with --endpoint <appliance or Mesh>)")
                continue
            try:
                p = subprocess.run([sys.executable] + blk["run"].split()[1:], cwd=work, env=env, capture_output=True, text=True,
                                   timeout=int(os.environ.get("VYOMILABS_TIMEOUT", "180")))
            except subprocess.TimeoutExpired:
                bad += 1
                print(f"  FAIL  {blk['run']}  -> timed out")
                continue
            ok = p.returncode == 0 and (not blk["expect"] or blk["expect"] in p.stdout)
            bad += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {blk['run']}  -> {(p.stdout.strip().splitlines() or [''])[-1][:100]}")
            if not ok:
                print("   ", (p.stderr or p.stdout)[-600:])
    print("ALL PASS" if not bad else f"{bad} FAILED")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
