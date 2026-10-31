# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""GCP Cloud IAM core — substrate-independent, the GCP analogue of
core/iam_core.py (AWS IAM). Speaks the native **Google Cloud IAM REST API**
(`iam.googleapis.com` service accounts + `cloudresourcemanager`-style
`:getIamPolicy` / `:setIamPolicy` / `:testIamPermissions` on any resource) so the
native `google-cloud-iam` / `google-cloud-resource-manager` clients (and
`gcloud`) work unchanged against it.

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide.
State (service accounts + resource IAM policies) is held in memory in its OWN
namespace (this is the GCP cloud; it does not share the AWS IamStore records).
It DOES reuse the InMemoryIamStore seam from core/iam_store.py as its container so
the same in-memory substrate backs every cloud, keeping the persistence hook in
one place — the GCP records live under dedicated `sa_by_email` / `iam_policies`
dicts on the store.

The star of this entry is the DECISION path: `:testIamPermissions` does NOT echo
the requested permissions back — it EVALUATES GCP's binding model. A permission
is granted iff the caller's member appears in a binding whose role grants that
permission (roles resolved through a small role→permissions map, mirroring the
real predefined-role expansion). This is the GCP analogue of AWS
SimulatePrincipalPolicy: the *decision* is what must conform; the store behind it
is our private pick.

Wire shapes (GCP IAM REST):
    Service accounts
      POST   projects/{p}/serviceAccounts   body {"accountId","serviceAccount":{"displayName"}}
             -> {"name","email","uniqueId","projectId","displayName", ...}
      GET    projects/{p}/serviceAccounts/{email}
      GET    projects/{p}/serviceAccounts                     -> {"accounts":[...]}
      DELETE projects/{p}/serviceAccounts/{email}             -> {}
    Resource IAM policy
      POST   {resource}:getIamPolicy      -> {"version","bindings":[...],"etag"}
      POST   {resource}:setIamPolicy      body {"policy":{"bindings":[...]}}
      POST   {resource}:testIamPermissions  body {"permissions":[...]}
             -> {"permissions":[granted...]}   (EVALUATED, not echoed)

