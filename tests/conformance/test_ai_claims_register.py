"""Drift check for docs/architecture/v4.0/AI-SELLABLE-CLAIMS.md (the sellable-claims register).

Fails if the register is stale relative to core/capabilities/*.json, if a claimed test file is
missing, if the recorded results do not cover every claimed test, or if a claim is stronger than
the recorded results allow. Fix: `python3 tools/ai_claims/gen_claims.py --run` and commit.

Run:  PYTHONPATH=. python3 tests/conformance/test_ai_claims_register.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("gen_claims", ROOT / "tools" / "ai_claims" / "gen_claims.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    print(("PASS " if ok else "FAIL ") + name + (f"  -> {detail}" if detail and not ok else ""))
    fails += 0 if ok else 1


feats = g.load_features()
check("registry yields AI features", len(feats) > 30, str(len(feats)))
check("register file exists", g.OUT.exists())
check("results.json exists", g.RESULTS.exists())
text = g.OUT.read_text() if g.OUT.exists() else ""
rd = json.loads(g.RESULTS.read_text()) if g.RESULTS.exists() else {"results": {}}

check("register digest matches current capability JSONs",
      f"registry-digest: `{g.inputs_digest(feats)}`" in text,
      "capability JSON changed since the register was generated; rerun gen_claims.py --run")
missing = [t for t in g.all_tests(feats) if not (ROOT / t).exists()]
check("every claimed test file exists", not missing, ", ".join(missing))
unrun = [t for t in g.all_tests(feats) if t not in rd["results"]]
check("results.json covers every claimed test", not unrun, ", ".join(unrun))
check("register is byte-identical to a regeneration from results.json",
      bool(text) and g.render(feats, rd) == text, "rerun gen_claims.py")
for f in feats:
    ok, _ = g.verified(f, rd["results"])
    c = g.claim(f, ok)
    check(f"claim for {f['id']} is not above its evidence", ok or c == g.UNVERIFIED)
    check(f"{f['id']} claim wording is allowed", c in g.CLAIMS or c == g.UNVERIFIED, c)
    if f["limitations"]:
        check(f"{f['id']} with registry limits is never 'supported'", c != "supported")

print(f"\n{'FAILED' if fails else 'OK'}: {fails} failure(s)")
sys.exit(1 if fails else 0)
