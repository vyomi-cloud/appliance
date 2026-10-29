#!/usr/bin/env python3
"""Join the detect shards' outputs into what one unsharded detect job wrote.

Each shard (run_suites.py --target T --cloud C) leaves in out/:
  results-T-C.json   its suites ({"at", "commit", "suites": [...]})
  ui-T-C.json        its slice of the UI crawl ({"target", "at", "services": [...]})
This writes out/results.json, out/ui-offline.json and out/ui-nano.json in the
same shapes triage.py and build_site.py already read. A crawl suite runs in all
three cloud shards of its target, so its three results are combined into one.
Shards that never reported are listed under "missing_shards" in results.json.

    python3 tests/conformance/hourly/merge_shards.py [--out DIR]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
CLOUDS = ("aws", "gcp", "azure")
TARGETS = ("offline", "nano")


def _load(path: str):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return None


def combine(parts: list[dict]) -> dict:
    """One suite's results from several shards (the per-cloud crawls)."""
    if len(parts) == 1:
        return parts[0]
    r = dict(parts[0])
    r["passed"] = sum(p.get("passed", 0) for p in parts)
    r["failed"] = sum(p.get("failed", 0) for p in parts)
    r["duration_s"] = max(p.get("duration_s", 0) for p in parts)
    r["exit_code"] = next((p["exit_code"] for p in parts if p.get("exit_code")), 0)
    r["status"] = "pass" if all(p.get("status") == "pass" for p in parts) else "fail"
    if any("broken_services" in p for p in parts):
        r["broken_services"] = [b for p in parts for b in p.get("broken_services", [])]
    r["tail"] = "\n".join(p.get("tail", "") for p in parts if p.get("tail"))[-3000:]
    return r


def merge(out: str, order: list[str]) -> dict:
    by_id: dict[str, list] = {}
    at, commit, seen = [], "", set()
    for path in sorted(glob.glob(os.path.join(out, "results-*-*.json"))):
        m = re.match(r"results-(\w+)-(\w+)\.json$", os.path.basename(path))
        d = _load(path)
        if not m or m.group(1) not in TARGETS or m.group(2) not in CLOUDS or not isinstance(d, dict):
            continue
        seen.add(f"{m.group(1)}-{m.group(2)}")
        at.append(d.get("at", ""))
        commit = commit or d.get("commit", "")
        for s in d.get("suites", []):
            by_id.setdefault(s["id"], []).append(s)
    rank = {sid: i for i, sid in enumerate(order)}
    suites = [combine(v) for _, v in sorted(by_id.items(), key=lambda kv: (rank.get(kv[0], len(rank)), kv[0]))]
    missing = [f"{t}-{c}" for t in TARGETS for c in CLOUDS if f"{t}-{c}" not in seen]
    res = {"at": max(at) if at else "", "commit": commit, "suites": suites}
    if missing:
        res["missing_shards"] = missing
    json.dump(res, open(os.path.join(out, "results.json"), "w"), indent=1)

    for t in TARGETS:
        services, ats, partial = [], [], False
        for c in CLOUDS:
            d = _load(os.path.join(out, f"ui-{t}-{c}.json"))
            if not isinstance(d, dict):
                partial = True          # that cloud's crawl never wrote its slice
                continue
            services += d.get("services", [])
            ats.append(d.get("at", ""))
            partial = partial or bool(d.get("partial"))
        if not ats:
            continue                    # no crawl ran for this target: leave no file, as before
        ui = {"target": t, "at": max(ats), "services": services}
        if partial:
            ui["partial"] = True
        json.dump(ui, open(os.path.join(out, f"ui-{t}.json"), "w"), indent=1)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    a = ap.parse_args()
    order = [s["id"] for s in json.load(open(os.path.join(HERE, "suites.json")))["suites"]]
    res = merge(a.out, order)
    bad = [s["id"] for s in res["suites"] if s.get("status") != "pass"]
    print(f"merged {len(res['suites'])} suites; {len(res['suites']) - len(bad)} green"
          + (f"; missing shards: {', '.join(res['missing_shards'])}" if res.get("missing_shards") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
