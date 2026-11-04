#!/usr/bin/env python3
"""Reality check of the v4 gap queue: compares a fresh gap-scan with the ORIGINAL 683-section queue and the
capability registry, and writes docs/architecture/v4.0/V4-GAP-STATUS.md (+ .json).

  python3 consoles/tests/gap-status.py <scan-out-dir> <original-queue.json>

<scan-out-dir> holds offline-<cloud>.json (and optionally nano-<cloud>.json) from gap-scan.mjs.
The original queue is `git show 0edff635:docs/architecture/v4.0/V4-GAP-QUEUE.json` (the 683-section baseline)."""
import json, re, sys, glob, os, collections, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = Path(sys.argv[1]); OLD = json.load(open(sys.argv[2]))
CLOUDS = ["aws", "gcp", "azure"]
norm = lambda t: re.sub(r"^[^|]{1,60} \| ", "", t or "").strip().lower()
toks = lambda s: set(w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2)

reg = {}
for f in sorted(glob.glob(str(ROOT / "core/capabilities/*/*.json"))):
    c = f.split("/")[-2]; s = os.path.basename(f)[:-5]
    for k, e in json.load(open(f)).items():
        if not k.startswith("$"):
            reg[k] = dict(cloud=c, svc=s, title=e.get("title", ""), off=(e.get("level") or {}).get("offline"), nano=(e.get("level") or {}).get("nano"), lim=e.get("limitations") or [])

def keyof(cloud, svc, capid, title): return (cloud, svc, capid or norm(title))

old = {}
for b in OLD["batches"]:
    for t in b["themes"]:
        for i in t["items"]:
            old[keyof(b["cloud"], i["service"], i["capabilityId"], i["title"])] = dict(cloud=b["cloud"], service=i["service"], title=norm(i["title"]) and re.sub(r"^[^|]{1,60} \| ", "", i["title"]), cap=i["capabilityId"], cls=t["cls"], family=t["family"], theme=t["theme"], batch=b["id"], note=i["note"], substrates=i.get("substrates", []))

new, scanmeta = {}, {}
for c in CLOUDS:
    for sub in ("offline", "nano"):
        fn = SCAN / f"{sub}-{c}.json"
        if not fn.exists(): continue
        d = json.load(open(fn)); scanmeta[f"{sub}/{c}"] = dict(pages=len(d["visited"]), errors=len(d.get("errors", [])), unreached=len(d.get("unreachedPatterns", [])))
        for f in d["findings"]:
            title = re.sub(r"^[^|]{1,60} \| ", "", f["title"])
            k = keyof(c, f["service"], f["capabilityId"], title)
            n = new.setdefault(k, dict(cloud=c, service=f["service"], title=title, cap=f["capabilityId"], note=f["note"], routes=set(), subs=set()))
            n["routes"].update(f["routes"]); n["subs"].add(sub)

def fuzzy(cloud, svc, title):
    t = toks(title); best, bs = None, 0
    for k, e in reg.items():
        if e["cloud"] != cloud: continue
        sc = len(t & toks(e["title"])) / max(1, len(t | toks(e["title"])))
        if e["svc"] in svc or svc in e["svc"] or svc.split("-")[0] in k: sc += 0.15
        if sc > bs: best, bs = k, sc
    return (best, bs) if bs >= 0.5 else (None, bs)

closed, still = [], []
for k, o in old.items():
    if k in new: still.append(dict(o, routes=sorted(new[k]["routes"])[:2], subs=sorted(new[k]["subs"]), note=new[k]["note"] or o["note"]))
    else:
        cap = o["cap"] if o["cap"] in reg else None; how = "registry id"
        if not cap: cap, sc = fuzzy(o["cloud"], o["service"], o["title"]); how = f"title match {sc:.2f}" if cap else ""
        lv = reg[cap]["off"] if cap else None
        st = "nano-only-unscanned" if (o["substrates"] == ["nano"] and "nano/" + o["cloud"] not in scanmeta) else "limited" if lv in ("limited", "config_only") else "real" if lv == "full" else "closed-unmatched"
        closed.append(dict(o, state=st, regid=cap, level=lv, how=how))
appeared = [dict(v, routes=sorted(v["routes"])[:2], subs=sorted(v["subs"])) for k, v in new.items() if k not in old]

