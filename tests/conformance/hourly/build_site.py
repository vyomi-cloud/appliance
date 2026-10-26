#!/usr/bin/env python3
"""Build the public, interactive conformance report from the hourly run.

Reads out/results.json, out/ui-*.json, out/new_features.json, out/agent_summary.md
and the previously published history.json; writes site/index.html (the
interactive grid report, data embedded) plus the raw JSON next to it.

    python3 tests/conformance/hourly/build_site.py --history prev/history.json
"""
from __future__ import annotations

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SITE = os.path.join(HERE, "site")


def load(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default="")
    a = ap.parse_args()

    res = load(os.path.join(OUT, "results.json"), {"suites": [], "at": "", "commit": ""})
    feats = load(os.path.join(OUT, "new_features.json"), {})
    ui = {t: load(os.path.join(OUT, f"ui-{t}.json"), {"services": []}) for t in ("nano", "offline")}
    agent = ""
    if os.path.exists(os.path.join(OUT, "agent_summary.md")):
        agent = open(os.path.join(OUT, "agent_summary.md")).read().strip()
    history = load(a.history, []) if a.history else []

    suites = res.get("suites", [])
    services = [{"target": t, **{k: r.get(k) for k in ("cloud", "service", "status", "tabs")},
                 "findings": len(r.get("findings", []))} for t, d in ui.items() for r in d.get("services", [])]
    findings = [{"target": t, "cloud": r.get("cloud"), "service": r.get("service"), "tab": f.get("tab", ""),
                 "type": f.get("type"), "detail": f.get("detail")}
                for t, d in ui.items() for r in d.get("services", []) for f in r.get("findings", [])]
    rt, ru = feats.get("routes_total", 0), feats.get("routes_uncovered", 0)
    api_cov = round(100 * (rt - ru) / rt, 1) if rt else 0.0

    def clean(target, cloud=None):
        rows = [s for s in services if s["target"] == target and (cloud is None or s["cloud"] == cloud)]
        return sum(1 for s in rows if s["status"] == "ok"), len(rows)

    entry = {"at": res.get("at"), "commit": res.get("commit", "")[:12],
             "suites_green": sum(1 for s in suites if s["status"] == "pass"), "suites_total": len(suites),
             "checks_passed": sum(s.get("passed", 0) for s in suites),
             "checks_failed": sum(s.get("failed", 0) for s in suites), "api_coverage_pct": api_cov,
             "ui_findings": len(findings), "agent": agent.splitlines()[0][:200] if agent else ""}
    for t in ("nano", "offline"):
        entry[f"ui_clean_{t}"], entry[f"ui_total_{t}"] = clean(t)
    for c in ("aws", "gcp", "azure"):
        cs = [s for s in suites if s["cloud"] == c]
        entry[f"{c}_checks_passed"] = sum(s.get("passed", 0) for s in cs)
        entry[f"{c}_findings"] = sum(1 for f in findings if f["cloud"] == c)
    history = (history + [entry])[-720:]   # 30 days of hourly runs

    data = {
        "at": res.get("at"), "commit": res.get("commit", ""), "agent": agent,
        "suites": [{k: s.get(k) for k in ("id", "target", "cloud", "kind", "status", "passed", "failed", "duration_s", "tail")}
                   for s in suites],
        "services": services, "findings": findings, "history": history,
        "api": {"total": rt, "uncovered": ru, "pct": api_cov},
        "new": feats.get("new", []), "uncovered": feats.get("uncovered", [])[:500],
    }
    template = open(os.path.join(HERE, "report.html"), encoding="utf-8").read()
    # Embedded as JSON inside <script type="application/json">; escape "</" so a
    # finding's text can never close the script tag.
    blob = json.dumps(data).replace("</", "<\\/")
    page = template.replace("__REPORT_DATA__", blob)

    os.makedirs(SITE, exist_ok=True)
    open(os.path.join(SITE, "index.html"), "w", encoding="utf-8").write(page)
    json.dump(res, open(os.path.join(SITE, "results.json"), "w"), indent=1)
    json.dump(history, open(os.path.join(SITE, "history.json"), "w"), indent=1)
    json.dump(ui, open(os.path.join(SITE, "ui-findings.json"), "w"), indent=1)
    print(f"report written: {entry['suites_green']}/{len(suites)} suites green, "
          f"{len(findings)} UI findings, API coverage {api_cov}%")


if __name__ == "__main__":
    main()
