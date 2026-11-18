"""Run all 13 Azure probes (each starts its own fresh in-process appliance) and write results/azure-probe.json.
   python run_probe.py [--jobs N] [NN ...]     exit 0 only if every component is PASS."""
import glob, json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))


def run(path):
    t = time.time()
    try:
        p = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=900, env=dict(os.environ, W="1500"))
        for line in reversed(p.stdout.splitlines()):
            if line.startswith("RESULT "):
                r = json.loads(line[7:]); r["seconds"] = round(time.time() - t, 1); return r
        return {"component": os.path.basename(path), "status": "FAIL", "steps": [], "error": "no RESULT line: " + (p.stderr or p.stdout)[-400:]}
    except subprocess.TimeoutExpired:
        return {"component": os.path.basename(path), "status": "FAIL", "steps": [], "error": "timeout 900s"}


def main():
    args = sys.argv[1:]
    jobs = 4
    if "--jobs" in args:
        i = args.index("--jobs"); jobs = int(args[i + 1]); del args[i:i + 2]
    files = sorted(glob.glob(os.path.join(HERE, "probe_*.py")))
    if args:
        files = [f for f in files if os.path.basename(f).split("_")[1] in args]
    with ThreadPoolExecutor(jobs) as ex:
        res = list(ex.map(run, files))
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    out = {"cloud": "azure", "generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "appliance server.py in-process, CLOUDLEARN_TIER_ENFORCE=0, no model",
           "summary": {r.get("name", r["component"]): r["status"] for r in res}, "components": res}
    json.dump(out, open(os.path.join(HERE, "results", "azure-probe.json"), "w"), indent=1)
    for r in res:
        n = {s: sum(1 for x in r["steps"] if x["status"] == s) for s in ("PASS", "BLOCKED", "FAIL")}
        print(f"{r.get('component')!s:>3} {r.get('name', ''):14} {r['status']:8} {n}")
    sys.exit(0 if all(r["status"] == "PASS" for r in res) else 1)


if __name__ == "__main__":
    main()