# ---- stale / contradictory registry text
neg = re.compile(r"\bnot simulated\b|\bnot implemented\b|\bno backend\b", re.I)
contra = [dict(id=k, level=e["off"], nano=e["nano"], hit=neg.search(" ".join(e["lim"])).group(0), text=" ".join(e["lim"])[:200]) for k, e in reg.items() if e["off"] in ("full", "limited", "config_only") and neg.search(" ".join(e["lim"]))]
fullwith = [k for k, e in reg.items() if e["off"] == "full" and e["lim"] and e["nano"] == "full"]
split = [k for k, e in reg.items() if e["off"] != e["nano"]]
ns_reg = {k: e for k, e in reg.items() if e["off"] == "not_simulated" or e["nano"] == "not_simulated"}
ns_ui_caps = {v["cap"] for v in new.values() if v["cap"]}
reg_ns_not_shown = [k for k in ns_reg if k not in ns_ui_caps]
# UI panels (not_simulated badge) whose capability id is registered at a level that is NOT not_simulated
badge_vs_level = [dict(id=v["cap"], title=v["title"], level=reg[v["cap"]]["off"], nano=reg[v["cap"]]["nano"]) for v in new.values() if v["cap"] in reg and reg[v["cap"]]["off"] != "not_simulated"]
# console capability ids with no registry entry
used = set()
for f in glob.glob(str(ROOT / "consoles/src/**/*.js*"), recursive=True):
    for m in re.finditer(r"(?:capId|capabilityId|capability)\s*[=:]\s*[\"'{`]+\s*([a-z0-9_-]+(?:\.[a-z0-9_-]+)+)", open(f, errors="ignore").read()): used.add(m.group(1))
noreg = sorted(u for u in used if u not in reg)
# scanner: limited badges rendered whose id is not in the registry
unk = sorted({l["id"] for sub in ("offline",) for c in CLOUDS if (SCAN / f"{sub}-{c}.json").exists() for l in json.load(open(SCAN / f"{sub}-{c}.json"))["limited"] if l["id"] not in reg})

tot = lambda L, c: sum(1 for x in L if x["cloud"] == c)
W = []; w = W.append
w("# v4 gap status: what v4 really does vs honestly does not")
w("")
w(f"Generated {datetime.date.today().isoformat()} at `{os.popen('git -C %s rev-parse --short HEAD' % ROOT).read().strip()}` by `consoles/tests/gap-scan.mjs` + `consoles/tests/gap-status.py`. Baseline = the original 683-section queue (`V4-GAP-QUEUE.md`, scan at `{OLD['baseCommit']}`). Scan = text-only Playwright crawl of the offline consoles" + (" and Nano" if any(k.startswith("nano") for k in scanmeta) else " (Nano was not re-scanned; see section 7)") + ". This doubles as the launch-claim checklist.")
w("")
w("## 1. Headline counts")
w("")
w("| Cloud | Original sections | Closed (real) | Closed (limited, honest text) | Closed (state not determinable) | Not re-scanned (Nano-only page) | Still Not simulated | New since baseline |")
w("|---|---|---|---|---|---|---|---|")
for c in CLOUDS:
    o = [x for x in old.values() if x["cloud"] == c]
    cl = [x for x in closed if x["cloud"] == c]
    w(f"| {c.upper()} | {len(o)} | {sum(1 for x in cl if x['state']=='real')} | {sum(1 for x in cl if x['state']=='limited')} | {sum(1 for x in cl if x['state']=='closed-unmatched')} | {sum(1 for x in cl if x['state']=='nano-only-unscanned')} | {tot(still, c)} | {tot(appeared, c)} |")
