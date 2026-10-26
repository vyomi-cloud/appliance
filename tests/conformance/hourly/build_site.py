#!/usr/bin/env python3
"""Render the public conformance page from the hourly run's outputs.

Reads out/results.json, out/ui-*.json, out/new_features.json, out/agent_summary.md
and the previously published history.json; writes site/index.html,
site/results.json and site/history.json.

    python3 tests/conformance/hourly/build_site.py --history prev/history.json
"""
from __future__ import annotations

import argparse
import html
import json
import os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SITE = os.path.join(HERE, "site")


def load(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def spark(values: list[float], w=360, h=56) -> str:
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pts = " ".join(f"{i * w / (len(values) - 1):.1f},{h - 4 - (v - lo) / span * (h - 8):.1f}" for i, v in enumerate(values))
    return f'<svg viewBox="0 0 {w} {h}" class="spark" role="img" aria-label="trend"><polyline points="{pts}" /></svg>'


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
    green = sum(1 for s in suites if s["status"] == "pass")
    checks_pass = sum(s.get("passed", 0) for s in suites)
    checks_fail = sum(s.get("failed", 0) for s in suites)
    ui_rows = {t: d.get("services", []) for t, d in ui.items()}
    ui_clean = {t: sum(1 for r in rows if r.get("status") == "ok") for t, rows in ui_rows.items()}
    findings = [(t, r, f) for t, rows in ui_rows.items() for r in rows for f in r.get("findings", [])]
    by_type = Counter(f["type"] for _, _, f in findings)
    rt, ru = feats.get("routes_total", 0), feats.get("routes_uncovered", 0)
    api_cov = round(100 * (rt - ru) / rt, 1) if rt else 0.0

    entry = {"at": res.get("at"), "commit": res.get("commit", "")[:12], "suites_green": green, "suites_total": len(suites),
             "checks_passed": checks_pass, "checks_failed": checks_fail, "api_coverage_pct": api_cov,
             "ui_clean_nano": ui_clean["nano"], "ui_total_nano": len(ui_rows["nano"]),
             "ui_clean_offline": ui_clean["offline"], "ui_total_offline": len(ui_rows["offline"]),
             "ui_findings": len(findings), "agent": agent.splitlines()[0][:200] if agent else ""}
    history = (history + [entry])[-720:]   # 30 days of hourly runs

    # Matrix: target × kind → cloud cells
    matrix = defaultdict(dict)
    for s in suites:
        matrix[(s["target"], s["kind"])][s["cloud"]] = s
    clouds = ["aws", "gcp", "azure", "all"]

    def cell(s):
        if not s:
            return '<td class="na">not yet</td>'
        cls = "ok" if s["status"] == "pass" else "bad"
        return f'<td class="{cls}" title="{esc(s["id"])}">{s["passed"]}✓ {s["failed"]}✗</td>'

    rows_html = "".join(
        f"<tr><th>{esc(t)}</th><th>{esc(k)}</th>{''.join(cell(matrix[(t, k)].get(c)) for c in clouds)}</tr>"
        for (t, k) in sorted(matrix))
    find_html = "".join(
        f"<tr><td>{esc(t)}</td><td>{esc(r['cloud'])}</td><td>{esc(r['service'])}</td><td>{esc(f.get('tab', ''))}</td>"
        f"<td><span class=tag>{esc(f['type'])}</span></td><td>{esc(f['detail'])}</td></tr>"
        for t, r, f in findings[:300])
    fail_html = "".join(
        f"<details><summary><b>{esc(s['id'])}</b> — {s['failed']} failed</summary><pre>{esc(s.get('tail', ''))}</pre></details>"
        for s in suites if s["status"] != "pass")
    new_html = "".join(
        f"<li>{'✅' if n.get('covered') else '⏳'} {esc(n.get('kind'))}: {esc(n.get('method', ''))} {esc(n.get('path') or n.get('file'))}</li>"
        for n in feats.get("new", [])[:100]) or "<li>No new features since the last run.</li>"
    hist_html = "".join(
        f"<tr><td>{esc(h['at'])}</td><td>{h['suites_green']}/{h['suites_total']}</td><td>{h['checks_passed']}</td>"
        f"<td>{h['ui_clean_nano']}/{h['ui_total_nano']}</td><td>{h['ui_clean_offline']}/{h['ui_total_offline']}</td>"
        f"<td>{h['api_coverage_pct']}%</td><td>{esc(h.get('agent', ''))}</td></tr>"
        for h in reversed(history[-48:]))
    type_html = " ".join(f'<span class=tag>{esc(k)} · {v}</span>' for k, v in by_type.most_common())

    # Cloud-wise report: one card per cloud with its suites, UI health on both
    # targets, and its open findings.
    names = {"aws": "AWS", "gcp": "GCP", "azure": "Azure"}
    cloud_html = ""
    for c, label in names.items():
        cs = [s for s in suites if s["cloud"] == c]
        cg = sum(1 for s in cs if s["status"] == "pass")
        cp = sum(s.get("passed", 0) for s in cs)
        cf = sum(s.get("failed", 0) for s in cs)
        ui_line = " · ".join(
            f"{t.capitalize()} UI {sum(1 for r in ui_rows[t] if r['cloud'] == c and r.get('status') == 'ok')}/"
            f"{sum(1 for r in ui_rows[t] if r['cloud'] == c)} clean" for t in ("nano", "offline"))
        cfind = [(t, r, f) for t, r, f in findings if r["cloud"] == c]
        ctypes = Counter(f["type"] for _, _, f in cfind)
        items = "".join(
            f"<li><b>{esc(r['service'])}</b>{(' › ' + esc(f['tab'])) if f.get('tab') else ''} "
            f"<span class=mut>({esc(t)})</span>: <span class=tag>{esc(f['type'])}</span> {esc(f['detail'])}</li>"
            for t, r, f in cfind[:25])
        more = f"<li class=mut>…and {len(cfind) - 25} more (see table below)</li>" if len(cfind) > 25 else ""
        cloud_html += f"""<div class="cloud"><h3>{label}</h3>
<div class="mut">Suites {cg}/{len(cs)} green · {cp} checks passing, {cf} failing · {ui_line}</div>
<div>{' '.join(f'<span class=tag>{esc(k)} · {v}</span>' for k, v in ctypes.most_common())}</div>
<ul>{items or '<li>No open UI findings.</li>'}{more}</ul></div>"""

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vyomi Conformance</title>
<style>
:root{{--bg:#f7f8fa;--fg:#14171f;--mut:#5b6472;--card:#fff;--line:#e3e6ec;--ok:#0f7b3f;--okbg:#e6f6ec;--bad:#b42318;--badbg:#fdecea;--acc:#2563eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d1117;--fg:#e6edf3;--mut:#9aa4b2;--card:#161b22;--line:#2b323c;--ok:#3fb950;--okbg:#12261a;--bad:#f85149;--badbg:#2d1414;--acc:#58a6ff;color-scheme:dark}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:28px 16px 60px}}
h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:17px;margin:32px 0 10px}}
.mut{{color:var(--mut)}} .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:20px}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.kpi b{{display:block;font-size:24px}} .scroll{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
td.ok{{background:var(--okbg);color:var(--ok);font-weight:600}} td.bad{{background:var(--badbg);color:var(--bad);font-weight:600}} td.na{{color:var(--mut)}}
.tag{{display:inline-block;padding:1px 8px;border-radius:999px;border:1px solid var(--line);font-size:12px;margin:2px 2px 2px 0}}
pre{{white-space:pre-wrap;font-size:12px;background:var(--bg);padding:10px;border-radius:8px;overflow-x:auto}}
details{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:6px 0}}
.spark{{width:100%;max-width:360px;height:56px}} .spark polyline{{fill:none;stroke:var(--acc);stroke-width:2}}
ul{{padding-left:18px}}
.cloud{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:10px 0}}
.cloud h3{{margin:0 0 4px;font-size:16px}} .cloud li{{margin:3px 0}}
</style></head><body><div class="wrap">
<h1>Vyomi Conformance</h1>
<div class="mut">Hourly run {esc(res.get('at'))} · commit <code>{esc(res.get('commit', '')[:12])}</code> · Nano (in-browser) + offline appliance · AWS, GCP, Azure</div>
<div class="kpis">
 <div class="kpi"><span class="mut">Suites green</span><b>{green}/{len(suites)}</b></div>
 <div class="kpi"><span class="mut">Checks passing</span><b>{checks_pass}</b><span class="mut">{checks_fail} failing</span></div>
 <div class="kpi"><span class="mut">Nano UI services clean</span><b>{ui_clean['nano']}/{len(ui_rows['nano'])}</b></div>
 <div class="kpi"><span class="mut">Offline UI services clean</span><b>{ui_clean['offline']}/{len(ui_rows['offline'])}</b></div>
 <div class="kpi"><span class="mut">API routes with tests</span><b>{api_cov}%</b><span class="mut">{rt - ru}/{rt}</span></div>
