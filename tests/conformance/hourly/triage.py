#!/usr/bin/env python3
"""Split this hour's findings into one work slice per cloud for the parallel fixers.

Reads what the detect job produced in out/ (ui-nano.json, ui-offline.json,
results.json, new_features.json, upstream_issues.json) and writes
out/slices/<cloud>.json + out/slices/<cloud>.md for cloud in aws/gcp/azure.

UI findings are grouped by root-cause signature (target, cloud, type and the
detail with names/ids/numbers stripped), largest group first: one root cause
often explains many findings, and a fixer should fix the cause, not the rows.
Cross-cloud items (suites with cloud "all", non-cloud routes) go to whichever
slice is smallest so the three fixers stay balanced.

    python3 tests/conformance/hourly/triage.py [--out tests/conformance/hourly/out]
"""
from __future__ import annotations

import json
import os
import re
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")   # --out overrides (CI runs this from a tools checkout)
CLOUDS = ("aws", "gcp", "azure")


def _load(name, default):
    try:
        with open(os.path.join(OUT, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _signature(detail: str) -> str:
    s = str(detail or "")
    s = re.sub(r"https?://\S+", "<url>", s)
    # Quoted values: keep short labels (column / tab names say WHICH thing is
    # broken), drop ids and long free text.
    s = re.sub(r"(['\"`])(.*?)\1",
               lambda m: m.group(0) if len(m.group(2)) <= 24 and not re.search(r"\d", m.group(2)) else "<v>", s)
    s = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", s)               # hex ids / suffixes
    s = re.sub(r"\b[a-z]+-[0-9a-z]{6,}\b", "<id>", s)        # i-0abc…, vyomi-conf-…
    s = re.sub(r"\d+", "<n>", s)
    return re.sub(r"\s+", " ", s).strip()[:160]


def _cloud_of(text: str) -> str:
    t = (text or "").lower()
    for c in ("gcp", "azure"):
        if c in t:
            return c
    return "aws" if "aws" in t else ""


def main() -> int:
    global OUT
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    OUT = os.path.abspath(ap.parse_args().out)
    slices = {c: {"cloud": c, "ui_root_causes": [], "failing_suites": [], "parity": [],
                  "new": [], "untested_ops": [], "uncovered": [], "upstream_issues": []}
              for c in CLOUDS}
    shared: dict[str, list] = {"failing_suites": [], "uncovered": []}

    # UI findings → root-cause clusters per cloud.
    ui = {t: _load(f"ui-{t}.json", {}) for t in ("nano", "offline")}
    clusters: dict[str, OrderedDict] = {c: OrderedDict() for c in CLOUDS}
    for target, doc in ui.items():
        for svc in (doc or {}).get("services", []):
            cloud = svc.get("cloud")
            if cloud not in CLOUDS:
                continue
            for f in svc.get("findings", []):
                key = f"{target}|{f.get('type')}|{_signature(f.get('detail'))}"
                g = clusters[cloud].setdefault(key, {
                    "target": target, "type": f.get("type"),
                    "signature": _signature(f.get("detail")),
                    "count": 0, "services": [], "examples": []})
                g["count"] += 1
                if svc.get("service") not in g["services"]:
                    g["services"].append(svc.get("service"))
                if len(g["examples"]) < 3:
                    g["examples"].append({"service": svc.get("service"), **f})
    for c in CLOUDS:
        slices[c]["ui_root_causes"] = sorted(clusters[c].values(), key=lambda g: -g["count"])

    # Failing suites (log tail included; full log in out/logs/<id>.log).
    for s in (_load("results.json", {}) or {}).get("suites", []):
        if not s.get("exit_code"):
            continue
        item = {k: s.get(k) for k in ("id", "target", "cloud", "kind", "exit_code", "tail")}
        (slices[s["cloud"]]["failing_suites"] if s.get("cloud") in CLOUDS
         else shared["failing_suites"]).append(item)

    # Feature inventory diff: parity / new / untested ops carry a cloud.
    nf = _load("new_features.json", {}) or {}
    for key in ("parity", "new", "untested_ops"):
        for f in nf.get(key, []):
            if f.get("cloud") in CLOUDS:
                slices[f["cloud"]][key].append(f)
    for r in nf.get("uncovered", []):
        c = _cloud_of(r.get("path", "") + " " + r.get("file", ""))
        (slices[c]["uncovered"] if c else shared["uncovered"]).append(r)

    # Upstream drift issues mention their cloud in the title or labels.
    for i in _load("upstream_issues.json", []) or []:
        labels = " ".join(l.get("name", "") for l in i.get("labels", []))
        c = _cloud_of(f"{i.get('title', '')} {labels}") or "aws"
        slices[c]["upstream_issues"].append({k: i.get(k) for k in ("number", "title", "createdAt")})

    # Cross-cloud work to the lightest slice, one item at a time.
    def load(c):
        s = slices[c]
        return sum(g["count"] for g in s["ui_root_causes"]) + 5 * len(s["failing_suites"])
    for key, items in shared.items():
        for item in items:
            c = min(CLOUDS, key=load)
            slices[c][key].append({**item, "shared": True})

    os.makedirs(os.path.join(OUT, "slices"), exist_ok=True)
    for c, s in slices.items():
        with open(os.path.join(OUT, "slices", f"{c}.json"), "w") as f:
            json.dump(s, f, indent=1)
        lines = [f"# {c.upper()} slice", "",
                 f"- UI root causes: {len(s['ui_root_causes'])} "
                 f"({sum(g['count'] for g in s['ui_root_causes'])} findings)",
                 f"- Failing suites: {', '.join(x['id'] for x in s['failing_suites']) or 'none'}",
                 f"- Parity gaps: {len(s['parity'])}, new features: {len(s['new'])}, "
                 f"untested ops: {len(s['untested_ops'])}, uncovered routes: {len(s['uncovered'])}, "
                 f"upstream issues: {len(s['upstream_issues'])}", "", "## Top root causes", ""]
        for g in s["ui_root_causes"][:15]:
            lines.append(f"- **{g['count']}×** {g['target']} {g['type']} — {g['signature']} "
                         f"({', '.join(map(str, g['services'][:5]))})")
        with open(os.path.join(OUT, "slices", f"{c}.md"), "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"{c}: {len(s['ui_root_causes'])} root causes, "
              f"{sum(g['count'] for g in s['ui_root_causes'])} UI findings, "
              f"{len(s['failing_suites'])} failing suites")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
