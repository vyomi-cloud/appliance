"""GCP Resource Manager core — substrate-independent. Speaks a faithful slice of the
native **Cloud Resource Manager v3** (`cloudresourcemanager.googleapis.com`), **Resource
Manager Tags v3** (`tagKeys`) and **Essential Contacts v1** (`essentialcontacts.googleapis.com`)
and **Org Policy v2** (`orgpolicy.googleapis.com`) REST APIs, so the native
`google-cloud-resource-manager` / `google-cloud-resource-settings` SDKs and `gcloud` work
unchanged against it.

NO fastapi / google-cloud / socket / subprocess imports -> loads under Pyodide.

Wire shapes:
    Project
      GET    /v3/projects/{projectId}                 -> Project
      PATCH  /v3/projects/{projectId}                  body {displayName?, labels?} -> Project
      POST   /v3/projects                              body {projectId,displayName?,parent?} -> Project
      GET    /v3/projects:search?query=                -> {projects:[...]}  (name/ID substring match)
      DELETE /v3/projects/{projectId}                  -> {}  (immediate delete; Vyomi has no
                                                          30-day recoverable soft-delete / folders
                                                          or organizations to move a project into)
    Tag keys
      POST   /v3/tagKeys          body {parent,shortName,description} -> TagKey
      GET    /v3/tagKeys?parent=projects/{p}          -> {tagKeys:[...]}
      GET    /v3/tagKeys/{id}
      DELETE /v3/tagKeys/{id}
    Tag values (nested under a tag key)
      POST   /v3/tagValues        body {parent: "tagKeys/{id}", shortName, description} -> TagValue
      GET    /v3/tagValues?parent=tagKeys/{id}        -> {tagValues:[...]}
      GET    /v3/tagValues/{id}
      DELETE /v3/tagValues/{id}
    Tag bindings (attach a tag value to ANY resource by its full resource name — the
    GCP-wide tags other services, like gcp.storage.tags, attach to a bucket/instance/…)
      POST   /v3/tagBindings      body {parent: "<full resource name>", tagValue: "tagValues/{id}"} -> TagBinding
      GET    /v3/tagBindings?parent=<full resource name>  -> {tagBindings:[...]}
      DELETE /v3/tagBindings/{id}
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
import re
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
        self.tag_values: dict = {}     # name "tagValues/{id}" -> TagValue
        self.tag_bindings: dict = {}   # name "tagBindings/{id}" -> TagBinding
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


_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


def _create_project(store, body) -> RmResponse:
    project_id = str(body.get("projectId", "")).strip()
    if not _PROJECT_ID_RE.match(project_id):
        return _err(400, "projectId must be 6-30 characters: lowercase letters, digits and "
                          "hyphens, starting with a letter and not ending with a hyphen.", "INVALID_ARGUMENT")
    if project_id in store.projects:
        return _err(409, f"Project {project_id} already exists.", "ALREADY_EXISTS")
    p = _get_or_create_project(store, project_id)
    if body.get("displayName"):
        p["displayName"] = body["displayName"]
    if body.get("parent"):
        p["parent"] = body["parent"]
    return _json(200, dict(p))


def _search_projects(store, query_str) -> RmResponse:
    q = (query_str or "").strip().lower()
    out = []
    for pid, p in sorted(store.projects.items()):
        if q and q not in pid.lower() and q not in str(p.get("displayName", "")).lower():
            continue
        out.append(dict(p))
    return _json(200, {"projects": out})


def _delete_project(store, project_id) -> RmResponse:
    if project_id not in store.projects:
        return _err(404, f"Project {project_id} not found.", "NOT_FOUND")
    del store.projects[project_id]
    return _json(200, {})


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
    for vname in [n for n, v in store.tag_values.items() if v["parent"] == name]:
        _delete_tag_value(store, vname)
    del store.tag_keys[name]
    return _json(200, {})


# ── tag values (nested under a tag key) ────────────────────────────────────────
def _tagvalue_id() -> str:
    return "tagValues/" + str(int(hashlib.sha1(uuid.uuid4().bytes).hexdigest(), 16) % (10 ** 9))


def _create_tag_value(store, body) -> RmResponse:
    short = str(body.get("shortName", "")).strip()
    parent = str(body.get("parent", "")).strip()
    if not short:
        return _err(400, "shortName is required.", "INVALID_ARGUMENT")
    tk = store.tag_keys.get(parent)
    if tk is None:
        return _err(404, f"TagKey {parent} not found.", "NOT_FOUND")
    for tv in store.tag_values.values():
        if tv["parent"] == parent and tv["shortName"] == short:
            return _err(409, f"TagValue {short} already exists under {parent}.", "ALREADY_EXISTS")
    name = _tagvalue_id()
    tv = {
        "name": name,
        "parent": parent,
        "shortName": short,
        "namespacedName": f"{tk['namespacedName']}/{short}",
        "description": body.get("description", ""),
        "createTime": "2026-01-01T00:00:00Z",
        "etag": base64.b64encode(uuid.uuid4().bytes[:8]).decode(),
    }
    store.tag_values[name] = tv
    return _json(200, dict(tv))


def _list_tag_values(store, parent) -> RmResponse:
    out = [dict(tv) for tv in sorted(store.tag_values.values(), key=lambda t: t["name"]) if tv["parent"] == parent]
    return _json(200, {"tagValues": out})


def _get_tag_value(store, name) -> RmResponse:
    tv = store.tag_values.get(name)
    if tv is None:
        return _err(404, f"TagValue {name} not found.", "NOT_FOUND")
    return _json(200, dict(tv))


def _delete_tag_value(store, name) -> RmResponse:
    if name not in store.tag_values:
        return _err(404, f"TagValue {name} not found.", "NOT_FOUND")
    for bname in [n for n, b in store.tag_bindings.items() if b["tagValue"] == name]:
        del store.tag_bindings[bname]
    del store.tag_values[name]
    return _json(200, {})


# ── tag bindings (attach a tag value to any resource by its full resource name) ────────
def _create_tag_binding(store, body) -> RmResponse:
    parent = str(body.get("parent", "")).strip()
    tag_value = str(body.get("tagValue", "")).strip()
    if not parent or not tag_value:
        return _err(400, "parent and tagValue are required.", "INVALID_ARGUMENT")
    tv = store.tag_values.get(tag_value)
    if tv is None:
        return _err(404, f"TagValue {tag_value} not found.", "NOT_FOUND")
    # Real API: at most one value of a given tag KEY can be bound to a resource.
    for b in store.tag_bindings.values():
        if b["parent"] != parent:
            continue
        other = store.tag_values.get(b["tagValue"])
        if other and other["parent"] == tv["parent"]:
            return _err(409, f"A value for tag key {tv['parent']} is already bound to {parent}.", "ALREADY_EXISTS")
    bid = uuid.uuid4().hex[:16]
    name = f"tagBindings/{bid}"
    tb = {"name": name, "parent": parent, "tagValue": tag_value, "tagValueNamespacedName": tv["namespacedName"]}
    store.tag_bindings[name] = tb
    return _json(200, dict(tb))


def _list_tag_bindings(store, parent) -> RmResponse:
    out = [dict(b) for n, b in sorted(store.tag_bindings.items()) if b["parent"] == parent]
    return _json(200, {"tagBindings": out})


def _delete_tag_binding(store, name) -> RmResponse:
    if name not in store.tag_bindings:
        return _err(404, f"TagBinding {name} not found.", "NOT_FOUND")
    del store.tag_bindings[name]
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

    # ---- tag values: tagValues[/{id}] ----
    if segs and segs[0] == "tagValues":
        if len(segs) == 1:
            if method == "POST":
                return _create_tag_value(store, _body())
            if method == "GET":
                return _list_tag_values(store, str(query.get("parent", "")).strip())
            return _err(400, f"Unsupported method {method} on tagValues", "INVALID_ARGUMENT")
        name = f"tagValues/{segs[1]}"
        if method == "GET":
            return _get_tag_value(store, name)
        if method == "DELETE":
            return _delete_tag_value(store, name)
        return _err(400, f"Unsupported method {method} on tagValue", "INVALID_ARGUMENT")

    # ---- tag bindings: tagBindings[/{id}] ----
    if segs and segs[0] == "tagBindings":
        if len(segs) == 1:
            if method == "POST":
                return _create_tag_binding(store, _body())
            if method == "GET":
                return _list_tag_bindings(store, str(query.get("parent", "")).strip())
            return _err(400, f"Unsupported method {method} on tagBindings", "INVALID_ARGUMENT")
        name = f"tagBindings/{segs[1]}"
        if method == "DELETE":
            return _delete_tag_binding(store, name)
        return _err(400, f"Unsupported method {method} on tagBinding", "INVALID_ARGUMENT")

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
        # The constraint id itself may carry a slash (predefined constraints are named
        # "constraints/iam.xxx"), so the policy name is everything after ".../policies/".
        name = f"{parent}/policies/{'/'.join(segs[3:])}"
        if method == "GET":
            return _get_org_policy(store, name)
        if method == "DELETE":
            return _delete_org_policy(store, name)
        return _err(400, f"Unsupported method {method} on policy", "INVALID_ARGUMENT")

    # ---- projects collection: POST creates, GET "projects:search" lists ----
    if segs == ["projects"] and method == "POST":
        return _create_project(store, _body())
    if len(segs) == 1 and segs[0].startswith("projects:"):
        verb = segs[0].split(":", 1)[1]
        if verb == "search" and method == "GET":
            return _search_projects(store, str(query.get("query", "")).strip())
        return _err(400, f"Unsupported projects verb '{verb}'", "INVALID_ARGUMENT")

    # ---- project: projects/{id} ----
    if len(segs) == 2 and segs[0] == "projects":
        project_id = segs[1]
        if method == "GET":
            return _get_project(store, project_id)
        if method == "PATCH":
            return _patch_project(store, project_id, _body())
        if method == "DELETE":
            return _delete_project(store, project_id)
        return _err(400, f"Unsupported method {method} on project", "INVALID_ARGUMENT")

    return _err(404, f"Unknown path: {path}", "NOT_FOUND")
