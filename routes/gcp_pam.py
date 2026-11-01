"""Privileged Access Manager (privilegedaccessmanager.googleapis.com v1) native wire on the
offline appliance.

The engine is core/gcp_pam_core.py (shared with Nano and the dev server). Entitlements and
grants live in the active space's `service_states["gcp_pam"]` slot, so they persist with the
appliance state. Activating a grant is a real project IAM policy change, exactly as on Nano:
the grant/revoke hooks edit the offline project policy (server._gcp_iam_policy_view /
_gcp_iam_set_policy — what projects.getIamPolicy and the console's Allow tab read).
Mounted on the entitlement paths only (`/v1/projects/...` is shared with many GCP APIs).
"""
from __future__ import annotations

from fastapi import FastAPI, Request, Response

from core import app_context as ctx
from core import gcp_pam_core as pam

PLATFORM = ctx.PLATFORM
_KEYS = ("entitlements", "grants", "notifications", "settings")


def _slot() -> dict | None:
    spaces_state = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    active_id = spaces_state.get("active_space_id", "")
    if not active_id:
        return None
    space = spaces_state.setdefault("spaces", {}).setdefault(active_id, {})
    slot = space.setdefault("service_states", {}).setdefault("gcp_pam", {})
    for k in _KEYS:
        slot.setdefault(k, {})
    return slot


class SpacePamStore(pam.PamStore):
    """PamStore whose state is the active space's persisted slot."""

    def __init__(self) -> None:           # no super().__init__: the state attrs are properties
        self._fallback = {k: {} for k in _KEYS}

    def _s(self) -> dict:
        return _slot() or self._fallback

    entitlements = property(lambda self: self._s()["entitlements"])
    grants = property(lambda self: self._s()["grants"])


_STORE = SpacePamStore()


def _project(resource: str) -> str:
    return resource.split("/", 2)[1] if resource.startswith("projects/") else resource


def _edit_policy(resource: str, role: str, member: str, add: bool) -> None:
    import server as s
    project = _project(resource)
    pol = s._gcp_iam_policy_view(project)
    bindings = [dict(b, members=list(b.get("members") or [])) for b in pol.get("bindings") or []]
    b = next((x for x in bindings if x.get("role") == role), None)
    if add:
        if b is None:
            bindings.append({"role": role, "members": [member]})
        elif member not in b["members"]:
            b["members"].append(member)
    elif b is not None and member in b["members"]:
        b["members"].remove(member)
        if not b["members"]:
            bindings.remove(b)
    s._gcp_iam_set_policy(project, {"version": pol.get("version", 1), "etag": pol.get("etag", ""), "bindings": bindings})


def _grant(resource, role, member):
    _edit_policy(resource, role, member, True)


def _revoke(resource, role, member):
    _edit_policy(resource, role, member, False)


def register(app: FastAPI) -> None:
    async def _wire(request: Request):
        r = pam.dispatch(_STORE, request.method, request.url.path, dict(request.query_params),
                         dict(request.headers), await request.body(), grant_fn=_grant, revoke_fn=_revoke)
        # grant expiry is evaluated on reads too (it revokes the binding), so persist after any 2xx
        if r.status < 300 and _slot() is not None:
            ctx.persist_state()
        return Response(content=r.body, status_code=r.status, media_type=r.media_type, headers=r.headers)

    rw = ["GET", "POST", "PATCH", "DELETE"]
    pre = "/v1/projects/{project}/locations/{loc}/entitlements"
    app.add_route(pre, _wire, methods=rw)
    app.add_route(pre + "/{rest:path}", _wire, methods=rw)
