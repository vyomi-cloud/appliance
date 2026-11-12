"""v4_eod_plan.decide: every guard/gate/safety branch. Run: python3 tests/conformance/test_v4_eod_plan.py"""
import importlib.util, shutil, tempfile
from pathlib import Path
R = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("p", R / "tests/release/v4_eod_plan.py"); p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
ki = p.ki
md = Path(tempfile.mkdtemp()) / "KI.md"; shutil.copy(ki.DEFAULT, md)
OK = {"azure": "ok", "aws": "ok", "gcp": "ok"}


def check(n, c):
    if not c: raise AssertionError(n)
    print("  ok ", n)


d = lambda **k: p.decide(**{**dict(version="4.0.0", commits_since=3, existing_tags=["v4.0.0"], cloud_status=OK, md=md, busy=(), paused=False, auto_release=True, dry_run=False), **k})
check("v3 VERSION -> skip (v4.0.0 not cut)", d(version="3.0.45")["decision"] == "skip")
check("paused -> skip", d(paused=True)["decision"] == "skip")
check("a fixer/bidi still running -> skip", d(busy=("v4-known-issues-hourly",))["decision"] == "skip")
check("no commits since the last tag -> skip", d(commits_since=0)["decision"] == "skip")
check("a red cloud blocks", d(cloud_status={**OK, "aws": "red: suite X"})["decision"] == "blocked")
check("a missing cloud blocks", d(cloud_status={"azure": "ok", "aws": "ok"})["decision"] == "blocked")
ki.add_issue("gcp", "boom", "S1", "wrong data", "x", path=md)
r = d(); check("an open S1 row blocks that cloud", r["decision"] == "blocked" and r["clouds"]["gcp"]["open_s1"] == ["AUTO-gcp-boom"])
ki.resolve("AUTO-gcp-boom", "x", md)
check("tag clash blocks", d(existing_tags=["v4.0.0", "v4.0.1"])["decision"] == "blocked")
check("armed + green -> release v4.0.1", (lambda r: r["decision"] == "release" and r["next_version"] == "4.0.1")(d()))
check("not armed -> dry-run", d(auto_release=False)["decision"] == "dry-run")
check("dry_run input wins over armed", d(dry_run=True)["decision"] == "dry-run")
check("next_patch", p.next_patch("4.0.9") == "4.0.10" and p.next_patch("x") is None)
a = "| AZ-1 | S2 | x | y | z |\n| AZ-2 | S3 | x | y | z |\n"; b = "| AZ-2 | S3 | x | y | z |\n| AUTO-azure-n | S2 | x | y | z |\n"
check("delta lists added + resolved rows", p.delta(a, b) == {"added": ["AUTO-azure-n"], "resolved": ["AZ-1"]})
print("PASS")
