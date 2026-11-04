#!/usr/bin/env python3
"""Generate docs/architecture/v4.0/V4-LAUNCH-CLAIMS.md: the launch-claim list per cloud / service,
split into REAL, LIMITED (with the limit) and NOT SIMULATED.

  python3 consoles/tests/launch-claims.py [<scan-out-dir>]

Sources (all regenerable, nothing hand-edited in the output):
  * core/capabilities/<cloud>/<service>.json     the registry: the authority for every claim and its level
  * <scan-out-dir>/offline-<cloud>.json          optional gap-scan.mjs output (the Not-simulated panels and
                                                 Limited badges the consoles really render)
  * consoles/tests/launch-claims-map.json        curated: scan panels that carry no registry id -> the id that
                                                 states their claim; pages that are editorial (no claim)
  * consoles/tests/launch-claims-reviewed.json   curated: registry entries whose 'not simulated' wording was
                                                 reviewed against the code (partial claims), and Nano/offline
                                                 level splits that are intentional
  * docs/architecture/v4.0/V4-GAP-STATUS.json    the 683-section baseline, for the closure ledger

A claim is 'real' only for level full; limited / config_only are listed with their limitation text;
not_simulated entries are listed with the reason shown to the user. A level is shown per substrate when
the offline and Nano levels differ."""
import collections, datetime, glob, json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = Path(sys.argv[1]) if len(sys.argv) > 1 else None
CLOUDS = ["aws", "gcp", "azure"]
LV = {"full": "real", "limited": "limited", "config_only": "limited (config only)", "not_simulated": "not simulated"}
NEG = re.compile(r"\bnot simulated\b|\bnot implemented\b|\bno backend\b", re.I)

reg = {}
for f in sorted(glob.glob(str(ROOT / "core/capabilities/*/*.json"))):
    cloud, svc = f.split("/")[-2], os.path.basename(f)[:-5]
    for k, e in json.load(open(f)).items():
        if k.startswith("$"): continue
        lv = e.get("level") or {}
        reg[k] = dict(id=k, cloud=cloud, svc=svc, title=e.get("title", ""), off=lv.get("offline"), nano=lv.get("nano"), lim=e.get("limitations") or [])

curated = json.load(open(ROOT / "consoles/tests/launch-claims-map.json")) if (ROOT / "consoles/tests/launch-claims-map.json").exists() else {}
reviewed = json.load(open(ROOT / "consoles/tests/launch-claims-reviewed.json")) if (ROOT / "consoles/tests/launch-claims-reviewed.json").exists() else {}
panel_ids = curated.get("panel_ids", {})      # "cloud|service|feature" -> registry id
no_claim = curated.get("no_claim", {})        # "cloud|service|feature" -> reason

def short(t, n=260):
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[: n].rsplit(" ", 1)[0] + " ..."

def lv(e):
    return LV.get(e["off"], e["off"]) if e["off"] == e["nano"] else f"{LV.get(e['off'], e['off'])} offline / {LV.get(e['nano'], e['nano'])} Nano"

# ---- scan evidence
scan = {}
for c in CLOUDS:
    fn = (SCAN / f"offline-{c}.json") if SCAN else None
    if fn and fn.exists():
        scan[c] = json.load(open(fn))
rendered_ns, rendered_lim, idless = set(), set(), []
for c, d in scan.items():
    for f in d.get("findings", []):
        if f.get("capabilityId"): rendered_ns.add(f["capabilityId"])
        else: idless.append((c, f))
    for f in d.get("limited", []):
        if f.get("id"): rendered_lim.add(f["id"])

resolved_idless, unresolved_idless, editorial = [], [], []
for c, f in idless:
    key = f"{c}|{f['service']}|{f['feature']}"
    if key in panel_ids and panel_ids[key] in reg: resolved_idless.append((key, panel_ids[key]))
    elif key in no_claim: editorial.append((key, no_claim[key]))
    else: unresolved_idless.append(key)

# ---- ledger of the 683-section baseline
ledger = collections.Counter(); ledger_rows = []
gs = ROOT / "docs/architecture/v4.0/V4-GAP-STATUS.json"
if gs.exists():
    st = json.load(open(gs))
    for s in st.get("closed", []) + st.get("remaining", []):
        key = f"{s['cloud']}|{s['service']}|{s['title']}"
        rid = panel_ids.get(key) or s.get("regid") or s.get("cap")
        if key in no_claim: state = "editorial (no claim)"
        elif rid in reg: state = LV.get(reg[rid]["off"], reg[rid]["off"])
        else: state = "unmapped"
        ledger[(s["cloud"], state)] += 1

# ---- consistency
partial_ok = set(reviewed.get("partial_text", []))
contradictions = [e for e in reg.values() if e["off"] in ("full", "limited", "config_only") and NEG.search(" ".join(e["lim"])) and e["id"] not in partial_ok]
split_ok = set(reviewed.get("substrate_split", []))
splits = [e for e in reg.values() if e["off"] != e["nano"]]
src = ""
for p in glob.glob(str(ROOT / "consoles/src/**/*.js*"), recursive=True): src += open(p, errors="ignore").read()
used = set()
for m in re.finditer(r"(?:capId|capabilityId|capability|id)\s*[=:]\s*[\"'{`]+\s*((?:azure|gcp|aws)\.[a-z0-9_-]+(?:\.[a-z0-9_-]+)+)", src): used.add(m.group(1))
noreg = sorted(u for u in used if u not in reg and not u.endswith("."))

