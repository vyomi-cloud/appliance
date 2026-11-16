"""(4) Guardrail semantic classifier precision/recall on 30 labelled prompts per category (15 harmful, 15 benign incl. hard negatives), REAL nomic embeddings.

Part A: end-to-end core.bedrock_guardrails_core.evaluate() with ONE content filter at strength HIGH / MEDIUM / LOW (the production decision = keywords + semantic
thresholds SEM_THRESHOLDS=(0.58,0.68,0.78) + SEM_MARGIN). Part B: semantic-only score sweep and threshold calibration with an even/odd split (calibrate on
even-indexed rows, report on odd-indexed rows) so the proposed numbers are not scored on the data they were fitted to.
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("VYOMI_LLM_ENDPOINT", os.environ.get("MV_GATEWAY_URL", "http://127.0.0.1:28090"))
from core import llm_core as llm
from core import bedrock_guardrails_core as g
from tools.mesh_verify.common import save
from tools.mesh_verify.guardrail_data import D

llm.set_backend(None)
llm._state["endpoint"] = os.environ["VYOMI_LLM_ENDPOINT"]
assert llm.embed(["x"]).get("backend") != "vyomi-hash-embed", "real embedder not reachable"


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": None if p is None else round(p, 3), "recall": None if r is None else round(r, 3), "f1": round(f, 3)}


def main():
    rows = []      # per prompt: category, label, idx, scores (margin-filtered max cosine per category), keyword hit flag
    for cat, items in D.items():
        for i, (lab, text) in enumerate(items):
            sem = g._semantic_scores(text) or {}
            rows.append({"cat": cat, "i": i, "label": lab, "text": text, "score": sem.get(cat, 0.0), "all": {k: round(v, 3) for k, v in sem.items()}})
    res = {"thresholds_default": list(g.SEM_THRESHOLDS), "margin": g.SEM_MARGIN, "A_end_to_end": {}, "B_semantic_only": {}}
    # A: production evaluate() per category and strength
    for strength in ("HIGH", "MEDIUM", "LOW"):
        out = {}
        for cat in D:
            pol = {"blockedInputMessaging": "blocked", "blockedOutputsMessaging": "blocked", "contentPolicyConfig": {"filtersConfig": [{"type": cat, "inputStrength": strength, "outputStrength": strength}]}}
            tp = fp = fn = 0
            for r in (x for x in rows if x["cat"] == cat):
                hit = bool(g.evaluate(pol, r["text"], "INPUT")["blocked"])
                tp += hit and r["label"] == 1; fp += hit and r["label"] == 0; fn += (not hit) and r["label"] == 1
            out[cat] = prf(tp, fp, fn)
        out["ALL"] = prf(sum(v["tp"] for v in out.values()), sum(v["fp"] for v in out.values()), sum(v["fn"] for v in out.values()))
        res["A_end_to_end"][strength] = out
    # B: semantic-only at each cut-off
    for t in (0.58, 0.68, 0.78):
        out = {}
        for cat in D:
            sub = [x for x in rows if x["cat"] == cat]
            out[cat] = prf(sum(x["score"] >= t and x["label"] == 1 for x in sub), sum(x["score"] >= t and x["label"] == 0 for x in sub), sum(x["score"] < t and x["label"] == 1 for x in sub))
        out["ALL"] = prf(sum(v["tp"] for v in out.values()), sum(v["fp"] for v in out.values()), sum(v["fn"] for v in out.values()))
        res["B_semantic_only"][f"cut_{t}"] = out
    # calibration: one global threshold set; candidate cut-offs scanned on EVEN rows
    def stat(sub, t):
        return prf(sum(x["score"] >= t and x["label"] == 1 for x in sub), sum(x["score"] >= t and x["label"] == 0 for x in sub), sum(x["score"] < t and x["label"] == 1 for x in sub))
    even = [x for x in rows if x["i"] % 2 == 0]; odd = [x for x in rows if x["i"] % 2 == 1]
    grid = [round(0.30 + 0.01 * k, 2) for k in range(0, 66)]
    sweep = {t: stat(even, t) for t in grid}
    # LOW cut-off (strength HIGH blocks it): best F1; MEDIUM: smallest t with precision >= 0.90; HIGH: smallest t with precision >= 0.97 (else max precision)
    lo = max(grid, key=lambda t: (sweep[t]["f1"], -t))
    mid = next((t for t in grid if t >= lo and (sweep[t]["precision"] or 0) >= 0.90 and sweep[t]["tp"] > 0), lo)
    hi = next((t for t in grid if t >= mid and (sweep[t]["precision"] or 0) >= 0.97 and sweep[t]["tp"] > 0), mid)
    res["calibration"] = {"fit_on": "even-indexed rows (90 prompts)", "proposed": [lo, mid, hi], "even_fit": {n: sweep[t] for n, t in zip(("lo", "mid", "hi"), (lo, mid, hi))},
                          "odd_heldout": {n: stat(odd, t) for n, t in zip(("lo", "mid", "hi"), (lo, mid, hi))},
                          "odd_heldout_defaults": {n: stat(odd, t) for n, t in zip(("lo", "mid", "hi"), g.SEM_THRESHOLDS)},
                          "all_rows_proposed": {n: stat(rows, t) for n, t in zip(("lo", "mid", "hi"), (lo, mid, hi))}}
    res["score_distribution"] = {cat: {"harmful": sorted(round(x["score"], 2) for x in rows if x["cat"] == cat and x["label"] == 1), "benign": sorted(round(x["score"], 2) for x in rows if x["cat"] == cat and x["label"] == 0)} for cat in D}
    res["rows"] = [{k: x[k] for k in ("cat", "i", "label", "score", "text")} for x in rows]
    print(json.dumps({k: v for k, v in res.items() if k not in ("rows", "score_distribution")}, indent=1))
    save("guardrail", res)


main()
