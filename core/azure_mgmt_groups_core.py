"""Azure management groups (Microsoft.Management/managementGroups) - the tenant-level hierarchy above subscriptions.

Native ARM wire (api-version 2021-04-01 / 2020-05-01 shapes):
  GET    /providers/Microsoft.Management/managementGroups                      list
  GET    /providers/Microsoft.Management/managementGroups/{id}[?$expand=children&$recurse=true]
  PUT    /providers/Microsoft.Management/managementGroups/{id}                 create / update (properties.displayName, details.parent.id)
  PATCH  /providers/Microsoft.Management/managementGroups/{id}                 move / rename
  DELETE /providers/Microsoft.Management/managementGroups/{id}                 (409 while it has children / subscriptions)
  GET    /providers/Microsoft.Management/managementGroups/{id}/descendants
  PUT    /providers/Microsoft.Management/managementGroups/{id}/subscriptions/{sub}      move a subscription under the group
  DELETE /providers/Microsoft.Management/managementGroups/{id}/subscriptions/{sub}      back to the root group
  POST   /providers/Microsoft.Management/checkNameAvailability

State: ordinary ARM records inside the space's ARM state dict (so they persist with it on Mesh and Nano), keyed lower-case:
  /providers/microsoft.management/managementgroups/{id}                       the group
  /providers/microsoft.management/managementgroups/{id}/subscriptions/{sub}   the subscription's membership record
The tenant root group (id = tenant id) is virtual, created on first use, can not be deleted; every subscription without a record
sits under it (`ensure` materialises the space's subscription there). core/iam_state_adapters.azure_state feeds both record types to
core/iam_engine/azure_eval.py (RBAC + deny assignments inherit down the chain) and core/azure_arm_core policy evaluation walks the same chain.
Pure stdlib - loads under Pyodide.
"""
from __future__ import annotations

import datetime as _dt
import re

TENANT_ID = "00000000-0000-0000-0000-000000000000"
SUB = "00000000-0000-0000-0000-cloudlearn01"
MG_T = "Microsoft.Management/managementGroups"
SUB_T = "Microsoft.Management/managementGroups/subscriptions"
_PFX = "/providers/microsoft.management/managementgroups/"
_NAME = re.compile(r"^[A-Za-z0-9._()\-]{1,90}$")
MAX_DEPTH = 6          # real Azure: 6 levels of management groups below the root (the subscription level is extra)


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def _ok(body, status=200):
    return {"status": status, "headers": {}, "body": body}


def _now():
    return _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def mg_id(name):
    return "/providers/Microsoft.Management/managementGroups/" + name


def _key(name):
    return _PFX + str(name).lower()


def _skey(mg, sub):
    return _key(mg) + "/subscriptions/" + str(sub).lower()


def _is_group(r):
    return isinstance(r, dict) and str(r.get("_type") or "").lower() == MG_T.lower()


def _is_member(r):
    return isinstance(r, dict) and str(r.get("_type") or "").lower() == SUB_T.lower()


def groups(state):
    return {str(r["name"]).lower(): r for r in state.values() if _is_group(r)}


def members(state):
    return [r for r in state.values() if _is_member(r)]


def _parent_name(rec):
    pid = (((rec.get("properties") or {}).get("details") or {}).get("parent") or {}).get("id") or ""
    return pid.rstrip("/").rsplit("/", 1)[-1] or TENANT_ID


def ensure(state):
    """Root group record + the space's subscription under it (idempotent). Called by every handler and by the IAM state adapter."""
    rk = _key(TENANT_ID)
    if rk not in state:
        state[rk] = {"id": mg_id(TENANT_ID), "name": TENANT_ID, "type": MG_T, "_type": MG_T, "_root": True,
                     "properties": {"tenantId": TENANT_ID, "displayName": "Tenant Root Group",
                                    "details": {"version": 1, "updatedTime": _now(), "updatedBy": "", "parent": None}}}
    if not any(_is_member(r) and r["name"].lower() == SUB.lower() for r in state.values()):
        _put_member(state, TENANT_ID, SUB)
    return state[rk]


def _put_member(state, mg, sub):
    for k in [k for k, r in state.items() if _is_member(r) and str(r["name"]).lower() == str(sub).lower()]:
        del state[k]
    state[_skey(mg, sub)] = {"id": mg_id(mg) + "/subscriptions/" + sub, "name": sub, "type": SUB_T, "_type": SUB_T,
                             "properties": {"displayName": "Vyomi Subscription" if sub.lower() == SUB.lower() else sub,
                                            "state": "Enabled", "tenant": TENANT_ID, "parent": {"id": mg_id(mg)}}}


