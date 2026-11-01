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
      POST   {resource}:testIamPermissions  body {"permissions":[...],"member"?}
             -> {"permissions":[granted...]}   (EVALUATED, not echoed; narrowed by any
             ENFORCED Principal Access Boundary binding on `member` — see rm_store)
    Service account Metrics tab (console-only convenience verb; derived from the real
    iamcredentials issuance log, not synthetic)
      GET    {resource}:metrics           -> {"totalRequests","byMethod":[...],"series":[...],"lastCallTime"}
    Managed Workload Identities (nested under a workload identity pool)
      POST   {pool}/managedIdentities?workloadIdentityPoolManagedIdentityId=X -> {"name","spiffeId","certificates":[...]}
      GET    {pool}/managedIdentities[/{id}]
      DELETE {pool}/managedIdentities/{id}
      POST   {managedIdentity}:rotateCertificate  -> issues a new certificate
    Asset Inventory
      GET    projects/{p}:searchAllResources?query= -> {"results":[...],"totalResults"}
    Security Insights
      GET    projects/{p}/locations/global/insights -> {"insights":[...]}  (evaluated live)
    Identity-Aware Proxy
      POST   projects/{p}/iap_web?resourceId=X    body {displayName} -> IapResource
      GET    projects/{p}/iap_web                 -> {"resources":[...]}
      PATCH  {resource}  body {enabled?,displayName?}
      DELETE {resource}
      POST   {resource}:checkAccess  body {"member"} -> {"allowed","reason"}  (the real
             Allow decision: enabled AND member holds roles/iap.httpsResourceAccessor)

Errors use the native GCP shape {"error":{"code","message","status"}}.
"""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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


def _managed_identities_ns(store: IamStore) -> dict:
    """Managed Workload Identities, keyed by '.../workloadIdentityPools/{pool}/managedIdentities/{id}'."""
    ns = getattr(store, "gcp_managed_identities", None)
    if ns is None:
        ns = {}
        store.gcp_managed_identities = ns  # type: ignore[attr-defined]
    return ns


def _iap_ns(store: IamStore) -> dict:
    """Identity-Aware Proxy resources, keyed by 'projects/{p}/iap_web/{id}'."""
    ns = getattr(store, "gcp_iap_resources", None)
    if ns is None:
        ns = {}
        store.gcp_iap_resources = ns  # type: ignore[attr-defined]
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


def _project_of_resource(resource: str) -> str | None:
    if resource.startswith("projects/"):
        return resource.split("/", 2)[1]
    return None


def org_policy_enforced(rm_store, project: str, constraint_id: str) -> bool:
    """Does an Org Policy v2 policy for `constraints/{constraint_id}` exist on the
    project with its first rule enforced? Backs the two boolean constraints Vyomi
    actually evaluates (iam.disableServiceAccountCreation,
    iam.disableServiceAccountKeyCreation) — every other constraint remains
    stored-but-not-evaluated, same as before. Public: shared with the offline
    legacy service-account handler (providers/gcp_iam.py), which keeps its own
    service-account state but must honour the same project's org policies."""
    if rm_store is None:
        return False
    policies = getattr(rm_store, "org_policies", None) or {}
    pol = policies.get(f"projects/{project}/policies/constraints/{constraint_id}")
    if not pol:
        return False
    rules = (pol.get("spec") or {}).get("rules") or []
    return bool(rules) and bool(rules[0].get("enforce", True))


