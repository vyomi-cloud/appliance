#!/usr/bin/env python3
"""Service pipeline page: every AWS / GCP / Azure service released or in the
build queue, with its gate checks, release, and hand-off status to the hourly
conformance run and the hourly upstream watcher. Published as README.md on the
service-pipeline branch (pipeline-status.yml).

Sources: services/registry.json + services/catalog.json (main), new-service
issues + expansion PRs (gh), each expansion/* branch (static gate run against
it), service-gate runs, the conformance-report branch (latest hourly results)
and the upstream-state branch (what the watcher tracks, open drift issues).

    GH_TOKEN=... python3 tests/conformance/expansion/build_pipeline_page.py OUT_DIR
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
REPO = os.environ.get("GITHUB_REPOSITORY", "vyomi-cloud/appliance")
GH = f"https://github.com/{REPO}"
CLOUDS = (("aws", "AWS"), ("gcp", "GCP"), ("azure", "Azure"))
# Static gate check → grid column
COLS = [("Engine", ["engine exists in core/"]),
        ("Nano", ["Nano copy is byte-identical (wasm/core/)", "engine listed in wasm/build_cores.py"]),
        ("Console", ["service in the Nano console catalog (wasm/fixtures)"]),
        ("Java", ["has a offline sdk-java test bed"]),
        ("Go", ["has a offline sdk-go test bed"]),
        ("CLI", ["has a offline cli test bed"]),
        ("PW offline", ["has a offline ui test bed"]),
        ("PW Nano", ["has a nano ui test bed"])]


def sh(*cmd: str, cwd: str = ROOT) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else ""


def gh_json(*args: str):
    out = sh("gh", *args)
    try:
        return json.loads(out) if out.strip() else []
    except ValueError:
        return []


def raw(branch: str, path: str):
    try:
        url = f"https://raw.githubusercontent.com/{REPO}/{branch}/{path}"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "vyomi-pipeline"}), timeout=60) as r:
            return json.loads(r.read())
    except Exception:
        return None


def key_of(upstream_id: str) -> str:
    return upstream_id.split("/")[0].replace("_", "-")


def static_gate(branch: str, manifest: str) -> dict[str, tuple[bool, str]]:
    """Run gate.py --static against the branch's tree; {check name: (ok, detail)}."""
    wt = tempfile.mkdtemp(prefix="gate-")
    if subprocess.run(["git", "worktree", "add", "-q", "--detach", wt, f"origin/{branch}"], cwd=ROOT,
                      capture_output=True).returncode:
        return {}
    try:
        if not os.path.exists(os.path.join(wt, manifest)):
            return {}
        env = dict(os.environ, GATE_ROOT=wt, OUT=os.path.join(wt, ".gate-out"))
        p = subprocess.run([sys.executable, os.path.join(HERE, "gate.py"), os.path.join(wt, manifest), "--static"],
                           cwd=wt, env=env, capture_output=True, text=True, timeout=600)
        res = {}
        for line in p.stdout.splitlines():
            m = re.match(r"(PASS|FAIL): (.+?)(?: — (.*))?$", line)
            if m:
                res[m.group(2)] = (m.group(1) == "PASS", m.group(3) or "")
        return res
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=ROOT, capture_output=True)


