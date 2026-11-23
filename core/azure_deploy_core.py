"""Azure ARM template deployment engine (Nano / dev_server / unified-ingress core, pure Python).

``Microsoft.Resources/deployments`` PUT really provisions what the template declares, through the
SAME ARM dispatcher (``arm.handle``), so every resource lands in the same state an SDK/CLI/console
PUT would create:

  * the ARM template expression language (parser + evaluator): parameters/variables (lazy, with
    defaults and ``allowedValues`` checks), concat/format/resourceId/subscriptionResourceId/
    resourceGroup/subscription/reference/uniqueString/guid/if/equals/and/or/not/coalesce/union/
    createObject/createArray/length/contains/split/replace/substring/toLower/toUpper/trim/int/
    string/bool/json/base64/indexOf/first/last/range/copyIndex/uri/...
  * ``copy`` loops on resources (``count`` + ``copyIndex()``) and on properties (``copy:[{name,count,input}]``)
  * ``condition``, nested child ``resources`` (type/name composed with the parent), ``scope`` for extension
    resources, ``dependsOn`` (explicit + implicit from ``reference()``/``resourceId()`` of another template
    resource) with a stable topological order and cycle detection
  * ``outputs`` evaluated after provisioning
  * ``whatIf`` (POST .../deployments/{n}/whatIf): Create / Modify / NoChange / Delete (Complete mode) with
    per-property deltas computed against the live state, and ``validate``

Not modelled (stated in the capability registry): linked templates (``templateLink``), user-defined
functions/types, Bicep-only ``languageVersion 2.0`` symbolic names (compile Bicep to JSON first), and
``listKeys``-style list* functions (that resource's expression fails with an explicit error).
"""
from __future__ import annotations

import base64
import copy as _copy
import hashlib
import json
import re
import uuid

META_KEYS = {"type", "name", "apiVersion", "dependsOn", "condition", "comments", "copy", "scope", "resources", "metadata", "id", "languageVersion"}


class TemplateError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


# ═════════════════════════════ expression language ═════════════════════════════════════════════
_TOK = re.compile(r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<num>-?\d+(?:\.\d+)?)|(?P<id>[A-Za-z_][A-Za-z0-9_]*)|(?P<p>[().,\[\]]))")


def _tokenize(s):
    pos, out = 0, []
    while pos < len(s):
        if s[pos:].strip() == "":
            break
        m = _TOK.match(s, pos)
        if not m:
            raise TemplateError("InvalidTemplate", f"Unrecognized token in template expression '{s}' at position {pos}.")
        pos = m.end()
        if m.group("str") is not None:
            out.append(("s", m.group("str")[1:-1].replace("''", "'")))
        elif m.group("num") is not None:
            t = m.group("num")
            out.append(("n", float(t) if "." in t else int(t)))
        elif m.group("id") is not None:
            out.append(("i", m.group("id")))
        else:
            out.append(("p", m.group("p")))
    return out


def parse_expr(s):
    toks = _tokenize(s)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else (None, None)

    def eat(kind=None, val=None):
        t = peek()
        if t[0] is None or (kind and t[0] != kind) or (val is not None and t[1] != val):
            raise TemplateError("InvalidTemplate", f"Unexpected token in expression '{s}'.")
        pos[0] += 1
        return t

    def primary():
        k, v = peek()
        if k in ("s", "n"):
            pos[0] += 1
            return ("lit", v)
        if k == "i":
            pos[0] += 1
            if v in ("true", "false", "null") and peek() != ("p", "("):
                return ("lit", {"true": True, "false": False, "null": None}[v])
            eat("p", "(")
            args = []
            if peek() != ("p", ")"):
                while True:
                    args.append(expr())
                    if peek() == ("p", ","):
                        pos[0] += 1
                        continue
                    break
            eat("p", ")")
            return ("call", v, args)
        raise TemplateError("InvalidTemplate", f"Unexpected token in expression '{s}'.")

    def expr():
        node = primary()
        while True:
            if peek() == ("p", "."):
                pos[0] += 1
                node = ("prop", node, eat("i")[1])
            elif peek() == ("p", "["):
                pos[0] += 1
                idx = expr()
                eat("p", "]")
                node = ("idx", node, idx)
            else:
                return node

    node = expr()
    if pos[0] != len(toks):
        raise TemplateError("InvalidTemplate", f"Unexpected trailing tokens in expression '{s}'.")
    return node


