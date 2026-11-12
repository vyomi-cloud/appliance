"""known_issues_pick.py: skips owner/env rows, orders by impact, honours the 24 h cooldown, no row -> empty.
Run: python3 tests/conformance/nightly/test_known_issues_pick.py"""
import json, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import known_issues_pick as kp  # noqa: E402

def check(n, c):
    if not c: raise AssertionError(n)
    print("  ok ", n)

MD = """# KI
## Azure (x)

| ID | Impact | What | Workaround | Where to start |
|---|---|---|---|---|
| AZ-1 | S3 | cosmetic thing in a console | None. | a.js |
| AZ-2 | S2 | **Mesh admits one VM** (by design) | stop it | x |
| AZ-3 | S2 | real bug in the ARM core | None. | core/a.py |
| AZ-4 | S1 | needs a call: owner decision on the data model | None. | x |
| AZ-5 | S2 | another real bug | None. | core/b.py |

## AWS (x)

| ID | Impact | What | Workaround | Where to start |
|---|---|---|---|---|
| AWS-1 | S3 | only thing | None. | y |

## Resolved after the cut

| ID | Impact | What | Workaround | Where to start |
|---|---|---|---|---|
| AZ-9 | resolved by abc | old | | |
"""
d = Path(tempfile.mkdtemp()); f = d / "KI.md"; f.write_text(MD); st = str(d / "st.json")
now = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
check("owner/design rows are not fixable", not kp.fixable({"what": "x (by design)"}) and not kp.fixable({"what": "owner decision needed"}) and kp.fixable({"what": "real bug"}))
check("highest impact fixable row first (S1 is owner-only, so S2 AZ-3)", kp.pick("azure", st, now, f) == "AZ-3")
kp.record("AZ-3", st, now)
check("an attempted row is skipped for 24 h", kp.pick("azure", st, now.replace(hour=20), f) == "AZ-5")
check("after 24 h it is eligible again", kp.pick("azure", st, now.replace(day=13, hour=11), f) == "AZ-3")
check("resolved rows never picked", kp.pick("azure", st, now.replace(day=20), f) != "AZ-9")
check("other cloud has its own row", kp.pick("aws", st, now, f) == "AWS-1")
check("gcp with no rows -> empty (no-op)", kp.pick("gcp", st, now, f) == "")
out = subprocess.run([sys.executable, str(HERE / "known_issues_pick.py"), "--cloud", "azure", "--file", str(f), "--state", str(d / "none.json"), "--now", "2026-11-12T10:00:00Z"], capture_output=True, text=True)
check("CLI prints just the id", out.stdout.strip() == "AZ-3" and out.returncode == 0)
real = [r for c in ("azure", "aws", "gcp") for r in [kp.pick(c, None, now)]]
print("  real file picks (azure, aws, gcp):", real)
print("PASS")
