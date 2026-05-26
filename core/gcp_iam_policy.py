"""GCP IAM enforcement — a small Policy Decision Point.

Reproduces IAM's *observable contract* (allow / 403 PERMISSION_DENIED) without
reproducing Google's internals: a curated role→permission catalog, a map from
each API operation to the permission it needs, and an authorize() that resolves
a project's policy bindings (principal → roles → permissions) for a request.

Enforcement is opt-in per space; owners/root always bypass so the console keeps
working. A real SDK/CLI selects its principal via the X-Cloudlearn-Principal
header (or the space's active principal).
"""

from __future__ import annotations

import fnmatch

# Curated predefined roles → permission patterns (wildcards allowed). A small,
# representative slice of GCP's catalog — enough to validate least-privilege.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "roles/owner": ["*"],
    "roles/editor": ["*.create", "*.update", "*.delete", "*.get", "*.list", "*.use",
                     "*.invoke", "*.publish", "*.consume", "*.connect"],
    "roles/viewer": ["*.get", "*.list"],
    # Cloud Storage
    "roles/storage.admin": ["storage.*"],
    "roles/storage.objectAdmin": ["storage.objects.*", "storage.buckets.get", "storage.buckets.list"],
    "roles/storage.objectCreator": ["storage.objects.create", "storage.buckets.get"],
    "roles/storage.objectViewer": ["storage.objects.get", "storage.objects.list", "storage.buckets.get"],
    # Cloud SQL
    "roles/cloudsql.admin": ["cloudsql.*"],
    "roles/cloudsql.editor": ["cloudsql.instances.*", "cloudsql.backupRuns.*"],
    "roles/cloudsql.viewer": ["cloudsql.instances.get", "cloudsql.instances.list"],
    "roles/cloudsql.client": ["cloudsql.instances.connect", "cloudsql.instances.get"],
    # Pub/Sub
    "roles/pubsub.admin": ["pubsub.*"],
    "roles/pubsub.editor": ["pubsub.topics.*", "pubsub.subscriptions.*"],
    "roles/pubsub.publisher": ["pubsub.topics.publish", "pubsub.topics.get"],
    "roles/pubsub.subscriber": ["pubsub.subscriptions.consume", "pubsub.subscriptions.get"],
    "roles/pubsub.viewer": ["pubsub.topics.get", "pubsub.topics.list", "pubsub.subscriptions.get", "pubsub.subscriptions.list"],
    # Cloud Functions
    "roles/cloudfunctions.admin": ["cloudfunctions.*"],
    "roles/cloudfunctions.developer": ["cloudfunctions.functions.*"],
    "roles/cloudfunctions.invoker": ["cloudfunctions.functions.invoke"],
    "roles/cloudfunctions.viewer": ["cloudfunctions.functions.get", "cloudfunctions.functions.list"],
    # Compute Engine
    "roles/compute.admin": ["compute.*"],
    "roles/compute.instanceAdmin": ["compute.instances.*", "compute.disks.*"],
    "roles/compute.viewer": ["compute.*.get", "compute.*.list"],
    # Firestore / Datastore
    "roles/datastore.user": ["datastore.entities.*", "datastore.databases.get"],
    "roles/datastore.viewer": ["datastore.entities.get", "datastore.entities.list"],
    # API Gateway
    "roles/apigateway.admin": ["apigateway.*"],
    "roles/apigateway.viewer": ["apigateway.*.get", "apigateway.*.list"],
    # IAM
    "roles/iam.serviceAccountAdmin": ["iam.serviceAccounts.*"],
    "roles/iam.securityAdmin": ["resourcemanager.projects.getIamPolicy", "resourcemanager.projects.setIamPolicy", "iam.*"],
}

# Owner-equivalent principals/roles that bypass enforcement.
_OWNER_PRINCIPALS = {"root", "owner", "admin", "", "allauthenticatedusers", "allusers"}
_OWNER_ROLES = {"roles/owner"}


def _read(verb: str) -> bool:
    return verb in ("get", "list")


