"""AWS policy simulation + policy-checks answered by the faithful engine (pure Python, Pyodide-safe: no fastapi / socket).

  simulate(...)               SimulatePrincipalPolicy / SimulateCustomPolicy -> [EvaluationResult dicts in the IAM API's own key names]
  context_keys(...)           GetContextKeysForPrincipalPolicy / GetContextKeysForCustomPolicy
  statement_spans(text)       (line, column) spans of each Statement element of a policy text (MatchedStatements.StartPosition/EndPosition)
  catalog(prefix)             the in-scope AWS service catalog slice (core/iam_catalog/aws/<prefix>.json) or None

Decisions come from `aws_eval.evaluate` over the REAL state (identity policies, boundary, SCP/RCP, resource policies); nothing here
re-implements evaluation. The XML wire rendering lives in core/iam_core.py (it already owns the IAM Query envelope)."""
from __future__ import annotations

import json
import re

from . import aws_eval, catalog_loader

_DEC = {"allow": "allowed", "explicit_deny": "explicitDeny", "implicit_deny": "implicitDeny"}
_VAR = re.compile(r"\$\{([^}]*)\}")
_FORCE_SRC = ("scp", "rcp")
_ENGINE_KEYS = {"aws:principalarn", "aws:principalaccount", "aws:principaltype", "aws:username", "aws:userid", "aws:currenttime", "aws:resourcearn",
                "aws:sourceowner", "aws:principalorgid", "aws:tagkeys"}


# ------------------------------------------------------------------ catalog access (Mesh: disk fallback; Nano: preloaded text)
_DISK = {}


def catalog(prefix):
    """Catalog slice of an AWS service prefix (`s3`, `iam`...), or None when this bundle has none (the caller must then NOT claim the
    action is invalid: an unknown service is unverifiable, not wrong)."""
    prefix = str(prefix or "").lower()
    if not re.fullmatch(r"[a-z0-9-]+", prefix):
        return None
    try:
        return catalog_loader.load("aws", prefix)
    except (catalog_loader.CatalogUnavailable, ValueError):
        pass
    if prefix in _DISK:
        return _DISK[prefix]
    cat = None
    try:
        import os
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iam_catalog", "aws", prefix + ".json")
        with open(p, encoding="utf-8") as f:
            cat = json.load(f)
    except Exception:
        cat = None
    _DISK[prefix] = cat
    return cat


def catalog_prefixes():
    """Service prefixes that have a catalog (Mesh: the directory listing; Nano: whatever the host preloaded)."""
    out = set()
    try:
        import os
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iam_catalog", "aws")
        out.update(f[:-5] for f in os.listdir(d) if f.endswith(".json"))
    except Exception:
        pass
    try:
        out.update(k.split("/", 1)[1] for k in catalog_loader.loaded() if k.startswith("aws/"))
    except Exception:
        pass
    return sorted(out)


# ------------------------------------------------------------------ policy text helpers
def parse_doc(raw):
    """policy JSON text | dict -> dict (raises ValueError)."""
    if isinstance(raw, dict):
        return raw
    try:
        d = json.loads(raw)
    except Exception:
        raise ValueError("not valid JSON")
    if not isinstance(d, dict):
        raise ValueError("policy must be a JSON object")
    return d


def statement_spans(text):
    """-> [((line, col, offset), (line, col, offset)), ...] one per element of the top-level "Statement" (1-based line, 0-based column), measured in
    `text` exactly as given. A single-object Statement yields one span. [] when `text` is not scannable."""
    try:
        n, i = len(text), 0
        depth, spans, in_stmt, stmt_depth = 0, [], False, None
        starts = []
        key_stack = []          # key name by depth for objects
        pending_key = None
        lines = [0]
        for k, ch in enumerate(text):
            if ch == "\n":
                lines.append(k + 1)

        def pos(off):
            lo, hi = 0, len(lines) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if lines[mid] <= off:
                    lo = mid
                else:
                    hi = mid - 1
            return (lo + 1, off - lines[lo], off)

        stack = []              # (opening char, key that opened it)

        def is_stmt():
            d = len(stack)
            return (d == 3 and stack[1] == ("[", "Statement") and stack[2][0] == "{") or (d == 2 and stack[1] == ("{", "Statement"))

        while i < n:
            ch = text[i]
            if ch == '"':
                j = i + 1
                while j < n and text[j] != '"':
                    j += 2 if text[j] == "\\" else 1
                k = j + 1
                while k < n and text[k] in " \t\r\n":
                    k += 1
                pending_key = text[i + 1:j] if (k < n and text[k] == ":") else pending_key
                i = j + 1
                continue
            if ch in "{[":
                stack.append((ch, pending_key))
                if ch == "{" and is_stmt():
                    starts.append(i)
                pending_key = None
            elif ch in "}]":
                if ch == "}" and stack and is_stmt() and starts:
                    spans.append((pos(starts.pop()), pos(i + 1)))
                if stack:
                    stack.pop()
                pending_key = None
            i += 1
        return spans
    except Exception:
        return []


