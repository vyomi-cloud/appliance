# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure Policy rule engine (Nano / dev_server / unified-ingress core).

Evaluates real Azure Policy ``policyRule`` JSON (``if`` / ``then.effect``) against a resource's ARM
view. Used by ``AzureArm._policy_block`` (``deny`` effect, at create/update time) and
``AzureArm._policy_states`` (compliance over every existing resource).

Supported: ``allOf`` / ``anyOf`` / ``not``; conditions ``equals notEquals like notLike match
matchInsensitively notMatch contains notContains in notIn containsKey notContainsKey exists less
lessOrEquals greater greaterOrEquals``; ``field`` = type / name / location / kind / id / tags /
``tags['k']`` / ``tags.k`` / a full alias (``Microsoft.Storage/storageAccounts/supportsHttpsTrafficOnly``)
resolved against ``properties`` (``[*]`` = any element); ``value`` with ``[parameters('p')]``;
parameter ``defaultValue``; effects ``deny`` / ``audit`` / ``disabled``.

NOT modelled (kept honest): ``count``, template functions other than ``parameters()`` /
``field()``-free literals, ``auditIfNotExists`` / ``deployIfNotExists`` / ``modify`` / ``append``
(these definitions evaluate as ``Unsupported`` and never block), policy initiatives (set definitions),
exemptions, and remediation tasks.

