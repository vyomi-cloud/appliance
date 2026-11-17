"""Static checks for the Mesh Codespace reference-app demo (vyomi-agent-demo). Run: PYTHONPATH=. python3 tests/mesh/test_mesh_example_demo.py
Set DEMO_PIP_DRY_RUN=1 to also check the example requirements resolve (needs network; pip --dry-run)."""
import json, os, re, shutil, subprocess, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CS = os.path.join(ROOT, "codespace"); MESH = os.path.join(CS, ".devcontainer", "mesh"); EX = os.path.join(ROOT, "examples", "enterprise-facilities-agent")
FAILS = []
def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else "")); (None if ok else FAILS.append(name))

demo = os.path.join(MESH, "vyomi-agent-demo")
check("demo script exists + executable", os.path.isfile(demo) and os.access(demo, os.X_OK))
for f in (demo, os.path.join(MESH, "boot-mesh.sh"), os.path.join(MESH, "vyomi-gate"), os.path.join(CS, "publish.sh")):
    r = subprocess.run(["bash", "-n", f], capture_output=True, text=True); check(f"bash -n {os.path.basename(f)}", r.returncode == 0, r.stderr)
sc = shutil.which("shellcheck")
if sc:
    r = subprocess.run([sc, "-S", "error", demo], capture_output=True, text=True); check("shellcheck (errors) vyomi-agent-demo", r.returncode == 0, r.stdout)
else:
    print("SKIP shellcheck not installed")
check("example run_e2e.py + requirements.txt exist", os.path.isfile(os.path.join(EX, "run_e2e.py")) and os.path.isfile(os.path.join(EX, "requirements.txt")))
check("MESH-DEMO.md exists", os.path.isfile(os.path.join(CS, "MESH-DEMO.md")))
dc = open(os.path.join(MESH, "devcontainer.json")).read()
check("devcontainer unchanged: no forwardPorts / appPort", "forwardPorts" not in dc and "appPort" not in dc)
check("Dockerfile installs python3-venv", "python3-venv" in open(os.path.join(MESH, "Dockerfile")).read())
pub = open(os.path.join(CS, "publish.sh")).read()
check("publish.sh copies example + MESH-DEMO.md + chmods demo", all(s in pub for s in ("examples/enterprise-facilities-agent", "MESH-DEMO.md", "vyomi-agent-demo")))
check("boot-mesh links the helper", "vyomi-agent-demo" in open(os.path.join(MESH, "boot-mesh.sh")).read())
check("compose gives the simulator ambient dummy AWS creds (Lambda callbacks)", "AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:-test}" in open(os.path.join(MESH, "docker-compose.mesh.yml")).read())
# gate verb is validated and shows nothing else
g = open(os.path.join(MESH, "vyomi-gate")).read()
check("gate sim-ip verb rejects an argument", re.search(r"sim-ip\).*?\[ -z \"\$arg\" \] \|\| deny", g, re.S) is not None)
# every path the doc names exists
doc = open(os.path.join(CS, "MESH-DEMO.md")).read()
check("doc paths exist", all(os.path.exists(os.path.join(ROOT, p)) for p in re.findall(r"`(examples/[A-Za-z0-9_./-]+?)/?`", doc) if "results" not in p))
# simulated publish: copy lands a runnable layout and the script finds the example from there
with tempfile.TemporaryDirectory() as d:
    r = subprocess.run(["bash", os.path.join(CS, "publish.sh"), d], capture_output=True, text=True)
    check("publish.sh into a scratch dir", r.returncode == 0, r.stderr[-300:])
    pd = os.path.join(d, ".devcontainer", "mesh", "vyomi-agent-demo")
    check("published layout complete", all(os.path.exists(os.path.join(d, p)) for p in ("examples/enterprise-facilities-agent/run_e2e.py", "MESH-DEMO.md", ".devcontainer/mesh/vyomi-agent-demo")) and os.access(pd, os.X_OK))
    r = subprocess.run(["bash", pd, "--endpoint", "http://127.0.0.1:9", "--only", "99"], capture_output=True, text=True, env=dict(os.environ, VYOMI_DEMO_VENV=os.path.join(d, "nonexistent-venv"), PATH="/nonexistent:/usr/bin:/bin"))
    check("script locates example from the published layout", "example sources not found" not in r.stderr, r.stderr[-200:])
if os.environ.get("DEMO_PIP_DRY_RUN") == "1":
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run", "-q", "-r", os.path.join(EX, "requirements.txt")], capture_output=True, text=True)
    check("requirements resolve (pip --dry-run)", r.returncode == 0, r.stderr[-300:])
print("FAILED: %s" % FAILS if FAILS else "ALL PASS"); sys.exit(1 if FAILS else 0)
