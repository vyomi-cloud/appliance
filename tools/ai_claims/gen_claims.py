#!/usr/bin/env python3
"""Generate docs/architecture/v4.0/AI-SELLABLE-CLAIMS.md from the capability registry.

Inputs : core/capabilities/{aws,gcp,azure}/*.json (AI services only, see AI_SERVICES),
         docs/architecture/v4.0/branches/ai-*.md (cross-references),
         tools/ai_claims/results.json (test results recorded by --run).
Output : the register, stamped with a digest of the capability inputs and the results.

  python3 tools/ai_claims/gen_claims.py --run [--python PY] [-j N]   # run every referenced test
                                                                    # in isolation (fresh
                                                                    # CLOUDLEARN_STATE_FILE), write
                                                                    # results.json, then regenerate
  python3 tools/ai_claims/gen_claims.py                              # regenerate from results.json

Nothing here touches engines; it only reads registry JSON and runs the existing tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPS = ROOT / "core" / "capabilities"
DOCS = ROOT / "docs" / "architecture" / "v4.0"
OUT = DOCS / "AI-SELLABLE-CLAIMS.md"
RESULTS = Path(__file__).with_name("results.json")

# (cloud, file stem, feature-id prefixes kept; None = whole file). panels.json holds extra AI tabs.
AI_SERVICES = [
    ("aws", "bedrock", None),
    ("gcp", "vertex-ai", None),
    ("azure", "cognitiveservices", None),
    ("azure", "aisearch", None),
    ("azure", "panels", ("azure.cognitiveservices.", "azure.aisearch.")),
]
CLOUD_NAME = {"aws": "AWS", "gcp": "GCP", "azure": "Azure"}
CLAIMS = ("supported", "dev-simplified", "Mesh only", "not supported")
UNVERIFIED = "not supported (test failing or not run)"
MESH_RE = re.compile(r"\bmesh\b", re.I)


def load_features() -> list[dict]:
    """All AI features, in stable order, with the registry fields kept verbatim."""
    feats = []
    for cloud, stem, prefixes in AI_SERVICES:
        path = CAPS / cloud / f"{stem}.json"
        data = json.loads(path.read_text())
        for fid, v in data.items():
            if fid.startswith("$") or not isinstance(v, dict):
                continue
            if prefixes and not fid.startswith(prefixes):
                continue
            feats.append({
                "cloud": cloud, "service": stem, "id": fid, "title": v.get("title", fid),
                "level": v.get("level", {}), "limitations": list(v.get("limitations", [])),
                "tests": list(v.get("tests", [])), "mesh": bool(v.get("mesh")),
                "tier": v.get("tier"), "source": f"core/capabilities/{cloud}/{stem}.json",
            })
    return feats


def inputs_digest(feats: list[dict]) -> str:
    """Digest of exactly the registry content the register depends on."""
    blob = json.dumps(feats, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def all_tests(feats) -> list[str]:
    return sorted({t for f in feats for t in f["tests"]})


def run_test(rel: str, py: str) -> dict:
    p = ROOT / rel
    if not p.exists():
        return {"status": "missing", "rc": None, "seconds": 0, "tail": ""}
    cmd = ["bash", str(p)] if rel.endswith(".sh") else [py, str(p)]
    with tempfile.TemporaryDirectory(prefix="claims-") as td:
        env = dict(os.environ, PYTHONPATH=str(ROOT), CLOUDLEARN_STATE_FILE=str(Path(td) / "state.sqlite3"),
                   PYTHONDONTWRITEBYTECODE="1")
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=1200)
            rc, out = r.returncode, (r.stdout + r.stderr)
        except subprocess.TimeoutExpired:
            rc, out = -9, "TIMEOUT after 1200s"
    lines = [l for l in out.strip().splitlines() if l.strip()]
    return {"status": "pass" if rc == 0 else "fail", "rc": rc, "seconds": round(time.time() - t0, 1),
            "tail": " | ".join(lines[-2:])[:300]}


def run_all(feats, py, jobs) -> dict:
    tests = all_tests(feats)
    with ThreadPoolExecutor(jobs) as ex:
        res = dict(zip(tests, ex.map(lambda t: run_test(t, py), tests)))
    out = {"python": py, "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                    text=True).stdout.strip(), "results": res}
    RESULTS.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out


def substrate(f: dict) -> str:
    lv = f["level"]
    n, o = lv.get("nano", "not_simulated"), lv.get("offline", "not_simulated")
    served = lambda x: x in ("full", "limited", "config_only")
    if f["mesh"] or (served(o) and not served(n)):
        return "Mesh"
    if served(n) and served(o):
        # a feature whose limitation text names a Mesh pack is only partly available on Nano
        if any(MESH_RE.search(l) for l in f["limitations"]):
            return "Both (parts Mesh-only, see limits)"
        return "Both"
    if served(n):
        return "Nano"
    return "None"


def verified(f: dict, res: dict) -> tuple[bool, str]:
    if not f["tests"]:
        return False, "no test referenced"
    cells, ok = [], True
    for t in f["tests"]:
        r = res.get(t)
        st = r["status"] if r else "not run"
        ok &= st == "pass"
        cells.append(f"`{Path(t).name}` {st.upper()}")
    return ok, "; ".join(cells)


def claim(f: dict, ok: bool) -> str:
    if not ok:
        return UNVERIFIED
    lv, sub = f["level"], substrate(f)
    if sub == "None" or all(lv.get(s) in (None, "not_simulated") for s in ("nano", "offline")):
        return "not supported"
    if sub == "Mesh":
        return "Mesh only"
    if all(lv.get(s) == "full" for s in ("nano", "offline")) and not f["limitations"]:
        return "supported"
    return "dev-simplified"


def esc(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def branch_docs(feats) -> dict:
    docs = {p.name: p.read_text() for p in sorted((DOCS / "branches").glob("ai-*.md"))}
    return {f["id"]: [n for n, t in docs.items() if f["id"] in t] for f in feats}


def render(feats, rd) -> str:
    res = rd["results"]
    digest = inputs_digest(feats)
    bd = branch_docs(feats)
    n_pass = sum(1 for r in res.values() if r["status"] == "pass")
    L = [
        "# AI sellable-claims register (Nano Free vs Mesh paid)",
        "",
        "GENERATED by `tools/ai_claims/gen_claims.py`; do not edit by hand. The drift check "
        "`tests/conformance/test_ai_claims_register.py` fails when this file is stale.",
        "",
        f"- registry-digest: `{digest}`",
        f"- results-commit: `{rd['commit']}`  ran-at: `{rd['ran_at']}`  interpreter: `{rd['python']}`",
        f"- tests run in isolation (fresh `CLOUDLEARN_STATE_FILE` each): {n_pass}/{len(res)} pass",
        "",
        "Public-claim wording is one of: `supported`, `dev-simplified`, `Mesh only`, `not supported`. A feature "
        f"whose referenced tests do not all pass today is forced to `{UNVERIFIED}` and must not be advertised. "
        "Rules: all tests pass AND substrates both `full` with no registry limits -> supported; "
        "served only on the Mesh -> Mesh only; served with registry limits -> dev-simplified; "
        "not simulated on any substrate -> not supported. The registry level is Vyomi's own statement; the "
        "tests prove behaviour through the real SDK or HTTP, not equivalence to the cloud vendor's models.",
        "",
        "Substrate: `Both` = served on Nano (browser) and Mesh (Codespace appliance); `Mesh` = Mesh only. "
        "The Limited column is verbatim from the registry.",
        "",
    ]
    claims_count: dict[str, int] = {}
    for cloud in ("aws", "gcp", "azure"):
        L += [f"## {CLOUD_NAME[cloud]}", ""]
        for svc in sorted({f["service"] for f in feats if f["cloud"] == cloud}):
            svc_feats = [f for f in feats if f["cloud"] == cloud and f["service"] == svc]
            L += [f"### {svc}", "",
                  "| Feature | Registry level (nano / offline) | Substrate | Works: verified by (run now) | Limited / not simulated (verbatim) | Recommended public claim |",
                  "|---|---|---|---|---|---|"]
            for f in svc_feats:
                ok, how = verified(f, res)
                c = claim(f, ok)
                claims_count[c] = claims_count.get(c, 0) + 1
                lv = f"{f['level'].get('nano', '-')} / {f['level'].get('offline', '-')}"
                lim = " ".join(f"({i + 1}) {l}" for i, l in enumerate(f["limitations"])) or "none declared"
                tier = f" Tier: {f['tier']}." if f["tier"] else ""
                L.append(f"| **{esc(f['title'])}** (`{f['id']}`){tier} | {lv} | {substrate(f)} | {esc(how)} | {esc(lim)} | **{c}** |")
            L.append("")
    L += ["## Summary", "", "| Claim | Features |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(claims_count.items())]
    L += ["", "## Failing or missing tests", ""]
    bad = {t: r for t, r in sorted(res.items()) if r["status"] != "pass"}
    if bad:
        L += ["| Test | Status | Last output |", "|---|---|---|"]
        L += [f"| `{t}` | {r['status']} (rc {r['rc']}) | {esc(r['tail'])} |" for t, r in bad.items()]
    else:
        L.append("None: every referenced test passed in isolation at the recorded commit.")
    L += ["", "## Branch docs that describe each feature", ""]
    L += [f"- `{k}`: {', '.join(v) if v else 'no branch doc names this id'}" for k, v in bd.items()]
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--python", default="/private/tmp/ai-probe-venv13/bin/python")
    ap.add_argument("-j", type=int, default=4)
    a = ap.parse_args()
    feats = load_features()
    if a.run:
        py = a.python if Path(a.python).exists() else sys.executable
        rd = run_all(feats, py, a.j)
    else:
        rd = json.loads(RESULTS.read_text())
    OUT.write_text(render(feats, rd))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(feats)} features, {len(rd['results'])} tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