def is_expr(v):
    return isinstance(v, str) and len(v) >= 2 and v.startswith("[") and v.endswith("]") and not v.startswith("[[")


class Ctx:
    """Evaluation context for one deployment."""

    def __init__(self, sub, rg, params=None, variables=None, location=None, reference=None, deployment_name="deployment", tenant="00000000-0000-0000-0000-000000000000"):
        self.sub, self.rg, self.tenant, self.location = sub, rg, tenant, location or "eastus"
        self.param_defs = params or {}
        self.param_vals = {}
        self.var_defs = variables or {}
        self.var_vals = {}
        self.reference_fn = reference            # (resource_id_or_name, full) -> dict | None
        self.deployment_name = deployment_name
        self.copy_idx = {}                        # loop name -> index; "" = innermost
        self.referenced = set()                   # resource ids touched via resourceId()/reference() (implicit dependsOn)
        self._var_busy = set()

    def sub_ctx(self, **kw):
        c = _copy.copy(self)
        c.copy_idx = dict(self.copy_idx)
        c.copy_idx.update(kw)
        return c


def _rid(ctx, args, with_rg=True, tenant=False):
    """resourceId([sub],[rg],type,names...) / subscriptionResourceId([sub],type,names...) / tenantResourceId(type,names...)."""
    args = [str(x) for x in args]
    i = next((k for k, x in enumerate(args) if "/" in x), 0)
    pre = args[:i]
    sub, rg = ctx.sub, ctx.rg
    if not tenant:
        if with_rg:
            if len(pre) == 1:
                rg = pre[0]
            elif len(pre) >= 2:
                sub, rg = pre[0], pre[1]
        elif pre:
            sub = pre[0]
    prefix = "" if tenant else f"/subscriptions/{sub}" + (f"/resourceGroups/{rg}" if with_rg and rg else "")
    ns, *tsegs = args[i].split("/")
    names = args[i + 1:]
    parts = []
    for n, t in enumerate(tsegs):
        parts.append(t)
        if n < len(names):
            parts.append(names[n])
    return f"{prefix}/providers/{ns}/" + "/".join(parts)


