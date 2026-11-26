"""Azure RBAC evaluator (WP engine-azure; contract: docs/architecture/v4.0/IAM-ENGINE-CONTRACT.md).

Pure Python (stdlib only, Pyodide-safe). `state` is a plain dict built by the host:
  role_assignments  [{id, principal_id, principal_type?, role_definition_id (guid | full id | roleName), scope, condition?,
                      condition_version?, assignment_type? ("active"|"eligible"), activated? bool}]      (PIM: eligible+not activated = inactive)
  role_definitions  custom roles, list or dict; flat {id|name, roleName, actions, notActions, dataActions, notDataActions} or ARM shape
                    {name, properties:{roleName, permissions:[{...}]}}. Built-ins come from core/iam_catalog/azure/_roles.json (or state["builtin_roles"]).
  deny_assignments  [{id, scope, principals:[{id,type}], exclude_principals:[{id,type}], permissions:[{actions,notActions,dataActions,notDataActions}],
                      is_system_protected?, do_not_apply_to_child_scopes?}]   (Everyone = 00000000-0000-0000-0000-000000000000)
  groups            {group_id: [member object ids (users, SPs, nested groups)]}   (transitive membership)
  management_groups {mg_id: parent_mg_id | None};  subscriptions {subscription_id: mg_id}
Request: types.request("azure", {"object_id", "type", "groups": [...]}, action, resource_scope, context, data=bool); context may carry
`request` / `resource` / `principal` / `environment` attribute dicts for ABAC conditions (and `suboperation`)."""
from __future__ import annotations

import ipaddress
import json
import os
import re

from .types import decision, request as _request

EVERYONE = "00000000-0000-0000-0000-000000000000"
_MG = "/providers/microsoft.management/managementgroups/"
_BUILTIN = None


# ------------------------------------------------------------------ wildcards / scopes
def _pat(p):
    return re.compile("^" + ".*".join(re.escape(x) for x in p.split("*")) + "$", re.I | re.S)


def action_matches(pattern, action):
    """Azure action wildcard (`*`, `Microsoft.Compute/*`, `*/read`, `Microsoft.Storage/*/read`), case-insensitive."""
    return bool(_pat(pattern).match(action))


def _any(patterns, action):
    for p in patterns or []:
        if action_matches(p, action):
            return p
    return None


def _norm(scope):
    s = (scope or "/").strip()
    if s in ("", "*"):
        return "/"
    return "/" + s.strip("/").lower() if s.strip("/") else "/"


def _ancestors(scope, state):
    """Lower-cased scopes that can carry an assignment covering `scope`: the scope and each segment-boundary prefix, then the parent
    management-group chain of its subscription, then '/'."""
    s = _norm(scope)
    out = []
    if s != "/":
        parts = s.strip("/").split("/")
        out = ["/" + "/".join(parts[:i]) for i in range(len(parts), 0, -1)]
    # data-plane resource names ("/<storage account>/<container>/<blob>", "/vaults/<v>/...") are not ARM ids: the host supplies
    # state["data_scopes"] {"/acct": "/subscriptions/../storageAccounts/acct", "/vaults/v": ...}; the resource then inherits from that
    # ARM resource (its resource group, subscription, management groups), exactly as Azure authorizes data actions.
    ds = state.get("data_scopes") or {}
    if ds and not s.startswith(("/subscriptions/", "/providers/")):
        for pref in out:
            arm = {k.lower(): v for k, v in ds.items()}.get(pref)
            if arm:
                tail = s[len(pref):]
                return out + [a for a in _ancestors(_norm(arm), dict(state, data_scopes=None)) if a not in out]
    mg = None
    if s.startswith(_MG):
        mg = s[len(_MG):].split("/")[0]
    else:
        m = re.match(r"^/subscriptions/([^/]+)", s)
        if m:
            subs = {k.lower(): v for k, v in (state.get("subscriptions") or {}).items()}
            mg = subs.get(m.group(1))
    mgs = {k.lower(): (v or None) for k, v in (state.get("management_groups") or {}).items()}
    seen = set()
    while mg and mg.lower() not in seen:
        seen.add(mg.lower())
        sc = _MG + mg.lower()
        if sc not in out:
            out.append(sc)
        mg = mgs.get(mg.lower())
    out.append("/")
    return out


def scope_covers(assignment_scope, resource, state=None, child_scopes=True):
    a, r = _norm(assignment_scope), _norm(resource)
    if not child_scopes:
        return a == r
    return a in _ancestors(r, state or {})


