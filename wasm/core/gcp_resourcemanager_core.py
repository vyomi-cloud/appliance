# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""GCP Resource Manager core — substrate-independent. Speaks a faithful slice of the
native **Cloud Resource Manager v3** (`cloudresourcemanager.googleapis.com`), **Resource
Manager Tags v3** (`tagKeys`) and **Essential Contacts v1** (`essentialcontacts.googleapis.com`)
and **Org Policy v2** (`orgpolicy.googleapis.com`) REST APIs, so the native
`google-cloud-resource-manager` / `google-cloud-resource-settings` SDKs and `gcloud` work
unchanged against it. It also hosts the org-scoped resources every Vyomi project's
single backing organization makes real: Cloud Identity Groups, Workforce Identity
Federation pools and Principal Access Boundary policies/bindings.

NO fastapi / google-cloud / socket / subprocess imports -> loads under Pyodide.

Wire shapes:
    Project
      GET    /v3/projects/{projectId}                 -> Project (parent: this project's
                                                          real backing organization, auto-created)
      PATCH  /v3/projects/{projectId}                  body {displayName?, labels?} -> Project
      POST   /v3/projects                              body {projectId,displayName?,parent?} -> Project
      GET    /v3/projects:search?query=                -> {projects:[...]}  (name/ID substring match)
      DELETE /v3/projects/{projectId}                  -> {}  (immediate delete; Vyomi has no
                                                          30-day recoverable soft-delete / folders)
    Organizations (every project belongs to the one Vyomi-wide organization)
      GET    /v3/organizations/{id}                   -> Organization
      GET    /v3/organizations[:search]                -> {organizations:[the one org]}
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
    Cloud Identity Groups (Cloud Identity Groups v1)
      POST   /v1/groups   body {groupKey:{id:email},displayName?,parent?} -> Group
      GET    /v1/groups[?parent=organizations/{id}]  -> {groups:[...]}
      GET/DELETE /v1/groups/{id}
      POST   /v1/{group}/memberships   body {preferredMemberKey:{id}}   -> Membership
      GET/DELETE /v1/{group}/memberships[/{id}]
    Workforce Identity Federation pools
      POST   /v1/locations/global/workforcePools?workforcePoolId=X  body {displayName?,parent?}
      GET    /v1/locations/global/workforcePools[?parent=]   -> {workforcePools:[...]}
      GET/DELETE /v1/locations/global/workforcePools/{id}
    Principal Access Boundary policies + bindings (ENFORCED by gcp_iam_core.py's
    testIamPermissions, which this module's `pab_bindings`/`pab_policies` back)
      POST   /v3/{org}/locations/global/principalAccessBoundaryPolicies?principalAccessBoundaryPolicyId=X
             body {displayName?,details:{rules:[{resources:[...]}]}}
      GET    /v3/{org}/locations/global/principalAccessBoundaryPolicies[/{id}]
      DELETE /v3/{org}/locations/global/principalAccessBoundaryPolicies/{id}
      POST   /v3/{org}/locations/global/policyBindings?policyBindingId=X
             body {policy,target:{principal}}
      GET/DELETE /v3/{org}/locations/global/policyBindings[/{id}]

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
        self.contacts: dict = {}       # "projects/{p}/contacts/{id}" -> Contact
        self.org_policies: dict = {}   # policy name -> Policy
        self.organizations: dict = {}  # "organizations/{id}" -> Organization
        self.groups: dict = {}         # "groups/{id}" -> Group (Cloud Identity)
        self.group_memberships: dict = {}  # "groups/{id}/memberships/{id}" -> Membership
        self.workforce_pools: dict = {}    # "locations/global/workforcePools/{id}" -> WorkforcePool
        self.pab_policies: dict = {}       # PAB policy name -> PrincipalAccessBoundaryPolicy
        self.pab_bindings: dict = {}       # PolicyBinding name -> PolicyBinding


def _json(status: int, obj: dict) -> RmResponse:
    return RmResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, message: str, gstatus: str) -> RmResponse:
    body = {"error": {"code": status, "message": message, "status": gstatus}}
    return RmResponse(status=status, body=json.dumps(body).encode())


