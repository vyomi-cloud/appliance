#!/usr/bin/env python3
"""aggregate.py <sdk.json> <cli.json> <ui.json> <out_dir>
Fold the three proof layers into
  <out_dir>/proof.json                   {capability_id: {sdk, cli, ui}}  each "pass" | "fail" | "n/a"   (every id in estate/coverage-map.json)
  <out_dir>/proof-detail.json            per-check results + reasons
  ../estate/coverage-map.proof.json      {id: {"proof": {sdk|cli|ui: note}}}  ONLY for what passed (consumed by coverage.py)
A capability passes a layer only when EVERY check mapped to it passed in that layer."""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import checks

sdk, cli, ui, out = sys.argv[1:5]
L = {"sdk": json.load(open(sdk)), "cli": json.load(open(cli))}
u = json.load(open(ui)); L["ui"] = {k: {"ok": v["ok"], "detail": v.get("detail", "")} for k, v in u.get("checks", {}).items()}
cmap = json.load(open(os.path.join(HERE, "..", "estate", "coverage-map.json")))
stamp = time.strftime("%Y-%m-%d")
proof, notes, mapout = {}, {}, {}
for cap in cmap:
    row, note = {}, {}
    if cap in checks.NA:
        row = {k: "n/a" for k in ("sdk", "cli", "ui")}; note = {k: checks.NA[cap] for k in row}
    else:
        names = checks.CAPS.get(cap)
        for layer in ("sdk", "cli", "ui"):
            if not names:
                row[layer] = "n/a"; note[layer] = "no proof check mapped"; continue
            rs = [L[layer].get(n) for n in names]
            if any(r is None or r["ok"] is None for r in rs):
                row[layer] = "n/a"; note[layer] = "; ".join((r or {}).get("detail", "not run") for r in rs if r is None or r["ok"] is None)
            elif all(r["ok"] for r in rs):
                row[layer] = "pass"
            else:
                row[layer] = "fail"; note[layer] = "; ".join(f"{n}: {r['detail']}" for n, r in zip(names, rs) if not r["ok"])
    proof[cap] = row; notes[cap] = note
    ok = {k: f"{k} proof {stamp}: " + (", ".join(checks.CAPS.get(cap, [])) or "") + f" ({'boto3' if k=='sdk' else 'aws cli' if k=='cli' else 'Nano v4 AWS console, Playwright, mesh-homed space'})"
          for k, v in row.items() if v == "pass"}
    if ok:
        mapout[cap] = {"proof": ok}
os.makedirs(out, exist_ok=True)
json.dump(proof, open(os.path.join(out, "proof.json"), "w"), indent=1, sort_keys=True)
json.dump({"checks": L, "notes": notes, "ui_fatal": u.get("fatal"),
           "model_backend": "fake-echo (OpenAI-compatible stand-in for llama.cpp; NOT a real model: no model is downloaded on this host, disk guard)"},
          open(os.path.join(out, "proof-detail.json"), "w"), indent=1, sort_keys=True)
json.dump(mapout, open(os.path.join(HERE, "..", "estate", "coverage-map.proof.json"), "w"), indent=1, sort_keys=True)
tot = {k: sum(1 for r in proof.values() if r[k] == "pass") for k in ("sdk", "cli", "ui")}
fail = {k: [c for c, r in proof.items() if r[k] == "fail"] for k in ("sdk", "cli", "ui")}
na = {k: sum(1 for r in proof.values() if r[k] == "n/a") for k in ("sdk", "cli", "ui")}
print(f"PROOF capabilities={len(proof)} pass={tot} n/a={na} fail={ {k: len(v) for k, v in fail.items()} }")
for k, v in fail.items():
    for c in v: print(f"  FAIL {k} {c}: {notes[c].get(k, '')[:200]}")
sys.exit(1 if any(fail.values()) else 0)