def permission_for_request(path: str, method: str) -> str:
    """Map an inbound GCP-native request to the IAM permission it requires.
    Returns "" for paths that aren't gated (operations pollers, tooling, etc.)."""
    method = (method or "GET").upper()
    p = (path or "").split("?")[0]

    def verb(read="get", write="create", delete="delete"):
        return read if method in ("GET", "HEAD") else (delete if method == "DELETE" else write)

    # Cloud Storage --------------------------------------------------------
    if p.startswith("/upload/storage/v1/") or "/storage/v1/" in p:
        if "/o/" in p or p.endswith("/o") or "/upload/" in p:
            return f"storage.objects.{verb('get', 'create', 'delete')}"
        return f"storage.buckets.{verb('get', 'create', 'delete')}"
    # Compute Engine -------------------------------------------------------
    if "/compute/v1/" in p:
        if p.endswith("/start") or p.endswith("/stop") or p.endswith("/reset"):
            return "compute.instances.update"
        if "/instances" in p:
            return f"compute.instances.{verb('get', 'create', 'delete')}"
        if "/disks" in p:
            return f"compute.disks.{verb('get', 'create', 'delete')}"
        if "/networks" in p:
            return f"compute.networks.{verb('get', 'create', 'delete')}"
        if "/firewalls" in p:
            return f"compute.firewalls.{verb('get', 'create', 'delete')}"
        if "/subnetworks" in p:
            return f"compute.subnetworks.{verb('get', 'create', 'delete')}"
        return f"compute.instances.{verb('get', 'create', 'delete')}"
    # Cloud SQL ------------------------------------------------------------
    if "/sql/v1beta4/" in p:
        return f"cloudsql.instances.{verb('get', 'create', 'delete')}"
    # Pub/Sub --------------------------------------------------------------
    if "/topics" in p:
        if p.endswith(":publish"):
            return "pubsub.topics.publish"
        return f"pubsub.topics.{verb('get', 'create', 'delete')}"
    if "/subscriptions" in p:
        if p.endswith(":pull") or p.endswith(":acknowledge") or p.endswith(":modifyAckDeadline"):
            return "pubsub.subscriptions.consume"
        return f"pubsub.subscriptions.{verb('get', 'create', 'delete')}"
    # Cloud Functions ------------------------------------------------------
    if "/functions" in p:
        if p.endswith(":call"):
            return "cloudfunctions.functions.invoke"
        return f"cloudfunctions.functions.{verb('get', 'create', 'delete')}"
    # Firestore ------------------------------------------------------------
    if "/firestore/v1/" in p:
        return f"datastore.entities.{verb('get', 'create', 'delete')}"
    # API Gateway ----------------------------------------------------------
    if "/apis" in p or "/apiConfigs" in p or "/gateways" in p:
        return f"apigateway.apiconfigs.{verb('get', 'create', 'delete')}"
    # IAM service accounts -------------------------------------------------
    if "/serviceAccounts" in p:
        return f"iam.serviceAccounts.{verb('get', 'create', 'delete')}"
    return ""


def _permissions_for_role(role: str, custom_roles: dict | None = None) -> list[str]:
    if role in ROLE_PERMISSIONS:
        return ROLE_PERMISSIONS[role]
    custom = (custom_roles or {}).get(role) or {}
    perms = custom.get("includedPermissions") or custom.get("permissions") or []
    return list(perms) if isinstance(perms, list) else []


def _matches(granted: str, required: str) -> bool:
    if granted == "*" or granted == required:
        return True
    return fnmatch.fnmatchcase(required, granted)


def is_owner(principal: str, bindings: list, custom_roles: dict | None = None) -> bool:
    if str(principal or "").strip().lower() in _OWNER_PRINCIPALS:
        return True
    for binding in bindings or []:
        if str(binding.get("role")) in _OWNER_ROLES and _principal_in(principal, binding.get("members", [])):
            return True
    return False


def _principal_in(principal: str, members: list) -> bool:
    principal = str(principal or "")
    for m in members or []:
        m = str(m)
        if m in ("allUsers", "allAuthenticatedUsers"):
            return True
        # members look like "serviceAccount:foo@..", "user:bar@..", or bare email
        if m == principal or m.split(":", 1)[-1] == principal:
            return True
    return False


def granted_permissions(principal: str, bindings: list, custom_roles: dict | None = None) -> set[str]:
    perms: set[str] = set()
    for binding in bindings or []:
        if _principal_in(principal, binding.get("members", [])):
            perms.update(_permissions_for_role(str(binding.get("role")), custom_roles))
    return perms


def authorize(principal: str, required_permission: str, bindings: list, custom_roles: dict | None = None) -> bool:
    """True if the principal is allowed to perform required_permission."""
    if not required_permission:
        return True
    if is_owner(principal, bindings, custom_roles):
        return True
    for granted in granted_permissions(principal, bindings, custom_roles):
        if _matches(granted, required_permission):
            return True
    return False