Errors use the native GCP shape {"error":{"code","message","status"}}.
"""
from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import unquote

MAX_ACTIVITY = 200

from core.iam_store import IamStore, InMemoryIamStore

# ── predefined role → permissions map ──────────────────────────────────────
# A small, faithful slice of GCP's predefined-role expansion. testIamPermissions
# resolves a member's bound roles through this map to decide grants. "*" is the
# owner/admin wildcard (grants everything, like roles/owner).
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "roles/owner": {"*"},
    "roles/editor": {
        "storage.buckets.create", "storage.buckets.delete", "storage.buckets.get",
        "storage.buckets.list", "storage.objects.create", "storage.objects.delete",
        "storage.objects.get", "storage.objects.list", "storage.objects.update",
    },
    "roles/viewer": {
        "storage.buckets.get", "storage.buckets.list",
        "storage.objects.get", "storage.objects.list",
        "resourcemanager.projects.get",
    },
    "roles/storage.admin": {
        "storage.buckets.create", "storage.buckets.delete", "storage.buckets.get",
        "storage.buckets.list", "storage.buckets.update", "storage.buckets.getIamPolicy",
        "storage.buckets.setIamPolicy", "storage.objects.create", "storage.objects.delete",
        "storage.objects.get", "storage.objects.list", "storage.objects.update",
    },
    "roles/storage.objectAdmin": {
        "storage.objects.create", "storage.objects.delete",
        "storage.objects.get", "storage.objects.list", "storage.objects.update",
    },
    "roles/storage.objectViewer": {
        "storage.objects.get", "storage.objects.list",
    },
    "roles/iam.serviceAccountAdmin": {
        "iam.serviceAccounts.create", "iam.serviceAccounts.delete",
        "iam.serviceAccounts.get", "iam.serviceAccounts.list",
        "iam.serviceAccounts.getIamPolicy", "iam.serviceAccounts.setIamPolicy",
    },
    "roles/iam.serviceAccountUser": {
        "iam.serviceAccounts.actAs", "iam.serviceAccounts.get",
    },
}

# ── predefined-role catalog (console "Roles > Predefined" tab) ─────────────
# {name: (title, service_display_name)} — a representative slice of GCP's
# predefined-role catalog (thousands of real roles; this is reference data,
# not user-created, so a fixed list is a faithful rendering of this tab).
PREDEFINED_ROLE_CATALOG: dict[str, tuple[str, str]] = {
    "roles/owner": ("Owner", "Basic"),
    "roles/editor": ("Editor", "Basic"),
    "roles/viewer": ("Viewer", "Basic"),
    "roles/storage.admin": ("Storage Admin", "Cloud Storage"),
    "roles/storage.objectAdmin": ("Storage Object Admin", "Cloud Storage"),
    "roles/storage.objectViewer": ("Storage Object Viewer", "Cloud Storage"),
    "roles/iam.serviceAccountAdmin": ("Service Account Admin", "Identity and Access Management (IAM)"),
    "roles/iam.serviceAccountUser": ("Service Account User", "Identity and Access Management (IAM)"),
    "roles/iam.securityAdmin": ("Security Admin", "Identity and Access Management (IAM)"),
    "roles/resourcemanager.projectIamAdmin": ("Project IAM Admin", "Resource Manager"),
    "roles/pubsub.admin": ("Pub/Sub Admin", "Cloud Pub/Sub"),
    "roles/pubsub.publisher": ("Pub/Sub Publisher", "Cloud Pub/Sub"),
    "roles/cloudsql.admin": ("Cloud SQL Admin", "Cloud SQL"),
    "roles/compute.admin": ("Compute Admin", "Compute Engine"),
    "roles/logging.viewer": ("Logs Viewer", "Cloud Logging"),
    "roles/monitoring.viewer": ("Monitoring Viewer", "Cloud Monitoring"),
}


def list_predefined_roles() -> list[dict]:
    return [{"name": n, "title": t, "service": svc, "stage": "GA"}
            for n, (t, svc) in sorted(PREDEFINED_ROLE_CATALOG.items())]


@dataclass
class GcpIamResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


# ── primitives ─────────────────────────────────────────────────────────────
def _json(status: int, obj: dict) -> GcpIamResponse:
    return GcpIamResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, message: str, gstatus: str) -> GcpIamResponse:
    body = {"error": {"code": status, "message": message, "status": gstatus}}
    return GcpIamResponse(status=status, body=json.dumps(body).encode())


def _unique_id() -> str:
    # GCP service-account uniqueId is a 21-digit numeric string.
    n = uuid.uuid4().int % (10 ** 21)
    return str(n).zfill(21)


def _etag() -> str:
    return base64.b64encode(uuid.uuid4().bytes[:8]).decode()


# ── store namespace ─────────────────────────────────────────────────────────
def _sa_ns(store: IamStore) -> dict:
    """Service accounts, keyed by email, in the GCP namespace on the store."""
    ns = getattr(store, "gcp_service_accounts", None)
    if ns is None:
        ns = {}
        store.gcp_service_accounts = ns  # type: ignore[attr-defined]
    return ns


def _policy_ns(store: IamStore) -> dict:
    """Resource IAM policies, keyed by resource path, in the GCP namespace."""
    ns = getattr(store, "gcp_iam_policies", None)
    if ns is None:
        ns = {}
        store.gcp_iam_policies = ns  # type: ignore[attr-defined]
    return ns


def _keys_ns(store: IamStore) -> dict:
    """Service account keys, keyed by SA email -> {keyId: record}."""
    ns = getattr(store, "gcp_sa_keys", None)
    if ns is None:
        ns = {}
        store.gcp_sa_keys = ns  # type: ignore[attr-defined]
    return ns


def _roles_ns(store: IamStore) -> dict:
    """Custom IAM roles, keyed by 'projects/{p}/roles/{roleId}'."""
    ns = getattr(store, "gcp_custom_roles", None)
    if ns is None:
        ns = {}
        store.gcp_custom_roles = ns  # type: ignore[attr-defined]
    return ns


def _deny_ns(store: IamStore) -> dict:
    """Deny policies, keyed by attachmentPoint -> {policyId: record}."""
    ns = getattr(store, "gcp_deny_policies", None)
    if ns is None:
        ns = {}
        store.gcp_deny_policies = ns  # type: ignore[attr-defined]
    return ns


def _pools_ns(store: IamStore) -> dict:
    """Workload identity pools, keyed by 'projects/{p}/locations/global/workloadIdentityPools/{id}'."""
    ns = getattr(store, "gcp_wi_pools", None)
    if ns is None:
        ns = {}
        store.gcp_wi_pools = ns  # type: ignore[attr-defined]
    return ns


def _activity_ns(store: IamStore) -> list:
    """Applied-policy-change log (console 'Recommendations history' tab), keyed by resource."""
    ns = getattr(store, "gcp_policy_activity", None)
    if ns is None:
        ns = []
        store.gcp_policy_activity = ns  # type: ignore[attr-defined]
    return ns


def _record_activity(store: IamStore, resource: str, old_bindings: list, new_bindings: list) -> None:
    def _pairs(bindings):
        return {(b.get("role", ""), m) for b in bindings or [] for m in b.get("members", [])}
    added, removed = _pairs(new_bindings) - _pairs(old_bindings), _pairs(old_bindings) - _pairs(new_bindings)
    if not added and not removed:
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log = _activity_ns(store)
    for role, member in sorted(added):
        log.append({"id": uuid.uuid4().hex[:12], "resource": resource, "action": "GRANT", "role": role, "member": member, "time": now})
    for role, member in sorted(removed):
        log.append({"id": uuid.uuid4().hex[:12], "resource": resource, "action": "REVOKE", "role": role, "member": member, "time": now})
    del log[:max(0, len(log) - MAX_ACTIVITY)]


def _list_activity(store: IamStore, resource: str) -> GcpIamResponse:
    entries = [dict(e) for e in _activity_ns(store) if e["resource"] == resource]
    entries.reverse()  # most recent first
    return _json(200, {"activity": entries})


def _record_event(store: IamStore, resource: str, action: str, detail: str = "") -> None:
    """Record a non-binding admin-activity event (key create/delete, disable/enable,
    display-name update) against `resource` — same log the per-service-account 'Logs'
    tab reads (console ServiceAccountDetail), keyed the same way as _record_activity."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log = _activity_ns(store)
    log.append({"id": uuid.uuid4().hex[:12], "resource": resource, "action": action, "role": "", "member": detail, "time": now})
    del log[:max(0, len(log) - MAX_ACTIVITY)]


