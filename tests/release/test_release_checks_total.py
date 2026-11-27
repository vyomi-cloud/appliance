"""The checks-total marker counts every row, Nano UI suite and SDK check the report states (not only the table rows)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import release_checks_total as rct  # noqa: E402

REPORT = """# Release checks - v9

| | Check | Detail |
|---|---|---|
| ✅ | a | x |
| ✅ | b | x |
| ❌ | c | x |

## Console UI (Nano) - aws

❌ 3/4 suites passed

| Failing suite | Passed | Failed |
|---|---|---|

## Console UI (Nano) - gcp

✅ 2/2 suites passed

## SDK checks (Python, Go, Java)

❌ SDK checks: 98/100 passed (98.0%)
"""


def test_counts_rows_ui_suites_and_sdk():
    t = rct.compute(REPORT)
    assert (t["rows"], t["ui_suites"], t["sdk"]) == (3, 6, 100)
    assert (t["passed"], t["failed"], t["total"]) == (2 + 5 + 98, 1 + 1 + 2, 109)


def test_missing_sections_add_zero():
    t = rct.compute("| ✅ | a | x |\n| ❌ | b | y |\n")
    assert t == dict(passed=1, failed=1, total=2, rows=2, ui_suites=0, sdk=0)


def test_marker_shape():
    assert rct.marker(rct.compute(REPORT)) == "<!-- checks-total: passed=105 failed=4 total=109 rows=3 ui_suites=6 sdk=100 -->"
