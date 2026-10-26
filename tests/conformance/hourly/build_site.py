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


NAMES = {"aws": "AWS", "gcp": "GCP", "azure": "Azure", "all": "Cross-cloud"}


def md(s) -> str:
    """Make a value safe inside a Markdown table cell."""
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def markdown(d: dict, e: dict) -> str:
    """The report as GitHub-rendered Markdown (README.md on the report branch):
    per-cloud sections with collapsible findings and failing-suite logs."""
    suites, services, findings = d["suites"], d["services"], d["findings"]
    L = [f"# Vyomi Conformance — hourly report",
         "",
         f"Run **{md(d.get('at') or 'not yet')}** · commit `{md((d.get('commit') or '')[:12])}` · "
         "Nano (in-browser) + offline appliance · updated every hour by "
         "[the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).",
         "",
         "| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |",
         "|---|---|---|---|---|---|---|",
         f"| {e['suites_green']}/{e['suites_total']} | {e['checks_passed']} | {e['checks_failed']} | "
         f"{e['ui_clean_nano']}/{e['ui_total_nano']} | {e['ui_clean_offline']}/{e['ui_total_offline']} | "
         f"{e['ui_findings']} | {d['api']['pct']}% ({d['api']['total'] - d['api']['uncovered']}/{d['api']['total']}) |",
         ""]
    if d.get("agent"):
        L += ["> **Agent this run:** " + md(d["agent"].splitlines()[0]), ""]

    L += ["## By cloud", "",
          "| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |",
          "|---|---|---|---|---|---|---|"]
    for c in ("aws", "gcp", "azure"):
        cs = [s for s in suites if s["cloud"] == c]
        def clean(t):
            rows = [s for s in services if s["cloud"] == c and s["target"] == t]
            return f"{sum(1 for s in rows if s['status'] == 'ok')}/{len(rows)}"
        L.append(f"| [{NAMES[c]}](#{c}) | {sum(1 for s in cs if s['status'] == 'pass')}/{len(cs)} | "
                 f"{sum(s.get('passed') or 0 for s in cs)} | {sum(s.get('failed') or 0 for s in cs)} | "
                 f"{clean('nano')} | {clean('offline')} | {sum(1 for f in findings if f['cloud'] == c)} |")
    L.append("")

    for c in ("aws", "gcp", "azure", "all"):
        cs = [s for s in suites if s["cloud"] == c]
        cf = [f for f in findings if f["cloud"] == c]
        if c == "all" and not cs:
            continue
        L += [f'<a id="{c}"></a>', f"## {NAMES[c]}", ""]
        if cs:
            L += ["| Status | Suite | Target | Kind | Passed | Failed | Time (s) |", "|---|---|---|---|---|---|---|"]
            for s in sorted(cs, key=lambda s: (s["status"] == "pass", s["id"])):
                L.append(f"| {'✅' if s['status'] == 'pass' else '❌'} | `{md(s['id'])}` | {md(s['target'])} | "
                         f"{md(s['kind'])} | {s.get('passed') or 0} | {s.get('failed') or 0} | {md(s.get('duration_s'))} |")
            L.append("")
            for s in cs:
                if s["status"] != "pass" and s.get("tail"):
                    L += [f"<details><summary>❌ <code>{md(s['id'])}</code> log</summary>", "", "```",
                          s["tail"].replace("```", "'''"), "```", "", "</details>", ""]
        if c != "all":
            by_svc: dict[tuple, list] = {}
            for f in cf:
                by_svc.setdefault((f["target"], f["service"]), []).append(f)
            L += [f"**UI findings: {len(cf)}**", ""]
            if not by_svc:
                L += ["No open UI findings.", ""]
            for (t, svc), fs in sorted(by_svc.items(), key=lambda kv: -len(kv[1])):
                L += [f"<details><summary><b>{md(svc)}</b> ({md(t)}) — {len(fs)} finding(s)</summary>", "",
                      "| Problem | Tab | Detail |", "|---|---|---|"]
                L += [f"| `{md(f['type'])}` | {md(f.get('tab'))} | {md(f['detail'])} |" for f in fs]
                L += ["", "</details>", ""]

    L += ["## New features since the last run", ""]
    if not d.get("baseline"):
        L += ["First inventory taken this run; new features are reported from the next run.", ""]
    elif not d["new"]:
        L += ["None.", ""]
    else:
        L += ["| Target | Cloud | Service | Kind | Feature | SDK test |", "|---|---|---|---|---|---|"]
        L += [f"| {md(n['target'])} | {NAMES.get(n['cloud'], n['cloud'])} | {md(n['service'])} | {md(n['kind'])} | {md(n['name'])} | "
              f"{'—' if n.get('tested') is None else ('✅' if n['tested'] else '❌')} |" for n in d["new"][:100]]
        L.append("")
    L += ["## Nano ↔ offline parity gaps", ""]
    L += [f"- {NAMES.get(p['cloud'], p['cloud'])} {md(p['kind'])} **{md(p['name'])}** ({md(p['service'])}): only in {md(p['only_in'])}"
          for p in d["parity"][:60]] or ["None: both targets expose the same services, tabs and operations."]
    L += ["", f"## SDK operations without a test ({d['ops']['untested']} of {d['ops']['total']})", ""]
    by_engine = {}
    for o in d["untested_ops"]:
        by_engine.setdefault((o["target"], o["cloud"], o["service"]), []).append(o["name"])
    for (t, c, eng), names in sorted(by_engine.items()):
        L.append(f"<details><summary>{NAMES.get(c, c)} · <code>{md(eng)}</code> ({md(t)}) — {len(names)}</summary>\n\n{', '.join(sorted(names))}\n\n</details>")
    L += ["", "## Last 24 runs", "", "| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |", "|---|---|---|---|---|---|---|"]
    for h in reversed(d["history"][-24:]):
        L.append(f"| {md(h.get('at'))} | {h.get('suites_green')}/{h.get('suites_total')} | {h.get('checks_passed')} | "
                 f"{h.get('checks_failed')} | {h.get('ui_findings')} | {h.get('api_coverage_pct')}% | {md(h.get('agent'))} |")
    L += ["", "Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`."]
    return "\n".join(L) + "\n"


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
             "ui_findings": len(findings), "agent": agent.splitlines()[0][:200] if agent else "",
             "new_features": len(feats.get("new", [])), "parity_gaps": len(feats.get("parity", [])),
             "ops_tested_pct": round(100 * (1 - feats.get("ops_untested", 0) / feats["ops_total"]), 1) if feats.get("ops_total") else 0.0}
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
        "ops": {"total": feats.get("ops_total", 0), "untested": feats.get("ops_untested", 0)},
        "baseline": feats.get("baseline", False),
        "new": [{k: f.get(k) for k in ("target", "cloud", "service", "kind", "name", "path", "tested")} for f in feats.get("new", [])][:2000],
        "removed": [{k: f.get(k) for k in ("target", "cloud", "service", "kind", "name")} for f in feats.get("removed", [])][:500],
        "parity": feats.get("parity", [])[:2000],
        "untested_ops": [{k: f.get(k) for k in ("target", "cloud", "service", "name")} for f in feats.get("untested_ops", [])],
        "uncovered": feats.get("uncovered", [])[:500],
    }
    template = open(os.path.join(HERE, "report.html"), encoding="utf-8").read()
    # Embedded as JSON inside <script type="application/json">; escape "</" so a
    # finding's text can never close the script tag.
    blob = json.dumps(data).replace("</", "<\\/")
    page = template.replace("__REPORT_DATA__", blob)

    os.makedirs(SITE, exist_ok=True)
    open(os.path.join(SITE, "index.html"), "w", encoding="utf-8").write(page)
    open(os.path.join(SITE, "README.md"), "w", encoding="utf-8").write(markdown(data, entry))
    json.dump(res, open(os.path.join(SITE, "results.json"), "w"), indent=1)
    json.dump(history, open(os.path.join(SITE, "history.json"), "w"), indent=1)
    json.dump(ui, open(os.path.join(SITE, "ui-findings.json"), "w"), indent=1)
    # Next run diffs its feature inventory against this one.
    inv = os.path.join(OUT, "inventory.json")
    if os.path.exists(inv):
        open(os.path.join(SITE, "inventory.json"), "w").write(open(inv).read())
    print(f"report written: {entry['suites_green']}/{len(suites)} suites green, "
          f"{len(findings)} UI findings, API coverage {api_cov}%")


if __name__ == "__main__":
    main()