def _pab_allowed_resources(rm_store, member: str | None) -> set[str] | None:
    """Principal Access Boundary enforcement. `None` means the member is not
    restricted by any boundary. Otherwise, the set of resource names the member's
    bound Principal Access Boundary policies explicitly allow — testIamPermissions
    must deny the member on every other resource, even if a regular IAM binding
    would otherwise grant it. Mirrors the real PAB semantics: a boundary can only
    narrow access, never widen it, on top of whatever Allow-policy bindings exist."""
    if rm_store is None or member is None:
        return None
    bindings = getattr(rm_store, "pab_bindings", None) or {}
    policies = getattr(rm_store, "pab_policies", None) or {}
    allowed: set[str] = set()
    restricted = False
    for b in bindings.values():
        if b.get("target", {}).get("principal") != member:
            continue
        pol = policies.get(b.get("policy"))
        if not pol:
            continue
        restricted = True
        for rule in (pol.get("details") or {}).get("rules", []):
            allowed.update(rule.get("resources", []))
    return allowed if restricted else None


# Data Access audit log categories Vyomi actually evaluates for iam.googleapis.com —
# ADMIN_READ on reads of service accounts / keys / custom roles / resource IAM
# policies. DATA_READ / DATA_WRITE are stored and returned but produce no entries:
# like real GCP, iam.googleapis.com has no data-plane payload to audit (creates/
# deletes are Admin Activity, always written regardless of this config, and are not
# modeled by this capability).
_AUDIT_SERVICE = "iam.googleapis.com"


def audit_log_enabled(policy: dict | None, service: str, log_type: str) -> bool:
    """Does `policy.auditConfigs` enable `log_type` for `service`? Takes the raw
    IAM-policy dict rather than a store, so it is reusable from the offline legacy
    handler's own policy dict (providers/gcp_iam.py) as well as this core's."""
    if not policy:
        return False
    for ac in policy.get("auditConfigs") or []:
        if ac.get("service") == service:
            return any(c.get("logType") == log_type for c in ac.get("auditLogConfigs") or [])
    return False


def _audit_log(logger, store, project: str | None, log_type: str, message: str) -> None:
    if not logger or not project:
        return
    pol = _policy_ns(store).get(f"projects/{project}")
    if not audit_log_enabled(pol, _AUDIT_SERVICE, log_type):
        return
    logger(project, log_type, message)


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
def _create_service_account(store, project, body, rm_store=None) -> GcpIamResponse:
    if org_policy_enforced(rm_store, project, "iam.disableServiceAccountCreation"):
        return _err(412, "Operation denied by org policy: 'constraints/iam.disableServiceAccountCreation' "
                         f"is enforced on 'projects/{project}'.", "FAILED_PRECONDITION")
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


def _get_service_account(store, project, ident, logger=None) -> GcpIamResponse:
    sas = _sa_ns(store)
    email = ident if "@" in ident else _sa_email(ident, project)
    sa = sas.get(email)
    if sa is None:
        return _err(404, f"Unknown service account: {ident}", "NOT_FOUND")
    _audit_log(logger, store, project, "ADMIN_READ", f"iam.googleapis.com serviceAccounts.get {email}")
    return _json(200, _sa_view(sa))


def _list_service_accounts(store, project, logger=None) -> GcpIamResponse:
    sas = _sa_ns(store)
    accounts = [_sa_view(sa) for email, sa in sorted(sas.items())
                if sa["projectId"] == project]
    _audit_log(logger, store, project, "ADMIN_READ", f"iam.googleapis.com serviceAccounts.list on projects/{project}")
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
def _get_iam_policy(store, resource, logger=None) -> GcpIamResponse:
    policies = _policy_ns(store)
    pol = policies.get(resource)
    _audit_log(logger, store, _project_of_resource(resource), "ADMIN_READ",
               f"iam.googleapis.com getIamPolicy on {resource}")
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


def _get_role(store, name, logger=None) -> GcpIamResponse:
    role = _roles_ns(store).get(name)
    if role is None:
        return _err(404, f"Role {name} not found.", "NOT_FOUND")
    _audit_log(logger, store, _project_of_resource(name), "ADMIN_READ", f"iam.googleapis.com roles.get {name}")
    return _json(200, _role_view(role))