def _stmt_list(doc):
    st = (doc or {}).get("Statement")
    return [st] if isinstance(st, dict) else [s for s in (st or []) if isinstance(s, dict)]


# ------------------------------------------------------------------ simulate
def _policy_name(pid):
    if pid.startswith("inline:"):
        return pid[7:]
    if ":policy/" in pid:
        return pid.rsplit("/", 1)[-1]
    return pid


def _ctx_value(entry):
    vals = [str(v) for v in (entry.get("ContextKeyValues") or [])]
    typ = str(entry.get("ContextKeyType") or "").lower()
    if len(vals) == 1 and not typ.endswith("list"):
        return vals[0]
    return vals


def _stmt_index(rec_id, doc):
    """Index of the statement a matched-record id (`<policyId>#<Sid|index>`) names inside `doc`."""
    tag = rec_id.rsplit("#", 1)[-1]
    sts = _stmt_list(doc)
    for i, s in enumerate(sts):
        if s.get("Sid") is not None and str(s["Sid"]) == tag:
            return i
    return int(tag) if tag.isdigit() and int(tag) < len(sts) else None


def simulate(principal, actions, resources, context_entries=None, state=None, *, source_docs=None, boundary_docs=None,
             resource_policy=None, resource_owner=None, with_org=True):
    """-> list of EvaluationResult dicts: {EvalActionName, EvalResourceName, EvalDecision, MatchedStatements[{SourcePolicyId,
    SourcePolicyType, StartPosition{Line,Column}, EndPosition{Line,Column}}], MissingContextValues[], OrganizationsDecisionDetail?,
    PermissionsBoundaryDecisionDetail?}.

    principal      engine principal: {"arn","type","account","tags"?, "policies"?: [{id, document, kind?, text?}], "boundary"?}
    source_docs    extra identity policies, [{"id","text"|"document","kind"}] (PolicyInputList.N -> id "PolicyInputList.N")
    boundary_docs  extra boundary policies (PermissionsBoundaryPolicyInputList), same shape
    resource_policy  text|dict applied to every resource (SimulatePrincipalPolicy ResourcePolicy)
    context_entries  [{"ContextKeyName","ContextKeyType","ContextKeyValues":[..]}]"""
    state = dict(state or {})
    pr = dict(principal or {})
    registry = {}               # policy id -> (type, name, doc, text)

    def register(pid, kind, doc, text=None):
        registry[pid] = (kind, _policy_name(pid), doc, text if text is not None else json.dumps(doc, indent=2))

    # identity policies the host already attached to the principal (+ groups), recorded with their owner kind
    ent_kind = "user" if ":user/" in (pr.get("arn") or "") else "role" if ":role/" in (pr.get("arn") or "") or ":assumed-role/" in (pr.get("arn") or "") else "user"
    own = []
    for p in pr.get("policies") or []:
        if isinstance(p, dict) and "document" in p:
            pid = str(p.get("id") or "identity")
            kind = p.get("kind") or ("aws-managed" if pid.startswith("arn:aws:iam::aws:policy/") else "user-managed" if pid.startswith("arn:") else ent_kind)
            register(pid, kind, p["document"], p.get("text"))
            own.append({"id": pid, "document": p["document"]})
        else:
            own.append(p)
    pr["policies"] = own
    for g in (pr.get("groups") or []):
        grp = (state.get("groups") or {}).get(g) if isinstance(g, str) else None
        for p in (grp or {}).get("policies") or []:
            if isinstance(p, dict) and "document" in p:
                pid = str(p.get("id") or "identity")
                register(pid, "aws-managed" if pid.startswith("arn:aws:iam::aws:policy/") else "user-managed" if pid.startswith("arn:") else "group", p["document"], p.get("text"))
    for sd in source_docs or []:
        doc = sd["document"] if "document" in sd else parse_doc(sd["text"])
        register(sd["id"], sd.get("kind") or "none", doc, sd.get("text"))
        pr["policies"].append({"id": sd["id"], "document": doc})
    if boundary_docs:
        bl = list(pr.get("boundary") or [])
        for bd in boundary_docs:
            doc = bd["document"] if "document" in bd else parse_doc(bd["text"])
            bl.append({"id": bd["id"], "document": doc})
            register(bd["id"], "none", doc, bd.get("text"))
        pr["boundary"] = bl
    # state-attached boundary docs are bare documents (engine ids "boundary[i]")
    rp_doc = None
    if resource_policy is not None and resource_policy != "":
        rp_doc = parse_doc(resource_policy)
        register("resource", "resource", rp_doc, resource_policy if isinstance(resource_policy, str) else None)
    if not with_org:
        state["scps"], state["rcps"] = [], []
    ctx = {}
    for e in context_entries or []:
        if e.get("ContextKeyName"):
            ctx[e["ContextKeyName"]] = _ctx_value(e)
    org_present = bool(state.get("scps") or state.get("rcps"))
    has_boundary = bool(pr.get("boundary") or ((state.get("principals") or {}).get(pr.get("arn") or "") or {}).get("boundary"))
    spans_cache = {}

    def span_of(pid, rec_id):
        ent = registry.get(pid)
        if not ent:
            return None
        if pid not in spans_cache:
            spans_cache[pid] = statement_spans(ent[3])
        idx = _stmt_index(rec_id, ent[2])
        sp = spans_cache[pid]
        return sp[idx] if idx is not None and idx < len(sp) else None

    scan = [(v[2], v[0] == "resource") for v in registry.values()]
    for b in ((state.get("principals") or {}).get(pr.get("arn") or "") or {}).get("boundary") or []:
        scan.append((b["document"] if isinstance(b, dict) and "document" in b else b, False))
    ctx_keys = {str(k).lower() for k in ctx}

    def missing_keys(action, res):
        got, seen = [], set()
        for doc, rb in scan:
            for st in _stmt_list(doc):
                if not st.get("Condition") or not aws_eval._stmt_applies({k: v for k, v in st.items() if k != "Condition"}, action, res, aws_eval._Ctx({}), rb):
                    continue
                for op in st["Condition"].values():
                    for key in (op or {}):
                        kl = str(key).lower()
                        if kl in ctx_keys or kl in _ENGINE_KEYS or kl.startswith(("aws:principaltag/", "aws:resourcetag/")) or kl in seen:
                            continue
                        seen.add(kl)
                        got.append(str(key))
        return got

    out = []
    for action in actions:
        for res in resources or ["*"]:
            req = {"cloud": "aws", "principal": pr, "action": action, "resource": res, "context": dict(ctx)}
            if rp_doc is not None:
                req["resource_policy"] = rp_doc
            if resource_owner:
                req["resource_account"] = resource_owner
            d = aws_eval.evaluate(req, state)
            matched = []
            for m in d.get("matched") or []:
                if m.get("source") in _FORCE_SRC:
                    continue
                pid = m["id"].rsplit("#", 1)[0]
                ent = registry.get(pid)
                kind = ent[0] if ent else ("resource" if m.get("source") == "resource" else "none")
                rec = {"SourcePolicyId": ent[1] if ent else _policy_name(pid), "SourcePolicyType": kind}
                sp = span_of(pid, m["id"])
                if sp:
                    rec["StartPosition"] = {"Line": sp[0][0], "Column": sp[0][1]}
                    rec["EndPosition"] = {"Line": sp[1][0], "Column": sp[1][1]}
                matched.append(rec)
            res_rec = {"EvalActionName": action, "EvalResourceName": res, "EvalDecision": _DEC.get(d["reason"], "implicitDeny"),
                       "MatchedStatements": matched,
                       "MissingContextValues": [k for k in dict.fromkeys(list(d.get("missingContext") or []) + missing_keys(action, res))
                                                if not str(k).lower().startswith("aws:principaltag/")]}   # principal tags are the simulated principal's own (existing contract: test_iam_sweepiam2_core)
            denied_by = {m.get("source") for m in d.get("matched") or [] if m.get("effect") == "Deny"}
            if org_present:
                res_rec["OrganizationsDecisionDetail"] = {"AllowedByOrganizations": not (d.get("failedLayer") in _FORCE_SRC or denied_by & set(_FORCE_SRC))}
            if has_boundary:
                res_rec["PermissionsBoundaryDecisionDetail"] = {"AllowedByPermissionsBoundary": not (d.get("failedLayer") == "boundary" or "boundary" in denied_by)}
            out.append(res_rec)
    return out