def _sa_email(account_id: str, project: str) -> str:
    return f"{account_id}@{project}.iam.gserviceaccount.com"


def _sa_view(sa: dict) -> dict:
    return {
        "name": sa["name"],
        "projectId": sa["projectId"],
        "uniqueId": sa["uniqueId"],
        "email": sa["email"],
        "displayName": sa.get("displayName", ""),
        "description": sa.get("description", ""),
        "etag": sa.get("etag", "BwXXX"),
        "oauth2ClientId": sa["uniqueId"],
        "disabled": sa.get("disabled", False),
    }


# ── service-account operations ──────────────────────────────────────────────
def _create_service_account(store, project, body) -> GcpIamResponse:
    account_id = str(body.get("accountId", "")).strip()
    if not account_id:
        return _err(400, "accountId is required.", "INVALID_ARGUMENT")
    email = _sa_email(account_id, project)
    sas = _sa_ns(store)
    if email in sas:
        return _err(409, f"Service account {email} already exists.", "ALREADY_EXISTS")
    spec = body.get("serviceAccount") or {}
    sa = {
        "name": f"projects/{project}/serviceAccounts/{email}",
        "projectId": project,
        "uniqueId": _unique_id(),
        "email": email,
        "accountId": account_id,
        "displayName": spec.get("displayName", ""),
        "description": spec.get("description", ""),
        "etag": _etag(),
        "disabled": False,
    }
    sas[email] = sa
    store.persist()
    return _json(200, _sa_view(sa))


def _get_service_account(store, project, ident) -> GcpIamResponse:
    sas = _sa_ns(store)
    email = ident if "@" in ident else _sa_email(ident, project)
    sa = sas.get(email)
    if sa is None:
        return _err(404, f"Unknown service account: {ident}", "NOT_FOUND")
    return _json(200, _sa_view(sa))


def _list_service_accounts(store, project) -> GcpIamResponse:
    sas = _sa_ns(store)
    accounts = [_sa_view(sa) for email, sa in sorted(sas.items())
                if sa["projectId"] == project]
    return _json(200, {"accounts": accounts})


def _delete_service_account(store, project, ident) -> GcpIamResponse:
    sas = _sa_ns(store)
    email = ident if "@" in ident else _sa_email(ident, project)
    if email not in sas:
        return _err(404, f"Unknown service account: {ident}", "NOT_FOUND")
    del sas[email]
    store.persist()
    return _json(200, {})


