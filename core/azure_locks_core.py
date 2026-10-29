"""Azure management locks core (``Microsoft.Authorization/locks``, api-version 2020-05-01).

Substrate-free so the SAME file runs offline and in Nano. A lock is an *extension resource*: it hangs off a
subscription, a resource group or any resource, and is addressed as

    {scope}/providers/Microsoft.Authorization/locks/{name}       (PUT / GET / DELETE)
    {scope}/providers/Microsoft.Authorization/locks              (GET: locks at the scope and below)

so ``azure-mgmt-resource`` ``ManagementLockClient`` / ``armlocks`` / ``az lock`` work unchanged. Locks live in
the same ARM state map as every other resource (record key = lower-cased lock id, ``_type`` =
``Microsoft.Authorization/locks``) so they persist with the rest of ARM.
"""
from __future__ import annotations

NAMESPACE = "Microsoft.Authorization"
TYPE = "locks"
FULL_TYPE = "Microsoft.Authorization/locks"
API_VERSION = "2020-05-01"
LEVELS = ("CanNotDelete", "ReadOnly")


def _split(after):
    """(scope_chain, rest) where ``rest`` starts at ``locks``; None when ``after`` is not a lock path."""
    low = [a.lower() for a in after]
    for i in range(len(after) - 2, -1, -1):
        if low[i] == "microsoft.authorization" and low[i + 1] == "locks" and (i == 0 or low[i - 1] == "providers"):
            return (after[:i - 1] if i else []), after[i + 1:]
    return None


def handles(after):
    s = _split(after)
    return bool(s) and len(s[1]) in (1, 2)


def _scope(sub, rg, scope_chain):
    base = f"/subscriptions/{sub}" + (f"/resourceGroups/{rg}" if rg else "")
    if scope_chain:
        base += "/providers/" + "/".join(scope_chain)
    return base


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "lro": False, "rid": "", "verb": ""}


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def dispatch(state, method, sub, rg, after, payload, query, base=""):
    scope_chain, rest = _split(after)
    scope = _scope(sub, rg, scope_chain)
    name = rest[1] if len(rest) == 2 else None
    out = {"status": 200, "headers": {}, "body": None, "lro": False, "rid": "", "verb": ""}
    if name is None:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        pre = scope.lower()
        items = [_view(r) for r in state.values() if r.get("_type") == FULL_TYPE
                 and (r["_scope"].lower() == pre or r["_scope"].lower().startswith(pre + "/"))]
        out["body"] = {"value": sorted(items, key=lambda x: x["name"].lower())}
        return out
    rid = f"{scope}/providers/{FULL_TYPE}/{name}"
    key = rid.lower()
    if method == "GET":
        rec = state.get(key)
        if rec is None:
            return _err(404, "LockNotFound", f"The lock '{name}' could not be found.")
        out["body"] = _view(rec)
        return out
    if method == "DELETE":
        if state.pop(key, None) is None:
            out["status"] = 204
        return out
    if method not in ("PUT", "PATCH"):
        return _err(405, "MethodNotAllowed", f"{method} is not supported on a lock.")
    props = (payload or {}).get("properties") or {}
    level = props.get("level")
    if level not in LEVELS:
        return _err(400, "InvalidLockLevel", f"The lock level '{level}' is invalid. Valid levels are CanNotDelete and ReadOnly.")
    existed = key in state
    rec = {"id": rid, "name": name, "type": FULL_TYPE,
           "properties": {"level": level, "notes": props.get("notes") or "",
                          "owners": props.get("owners") or []},
           "_type": FULL_TYPE, "_scope": scope, "_sub": sub, "_rg": rg}
    state[key] = rec
    out["status"] = 200 if existed else 201
    out["body"] = _view(rec)
    out["rid"], out["verb"] = rid, "put"
    return out