def _s(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"))
    return str(v)


def _unique_string(*a):
    h = hashlib.sha256("-".join(map(str, a)).encode()).digest()
    n = int.from_bytes(h[:9], "big")
    alphabet = "abcdefghijklmnopqrstuvwxyz234567"
    out = ""
    for _ in range(13):
        out += alphabet[n & 31]
        n >>= 5
    return out[::-1]


def _call(ctx, name, args_nodes):
    n = name.lower()
    if n == "if":      # lazy
        c = ev(ctx, args_nodes[0])
        return ev(ctx, args_nodes[1] if c else args_nodes[2])
    if n == "and":
        return all(bool(ev(ctx, a)) for a in args_nodes)
    if n == "or":
        return any(bool(ev(ctx, a)) for a in args_nodes)
    if n == "coalesce":
        for a in args_nodes:
            v = ev(ctx, a)
            if v is not None:
                return v
        return None
    a = [ev(ctx, x) for x in args_nodes]
    if n == "parameters":
        return param_value(ctx, a[0])
    if n == "variables":
        return var_value(ctx, a[0])
    if n == "concat":
        if a and all(isinstance(x, list) for x in a):
            return [i for x in a for i in x]
        return "".join(_s(x) for x in a)
    if n == "format":
        out = str(a[0])
        return re.sub(r"\{(\d+)(?::[^}]*)?\}", lambda m: _s(a[1 + int(m.group(1))]) if 1 + int(m.group(1)) < len(a) else m.group(0), out)
    if n in ("resourceid",):
        r = _rid(ctx, a)
        ctx.referenced.add(r.lower())
        return r
    if n == "subscriptionresourceid":
        r = _rid(ctx, a, with_rg=False)
        ctx.referenced.add(r.lower())
        return r
    if n == "tenantresourceid":
        return _rid(ctx, a, tenant=True)
    if n == "extensionresourceid":
        return f"{a[0]}/providers/{a[1]}/" + "/".join(f"{t}/{nm}" for t, nm in zip(a[1].split("/")[1:], a[2:])) if len(a) > 2 else a[0]
    if n == "resourcegroup":
        return {"id": f"/subscriptions/{ctx.sub}/resourceGroups/{ctx.rg}", "name": ctx.rg, "type": "Microsoft.Resources/resourceGroups",
                "location": ctx.location, "tags": {}, "properties": {"provisioningState": "Succeeded"}}
    if n == "subscription":
        return {"id": f"/subscriptions/{ctx.sub}", "subscriptionId": ctx.sub, "tenantId": ctx.tenant, "displayName": ctx.sub}
    if n == "tenant":
        return {"tenantId": ctx.tenant}
    if n == "deployment":
        return {"name": ctx.deployment_name, "properties": {"mode": "Incremental"}}
    if n == "environment":
        return {"name": "AzureCloud", "suffixes": {"storage": "core.windows.net", "keyvaultDns": ".vault.azure.net", "sqlServerHostname": ".database.windows.net",
                                                      "acrLoginServer": ".azurecr.io"}, "resourceManager": "https://management.azure.com/"}
    if n == "reference":
        if ctx.reference_fn is None:
            raise TemplateError("InvalidTemplate", "reference() is not available in this context.")
        full = len(a) >= 3 and str(a[2]).lower() == "full"
        rid = str(a[0])
        ctx.referenced.add(rid.lower())
        v = ctx.reference_fn(rid, full)
        if v is None:
            raise TemplateError("ResourceNotFound", f"The Resource '{rid}' was not found while evaluating reference().")
        return v
    if n in ("listkeys", "listsecrets", "listaccountsas", "listservicesas", "listcredentials", "listconnectionstrings", "listkeys"):
        raise TemplateError("InvalidTemplate", f"The template function '{name}' is not supported by this simulator's template engine.")
    if n == "uniquestring":
        return _unique_string(*a)
    if n == "guid":
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, "-".join(map(str, a))))
    if n == "newguid":
        return str(uuid.uuid4())
    if n == "utcnow":
        import datetime
        return datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    if n == "tolower":
        return str(a[0]).lower()
    if n == "toupper":
        return str(a[0]).upper()
    if n == "trim":
        return str(a[0]).strip()
    if n == "replace":
        return str(a[0]).replace(str(a[1]), str(a[2]))
    if n == "substring":
        s = str(a[0])
        st = int(a[1])
        return s[st:] if len(a) < 3 else s[st:st + int(a[2])]
    if n == "split":
        seps = a[1] if isinstance(a[1], list) else [a[1]]
        parts = [str(a[0])]
        for sp in seps:
            parts = [q for p in parts for q in p.split(str(sp))]
        return parts
    if n == "startswith":
        return str(a[0]).lower().startswith(str(a[1]).lower())
    if n == "endswith":
        return str(a[0]).lower().endswith(str(a[1]).lower())
    if n == "indexof":
        return str(a[0]).lower().find(str(a[1]).lower())
    if n == "padleft":
        return str(a[0]).rjust(int(a[1]), str(a[2]) if len(a) > 2 else " ")
    if n == "length":
        return len(a[0])
    if n == "empty":
        return a[0] in (None, "", [], {})
    if n == "contains":
        c, k = a
        return (k in c) if isinstance(c, (dict, list)) and not isinstance(c, str) and isinstance(c, list) else (str(k) in c if isinstance(c, str) else (k in c))
    if n == "equals":
        x, y = a
        if isinstance(x, str) and isinstance(y, str):
            return x.lower() == y.lower()
        return x == y
    if n == "not":
        return not a[0]
    if n == "greater":
        return a[0] > a[1]
    if n == "greaterorequals":
        return a[0] >= a[1]
    if n == "less":
        return a[0] < a[1]
    if n == "lessorequals":
        return a[0] <= a[1]
    if n == "add":
        return a[0] + a[1]
    if n == "sub":
        return a[0] - a[1]
    if n == "mul":
        return a[0] * a[1]
    if n == "div":
        return a[0] // a[1]
    if n == "mod":
        return a[0] % a[1]
    if n == "min":
        return min(a[0] if isinstance(a[0], list) else a)
    if n == "max":
        return max(a[0] if isinstance(a[0], list) else a)
    if n == "int":
        return int(a[0])
    if n == "string":
        return _s(a[0])
    if n == "bool":
        return a[0] if isinstance(a[0], bool) else str(a[0]).lower() == "true"
    if n == "json":
        return json.loads(a[0])
    if n == "base64":
        return base64.b64encode(str(a[0]).encode()).decode()
    if n == "base64tostring":
        return base64.b64decode(str(a[0])).decode()
    if n == "uri":
        return str(a[0]).rstrip("/") + "/" + str(a[1]).lstrip("/")
    if n == "uricomponent":
        from urllib.parse import quote
        return quote(str(a[0]), safe="")
    if n == "createarray":
        return list(a)
    if n == "createobject":
        return {str(a[i]): a[i + 1] for i in range(0, len(a) - 1, 2)}
    if n == "union":
        if isinstance(a[0], list):
            out = []
            for x in a:
                out += [i for i in x if i not in out]
            return out
        out = {}
        for x in a:
            out.update(x)
        return out
    if n == "first":
        return a[0][0] if a[0] else None
    if n == "last":
        return a[0][-1] if a[0] else None
    if n == "take":
        return a[0][:int(a[1])]
    if n == "skip":
        return a[0][int(a[1]):]
    if n == "range":
        return list(range(int(a[0]), int(a[0]) + int(a[1])))
    if n == "array":
        return a[0] if isinstance(a[0], list) else [a[0]]
    if n == "items":
        return [{"key": k, "value": v} for k, v in a[0].items()]
    if n == "copyindex":
        key = str(a[0]) if a and isinstance(a[0], str) else ""
        off = int(a[-1]) if a and isinstance(a[-1], int) and not isinstance(a[-1], bool) else 0
        if key not in ctx.copy_idx:
            raise TemplateError("InvalidTemplate", "copyIndex() can only be used inside a copy loop.")
        return ctx.copy_idx[key] + off
    if n == "dataurl":
        return "data:text/plain;base64," + base64.b64encode(str(a[0]).encode()).decode()
    raise TemplateError("InvalidTemplate", f"The template function '{name}' is not supported by this simulator's template engine.")


