"""GCP Resource Manager core — substrate-independent. Speaks a faithful slice of the
native **Cloud Resource Manager v3** (`cloudresourcemanager.googleapis.com`), **Resource
Manager Tags v3** (`tagKeys`) and **Essential Contacts v1** (`essentialcontacts.googleapis.com`)
and **Org Policy v2** (`orgpolicy.googleapis.com`) REST APIs, so the native
`google-cloud-resource-manager` / `google-cloud-resource-settings` SDKs and `gcloud` work
unchanged against it.

NO fastapi / google-cloud / socket / subprocess imports -> loads under Pyodide.

Wire shapes:
    Project
      GET   /v3/projects/{projectId}                 -> Project
      PATCH /v3/projects/{projectId}                  body {displayName?, labels?} -> Project
    Tag keys
      POST   /v3/tagKeys          body {parent,shortName,description} -> TagKey
      GET    /v3/tagKeys?parent=projects/{p}          -> {tagKeys:[...]}
      GET    /v3/tagKeys/{id}
      DELETE /v3/tagKeys/{id}
    Essential contacts
      POST   projects/{p}/contacts   body {email,notificationCategorySubscriptions,languageTag}
      GET    projects/{p}/contacts   -> {contacts:[...]}
      DELETE projects/{p}/contacts/{id}
    Org policies
      POST   {parent}/policies?policyId=constraints/x   body {spec:{rules:[...]}} -> Policy
      GET    {parent}/policies        -> {policies:[...]}
      GET    {name}
      DELETE {name}

Errors use the native GCP shape {"error":{"code","message","status"}}.
"""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from urllib.parse import unquote


@dataclass
class RmResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class ResourceManagerStore:
    """Public dict attrs only -> persisted/synced by core/nano_persist."""

    def __init__(self):
        self.projects: dict = {}       # projectId -> Project
        self.tag_keys: dict = {}       # name "tagKeys/{id}" -> TagKey
        self.contacts: dict = {}       # "projects/{p}/contacts/{id}" -> Contact
        self.org_policies: dict = {}   # policy name -> Policy


def _json(status: int, obj: dict) -> RmResponse:
    return RmResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, message: str, gstatus: str) -> RmResponse:
    body = {"error": {"code": status, "message": message, "status": gstatus}}
    return RmResponse(status=status, body=json.dumps(body).encode())


def _project_number(project_id: str) -> str:
    # Stable 12-digit numeric project number derived from the project id (GCP's are
    # globally-unique random numbers; determinism here just keeps re-reads stable).
    return str(int(hashlib.sha1(project_id.encode()).hexdigest(), 16) % (10 ** 12)).zfill(12)


# ── project ───────────────────────────────────────────────────────────────────
def _get_or_create_project(store: ResourceManagerStore, project_id: str) -> dict:
    p = store.projects.get(project_id)
    if p is None:
        p = {
            "name": f"projects/{_project_number(project_id)}",
            "projectId": project_id,
            "displayName": project_id,
            "state": "ACTIVE",
            "createTime": "2026-01-01T00:00:00Z",
            "etag": base64.b64encode(uuid.uuid4().bytes[:8]).decode(),
            "labels": {},
        }
        store.projects[project_id] = p
    return p


def _get_project(store, project_id) -> RmResponse:
    return _json(200, dict(_get_or_create_project(store, project_id)))


def _patch_project(store, project_id, body) -> RmResponse:
    p = _get_or_create_project(store, project_id)
    if "displayName" in body:
        p["displayName"] = body["displayName"]
    if "labels" in body:
        p["labels"] = dict(body["labels"] or {})
    p["etag"] = base64.b64encode(uuid.uuid4().bytes[:8]).decode()
    return _json(200, dict(p))


# ── tag keys ──────────────────────────────────────────────────────────────────
def _tagkey_id() -> str:
    return "tagKeys/" + str(int(hashlib.sha1(uuid.uuid4().bytes).hexdigest(), 16) % (10 ** 9))


def _create_tag_key(store, body) -> RmResponse:
    short = str(body.get("shortName", "")).strip()
    parent = str(body.get("parent", "")).strip()
    if not short:
        return _err(400, "shortName is required.", "INVALID_ARGUMENT")
    if not parent:
        return _err(400, "parent is required.", "INVALID_ARGUMENT")
    for tk in store.tag_keys.values():
        if tk["parent"] == parent and tk["shortName"] == short:
            return _err(409, f"TagKey {short} already exists under {parent}.", "ALREADY_EXISTS")
    name = _tagkey_id()
    tk = {
        "name": name,
        "parent": parent,
        "shortName": short,
        "namespacedName": f"{parent.split('/')[-1]}/{short}",
        "description": body.get("description", ""),
        "createTime": "2026-01-01T00:00:00Z",
        "etag": base64.b64encode(uuid.uuid4().bytes[:8]).decode(),
    }
    store.tag_keys[name] = tk
    return _json(200, dict(tk))


def _list_tag_keys(store, parent) -> RmResponse:
    out = [dict(tk) for tk in sorted(store.tag_keys.values(), key=lambda t: t["name"]) if tk["parent"] == parent]
    return _json(200, {"tagKeys": out})


def _get_tag_key(store, name) -> RmResponse:
    tk = store.tag_keys.get(name)
    if tk is None:
        return _err(404, f"TagKey {name} not found.", "NOT_FOUND")
    return _json(200, dict(tk))


