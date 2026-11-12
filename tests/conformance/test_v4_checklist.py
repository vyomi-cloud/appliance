"""tests/release/v4_checklist.py must FAIL when a check is broken (deliberate desyncs in temp trees) and never pass silently.
Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/conformance/test_v4_checklist.py"""
import importlib.util, json, os, shutil, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("v4c", REPO / "tests/release/v4_checklist.py")
v4c = importlib.util.module_from_spec(spec); spec.loader.exec_module(v4c)


def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print("  ok ", name)


def tree(files):
    root = Path(tempfile.mkdtemp(prefix="v4t-"))
    for rel, body in files.items():
        p = root / rel; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body if isinstance(body, str) else json.dumps(body))
    return root


KI = "# x\n\n## Azure\n\n| ID | Impact | What | Workaround | Where |\n|---|---|---|---|---|\n| AZ-1 | S2 | a | b | c |\n"
# 1 known issues
r = tree({v4c.KI_PATH: KI})
check("known issues: no S1 -> PASS", v4c.check_known_issues(r, "azure")["status"] == "PASS")
r = tree({v4c.KI_PATH: KI + "| AZ-2 | S1 | data loss | none | x |\n"})
c = v4c.check_known_issues(r, "azure")
check("known issues: open S1 for the cloud -> FAIL naming it", c["status"] == "FAIL" and "AZ-2" in c["reason"])
check("known issues: S1 of another cloud does not fail this cloud", v4c.check_known_issues(r, "aws")["status"] == "PASS")
r = tree({v4c.KI_PATH: KI + "\n## Resolved after the cut\n\n| ID | Impact | What |\n|---|---|---|\n| AZ-3 | S1 | old | | |\n"})
check("known issues: S1 in the Resolved section is closed", v4c.check_known_issues(r, "azure")["status"] == "PASS")
check("known issues: missing file -> FAIL", v4c.check_known_issues(tree({}), "azure")["status"] == "FAIL")
# 2 pyodide
r = tree({"wasm/pyodide-source.json": {"local": True}})
check("pyodide: local:true without the runtime -> FAIL", v4c.check_pyodide(r)["status"] == "FAIL")
r = tree({"wasm/pyodide-source.json": {"local": False}, "wasm/vendor/pyodide/pyodide.mjs": "x"})
check("pyodide: runtime vendored but local:false -> FAIL", v4c.check_pyodide(r)["status"] == "FAIL")
check("pyodide: consistent CDN -> PASS", v4c.check_pyodide(tree({"wasm/pyodide-source.json": {"local": False}}))["status"] == "PASS")
check("pyodide: file missing -> FAIL", v4c.check_pyodide(tree({}))["status"] == "FAIL")
# 3 *.bak
check("stray .bak -> FAIL", v4c.check_no_bak(tree({"wasm/a.html.bak": "x"}))["status"] == "FAIL")
check("no .bak -> PASS", v4c.check_no_bak(tree({"wasm/a.html": "x"}))["status"] == "PASS")
# 4 suites
S = lambda ss: tree({v4c.SUITES_PATH: {"suites": ss}})
ok = [{"id": "offline-a", "target": "offline", "cloud": "azure", "cmd": "x"}, {"id": "nano-a", "target": "nano", "cloud": "azure", "cmd": "x"},
      {"id": "offline-ui-azure-v4-bidirectional", "target": "offline", "cloud": "azure", "cmd": "x"}]