def ev(ctx, node):
    k = node[0]
    if k == "lit":
        return node[1]
    if k == "call":
        return _call(ctx, node[1], node[2])
    if k == "prop":
        base = ev(ctx, node[1])
        if isinstance(base, dict):
            for key, v in base.items():
                if key.lower() == node[2].lower():
                    return v
            raise TemplateError("InvalidTemplate", f"The language expression property '{node[2]}' doesn't exist.")
        raise TemplateError("InvalidTemplate", f"The language expression property '{node[2]}' cannot be evaluated on a non-object.")
    if k == "idx":
        base, i = ev(ctx, node[1]), ev(ctx, node[2])
        try:
            if isinstance(base, dict):
                return next(v for kk, v in base.items() if str(kk).lower() == str(i).lower())
            return base[int(i)]
        except (StopIteration, IndexError, ValueError, TypeError):
            raise TemplateError("InvalidTemplate", f"The language expression index '{i}' is out of range.")
    raise TemplateError("InvalidTemplate", "bad expression")


def param_value(ctx, name):
    for k in ctx.param_vals:
        if k.lower() == str(name).lower():
            return ctx.param_vals[k]
    raise TemplateError("InvalidTemplate", f"The template parameter '{name}' is not found. Please see https://aka.ms/arm-template/#parameters for usage details.")


def var_value(ctx, name):
    key = next((k for k in ctx.var_defs if k.lower() == str(name).lower()), None)
    if key is None:
        raise TemplateError("InvalidTemplate", f"The template variable '{name}' is not found. Please see https://aka.ms/arm-template/#variables for usage details.")
    if key in ctx.var_vals:
        return ctx.var_vals[key]
    if key in ctx._var_busy:
        raise TemplateError("InvalidTemplate", f"Circular reference in template variable '{name}'.")
    ctx._var_busy.add(key)
    try:
        val = evaluate(ctx, ctx.var_defs[key])
    finally:
        ctx._var_busy.discard(key)
    ctx.var_vals[key] = val
    return val


def evaluate(ctx, v):
    """Recursively evaluate a template value (expressions, escaped '[[', property copy loops)."""
    if isinstance(v, str):
        if is_expr(v):
            return ev(ctx, parse_expr(v[1:-1]))
        if v.startswith("[["):
            return v[1:]
        return v
    if isinstance(v, list):
        return [evaluate(ctx, x) for x in v]
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if k == "copy" and isinstance(x, list) and all(isinstance(c, dict) and "name" in c and "count" in c and "input" in c for c in x):
                for c in x:
                    cnt = int(evaluate(ctx, c["count"]))
                    out[c["name"]] = [evaluate(ctx.sub_ctx(**{"": i, c["name"]: i}), c["input"]) for i in range(cnt)]
                continue
            out[evaluate(ctx, k) if isinstance(k, str) and is_expr(k) else k] = evaluate(ctx, x)
        return out
    return v