def sub_parent(state, sub):
    for r in state.values():
        if _is_member(r) and str(r["name"]).lower() == str(sub).lower():
            return r["properties"]["parent"]["id"].rsplit("/", 1)[-1]
    return TENANT_ID


def chain(state, mg):
    """[mg, parent, ..., root] (names, original case)."""
    gs, out, seen = groups(state), [], set()
    cur = mg
    while cur and cur.lower() not in seen:
        seen.add(cur.lower())
        out.append(gs[cur.lower()]["name"] if cur.lower() in gs else cur)
        rec = gs.get(cur.lower())
        cur = _parent_name(rec) if rec and not rec.get("_root") else None
    return out


def sub_chain(state, sub):
    """Management group names enclosing a subscription, nearest first (incl. root)."""
    return chain(state, sub_parent(state, sub))


def _children(state, name):
    low = name.lower()
    kids = [r for r in groups(state).values() if not r.get("_root") and _parent_name(r).lower() == low]
    subs = [r for r in members(state) if r["properties"]["parent"]["id"].rsplit("/", 1)[-1].lower() == low]
    return kids, subs


def _depth(state, name):
    return len(chain(state, name)) - 1          # root = 0


def _view(r, expand=False, recurse=False, state=None):
    d = r["properties"].get("details") or {}
    body = {"id": r["id"], "type": MG_T, "name": r["name"],
            "properties": {"tenantId": TENANT_ID, "displayName": r["properties"].get("displayName") or r["name"]}}
    if r.get("_root") and not expand:
        body["properties"]["details"] = {"version": d.get("version", 1), "updatedTime": d.get("updatedTime"), "updatedBy": "", "parent": None}
    if not r.get("_root"):
        par = groups(state).get(_parent_name(r).lower()) if state is not None else None
        body["properties"]["details"] = {"version": d.get("version", 1), "updatedTime": d.get("updatedTime"), "updatedBy": d.get("updatedBy", ""),
                                         "parent": {"id": mg_id(_parent_name(r)), "displayName": (par or {}).get("properties", {}).get("displayName") or _parent_name(r),
                                                    "name": _parent_name(r)}}
    if expand and state is not None:
        body["properties"]["children"] = _child_tree(state, r["name"], recurse)
    return body


def _child_tree(state, name, recurse):
    kids, subs = _children(state, name)
    out = []
    for k in sorted(kids, key=lambda x: x["name"].lower()):
        c = {"type": MG_T, "id": k["id"], "name": k["name"], "displayName": k["properties"].get("displayName") or k["name"]}
        if recurse:
            c["children"] = _child_tree(state, k["name"], True)
        out.append(c)
    for s in sorted(subs, key=lambda x: x["name"].lower()):
        out.append({"type": "/subscriptions", "id": "/subscriptions/" + s["name"], "name": s["name"], "displayName": s["properties"].get("displayName") or s["name"]})
    return out


def descendants(state, name):
    out = []
    kids, subs = _children(state, name)
    for k in sorted(kids, key=lambda x: x["name"].lower()):
        out.append({"id": k["id"], "type": MG_T, "name": k["name"],
                    "properties": {"displayName": k["properties"].get("displayName") or k["name"], "parent": {"id": mg_id(name)}}})
        out += descendants(state, k["name"])
    for s in sorted(subs, key=lambda x: x["name"].lower()):
        out.append({"id": "/subscriptions/" + s["name"], "type": "/subscriptions", "name": s["name"],
                    "properties": {"displayName": s["properties"].get("displayName") or s["name"], "parent": {"id": mg_id(name)}}})
    return out


def tree(state):
    """The whole hierarchy as nested dicts (the console's tree view): root -> groups -> subscriptions."""
    ensure(state)

    def node(r):
        kids, subs = _children(state, r["name"])
        return {"id": r["id"], "name": r["name"], "displayName": r["properties"].get("displayName") or r["name"], "kind": "managementGroup",
                "root": bool(r.get("_root")),
                "children": [node(k) for k in sorted(kids, key=lambda x: x["name"].lower())]
                + [{"id": "/subscriptions/" + s["name"], "name": s["name"], "displayName": s["properties"].get("displayName") or s["name"], "kind": "subscription", "children": []}
                   for s in sorted(subs, key=lambda x: x["name"].lower())]}
    return node(state[_key(TENANT_ID)])


def _parse(path):
    p = path.split("?", 1)[0].rstrip("/")
    i = p.lower().find("/providers/microsoft.management/")
    if i < 0:
        return None
    return [s for s in p[i + len("/providers/microsoft.management/"):].split("/") if s]