check("suites valid -> PASS", v4c.check_suites_valid(S(ok))["status"] == "PASS")
check("suite pending without a reason -> FAIL", v4c.check_suites_valid(S(ok + [{"id": "p", "pending": "", "cloud": "azure", "target": "nano"}]))["status"] == "FAIL")
check("duplicate suite id -> FAIL", v4c.check_suites_valid(S(ok + [dict(ok[0])]))["status"] == "FAIL")
check("suite without cmd and not pending -> FAIL", v4c.check_suites_valid(S(ok + [{"id": "n", "cloud": "azure", "target": "nano"}]))["status"] == "FAIL")
check("registered: both targets + bidi -> PASS", v4c.check_suites_registered(S(ok), "azure")["status"] == "PASS")
check("registered: no nano suite -> FAIL", v4c.check_suites_registered(S([ok[0], ok[2]]), "azure")["status"] == "FAIL")
check("registered: no bi-directional suite -> FAIL", v4c.check_suites_registered(S(ok[:2]), "azure")["status"] == "FAIL")
# 5 results
check("results: no dir -> SKIPPED (not PASS)", v4c.check_results(Path("."), "azure", None)["status"] == "SKIPPED")
d = Path(tempfile.mkdtemp())
(d / "results-offline-azure.json").write_text(json.dumps({"suites": [{"id": "a", "status": "pass"}]}))
check("results: nano missing -> FAIL", v4c.check_results(Path("."), "azure", d)["status"] == "FAIL")
(d / "results-nano-azure.json").write_text(json.dumps({"suites": [{"id": "b", "status": "fail"}]}))
c = v4c.check_results(Path("."), "azure", d)
check("results: a failed suite -> FAIL naming it", c["status"] == "FAIL" and "b" in c["reason"])
(d / "results-nano-azure.json").write_text(json.dumps({"suites": [{"id": "b", "status": "pass"}]}))
check("results: all green -> PASS", v4c.check_results(Path("."), "azure", d)["status"] == "PASS")
# 6 console bundle
check("console bundle missing -> FAIL", v4c.check_console_bundle(tree({}), "azure")["status"] == "FAIL")
check("console bundle present -> PASS", v4c.check_console_bundle(tree({"wasm/v4/azure/index.html": "x", "wasm/v4/azure/main.js": "x"}), "azure")["status"] == "PASS")
# 7 tunnel
tj = lambda v, rb: tree({"packaging/tunnel/package.json": {"version": v}, "packaging/brew/vyomi-tunnel.rb": f'url "https://r/vyomi-tunnel-{rb}.tgz"'})
import os as _os
_os.environ["VYOMI_NPM_VERSIONS"] = "1.0.0,1.1.0"
check("tunnel: 1.2.0 unpublished, formula behind -> PASS (normal pre-release)", v4c.check_tunnel_sync(tj("1.2.0", "1.0.0"))["status"] == "PASS")
_os.environ["VYOMI_NPM_VERSIONS"] = "1.0.0,1.1.0,1.2.0"
check("tunnel: 1.2.0 published but formula still 1.0.0 -> FAIL", v4c.check_tunnel_sync(tj("1.2.0", "1.0.0"))["status"] == "FAIL")
_os.environ.pop("VYOMI_NPM_VERSIONS")
check("tunnel: in sync -> PASS", v4c.check_tunnel_sync(tj("1.2.0", "1.2.0"))["status"] == "PASS")
check("tunnel: files absent -> SKIPPED", v4c.check_tunnel_sync(tree({}))["status"] == "SKIPPED")
# 8 image (no token -> SKIPPED, never PASS)
saved = {k: os.environ.pop(k, None) for k in ("GH_TOKEN", "GITHUB_TOKEN")}
check("image: no token -> SKIPPED", v4c.check_image_published(Path("."), None)["status"] == "SKIPPED")
for k, v in saved.items():
    if v: os.environ[k] = v
# 9 branch doc
check("branch doc: v4/x without doc -> FAIL", v4c.check_branch_doc(tree({}), "v4/foo")["status"] == "FAIL")
check("branch doc: present -> PASS", v4c.check_branch_doc(tree({"docs/architecture/v4.0/branches/foo.md": "x"}), "v4/foo")["status"] == "PASS")
check("branch doc: release branch -> SKIPPED", v4c.check_branch_doc(tree({}), "release/v4.0.0")["status"] == "SKIPPED")
# 10 waivers + exit code
cs = [v4c.R("x", "global", "FAIL", "boom"), v4c.R("y", "global", "SKIPPED", "no net")]
w = v4c.apply_waivers([dict(c) for c in cs], {"x": "ships bundled"})
check("waiver turns FAIL into a visible WAIVED", w[0]["status"] == "WAIVED" and "ships bundled" in w[0]["reason"] and w[1]["status"] == "SKIPPED")
# 11 wasm/core sync: build a clean copy, prove PASS, then desync one file and prove FAIL
tmp = Path(tempfile.mkdtemp(prefix="v4sync-"))
v4c._copy_for_build(REPO, tmp)
rc, out = v4c.run([sys.executable, "wasm/build_cores.py"], tmp)
check("setup: build_cores ran in the temp tree", rc == 0)
check("wasm/core in sync after a fresh vendor -> PASS", v4c.check_wasm_core_sync(tmp)["status"] == "PASS")
f = next((tmp / "wasm/core").glob("azure_dns_core.py"))
f.write_text(f.read_text() + "\n# deliberate desync\n")
c = v4c.check_wasm_core_sync(tmp)
check("desynced wasm/core file -> FAIL naming it", c["status"] == "FAIL" and "azure_dns_core.py" in c["reason"])
shutil.rmtree(tmp, ignore_errors=True)
print("PASS")