def _list_roles(store, project, logger=None) -> GcpIamResponse:
    roles = _roles_ns(store)
    out = [_role_view(r) for n, r in sorted(roles.items())
           if r.get("_project") == project and not r.get("deleted")]
    _audit_log(logger, store, project, "ADMIN_READ", f"iam.googleapis.com roles.list on projects/{project}")
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


def _create_key(store, project, email, body, rm_store=None) -> GcpIamResponse:
    if org_policy_enforced(rm_store, project, "iam.disableServiceAccountKeyCreation"):
        return _err(412, "Operation denied by org policy: 'constraints/iam.disableServiceAccountKeyCreation' "
                         f"is enforced on 'projects/{project}'.", "FAILED_PRECONDITION")
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


def _list_keys(store, project, email, logger=None) -> GcpIamResponse:
    keys = _keys_ns(store).get(email, {})
    # listKey responses omit privateKeyData by default.
    out = [{k2: v2 for k2, v2 in _key_view(k).items() if k2 != "privateKeyData"}
           for k in sorted(keys.values(), key=lambda k: k["name"])]
    _audit_log(logger, store, project, "ADMIN_READ", f"iam.googleapis.com keys.list for {email}")
    return _json(200, {"keys": out})


def _get_key(store, project, email, kid, logger=None) -> GcpIamResponse:
    key = _keys_ns(store).get(email, {}).get(kid)
    if key is None:
        return _err(404, f"Key {kid} not found.", "NOT_FOUND")
    _audit_log(logger, store, project, "ADMIN_READ", f"iam.googleapis.com keys.get {kid} for {email}")
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


def _test_iam_permissions(store, resource, body, rm_store=None) -> GcpIamResponse:
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

    boundary = _pab_allowed_resources(rm_store, member)
    if boundary is not None and resource not in boundary:
        return _json(200, {"permissions": []})

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


# ── service account Metrics tab (console) ───────────────────────────────────
def _get_service_account_metrics(store, resource: str, iamc_store=None) -> GcpIamResponse:
    """Real request-activity series for a service account, derived from the
    credentials this service account actually issued (core/gcp_iamcredentials_core.py's
    `store.issued`, written on every generateAccessToken/generateIdToken/signBlob/signJwt
    call made AS this service account) — never synthetic/random data."""
    rsegs = resource.split("/")
    if len(rsegs) != 4 or rsegs[0] != "projects" or rsegs[2] != "serviceAccounts":
        return _err(400, f"Invalid resource for metrics: {resource}", "INVALID_ARGUMENT")
    project, ident = rsegs[1], rsegs[3]
    sas = _sa_ns(store)
    email = ident if "@" in ident else _sa_email(ident, project)
    if email not in sas or sas[email]["projectId"] != project:
        return _err(404, f"Unknown service account: {ident}", "NOT_FOUND")
    return _json(200, service_account_metrics(email, iamc_store))


def service_account_metrics(email: str, iamc_store=None) -> dict:
    """The metrics document for one service account's issued credentials (also the offline
    console route's, whose service accounts live in the pre-v4 IAM state)."""
    issued = list(getattr(iamc_store, "issued", {}).values()) if iamc_store is not None else []
    rows = [r for r in issued if r.get("serviceAccount") == email]
    by_method: dict[str, int] = {}
    by_day: dict[str, int] = {}
    last_call = ""
    for r in rows:
        by_method[r["method"]] = by_method.get(r["method"], 0) + 1
        day = (r.get("issueTime") or "")[:10]
        if day:
            by_day[day] = by_day.get(day, 0) + 1
        if (r.get("issueTime") or "") > last_call:
            last_call = r["issueTime"]
    return {
        "serviceAccount": email,
        "totalRequests": len(rows),
        "byMethod": [{"method": m, "count": c} for m, c in sorted(by_method.items())],
        "series": [{"date": d, "count": c} for d, c in sorted(by_day.items())],
        "lastCallTime": last_call,
    }