def handle(state, method, path, query=None, body=None):
    """-> ARM response dict, or None when `path` is not a Microsoft.Management path."""
    segs = _parse(str(path))
    if segs is None:
        return None
    method = (method or "GET").upper()
    query = {str(k).lower(): (v[0] if isinstance(v, list) and v else v) for k, v in (query or {}).items()}
    if "?" in str(path):          # raw query string carried on the path
        from urllib.parse import parse_qsl
        for k, v in parse_qsl(str(path).split("?", 1)[1]):
            query.setdefault(k.lower(), v)
    body = body if isinstance(body, dict) else {}
    ensure(state)
    head = segs[0].lower()
    if head == "checknameavailability" and method == "POST":
        name = str(body.get("name") or "")
        if not _NAME.match(name):
            return _ok({"nameAvailable": False, "reason": "Invalid", "message": "The name is invalid."})
        taken = name.lower() in groups(state)
        return _ok({"nameAvailable": not taken, "reason": "AlreadyExists" if taken else None,
                    "message": f"The management group '{name}' already exists." if taken else None})
    if head != "managementgroups":
        return _err(404, "NotFound", f"Unsupported Microsoft.Management path: {path}")
    gs = groups(state)
    if len(segs) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Use GET to list management groups.")
        return _ok({"value": [{"id": r["id"], "type": MG_T, "name": r["name"], "properties": {"tenantId": TENANT_ID,
                                                                                                     "displayName": r["properties"].get("displayName") or r["name"]}}
                              for r in sorted(gs.values(), key=lambda x: x["name"].lower())]})
    name = segs[1]
    rec = gs.get(name.lower())
    if len(segs) == 2:
        if method == "GET":
            if rec is None:
                return _err(404, "NotFound", f"The management group '{name}' was not found.")
            exp = str(query.get("$expand") or "").lower() == "children"
            return _ok(_view(rec, exp, str(query.get("$recurse") or "").lower() == "true", state))
        if method in ("PUT", "PATCH"):
            return _upsert(state, name, rec, body, method)
        if method == "DELETE":
            if rec is None:
                return _ok({}, 204)
            if rec.get("_root"):
                return _err(400, "BadRequest", "The tenant root management group cannot be deleted.")
            kids, subs = _children(state, name)
            if kids or subs:
                return _err(409, "ConflictError", f"The management group '{name}' cannot be deleted while it has child management groups or subscriptions.")
            for k in [k for k in state if k.startswith(_key(name) + "/") or k == _key(name)]:
                del state[k]
            for k in [k for k, r in state.items() if isinstance(r, dict) and str(r.get("_mg") or "").lower() == name.lower()]:
                del state[k]                       # its policy / role assignments go with it
            return _ok({"id": mg_id(name), "name": name, "type": MG_T}, 200)
    if rec is None:
        return _err(404, "NotFound", f"The management group '{name}' was not found.")
    if len(segs) >= 5 and segs[2].lower() == "providers" and segs[3].lower() == "microsoft.authorization" and segs[4].lower() == "policyassignments":
        return _policy_assignment(state, rec["name"], segs[5:], method, body)
    if len(segs) == 3 and segs[2].lower() == "descendants" and method == "GET":
        return _ok({"value": descendants(state, rec["name"])})
    if len(segs) == 4 and segs[2].lower() == "subscriptions":
        sub = segs[3]
        if method == "PUT":
            if sub.lower() != SUB.lower() and sub.lower() not in {m["name"].lower() for m in members(state)}:
                return _err(404, "SubscriptionNotFound", f"The subscription '{sub}' could not be found.")
            _put_member(state, rec["name"], sub)
            return _ok({k: v for k, v in state[_skey(rec["name"], sub)].items() if not k.startswith("_")})
        if method == "DELETE":
            if sub_parent(state, sub).lower() != name.lower():
                return _err(404, "NotFound", f"The subscription '{sub}' is not a child of management group '{name}'.")
            _put_member(state, TENANT_ID, sub)
            return _ok({}, 200)
        if method == "GET":
            if sub_parent(state, sub).lower() != name.lower():
                return _err(404, "NotFound", f"The subscription '{sub}' is not a child of management group '{name}'.")
            return _ok({k: v for k, v in state[_skey(rec["name"], sub)].items() if not k.startswith("_")})
    return _err(404, "NotFound", f"Unsupported {method} {path}")