# ═════════════════════════════ template -> ordered resource list ═══════════════════════════════
def _full_type_name(parent, ent):
    t, n = ent.get("type", ""), ent.get("name", "")
    if parent is None:
        return t, n
    pt, pn = parent
    if t.lower().startswith(pt.split("/")[0].lower() + "/"):
        return t, n if "/" in str(n) and str(n).lower().startswith(str(pn).lower() + "/") else f"{pn}/{n}"
    return f"{pt}/{t}", f"{pn}/{n}"


def _flatten(resources, parent=None, parent_ent=None):
    """Nested ``resources`` -> flat list; children keep a back-reference as implicit dependsOn on the parent."""
    out = []
    for ent in resources or []:
        if not isinstance(ent, dict):
            continue
        flat = dict(ent)
        flat["_children"] = None
        if parent is not None:
            # type/name are composed AFTER evaluation (names may be expressions) -> mark
            flat["_parent_expr"] = parent
        out.append(flat)
        for ch in ent.get("resources") or []:
            c = dict(ch)
            c["_parent_ent"] = flat
            out.extend(_flatten([c]))
    return out


def _expand_one(ctx, ent, parent_resolved):
    """Evaluate one flattened entry (with copy loops) into concrete resource dicts."""
    copies = []
    cp = ent.get("copy")
    if isinstance(cp, dict) and "count" in cp:
        cname = evaluate(ctx, cp.get("name", ""))
        cnt = int(evaluate(ctx, cp["count"]))
        copies = [(i, cname) for i in range(cnt)]
    else:
        copies = [(None, None)]
    outs = []
    for i, cname in copies:
        c = ctx if i is None else ctx.sub_ctx(**{"": i, cname: i})
        if "condition" in ent and not bool(evaluate(c, ent["condition"])):
            continue
        rtype = evaluate(c, ent.get("type"))
        rname = evaluate(c, ent.get("name"))
        if parent_resolved is not None:
            rtype, rname = _full_type_name((parent_resolved["type"], parent_resolved["name"]), {"type": rtype, "name": rname})
        body = {k: evaluate(c, v) for k, v in ent.items() if k not in META_KEYS and not k.startswith("_")}
        scope = evaluate(c, ent.get("scope")) if ent.get("scope") else None
        deps = [evaluate(c, d) for d in (ent.get("dependsOn") or [])]
        outs.append({"type": rtype, "name": str(rname), "apiVersion": evaluate(c, ent.get("apiVersion")) or "2023-01-01", "body": body, "scope": scope, "dependsOn": deps,
                     "_ent": ent})
    return outs


def _res_id(sub, rg, rtype, name, scope=None):
    ns, *tsegs = rtype.split("/")
    names = str(name).split("/")
    parts = []
    for i, t in enumerate(tsegs):
        parts += [t, names[i] if i < len(names) else ""]
    base = scope.rstrip("/") if scope else (f"/subscriptions/{sub}" + (f"/resourceGroups/{rg}" if rg else ""))
    return f"{base}/providers/{ns}/" + "/".join(parts)