try: head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
except Exception: head = "?"

out = []
w = out.append
w("# v4 launch claims: what is real, limited, and not simulated\n")
w(f"Generated {datetime.date.today()} at `{head}` by `consoles/tests/launch-claims.py` (rerun it; do not edit by hand). Source of truth is the capability registry (`core/capabilities/<cloud>/<service>.json`); the consoles render the same text, and `tests/conformance/test_capabilities.py` proves each claim against the backend. 'Nano' differs from 'offline' only where stated.\n")
w("Reading the levels: **real** = full on both substrates; **limited** = works, with the limit quoted; **not simulated** = the console shows an honest 'Not simulated in Vyomi' panel (never a fake page).\n")
w("## 1. Totals\n")
w("| Cloud | Capabilities | Real | Limited | Config only | Not simulated | Nano level differs |")
w("|---|---|---|---|---|---|---|")
tot = collections.Counter()
for c in CLOUDS:
    es = [e for e in reg.values() if e["cloud"] == c]
    n = collections.Counter(e["off"] for e in es)
    d = sum(1 for e in es if e["off"] != e["nano"])
    w(f"| {c.upper()} | {len(es)} | {n['full']} | {n['limited']} | {n['config_only']} | {n['not_simulated']} | {d} |")
    tot.update(n); tot["all"] += len(es); tot["d"] += d
w(f"| **Total** | {tot['all']} | {tot['full']} | {tot['limited']} | {tot['config_only']} | {tot['not_simulated']} | {tot['d']} |\n")
if scan:
    w("Console evidence (gap-scan, text-only crawl of the offline consoles): " + "; ".join(f"{c}: {len(d.get('visited', []))} pages, {len(d.get('findings', []))} Not-simulated panels, {len(d.get('limited', []))} Limited badges" for c, d in scan.items()) + ".\n")
w("## 2. Section ledger (the original 683 Not-simulated sections)\n")
if ledger:
    states = ["real", "limited", "limited (config only)", "not simulated", "editorial (no claim)", "unmapped"]
    w("| Cloud | " + " | ".join(states) + " |"); w("|---|" + "---|" * len(states))
    for c in CLOUDS:
        w(f"| {c.upper()} | " + " | ".join(str(ledger[(c, s)]) for s in states) + " |")
    w("")
w(f"Console Not-simulated panels that carry no registry id: {len(idless)}; mapped to an id by `launch-claims-map.json`: {len(resolved_idless)}; editorial (no claim): {len(editorial)}; **unresolved: {len(unresolved_idless)}**." + (" " + "; ".join(unresolved_idless[:40]) if unresolved_idless else "") + "\n")

for c in CLOUDS:
    w(f"## 3.{CLOUDS.index(c) + 1} {c.upper()}\n")
    by = collections.defaultdict(list)
    for e in reg.values():
        if e["cloud"] == c: by[e["svc"]].append(e)
    for svc in sorted(by):
        es = sorted(by[svc], key=lambda e: e["id"])
        real = [e for e in es if e["off"] == "full" and e["nano"] == "full"]
        lim = [e for e in es if e["off"] in ("limited", "config_only") or (e["off"] == "full" and e["nano"] != "full")]
        ns = [e for e in es if e["off"] == "not_simulated"]
        w(f"### {c}/{svc}: {len(real)} real, {len(lim)} limited, {len(ns)} not simulated\n")
        if real:
            w("**Real:** " + "; ".join(f"{e['title']} (`{e['id']}`)" for e in real) + "\n")
        if lim:
            w("**Limited:**\n")
            for e in lim:
                w(f"- `{e['id']}` {e['title']} [{lv(e)}]: {short(' '.join(e['lim'])) or 'see registry'}")
            w("")
        if ns:
            w("**Not simulated:**\n")
            for e in ns:
                w(f"- `{e['id']}` {e['title']}{' [offline/Nano: ' + e['off'] + '/' + e['nano'] + ']' if e['off'] != e['nano'] else ''}: {short(' '.join(e['lim'])) or 'see registry'}")
            w("")

w("## 4. Registry hygiene (checked on every regeneration)\n")
w(f"- Registered full/limited/config_only whose text still says 'not simulated' / 'not implemented' and has not been reviewed: **{len(contradictions)}**" + ((" (" + ", ".join(f"`{e['id']}`" for e in contradictions[:30]) + ")") if contradictions else "") + f". Reviewed partial claims (text states what is real AND the specific part that is not): {len(partial_ok)}.")
w(f"- Entries whose Nano level differs from offline: {len(splits)}, of which {len([e for e in splits if e['id'] in split_ok])} reviewed as intentional (Nano has no instance runtime / durable worker; the text says so): " + ", ".join(f"`{e['id']}` ({e['off']}/{e['nano']})" for e in splits) + ".")
w(f"- Console capability ids with no registry entry: {len(noreg)}" + ((": " + ", ".join(f"`{u}`" for u in noreg)) if noreg else "") + ".")
ns_all = [e for e in reg.values() if e["off"] == "not_simulated" or e["nano"] == "not_simulated"]
if scan:
    nopanel = [e["id"] for e in ns_all if e["id"] not in rendered_ns]
    w(f"- Registered not_simulated ids: {len(ns_all)}; rendered by the scan: {len(ns_all) - len(nopanel)}; not rendered by the scan: {len(nopanel)} (a registry-only claim, or a panel the crawl did not reach): " + ", ".join(f"`{i}`" for i in nopanel) + ".")
print("\n".join(out))