# ------------------------------------------------------------------ roles
def _builtin(state):
    global _BUILTIN
    if state.get("builtin_roles") is not None:
        return state["builtin_roles"]
    if _BUILTIN is None:
        try:
            p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iam_catalog", "azure", "_roles.json")
            _BUILTIN = json.load(open(p))["roles"]
        except Exception:
            _BUILTIN = {}
    return _BUILTIN


def _flat_role(d):
    p = d.get("properties") or d
    perms = p.get("permissions")
    if perms is None:
        perms = [{k: p.get(k, []) for k in ("actions", "notActions", "dataActions", "notDataActions")}]
    return {"id": (d.get("name") or d.get("id") or "").split("/")[-1], "roleName": p.get("roleName") or d.get("roleName") or "",
            "assignable_scopes": list(p.get("assignableScopes") or d.get("assignableScopes") or d.get("assignable_scopes") or []),
            "permissions": [{k: list(x.get(k) or []) for k in ("actions", "notActions", "dataActions", "notDataActions")} for x in perms]}


def resolve_role(state, ref):
    """Role by GUID, full roleDefinition id or roleName (custom roles shadow nothing: built-in GUIDs are unique)."""
    if not ref:
        return None
    key = ref.split("/")[-1].lower()
    cr = state.get("role_definitions") or []
    for d in (cr.values() if isinstance(cr, dict) else cr):
        f = _flat_role(d)
        if key in (f["id"].lower(), f["roleName"].lower()):
            return f
    for gid, d in _builtin(state).items():
        if key in (gid.lower(), (d.get("roleName") or "").lower()):
            return {"id": gid, "roleName": d["roleName"], "permissions": [{k: d.get(k, []) for k in ("actions", "notActions", "dataActions", "notDataActions")}]}
    return None


def role_grants(role, action, data=False):
    """Effective permission of one role: (union of actions) minus (notActions), separately for the data plane. Returns the matching
    action pattern or None. notActions are NOT a deny: they only subtract inside the same role."""
    for p in role["permissions"]:
        allow, sub = ("dataActions", "notDataActions") if data else ("actions", "notActions")
        hit = _any(p.get(allow), action)
        if hit and not _any(p.get(sub), action):
            return hit
    return None


# ------------------------------------------------------------------ principals
def expand_groups(state, object_id, groups=()):
    """All group ids the principal belongs to, transitively (request-supplied groups + state['groups'])."""
    g = {x.lower() for x in groups or []}
    members = {k.lower(): [m.lower() for m in v] for k, v in (state.get("groups") or {}).items()}
    todo = [object_id.lower()] + list(g)
    seen = set(todo)
    while todo:
        cur = todo.pop()
        for gid, ms in members.items():
            if cur in ms and gid not in seen:
                seen.add(gid); g.add(gid); todo.append(gid)
    return g


def _ids(principal, state):
    oid = (principal.get("object_id") or principal.get("id") or "").lower()
    return {oid} | expand_groups(state, oid, principal.get("groups"))


# ------------------------------------------------------------------ ABAC conditions
_TOK = re.compile(r"\s*(?:(@(?:Resource|Request|Principal|Environment)\[)|('(?:[^']|'')*')|([(){},!])|([A-Za-z_][A-Za-z0-9_:.\-]*)|(-?\d+(?:\.\d+)?))")


def _lex(s):
    out, i = [], 0
    while i < len(s):
        if not s[i:].strip():
            break
        m = _TOK.match(s, i)
        if not m:
            raise ValueError("condition: unexpected text at %r" % s[i:i + 20])
        if m.group(1):
            j = s.index("]", m.end())
            out.append(("attr", m.group(1)[1:-1].lower(), s[m.end():j].strip())); i = j + 1; continue
        if m.group(2): out.append(("str", m.group(2)[1:-1].replace("''", "'")))
        elif m.group(3): out.append(("p", m.group(3)))
        elif m.group(4): out.append(("w", m.group(4)))
        else: out.append(("num", float(m.group(5))))
        i = m.end()
    return out