def plan(ctx, template):
    """Resolve the template into an ordered list of concrete resources (dicts with id/type/name/body/deps).
    Raises TemplateError for invalid templates / cycles."""
    # parameters
    declared = template.get("parameters") or {}
    for pname, pdef in declared.items():
        pass
    resolved = []
    flat_entries = []
    stack = [(e, None) for e in (template.get("resources") or [])]
    # preserve declaration order: DFS pre-order
    order = []

    def walk(ents, parent):
        for e in ents:
            order.append((e, parent))
            walk(e.get("resources") or [], e)
    walk(template.get("resources") or [], None)
    expanded_by_ent = {}
    for e, parent in order:
        pr = expanded_by_ent.get(id(parent))
        outs = []
        if parent is None:
            outs = _expand_one(ctx, e, None)
        else:
            for p in (pr or []):
                outs += _expand_one(ctx, e, p)
        expanded_by_ent[id(e)] = outs
        for o in outs:
            o["_parent"] = parent
            resolved.append(o)
    for r in resolved:
        r["id"] = _res_id(ctx.sub, ctx.rg, r["type"], r["name"], r["scope"])
        r["deps"] = set()
    by_id = {r["id"].lower(): r for r in resolved}
    by_tn = {}
    for r in resolved:
        by_tn.setdefault(r["name"].lower(), []).append(r)
    for r in resolved:
        for d in r["dependsOn"]:
            d = str(d)
            t = by_id.get(d.lower())
            if t is None:
                t = next((x for x in by_tn.get(d.lower(), [])), None)
            if t is None:
                # allow a prefix match on id (dependsOn a child's parent expression)
                t = next((x for k, x in by_id.items() if k == d.lower()), None)
            if t is not None and t is not r:
                r["deps"].add(t["id"].lower())
            elif t is None and d.startswith("/"):
                pass    # dependency on a resource outside this template (already exists)
            elif t is None and d:
                raise TemplateError("InvalidTemplate", f"The resource '{r['type']}/{r['name']}' depends on '{d}', which is not defined in this template.")
        r["explicit"] = set(r["deps"])
        # children depend on parent
        pe = r["_parent"]
        if pe is not None:
            for p in expanded_by_ent.get(id(pe), []):
                if r["name"].lower().startswith(p["name"].lower() + "/"):
                    r["deps"].add(_res_id(ctx.sub, ctx.rg, p["type"], p["name"], p["scope"]).lower())
                    r["explicit"].add(_res_id(ctx.sub, ctx.rg, p["type"], p["name"], p["scope"]).lower())
        # implicit: any string in the body equal to (or under) another template resource's id
        strs = []
        _walk_strings(r["body"], strs)
        for s in strs:
            sl = s.lower()
            for k in by_id:
                if k != r["id"].lower() and (sl == k or sl.startswith(k + "/")) and not (r["id"].lower().startswith(k + "/")):
                    r["deps"].add(k)
        # a child never needs to wait for a sibling whose id merely prefixes it
        r["deps"].discard(r["id"].lower())
    # stable topological order (Kahn, keeping declaration order among ready nodes)
    done, ordered, remaining = set(), [], list(resolved)
    while remaining:
        progressed = False
        for r in list(remaining):
            if all((d in done) or (d not in by_id) for d in r["deps"]):
                ordered.append(r)
                done.add(r["id"].lower())
                remaining.remove(r)
                progressed = True
        if not progressed and any(x["deps"] != x["explicit"] for x in remaining):
            for x in remaining:     # reference-only edges (two resources pointing at each other, e.g. NIC <-> VM) are not ordering constraints
                x["deps"] = set(x["explicit"])
            continue
        if not progressed:
            names = ", ".join(f"{x['type']}/{x['name']}" for x in remaining)
            raise TemplateError("InvalidTemplate", f"Circular dependency detected on resource(s): {names}.")
    return ordered


def _walk_strings(o, out):
    if isinstance(o, str):
        out.append(o)
    elif isinstance(o, list):
        for x in o:
            _walk_strings(x, out)
    elif isinstance(o, dict):
        for v in o.values():
            _walk_strings(v, out)


