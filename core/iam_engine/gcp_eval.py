"""GCP IAM evaluation engine (contract: docs/architecture/v4.0/IAM-ENGINE-CONTRACT.md).

Order, as in Google Cloud: (1) principal access boundary (PAB) first filter, (2) deny policies (deny wins), (3) allow policies with
hierarchy inheritance (org > folder > project > resource, union), IAM Conditions via a CEL subset (see CEL section).
Pure Python (json/os/re/datetime only) so it vendors to Pyodide unchanged.

`state` (plain dict, built by the host adapter):
  allow_policies : {attachment_point: {"bindings":[{"role","members":[..],"condition":{"expression","title"}?}]}}
  deny_policies  : {attachment_point: [{"name","rules":[{"denyRule":{"deniedPrincipals","exceptionPrincipals",
                    "deniedPermissions","exceptionPermissions","denialCondition"}}]}]}   (a dict keyed by policy id is accepted too)
  pab_policies   : {name: {"rules":[{"resources":[..],"effect":"ALLOW"}]}}   (legacy {"details":{"rules":..}} accepted)
  pab_bindings   : [{"policy": name, "target": {"principal"|"principalSet": member}, "condition"?}]  (list or dict)
  custom_roles   : {"projects/p/roles/x": {"includedPermissions":[..], "deleted"?}}
  groups         : {"group:a@x.com": ["user:u@x.com", "group:b@x.com", ...]}   (nested groups expanded)
  hierarchy      : {"projects/p": "folders/1", "folders/1": "organizations/9", "projects/_/buckets/b": "projects/p"}
  catalog        : optional {"roles": {role: [perms]}, "permissions": [..]} (default: core/iam_catalog/gcp/*.json)
Attachment points / resource names may be `//svc.googleapis.com/projects/p/...` or the bare path."""
from __future__ import annotations

import datetime as _dt
import fnmatch
import json
import os
import re

try:  # package import (appliance) or flat import (vendored)
    from .types import decision
except ImportError:  # pragma: no cover
    from types import SimpleNamespace  # noqa: F401

    def decision(allowed, reason, matched=None, **extra):
        return {"allowed": bool(allowed), "reason": reason, "matched": matched or [], **extra}

# ------------------------------------------------------------------ catalog
_CATALOG_CACHE: dict = {}