w(f"| **Total** | {len(old)} | {sum(1 for x in closed if x['state']=='real')} | {sum(1 for x in closed if x['state']=='limited')} | {sum(1 for x in closed if x['state']=='closed-unmatched')} | {sum(1 for x in closed if x['state']=='nano-only-unscanned')} | {len(still)} | {len(appeared)} |")
w("")
w("How to read: a section is *closed* when its `Not simulated in Vyomi` panel no longer renders anywhere in the console. Its state is taken from the capability registry (by id, else the best title match in the same cloud; the match score is in the JSON): `real` = registered `full`, `limited` = registered `limited`/`config_only` (the page works but shows the border tab with the honest limitation), *state not determinable* = no registry entry matched (the panel was replaced by a real page or removed, but nothing in the registry states which; treat as unverified until a registry entry exists). 'New since baseline' = panels the scanner now finds that were not in the original 683 (new pages added since, or titles that changed).")
w("")
w("Registry totals (all 1 281 entries, offline level / Nano level):")
w("")
w("| Cloud | full | limited | config_only | not_simulated | entries where Nano differs from offline |")
w("|---|---|---|---|---|---|")
for c in CLOUDS:
    r = [e for e in reg.values() if e["cloud"] == c]; cn = collections.Counter(e["off"] for e in r)
    w(f"| {c.upper()} | {cn['full']} | {cn['limited']} | {cn['config_only']} | {cn['not_simulated']} | {sum(1 for e in r if e['off']!=e['nano'])} |")
w("")
w("## 2. Remaining Not-simulated sections (UI) by service and class")
w("")
w("| Cloud | Service | Remaining | A (buildable) | B (decided backend) | C (unbuildable) | N (not a gap) |")
w("|---|---|---|---|---|---|---|")
sv = collections.defaultdict(collections.Counter)
for x in still: sv[(x["cloud"], x["service"])][x["cls"]] += 1
for (c, s), v in sorted(sv.items(), key=lambda kv: (CLOUDS.index(kv[0][0]), kv[0][1])):
    w(f"| {c} | {s} | {sum(v.values())} | {v['A']} | {v['B']} | {v['C']} | {v['N']} |")
w("")
w("## 3. Every remaining Not-simulated section")
w("")
w("Format: title (route) - reason shown to the user - waits on: backend family / class. Class A has no decided family: it is simply unbuilt. Class C is honest-forever (hardware, payments, real-cloud-only, editorial). Class N is a state-dependent panel, not a gap.")
w("")
for c in CLOUDS:
    w(f"### {c.upper()} ({tot(still, c)})")
    w("")
    for s in sorted({x['service'] for x in still if x['cloud'] == c}):
        w(f"**{s}**")
        w("")
        for x in sorted([x for x in still if x["cloud"] == c and x["service"] == s], key=lambda x: (x["cls"], x["title"])):
            wait = f"family `{x['family']}`" if x["family"] else {"A": "unbuilt (class A)", "C": "no honest backend (class C)", "N": "not a gap (class N)"}.get(x["cls"], x["cls"])
            note = re.sub(r"\s+", " ", x["note"] or "").strip()[:170]
            w(f"- {x['title'][:90]} (`{x['routes'][0] if x['routes'] else ''}`) - {note or 'no reason text'} - waits on: {wait}; batch {x['batch']}" + (f" [{x['cap']}]" if x["cap"] else ""))
        w("")
w("## 4. Closed since the baseline")
w("")
for st, lab in (("real", "Closed real (registered full)"), ("limited", "Closed but registered limited / config_only (honest text)"), ("closed-unmatched", "Closed, no registry entry matched (verify)"), ("nano-only-unscanned", "Not re-scanned: only reachable on Nano (EC2 instance detail needs RunInstances, unsupported on macOS offline)")):
    L = [x for x in closed if x["state"] == st]
    w(f"### {lab}: {len(L)}")
    w("")
    for c in CLOUDS:
        Lc = [x for x in L if x["cloud"] == c]
        if not Lc: continue
        w(f"{c.upper()}: " + "; ".join(f"{x['service']}: {x['title'][:60]}" + (f" [{x['regid']}]" if x["regid"] else "") for x in sorted(Lc, key=lambda x: (x["service"], x["title"]))))
        w("")
if appeared:
    w(f"### New panels not in the baseline: {len(appeared)}")
    w("")
    for x in sorted(appeared, key=lambda x: (x["cloud"], x["service"], x["title"])):
        w(f"- {x['cloud']}/{x['service']}: {x['title'][:80]} (`{x['routes'][0] if x['routes'] else ''}`) - {re.sub(chr(10), ' ', x['note'] or '')[:130]}")
    w("")
