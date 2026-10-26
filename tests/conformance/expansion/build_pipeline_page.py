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

    sections, totals = [], {}
    for cloud, label in CLOUDS:
        rows, stages = [], {}
        released = [s for s in reg if s["cloud"] == cloud and s.get("status") == "released"]
        released_keys = {s["key"] for s in released} | {key_of(s.get("upstream") or s["key"]) for s in released}
        queue = [s for s in cat["services"] if s["cloud"] == cloud and s["priority"] in ("P1", "P2")
                 and s["status"] != "released" and key_of(s["id"]) not in released_keys]
        queue.sort(key=lambda s: (s["priority"], s["name"].lower()))
        details = []

        for s in released:
            man = os.path.join(ROOT, "services", "manifests", f"{cloud}-{s['key']}.json")
            suites = json.load(open(man)).get("suites", []) if os.path.exists(man) else []
            ver = s.get("released_in", "")
            rel = f"[v{ver}]({GH}/releases/tag/v{ver})" if re.match(r"^\d", ver) else (ver or "baseline")
            stages["Released"] = stages.get("Released", 0) + 1
            # Pre-gate (baseline) services weren't built through the gate: no
            # per-check claims for them, only their hourly + upstream status.
            rows.append([f"**{s['name']}**", "—", "🟢 Released", "—"] + (["✅"] * len(COLS) if suites else ["—"] * len(COLS)) +
                        [console_cell(cloud, s["name"]), par_cell(cloud, s["name"]), "✅ passed" if suites else "baseline (pre-gate)", rel, hourly_cell(cloud, s["name"], suites),
                         upstream_cell(cloud, s.get("upstream") or s["key"], [s["key"], s["name"]])])

        for s in queue:
            k = key_of(s["id"])
            branch = f"expansion/{cloud}-{k}"
            it = by_key.get((cloud, k))
            labels = {l["name"] for l in (it or {}).get("labels", [])}
            pr = prs.get(branch)
            issue = f" [#{it['number']}]({GH}/issues/{it['number']})" if it else ""
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
                stage = "· Not filed"
            stages[stage.split(" (")[0]] = stages.get(stage.split(" (")[0], 0) + 1
            gate = static_gate(branch, f"services/manifests/{cloud}-{k}.json") if branch in branches else {}
            if gate:
                cells = ["✅" if all(gate.get(c, (False,))[0] for c in checks) else "❌" for _, checks in COLS]
                ok = sum(1 for v in gate.values() if v[0])
                gcell = f"static {ok}/{len(gate)} · live {live_gate(branch) if pr else '—'}"
                details.append(f"<details><summary>{label} {s['name']} — gate {ok}/{len(gate)}</summary>\n\n"
                               "| | Check | Detail |\n|---|---|---|\n" +
                               "\n".join(f"| {'✅' if v[0] else '❌'} | {n} | {v[1].replace('|', '/')[:160]} |" for n, v in gate.items())
                               + "\n\n</details>")
            else:
                cells = ["⬜"] * len(COLS)
                gcell = "no manifest yet" if branch in branches else "—"
            name = s["name"] if s["name"] != s["id"] else s["id"]
            mb = None
            if branch in branches:
                try:
                    mb = json.loads(sh("git", "show", f"origin/{branch}:services/manifests/{cloud}-{k}.json") or "{}").get("backend")
                except ValueError:
                    mb = None
            rows.append([f"{name}{issue}", s["priority"], stage, backend_cell(cloud, s["id"], mb)] + cells + ["⏳ after release", "⏳ gated", gcell, "—", "⏳ after release",
                        "⏳ registered at build" if not gate else
                        ("✅ registered" if gate.get("upstream id tracked by the hourly upstream watcher", (False,))[0] else "⬜ not yet")])

        totals[cloud] = {"released": len(released), "queue": len(queue), **stages}
        head = ["Service", "Pri", "Stage", "Offline backend"] + [c for c, _ in COLS] + ["Console live", "Nano ↔ offline", "Gate", "Release", "Hourly conformance hand-off", "Upstream watcher hand-off"]
        t = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(r) + " |" for r in rows]
        summary = " · ".join(f"{k}: **{v}**" for k, v in stages.items())
        ctab = ["| Console | Surfaces | ✅ Live | 🟡 Partial (blank fields) | ⬜ Static | ❌ Unimplemented |", "|---|---|---|---|---|---|"]
        notlive = []
        for t, lbl in (("offline", "Offline"), ("nano", "Nano")):
            xs = surf(t, cloud)
            if not xs:
                ctab.append(f"| {lbl} | not crawled yet | | | | |")
                continue
            c = {st: sum(x["state"] == st for x in xs) for st in STATES}
            ctab.append(f"| {lbl} | {len(xs)} | " + " | ".join(f"{c[st]} ({100 * c[st] // len(xs)}%)" for st in STATES) + " |")
            for r in (ui.get(t) or {}).get("services", []):
                if r["cloud"] == cloud:
                    for x in r.get("surfaces", []):
                        if x["state"] != "live":
                            notlive.append(f"| {r['service']} | {lbl} | {x['kind']} | {x['name']} | {x['state']} |")
        summary += ("\n\n**Console implementation** (latest hourly crawl; the hourly agent implements static and "
                    "unimplemented surfaces):\n\n" + "\n".join(ctab))
        if notlive:
            summary += (f"\n\n<details><summary>{len(notlive)} console surfaces not live yet</summary>\n\n"
                        "| Service | Console | Surface | Name | State |\n|---|---|---|---|---|\n" + "\n".join(notlive) + "\n\n</details>")
        gaps = []
        for svc in sorted({k[2] for k in feats if k[1] == cloud}):
            tot, off_only, nano_only = parity(cloud, svc)
            if off_only or nano_only:
                o, n = feats.get(("offline", cloud, svc), set()), feats.get(("nano", cloud, svc), set())
                gaps.append(f"| {svc} | {', '.join(f'{k}: {v}' for k, v in sorted(o - n)[:6]) or '—'} | "
                            f"{', '.join(f'{k}: {v}' for k, v in sorted(n - o)[:6]) or '—'} |")
        summary += ("\n\n**Nano ↔ offline parity gaps** (the hourly agent closes these):\n\n"
                    "| Console page | Offline only | Nano only |\n|---|---|---|\n" + "\n".join(gaps)) if gaps \
            else "\n\n**Nano ↔ offline parity:** ✅ every console page has the same features on both."
        # Everything else the cloud publishes (P3): listed so the page covers
        # the whole cloud, folded because it's long.
        rest = sorted((r for r in cat["services"] if r["cloud"] == cloud and r["priority"] == "P3"
                       and r["status"] != "released" and key_of(r["id"]) not in released_keys),
                      key=lambda r: r["id"])
        upstream_total = sum(1 for r in cat["services"] if r["cloud"] == cloud)
        totals[cloud]["upstream"] = upstream_total
        p3 = (f"<details><summary><b>Not yet scheduled (P3): {len(rest)} services</b> — the rest of {label}'s "
              f"{upstream_total} published services; scheduled by promoting them to P1/P2 in tests/conformance/expansion/priorities.json</summary>\n\n"
              "| Service | Upstream id | Operations | Stage |\n|---|---|---|---|\n" +
              "\n".join(f"| {r['name'] if r['name'] != r['id'] else '—'} | `{r['id']}` | {r.get('operations', '')} | · not scheduled |"
                         for r in rest) + "\n\n</details>")
        sections.append(f"## {label} — {len(released)} released, {len(queue)} in the pipeline, {len(rest)} not yet scheduled "
                        f"({upstream_total} published by {label})\n\n{summary}\n\n" + "\n".join(t)
                        + ("\n\n**Gate details**\n\n" + "\n\n".join(details) if details else "") + "\n\n" + p3)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cloud_suites = " · ".join(f"`{sid}` {'✅' if r['status'] == 'pass' else '❌'} {r.get('passed', 0)}/{r.get('passed', 0) + r.get('failed', 0)}"
                              for sid, r in suite_res.items())
    total_rel = sum(v["released"] for v in totals.values())
    per_cloud = " / ".join(f"{l} {totals[c]['released']}" for c, l in CLOUDS)
    md = [f"# Vyomi service pipeline", "",
          f"Updated **{now}** · **{total_rel} services released** "
          f"({per_cloud}) · "
          f"**{sum(v['queue'] for v in totals.values())} in the pipeline** (P1 + P2) · "
          f"covering all **{sum(v.get('upstream', 0) for v in totals.values())} services** AWS, GCP and Azure publish "
          f"(catalog of {cat.get('generated', '')[:10]}).", "",
          "A new service goes live only when the service gate passes: engine, native SDK/CLI wire, console UI offline + Nano, "
          "Java + Go + CLI test beds, Playwright console tests offline + Nano, registered with the hourly conformance run and "
          "the upstream watcher. Then it is released (patch version) and handed off to both hourly jobs.", "",
          "**Stages:** 📋 Queued → 🛠 Building → 🔍 In gate → 🚀 Releasing → 🟢 Released. "
          "Columns Engine…PW Nano are the gate's static checks on the service branch (⬜ = not checked yet). "
          "Offline backend is the cheap, permissively licensed software behind the service offline "
          "([rules + defaults](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/expansion/backends.json)); "
          "the gate checks its license, arch, pinning and idle memory. "
          "Console live counts the console surfaces (service page, create, resource detail, each detail tab) that "
          "are really implemented: ✅ live = loads data from the API or shows the resource's own data; 🟡 partial = "
          "API-backed with blank fields; ⬜ static = hard-coded or generic text; ❌ unimplemented = errors, 404/501, "
          "dead or empty. Classified by the hourly crawl on both consoles. "
          "Nano ↔ offline compares every console feature (pages, tabs, columns, create fields, actions, operations) "
          "between the two simulators from the latest hourly inventory; a new service can't pass the gate unless both match. "
          "Hourly hand-off shows the latest hourly UI crawl (⚠️ n = open findings) and the service's own suites; "
          "upstream hand-off shows whether the watcher tracks the API and any open drift issues.", "",
          f"Links: [backlog]({GH}/issues?q=label%3Anew-service) · [expansion runs]({GH}/actions/workflows/expansion-agent.yml) · "
          f"[usage-limit log]({GH}/tree/expansion-state) · [hourly conformance report]({GH}/tree/conformance-report) · "
          f"[upstream watcher]({GH}/tree/upstream-state) · [full catalog]({GH}/blob/main/docs/expansion/CLOUD-CATALOG.md)", "",
          f"**Latest hourly run** ({hourly.get('at', 'n/a')[:16].replace('T', ' ')} UTC): {cloud_suites or 'n/a'}", ""]
    md += ["\n\n".join(sections), ""]
    open(os.path.join(out_dir, "README.md"), "w").write("\n".join(md))
    json.dump({"updated": now, "totals": totals}, open(os.path.join(out_dir, "pipeline.json"), "w"), indent=1)
    print(json.dumps(totals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