# ═════════════════════════════ execution ═══════════════════════════════════════════════════════
def make_ctx(arm, sub, rg, rec, location=None):
    props = rec.get("properties") or {}
    template = props.get("template") or {}
    if not isinstance(template, dict):
        raise TemplateError("InvalidTemplate", "The template must be a JSON object.")

    def ref(rid, full):
        rid = str(rid)
        if not rid.startswith("/"):
            return None
        r = arm.handle("GET", rid, {"api-version": "2023-01-01"}, None)
        if r["status"] >= 400 or not isinstance(r["body"], dict):
            return None
        b = r["body"]
        return b if full else (b.get("properties") or {})
    ctx = Ctx(sub, rg, template.get("parameters"), template.get("variables"), location, ref, deployment_name=rec.get("name", "deployment"))
    # parameters: supplied values > defaultValue; required ones must be provided; allowedValues / length checks
    supplied = {}
    for k, v in (props.get("parameters") or {}).items():
        supplied[k] = v.get("value", v) if isinstance(v, dict) and "value" in v else v
    missing = []
    for pname, pdef in (template.get("parameters") or {}).items():
        sk = next((k for k in supplied if k.lower() == pname.lower()), None)
        if sk is not None:
            val = supplied[sk]
        elif isinstance(pdef, dict) and "defaultValue" in pdef:
            val = None
            ctx.param_vals.setdefault(pname, None)
            ctx._pending = getattr(ctx, "_pending", [])
            ctx._pending.append((pname, pdef["defaultValue"]))
            continue
        else:
            missing.append(pname)
            continue
        ctx.param_vals[pname] = val
    if missing:
        raise TemplateError("InvalidTemplate", f"Deployment template validation failed: 'The template parameters '{', '.join(missing)}' in the parameters file are not valid; they are not provided and have no default value.'")
    for pname, dv in getattr(ctx, "_pending", []):
        ctx.param_vals[pname] = evaluate(ctx, dv)
    for pname, pdef in (template.get("parameters") or {}).items():
        v = ctx.param_vals.get(pname)
        allowed = (pdef or {}).get("allowedValues")
        if allowed is not None and v not in allowed and not (isinstance(v, str) and v.lower() in [str(x).lower() for x in allowed]):
            raise TemplateError("InvalidTemplate", f"Deployment template validation failed: 'The provided value for the template parameter '{pname}' is not valid. The allowed values are '{allowed}'.'")
        if isinstance(v, str):
            if "minLength" in (pdef or {}) and len(v) < int(pdef["minLength"]):
                raise TemplateError("InvalidTemplate", f"The provided value for the template parameter '{pname}' is too short (minLength {pdef['minLength']}).")
            if "maxLength" in (pdef or {}) and len(v) > int(pdef["maxLength"]):
                raise TemplateError("InvalidTemplate", f"The provided value for the template parameter '{pname}' is too long (maxLength {pdef['maxLength']}).")
    return ctx


def execute(arm, sub, rg, rec, location=None):
    """Provision rec.properties.template. Returns (provisioned, errors, outputs)."""
    template = (rec.get("properties") or {}).get("template") or {}
    if not isinstance(template.get("resources"), list) or not template["resources"]:
        try:
            ctx = make_ctx(arm, sub, rg, rec, location)
            return [], [], _outputs(ctx, template)
        except TemplateError as e:
            return [], [{"code": e.code, "message": e.message}], {}
    try:
        ctx = make_ctx(arm, sub, rg, rec, location)
        steps = plan(ctx, template)
    except TemplateError as e:
        return [], [{"code": e.code, "message": e.message}], {}
    provisioned, errors = [], []
    failed_ids = set()
    for r in steps:
        if r["deps"] & failed_ids:
            failed_ids.add(r["id"].lower())
            errors.append({"resource": f"{r['type']}/{r['name']}", "status": 409, "error": {"code": "DependencyFailed", "message": "A resource this one depends on failed to deploy."}})
            continue
        path = r["id"]
        resp = arm.handle("PUT", path, {"api-version": r["apiVersion"]}, r["body"])
        if resp["status"] >= 400:
            failed_ids.add(r["id"].lower())
            errors.append({"resource": f"{r['type']}/{r['name']}", "status": resp["status"], "error": resp["body"]})
        else:
            provisioned.append({"id": (resp["body"] or {}).get("id", path) if isinstance(resp["body"], dict) else path, "resourceType": r["type"], "resourceName": r["name"]})
    outputs = {}
    if not errors:
        try:
            outputs = _outputs(ctx, template)
        except TemplateError as e:
            errors.append({"code": e.code, "message": e.message})
    return provisioned, errors, outputs


def _outputs(ctx, template):
    out = {}
    for k, o in (template.get("outputs") or {}).items():
        if isinstance(o, dict) and "value" in o:
            if "condition" in o and not bool(evaluate(ctx, o["condition"])):
                continue
            out[k] = {"type": o.get("type", "String"), "value": evaluate(ctx, o["value"])}
    return out


# ═════════════════════════════ what-if / validate ══════════════════════════════════════════════
_SERVER_KEYS = {"provisioningState", "etag", "resourceGuid", "creationTime", "createdAt", "timestamp"}