# ── Managed Workload Identities (nested under a workload identity pool) ─────
def _mi_cert(identity_name: str, serial: int, now: datetime) -> dict:
    """Synthetic X.509-shaped certificate material — real stateful lifecycle
    (serial, notBefore/notAfter, rotation) but not issued by a real CA, so it
    cannot be used to authenticate against anything outside Vyomi (same caveat
    as service-account keys)."""
    fp = hashlib.sha256(f"{identity_name}#{serial}#{now.isoformat()}".encode()).hexdigest()
    pem = ("-----BEGIN CERTIFICATE-----\n" +
           base64.b64encode(fp.encode()).decode() + "\n-----END CERTIFICATE-----\n")
    return {
        "serialNumber": str(serial),
        "pemCertificate": pem,
        "notBefore": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notAfter": (now + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _create_managed_identity(store, pool_name, identity_id, body) -> GcpIamResponse:
    if pool_name not in _pools_ns(store):
        return _err(404, f"Workload identity pool {pool_name} not found.", "NOT_FOUND")
    if not identity_id:
        return _err(400, "workloadIdentityPoolManagedIdentityId is required.", "INVALID_ARGUMENT")
    name = f"{pool_name}/managedIdentities/{identity_id}"
    ns = _managed_identities_ns(store)
    if name in ns:
        return _err(409, f"Managed identity {identity_id} already exists.", "ALREADY_EXISTS")
    pool_id = pool_name.rsplit("/", 1)[-1]
    now = datetime.now(timezone.utc)
    mi = {
        "name": name,
        "spiffeId": f"spiffe://{pool_id}.global.vyomi.dev/ns/default/sa/{identity_id}",
        "description": body.get("description", ""),
        "createTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "state": "ACTIVE",
        "certificates": [_mi_cert(name, 1, now)],
        "_next_serial": 2,
    }
    ns[name] = mi
    store.persist()
    return _json(200, {k: v for k, v in mi.items() if not k.startswith("_")})


def _list_managed_identities(store, pool_name) -> GcpIamResponse:
    prefix = pool_name + "/managedIdentities/"
    out = [{k: v for k, v in mi.items() if not k.startswith("_")}
           for n, mi in sorted(_managed_identities_ns(store).items()) if n.startswith(prefix)]
    return _json(200, {"managedIdentities": out})


def _get_managed_identity(store, name) -> GcpIamResponse:
    mi = _managed_identities_ns(store).get(name)
    if mi is None:
        return _err(404, f"Managed identity {name} not found.", "NOT_FOUND")
    return _json(200, {k: v for k, v in mi.items() if not k.startswith("_")})


def _delete_managed_identity(store, name) -> GcpIamResponse:
    ns = _managed_identities_ns(store)
    if name not in ns:
        return _err(404, f"Managed identity {name} not found.", "NOT_FOUND")
    del ns[name]
    store.persist()
    return _json(200, {})


def _rotate_managed_identity_cert(store, name) -> GcpIamResponse:
    ns = _managed_identities_ns(store)
    mi = ns.get(name)
    if mi is None:
        return _err(404, f"Managed identity {name} not found.", "NOT_FOUND")
    now = datetime.now(timezone.utc)
    cert = _mi_cert(name, mi["_next_serial"], now)
    mi["_next_serial"] += 1
    mi["certificates"].insert(0, cert)
    mi["certificates"] = mi["certificates"][:5]
    store.persist()
    return _json(200, {k: v for k, v in mi.items() if not k.startswith("_")})


# ── Asset Inventory: searchAllResources over what Vyomi models for IAM/RM ───
def _search_assets(store, project, query_str, rm_store=None) -> GcpIamResponse:
    """Real, live search over the IAM & Resource Manager resources this project
    actually has — not Cloud Asset Inventory's full org-wide resource/IAM/policy
    index (which spans every GCP service and keeps a change history Vyomi doesn't
    maintain)."""
    q = (query_str or "").strip().lower()
    results = []
    for email, sa in sorted(_sa_ns(store).items()):
        if sa["projectId"] != project:
            continue
        results.append({
            "name": sa["name"], "assetType": "iam.googleapis.com/ServiceAccount",
            "displayName": sa.get("displayName") or email, "project": f"projects/{project}",
            "state": "DISABLED" if sa.get("disabled") else "ACTIVE",
        })
    for name, role in sorted(_roles_ns(store).items()):
        if not name.startswith(f"projects/{project}/roles/"):
            continue
        results.append({
            "name": name, "assetType": "iam.googleapis.com/Role",
            "displayName": role.get("title") or name.rsplit("/", 1)[-1],
            "project": f"projects/{project}", "state": role.get("stage", "GA"),
        })
    for name, pool in sorted(_pools_ns(store).items()):
        if not name.startswith(f"projects/{project}/locations/"):
            continue
        results.append({
            "name": name, "assetType": "iam.googleapis.com/WorkloadIdentityPool",
            "displayName": pool.get("displayName") or name.rsplit("/", 1)[-1],
            "project": f"projects/{project}", "state": pool.get("state", "ACTIVE"),
        })
    if rm_store is not None:
        p = getattr(rm_store, "projects", {}).get(project)
        if p:
            results.append({
                "name": p["name"], "assetType": "cloudresourcemanager.googleapis.com/Project",
                "displayName": p.get("displayName") or project, "project": f"projects/{project}",
                "state": p.get("state", "ACTIVE"),
            })
        for name, tk in sorted(getattr(rm_store, "tag_keys", {}).items()):
            if tk.get("parent") != f"projects/{project}":
                continue
            results.append({
                "name": name, "assetType": "cloudresourcemanager.googleapis.com/TagKey",
                "displayName": tk.get("shortName", ""), "project": f"projects/{project}", "state": "ACTIVE",
            })
    if q:
        results = [r for r in results if q in r["displayName"].lower() or q in r["assetType"].lower()]
    return _json(200, {"results": results, "totalResults": len(results)})


# ── Security Insights: lint rules evaluated live over the current IAM state ─
def _security_insights(store, project, iamc_store=None) -> GcpIamResponse:
    """Real IAM-lint-style findings computed fresh on every call from the
    project's ACTUAL policy bindings, service accounts, keys and issued
    credentials — not a canned or randomly-generated list."""
    insights = []
    pol = _policy_ns(store).get(f"projects/{project}") or {}
    for b in pol.get("bindings", []):
        if b.get("role") not in ("roles/owner", "roles/editor"):
            continue
        for m in b.get("members", []):
            insights.append({
                "name": "insights/primitive-role-" + hashlib.sha1(f"{b['role']}|{m}".encode()).hexdigest()[:12],
                "category": "PERMISSIONS_USAGE", "severity": "MEDIUM",
                "description": f"{m} is granted the basic role {b['role']} on projects/{project}. "
                                "Basic roles grant broad permissions across every service; consider a "
                                "predefined or custom role with the specific permissions needed instead.",
                "stateMetadata": {"state": "ACTIVE"},
            })
    issued_sas = {r["serviceAccount"] for r in getattr(iamc_store, "issued", {}).values()} if iamc_store else set()
    keys = _keys_ns(store)
    for email, sa in sorted(_sa_ns(store).items()):
        if sa["projectId"] != project:
            continue
        has_keys = bool(keys.get(email))
        if has_keys:
            insights.append({
                "name": "insights/sa-has-keys-" + hashlib.sha1(email.encode()).hexdigest()[:12],
                "category": "SECURITY", "severity": "LOW",
                "description": f"{email} has {len(keys[email])} user-managed key(s). Downloadable keys are a "
                                "long-lived credential risk; prefer Workload Identity Federation or short-lived "
                                "tokens where possible.",
                "stateMetadata": {"state": "ACTIVE"},
            })
        if not has_keys and email not in issued_sas and not sa.get("disabled"):
            insights.append({
                "name": "insights/sa-unused-" + hashlib.sha1(email.encode()).hexdigest()[:12],
                "category": "PERMISSIONS_USAGE", "severity": "LOW",
                "description": f"{email} has no keys and has never issued a credential (access token, ID "
                                "token or signed blob/JWT). If it is not needed, consider removing it.",
                "stateMetadata": {"state": "ACTIVE"},
            })
    return _json(200, {"insights": insights})


# ── Identity-Aware Proxy: per-resource toggle + the Allow decision it gates ──
def _iap_create(store, project, resource_id, body) -> GcpIamResponse:
    if not resource_id:
        return _err(400, "resourceId is required.", "INVALID_ARGUMENT")
    name = f"projects/{project}/iap_web/{resource_id}"
    ns = _iap_ns(store)
    if name in ns:
        return _err(409, f"IAP resource {resource_id} already exists.", "ALREADY_EXISTS")
    ns[name] = {"name": name, "enabled": bool(body.get("enabled", True)),
                "displayName": body.get("displayName", resource_id)}
    store.persist()
    return _json(200, dict(ns[name]))


def _iap_list(store, project) -> GcpIamResponse:
    prefix = f"projects/{project}/iap_web/"
    return _json(200, {"resources": [dict(r) for n, r in sorted(_iap_ns(store).items()) if n.startswith(prefix)]})


def _iap_patch(store, name, body) -> GcpIamResponse:
    ns = _iap_ns(store)
    r = ns.get(name)
    if r is None:
        return _err(404, f"IAP resource {name} not found.", "NOT_FOUND")
    if "enabled" in body:
        r["enabled"] = bool(body["enabled"])
    if "displayName" in body:
        r["displayName"] = body["displayName"]
    store.persist()
    return _json(200, dict(r))


def _iap_delete(store, name) -> GcpIamResponse:
    ns = _iap_ns(store)
    if name not in ns:
        return _err(404, f"IAP resource {name} not found.", "NOT_FOUND")
    del ns[name]
    store.persist()
    return _json(200, {})


def _iap_check_access(store, resource, body) -> GcpIamResponse:
    """The decision IAP's proxy makes on every request: enabled AND the member
    holds roles/iap.httpsResourceAccessor (or roles/owner) on this IAP resource."""
    member = body.get("member")
    r = _iap_ns(store).get(resource)
    if r is None:
        return _err(404, f"IAP resource {resource} not found.", "NOT_FOUND")
    if not r.get("enabled"):
        return _json(200, {"allowed": False, "reason": "Identity-Aware Proxy is turned off for this resource."})
    pol = _policy_ns(store).get(resource) or {"bindings": []}
    accessor_roles = {"roles/iap.httpsResourceAccessor", "roles/owner"}
    allowed = any(member in b.get("members", []) for b in pol.get("bindings", []) if b.get("role") in accessor_roles)
    reason = "Member holds roles/iap.httpsResourceAccessor." if allowed else \
        "Member does not hold roles/iap.httpsResourceAccessor (or roles/owner) on this resource."
    return _json(200, {"allowed": allowed, "reason": reason})


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: IamStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", rm_store=None, logger=None, iamc_store=None) -> GcpIamResponse:
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
        if verb == "metrics" and method == "GET":
            return _get_service_account_metrics(store, resource, iamc_store=iamc_store)
        if verb == "searchAllResources" and method == "GET":
            rsegs = resource.split("/")
            if len(rsegs) == 2 and rsegs[0] == "projects":
                return _search_assets(store, rsegs[1], query.get("query"), rm_store=rm_store)
            return _err(400, f"Invalid scope for searchAllResources: {resource}", "INVALID_ARGUMENT")

        if verb == "checkAccess" and method == "POST" and "/iap_web/" in resource:
            return _iap_check_access(store, resource, _body())
        if verb == "rotateCertificate" and method == "POST" and "/managedIdentities/" in resource:
            return _rotate_managed_identity_cert(store, resource)
        if method != "POST":
            return _err(400, f"Method {method} not allowed for :{verb}", "INVALID_ARGUMENT")
        if verb == "getIamPolicy":
            return _get_iam_policy(store, resource, logger=logger)
        if verb == "setIamPolicy":
            return _set_iam_policy(store, resource, _body())
        if verb == "testIamPermissions":
            return _test_iam_permissions(store, resource, _body(), rm_store=rm_store)
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
                return _create_key(store, project, email, _body(), rm_store=rm_store)
            if method == "GET":
                return _list_keys(store, project, email, logger=logger)
            return _err(400, f"Unsupported method {method} on keys", "INVALID_ARGUMENT")
        kid = segs[5]
        if method == "GET":
            return _get_key(store, project, email, kid, logger=logger)
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
                return _create_service_account(store, project, _body(), rm_store=rm_store)
            if method == "GET":
                return _list_service_accounts(store, project, logger=logger)
            return _err(400, f"Unsupported method {method} on serviceAccounts", "INVALID_ARGUMENT")
        # single service account (email may contain no slash)
        ident = segs[3]
        if method == "GET":
            return _get_service_account(store, project, ident, logger=logger)
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
                return _list_roles(store, project, logger=logger)
            return _err(400, f"Unsupported method {method} on roles", "INVALID_ARGUMENT")
        name = f"projects/{project}/roles/{segs[3]}"
        if method == "GET":
            return _get_role(store, name, logger=logger)
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
        if len(segs) == 6:
            if method == "GET":
                return _get_pool(store, name)
            if method == "DELETE":
                return _delete_pool(store, name)
            return _err(400, f"Unsupported method {method} on workloadIdentityPool", "INVALID_ARGUMENT")
        # ---- managed workload identities: .../workloadIdentityPools/{pool}/managedIdentities[/{id}] ----
        if segs[6] == "managedIdentities":
            if len(segs) == 7:
                if method == "POST":
                    return _create_managed_identity(store, name, str(query.get("workloadIdentityPoolManagedIdentityId", "")).strip(), _body())
                if method == "GET":
                    return _list_managed_identities(store, name)
                return _err(400, f"Unsupported method {method} on managedIdentities", "INVALID_ARGUMENT")
            mi_name = f"{name}/managedIdentities/{segs[7]}"
            if method == "GET":
                return _get_managed_identity(store, mi_name)
            if method == "DELETE":
                return _delete_managed_identity(store, mi_name)
            return _err(400, f"Unsupported method {method} on managedIdentity", "INVALID_ARGUMENT")
        return _err(404, f"Unknown path: {path}", "NOT_FOUND")

    # ---- Identity-Aware Proxy resources: projects/{p}/iap_web[/{id}] ----
    if len(segs) >= 3 and segs[0] == "projects" and segs[2] == "iap_web":
        project = segs[1]
        if len(segs) == 3:
            if method == "POST":
                return _iap_create(store, project, str(query.get("resourceId", "")).strip(), _body())
            if method == "GET":
                return _iap_list(store, project)
            return _err(400, f"Unsupported method {method} on iap_web", "INVALID_ARGUMENT")
        name = f"projects/{project}/iap_web/{segs[3]}"
        if method == "PATCH":
            return _iap_patch(store, name, _body())
        if method == "DELETE":
            return _iap_delete(store, name)
        return _err(400, f"Unsupported method {method} on IAP resource", "INVALID_ARGUMENT")

    # ---- Security Insights: projects/{p}/locations/global/insights ----
    if (len(segs) == 5 and segs[0] == "projects" and segs[2] == "locations"
            and segs[3] == "global" and segs[4] == "insights"):
        if method == "GET":
            return _security_insights(store, segs[1], iamc_store=iamc_store)
        return _err(400, f"Unsupported method {method} on insights", "INVALID_ARGUMENT")

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
