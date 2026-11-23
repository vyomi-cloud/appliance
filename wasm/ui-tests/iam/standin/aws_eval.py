"""STAND-IN AWS evaluator (identity policies, Action/NotAction/Resource wildcards, explicit deny > allow). The real one is aws_eval.py (engine-aws WP)."""
import fnmatch
from core.iam_engine.types import decision


def _m(pat, val, fold=False):
    pats = [pat] if isinstance(pat, str) else pat
    if fold:
        val = val.lower()
    return any(fnmatch.fnmatchcase(val, p.lower() if fold else p) for p in pats)


def evaluate(req, state):
    allowed, matched = False, []
    for pol in state.get("policies", {}).get(req["principal"].get("arn"), []):
        for i, st in enumerate(pol["Statement"]):
            if "Action" in st and not _m(st["Action"], req["action"], True):
                continue
            if "NotAction" in st and _m(st["NotAction"], req["action"], True):
                continue
            if not _m(st.get("Resource", "*"), req["resource"]):
                continue
            m = {"source": "identity", "id": f"policy/{i}", "effect": st["Effect"]}
            if st["Effect"] == "Deny":
                return decision(False, "explicit_deny", [m])
            allowed, matched = True, [m]
    return decision(allowed, "allow" if allowed else "implicit_deny", matched)