def load_catalog(path: str | None = None) -> dict:
    """{"roles": {role: [perms]}, "permissions": sorted list} merged over core/iam_catalog/gcp/*.json (cached)."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iam_catalog", "gcp")
    if path in _CATALOG_CACHE:
        return _CATALOG_CACHE[path]
    roles: dict = {}
    perms: set = set()
    try:
        for fn in sorted(os.listdir(path)):
            if not fn.endswith(".json") or fn.startswith("_"):
                continue
            with open(os.path.join(path, fn), encoding="utf-8") as fh:
                d = json.load(fh)
            perms.update((d.get("permissions") or {}).keys())
            for r, v in (d.get("roles") or {}).items():
                roles.setdefault(r, set()).update(v.get("permissions") or [])
    except OSError:
        pass
    for v in roles.values():
        perms.update(v)
    cat = {"roles": {r: sorted(v) for r, v in roles.items()}, "permissions": sorted(perms)}
    _CATALOG_CACHE[path] = cat
    return cat


_VIEW_VERBS = ("get", "list", "search", "export", "read", "check", "validate", "view", "query", "describe", "lookup")


def _verb(perm: str) -> str:
    return perm.rsplit(".", 1)[-1]


def _basic_role_permissions(role: str, cat: dict) -> set:
    """roles/owner|editor|viewer are not published as permission lists in the catalog; derived approximation (see branch doc):
    viewer = read-style verbs; editor = everything but IAM/policy administration and project/org lifecycle; owner = everything."""
    allp = cat.get("permissions") or []
    if role == "roles/owner":
        return set(allp)
    if role == "roles/viewer" or role == "roles/browser":
        if role == "roles/browser":
            return {p for p in allp if p.startswith(("resourcemanager.projects.get", "resourcemanager.projects.list", "resourcemanager.folders.", "resourcemanager.organizations.get")) and _verb(p) in ("get", "list")}
        return {p for p in allp if _verb(p).startswith(_VIEW_VERBS) and not p.endswith("IamPolicy") and not p.startswith("iam.roles")} | {p for p in allp if p.endswith("getIamPolicy")}
    if role == "roles/editor":
        out = set()
        for p in allp:
            if p.endswith("setIamPolicy") or p.startswith(("iam.roles.", "resourcemanager.projects.delete", "resourcemanager.projects.undelete", "resourcemanager.projects.move", "resourcemanager.organizations.", "orgpolicy.policy.set")):
                continue
            out.add(p)
        return out
    return set()


def role_permissions(role: str, state: dict) -> set:
    cr = (state.get("custom_roles") or {}).get(role)
    if cr is not None:
        if cr.get("deleted") or str(cr.get("stage", "")).upper() == "DISABLED":
            return set()
        return set(cr.get("includedPermissions") or cr.get("permissions") or [])
    cat = state.get("catalog") or load_catalog()
    if role in ("roles/owner", "roles/editor", "roles/viewer", "roles/browser") and role not in cat["roles"]:
        return _basic_role_permissions(role, cat)
    return set(cat["roles"].get(role) or [])


# ------------------------------------------------------------------ names & hierarchy
def split_resource(name: str):
    """'//svc.googleapis.com/projects/p/x' -> ('svc.googleapis.com', 'projects/p/x'); bare path -> ('', path)."""
    name = name or ""
    if name.startswith("//"):
        host, _, rest = name[2:].partition("/")
        return host, rest.strip("/")
    return "", name.strip("/")


def _norm_key(k: str) -> str:
    return split_resource(k)[1]


def ancestry(resource: str, state: dict) -> list:
    """Attachment-point paths from most specific to the root: resource prefixes, then parents via state['hierarchy']."""
    _, path = split_resource(resource)
    segs = [s for s in path.split("/") if s]
    out: list = []
    seen: set = set()

    def add(n):
        if n and n not in seen:
            seen.add(n)
            out.append(n)

    if segs:
        add("/".join(segs))
        for i in range(len(segs) - 1, 0, -1):
            add("/".join(segs[:i]))
    hier = {_norm_key(k): _norm_key(v) for k, v in (state.get("hierarchy") or {}).items()}
    i = 0
    while i < len(out):  # BFS over parents, including parents of prefixes
        p = hier.get(out[i])
        if p:
            add(p)
        i += 1
    return out


# ------------------------------------------------------------------ principals
def _email_of(member: str) -> str:
    return member.split(":", 1)[1] if ":" in member else ""


def _group_closure(member: str, state: dict) -> set:
    groups = {_norm_member(k): [_norm_member(m) for m in v] for k, v in (state.get("groups") or {}).items()}
    found: set = set()
    changed = True
    while changed:
        changed = False
        for g, mem in groups.items():
            if g in found:
                continue
            if member in mem or any(f in mem for f in found):
                found.add(g)
                changed = True
    return found


def _norm_member(m: str) -> str:
    return m.strip() if isinstance(m, str) else m


def principal_identities(principal: dict, state: dict) -> set:
    """Every member string a binding may name that includes this caller."""
    member = _norm_member((principal or {}).get("member") or "")
    ids: set = {"allUsers"} if member in ("", "allUsers") else {"allUsers", "allAuthenticatedUsers"}
    if member in ("", "allUsers"):
        ids.add("allUsers")
        return ids
    ids.add(member)
    if member == "allAuthenticatedUsers":
        return ids
    ids.add("principalSet://goog/public:all")
    email = _email_of(member)
    kind = member.split(":", 1)[0]
    if kind in ("user", "group", "serviceAccount") and "@" in email:
        dom = email.split("@", 1)[1]
        if kind != "serviceAccount":
            ids.add("domain:" + dom)
        if kind == "user":
            ids.add("principal://goog/subject/" + email)
        if kind == "serviceAccount":
            ids.add("principal://iam.googleapis.com/projects/-/serviceAccounts/" + email)
    closure = _group_closure(member, state)
    for g in closure:
        ids.add(g)
        ids.add("principalSet://goog/group/" + _email_of(g))
    for a, v in ((principal or {}).get("attributes") or {}).items():
        ids.add("principalSet://%s/%s/%s" % ((principal or {}).get("pool", ""), a, v))
    for extra in (principal or {}).get("principal_sets") or []:
        ids.add(extra)
    if member.startswith(("principal://", "principalSet://")):
        pass
    return ids


def _member_matches(binding_member: str, ids: set, principal: dict, state: dict, project_hint: set = None) -> bool:
    bm = _norm_member(binding_member)
    if not isinstance(bm, str):
        return False
    if bm.startswith("deleted:"):
        return False  # a deleted principal's binding never matches a live caller
    if bm in ids:
        return True
    if bm.startswith("principalSet://") and bm.endswith("/*"):
        pref = bm[:-1]
        mem = _norm_member((principal or {}).get("member") or "")
        return mem.startswith(pref.replace("principalSet://", "principal://", 1)) or any(i.startswith(pref) for i in ids)
    for pre, role in (("projectOwner:", "roles/owner"), ("projectEditor:", "roles/editor"), ("projectViewer:", "roles/viewer")):
        if bm.startswith(pre):
            proj = "projects/" + bm[len(pre):]
            pol = _lookup(state.get("allow_policies") or {}, proj) or {}
            for b in pol.get("bindings") or []:
                if b.get("role") == role and any(m in ids for m in b.get("members") or [] if not str(m).startswith("project")):
                    return True
    return False


def _lookup(table: dict, path: str):
    for k, v in (table or {}).items():
        if _norm_key(k) == path:
            return v
    return None


# ------------------------------------------------------------------ CEL subset
class CelUnsupported(Exception):
    """Syntax or function outside the supported subset: the condition is NOT evaluated."""


class CelError(Exception):
    """Runtime CEL error (missing key, type mismatch): IAM treats the condition as not satisfied."""


_TOK = re.compile(r"""\s*(?:(?P<num>\d+\.\d+(?:[eE][+-]?\d+)?|\d+)|(?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(?P<id>[A-Za-z_][A-Za-z_0-9]*)|(?P<op>\|\||&&|==|!=|<=|>=|[<>!+\-*/%()\[\].,?:{}]))""")


def _tokenize(s):
    pos, out = 0, []
    s = s.rstrip()
    while pos < len(s):
        m = _TOK.match(s, pos)
        if not m or m.end() == pos:
            raise CelUnsupported("unexpected character at %d: %r" % (pos, s[pos:pos + 8]))
        pos = m.end()
        for k in ("num", "str", "id", "op"):
            if m.group(k) is not None:
                out.append((k, m.group(k)))
                break
    return out


def _unquote(t):
    body = t[1:-1]
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t", "r": "\r"}.get(m.group(1), m.group(1)), body)


class _P:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, val=None):
        tok = self.peek()
        if tok[0] is None or (val is not None and tok[1] != val):
            raise CelUnsupported("expected %r got %r" % (val, tok[1]))
        self.i += 1
        return tok

    def accept(self, val):
        if self.peek()[1] == val and self.peek()[0] in ("op", "id"):
            self.i += 1
            return True
        return False

    def parse(self):
        e = self.ternary()
        if self.i != len(self.t):
            raise CelUnsupported("trailing tokens near %r" % (self.peek()[1],))
        return e

    def ternary(self):
        c = self.or_()
        if self.accept("?"):
            a = self.ternary()
            self.take(":")
            b = self.ternary()
            return ("?", c, a, b)
        return c

    def or_(self):
        l = self.and_()
        while self.accept("||"):
            l = ("||", l, self.and_())
        return l

    def and_(self):
        l = self.rel()
        while self.accept("&&"):
            l = ("&&", l, self.rel())
        return l

    def rel(self):
        l = self.add()
        while True:
            k, v = self.peek()
            if k == "op" and v in ("==", "!=", "<", "<=", ">", ">="):
                self.i += 1
                l = (v, l, self.add())
            elif k == "id" and v == "in":
                self.i += 1
                l = ("in", l, self.add())
            else:
                return l

    def add(self):
        l = self.mul()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            l = (op, l, self.mul())
        return l

    def mul(self):
        l = self.unary()
        while self.peek()[0] == "op" and self.peek()[1] in ("*", "/", "%"):
            op = self.take()[1]
            l = (op, l, self.unary())
        return l

    def unary(self):
        if self.accept("!"):
            return ("!", self.unary())
        if self.peek() == ("op", "-"):
            self.i += 1
            return ("neg", self.unary())
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while True:
            if self.accept("."):
                name = self.take()[1]
                if self.accept("("):
                    e = ("call", name, e, self.args())
                else:
                    e = ("field", e, name)
            elif self.accept("["):
                idx = self.ternary()
                self.take("]")
                e = ("index", e, idx)
            else:
                return e

    def args(self):
        out = []
        if self.accept(")"):
            return out
        while True:
            out.append(self.ternary())
            if self.accept(")"):
                return out
            self.take(",")

    def primary(self):
        k, v = self.peek()
        if k is None:
            raise CelUnsupported("unexpected end")
        self.i += 1
        if k == "num":
            return ("lit", float(v) if "." in v or "e" in v.lower() else int(v))
        if k == "str":
            return ("lit", _unquote(v))
        if k == "op" and v == "(":
            e = self.ternary()
            self.take(")")
            return e
        if k == "op" and v == "[":
            items = []
            if not self.accept("]"):
                while True:
                    items.append(self.ternary())
                    if self.accept("]"):
                        break
                    self.take(",")
            return ("list", items)
        if k == "id":
            if v in ("true", "false"):
                return ("lit", v == "true")
            if v == "null":
                return ("lit", None)
            if self.accept("("):
                return ("fn", v, self.args())
            return ("var", v)
        raise CelUnsupported("unexpected token %r" % (v,))


def _parse_ts(s):
    if isinstance(s, _dt.datetime):
        return s if s.tzinfo else s.replace(tzinfo=_dt.timezone.utc)
    if not isinstance(s, str):
        raise CelError("bad timestamp")
    try:
        t = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise CelError("bad timestamp %r" % (s,))
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


_DUR = re.compile(r"(-?\d+(?:\.\d+)?)(h|ms|m|s|us|ns)")


def _parse_dur(s):
    if not isinstance(s, str) or not re.fullmatch(r"(?:-?\d+(?:\.\d+)?(?:h|ms|m|s|us|ns))+", s):
        raise CelError("bad duration")
    mult = {"h": 3600, "m": 60, "s": 1, "ms": 1e-3, "us": 1e-6, "ns": 1e-9}
    return _dt.timedelta(seconds=sum(float(n) * mult[u] for n, u in _DUR.findall(s)))


class _Missing:
    pass


def _ev(n, env):
    t = n[0]
    if t == "lit":
        return n[1]
    if t == "list":
        return [_ev(x, env) for x in n[1]]
    if t == "var":
        if n[1] in env:
            return env[n[1]]
        raise CelError("undeclared reference to '%s'" % n[1])
    if t == "field":
        base = _ev(n[1], env)
        if isinstance(base, dict) and n[2] in base:
            return base[n[2]]
        raise CelError("no such key: %s" % n[2])
    if t == "index":
        base, idx = _ev(n[1], env), _ev(n[2], env)
        try:
            return base[idx]
        except (KeyError, IndexError, TypeError):
            raise CelError("index error")
    if t == "!":
        v = _ev(n[1], env)
        if not isinstance(v, bool):
            raise CelError("! needs bool")
        return not v
    if t == "neg":
        return -_ev(n[1], env)
    if t == "?":
        c = _ev(n[1], env)
        return _ev(n[2] if c else n[3], env)
    if t in ("&&", "||"):
        # CEL commutative short-circuit: an error on one side is absorbed if the other side decides.
        l = r = None
        le = re_ = None
        try:
            l = _ev(n[1], env)
        except CelError as e:
            le = e
        absorb = False if t == "&&" else True
        if le is None and l is absorb:
            return absorb
        try:
            r = _ev(n[2], env)
        except CelError as e:
            re_ = e
        if re_ is None and r is absorb:
            return absorb
        if le or re_:
            raise le or re_
        if not isinstance(l, bool) or not isinstance(r, bool):
            raise CelError("logical op needs bool")
        return (l and r) if t == "&&" else (l or r)
    if t in ("==", "!=", "<", "<=", ">", ">="):
        l, r = _ev(n[1], env), _ev(n[2], env)
        if t in ("==", "!="):
            eq = l == r
            return eq if t == "==" else not eq
        try:
            return {"<": l < r, "<=": l <= r, ">": l > r, ">=": l >= r}[t]
        except TypeError:
            raise CelError("incomparable types")
    if t == "in":
        l, r = _ev(n[1], env), _ev(n[2], env)
        if isinstance(r, (list, tuple, dict)):
            return l in r
        raise CelError("'in' needs list or map")
    if t in ("+", "-", "*", "/", "%"):
        l, r = _ev(n[1], env), _ev(n[2], env)
        try:
            if t == "+":
                return l + r
            if t == "-":
                return l - r
            if t == "*":
                return l * r
            if t == "/":
                return l // r if isinstance(l, int) and isinstance(r, int) else l / r
            return l % r
        except (TypeError, ZeroDivisionError):
            raise CelError("arithmetic error")
    if t == "fn":
        name, args = n[1], n[2]
        if name == "has":
            if len(args) != 1 or args[0][0] != "field":
                raise CelUnsupported("has() needs a field selection")
            try:
                base = _ev(args[0][1], env)
            except CelError:
                return False
            return isinstance(base, dict) and args[0][2] in base
        vals = [_ev(a, env) for a in args]
        if name == "timestamp" and len(vals) == 1:
            return _parse_ts(vals[0])
        if name == "duration" and len(vals) == 1:
            return _parse_dur(vals[0])
        if name == "size" and len(vals) == 1:
            return len(vals[0])
        if name == "string" and len(vals) == 1:
            return str(vals[0])
        if name == "int" and len(vals) == 1:
            if isinstance(vals[0], _dt.datetime):
                return int(vals[0].timestamp())
            return int(vals[0])
        if name == "double" and len(vals) == 1:
            return float(vals[0])
        raise CelUnsupported("function %s() not supported" % name)
    if t == "call":
        name, recv, args = n[1], _ev(n[2], env), [_ev(a, env) for a in n[3]]
        if name in ("startsWith", "endsWith", "contains", "matches") and isinstance(recv, str) and len(args) == 1 and isinstance(args[0], str):
            if name == "startsWith":
                return recv.startswith(args[0])
            if name == "endsWith":
                return recv.endswith(args[0])
            if name == "contains":
                return args[0] in recv
            try:
                return re.search(args[0], recv) is not None
            except re.error:
                raise CelError("bad regex")
        if name == "size" and not args:
            return len(recv)
        if name == "exists" or name == "all":
            raise CelUnsupported("macro %s() not supported" % name)
        if isinstance(recv, _dt.datetime):
            tz = recv
            if args and isinstance(args[0], str):
                m = re.fullmatch(r"([+-])(\d\d):(\d\d)", args[0])
                if not m:
                    raise CelUnsupported("named time zones not supported")
                off = _dt.timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
                tz = recv.astimezone(_dt.timezone(off if m.group(1) == "+" else -off))
            tbl = {"getFullYear": lambda: tz.year, "getMonth": lambda: tz.month - 1, "getDate": lambda: tz.day,
                   "getDayOfMonth": lambda: tz.day - 1, "getDayOfWeek": lambda: (tz.weekday() + 1) % 7,
                   "getDayOfYear": lambda: tz.timetuple().tm_yday - 1, "getHours": lambda: tz.hour,
                   "getMinutes": lambda: tz.minute, "getSeconds": lambda: tz.second, "getMilliseconds": lambda: tz.microsecond // 1000}
            if name in tbl:
                return tbl[name]()
        raise CelUnsupported("method %s() not supported" % name)
    raise CelUnsupported("node %s" % t)


def eval_condition(expression: str, env: dict):
    """-> (True|False|None, note). None = unsupported/erroring: the caller treats it as 'does not grant'."""
    try:
        v = _ev(_P(_tokenize(expression)).parse(), env)
    except CelUnsupported as e:
        return None, "condition not evaluated (unsupported CEL): %s" % e
    except CelError as e:
        return None, "condition error (treated as not satisfied): %s" % e
    except Exception as e:  # noqa: BLE001 - never raise into the gate
        return None, "condition error: %s" % e
    if not isinstance(v, bool):
        return None, "condition did not evaluate to bool"
    return v, ""


def _cond_env(req: dict, resource: str) -> dict:
    ctx = req.get("context") or {}
    host, path = split_resource(resource)
    t = ctx.get("time") or ctx.get("request_time")
    now = _parse_ts(t) if t else _dt.datetime.now(_dt.timezone.utc)
    env = {"request": {"time": now}, "resource": {"name": ctx.get("resource_name") or path, "service": ctx.get("resource_service") or host,
                                                    "type": ctx.get("resource_type", "")}}
    for k, v in (ctx.get("request") or {}).items():
        env["request"][k] = v
    for k, v in (ctx.get("resource") or {}).items():
        env["resource"][k] = v
    if "api" in ctx:
        env["api"] = ctx["api"]
    return env


# ------------------------------------------------------------------ deny
_FQDN_EXC = {"resourcemanager": "cloudresourcemanager", "cloudsql": "sqladmin", "firebaseauth": "identitytoolkit",
             "container": "container", "cloudfunctions": "cloudfunctions", "storage": "storage"}


def _split_perm(perm: str):
    svc, _, rest = perm.partition(".")
    return _FQDN_EXC.get(svc, svc) + ".googleapis.com", rest


def _perm_pattern_match(pattern: str, perm: str) -> bool:
    """Deny permission forms: `service.googleapis.com/resource.verb` with `*` wildcards (e.g. `compute.googleapis.com/instances.*`,
    `iam.googleapis.com/*.create`), or the bare `service.resource.verb` ID (also with wildcards)."""
    fq, rest = _split_perm(perm)
    if "/" in pattern:
        ps, _, pr = pattern.partition("/")
        return fnmatch.fnmatchcase(fq, ps) and fnmatch.fnmatchcase(rest, pr)
    return fnmatch.fnmatchcase(perm, pattern)


def _principal_listed(entries, ids, principal, state) -> bool:
    for e in entries or []:
        if _member_matches(e, ids, principal, state):
            return True
        if e == "principalSet://goog/public:all":
            return True
    return False


def _as_list(v):
    if isinstance(v, dict):
        return list(v.values())
    return list(v or [])


def _deny_rules(state, chain):
    for ap in chain:
        for pol in _as_list(_lookup_multi(state.get("deny_policies") or {}, ap)):
            for i, rule in enumerate(pol.get("rules") or []):
                dr = rule.get("denyRule") or rule
                yield ap, pol, i, dr


def _lookup_multi(table, path):
    out = []
    for k, v in (table or {}).items():
        if _norm_key(k) == path:
            out.extend(_as_list(v) if isinstance(v, (list, dict)) and not (isinstance(v, dict) and ("rules" in v or "name" in v)) else [v])
    return out


# ------------------------------------------------------------------ PAB
def _pab_applicable(state, ids, principal):
    pols = state.get("pab_policies") or {}
    out = []
    for b in _as_list(state.get("pab_bindings")):
        tgt = b.get("target") or {}
        who = tgt.get("principal") or tgt.get("principalSet")
        if not who or not _member_matches(who, ids, principal, state):
            continue
        name = b.get("policy")
        pol = pols.get(name) or next((v for k, v in pols.items() if k.endswith("/" + str(name).rsplit("/", 1)[-1]) or k == name), None)
        if pol is None:
            continue
        out.append((b, name, pol))
    return out


def _pab_resources(pol) -> list:
    rules = pol.get("rules") or (pol.get("details") or {}).get("rules") or []
    res = []
    for r in rules:
        if str(r.get("effect", "ALLOW")).upper() == "ALLOW":
            res.extend(_norm_key(x) for x in r.get("resources") or [])
    return res


# ------------------------------------------------------------------ evaluate
def evaluate(req: dict, state: dict) -> dict:
    perm = req.get("action")
    resource = req.get("resource") or "*"
    principal = req.get("principal") or {}
    state = state or {}
    ids = principal_identities(principal, state)
    chain = ancestry(resource, state)
    env = None
    matched: list = []

    # 1) principal access boundary
    pabs = _pab_applicable(state, ids, principal)
    if pabs:
        allowed_res: list = []
        for b, name, pol in pabs:
            allowed_res.extend(_pab_resources(pol))
        inside = any(a in chain for a in allowed_res)
        entry = {"source": "pab", "id": ",".join(str(n) for _, n, _ in pabs), "effect": "Allow" if inside else "Deny",
                 "statement": {"eligibleResources": allowed_res}}
        matched.append(entry)
        if not inside:
            return decision(False, "explicit_deny", matched, note="principal access boundary does not include the resource")

    # 2) deny policies
    for ap, pol, i, dr in _deny_rules(state, chain):
        if not any(_perm_pattern_match(p, perm) for p in dr.get("deniedPermissions") or []):
            continue
        if any(_perm_pattern_match(p, perm) for p in dr.get("exceptionPermissions") or []):
            continue
        if not _principal_listed(dr.get("deniedPrincipals"), ids, principal, state):
            continue
        if _principal_listed(dr.get("exceptionPrincipals"), ids, principal, state):
            continue
        cond = dr.get("denialCondition")
        note = ""
        if cond and cond.get("expression"):
            env = env or _cond_env(req, resource)
            ok, note = eval_condition(cond["expression"], env)
            if ok is False:
                continue
            if ok is None:
                note = note + " - deny applied (fail closed)"
        m = {"source": "deny_policy", "id": "%s#%s/rule%d" % (ap, pol.get("name") or pol.get("displayName") or "policy", i),
             "effect": "Deny", "statement": dr}
        if note:
            m["note"] = note
        matched.append(m)
        return decision(False, "explicit_deny", matched)

    # 3) allow policies, union over the hierarchy
    allowed = False
    for ap in chain:
        pol = _lookup(state.get("allow_policies") or {}, ap)
        for bi, b in enumerate((pol or {}).get("bindings") or []):
            role = b.get("role", "")
            if perm not in role_permissions(role, state):
                continue
            if not any(_member_matches(m, ids, principal, state) for m in b.get("members") or []):
                continue
            cond = b.get("condition")
            m = {"source": "allow_policy", "id": "%s#%d" % (ap, bi), "effect": "Allow",
                 "statement": {"role": role, "members": b.get("members"), **({"condition": cond} if cond else {})}}
            if cond and cond.get("expression"):
                env = env or _cond_env(req, resource)
                ok, note = eval_condition(cond["expression"], env)
                if ok is not True:
                    m["effect"] = "NotApplicable"
                    m["note"] = note or "condition evaluated to false"
                    matched.append(m)
                    continue
            matched.append(m)
            allowed = True
    if allowed:
        return decision(True, "allow", matched)
    return decision(False, "implicit_deny", matched)


def test_iam_permissions(principal: dict, resource: str, permissions: list, state: dict, context: dict = None) -> list:
    """The `:testIamPermissions` answer: the subset of `permissions` the principal holds on `resource` (deny and PAB applied)."""
    out = []
    for p in permissions or []:
        d = evaluate({"cloud": "gcp", "principal": principal, "action": p, "resource": resource, "context": context or {}}, state)
        if d["allowed"]:
            out.append(p)
    return out