def main() -> int:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "out", "pipeline")
    os.makedirs(out_dir, exist_ok=True)
    reg = json.load(open(os.path.join(ROOT, "services", "registry.json")))["services"]
    cat = json.load(open(os.path.join(ROOT, "services", "catalog.json")))
    hourly = raw("conformance-report", "results.json") or {}
    ui = raw("conformance-report", "ui-findings.json") or {}
    up_state = raw("upstream-state", "state.json") or {}
    tracked = json.load(open(os.path.join(ROOT, "tests", "conformance", "upstream", "tracked.json")))
    suite_res = {s["id"]: s for s in hourly.get("suites", [])}
    bk = json.load(open(os.path.join(HERE, "backends.json")))

    def backend_cell(cloud: str, upstream: str, manifest_backend: dict | None) -> str:
        b = manifest_backend or {}
        if b.get("kind") == "in-process" or (not b and upstream in bk["in_process"].get(cloud, [])):
            return "in-process"
        name = b.get("name") or next((n for n, x in bk["shared"].items() if f"{cloud}:{upstream}" in x.get("for", [])), None)
        if not name:
            return "to choose"
        x = bk["shared"].get(name, {})
        tier = b.get("tier") or x.get("tier", "")
        bits = [name] + ([f"{x['idle_mb']} MB"] if x.get("idle_mb") else []) + ([tier.capitalize()] if tier else [])
        return " · ".join(bits) + ("" if b else " (default)")

    def real_backend_cell(cloud: str, upstream: str) -> str:
        """The backend the service should have: the shared default for its
        upstream id, else in-process (the engine itself is the backend)."""
        name = next((n for n, x in bk["shared"].items() if f"{cloud}:{upstream}" in x.get("for", [])), None)
        if not name:
            return "in-process" if upstream in bk["in_process"].get(cloud, []) else "—"
        x = bk["shared"][name]
        extra = ["in-process"] if x.get("kind") == "in-process" else ([x["tier"].capitalize()] if x.get("tier") else [])
        comp = [f"+ {n} {y.get('role', 'agent')}" for n, y in bk["shared"].items() if f"{cloud}:{upstream}" in y.get("agent_for", [])]
        return " · ".join([name] + extra + comp)

    LIVE_ICON = {"real": "✅", "partial": "🟡", "api": "⚪"}

    def wired_cell(cloud: str, upstream: str) -> str:
        x = bk.get("live", {}).get(f"{cloud}:{upstream}")
        if not x:
            return "not audited"
        return f"{LIVE_ICON.get(x['state'], '')} {x['today']}".replace("|", "/")
    # Nano ↔ offline feature parity from the hourly inventory (routes are an
    # offline-only concept, so they're left out).
    feats: dict = {}
    for x in (raw("conformance-report", "inventory.json") or {}).get("features", []):
        if x.get("kind") != "route":
            feats.setdefault((x["target"], x["cloud"], x["service"]), set()).add((x["kind"], x["name"]))

    def parity(cloud: str, svc: str) -> tuple[int, int, int]:
        o, n = feats.get(("offline", cloud, svc), set()), feats.get(("nano", cloud, svc), set())
        return len(o | n), len(o - n), len(n - o)
    ui_res = {(t, s["cloud"], s["service"]): s for t in ("offline", "nano") for s in (ui.get(t) or {}).get("services", [])}

    issues = gh_json("issue", "list", "-R", REPO, "--label", "new-service", "--state", "all", "--limit", "500",
                     "--json", "number,state,labels,body,title")
    by_key = {}
    for it in issues:
        m = re.search(r"<!-- expansion: cloud=(\w+) key=([\w.-]+)", it.get("body") or "")
        if m:
            by_key[(m.group(1), m.group(2))] = it
    prs = {p["headRefName"]: p for p in gh_json("pr", "list", "-R", REPO, "--state", "all", "--limit", "300",
                                                 "--json", "number,state,headRefName,mergedAt,url")
           if p["headRefName"].startswith("expansion/")}
    drift = gh_json("issue", "list", "-R", REPO, "--label", "upstream-drift", "--state", "open", "--limit", "500",
                    "--json", "number,body")
    sh("git", "fetch", "-q", "origin", "+refs/heads/expansion/*:refs/remotes/origin/expansion/*")
    branches = {b.strip().removeprefix("origin/") for b in sh("git", "branch", "-r", "--list", "origin/expansion/*").split()}

    def live_gate(branch: str) -> str:
        runs = gh_json("run", "list", "-R", REPO, "--workflow", "service-gate.yml", "--branch", branch, "-L", "1",
                       "--json", "conclusion,status,url")
        if not runs:
            return "—"
        r = runs[0]
        if r["status"] != "completed":
            return f"[⏳ running]({r['url']})"
        return f"[{'✅ passed' if r['conclusion'] == 'success' else '❌ ' + (r['conclusion'] or 'failed')}]({r['url']})"

    def upstream_cell(cloud: str, upstream: str, svc_names: list[str]) -> str:
        lists = {"aws": tracked["aws"]["botocore"], "gcp": tracked["gcp"]["discovery"], "azure": tracked["azure"]["specs"]}
        az = {"Microsoft.Compute": "compute", "Microsoft.Storage": "storage", "Microsoft.Sql": "sql",
              "Microsoft.ServiceBus": "servicebus", "Microsoft.DocumentDB": "cosmos-db", "Microsoft.Web": "web",
              "Microsoft.ApiManagement": "apimanagement", "Microsoft.Network": "network", "Microsoft.EventGrid": "eventgrid",
              "Microsoft.KeyVault": "keyvault", "Microsoft.Authorization": "authorization"}
        uid = az.get(upstream, upstream) if cloud == "azure" else upstream
        if uid not in lists.get(cloud, []):
            return "⬜ not watched"
        ops = len(((up_state.get(cloud) or {}).get(uid) or {}).get("ops") or {}) if cloud in ("aws", "gcp") else 0
        n = sum(1 for d in drift if f"`{uid}`" in (d.get("body") or "") or any(f"`{s}`" in (d.get("body") or "") for s in svc_names))
        cell = "👁 watched" + (f" ({ops} ops)" if ops else "")
        if n:
            cell += f" · [⚠️ {n} drift]({GH}/issues?q=is%3Aopen+label%3Aupstream-drift+{uid})"
        return cell

    def hourly_cell(cloud: str, name: str, suites: list[str]) -> str:
        parts = []
        for t in ("offline", "nano"):
            r = ui_res.get((t, cloud, name))
            if r:
                n = len(r.get("findings", []))
                parts.append(f"UI {t} {'✅' if n == 0 else f'⚠️ {n}'}")
        for sid in suites:
            r = suite_res.get(sid)
            if r:
                parts.append(f"{sid.split('-', 1)[1]} {'✅' if r['status'] == 'pass' else '❌'}")
        if not parts:
            return "✅ handed off (awaiting next hourly run)" if suites else "—"
        return " · ".join(parts)

    # Console implementation (hourly crawl `surfaces`): live / partial /
    # static / unimplemented per service page, create, detail and tab.
    STATES = ("live", "partial", "static", "unimplemented")

    def surf(target: str, cloud: str, svc: str | None = None) -> list:
        return [x for r in (ui.get(target) or {}).get("services", []) if r["cloud"] == cloud and (svc is None or r["service"] == svc)
                for x in r.get("surfaces", [])]

    def console_cell(cloud: str, svc: str) -> str:
        parts = []
        for t, lbl in (("offline", "off"), ("nano", "Nano")):
            xs = surf(t, cloud, svc)
            if xs:
                live = sum(x["state"] == "live" for x in xs)
                parts.append(f"{lbl} {'✅' if live == len(xs) else '🧩'} {live}/{len(xs)}")
        return " · ".join(parts) or "—"

    def par_cell(cloud: str, svc: str) -> str:
        tot, off_only, nano_only = parity(cloud, svc)
        if not tot:
            return "—"
        if not off_only and not nano_only:
            return f"✅ {tot}/{tot}"
        return f"⚠️ {tot - off_only - nano_only}/{tot}" + (f" · {off_only} offline-only" if off_only else "") + \
            (f" · {nano_only} Nano-only" if nano_only else "")

    # ---- collect --------------------------------------------------------
    data = {}
    for cloud, label in CLOUDS:
        released = [s for s in reg if s["cloud"] == cloud and s.get("status") == "released"]
        released_keys = {s["key"] for s in released} | {key_of(s.get("upstream") or s["key"]) for s in released}
        queue = [s for s in cat["services"] if s["cloud"] == cloud and s["priority"] in ("P1", "P2")
                 and s["status"] != "released" and key_of(s["id"]) not in released_keys]
        queue.sort(key=lambda s: (s["priority"], s["name"].lower()))
        rest = sorted((r for r in cat["services"] if r["cloud"] == cloud and r["priority"] == "P3"
                       and r["status"] != "released" and key_of(r["id"]) not in released_keys), key=lambda r: r["id"])
        rel_rows = []
        for s in released:
            issues_n = []
            for t in ("offline", "nano"):
                r = ui_res.get((t, cloud, s["name"]))
                issues_n.append(str(len(r.get("findings", []))) if r else "–")
            up = upstream_cell(cloud, s.get("upstream") or s["key"], [s["key"], s["name"]])
            up = "⬜ not watched" if up.startswith("⬜") else ("⚠️ " + up.split("⚠️ ")[1] if "⚠️" in up else "✅ watched")
            ver = s.get("released_in", "")
            rel_rows.append({"name": s["name"], "console": console_cell(cloud, s["name"]).replace("off ", "").replace("Nano ", ""),
                             "real": real_backend_cell(cloud, s.get("upstream") or s["key"]),
                             "wired": wired_cell(cloud, s.get("upstream") or s["key"]),
                             "issues": " · ".join(issues_n), "upstream": up,
                             "release": f"[v{ver}]({GH}/releases/tag/v{ver})" if re.match(r"^\d", ver) else "before gate"})
        moving, queued = [], []
        for s in queue:
            k = key_of(s["id"])
            branch = f"expansion/{cloud}-{k}"
            it = by_key.get((cloud, k))
            labels = {l["name"] for l in (it or {}).get("labels", [])}
            pr = prs.get(branch)
            name = s["name"] if s["name"] != s["id"] else s["id"]
            link = f"[#{it['number']}]({GH}/issues/{it['number']})" if it else ""
            if pr and pr["state"] == "MERGED":
                stage = "🚀 Releasing"
            elif "blocked" in labels:
                stage = "⛔ Blocked"
            elif pr and pr["state"] == "OPEN":
                stage = f"🔍 In gate ([PR #{pr['number']}]({pr['url']}))"
            elif branch in branches:
                stage = "🛠 Building"
            elif it and it["state"] == "OPEN":
                stage = "📋 Queued"
            else:
                stage = "Not filed"
            mb = None
            if branch in branches:
                try:
                    mb = json.loads(sh("git", "show", f"origin/{branch}:services/manifests/{cloud}-{k}.json") or "{}").get("backend")
                except ValueError:
                    mb = None
            row = {"name": name, "link": link, "priority": s["priority"], "stage": stage,
                   "backend": backend_cell(cloud, s["id"], mb).replace(" (default)", ""),
                   "real": real_backend_cell(cloud, s["id"])}
            if stage.startswith(("📋", "Not")):
                queued.append(row)
                continue
            gate = static_gate(branch, f"services/manifests/{cloud}-{k}.json") if branch in branches else {}
            ok = sum(1 for v in gate.values() if v[0])
            row["checks"] = f"{ok}/{len(gate)}" if gate else "no manifest yet"
            row["missing"] = [n for n, v in gate.items() if not v[0]]
            row["gate"] = gate
            row["live"] = live_gate(branch) if pr else ""
            moving.append(row)
        con = {}
        notlive = []
        for t in ("offline", "nano"):
            xs = surf(t, cloud)
            con[t] = {st: sum(x["state"] == st for x in xs) for st in STATES} | {"total": len(xs)}
            for r in (ui.get(t) or {}).get("services", []):
                if r["cloud"] == cloud:
                    notlive += [(r["service"], t, x) for x in r.get("surfaces", []) if x["state"] != "live"]
        gaps = []
        for svc in sorted({k[2] for k in feats if k[1] == cloud}):
            tot, off_only, nano_only = parity(cloud, svc)
            if off_only or nano_only:
                gaps.append((svc, off_only, nano_only))
        data[cloud] = {"label": label, "released": rel_rows, "moving": moving, "queued": queued, "rest": rest,
                       "upstream": sum(1 for r in cat["services"] if r["cloud"] == cloud), "console": con,
                       "notlive": notlive, "gaps": gaps}
    totals = {c: {"released": len(d["released"]), "queue": len(d["moving"]) + len(d["queued"]),
                  "building": sum(r["stage"].startswith("🛠") for r in d["moving"]),
                  "in_gate": sum(r["stage"].startswith(("🔍", "🚀")) for r in d["moving"]),
                  "upstream": d["upstream"]} for c, d in data.items()}

    # ---- render ---------------------------------------------------------
    def pct(c: dict) -> str:
        return f"{100 * c['live'] // c['total']}%" if c.get("total") else "not measured yet"

    def con_total(t: str) -> dict:
        agg = {"total": 0, **{st: 0 for st in STATES}}
        for d in data.values():
            for k in agg:
                agg[k] += d["console"][t].get(k, 0)
        return agg

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    T = lambda k: sum(v[k] for v in totals.values())
    moving_all = [(d["label"], r) for d in data.values() for r in d["moving"]]
    building = [f"{r['name']} ({lbl}, {r['checks']} checks)" for lbl, r in moving_all if r["stage"].startswith("🛠")]
    gating = [f"{r['name']} ({lbl})" for lbl, r in moving_all if r["stage"].startswith(("🔍", "🚀"))]
    passing = sum(1 for r in suite_res.values() if r["status"] == "pass")
    drift_n = len(drift)
    off, nano = con_total("offline"), con_total("nano")
    md = ["# Vyomi service pipeline", "",
          f"_Updated {now} · refreshes after every pipeline run_", "",
          "## At a glance", "",
          f"- **Released:** {T('released')} services (AWS {totals['aws']['released']} · GCP {totals['gcp']['released']} · "
          f"Azure {totals['azure']['released']}) of {T('upstream'):,} the clouds publish",
          f"- **Building now:** {', '.join(building) or 'nothing'}",
          f"- **In the gate / releasing:** {', '.join(gating) or 'nothing'}",
          f"- **Queued:** {sum(len(d['queued']) for d in data.values())} services (P1 first, then P2)",
          f"- **Consoles really implemented:** offline {pct(off)} · Nano {pct(nano)}",
          f"- **Hourly tests:** {passing} of {len(suite_res)} suites passing" + (f" (run {hourly['at'][11:16]} UTC)" if hourly.get("at") else ""),
          f"- **Upstream watch:** {drift_n} open change{'s' if drift_n != 1 else ''} from the real clouds to adopt", "",
          "## By cloud", "",
          "| Cloud | Released | Building | In gate | Queued | Console live (offline · Nano) |", "|---|---|---|---|---|---|"]
    for c, d in data.items():
        md.append(f"| {d['label']} | {totals[c]['released']} | {totals[c]['building']} | {totals[c]['in_gate']} | {len(d['queued'])} | "
                  f"{pct(d['console']['offline'])} · {pct(d['console']['nano'])} |")

    md += ["", "## In progress", ""]
    if moving_all:
        md += ["| Service | Cloud | Stage | Checks | Real backend | Built with | Still missing |", "|---|---|---|---|---|---|---|"]
        for lbl, r in moving_all:
            miss = "; ".join(r["missing"][:3]) + (f" (+{len(r['missing']) - 3} more)" if len(r["missing"]) > 3 else "")
            md.append(f"| {r['name']} {r['link']} | {lbl} | {r['stage']} | {r['checks']} | {r['real']} | {r['backend']} | {miss or '—'} |")
    else:
        md.append("- Nothing is being built right now.")

    md += ["", "## Released services", "",
           "- **Console live:** parts of the console that are really implemented, offline · Nano",
           "- **UI issues:** problems the latest hourly crawl found, offline · Nano",
           "- **Real backend:** what the service should run on ([backends.json]"
           f"({GH}/blob/main/tests/conformance/expansion/backends.json)) · **Wired today:** ✅ real · 🟡 partial · ⚪ management API only", ""]
    for c, d in data.items():
        md += [f"### {d['label']}", "", "| Service | Real backend | Wired today | Console live | UI issues | Upstream | Release |",
               "|---|---|---|---|---|---|---|"]
        md += [f"| {r['name']} | {r['real']} | {r['wired']} | {r['console']} | {r['issues']} | {r['upstream']} | {r['release']} |"
               for r in d["released"]]
        if d["gaps"]:
            md += ["", "- **Nano ↔ offline gaps:** " + ", ".join(
                f"{svc} ({'offline-only' if o else 'Nano-only'})" for svc, o, n in d["gaps"])]
        md.append("")

    md += ["## Up next", ""]
    for c, d in data.items():
        md += [f"<details><summary><b>{d['label']}</b> — {len(d['queued'])} queued</summary>", "",
               "| Service | Priority | Issue | Real backend |", "|---|---|---|---|"]
        md += [f"| {r['name']} | {r['priority']} | {r['link'] or 'not filed'} | {r['real']} |" for r in d["queued"]]
        md += ["", "</details>", ""]

    md += ["## Details", ""]
    for lbl, r in moving_all:
        if r["gate"]:
            md += [f"<details><summary>Gate checks — {r['name']} ({lbl})</summary>", "", "| | Check | Detail |", "|---|---|---|"]
            md += [f"| {'✅' if v[0] else '❌'} | {n} | {v[1].replace('|', '/')[:140]} |" for n, v in r["gate"].items()]
            md += ["", "</details>", ""]
    for c, d in data.items():
        if d["notlive"]:
            md += [f"<details><summary>Console parts not live yet — {d['label']} ({len(d['notlive'])})</summary>", "",
                   "| Service | Console | Part | State |", "|---|---|---|---|"]
            md += [f"| {svc} | {t} | {x['kind']}: {x['name']} | {x['state']} |" for svc, t, x in d["notlive"]]
            md += ["", "</details>", ""]
    if suite_res:
        md += ["<details><summary>Latest hourly test results</summary>", "", "| Suite | Result | Checks |", "|---|---|---|"]
        md += [f"| {sid} | {'✅' if r['status'] == 'pass' else '❌'} | {r.get('passed', 0)}/{r.get('passed', 0) + r.get('failed', 0)} |"
               for sid, r in suite_res.items()]
        md += ["", "</details>", ""]
    for c, d in data.items():
        md += [f"<details><summary>Not yet scheduled — {d['label']} ({len(d['rest'])} of {d['upstream']} published)</summary>", "",
               "| Service | Upstream id | Operations |", "|---|---|---|"]
        md += [f"| {r['name'] if r['name'] != r['id'] else '—'} | `{r['id']}` | {r.get('operations', '')} |" for r in d["rest"]]
        md += ["", "</details>", ""]

    md += ["## How to read this page", "",
           "- **Stages:** 📋 Queued → 🛠 Building → 🔍 In gate → 🚀 Releasing → released",
           "- **A service goes live only when the gate passes:** engine, native SDK/CLI, console offline + Nano, "
           "Java/Go/CLI/Playwright tests, cheap licensed backend, hourly + upstream registration",
           "- **Console parts:** service page, create, resource detail and each detail tab",
           "  - ✅ live = real data from the API",
           "  - 🟡 partial = real but some fields blank",
           "  - ⬜ static = hard-coded or generic text",
           "  - ❌ unimplemented = errors, 404/501, empty",
           "- **Console live `6/12 · 5/12`:** 6 of 12 parts live offline, 5 of 12 in Nano",
           f"- **Backends:** [rules and defaults]({GH}/blob/main/tests/conformance/expansion/backends.json)",
           f"- **Links:** [backlog]({GH}/issues?q=label%3Anew-service) · [expansion runs]({GH}/actions/workflows/expansion-agent.yml) · "
           f"[run log]({GH}/tree/expansion-state) · [hourly report]({GH}/tree/conformance-report) · "
           f"[upstream watcher]({GH}/tree/upstream-state) · [full catalog]({GH}/blob/main/docs/expansion/CLOUD-CATALOG.md)", ""]
    open(os.path.join(out_dir, "README.md"), "w").write("\n".join(md))
    json.dump({"updated": now, "totals": totals}, open(os.path.join(out_dir, "pipeline.json"), "w"), indent=1)
    print(json.dumps(totals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