# ------------------------------------------------------------------ context keys
def referenced_keys(docs):
    """Condition keys (and policy variables) referenced by the policies, in first-seen order, with the catalog's verbatim casing."""
    seen, out = set(), []

    def add(k):
        k = str(k)
        if k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)

    for doc in docs:
        for st in _stmt_list(doc):
            for op in (st.get("Condition") or {}).values():
                for key, val in (op or {}).items():
                    add(key)
                    for v in (val if isinstance(val, list) else [val]):
                        for m in _VAR.finditer(str(v)):
                            add(m.group(1))
            for fld in ("Resource", "NotResource", "Action"):
                v = st.get(fld)
                for s in (v if isinstance(v, list) else [v]):
                    for m in _VAR.finditer(str(s or "")):
                        add(m.group(1))
    # restore the catalog's verbatim casing where the service catalog knows the key
    keys = {}
    for k in out:
        pre = k.split(":", 1)[0].lower()
        if pre == "aws":
            continue
        cat = catalog(pre)
        for ck in (cat or {}).get("conditionKeys", {}):
            keys.setdefault(ck.lower(), ck)
    return [keys.get(k.lower(), k) for k in out]


def context_keys(docs):
    """GetContextKeysForPrincipalPolicy / ForCustomPolicy: keys referenced by the given policy documents."""
    return referenced_keys(docs)
