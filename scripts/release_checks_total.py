#!/usr/bin/env python3
"""Total checks run in a release, read from the finished RELEASE-CHECKS.md, as ONE machine-readable marker for the portal:

    <!-- checks-total: passed=P failed=F total=T rows=R ui_suites=U sdk=S -->

The portal used to count only the "| ✅ |" / "| ❌ |" table rows (packages, CLI, Nano CLI): 277 for v4.1.1, while the report also runs the
Nano console UI suites and the native-SDK suites. This counts everything the report states, each in its own unit:
  rows       one per check row (deb/rpm/brew install + vyomi commands, CLI suites, CLI <-> console both ways, Nano CLI through the tunnel)
  ui_suites  one per Nano console UI suite ("## Console UI (Nano) - <cloud>": "P/N suites passed")
  sdk        one per native-SDK check ("SDK checks: P/N passed")
total = rows + ui_suites + sdk; the portal shows total and the breakdown. Nothing estimated: a section that is absent adds 0.

    python3 scripts/release_checks_total.py RELEASE-CHECKS.md          # prints the marker
"""
import re
import sys

ROW_OK, ROW_BAD = "| ✅ |", "| ❌ |"
UI = re.compile(r"^## Console UI \(Nano\)[^\n]*\n\n\S+ (\d+)/(\d+) suites passed", re.M)
SDK = re.compile(r"SDK checks: (\d+)/(\d+) passed")


def compute(text):
    ok = sum(1 for ln in text.splitlines() if ln.startswith(ROW_OK))
    bad = sum(1 for ln in text.splitlines() if ln.startswith(ROW_BAD))
    ui_p = ui_n = 0
    for p, n in UI.findall(text):
        ui_p += int(p)
        ui_n += int(n)
    m = SDK.search(text)
    sdk_p, sdk_n = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    passed, total = ok + ui_p + sdk_p, ok + bad + ui_n + sdk_n
    return dict(passed=passed, failed=total - passed, total=total, rows=ok + bad, ui_suites=ui_n, sdk=sdk_n)


def marker(t):
    return "<!-- checks-total: " + " ".join(f"{k}={t[k]}" for k in ("passed", "failed", "total", "rows", "ui_suites", "sdk")) + " -->"


if __name__ == "__main__":
    print(marker(compute(open(sys.argv[1], encoding="utf-8").read())))