Pure python, no framework imports.
"""
from __future__ import annotations

import fnmatch
import re

ALLOWED_LOCATIONS_ID = "e56962a6-4747-49cd-b67b-bf8b01975c4c"
ALLOWED_TYPES_ID = "a08ec900-254a-4555-9bf5-e42af04b5c5c"
NOT_ALLOWED_TYPES_ID = "6c112d4e-5bc7-47ae-a041-ea2d9dccd749"
REQUIRE_TAG_ID = "871b6d14-10aa-478d-b590-94f262ecfa99"
REQUIRE_TAG_VALUE_ID = "1e30110a-5ceb-460c-a204-c1c3969c6d62"
SECURE_TRANSFER_ID = "404c3081-a854-4457-ae30-26a93ef643f9"

SUPPORTED_EFFECTS = ("deny", "audit", "disabled")


class Unsupported(Exception):
    pass


def _builtin(guid, name, desc, params, rule, mode="Indexed"):
    return {
        "id": f"/providers/Microsoft.Authorization/policyDefinitions/{guid}", "name": guid,
        "type": "Microsoft.Authorization/policyDefinitions",
        "properties": {"policyType": "BuiltIn", "mode": mode, "displayName": name, "description": desc,
                       "parameters": params, "policyRule": rule},
    }


BUILTINS = {b["name"]: b for b in [
    _builtin(ALLOWED_LOCATIONS_ID, "Allowed locations", "Restricts the locations your organization can specify when deploying resources.",
             {"listOfAllowedLocations": {"type": "Array", "metadata": {"displayName": "Allowed locations"}}},
             {"if": {"not": {"field": "location", "in": "[parameters('listOfAllowedLocations')]"}}, "then": {"effect": "deny"}}),
    _builtin(ALLOWED_TYPES_ID, "Allowed resource types", "Restricts the resource types that can be deployed.",
             {"listOfResourceTypesAllowed": {"type": "Array", "metadata": {"displayName": "Allowed resource types"}}},
             {"if": {"not": {"field": "type", "in": "[parameters('listOfResourceTypesAllowed')]"}}, "then": {"effect": "deny"}}),
    _builtin(NOT_ALLOWED_TYPES_ID, "Not allowed resource types", "Restricts the resource types that cannot be deployed.",
             {"listOfResourceTypesNotAllowed": {"type": "Array", "metadata": {"displayName": "Not allowed resource types"}}},
             {"if": {"field": "type", "in": "[parameters('listOfResourceTypesNotAllowed')]"}, "then": {"effect": "deny"}}),
    _builtin(REQUIRE_TAG_ID, "Require a tag on resources", "Enforces existence of a tag.",
             {"tagName": {"type": "String", "metadata": {"displayName": "Tag name"}}},
             {"if": {"field": "[concat('tags[', parameters('tagName'), ']')]", "exists": "false"}, "then": {"effect": "deny"}}),
    _builtin(REQUIRE_TAG_VALUE_ID, "Require a tag and its value on resources", "Enforces a required tag and its value.",
             {"tagName": {"type": "String", "metadata": {"displayName": "Tag name"}},
              "tagValue": {"type": "String", "metadata": {"displayName": "Tag value"}}},
             {"if": {"not": {"field": "[concat('tags[', parameters('tagName'), ']')]", "equals": "[parameters('tagValue')]"}},
              "then": {"effect": "deny"}}),
    _builtin(SECURE_TRANSFER_ID, "Secure transfer to storage accounts should be enabled",
             "Audit requirement of Secure transfer in your storage account.",
             {"effect": {"type": "String", "defaultValue": "Audit", "allowedValues": ["Audit", "Deny", "Disabled"]}},
             {"if": {"allOf": [{"field": "type", "equals": "Microsoft.Storage/storageAccounts"},
                               {"field": "Microsoft.Storage/storageAccounts/supportsHttpsTrafficOnly", "equals": "false"}]},
              "then": {"effect": "[parameters('effect')]"}}),
]}


def guid_of(definition_id: str) -> str:
    return str(definition_id or "").rstrip("/").split("/")[-1].lower()


def find_definition(state: dict, sub: str, definition_id: str):
    """Built-in by GUID, else a custom definition stored in ARM state. ``None`` if unknown."""
    g = guid_of(definition_id)
    for k, v in BUILTINS.items():
        if k.lower() == g:
            return v
    for r in state.values():
        if r.get("_type", "").lower() == "microsoft.authorization/policydefinitions" and r.get("name", "").lower() == g \
                and r.get("_sub") in (sub, None):
            return r
    return None


def _params(defn: dict, assignment: dict) -> dict:
    out = {}
    for n, spec in ((defn.get("properties") or {}).get("parameters") or {}).items():
        if isinstance(spec, dict) and "defaultValue" in spec:
            out[n.lower()] = spec["defaultValue"]
    for n, spec in ((assignment.get("properties") or {}).get("parameters") or {}).items():
        out[n.lower()] = spec.get("value") if isinstance(spec, dict) else spec
    return out


_PARAM = re.compile(r"^\[parameters\('([^']+)'\)\]$")
_CONCAT = re.compile(r"^\[concat\((.*)\)\]$")


def _subst(v, params):
    if isinstance(v, str) and v.startswith("[") and v.endswith("]"):
        m = _PARAM.match(v)
        if m:
            return params.get(m.group(1).lower())
        m = _CONCAT.match(v)
        if m:
            parts = []
            for tok in re.findall(r"'[^']*'|parameters\('[^']+'\)", m.group(1)):
                if tok.startswith("'"):
                    parts.append(tok[1:-1])
                else:
                    parts.append(str(params.get(re.search(r"'([^']+)'", tok).group(1).lower(), "")))
            return "".join(parts)
        if v.startswith("[["):
            return v[1:]
        raise Unsupported(f"template expression {v}")
    return v


def _tag_lookup(tags: dict, name: str):
    for k, val in (tags or {}).items():
        if k.lower() == name.lower():
            return True, val
    return False, None


def _resolve(field: str, res: dict):
    """-> (exists, value-or-list). ``[*]`` aliases return a list of values."""
    f = field.strip()
    low = f.lower()
    props = res.get("properties") or {}
    if low in ("type", "name", "location", "kind", "id"):
        v = res.get(low)
        return (v is not None), v
    if low == "fullname":
        return True, res.get("name")
    if low == "tags":
        return True, res.get("tags") or {}
    m = re.match(r"^tags(?:\['([^']+)'\]|\[\"([^\"]+)\"\]|\.(.+))$", f, re.I)
    if m:
        return _tag_lookup(res.get("tags"), m.group(1) or m.group(2) or m.group(3))
    if low.startswith("identity."):
        cur = res.get("identity") or {}
        path = f.split(".")[1:]
    else:
        # Full alias: Namespace/type[/sub]/path.to.prop -> strip leading Namespace/type segments.
        rest = f
        if "/" in f:
            segs = f.split("/")
            # namespace + type segment(s) + final property path
            rest = segs[-1]
        elif low.startswith("properties."):
            rest = f[len("properties."):]
        cur = props
        path = rest.split(".")
    vals = [cur]
    exists = True
    for seg in path:
        nxt = []
        star = seg.endswith("[*]")
        key = seg[:-3] if star else seg
        for c in vals:
            if isinstance(c, dict):
                hit = next((k for k in c if k.lower() == key.lower()), None)
                if hit is None:
                    continue
                v = c[hit]
                if star and isinstance(v, list):
                    nxt.extend(v)
                else:
                    nxt.append(v)
        if not nxt:
            exists = False
            vals = []
            break
        vals = nxt
    if not exists:
        return False, None
    if any(s.endswith("[*]") for s in path):
        return True, vals
    return True, vals[0]


def _norm(v):
    if isinstance(v, str):
        lv = v.lower()
        if lv in ("true", "false"):
            return lv == "true"
    return v


def _cmp(op: str, lhs, rhs, exists=True):
    if op == "exists":
        want = str(rhs).lower() == "true" if not isinstance(rhs, bool) else rhs
        return bool(exists) == want
    if op in ("equals", "notequals"):
        a, b = _norm(lhs), _norm(rhs)
        eq = (a.lower() == b.lower()) if isinstance(a, str) and isinstance(b, str) else a == b
        return eq if op == "equals" else not eq
    if op in ("like", "notlike"):
        hit = isinstance(lhs, str) and fnmatch.fnmatchcase(lhs.lower(), str(rhs).lower())
        return hit if op == "like" else not hit
    if op in ("match", "matchinsensitively", "notmatch", "notmatchinsensitively"):
        pat = "^" + "".join("[0-9]" if c == "#" else "[A-Za-z]" if c == "?" else "." if c == "." else re.escape(c) for c in str(rhs)) + "$"
        hit = bool(re.match(pat, str(lhs), re.I if "insens" in op else 0))
        return not hit if op.startswith("not") else hit
    if op in ("contains", "notcontains"):
        if isinstance(lhs, (list, tuple)):
            hit = any(str(x).lower() == str(rhs).lower() for x in lhs)
        else:
            hit = str(rhs).lower() in str(lhs).lower()
        return hit if op == "contains" else not hit
    if op in ("in", "notin"):
        coll = rhs if isinstance(rhs, list) else []
        hit = any(str(x).lower() == str(lhs).lower() for x in coll)
        return hit if op == "in" else not hit
    if op in ("containskey", "notcontainskey"):
        hit = isinstance(lhs, dict) and any(k.lower() == str(rhs).lower() for k in lhs)
        return hit if op == "containskey" else not hit
    if op in ("less", "lessorequals", "greater", "greaterorequals"):
        try:
            a, b = float(lhs), float(rhs)
        except (TypeError, ValueError):
            a, b = str(lhs), str(rhs)
        return {"less": a < b, "lessorequals": a <= b, "greater": a > b, "greaterorequals": a >= b}[op]
    raise Unsupported(f"operator {op}")


_OPS = ("equals", "notEquals", "like", "notLike", "match", "matchInsensitively", "notMatch", "notMatchInsensitively",
        "contains", "notContains", "in", "notIn", "containsKey", "notContainsKey", "exists", "less", "lessOrEquals",
        "greater", "greaterOrEquals")


def eval_condition(cond, res: dict, params: dict) -> bool:
    if not isinstance(cond, dict):
        raise Unsupported("condition")
    if "allOf" in cond:
        return all(eval_condition(c, res, params) for c in cond["allOf"])
    if "anyOf" in cond:
        return any(eval_condition(c, res, params) for c in cond["anyOf"])
    if "not" in cond:
        return not eval_condition(cond["not"], res, params)
    op = next((o for o in _OPS if o in cond), None)
    if op is None:
        raise Unsupported("condition operator")
    if "count" in cond or isinstance(cond.get("field"), dict):
        raise Unsupported("count")
    rhs = _subst(cond[op], params)
    if "field" in cond:
        fld = _subst(cond["field"], params)
        exists, lhs = _resolve(str(fld), res)
        if isinstance(lhs, list) and op not in ("contains", "notContains", "in", "notIn") and "[*]" in str(fld):
            # alias[*] with a scalar operator: every element must satisfy (Azure semantics for [*])
            return all(_cmp(op.lower(), x, rhs) for x in lhs) if lhs else _cmp(op.lower(), None, rhs, False)
        return _cmp(op.lower(), lhs, rhs, exists)
    if "value" in cond:
        return _cmp(op.lower(), _subst(cond["value"], params), rhs)
    raise Unsupported("condition without field/value")


def effect_of(rule: dict, params: dict) -> str:
    eff = _subst(((rule or {}).get("then") or {}).get("effect"), params)
    return str(eff or "").lower()


def evaluate(defn: dict, assignment: dict, res: dict):
    """-> (state, effect) where state is 'Compliant' | 'NonCompliant' | 'Unsupported' | 'Disabled'."""
    rule = (defn.get("properties") or {}).get("policyRule") or {}
    params = _params(defn, assignment)
    try:
        eff = effect_of(rule, params)
        if eff == "disabled":
            return "Disabled", eff
        if eff not in SUPPORTED_EFFECTS:
            return "Unsupported", eff
        matched = eval_condition(rule.get("if") or {}, res, params)
    except Unsupported:
        return "Unsupported", ""
    return ("NonCompliant" if matched else "Compliant"), eff


def validate_definition(payload: dict):
    """-> error message or None. Rejects structurally invalid rules at PUT time."""
    props = (payload or {}).get("properties") or {}
    rule = props.get("policyRule")
    if rule is None:
        return None
    if not isinstance(rule, dict) or "if" not in rule or "then" not in ((rule or {})) or "effect" not in (rule.get("then") or {}):
        return "The policy definition 'policyRule' must contain 'if' and 'then.effect'."
    return None


def scope_of(rec: dict):
    return rec.get("_sub"), rec.get("_rg")


def resource_view(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_")} | {"type": rec.get("_type") or rec.get("type")}