def _patch_service_account(store, project, ident, body) -> GcpIamResponse:
    sas = _sa_ns(store)
    email = ident if "@" in ident else _sa_email(ident, project)
    sa = sas.get(email)
    if sa is None:
        return _err(404, f"Unknown service account: {ident}", "NOT_FOUND")
    # serviceAccounts.patch takes a "serviceAccount" resource body (updateMask implied by
    # which fields are present) — mirrors the real partial-update contract.
    spec = body.get("serviceAccount") or body
    for field in ("displayName", "description"):
        if field in spec:
            sa[field] = spec[field]
    sa["etag"] = _etag()
    store.persist()
    _record_event(store, sa["name"], "UPDATE")
    return _json(200, _sa_view(sa))


def _set_service_account_disabled(store, project, ident, disabled) -> GcpIamResponse:
    sas = _sa_ns(store)
    email = ident if "@" in ident else _sa_email(ident, project)
    sa = sas.get(email)
    if sa is None:
        return _err(404, f"Unknown service account: {ident}", "NOT_FOUND")
    sa["disabled"] = disabled
    store.persist()
    _record_event(store, sa["name"], "DISABLE" if disabled else "ENABLE")
    return _json(200, {})


# ── resource IAM policy operations ──────────────────────────────────────────
def _get_iam_policy(store, resource) -> GcpIamResponse:
    policies = _policy_ns(store)
    pol = policies.get(resource)
    if pol is None:
        # GCP returns an empty policy (version 1, no bindings) for a resource
        # that has never had a policy set.
        return _json(200, {"version": 1, "bindings": [], "etag": _etag()})
    out = {
        "version": pol.get("version", 1),
        "bindings": [dict(b) for b in pol.get("bindings", [])],
        "etag": pol.get("etag", _etag()),
    }
    if pol.get("auditConfigs"):
        out["auditConfigs"] = [dict(a) for a in pol["auditConfigs"]]
    return _json(200, out)


def _set_iam_policy(store, resource, body) -> GcpIamResponse:
    policy = body.get("policy") or {}
    bindings = policy.get("bindings") or []
    old = _policy_ns(store).get(resource) or {}
    _record_activity(store, resource, old.get("bindings") or [], bindings)
    # Normalise bindings to {"role","members":[...]} preserving any condition.
    norm = []
    for b in bindings:
        entry = {"role": b.get("role", ""), "members": list(b.get("members", []))}
        if b.get("condition"):
            entry["condition"] = b["condition"]
        norm.append(entry)
    stored = {
        "version": policy.get("version", 1),
        "bindings": norm,
        "etag": policy.get("etag") or _etag(),
    }
    # auditConfigs (Data Access audit logging config) — stored and returned
    # verbatim (config_only: Vyomi does not gate calls on it), same object
    # shape as real IAM Policy.auditConfigs.
    if "auditConfigs" in policy:
        stored["auditConfigs"] = [
            {"service": a.get("service", ""),
             "auditLogConfigs": [dict(c) for c in a.get("auditLogConfigs", [])]}
            for a in policy.get("auditConfigs") or []
        ]
    elif resource in _policy_ns(store) and _policy_ns(store)[resource].get("auditConfigs"):
        stored["auditConfigs"] = _policy_ns(store)[resource]["auditConfigs"]
    _policy_ns(store)[resource] = stored
    store.persist()
    out = {
        "version": stored["version"],
        "bindings": [dict(b) for b in stored["bindings"]],
        "etag": stored["etag"],
    }
    if stored.get("auditConfigs"):
        out["auditConfigs"] = [dict(a) for a in stored["auditConfigs"]]
    return _json(200, out)


def grant_member(store, resource: str, role: str, member: str) -> None:
    """Merge `member` into `role`'s bindings on `resource`. Lets Privileged Access
    Manager grant activation (core/gcp_pam_core.py) make a time-boxed grant a real
    policy change — logged the same way a console-driven setIamPolicy is."""
    pol = _policy_ns(store).get(resource) or {"version": 1, "bindings": []}
    old = [dict(b) for b in pol.get("bindings", [])]
    bindings = [dict(b) for b in old]
    for b in bindings:
        if b.get("role") == role:
            if member not in b.get("members", []):
                b["members"] = [*b.get("members", []), member]
            break
    else:
        bindings.append({"role": role, "members": [member]})
    _record_activity(store, resource, old, bindings)
    stored = dict(pol)
    stored["bindings"], stored["etag"] = bindings, _etag()
    _policy_ns(store)[resource] = stored
    store.persist()


