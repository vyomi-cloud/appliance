#!/usr/bin/env python3
"""Markdown summary of one run_suites results file, for the release-checks report."""
import json, sys

title, path = sys.argv[1], sys.argv[2]
try:
    suites = json.load(open(path))["suites"]
except Exception:
    print(f"## {title}\n\n❌ no results file (the job did not finish)\n")
    sys.exit(0)
bad = [s for s in suites if s["status"] not in ("pass", "pending")]
ok = len(suites) - len(bad)
print(f"## {title}\n\n{'✅' if not bad else '❌'} {ok}/{len(suites)} suites passed\n")
if bad:
    print("| Failing suite | Passed | Failed |\n|---|---|---|")
    for s in bad:
        print(f"| `{s['id']}` | {s.get('passed', 0)} | {s.get('failed', 0)} |")
    print()