def _upsert(state, name, rec, body, method):
    props = body.get("properties") or {}
    if rec is not None and rec.get("_root"):
        if props.get("displayName"):
            rec["properties"]["displayName"] = str(props["displayName"])
        return _ok(_view(rec, False, False, state))
    if rec is None and method == "PATCH":
        return _err(404, "NotFound", f"The management group '{name}' was not found.")
    if not _NAME.match(name):
        return _err(400, "BadRequest", "The management group name may contain only letters, digits, '-', '_', '.', '(' and ')' (max 90).")
    parent = ((props.get("details") or {}).get("parent") or {}).get("id")
    pname = parent.rstrip("/").rsplit("/", 1)[-1] if parent else (_parent_name(rec) if rec else TENANT_ID)
    gs = groups(state)
    if pname.lower() not in gs:
        return _err(400, "BadRequest", f"The parent management group '{pname}' was not found.")
    if pname.lower() == name.lower() or name.lower() in {c.lower() for c in chain(state, pname)}:
        return _err(400, "BadRequest", "A management group cannot be moved under itself or one of its descendants.")
    if rec is None and _depth(state, pname) + 1 > MAX_DEPTH:
        return _err(400, "BadRequest", f"The management group hierarchy cannot be deeper than {MAX_DEPTH} levels (excluding the root and subscription levels).")
    if rec is not None and _depth(state, pname) + 1 + _subtree_height(state, name) > MAX_DEPTH:
        return _err(400, "BadRequest", f"The move would make the hierarchy deeper than {MAX_DEPTH} levels.")
    ver = ((rec or {}).get("properties", {}).get("details") or {}).get("version", 0) + 1
    disp = props.get("displayName") or (rec or {}).get("properties", {}).get("displayName") or name
    state[_key(name)] = {"id": mg_id(name), "name": name if rec is None else rec["name"], "type": MG_T, "_type": MG_T,
                         "properties": {"tenantId": TENANT_ID, "displayName": disp,
                                        "details": {"version": ver, "updatedTime": _now(), "updatedBy": "", "parent": {"id": mg_id(gs[pname.lower()]["name"])}}}}
    return _ok(_view(state[_key(name)], False, False, state), 200)


def _subtree_height(state, name):
    kids, _ = _children(state, name)
    return 0 if not kids else 1 + max(_subtree_height(state, k["name"]) for k in kids)


# ---------------------------------------------------------------- assignments at management-group scope
def scope_mg(path):
    """'/providers/Microsoft.Management/managementGroups/x/providers/...' -> 'x' (None when the scope is not a management group)."""
    m = re.match(r"^/providers/microsoft\.management/managementgroups/([^/]+)(?:/|$)", str(path).split("?", 1)[0], re.I)
    return m.group(1) if m else None


def _pa_key(mg, name):
    return _key(mg) + "/providers/microsoft.authorization/policyassignments/" + str(name).lower()


def _policy_assignment(state, mg, tail, method, body):
    """Azure Policy assignments at management-group scope. Evaluated by core/azure_arm_core (`_policy_assignments_for`) for every
    subscription below the group, exactly like a subscription-scope assignment."""
    pfx = _key(mg) + "/providers/microsoft.authorization/policyassignments/"
    if not tail:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Use GET to list policy assignments.")
        return _ok({"value": [{k: v for k, v in r.items() if not k.startswith("_")} for k, r in sorted(state.items()) if k.startswith(pfx)]})
    name = tail[0]
    k = _pa_key(mg, name)
    if method == "GET":
        if k not in state:
            return _err(404, "PolicyAssignmentNotFound", f"The policy assignment '{name}' is not found.")
        return _ok({kk: v for kk, v in state[k].items() if not kk.startswith("_")})
    if method == "PUT":
        props = dict(body.get("properties") or {})
        if not props.get("policyDefinitionId"):
            return _err(400, "InvalidRequestContent", "The request content was invalid: properties.policyDefinitionId is required.")
        props.setdefault("displayName", name)
        props.setdefault("enforcementMode", "Default")
        props["scope"] = mg_id(mg)
        state[k] = {"id": mg_id(mg) + "/providers/Microsoft.Authorization/policyAssignments/" + name, "name": name,
                    "type": "Microsoft.Authorization/policyAssignments", "_type": "Microsoft.Authorization/policyAssignments",
                    "_mg": mg, "properties": props, "location": body.get("location"), "identity": body.get("identity")}
        return _ok({kk: v for kk, v in state[k].items() if not kk.startswith("_")}, 201)
    if method == "DELETE":
        if state.pop(k, None) is None:
            return _ok({}, 204)
        return _ok({}, 200)
    return _err(405, "MethodNotAllowed", f"{method} is not supported.")


def policy_assignments_above(state, sub):
    """Policy assignment records at the management groups that enclose `sub` (nearest first)."""
    out = []
    for mg in sub_chain(state, sub):
        pfx = _key(mg) + "/providers/microsoft.authorization/policyassignments/"
        out += [r for k, r in sorted(state.items()) if k.startswith(pfx)]
    return out
