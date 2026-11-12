#!/usr/bin/env python3
"""Turn the console crawler's findings into AUTO rows in docs/architecture/v4.0/V4.0.0-KNOWN-ISSUES.md (all three clouds).

    python3 tests/conformance/nightly/crawl_report.py --cloud azure [--ui out/ui-nano-azure.json ...] [--file <md>] [--by <sha>]

Input: the crawler's JSON (tests/conformance/hourly/out/ui-<target>-<cloud>.json): {"services": [{"cloud","service","findings":[{"type","detail"}]}]}.
Row key: `crawl-<service slug>-<finding type>` -> `AUTO-<cloud>-crawl-<service>-<type>`. A finding that disappears for a service that WAS
crawled in this run resolves its row (self-healing); services that were not crawled never resolve anything.
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("known_issues", HERE / "lib" / "known_issues.py")
ki = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ki)

# findings that mean the feature does not work -> S2; the rest are fidelity/cosmetic -> S3
S2 = {"PAGE_ERROR", "HTTP_5XX", "HTTP_404", "PLACEHOLDER_PANE", "DEAD_TAB", "UNCAUGHT"}


def slug(t: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:n] or "x"


def collect(ui_files, cloud):
    """-> (crawled service slugs, {key: (type, service, [details])})"""
    crawled, found = set(), {}
    for f in ui_files:
        data = json.load(open(f))
        for s in data.get("services") or []:
            if s.get("cloud") != cloud:
                continue
            ss = slug(s.get("service") or "")
            crawled.add(ss)
            for fd in s.get("findings") or []:
                t = str(fd.get("type") or "FINDING").upper()
                k = f"crawl-{ss}-{slug(t, 24)}"
                ent = found.setdefault(k, (t, s.get("service"), []))
                if len(ent[2]) < 3:
                    ent[2].append(str(fd.get("detail") or "")[:140])
    return crawled, found


def report(cloud, ui_files, md, by=""):
    crawled, found = collect(ui_files, cloud)
    out = {"cloud": cloud, "crawled": len(crawled), "added": [], "updated": [], "resolved": []}
    for k, (t, svc, details) in sorted(found.items()):
        what = f"Console crawl: {svc}: {t}: " + " / ".join(dict.fromkeys(details))
        r = ki.add_issue(cloud, k, "S2" if t in S2 else "S3", what, "tests/conformance/hourly/ui_crawler.mjs (finding in the console for " + str(svc) + ")", path=md)
        out["added" if r == "added" else "updated"].append(f"AUTO-{cloud}-{k}")
    seen = {f"AUTO-{cloud}-{k}" for k in found}
    for row in ki.list_open(cloud, md):
        rid = row["id"]
        m = re.match(rf"AUTO-{cloud}-crawl-(.+)-[a-z0-9-]+$", rid)
        if not m or rid in seen:
            continue
        # resolve only when that service was crawled this run
        if any(rid.startswith(f"AUTO-{cloud}-crawl-{c}-") for c in crawled) and ki.resolve(rid, by or "crawl", md):
            out["resolved"].append(rid)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud", required=True, choices=["azure", "aws", "gcp"])
    ap.add_argument("--ui", nargs="*", default=None)
    ap.add_argument("--file", default=str(ki.DEFAULT))
    ap.add_argument("--by", default="")
    ap.add_argument("--require-run", action="store_true", help="exit 3 when no crawl result for the cloud was found")
    a = ap.parse_args(argv)
    files = a.ui or sorted(glob.glob(str(HERE.parents[2] / "tests/conformance/hourly/out/ui-*.json")))
    res = report(a.cloud, files, a.file, a.by)
    print(json.dumps(res))
    if a.require_run and not res["crawled"]:
        print("::warning::no crawl result for " + a.cloud, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