def revoke_member(store, resource: str, role: str, member: str) -> None:
    """Undo grant_member: drop `member` from `role`'s bindings on `resource`."""
    pol = _policy_ns(store).get(resource)
    if not pol:
        return
    old = [dict(b) for b in pol.get("bindings", [])]
    bindings = []
    for b in old:
        if b.get("role") == role:
            members = [m for m in b.get("members", []) if m != member]
            if members:
                bindings.append({**b, "members": members})
        else:
            bindings.append(b)
    _record_activity(store, resource, old, bindings)
    stored = dict(pol)
    stored["bindings"], stored["etag"] = bindings, _etag()
    _policy_ns(store)[resource] = stored
    store.persist()


# ── custom IAM roles ─────────────────────────────────────────────────────────
def _role_view(role: dict) -> dict:
    return {k: v for k, v in role.items() if k != "_project"}


def _create_role(store, project, role_id, body) -> GcpIamResponse:
    if not role_id:
        return _err(400, "roleId is required.", "INVALID_ARGUMENT")
    roles = _roles_ns(store)
    name = f"projects/{project}/roles/{role_id}"
    if name in roles and not roles[name].get("deleted"):
        return _err(409, f"Role {name} already exists.", "ALREADY_EXISTS")
    spec = body.get("role") or {}
    role = {
        "name": name,
        "title": spec.get("title", role_id),
        "description": spec.get("description", ""),
        "includedPermissions": list(spec.get("includedPermissions", [])),
        "stage": spec.get("stage", "GA"),
        "etag": _etag(),
        "deleted": False,
        "_project": project,
    }
    roles[name] = role
    store.persist()
    return _json(200, _role_view(role))


def _get_role(store, name) -> GcpIamResponse:
    role = _roles_ns(store).get(name)
    if role is None:
        return _err(404, f"Role {name} not found.", "NOT_FOUND")
    return _json(200, _role_view(role))


def _list_roles(store, project) -> GcpIamResponse:
    roles = _roles_ns(store)
    out = [_role_view(r) for n, r in sorted(roles.items())
           if r.get("_project") == project and not r.get("deleted")]
    return _json(200, {"roles": out})


def _patch_role(store, name, body) -> GcpIamResponse:
    roles = _roles_ns(store)
    role = roles.get(name)
    if role is None:
        return _err(404, f"Role {name} not found.", "NOT_FOUND")
    spec = body.get("role") or body
    for field, key in (("title", "title"), ("description", "description"),
                       ("includedPermissions", "includedPermissions"), ("stage", "stage")):
        if key in spec:
            role[field] = spec[key]
    role["etag"] = _etag()
    store.persist()
    return _json(200, _role_view(role))


def _delete_role(store, name) -> GcpIamResponse:
    roles = _roles_ns(store)
    role = roles.get(name)
    if role is None:
        return _err(404, f"Role {name} not found.", "NOT_FOUND")
    role["deleted"] = True  # GCP soft-deletes custom roles (undeletable for 7 days)
    store.persist()
    return _json(200, _role_view(role))


# ── service account keys ────────────────────────────────────────────────────
def _key_id() -> str:
    return uuid.uuid4().hex


def _key_view(k: dict) -> dict:
    return {kk: vv for kk, vv in k.items() if kk != "_email"}


def _create_key(store, project, email, body) -> GcpIamResponse:
    keys = _keys_ns(store).setdefault(email, {})
    kid = _key_id()
    now = _etag()  # not a real timestamp source available here; validAfterTime below uses a stable marker
    key = {
        "name": f"projects/{project}/serviceAccounts/{email}/keys/{kid}",
        "privateKeyType": body.get("privateKeyType", "TYPE_GOOGLE_CREDENTIALS_FILE"),
        "keyAlgorithm": body.get("keyAlgorithm", "KEY_ALG_RSA_2048"),
        "privateKeyData": base64.b64encode(json.dumps({
            "type": "service_account", "project_id": project, "private_key_id": kid,
            "client_email": email,
        }).encode()).decode(),
        "publicKeyData": base64.b64encode(f"public-key-material-{kid}".encode()).decode(),
        "validAfterTime": "2026-01-01T00:00:00Z",
        "validBeforeTime": "2036-01-01T00:00:00Z",
        "keyOrigin": "GOOGLE_PROVIDED",
        "keyType": "USER_MANAGED",
        "disabled": False,
        "_email": email,
    }
    keys[kid] = key
    store.persist()
    _record_event(store, f"projects/{project}/serviceAccounts/{email}", "CREATE_KEY", kid)
    return _json(200, _key_view(key))