</div>
<h2>By cloud</h2>{cloud_html}
<h2>Checks passing over time</h2>{spark([h['checks_passed'] for h in history])}
<h2>Agent this run</h2><pre>{esc(agent or 'No agent summary for this run.')}</pre>
<h2>Coverage matrix</h2><div class="scroll"><table><tr><th>Target</th><th>Kind</th><th>AWS</th><th>GCP</th><th>Azure</th><th>Cross-cloud</th></tr>{rows_html}</table></div>
<h2>Open UI findings ({len(findings)})</h2><div>{type_html}</div>
<div class="scroll"><table><tr><th>Target</th><th>Cloud</th><th>Service</th><th>Tab</th><th>Type</th><th>Detail</th></tr>{find_html or '<tr><td colspan=6>None. Every crawled service is clean.</td></tr>'}</table></div>
<h2>Failing suites</h2>{fail_html or '<p>None.</p>'}
<h2>New features since last run</h2><ul>{new_html}</ul>
<h2>Last 48 runs</h2><div class="scroll"><table><tr><th>Run</th><th>Suites</th><th>Checks</th><th>Nano UI</th><th>Offline UI</th><th>API cov.</th><th>Agent</th></tr>{hist_html}</table></div>
</div></body></html>"""

    os.makedirs(SITE, exist_ok=True)
    open(os.path.join(SITE, "index.html"), "w").write(page)
    json.dump(res, open(os.path.join(SITE, "results.json"), "w"), indent=1)
    json.dump(history, open(os.path.join(SITE, "history.json"), "w"), indent=1)
    json.dump({t: d for t, d in ui.items()}, open(os.path.join(SITE, "ui-findings.json"), "w"), indent=1)
    print(f"site written: {green}/{len(suites)} suites green, {len(findings)} UI findings, API coverage {api_cov}%")


if __name__ == "__main__":
    main()
