# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
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

Errors use the native GCP shape {"error":{"code","message","status"}}.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
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


def _json(status: int, obj: dict) -> PamResponse:
    return PamResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, message: str, gstatus: str) -> PamResponse:
    body = {"error": {"code": status, "message": message, "status": gstatus}}
    return PamResponse(status=status, body=json.dumps(body).encode())


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


def dispatch(store: PamStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> PamResponse:
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
        if len(segs) == 5:
            if method == "POST":
                return _create(store, project, location, str(query.get("entitlementId", "")).strip(), _body())
            if method == "GET":
                return _list(store, project, location)
            return _err(400, f"Unsupported method {method} on entitlements", "INVALID_ARGUMENT")
        name = f"projects/{project}/locations/{location}/entitlements/{segs[5]}"
        if method == "GET":
            return _get(store, name)
        if method == "DELETE":
            return _delete(store, name)
        return _err(400, f"Unsupported method {method} on entitlement", "INVALID_ARGUMENT")

    return _err(404, f"Unknown path: {path}", "NOT_FOUND")