def _delete_tag_key(store, name) -> RmResponse:
    if name not in store.tag_keys:
        return _err(404, f"TagKey {name} not found.", "NOT_FOUND")
    del store.tag_keys[name]
    return _json(200, {})


# ── essential contacts ────────────────────────────────────────────────────────
def _create_contact(store, project, body) -> RmResponse:
    email = str(body.get("email", "")).strip()
    if not email or "@" not in email:
        return _err(400, "A valid email is required.", "INVALID_ARGUMENT")
    cid = str(uuid.uuid4().int % (10 ** 10))
    name = f"projects/{project}/contacts/{cid}"
    c = {
        "name": name,
        "email": email,
        "notificationCategorySubscriptions": list(body.get("notificationCategorySubscriptions", ["ALL"])),
        "languageTag": body.get("languageTag", "en-US"),
        "validationState": "VALID",
        "validateTime": "2026-01-01T00:00:00Z",
    }
    store.contacts[name] = c
    return _json(200, dict(c))


def _list_contacts(store, project) -> RmResponse:
    prefix = f"projects/{project}/contacts/"
    out = [dict(c) for n, c in sorted(store.contacts.items()) if n.startswith(prefix)]
    return _json(200, {"contacts": out})


def _delete_contact(store, name) -> RmResponse:
    if name not in store.contacts:
        return _err(404, f"Contact {name} not found.", "NOT_FOUND")
    del store.contacts[name]
    return _json(200, {})


# ── org policies ──────────────────────────────────────────────────────────────
def _create_org_policy(store, parent, policy_id, body) -> RmResponse:
    if not policy_id:
        return _err(400, "policyId is required.", "INVALID_ARGUMENT")
    name = f"{parent}/policies/{policy_id}"
    if name in store.org_policies:
        return _err(409, f"Policy {name} already exists.", "ALREADY_EXISTS")
    pol = {
        "name": name,
        "spec": body.get("spec") or {"rules": [{"enforce": True}]},
        "etag": base64.b64encode(uuid.uuid4().bytes[:8]).decode(),
    }
    store.org_policies[name] = pol
    return _json(200, dict(pol))


def _list_org_policies(store, parent) -> RmResponse:
    prefix = f"{parent}/policies/"
    out = [dict(p) for n, p in sorted(store.org_policies.items()) if n.startswith(prefix)]
    return _json(200, {"policies": out})


def _get_org_policy(store, name) -> RmResponse:
    pol = store.org_policies.get(name)
    if pol is None:
        return _err(404, f"Policy {name} not found.", "NOT_FOUND")
    return _json(200, dict(pol))


def _delete_org_policy(store, name) -> RmResponse:
    if name not in store.org_policies:
        return _err(404, f"Policy {name} not found.", "NOT_FOUND")
    del store.org_policies[name]
    return _json(200, {})


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: ResourceManagerStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> RmResponse:
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
    for pre in ("/v1", "/v2", "/v3"):
        if p.startswith(pre + "/") or p == pre:
            p = p[len(pre):]
            break
    p = p.strip("/")
    segs = [unquote(s) for s in p.split("/") if s != ""]

    # ---- tag keys: tagKeys[/{id}] ----
    if segs and segs[0] == "tagKeys":
        if len(segs) == 1:
            if method == "POST":
                return _create_tag_key(store, _body())
            if method == "GET":
                return _list_tag_keys(store, str(query.get("parent", "")).strip())
            return _err(400, f"Unsupported method {method} on tagKeys", "INVALID_ARGUMENT")
        name = f"tagKeys/{segs[1]}"
        if method == "GET":
            return _get_tag_key(store, name)
        if method == "DELETE":
            return _delete_tag_key(store, name)
        return _err(400, f"Unsupported method {method} on tagKey", "INVALID_ARGUMENT")

    # ---- essential contacts: projects/{p}/contacts[/{id}] ----
    if len(segs) >= 3 and segs[0] == "projects" and segs[2] == "contacts":
        project = segs[1]
        if len(segs) == 3:
            if method == "POST":
                return _create_contact(store, project, _body())
            if method == "GET":
                return _list_contacts(store, project)
            return _err(400, f"Unsupported method {method} on contacts", "INVALID_ARGUMENT")
        name = f"projects/{project}/contacts/{segs[3]}"
        if method == "DELETE":
            return _delete_contact(store, name)
        return _err(400, f"Unsupported method {method} on contact", "INVALID_ARGUMENT")

    # ---- org policies: projects/{p}/policies[/{constraint}] ----
    if len(segs) >= 3 and segs[0] == "projects" and segs[2] == "policies":
        parent = f"projects/{segs[1]}"
        if len(segs) == 3:
            if method == "POST":
                return _create_org_policy(store, parent, str(query.get("policyId", "")).strip(), _body())
            if method == "GET":
                return _list_org_policies(store, parent)
            return _err(400, f"Unsupported method {method} on policies", "INVALID_ARGUMENT")
        name = f"{parent}/policies/{segs[3]}"
        if method == "GET":
            return _get_org_policy(store, name)
        if method == "DELETE":
            return _delete_org_policy(store, name)
        return _err(400, f"Unsupported method {method} on policy", "INVALID_ARGUMENT")

    # ---- project: projects/{id} ----
    if len(segs) == 2 and segs[0] == "projects":
        project_id = segs[1]
        if method == "GET":
            return _get_project(store, project_id)
        if method == "PATCH":
            return _patch_project(store, project_id, _body())
        return _err(400, f"Unsupported method {method} on project", "INVALID_ARGUMENT")

    return _err(404, f"Unknown path: {path}", "NOT_FOUND")