class _P:
    def __init__(self, toks): self.t, self.i = toks, 0
    def peek(self):
        t = self.t[self.i] if self.i < len(self.t) else (None, None)
        return (t[0], t[1] if len(t) > 1 else None)
    def nxt(self):
        x = self.t[self.i] if self.i < len(self.t) else (None, None)
        self.i += 1
        return x

    def expr(self):
        n = self.and_()
        while self.peek()[0] == "w" and self.peek()[1].upper() == "OR":
            self.nxt(); n = ("or", n, self.and_())
        return n

    def and_(self):
        n = self.unary()
        while self.peek()[0] == "w" and self.peek()[1].upper() == "AND":
            self.nxt(); n = ("and", n, self.unary())
        return n

    def unary(self):
        k, v = self.peek()
        if k == "p" and v == "!":
            self.nxt(); return ("not", self.unary())
        if k == "p" and v == "(":
            self.nxt(); n = self.expr()
            if self.nxt() != ("p", ")"): raise ValueError("condition: missing ')'")
            return n
        return self.atom()

    def value(self):
        k, *r = self.nxt()
        if k == "str": return ("lit", r[0])
        if k == "num": return ("lit", r[0])
        if k == "w" and r[0].lower() in ("true", "false"): return ("lit", r[0].lower() == "true")
        if k == "attr": return ("attr", r[0], r[1])
        if k == "p" and r[0] == "{": return ("set", self.setbody())
        raise ValueError("condition: bad value %r" % (r,))

    def setbody(self):
        vals = []
        while True:
            k, *r = self.nxt()
            if k == "p" and r[0] == "}": return vals
            if k == "p" and r[0] == ",": continue
            if k in ("str", "num"): vals.append(r[0])
            elif k == "w": vals.append(r[0].lower() == "true" if r[0].lower() in ("true", "false") else r[0])
            elif k is None: raise ValueError("condition: unterminated set")

    def atom(self):
        tok = self.nxt(); k, v = tok[0], tok[1]
        if k == "w" and v in ("ActionMatches", "SubOperationMatches"):
            if self.nxt() != ("p", "{"): raise ValueError("condition: %s needs {…}" % v)
            return (v, self.setbody())
        if k == "w" and v in ("Exists", "NotExists"):
            a = self.nxt()
            if a[0] != "attr": raise ValueError("condition: Exists needs an attribute")
            return (v, a[1], a[2])
        if k == "attr":
            op = self.nxt()
            if op[0] != "w": raise ValueError("condition: operator expected")
            return ("cmp", ("attr", v, tok[2]), op[1], self.value())
        raise ValueError("condition: unexpected %r" % ((k, v),))


def parse_condition(text):
    p = _P(_lex(text)); n = p.expr()
    if p.i != len(p.t): raise ValueError("condition: trailing tokens")
    return n


_SRC = {"resource": "resource", "request": "request", "principal": "principal", "environment": "environment"}
_MISSING = object()


def _attr(ctx, src, name):
    d = ctx.get(_SRC[src]) or {}
    if name in d: return d[name]
    low = name.lower()
    for k, v in d.items():
        if k.lower() == low: return v
    return _MISSING


def _scalar_op(op, a, b):
    """op without cardinality prefix; a = attribute value, b = literal. Raises ValueError for unknown ops."""
    o = op.lower()
    s = lambda x: x if isinstance(x, str) else str(x)
    if o in ("stringequals", "guidequals"): return s(a) == s(b) if o == "stringequals" else s(a).lower() == s(b).lower()
    if o in ("stringnotequals", "guidnotequals"): return not _scalar_op(op.replace("Not", ""), a, b)
    if o == "stringequalsignorecase": return s(a).lower() == s(b).lower()
    if o == "stringnotequalsignorecase": return s(a).lower() != s(b).lower()
    if o == "stringstartswith": return s(a).startswith(s(b))
    if o == "stringnotstartswith": return not s(a).startswith(s(b))
    if o in ("stringlike", "stringmatches"): return bool(re.fullmatch(".*".join(re.escape(x) for x in s(b).split("*")), s(a), re.S))
    if o in ("stringnotlike", "stringnotmatches"): return not _scalar_op("StringLike", a, b)
    if o == "stringlikeignorecase": return bool(re.fullmatch(".*".join(re.escape(x) for x in s(b).split("*")), s(a), re.S | re.I))
    if o.startswith("numeric"):
        x, y = float(a), (float(b) if not isinstance(b, (list, tuple)) else None)
        t = o[7:]
        if t == "equals": return x == y
        if t == "notequals": return x != y
        if t == "lessthan": return x < y
        if t == "lessthanequals": return x <= y
        if t == "greaterthan": return x > y
        if t == "greaterthanequals": return x >= y
    if o == "boolequals": return _bool(a) == _bool(b)
    if o == "boolnotequals": return _bool(a) != _bool(b)
    if o.startswith("datetime"):
        x, y = s(a), s(b); t = o[8:]
        if t == "equals": return x == y
        if t == "notequals": return x != y
        if t == "lessthan": return x < y
        if t == "lessthanequals": return x <= y
        if t == "greaterthan": return x > y
        if t == "greaterthanequals": return x >= y
    if o in ("ipmatch", "ipnotmatch", "ipinrange"):
        hit = ipaddress.ip_address(s(a)) in ipaddress.ip_network(s(b), strict=False)
        return hit if o != "ipnotmatch" else not hit
    raise ValueError("unsupported condition operator " + op)