def _list_keys(store, email) -> GcpIamResponse:
    keys = _keys_ns(store).get(email, {})
    # listKey responses omit privateKeyData by default.
    out = [{k2: v2 for k2, v2 in _key_view(k).items() if k2 != "privateKeyData"}
           for k in sorted(keys.values(), key=lambda k: k["name"])]
    return _json(200, {"keys": out})


def _get_key(store, email, kid) -> GcpIamResponse:
    key = _keys_ns(store).get(email, {}).get(kid)
    if key is None:
        return _err(404, f"Key {kid} not found.", "NOT_FOUND")
    return _json(200, _key_view(key))


def _delete_key(store, project, email, kid) -> GcpIamResponse:
    keys = _keys_ns(store).get(email, {})
    if kid not in keys:
        return _err(404, f"Key {kid} not found.", "NOT_FOUND")
    del keys[kid]
    store.persist()
    _record_event(store, f"projects/{project}/serviceAccounts/{email}", "DELETE_KEY", kid)
    return _json(200, {})


# ── deny policies (IAM Deny API, iam.googleapis.com/v2) ─────────────────────
def _create_deny_policy(store, attachment_point, policy_id, body) -> GcpIamResponse:
    if not policy_id:
        return _err(400, "policyId is required.", "INVALID_ARGUMENT")
    policies = _deny_ns(store).setdefault(attachment_point, {})
    name = f"{attachment_point}/denypolicies/{policy_id}"
    if policy_id in policies:
        return _err(409, f"Deny policy {policy_id} already exists.", "ALREADY_EXISTS")
    pol = {
        "name": name,
        "displayName": body.get("displayName", policy_id),
        "rules": list(body.get("rules", [])),
        "etag": _etag(),
        "updateTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    policies[policy_id] = pol
    store.persist()
    return _json(200, dict(pol))


def _list_deny_policies(store, attachment_point) -> GcpIamResponse:
    policies = _deny_ns(store).get(attachment_point, {})
    return _json(200, {"policies": [dict(p) for p in policies.values()]})


def _get_deny_policy(store, attachment_point, policy_id) -> GcpIamResponse:
    pol = _deny_ns(store).get(attachment_point, {}).get(policy_id)
    if pol is None:
        return _err(404, f"Deny policy {policy_id} not found.", "NOT_FOUND")
    return _json(200, dict(pol))


def _delete_deny_policy(store, attachment_point, policy_id) -> GcpIamResponse:
    policies = _deny_ns(store).get(attachment_point, {})
    if policy_id not in policies:
        return _err(404, f"Deny policy {policy_id} not found.", "NOT_FOUND")
    del policies[policy_id]
    store.persist()
    return _json(200, {})


# ── workload identity pools (iam.googleapis.com/v1) ─────────────────────────
def _create_pool(store, project, pool_id, body) -> GcpIamResponse:
    if not pool_id:
        return _err(400, "workloadIdentityPoolId is required.", "INVALID_ARGUMENT")
    name = f"projects/{project}/locations/global/workloadIdentityPools/{pool_id}"
    pools = _pools_ns(store)
    if name in pools:
        return _err(409, f"Pool {pool_id} already exists.", "ALREADY_EXISTS")
    pool = {
        "name": name,
        "displayName": body.get("displayName", pool_id),
        "description": body.get("description", ""),
        "state": "ACTIVE",
        "disabled": False,
    }
    pools[name] = pool
    store.persist()
    return _json(200, dict(pool))


def _list_pools(store, project) -> GcpIamResponse:
    prefix = f"projects/{project}/locations/global/workloadIdentityPools/"
    pools = [dict(p) for n, p in sorted(_pools_ns(store).items()) if n.startswith(prefix)]
    return _json(200, {"workloadIdentityPools": pools})


def _get_pool(store, name) -> GcpIamResponse:
    pool = _pools_ns(store).get(name)
    if pool is None:
        return _err(404, f"Pool not found: {name}", "NOT_FOUND")
    return _json(200, dict(pool))


def _delete_pool(store, name) -> GcpIamResponse:
    pools = _pools_ns(store)
    if name not in pools:
        return _err(404, f"Pool not found: {name}", "NOT_FOUND")
    pools[name]["state"] = "DELETED"
    store.persist()
    return _json(200, dict(pools[name]))


def _permissions_for_role(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


def _test_iam_permissions(store, resource, body) -> GcpIamResponse:
    """EVALUATE, don't echo. For each requested permission, grant it iff the
    caller's member is in a binding whose role grants that permission.

    The caller is taken from the request context: body may carry a "member"
    (test convenience / in-tab enforcement). Absent an explicit member we
    evaluate against ALL bindings on the resource (i.e. "is this permission
    granted to anyone bound here") — but the conformance contract is the
    explicit-member path, which is what a real testIamPermissions authorizes
    (the calling identity)."""
    requested = list(body.get("permissions") or [])
    member = body.get("member")  # optional caller override
    policies = _policy_ns(store)
    pol = policies.get(resource) or {"bindings": []}

    granted_perms: set[str] = set()
    for b in pol.get("bindings", []):
        members = b.get("members", [])
        if member is not None and member not in members:
            continue
        perms = _permissions_for_role(b.get("role", ""))
        if "*" in perms:
            # owner-style role grants any requested permission
            granted_perms.update(requested)
        else:
            granted_perms.update(perms)

    # Preserve request order, return only actually-granted permissions.
    result = [p for p in requested if p in granted_perms]
    return _json(200, {"permissions": result})


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: IamStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> GcpIamResponse:
    """Single routing point for the native GCP IAM REST API — what unmodified
    google-cloud-iam / google-cloud-resource-manager clients speak."""
    query = query or {}
    method = method.upper()

    def _body() -> dict:
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return {}

    # Strip a leading /v1 (iam.googleapis.com), /v2 (IAM Deny API) or /v3
    # (resourcemanager) prefix, and query string.
    p = path.split("?", 1)[0]
    for pre in ("/v1", "/v2", "/v3", "/v1beta1"):
        if p.startswith(pre + "/") or p == pre:
            p = p[len(pre):]
            break
    p = p.strip("/")

    # ---- resource IAM policy verbs (colon methods) ----
    # These live on the LAST path segment: "{resource}:getIamPolicy"
    if ":" in p:
        resource_path, _, verb = p.rpartition(":")
        resource = unquote(resource_path)
        if method != "POST":
            return _err(400, f"Method {method} not allowed for :{verb}", "INVALID_ARGUMENT")
        if verb == "getIamPolicy":
            return _get_iam_policy(store, resource)
        if verb == "setIamPolicy":
            return _set_iam_policy(store, resource, _body())
        if verb == "testIamPermissions":
            return _test_iam_permissions(store, resource, _body())
        if verb in ("disable", "enable") and resource.startswith("projects/") and "/serviceAccounts/" in resource:
            rsegs = resource.split("/")
            return _set_service_account_disabled(store, rsegs[1], rsegs[3], verb == "disable")
        return _err(400, f"Unknown method: {verb}", "INVALID_ARGUMENT")

    segs = [unquote(s) for s in p.split("/") if s != ""]

    # ---- service account keys: projects/{p}/serviceAccounts/{email}/keys[/{keyId}] ----
    if len(segs) >= 5 and segs[0] == "projects" and segs[2] == "serviceAccounts" and segs[4] == "keys":
        project, email = segs[1], segs[3]
        if len(segs) == 5:
            if method == "POST":
                return _create_key(store, project, email, _body())
            if method == "GET":
                return _list_keys(store, email)
            return _err(400, f"Unsupported method {method} on keys", "INVALID_ARGUMENT")
        kid = segs[5]
        if method == "GET":
            return _get_key(store, email, kid)
        if method == "DELETE":
            return _delete_key(store, project, email, kid)
        return _err(400, f"Unsupported method {method} on key", "INVALID_ARGUMENT")

    # ---- per-service-account admin-activity log: .../serviceAccounts/{email}/policyActivity ----
    if len(segs) == 5 and segs[0] == "projects" and segs[2] == "serviceAccounts" and segs[4] == "policyActivity":
        if method == "GET":
            return _list_activity(store, f"projects/{segs[1]}/serviceAccounts/{segs[3]}")
        return _err(400, f"Unsupported method {method} on policyActivity", "INVALID_ARGUMENT")

    # ---- service accounts: projects/{p}/serviceAccounts[/{email}] ----
    if len(segs) >= 3 and segs[0] == "projects" and segs[2] == "serviceAccounts":
        project = segs[1]
        if len(segs) == 3:
            if method == "POST":
                return _create_service_account(store, project, _body())
            if method == "GET":
                return _list_service_accounts(store, project)
            return _err(400, f"Unsupported method {method} on serviceAccounts", "INVALID_ARGUMENT")
        # single service account (email may contain no slash)
        ident = segs[3]
        if method == "GET":
            return _get_service_account(store, project, ident)
        if method == "PATCH":
            return _patch_service_account(store, project, ident, _body())
        if method == "DELETE":
            return _delete_service_account(store, project, ident)
        return _err(400, f"Unsupported method {method} on serviceAccount", "INVALID_ARGUMENT")

    # ---- applied-policy-change activity: projects/{p}/policyActivity ----
    if len(segs) == 3 and segs[0] == "projects" and segs[2] == "policyActivity":
        if method == "GET":
            return _list_activity(store, f"projects/{segs[1]}")
        return _err(400, f"Unsupported method {method} on policyActivity", "INVALID_ARGUMENT")

    # ---- predefined roles: roles ----
    if len(segs) == 1 and segs[0] == "roles":
        if method == "GET":
            return _json(200, {"roles": list_predefined_roles()})
        return _err(400, f"Unsupported method {method} on roles", "INVALID_ARGUMENT")

    # ---- custom roles: projects/{p}/roles[/{roleId}] ----
    if len(segs) >= 3 and segs[0] == "projects" and segs[2] == "roles":
        project = segs[1]
        if len(segs) == 3:
            if method == "POST":
                return _create_role(store, project, str(_body().get("roleId", "")).strip(), _body())
            if method == "GET":
                return _list_roles(store, project)
            return _err(400, f"Unsupported method {method} on roles", "INVALID_ARGUMENT")
        name = f"projects/{project}/roles/{segs[3]}"
        if method == "GET":
            return _get_role(store, name)
        if method == "PATCH":
            return _patch_role(store, name, _body())
        if method == "DELETE":
            return _delete_role(store, name)
        return _err(400, f"Unsupported method {method} on role", "INVALID_ARGUMENT")

    # ---- workload identity pools: projects/{p}/locations/global/workloadIdentityPools[/{id}] ----
    if (len(segs) >= 5 and segs[0] == "projects" and segs[2] == "locations"
            and segs[3] == "global" and segs[4] == "workloadIdentityPools"):
        project = segs[1]
        if len(segs) == 5:
            if method == "POST":
                return _create_pool(store, project, str(query.get("workloadIdentityPoolId", "")).strip(), _body())
            if method == "GET":
                return _list_pools(store, project)
            return _err(400, f"Unsupported method {method} on workloadIdentityPools", "INVALID_ARGUMENT")
        name = f"projects/{project}/locations/global/workloadIdentityPools/{segs[5]}"
        if method == "GET":
            return _get_pool(store, name)
        if method == "DELETE":
            return _delete_pool(store, name)
        return _err(400, f"Unsupported method {method} on workloadIdentityPool", "INVALID_ARGUMENT")

    # ---- deny policies: policies/{attachmentPoint}/denypolicies[/{policyId}] ----
    if len(segs) >= 3 and segs[0] == "policies" and segs[2] == "denypolicies":
        attachment_point = segs[1]
        if len(segs) == 3:
            if method == "POST":
                return _create_deny_policy(store, attachment_point, str(query.get("policyId", "")).strip(), _body())
            if method == "GET":
                return _list_deny_policies(store, attachment_point)
            return _err(400, f"Unsupported method {method} on denypolicies", "INVALID_ARGUMENT")
        policy_id = segs[3]
        if method == "GET":
            return _get_deny_policy(store, attachment_point, policy_id)
        if method == "DELETE":
            return _delete_deny_policy(store, attachment_point, policy_id)
        return _err(400, f"Unsupported method {method} on denypolicy", "INVALID_ARGUMENT")

    return _err(404, f"Unknown path: {path}", "NOT_FOUND")


# ── decision helper (not a native verb — for in-tab enforcement / console) ──
def is_permission_granted(store: IamStore, resource: str, member: str,
                          permission: str) -> bool:
    """Convenience probe: does `member` hold `permission` on `resource` via its
    bound roles? The GCP analogue of iam_core.is_authorized."""
    r = _test_iam_permissions(store, resource,
                              {"permissions": [permission], "member": member})
    return permission in json.loads(r.body.decode("utf-8")).get("permissions", [])