def _project_number(project_id: str) -> str:
    # Stable 12-digit numeric project number derived from the project id (GCP's are
    # globally-unique random numbers; determinism here just keeps re-reads stable).
    return str(int(hashlib.sha1(project_id.encode()).hexdigest(), 16) % (10 ** 12)).zfill(12)


# ── organizations ─────────────────────────────────────────────────────────────
# Vyomi's GCP lens is single-customer: every project it hosts belongs to the SAME
# backing organization (a Google Workspace / Cloud Identity account normally owns
# every project under it, same as this). This is what lets the org-scoped IAM & Admin
# pages (Groups, Workforce Identity Federation, Principal Access Boundary, Identity &
# Organization) be real instead of "requires an organization" — the organization
# always exists, a project's `parent` always points at it unless the caller supplies
# a different one explicitly at creation.
_DEFAULT_ORG_ID = "908614232548"


def get_or_create_default_org(store: ResourceManagerStore) -> dict:
    name = f"organizations/{_DEFAULT_ORG_ID}"
    org = store.organizations.get(name)
    if org is None:
        customer_id = "C" + hashlib.sha1(name.encode()).hexdigest()[:8].upper()
        org = {
            "name": name,
            "displayName": "vyomi.example.com",
            "directoryCustomerId": customer_id,
            "state": "ACTIVE",
            "createTime": "2026-01-01T00:00:00Z",
            "owner": {"directoryCustomerId": customer_id},
        }
        store.organizations[name] = org
    return org


def _get_organization(store, name) -> RmResponse:
    org = store.organizations.get(name)
    if org is None and name == f"organizations/{_DEFAULT_ORG_ID}":
        org = get_or_create_default_org(store)
    if org is None:
        return _err(404, f"Organization {name} not found.", "NOT_FOUND")
    return _json(200, dict(org))


def _search_organizations(store) -> RmResponse:
    return _json(200, {"organizations": [dict(get_or_create_default_org(store))]})


