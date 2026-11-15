"""Static HTML report (no build step, no external assets). `python report.py results/e2e-result.json > report.html` or imported by run_e2e."""
import html, json, sys

COL = {"PASS": "#1a7f37", "BLOCKED": "#9a6700", "FAIL": "#cf222e"}


def render(doc):
    e = html.escape
    rows = []
    for c in doc["components"]:
        steps = "".join(f"<tr><td class='s' style='color:{COL[s['status']]}'>{s['status']}</td><td>{e(s['name'])}</td><td class='d'>{e(str(s['detail']))}</td><td>{s['secs']}s</td></tr>" for s in c["steps"])
        blk = f" <span class='by'>blocked by {e(', '.join(c['blocked_by']))}</span>" if c["blocked_by"] else ""
        rows.append(f"<details {'open' if c['status'] != 'PASS' else ''}><summary><b>{c['id']:02d}</b> {e(c['name'])} "
                    f"<span class='pill' style='background:{COL[c['status']]}'>{c['status']}</span> {c['passed']}/{c['total']}{blk}</summary><table>{steps}</table></details>")
    a = doc.get("agent") or {}
    cites = "".join(f"<li>[{x['n']}] <code>{e(x['source'])}</code><br><small>{e(x['text'])}</small></li>" for x in (a.get("citations") or []))
    tools = "".join(f"<li><code>{e(t['tool'])}</code> via {e(t['via'])}</li>" for t in (a.get("tools") or []))
    t = doc["totals"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Facilities agent e2e report</title><style>
:root{{--bg:#fff;--fg:#1f2328;--mut:#656d76;--bd:#d0d7de}}@media(prefers-color-scheme:dark){{:root{{--bg:#0d1117;--fg:#e6edf3;--mut:#8d96a0;--bd:#30363d}}}}
body{{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);max-width:980px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px}}h2{{font-size:17px;margin-top:28px}}details{{border:1px solid var(--bd);border-radius:8px;margin:8px 0;padding:8px 12px}}
summary{{cursor:pointer}}table{{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}}td{{padding:3px 6px;border-top:1px solid var(--bd);vertical-align:top}}
.s{{font-weight:600;width:70px}}.d{{color:var(--mut)}}.pill{{color:#fff;border-radius:10px;padding:1px 9px;font-size:12px;margin:0 6px}}.by{{color:var(--mut);font-size:12px}}
.tot span{{display:inline-block;margin-right:14px;font-weight:600}}pre{{background:rgba(127,127,127,.12);padding:12px;border-radius:8px;overflow:auto;font-size:12px}}code{{font-size:12px}}</style></head><body>
<h1>Enterprise Facilities agent: end-to-end report</h1>
<p class="d">Endpoint <code>{e(doc['endpoint'])}</code> &middot; {e(doc['when'])} &middot; real AWS SDK (boto3) calls, no mocks</p>
<p class="tot"><span style="color:{COL['PASS']}">{t['PASS']} PASS</span><span style="color:{COL['BLOCKED']}">{t['BLOCKED']} BLOCKED</span><span style="color:{COL['FAIL']}">{t['FAIL']} FAIL</span></p>
<h2>The agent run</h2><p><b>User:</b> {e(str(a.get('user')))}<br><b>Question:</b> {e(str(a.get('question')))}<br><b>Route:</b> {e(str(a.get('route')))} (by {'model' if a.get('llm_used') else 'keyword rules, no model reachable'})</p>
<ul>{tools}</ul><p><b>Answer:</b> {e(str(a.get('answer')))}</p><ol>{cites}</ol><p><b>Work order after approval:</b> {e(str(doc.get('work_order')))}</p>
<h2>13 components</h2>{''.join(rows)}<h2>Transcript</h2><pre>{e(doc['transcript'])}</pre></body></html>"""


if __name__ == "__main__":
    print(render(json.load(open(sys.argv[1]))))
