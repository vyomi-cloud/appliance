"""GCP Privileged Access Manager core — substrate-independent. Speaks a faithful slice
of the native **Privileged Access Manager v1** REST API (`privilegedaccessmanager.googleapis.com`)
so the native `google-cloud-privilegedaccessmanager` SDK and `gcloud pam` work unchanged
against it.

NO fastapi / google-cloud / socket / subprocess imports -> loads under Pyodide.

Wire shapes:
    POST   projects/{p}/locations/{loc}/entitlements?entitlementId=X
           body {maxRequestDuration, privilegedAccess, eligibleUsers, approvalWorkflow}
           -> Entitlement {name,state,...}
    GET    projects/{p}/locations/{loc}/entitlements           -> {entitlements:[...]}
    GET    projects/{p}/locations/{loc}/entitlements/{id}
    DELETE projects/{p}/locations/{loc}/entitlements/{id}

    POST   .../entitlements/{id}/grants       body {requestedDuration, justification, requester}
           -> Grant {name,state,timeline,...}  (REQUESTED; ACTIVATED immediately if the
           entitlement has no approval steps)
    GET    .../entitlements/{id}/grants                        -> {grants:[...]}
    GET    .../entitlements/{id}/grants/{gid}
    POST   .../grants/{gid}:approve  body {approver}  -> activates the grant
    POST   .../grants/{gid}:deny     body {approver}
    POST   .../grants/{gid}:revoke   body {actor}     -> ends an active grant early

Activating a grant is a REAL IAM policy change: the caller-supplied `grant_fn(resource,
role, member)` / `revoke_fn(...)` hooks (the wire router binds these to
core/gcp_iam_core.py's grant_member / revoke_member, the same store the console's "Allow"
tab reads) add/remove the requester as a member of the entitlement's role(s) on the
project for the grant's duration. A lazy sweep on every grants read expires any grant
past its `scheduledExpireTime` and removes the binding — no background scheduler needed.

Errors use the native GCP shape {"error":{"code","message","status"}}.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import unquote


@dataclass
class PamResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class PamStore:
    """Public dict attrs only -> persisted/synced by core/nano_persist."""

    def __init__(self):
        self.entitlements: dict = {}   # name -> Entitlement
        self.grants: dict = {}         # name (entitlement/grants/id) -> Grant


def _json(status: int, obj: dict) -> PamResponse:
    return PamResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, message: str, gstatus: str) -> PamResponse:
    body = {"error": {"code": status, "message": message, "status": gstatus}}
    return PamResponse(status=status, body=json.dumps(body).encode())


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _iso_from_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_duration(s) -> float:
    s = str(s or "").strip()
    if s.endswith("s"):
        try:
            return float(s[:-1])
        except ValueError:
            pass
    return 3600.0


def _create(store: PamStore, project, location, entitlement_id, body) -> PamResponse:
    if not entitlement_id:
        return _err(400, "entitlementId is required.", "INVALID_ARGUMENT")
    name = f"projects/{project}/locations/{location}/entitlements/{entitlement_id}"
    if name in store.entitlements:
        return _err(409, f"Entitlement {entitlement_id} already exists.", "ALREADY_EXISTS")
    ent = {
        "name": name,
        "state": "AVAILABLE",
        "maxRequestDuration": body.get("maxRequestDuration", "3600s"),
        "privilegedAccess": body.get("privilegedAccess") or {},
        "eligibleUsers": list(body.get("eligibleUsers", [])),
        "approvalWorkflow": body.get("approvalWorkflow") or {},
        "createTime": "2026-01-01T00:00:00Z",
    }
    store.entitlements[name] = ent
    return _json(200, dict(ent))


def _list(store: PamStore, project, location) -> PamResponse:
    prefix = f"projects/{project}/locations/{location}/entitlements/"
    out = [dict(e) for n, e in sorted(store.entitlements.items()) if n.startswith(prefix)]
    return _json(200, {"entitlements": out})


def _get(store: PamStore, name) -> PamResponse:
    ent = store.entitlements.get(name)
    if ent is None:
        return _err(404, f"Entitlement {name} not found.", "NOT_FOUND")
    return _json(200, dict(ent))


def _delete(store: PamStore, name) -> PamResponse:
    if name not in store.entitlements:
        return _err(404, f"Entitlement {name} not found.", "NOT_FOUND")
    del store.entitlements[name]
    return _json(200, {})


# ── grants (requesting / approving / time-boxed activation) ─────────────────
def _grant_view(g: dict) -> dict:
    return {k: v for k, v in g.items() if not k.startswith("_")}


def _role_bindings(ent: dict) -> list:
    return ((ent.get("privilegedAccess") or {}).get("gcpIamAccess") or {}).get("roleBindings", []) or []


def _requires_approval(ent: dict) -> bool:
    steps = ((ent.get("approvalWorkflow") or {}).get("manualApprovals") or {}).get("steps") or []
    return bool(steps)


def _apply_bindings(grant: dict, fn) -> None:
    if not fn:
        return
    for rb in _role_bindings({"privilegedAccess": grant.get("privilegedAccess")}):
        role = rb.get("role")
        if role:
            fn(grant["_project_resource"], role, grant["requester"])


def _activate(grant: dict, grant_fn, actor: str) -> None:
    duration = _parse_duration(grant["requestedDuration"])
    expire_ts = _now_ts() + duration
    grant["state"] = "ACTIVATED"
    grant["_expire_ts"] = expire_ts
    grant["scheduledExpireTime"] = _iso_from_ts(expire_ts)
    now = _now_iso()
    grant["updateTime"] = now
    grant["timeline"]["events"].append({"eventTime": now, "event": "ACTIVATED", "actor": actor})
    _apply_bindings(grant, grant_fn)


def _end(grant: dict, revoke_fn, state: str, actor: str) -> None:
    _apply_bindings(grant, revoke_fn)
    grant["state"] = state
    grant["_expire_ts"] = None
    now = _now_iso()
    grant["updateTime"] = now
    grant["timeline"]["events"].append({"eventTime": now, "event": state, "actor": actor})


def _sweep(store: PamStore, revoke_fn) -> None:
    now_ts = _now_ts()
    for g in store.grants.values():
        if g["state"] == "ACTIVATED" and g.get("_expire_ts") and now_ts >= g["_expire_ts"]:
            _end(g, revoke_fn, "EXPIRED", "system")


def _create_grant(store: PamStore, entitlement_name, body, project_resource, grant_fn) -> PamResponse:
    ent = store.entitlements.get(entitlement_name)
    if ent is None:
        return _err(404, f"Entitlement {entitlement_name} not found.", "NOT_FOUND")
    gid = uuid.uuid4().hex[:12]
    name = f"{entitlement_name}/grants/{gid}"
    requester = str(body.get("requester") or "user:console@example.com")
    now = _now_iso()
    needs_approval = _requires_approval(ent)
    grant = {
        "name": name,
        "requester": requester,
        "requestedDuration": body.get("requestedDuration") or ent.get("maxRequestDuration", "3600s"),
        "justification": body.get("justification") or {},
        "privilegedAccess": ent.get("privilegedAccess") or {},
        "state": "APPROVAL_AWAITED" if needs_approval else "ACTIVATED",
        "createTime": now,
        "updateTime": now,
        "timeline": {"events": [{"eventTime": now, "event": "REQUESTED", "actor": requester}]},
        "_expire_ts": None,
        "_project_resource": project_resource,
    }
    store.grants[name] = grant
    if not needs_approval:
        _activate(grant, grant_fn, "system (auto-approved — no approvers configured)")
    return _json(200, _grant_view(grant))


def _list_grants(store: PamStore, entitlement_name, revoke_fn) -> PamResponse:
    _sweep(store, revoke_fn)
    prefix = entitlement_name + "/grants/"
    out = [_grant_view(g) for n, g in sorted(store.grants.items()) if n.startswith(prefix)]
    return _json(200, {"grants": out})


def _get_grant(store: PamStore, name, revoke_fn) -> PamResponse:
    _sweep(store, revoke_fn)
    g = store.grants.get(name)
    if g is None:
        return _err(404, f"Grant {name} not found.", "NOT_FOUND")
    return _json(200, _grant_view(g))


def _approve_grant(store: PamStore, name, body, grant_fn, revoke_fn) -> PamResponse:
    _sweep(store, revoke_fn)
    g = store.grants.get(name)
    if g is None:
        return _err(404, f"Grant {name} not found.", "NOT_FOUND")
    if g["state"] != "APPROVAL_AWAITED":
        return _err(400, f"Grant {name} is not awaiting approval.", "FAILED_PRECONDITION")
    _activate(g, grant_fn, str(body.get("approver") or "user:approver@example.com"))
    return _json(200, _grant_view(g))


def _deny_grant(store: PamStore, name, body, revoke_fn) -> PamResponse:
    _sweep(store, revoke_fn)
    g = store.grants.get(name)
    if g is None:
        return _err(404, f"Grant {name} not found.", "NOT_FOUND")
    if g["state"] != "APPROVAL_AWAITED":
        return _err(400, f"Grant {name} is not awaiting approval.", "FAILED_PRECONDITION")
    now = _now_iso()
    g["state"], g["updateTime"] = "DENIED", now
    g["timeline"]["events"].append({"eventTime": now, "event": "DENIED", "actor": str(body.get("approver") or "user:approver@example.com")})
    return _json(200, _grant_view(g))


def _revoke_grant(store: PamStore, name, body, revoke_fn) -> PamResponse:
    _sweep(store, revoke_fn)
    g = store.grants.get(name)
    if g is None:
        return _err(404, f"Grant {name} not found.", "NOT_FOUND")
    if g["state"] != "ACTIVATED":
        return _err(400, f"Grant {name} is not active.", "FAILED_PRECONDITION")
    _end(g, revoke_fn, "REVOKED", str(body.get("actor") or "user:console@example.com"))
    return _json(200, _grant_view(g))


def dispatch(store: PamStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", grant_fn=None, revoke_fn=None) -> PamResponse:
    query = query or {}
    method = method.upper()

    def _body() -> dict:
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return {}

    p = path.split("?", 1)[0]
    if p.startswith("/v1/") or p == "/v1":
        p = p[len("/v1"):]
    p = p.strip("/")
    segs = [unquote(s) for s in p.split("/") if s != ""]

    if (len(segs) >= 5 and segs[0] == "projects" and segs[2] == "locations"
            and segs[4] == "entitlements"):
        project, location = segs[1], segs[3]
        project_resource = f"projects/{project}"
        if len(segs) == 5:
            if method == "POST":
                return _create(store, project, location, str(query.get("entitlementId", "")).strip(), _body())
            if method == "GET":
                return _list(store, project, location)
            return _err(400, f"Unsupported method {method} on entitlements", "INVALID_ARGUMENT")
        entitlement_name = f"projects/{project}/locations/{location}/entitlements/{segs[5]}"
        if len(segs) == 6:
            if method == "GET":
                return _get(store, entitlement_name)
            if method == "DELETE":
                return _delete(store, entitlement_name)
            return _err(400, f"Unsupported method {method} on entitlement", "INVALID_ARGUMENT")
        if len(segs) >= 7 and segs[6] == "grants":
            if len(segs) == 7:
                if method == "POST":
                    return _create_grant(store, entitlement_name, _body(), project_resource, grant_fn)
                if method == "GET":
                    return _list_grants(store, entitlement_name, revoke_fn)
                return _err(400, f"Unsupported method {method} on grants", "INVALID_ARGUMENT")
            last = segs[7]
            if ":" in last:
                gid, action = last.split(":", 1)
            else:
                gid, action = last, None
            grant_name = f"{entitlement_name}/grants/{gid}"
            if action is None and method == "GET":
                return _get_grant(store, grant_name, revoke_fn)
            if action == "approve" and method == "POST":
                return _approve_grant(store, grant_name, _body(), grant_fn, revoke_fn)
            if action == "deny" and method == "POST":
                return _deny_grant(store, grant_name, _body(), revoke_fn)
            if action == "revoke" and method == "POST":
                return _revoke_grant(store, grant_name, _body(), revoke_fn)
            return _err(400, f"Unsupported method {method} on grant", "INVALID_ARGUMENT")
        return _err(404, f"Unknown path: {path}", "NOT_FOUND")

    return _err(404, f"Unknown path: {path}", "NOT_FOUND")
