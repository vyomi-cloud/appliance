"""Run every GCP reference-arch probe (one process each = a fresh in-process simulator and state), write results/gcp-probe.json.
Usage: python run_probe.py [NN ...]   Component status = FAIL if any step FAILed, else BLOCKED if any step was BLOCKED, else PASS.
Set VYOMI_ENDPOINT to probe an already-running simulator instead of the in-process one."""
import glob, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NAMES = {"01": "Access", "02": "Channels", "03": "Runtime", "04": "Gateway", "05": "Approval", "05b": "Approval on real emulators", "06": "Knowledge", "07": "Tools",
         "08": "Observability", "09": "Memory", "10": "Models", "11": "Response", "12": "Pipeline", "13": "Governance"}
want = sys.argv[1:]
out = {"cloud": "gcp", "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "components": []}
for path in sorted(glob.glob(os.path.join(HERE, "probe_*.py"))):
    nn = os.path.basename(path).split("_")[1]
    if want and nn not in want:
        continue
    steps_file = tempfile.mktemp(suffix=".json")
    env = dict(os.environ, PROBE_STEPS_OUT=steps_file, PYTHONPATH=REPO, PYTHONUNBUFFERED="1")
    t0 = time.time()
    p = subprocess.run([sys.executable, path], cwd=HERE, env=env, capture_output=True, text=True, timeout=900)
    steps = json.load(open(steps_file)) if os.path.exists(steps_file) else [{"status": "FAIL", "step": "probe crashed", "detail": p.stderr[-400:]}]
    status = "FAIL" if any(x["status"] == "FAIL" for x in steps) else "BLOCKED" if any(x["status"] == "BLOCKED" for x in steps) else "PASS"
    out["components"].append({"id": nn, "name": NAMES.get(nn, nn), "status": status, "exit_code": p.returncode, "seconds": round(time.time() - t0, 1), "steps": steps})
    print(f"{nn} {NAMES.get(nn, ''):28s} {status:8s} ({sum(x['status']=='PASS' for x in steps)}/{len(steps)} steps pass)")
os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
json.dump(out, open(os.path.join(HERE, "results", "gcp-probe.json"), "w"), indent=1)
sys.exit(1 if any(c["status"] == "FAIL" for c in out["components"]) else 0)
