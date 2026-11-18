"""scripts/release_checks_sdk_rate.py: the SDK pass-rate line of the release-checks report.

The marker must parse in the portal (vyomi-cloud/portal app/release_checks.py parse_sdk): the test below re-implements that
parser byte for byte (regexes copied from the portal) so a drift on either side shows up here.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(ROOT, "scripts", "release_checks_sdk_rate.py")
spec = importlib.util.spec_from_file_location("release_checks_sdk_rate", SCRIPT)
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

# --- copied from the portal's app/release_checks.py (keep identical) -------------------------------------------------------
_SDK_RE = re.compile(r"<!--\s*sdk-pass-rate:\s*(.*?)\s*-->", re.I | re.S)
_KV_RE = re.compile(r"(\w+)\s*=\s*([0-9]+(?:\.[0-9]+)?)")


def portal_parse_sdk(text):
    empty = {"sdk_passed": None, "sdk_total": None, "sdk_not_run": None, "sdk_rate": None}
    if not text:
        return empty
    try:
        m = _SDK_RE.search(text)
        if not m:
            return empty
        kv = {k.lower(): v for k, v in _KV_RE.findall(m.group(1))}
        passed, total = int(float(kv["passed"])), int(float(kv["total"]))
        not_run = int(float(kv.get("not_run", 0)))
        rate = float(kv["rate"]) if "rate" in kv else (round(100.0 * passed / total, 1) if total else None)
        if total <= 0 or passed < 0 or passed > total or rate is None or not (0.0 <= rate <= 100.0):
            return empty
        return {"sdk_passed": passed, "sdk_total": total, "sdk_not_run": max(0, not_run), "sdk_rate": round(rate, 1)}
    except (KeyError, ValueError, TypeError):
        return empty
# ---------------------------------------------------------------------------------------------------------------------------


def suite(id_, kind, cloud, passed, failed, status=None):
    return {"id": id_, "target": "offline", "cloud": cloud, "kind": kind, "passed": passed, "failed": failed,
            "status": status or ("pass" if not failed else "fail")}


def write(arts, cloud, suites, name=None):
    d = arts / f"checks-sdk-{cloud}"
    d.mkdir(parents=True, exist_ok=True)
    (d / (name or f"results-offline-{cloud}.json")).write_text(json.dumps({"suites": suites}))


def test_all_pass(tmp_path):
    write(tmp_path, "aws", [suite("a-py", "sdk-python", "aws", 40, 0), suite("a-go", "sdk-go", "aws", 10, 0),
                            suite("a-java", "sdk-java", "aws", 5, 0)])
    t = rc.compute(str(tmp_path))
    assert (t["passed"], t["failed"], t["not_run"], t["total"], t["rate"]) == (55, 0, 0, 55, 100.0)
    assert rc.marker(t) == "<!-- sdk-pass-rate: passed=55 total=55 not_run=0 rate=100.0 -->"


def test_some_fail_rate_one_decimal(tmp_path):
    write(tmp_path, "aws", [suite("a-py", "sdk-python", "aws", 18, 1)])
    write(tmp_path, "gcp", [suite("g-go", "sdk-go", "gcp", 9, 0), suite("g-java", "sdk-java", "gcp", 2, 1)])
    t = rc.compute(str(tmp_path))
    assert (t["passed"], t["failed"]) == (29, 2)
    assert t["rate"] == round(100 * 29 / 31, 1) == 93.5
    assert rc.marker(t) == "<!-- sdk-pass-rate: passed=29 total=31 not_run=0 rate=93.5 -->"
    assert {f["id"] for f in t["failing"]} == {"a-py", "g-java"}


def test_pending_suites_are_not_run_and_excluded_from_rate(tmp_path):
    write(tmp_path, "azure", [suite("z-go", "sdk-go", "azure", 8, 2), suite("z-java", "sdk-java", "azure", 0, 0, "pending")])
    t = rc.compute(str(tmp_path))
    assert (t["passed"], t["failed"], t["not_run"]) == (8, 2, 1)
    assert t["rate"] == 80.0                    # not_run is not in the rate
    assert t["total"] == 11                     # the portal derives failing = total - passed - not_run = 2
    assert t["total"] - t["passed"] - t["not_run"] == t["failed"]


def test_suite_that_printed_nothing_counts_as_one_failure(tmp_path):
    write(tmp_path, "aws", [suite("a-go", "sdk-go", "aws", 0, 0, "fail"), suite("a-py", "sdk-python", "aws", 9, 0)])
    t = rc.compute(str(tmp_path))
    assert (t["passed"], t["failed"]) == (9, 1)


def test_only_sdk_kinds_count(tmp_path):
    write(tmp_path, "aws", [suite("ui", "ui", "aws", 99, 99), suite("api", "api", "aws", 5, 5), suite("cli", "cli", "aws", 7, 7),
                            suite("a-sdk", "sdk", "aws", 3, 0)])
    t = rc.compute(str(tmp_path))
    assert (t["passed"], t["failed"]) == (3, 0)


def test_nothing_ran_emits_no_marker(tmp_path):
    write(tmp_path, "aws", [suite("a-go", "sdk-go", "aws", 0, 0, "pending")])
    t = rc.compute(str(tmp_path))
    assert t["rate"] is None and rc.marker(t) == ""
    md = rc.render(t, True)
    assert "sdk-pass-rate" not in md and "Not measured" in md


def test_no_artifacts_emits_nothing(tmp_path):
    t = rc.compute(str(tmp_path))
    assert t["rate"] is None
    assert rc.render(t, have_artifacts=False) == ""
    out = subprocess.run([sys.executable, SCRIPT, str(tmp_path)], capture_output=True, text=True, check=True).stdout
    assert out == ""


def test_malformed_files_are_skipped_and_reported(tmp_path):
    write(tmp_path, "aws", [suite("a-py", "sdk-python", "aws", 4, 0)])
    d = tmp_path / "checks-sdk-gcp"
    d.mkdir()
    (d / "results-offline-gcp.json").write_text("{not json")
    (tmp_path / "checks-sdk-azure").mkdir()
    (tmp_path / "checks-sdk-azure" / "results-offline-azure.json").write_text(json.dumps({"suites": "nope"}))
    t = rc.compute(str(tmp_path))
    assert (t["passed"], t["failed"], t["rate"]) == (4, 0, 100.0)
    assert len(t["unreadable"]) == 2 and set(t["missing_clouds"]) == {"gcp", "azure"}
    md = rc.render(t, True)
    assert "Unreadable result files" in md and "No SDK results from: gcp, azure" in md


def test_garbage_counts_do_not_crash(tmp_path):
    write(tmp_path, "aws", [{"id": "x", "kind": "sdk-go", "cloud": "aws", "passed": "many", "failed": None, "status": "fail"}])
    t = rc.compute(str(tmp_path))
    assert t["failed"] == 1 and t["rate"] == 0.0


@pytest.mark.parametrize("passed,failed,not_run", [(55, 0, 0), (29, 2, 0), (8, 2, 1), (1, 99, 3)])
def test_marker_parses_in_the_portal(tmp_path, passed, failed, not_run):
    suites = [suite("a", "sdk-go", "aws", passed, failed)] + [suite(f"p{i}", "sdk-java", "aws", 0, 0, "pending") for i in range(not_run)]
    write(tmp_path, "aws", suites)
    t = rc.compute(str(tmp_path))
    md = "# Release checks — v9.9.9\n\n| a | b |\n\n" + rc.render(t, True)
    got = portal_parse_sdk(md)
    assert got["sdk_passed"] == passed
    assert got["sdk_total"] == passed + failed + not_run
    assert got["sdk_not_run"] == not_run
    assert got["sdk_rate"] == round(100.0 * passed / (passed + failed), 1)
    # the portal's failing count for the bars
    assert got["sdk_total"] - got["sdk_passed"] - got["sdk_not_run"] == failed
    assert md.count("sdk-pass-rate") == 1          # exactly one marker


def test_marker_is_an_html_comment_so_row_counts_are_unchanged(tmp_path):
    write(tmp_path, "aws", [suite("a", "sdk-go", "aws", 3, 0)])
    line = rc.marker(rc.compute(str(tmp_path)))
    assert line.startswith("<!--") and line.endswith("-->") and "\n" not in line
    assert "✅" not in line and "❌" not in line


def test_workflow_wires_the_job_and_report_step():
    import yaml
    wf = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", "release-checks.yml")))
    jobs = wf["jobs"]
    assert "sdk-checks" in jobs and "sdk-checks" in jobs["report"]["needs"]
    assert jobs["sdk-checks"]["strategy"]["matrix"]["cloud"] == ["aws", "gcp", "azure"]
    names = [s.get("name", "") for s in jobs["report"]["steps"]]
    assert any("SDK" in n for n in names)
    text = open(os.path.join(ROOT, ".github", "workflows", "release-checks.yml")).read()
    assert "scripts/release_checks_sdk_rate.py" in text
    # the existing report sections are untouched
    for must in ("## ${k^^}", "## CLI (aws / gcloud / az) and CLI", "## Startup (all services + UI)"):
        assert must in text
