#!/usr/bin/env python3
"""SDK pass rate for the release-checks report.

Reads the per-cloud result files the `sdk-checks` jobs of release-checks.yml upload
(`<arts>/checks-sdk-<cloud>/results-offline-<cloud>.json`, written by tests/conformance/hourly/run_suites.py) and prints a
markdown section for RELEASE-CHECKS.md that ends with the machine-readable marker the portal parses
(portal app/release_checks.py `_SDK_RE`):

    <!-- sdk-pass-rate: passed=P total=T not_run=N rate=X.X -->

What counts as an SDK check: every check printed by a suite whose kind is sdk, sdk-python, sdk-go or sdk-java
(suites.json: the native Python / Go / Java SDK conformance suites run against the PUBLISHED release images).
  passed   = checks that passed
  failed   = checks that failed (a suite that crashed or printed nothing counts as 1 failed check: never green by silence)
  not_run  = suites marked pending in suites.json (written, but their dependency is not built): reported, never scored
  total    = passed + failed + not_run   (the portal computes the failing count as total - passed - not_run)
  rate     = passed / (passed + failed) * 100, one decimal: not_run is excluded from the rate
Nothing ran (no result files, or only pending suites) -> NO marker (the tiles stay "collecting"); nothing is estimated.

    python3 scripts/release_checks_sdk_rate.py arts            # markdown on stdout
    python3 scripts/release_checks_sdk_rate.py arts --json     # the totals as JSON
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

SDK_KINDS = ("sdk", "sdk-python", "sdk-go", "sdk-java")
CLOUDS = ("aws", "gcp", "azure")
LANG = {"sdk": "python", "sdk-python": "python", "sdk-go": "go", "sdk-java": "java"}


def _empty() -> dict:
    return {"passed": 0, "failed": 0, "not_run": 0, "suites": 0}


def compute(arts_dir: str) -> dict:
    """Totals + per-cloud / per-language breakdown from <arts_dir>/checks-sdk-*/results-offline-*.json."""
    per: dict = {}          # (cloud, lang) -> counters
    seen_clouds: set = set()
    unreadable: list = []
    failing: list = []
    paths = sorted(glob.glob(os.path.join(arts_dir, "checks-sdk-*", "**", "results-offline-*.json"), recursive=True))
    for path in paths:
        try:
            data = json.load(open(path))
            suites = data["suites"]
            if not isinstance(suites, list):
                raise ValueError("suites is not a list")
        except Exception:
            unreadable.append(os.path.relpath(path, arts_dir))
            continue
        for s in suites:
            if not isinstance(s, dict) or s.get("kind") not in SDK_KINDS:
                continue
            cloud = s.get("cloud") if s.get("cloud") in CLOUDS else "other"
            seen_clouds.add(cloud)
            c = per.setdefault((cloud, LANG[s["kind"]]), _empty())
            c["suites"] += 1
            if s.get("status") == "pending":
                c["not_run"] += 1
                continue
            try:
                p, f = max(0, int(s.get("passed") or 0)), max(0, int(s.get("failed") or 0))
            except (TypeError, ValueError):
                p, f = 0, 1
            if p + f == 0:
                f = 1          # nothing was checked: never green
            c["passed"] += p
            c["failed"] += f
            if f:
                failing.append({"id": s.get("id", "?"), "cloud": cloud, "passed": p, "failed": f})
    passed = sum(c["passed"] for c in per.values())
    failed = sum(c["failed"] for c in per.values())
    not_run = sum(c["not_run"] for c in per.values())
    ran = passed + failed
    return {
        "passed": passed, "failed": failed, "not_run": not_run,
        "total": ran + not_run,
        "rate": round(100.0 * passed / ran, 1) if ran else None,
        "per": per, "unreadable": unreadable, "failing": failing,
        "missing_clouds": [c for c in CLOUDS if c not in seen_clouds],
    }


def marker(t: dict) -> str:
    """The one machine-readable line, or '' when no SDK check ran."""
    if t["rate"] is None:
        return ""
    return f"<!-- sdk-pass-rate: passed={t['passed']} total={t['total']} not_run={t['not_run']} rate={t['rate']:.1f} -->"


def render(t: dict, have_artifacts: bool = True) -> str:
    if not have_artifacts:
        return ""
    lines = ["## SDK checks (Python, Go, Java)", ""]
    if t["rate"] is None:
        lines += ["❔ Not measured for this release: no SDK check produced a result.", ""]
        if t["unreadable"]:
            lines += ["Unreadable result files: " + ", ".join(f"`{p}`" for p in t["unreadable"]), ""]
        return "\n".join(lines)
    ran = t["passed"] + t["failed"]
    icon = "✅" if not t["failed"] else "❌"
    lines += [f"{icon} SDK checks: {t['passed']}/{ran} passed ({t['rate']:.1f}%)"
              + (f", {t['not_run']} suite(s) pending (not scored)" if t["not_run"] else ""), "",
              "Native-SDK conformance suites (the ones the hourly conformance agent runs) against the published release images, "
              "per cloud and language.", "",
              "| Cloud | Python | Go | Java |", "|---|---|---|---|"]
    for cloud in (*CLOUDS, "other"):
        row = [t["per"].get((cloud, lang)) for lang in ("python", "go", "java")]
        if not any(row):
            continue
        cells = [f"{c['passed']}/{c['passed'] + c['failed']}" if c and c["passed"] + c["failed"] else "—" for c in row]
        lines.append(f"| {cloud} | " + " | ".join(cells) + " |")
    lines.append("")
    if t["missing_clouds"]:
        lines += ["No SDK results from: " + ", ".join(t["missing_clouds"]) + " (their job did not finish; not counted).", ""]
    if t["unreadable"]:
        lines += ["Unreadable result files (not counted): " + ", ".join(f"`{p}`" for p in t["unreadable"]), ""]
    if t["failing"]:
        lines += ["| Failing suite | Passed | Failed |", "|---|---|---|"]
        lines += [f"| `{f['id']}` | {f['passed']} | {f['failed']} |" for f in t["failing"]]
        lines.append("")
    lines += [marker(t), ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("arts", help="the downloaded-artifacts directory (contains checks-sdk-<cloud>/)")
    ap.add_argument("--json", action="store_true", help="print the totals as JSON instead of markdown")
    a = ap.parse_args(argv)
    t = compute(a.arts)
    have = bool(glob.glob(os.path.join(a.arts, "checks-sdk-*")))
    if a.json:
        out = {k: v for k, v in t.items() if k != "per"}
        out["per"] = {f"{c}/{l}": v for (c, l), v in t["per"].items()}
        out["marker"] = marker(t)
        print(json.dumps(out, indent=1))
    else:
        sys.stdout.write(render(t, have))
    return 0


if __name__ == "__main__":
    sys.exit(main())
