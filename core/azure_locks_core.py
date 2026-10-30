"""Azure Management Locks (Nano / dev_server / unified-ingress core).

``Microsoft.Authorization/locks`` is a real ARM extension resource: azure-mgmt-resource /
``az lock`` address it scoped to the locked resource's OWN id, the same shape as
``Microsoft.EventGrid/eventSubscriptions`` (``core/azure_eventgrid_core.py``) — the URL
re-enters "providers" instead of alternating type/name:

    PUT {scope}/providers/Microsoft.Authorization/locks/{name}?api-version=2016-09-01

Generic over every resource type already in ``AzureArm``'s catalog (not just Event Grid
topics), so any v4 resource blade's "Locks" panel is real once wired to this module. Records
are kept in the SAME flat ``AzureArm.state`` map (keyed by the lock's own canonical, lower-cased
id) so they persist and are swept by the rest of ARM.

Not modelled: subscription/resource-group-scoped locks (only resource-scoped) and lock
enforcement — Vyomi does not block writes/deletes on a locked resource.

Each function returns ``{"status": int, "body": dict | None}``.
"""
from __future__ import annotations

import datetime

API_VERSION = "2016-09-01"
LEVELS = ("CanNotDelete", "ReadOnly")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _view(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _base(scope_rid: str) -> str:
    return f"{scope_rid}/providers/Microsoft.Authorization/locks"


def find_marker(chain):
    """Index of the ``['providers', 'Microsoft.Authorization', 'locks']`` marker in
    ``chain`` (``AzureArm._arm``'s split of everything after the FIRST namespace token),
    or ``None`` if this chain isn't a resource-scoped lock path."""
    for i in range(len(chain) - 2):
        if (chain[i].lower() == "providers" and chain[i + 1].lower() == "microsoft.authorization"
                and chain[i + 2].lower() == "locks"):
            return i
    return None


def list_for(state: dict, scope_rid: str) -> dict:
    items = [_view(r) for r in state.values() if r.get("_lock_scope") == scope_rid.lower()]
    return {"status": 200, "body": {"value": items}}


def get(state: dict, scope_rid: str, name: str) -> dict:
    rec = state.get(f"{_base(scope_rid)}/{name}".lower())
    if not rec:
        return {"status": 404, "body": {"error": {"code": "ResourceNotFound", "message": f"Lock '{name}' was not found."}}}
    return {"status": 200, "body": _view(rec)}


def upsert(state: dict, scope_rid: str, name: str, payload: dict) -> dict:
    rid = f"{_base(scope_rid)}/{name}"
    key = rid.lower()
    props = (payload or {}).get("properties") or {}
    existed = key in state
    rec = state.get(key) if existed else {
        "id": rid, "name": name, "type": "Microsoft.Authorization/locks",
        "_lock_scope": scope_rid.lower(), "_created": _now(),
    }
    level = props.get("level") or (rec.get("properties") or {}).get("level") or "CanNotDelete"
    rec["properties"] = {
        "level": level if level in LEVELS else "CanNotDelete",
        "notes": props.get("notes", (rec.get("properties") or {}).get("notes", "")),
    }
    state[key] = rec
    return {"status": 200 if existed else 201, "body": _view(rec)}


def remove(state: dict, scope_rid: str, name: str) -> dict:
    rec = state.pop(f"{_base(scope_rid)}/{name}".lower(), None)
    return {"status": 200 if rec is not None else 204, "body": None}
