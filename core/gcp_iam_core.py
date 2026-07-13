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
from urllib.parse import unquote

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


# ── resource IAM policy operations ──────────────────────────────────────────
def _get_iam_policy(store, resource) -> GcpIamResponse:
    policies = _policy_ns(store)
    pol = policies.get(resource)
    if pol is None:
        # GCP returns an empty policy (version 1, no bindings) for a resource
        # that has never had a policy set.
        return _json(200, {"version": 1, "bindings": [], "etag": _etag()})
    return _json(200, {
        "version": pol.get("version", 1),
        "bindings": [dict(b) for b in pol.get("bindings", [])],
        "etag": pol.get("etag", _etag()),
    })


def _set_iam_policy(store, resource, body) -> GcpIamResponse:
    policy = body.get("policy") or {}
    bindings = policy.get("bindings") or []
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
    _policy_ns(store)[resource] = stored
    store.persist()
    return _json(200, {
        "version": stored["version"],
        "bindings": [dict(b) for b in stored["bindings"]],
        "etag": stored["etag"],
    })


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

    # Strip a leading /v1 (iam.googleapis.com) or /v3 (resourcemanager) prefix,
    # and query string.
    p = path.split("?", 1)[0]
    for pre in ("/v1", "/v3", "/v1beta1"):
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
        return _err(400, f"Unknown method: {verb}", "INVALID_ARGUMENT")

    segs = [unquote(s) for s in p.split("/") if s != ""]

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
        if method == "DELETE":
            return _delete_service_account(store, project, ident)
        return _err(400, f"Unsupported method {method} on serviceAccount", "INVALID_ARGUMENT")

    return _err(404, f"Unknown path: {path}", "NOT_FOUND")


# ── decision helper (not a native verb — for in-tab enforcement / console) ──
def is_permission_granted(store: IamStore, resource: str, member: str,
                          permission: str) -> bool:
    """Convenience probe: does `member` hold `permission` on `resource` via its
    bound roles? The GCP analogue of iam_core.is_authorized."""
    r = _test_iam_permissions(store, resource,
                              {"permissions": [permission], "member": member})
    return permission in json.loads(r.body.decode("utf-8")).get("permissions", [])