def _bool(x):
    return x if isinstance(x, bool) else str(x).strip().lower() == "true"


def _compare(op, lhs, rhs):
    card = None
    if ":" in op:
        card, op = op.split(":", 1)
    ls = lhs if isinstance(lhs, (list, tuple, set)) else [lhs]
    rs = rhs if isinstance(rhs, (list, tuple, set)) else [rhs]
    if card is None:
        if isinstance(lhs, (list, tuple, set)): return False       # single-valued operator on a multi-valued attribute
        neg = bool(re.match(r"(string|guid|bool|ip|numeric)not", op.lower()))
        f = all if neg else any
        return f(_scalar_op(op, lhs, r) for r in rs)
    c = card.lower()
    inner = lambda x: [_scalar_op(op, x, r) for r in rs]
    if c == "foranyofanyvalues": return any(any(inner(x)) for x in ls)
    if c == "foranyofallvalues": return any(all(inner(x)) for x in ls)
    if c == "forallofanyvalues": return all(any(inner(x)) for x in ls)
    if c == "forallofallvalues": return all(all(inner(x)) for x in ls)
    raise ValueError("unsupported cardinality " + card)


def _ev(n, action, ctx):
    t = n[0]
    if t == "or": return _ev(n[1], action, ctx) or _ev(n[2], action, ctx)
    if t == "and": return _ev(n[1], action, ctx) and _ev(n[2], action, ctx)
    if t == "not": return not _ev(n[1], action, ctx)
    if t == "ActionMatches": return any(action_matches(p, action) for p in n[1])
    if t == "SubOperationMatches":
        sub = ctx.get("suboperation")
        return sub is not None and any(action_matches(p, sub) for p in n[1])
    if t in ("Exists", "NotExists"):
        has = _attr(ctx, n[1], n[2]) is not _MISSING
        return has if t == "Exists" else not has
    if t == "cmp":
        lhs = _attr(ctx, n[1][1], n[1][2])
        if lhs is _MISSING: return False            # missing attribute -> comparison false (recorded in the branch doc)
        v = n[3]
        if v[0] == "lit": rhs = v[1]
        elif v[0] == "set": rhs = v[1]
        else:
            rhs = _attr(ctx, v[1], v[2])
            if rhs is _MISSING: return False
        return _compare(n[2], lhs, rhs)
    raise ValueError("bad condition node")


def eval_condition(text, action, context=None):
    """Evaluate an ABAC role-assignment condition for `action`. Unparseable / unsupported conditions evaluate False (fail closed)."""
    if not text or not str(text).strip():
        return True
    try:
        return bool(_ev(parse_condition(text), action, context or {}))
    except (ValueError, TypeError, IndexError):
        return False


# ------------------------------------------------------------------ evaluation
def _ts(v):
    import calendar
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)", str(v or ""))
    return float(calendar.timegm(tuple(int(x) for x in m.groups()) + (0, 0, 0))) if m else None


def _active(ra):
    """An eligible-but-not-activated assignment grants nothing; a time-bound one (PIM activation, AdminAssign with an expiry) grants only
    inside [start_date_time, end_date_time) -- so access appears at activation and disappears at expiry with no sweeper."""
    if str(ra.get("assignment_type") or "active").lower() == "eligible" and not ra.get("activated"):
        return False
    if ra.get("start_date_time") or ra.get("end_date_time"):
        import time
        now = time.time()
        s, e = _ts(ra.get("start_date_time")), _ts(ra.get("end_date_time"))
        if (s is not None and s > now) or (e is not None and e <= now):
            return False
    return True