w("## 5. Registry entries registered Not simulated")
w("")
for k, e in sorted(ns_reg.items()):
    w(f"- `{k}` ({e['off']}/{e['nano']}): {e['title']} - {' '.join(e['lim'])[:200]}" + ("" if k in ns_ui_caps else " [no panel found by the scan: unreachable state, or shown without its id]"))
w("")
w("## 6. Registered limited / config_only: the launch-claim checklist")
w("")
w("One line per capability: id (offline/Nano level) - main limitation (first limitation, truncated). Full text lives in `core/capabilities/<cloud>/<service>.json`.")
w("")
for c in CLOUDS:
    for s in sorted({e["svc"] for e in reg.values() if e["cloud"] == c}):
        L = [(k, e) for k, e in sorted(reg.items()) if e["cloud"] == c and e["svc"] == s and (e["off"] in ("limited", "config_only") or e["nano"] in ("limited", "config_only")) and e["off"] != "not_simulated"]
        if not L: continue
        w(f"**{c}/{s}** ({len(L)})")
        w("")
        for k, e in L:
            lv = e["off"] if e["off"] == e["nano"] else f"{e['off']}/{e['nano']}"
            w(f"- `{k}` ({lv}) - {re.sub(chr(10), ' ', (e['lim'] or ['(no text)'])[0])[:200]}")
        w("")
w("## 7. Stale or contradictory registry entries")
w("")
w(f"1. Registered full/limited/config_only whose limitation text still says 'not simulated' / 'not implemented' ({len(contra)}). Some are legitimately partial ('X is not simulated, the rest is'); the ones where the WHOLE capability reads as not simulated are stale and should be re-levelled or reworded:")
w("")
for x in contra: w(f"- `{x['id']}` ({x['level']}/{x['nano']}): ...{x['hit']}... {x['text']}")
w("")
w(f"2. UI still renders a Not-simulated panel for a capability id registered above not_simulated ({len(badge_vs_level)}): " + ("; ".join(f"`{x['id']}` ({x['level']}/{x['nano']})" for x in badge_vs_level) or "none") + ".")
w("")
w(f"3. Registry says not_simulated (either substrate) but the scan found no panel carrying that id ({len(reg_ns_not_shown)}): " + (", ".join(f"`{k}`" for k in reg_ns_not_shown) or "none") + ". Either the page shows it without a capability id, or the page does not exist.")
w("")
w(f"4. Console references a capability id with no registry entry ({len(noreg)}): " + (", ".join(f"`{k}`" for k in noreg) or "none") + ". Limited/config badges rendered by the scan with an unregistered id: " + (", ".join(f"`{k}`" for k in unk) or "none") + ".")
w("")
w(f"5. Registered `full` offline AND Nano but still carrying limitation text ({len(fullwith)}): a `full` entry with limitations is a contradiction; either the text is a historic note or the level is too generous. " + ", ".join(f"`{k}`" for k in fullwith[:60]) + (" ..." if len(fullwith) > 60 else ""))
w("")
w(f"6. Entries where Nano and offline levels differ ({len(split)}): " + ", ".join(f"`{k}` ({reg[k]['off']}/{reg[k]['nano']})" for k in split))
w("")
w("## 8. Scan coverage")
w("")
for k, m in sorted(scanmeta.items()): w(f"- {k}: pages visited {m['pages']}, page errors {m['errors']}, unreached parameterised routes {m['unreached']}")
w("")
(ROOT / "docs/architecture/v4.0/V4-GAP-STATUS.md").write_text("\n".join(W) + "\n")
(ROOT / "docs/architecture/v4.0/V4-GAP-STATUS.json").write_text(json.dumps(dict(
    counts={c: dict(original=sum(1 for x in old.values() if x["cloud"] == c), real=sum(1 for x in closed if x["cloud"] == c and x["state"] == "real"), limited=sum(1 for x in closed if x["cloud"] == c and x["state"] == "limited"), unmatched=sum(1 for x in closed if x["cloud"] == c and x["state"] == "closed-unmatched"), remaining=tot(still, c), new=tot(appeared, c)) for c in CLOUDS},
    remaining=still, closed=closed, appeared=appeared, contradictions=contra, scan=scanmeta), indent=1, default=list))
print({c: (tot(still, c), tot(appeared, c)) for c in CLOUDS}, "closed", collections.Counter(x["state"] for x in closed))