# ── project ───────────────────────────────────────────────────────────────────
def _get_or_create_project(store: ResourceManagerStore, project_id: str) -> dict:
    p = store.projects.get(project_id)
    if p is None:
        org = get_or_create_default_org(store)
        p = {
            "name": f"projects/{_project_number(project_id)}",
            "projectId": project_id,
            "displayName": project_id,
            "state": "ACTIVE",
            "createTime": "2026-01-01T00:00:00Z",
            "etag": base64.b64encode(uuid.uuid4().bytes[:8]).decode(),
            "labels": {},
            "parent": {"type": "organization", "id": org["name"].split("/", 1)[1]},
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


# ── Cloud Identity Groups (org-scoped; console "Groups" page) ────────────────
def _group_id() -> str:
    return "groups/" + str(int(hashlib.sha1(uuid.uuid4().bytes).hexdigest(), 16) % (10 ** 12))


def _create_group(store, body) -> RmResponse:
    key = (body.get("groupKey") or {}).get("id", "").strip()
    if not key or "@" not in key:
        return _err(400, "groupKey.id must be a valid group email.", "INVALID_ARGUMENT")
    for g in store.groups.values():
        if g["groupKey"]["id"] == key:
            return _err(409, f"Group {key} already exists.", "ALREADY_EXISTS")
    name = _group_id()
    get_or_create_default_org(store)
    g = {
        "name": name,
        "groupKey": {"id": key},
        "parent": body.get("parent") or f"organizations/{_DEFAULT_ORG_ID}",
        "displayName": body.get("displayName", key.split("@")[0]),
        "description": body.get("description", ""),
        "createTime": "2026-01-01T00:00:00Z",
        "updateTime": "2026-01-01T00:00:00Z",
        "labels": body.get("labels") or {"cloudidentity.googleapis.com/groups.discussion_forum": ""},
    }
    store.groups[name] = g
    return _json(200, dict(g))


def _list_groups(store, parent) -> RmResponse:
    out = [dict(g) for n, g in sorted(store.groups.items()) if not parent or g["parent"] == parent]
    return _json(200, {"groups": out})


def _get_group(store, name) -> RmResponse:
    g = store.groups.get(name)
    if g is None:
        return _err(404, f"Group {name} not found.", "NOT_FOUND")
    return _json(200, dict(g))


def _delete_group(store, name) -> RmResponse:
    if name not in store.groups:
        return _err(404, f"Group {name} not found.", "NOT_FOUND")
    del store.groups[name]
    for mname in [m for m in store.group_memberships if m.startswith(name + "/memberships/")]:
        del store.group_memberships[mname]
    return _json(200, {})


def _create_membership(store, group_name, body) -> RmResponse:
    if group_name not in store.groups:
        return _err(404, f"Group {group_name} not found.", "NOT_FOUND")
    key = (body.get("preferredMemberKey") or {}).get("id", "").strip()
    if not key:
        return _err(400, "preferredMemberKey.id is required.", "INVALID_ARGUMENT")
    for n, m in store.group_memberships.items():
        if n.startswith(group_name + "/memberships/") and m["preferredMemberKey"]["id"] == key:
            return _err(409, f"{key} is already a member of {group_name}.", "ALREADY_EXISTS")
    mid = str(int(hashlib.sha1(uuid.uuid4().bytes).hexdigest(), 16) % (10 ** 12))
    name = f"{group_name}/memberships/{mid}"
    m = {
        "name": name,
        "preferredMemberKey": {"id": key},
        "roles": body.get("roles") or [{"name": "MEMBER"}],
        "createTime": "2026-01-01T00:00:00Z",
    }
    store.group_memberships[name] = m
    return _json(200, dict(m))


def _list_memberships(store, group_name) -> RmResponse:
    prefix = group_name + "/memberships/"
    out = [dict(m) for n, m in sorted(store.group_memberships.items()) if n.startswith(prefix)]
    return _json(200, {"memberships": out})


def _delete_membership(store, name) -> RmResponse:
    if name not in store.group_memberships:
        return _err(404, f"Membership {name} not found.", "NOT_FOUND")
    del store.group_memberships[name]
    return _json(200, {})


# ── Workforce Identity Federation pools (org-scoped) ─────────────────────────
def _create_workforce_pool(store, pool_id, body) -> RmResponse:
    if not pool_id:
        return _err(400, "workforcePoolId is required.", "INVALID_ARGUMENT")
    name = f"locations/global/workforcePools/{pool_id}"
    if name in store.workforce_pools:
        return _err(409, f"Workforce pool {pool_id} already exists.", "ALREADY_EXISTS")
    get_or_create_default_org(store)
    wp = {
        "name": name,
        "parent": body.get("parent") or f"organizations/{_DEFAULT_ORG_ID}",
        "displayName": body.get("displayName", pool_id),
        "description": body.get("description", ""),
        "state": "ACTIVE",
        "disabled": False,
        "sessionDuration": body.get("sessionDuration", "3600s"),
    }
    store.workforce_pools[name] = wp
    return _json(200, dict(wp))


def _list_workforce_pools(store, parent) -> RmResponse:
    out = [dict(wp) for n, wp in sorted(store.workforce_pools.items()) if not parent or wp["parent"] == parent]
    return _json(200, {"workforcePools": out})


def _get_workforce_pool(store, name) -> RmResponse:
    wp = store.workforce_pools.get(name)
    if wp is None:
        return _err(404, f"Workforce pool {name} not found.", "NOT_FOUND")
    return _json(200, dict(wp))


def _delete_workforce_pool(store, name) -> RmResponse:
    if name not in store.workforce_pools:
        return _err(404, f"Workforce pool {name} not found.", "NOT_FOUND")
    del store.workforce_pools[name]
    return _json(200, {})


# ── Principal Access Boundary policies + bindings (org-scoped, ENFORCED) ────
# A PAB binding ties a principal to a policy whose rules enumerate the ONLY
# resources that principal may be granted access to; core/gcp_iam_core.py's
# testIamPermissions consults store.pab_policies/pab_bindings (via the rm_store it
# already receives) on every call, so this narrows real access decisions — it is
# not stored-but-unevaluated config.
def _create_pab_policy(store, parent, policy_id, body) -> RmResponse:
    if not policy_id:
        return _err(400, "principalAccessBoundaryPolicyId is required.", "INVALID_ARGUMENT")
    name = f"{parent}/locations/global/principalAccessBoundaryPolicies/{policy_id}"
    if name in store.pab_policies:
        return _err(409, f"Policy {policy_id} already exists.", "ALREADY_EXISTS")
    pol = {
        "name": name,
        "displayName": body.get("displayName", policy_id),
        "details": body.get("details") or {"rules": []},
        "etag": base64.b64encode(uuid.uuid4().bytes[:8]).decode(),
        "createTime": "2026-01-01T00:00:00Z",
    }
    store.pab_policies[name] = pol
    return _json(200, dict(pol))


def _list_pab_policies(store, parent) -> RmResponse:
    prefix = f"{parent}/locations/global/principalAccessBoundaryPolicies/"
    out = [dict(p) for n, p in sorted(store.pab_policies.items()) if n.startswith(prefix)]
    return _json(200, {"principalAccessBoundaryPolicies": out})


def _get_pab_policy(store, name) -> RmResponse:
    pol = store.pab_policies.get(name)
    if pol is None:
        return _err(404, f"Policy {name} not found.", "NOT_FOUND")
    return _json(200, dict(pol))


def _delete_pab_policy(store, name) -> RmResponse:
    if name not in store.pab_policies:
        return _err(404, f"Policy {name} not found.", "NOT_FOUND")
    del store.pab_policies[name]
    for bname in [b for b, bind in store.pab_bindings.items() if bind.get("policy") == name]:
        del store.pab_bindings[bname]
    return _json(200, {})


def _create_pab_binding(store, parent, binding_id, body) -> RmResponse:
    if not binding_id:
        return _err(400, "policyBindingId is required.", "INVALID_ARGUMENT")
    policy = str(body.get("policy", "")).strip()
    if policy not in store.pab_policies:
        return _err(400, f"policy {policy} does not exist.", "INVALID_ARGUMENT")
    target = body.get("target") or {}
    if not target.get("principal"):
        return _err(400, "target.principal is required.", "INVALID_ARGUMENT")
    name = f"{parent}/locations/global/policyBindings/{binding_id}"
    if name in store.pab_bindings:
        return _err(409, f"Policy binding {binding_id} already exists.", "ALREADY_EXISTS")
    b = {
        "name": name,
        "policy": policy,
        "policyKind": "PRINCIPAL_ACCESS_BOUNDARY",
        "target": target,
        "createTime": "2026-01-01T00:00:00Z",
    }
    store.pab_bindings[name] = b
    return _json(200, dict(b))


def _list_pab_bindings(store, parent) -> RmResponse:
    prefix = f"{parent}/locations/global/policyBindings/"
    out = [dict(b) for n, b in sorted(store.pab_bindings.items()) if n.startswith(prefix)]
    return _json(200, {"policyBindings": out})


def _delete_pab_binding(store, name) -> RmResponse:
    if name not in store.pab_bindings:
        return _err(404, f"Policy binding {name} not found.", "NOT_FOUND")
    del store.pab_bindings[name]
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
        # The constraint id itself may carry a slash (predefined constraints are named
        # "constraints/iam.xxx"), so the policy name is everything after ".../policies/".
        name = f"{parent}/policies/{'/'.join(segs[3:])}"
        if method == "GET":
            return _get_org_policy(store, name)
        if method == "DELETE":
            return _delete_org_policy(store, name)
        return _err(400, f"Unsupported method {method} on policy", "INVALID_ARGUMENT")

    # ---- organizations: organizations[/{id}|:search] ----
    if segs and segs[0] == "organizations":
        if len(segs) == 1 and method == "GET":
            return _search_organizations(store)
        if len(segs) >= 2 and ":" in segs[1]:
            org_id, verb = segs[1].split(":", 1)
            if verb == "search" and method == "GET":
                return _search_organizations(store)
            return _err(400, f"Unsupported organizations verb '{verb}'", "INVALID_ARGUMENT")
        if len(segs) == 2:
            if method == "GET":
                return _get_organization(store, f"organizations/{segs[1]}")
            return _err(400, f"Unsupported method {method} on organization", "INVALID_ARGUMENT")
        org_name = f"organizations/{segs[1]}"
        # ---- Principal Access Boundary: organizations/{org}/locations/global/{principalAccessBoundaryPolicies|policyBindings}[/{id}] ----
        if len(segs) >= 5 and segs[2] == "locations" and segs[3] == "global" and segs[4] == "principalAccessBoundaryPolicies":
            if len(segs) == 5:
                if method == "POST":
                    return _create_pab_policy(store, org_name, str(query.get("principalAccessBoundaryPolicyId", "")).strip(), _body())
                if method == "GET":
                    return _list_pab_policies(store, org_name)
                return _err(400, f"Unsupported method {method} on principalAccessBoundaryPolicies", "INVALID_ARGUMENT")
            name = f"{org_name}/locations/global/principalAccessBoundaryPolicies/{segs[5]}"
            if method == "GET":
                return _get_pab_policy(store, name)
            if method == "DELETE":
                return _delete_pab_policy(store, name)
            return _err(400, f"Unsupported method {method} on principalAccessBoundaryPolicy", "INVALID_ARGUMENT")
        if len(segs) >= 5 and segs[2] == "locations" and segs[3] == "global" and segs[4] == "policyBindings":
            if len(segs) == 5:
                if method == "POST":
                    return _create_pab_binding(store, org_name, str(query.get("policyBindingId", "")).strip(), _body())
                if method == "GET":
                    return _list_pab_bindings(store, org_name)
                return _err(400, f"Unsupported method {method} on policyBindings", "INVALID_ARGUMENT")
            name = f"{org_name}/locations/global/policyBindings/{segs[5]}"
            if method == "DELETE":
                return _delete_pab_binding(store, name)
            return _err(400, f"Unsupported method {method} on policyBinding", "INVALID_ARGUMENT")
        return _err(404, f"Unknown path: {path}", "NOT_FOUND")

    # ---- Cloud Identity groups: groups[/{id}[/memberships[/{id}]]] ----
    if segs and segs[0] == "groups":
        if len(segs) == 1:
            if method == "POST":
                return _create_group(store, _body())
            if method == "GET":
                return _list_groups(store, str(query.get("parent", "")).strip())
            return _err(400, f"Unsupported method {method} on groups", "INVALID_ARGUMENT")
        group_name = f"groups/{segs[1]}"
        if len(segs) == 2:
            if method == "GET":
                return _get_group(store, group_name)
            if method == "DELETE":
                return _delete_group(store, group_name)
            return _err(400, f"Unsupported method {method} on group", "INVALID_ARGUMENT")
        if len(segs) >= 3 and segs[2] == "memberships":
            if len(segs) == 3:
                if method == "POST":
                    return _create_membership(store, group_name, _body())
                if method == "GET":
                    return _list_memberships(store, group_name)
                return _err(400, f"Unsupported method {method} on memberships", "INVALID_ARGUMENT")
            if method == "DELETE":
                return _delete_membership(store, f"{group_name}/memberships/{segs[3]}")
            return _err(400, f"Unsupported method {method} on membership", "INVALID_ARGUMENT")
        return _err(404, f"Unknown path: {path}", "NOT_FOUND")

    # ---- Workforce Identity Federation pools: locations/global/workforcePools[/{id}] ----
    if len(segs) >= 3 and segs[0] == "locations" and segs[1] == "global" and segs[2] == "workforcePools":
        if len(segs) == 3:
            if method == "POST":
                return _create_workforce_pool(store, str(query.get("workforcePoolId", "")).strip(), _body())
            if method == "GET":
                return _list_workforce_pools(store, str(query.get("parent", "")).strip())
            return _err(400, f"Unsupported method {method} on workforcePools", "INVALID_ARGUMENT")
        name = f"locations/global/workforcePools/{segs[3]}"
        if method == "GET":
            return _get_workforce_pool(store, name)
        if method == "DELETE":
            return _delete_workforce_pool(store, name)
        return _err(400, f"Unsupported method {method} on workforcePool", "INVALID_ARGUMENT")

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