def _assignable(role, scope, state):
    """Custom-role assignableScopes: the assignment scope must lie inside one of them ('/' or no list = anywhere, as every built-in)."""
    asc = role.get("assignable_scopes") or []
    if not asc or any(str(x).strip() in ("/", "") for x in asc):
        return True
    return any(scope_covers(x, scope, state) for x in asc)


def _deny_applies(d, req, ids, state, data):
    if not scope_covers(d.get("scope"), req["resource"], state, not d.get("do_not_apply_to_child_scopes")):
        return None
    ps = d.get("principals") or []
    if not any((p.get("id") or "").lower() == EVERYONE or (p.get("id") or "").lower() in ids for p in ps):
        return None
    if any((p.get("id") or "").lower() in ids for p in d.get("exclude_principals") or []):
        return None
    for perm in d.get("permissions") or []:
        allow, sub = ("dataActions", "notDataActions") if data else ("actions", "notActions")
        hit = _any(perm.get(allow), req["action"])
        if hit and not _any(perm.get(sub), req["action"]):
            return hit
    return None


def evaluate(req, state):
    """Entry point. SAS / Shared Key principals (storage data plane) are authorised by azure_sas, everything else by Azure RBAC (`_rbac`)."""
    if (req.get("principal") or {}).get("type") in ("sas", "sharedkey"):
        from . import azure_sas
        return azure_sas.evaluate(req, state, rbac=_rbac)
    return _rbac(req, state)


def _rbac(req, state):
    """Azure RBAC decision: deny assignments first (explicit_deny), then any role assignment (scope-inherited, principal/group matched,
    active, condition true) whose role grants the action in the right plane (allow), else implicit_deny."""
    state = state or {}
    pr = req.get("principal") or {}
    ids = _ids(pr, state)
    # The gate always states the plane (map_azure sets data True/False). A caller that does not (effective-access / /evaluate, which only has the
    # action string) is evaluated in both planes: an action is a control-plane action OR a data action, never both for the same role.
    planes = [bool(req["data"])] if req.get("data") is not None else [False, True]
    ctx = req.get("context") or {}
    denies = []
    for d in state.get("deny_assignments") or []:
        hit = next((h for h in (_deny_applies(d, req, ids, state, pl) for pl in planes) if h), None)
        if hit:
            denies.append({"source": "deny_assignment", "id": d.get("id", ""), "effect": "Deny",
                           "statement": {"scope": d.get("scope"), "matchedAction": hit, "isSystemProtected": bool(d.get("is_system_protected"))}})
    if denies:
        return decision(False, "explicit_deny", denies)
    grants = []
    for ra in state.get("role_assignments") or []:
        if (ra.get("principal_id") or "").lower() not in ids or not _active(ra):
            continue
        if not scope_covers(ra.get("scope"), req["resource"], state):
            continue
        role = resolve_role(state, ra.get("role_definition_id"))
        if not role:
            continue
        if not _assignable(role, ra.get("scope"), state):      # a custom role only exists inside its assignableScopes
            continue
        hit = next((h for h in (role_grants(role, req["action"], pl) for pl in planes) if h), None)
        if not hit:
            continue
        if ra.get("condition") and not eval_condition(ra["condition"], req["action"], ctx):
            continue
        st = {"roleName": role["roleName"], "roleDefinitionId": role["id"], "scope": ra.get("scope"), "principalId": ra.get("principal_id"),
              "matchedAction": hit}
        if ra.get("condition"): st["condition"] = ra["condition"]
        grants.append({"source": "role_assignment", "id": ra.get("id", ""), "effect": "Allow", "statement": st})
    if grants:
        return decision(True, "allow", grants)
    return decision(False, "implicit_deny", [])


def check_access(state, principal_id, action, scope, data=False, groups=None, principal_type="User", context=None):
    """ARM `checkAccess`-shaped result (accessDecision / isDataAction / roleAssignment / denyAssignment) plus the engine decision."""
    d = evaluate(_request("azure", {"object_id": principal_id, "type": principal_type, "groups": list(groups or [])}, action, scope, context, data=bool(data)), state)
    ra = next((m for m in d["matched"] if m["source"] == "role_assignment"), None)
    da = next((m for m in d["matched"] if m["source"] == "deny_assignment"), None)
    return {"actionId": action, "accessDecision": "Allowed" if d["allowed"] else "NotAllowed", "isDataAction": bool(data),
            "roleAssignment": ra and {"id": ra["id"], **ra["statement"]}, "denyAssignment": da and {"id": da["id"], **da["statement"]},
            "timeToLiveInMs": 300000, "decision": d}