def _delta(path, before, after, out):
    """Property-level delta of what the template sets vs what is stored (only keys the template declares)."""
    if isinstance(after, dict) and isinstance(before, dict):
        for k, v in after.items():
            bk = next((x for x in before if str(x).lower() == str(k).lower()), None)
            if bk is None:
                out.append({"path": f"{path}.{k}" if path else k, "propertyChangeType": "Create", "after": v})
            else:
                _delta(f"{path}.{k}" if path else k, before[bk], v, out)
    elif isinstance(after, list) and isinstance(before, list):
        if len(after) != len(before) or any(_norm(a) != _norm(b) and not _subset(a, b) for a, b in zip(after, before)):
            kids = []
            for i, (a, b) in enumerate(zip(after, before)):
                _delta(f"{path}[{i}]", b, a, kids)
            for i in range(len(before), len(after)):
                kids.append({"path": f"{path}[{i}]", "propertyChangeType": "Create", "after": after[i]})
            for i in range(len(after), len(before)):
                kids.append({"path": f"{path}[{i}]", "propertyChangeType": "Delete", "before": before[i]})
            if kids:
                out.append({"path": path, "propertyChangeType": "Array", "children": kids})
    else:
        if _norm(before) != _norm(after):
            out.append({"path": path, "propertyChangeType": "Modify", "before": before, "after": after})


def _norm(v):
    return v.lower() if isinstance(v, str) else v


def _subset(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return all(any(str(k).lower() == str(bk).lower() and _subset(v, bv) for bk, bv in b.items()) for k, v in a.items())
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_subset(x, y) for x, y in zip(a, b))
    return _norm(a) == _norm(b)


def what_if(arm, sub, rg, rec, mode="Incremental", location=None):
    """Returns the WhatIfOperationResult body."""
    template = (rec.get("properties") or {}).get("template") or {}
    try:
        ctx = make_ctx(arm, sub, rg, rec, location)
        steps = plan(ctx, template)
    except TemplateError as e:
        return {"status": "Failed", "error": {"code": e.code, "message": e.message}}
    # references to resources that this template would create can't be evaluated against live state
    changes, seen = [], set()
    for r in steps:
        seen.add(r["id"].lower())
        cur = arm.handle("GET", r["id"], {"api-version": r["apiVersion"]}, None)
        after = {"id": r["id"], "name": r["name"].split("/")[-1], "type": r["type"], **{k: v for k, v in r["body"].items()}}
        if cur["status"] >= 400:
            changes.append({"resourceId": r["id"], "changeType": "Create", "after": after})
            continue
        before = cur["body"] if isinstance(cur["body"], dict) else {}
        d = []
        _delta("", {k: v for k, v in before.items() if k not in ("id", "name", "type")}, {k: v for k, v in r["body"].items()}, d)
        d = [x for x in d if x["path"].split(".")[-1].split("[")[0] not in _SERVER_KEYS]
        if d:
            changes.append({"resourceId": r["id"], "changeType": "Modify", "before": before, "after": {**before, **after}, "delta": d})
        else:
            changes.append({"resourceId": r["id"], "changeType": "NoChange", "before": before, "after": before})
    if str(mode).lower() == "complete" and rg:
        rp = f"/subscriptions/{sub}/resourceGroups/{rg}/".lower()
        for k, v in list(arm.state.items()):
            if not isinstance(v, dict) or (v.get("_rg") or "").lower() != rg.lower() or v.get("_sub") != sub:
                continue
            t = str(v.get("_type") or "").lower()
            if t.startswith(("microsoft.resources/", "microsoft.authorization/", "microsoft.insights/eventtypes")) or t.count("/") > 1:
                continue
            rid = str(v.get("id") or k)
            if rid.lower() not in seen and rid.lower().startswith(rp):
                changes.append({"resourceId": rid, "changeType": "Delete", "before": {kk: vv for kk, vv in v.items() if not kk.startswith("_")}})
    return {"status": "Succeeded", "properties": {"changes": changes}}


def validate(arm, sub, rg, rec, location=None):
    template = (rec.get("properties") or {}).get("template") or {}
    try:
        ctx = make_ctx(arm, sub, rg, rec, location)
        steps = plan(ctx, template)
    except TemplateError as e:
        return {"error": {"code": "InvalidTemplateDeployment", "message": "The template deployment failed validation.",
                          "details": [{"code": e.code, "message": e.message}]}}
    return {"id": f"/subscriptions/{sub}" + (f"/resourceGroups/{rg}" if rg else "") + f"/providers/Microsoft.Resources/deployments/{rec.get('name', '')}",
            "name": rec.get("name"), "type": "Microsoft.Resources/deployments",
            "properties": {"provisioningState": "Succeeded", "mode": (rec.get("properties") or {}).get("mode", "Incremental"),
                           "validatedResources": [{"id": r["id"]} for r in steps]}}
