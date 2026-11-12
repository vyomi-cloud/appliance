"""bidi_report.py with synthetic run_suites results: a new failure adds a row, a repeat does not duplicate, a passing check resolves
its row (self-healing), a crashed suite gets one suite row, a suite that did not run changes nothing. Works on a COPY of the md file.
Run: python3 tests/conformance/nightly/test_bidi_report.py"""
import json, shutil, tempfile
from pathlib import Path
import importlib.util

spec = importlib.util.spec_from_file_location("br", Path(__file__).parent / "bidi_report.py")
br = importlib.util.module_from_spec(spec); spec.loader.exec_module(br)
ki = br.ki
SID = "offline-ui-azure-v4-bidirectional"   # a real, selected suite id

d = Path(tempfile.mkdtemp())
md = d / "KI.md"; shutil.copy(ki.DEFAULT, md)
(d / "logs").mkdir()


def run(status, log, sid=SID, cloud="azure", tail=None):
    (d / "logs" / f"{sid}.log").write_text(log)
    json.dump({"suites": [{"id": sid, "target": "offline", "cloud": cloud, "kind": "ui", "status": status,
                           "tail": tail if tail is not None else log[-500:]}]}, open(d / f"results-offline-{cloud}.json", "w"))
    return br.report(cloud, d, md, "test", [])


def auto(cloud="azure"):
    return sorted(r["id"] for r in ki.list_open(cloud, md) if r["id"].startswith("AUTO-"))


def check(n, c):
    if not c: raise AssertionError(n)
    print("  ok ", n)


check("select finds the azure bi-directional suite", SID in [x["id"] for x in br.select("azure", "offline")] and br.select("aws") and br.select("gcp"))
check("legacy-console suite is excluded", "offline-ui-sdk-roundtrip" not in [s["id"] for s in br.select("aws")])
check("keys ignore run-specific ids", br.slug("VM bd-u542884 created") == br.slug("VM bd-u991122 created"))

c = run("fail", "[PASS] setup ok\n[FAIL] UI->API: VM bd-u111222 power state :: expected stopped got running\n[FAIL] list shows wrong data :: names differ\n")
check("two failures added", len(c["added"]) == 2 and len(auto()) == 2)
check("impact: plain failure S2, wrong-data wording S1", {r["impact"] for r in ki.list_open("azure", md) if r["id"].startswith("AUTO-")} == {"S1", "S2"})
check("row names the suite file", "validate-azure-v4-bidirectional.mjs" in md.read_text())

c = run("fail", "[PASS] setup ok\n[FAIL] UI->API: VM bd-u999000 power state :: expected stopped got running\n[FAIL] list shows wrong data :: names differ\n")
check("repeat run does not duplicate (run id changed)", len(auto()) == 2 and not c["added"] and len(c["updated"]) == 2)

c = run("fail", "[PASS] UI->API: VM bd-u5550 power state\n[FAIL] list shows wrong data :: names differ\n")
check("a check that passes again is resolved; the other stays", len(c["resolved"]) == 1 and len(auto()) == 1)
check("resolved row moved to the Resolved section", "resolved by test" in md.read_text())

c = run("pass", "[PASS] UI->API: VM x\n[PASS] list shows wrong data\n")
check("fully green suite resolves what is left", auto() == [] and len(c["resolved"]) == 1)

c = run("fail", "node: command crashed\nTypeError: boom", tail="TypeError: boom")
check("a crashed suite gets exactly one suite row", auto() == [f"AUTO-azure-{br.slug(SID, 40)}-suite"])
c = run("fail", "node: command crashed again", tail="crash again")
check("crash repeat does not duplicate", len(auto()) == 1)
c = run("pass", "[PASS] a\n")
check("green run resolves the suite row", auto() == [])

run("fail", "[FAIL] keep me :: x\n")
before = auto()
json.dump({"suites": []}, open(d / "results-offline-azure.json", "w"))     # the suite did not run today
c = br.report("azure", d, md, "test", [])
check("a suite that did not run changes nothing", auto() == before and not c["resolved"] and c["suites_run"] == [])
pend = {"suites": [{"id": SID, "status": "pending", "tail": "PENDING"}]}
json.dump(pend, open(d / "results-offline-azure.json", "w"))
check("a pending suite changes nothing", auto() == before and not br.report("azure", d, md, "test", [])["resolved"])

(d / "mesh.log").write_text("[PASS] ok\n[FAIL] runCommand echo hello :: HTTP 200 no guest\n")
json.dump({"suites": []}, open(d / "results-offline-azure.json", "w"))
c = br.report("azure", d, md, "test", [("azure-mesh-vm", str(d / "mesh.log"), "wasm/ui-tests/azure-mesh/vm-bidirectional.mjs")])
check("an optional live-Mesh log is reported too", any("azure-mesh-vm" in i for i in c["added"]) and "vm-bidirectional.mjs" in md.read_text())

c = run("fail", "[FAIL] x :: y\n", sid="nightly-aws-v4-roundtrip", cloud="aws")
check("other clouds report under their own prefix", any(i.startswith("AUTO-aws-") for i in c["added"]) and not any(i.startswith("AUTO-aws-") for i in auto("azure")))
print("PASS")
