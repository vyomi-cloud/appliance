"""Azure ARM control-plane core (substrate-free) for Vyomi-Nano.

A faithful port of ``providers/azure_services.handle_arm``: a GENERIC Azure
Resource Manager CRUD over a flat in-memory store keyed by the lower-cased
resource id, parameterized by the RESOURCE_CATALOG dumped verbatim from the
appliance (``core/azure_arm_data.py``). Unlike AWS/GCP in Nano (which ride the
generic ``/api/{cloud}/{service}`` collection-path ResourceStore), the Azure
console speaks real ARM —
    PUT/GET/DELETE /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.X/{type}/{name}?api-version=
— so this core handles those paths directly.

Stripped vs the appliance handler (no substrate): FastAPI Request/Response,
CloudSim sync, usage recording, real backend provisioning, host-budget + tier
quantity/size caps. VM lifecycle actions become metadata-only (no LXD in a
browser). Pure stdlib → runs identically on host CPython and under Pyodide.

Entry point:
    AzureArm().handle(method, path, query=None, body=None)
      -> {"status": int, "headers": dict, "body": dict | None}
where ``path`` is the request path (``/subscriptions/...`` or
``/api/azure/operations/{id}``) AFTER any bundle base-prefix is stripped.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import re
import uuid
from urllib.parse import unquote, urlsplit

try:                                              # host: package import
    from core.azure_arm_data import CATALOG, ROLES
except ImportError:                               # Pyodide: cores are flat on sys.path
    from azure_arm_data import CATALOG, ROLES      # type: ignore

try:                                              # Container Apps engine (Microsoft.App)
    from core import azure_app_core as app_engine
except ImportError:
    import azure_app_core as app_engine            # type: ignore

try:                                              # Azure Monitor workspaces + Managed Grafana (Microsoft.Monitor, Microsoft.Dashboard)
    from core import azure_monitorproducts_core as monprod_engine
except ImportError:
    import azure_monitorproducts_core as monprod_engine   # type: ignore

try:                                              # App Service engine (Microsoft.Web: web apps, function apps, plans)
    from core import azure_webapp_core as web_engine
except ImportError:
    import azure_webapp_core as web_engine          # type: ignore

try:                                              # App Configuration engine (Microsoft.AppConfiguration)
    from core import azure_appconfiguration_core as appconfig_engine
except ImportError:
    import azure_appconfiguration_core as appconfig_engine   # type: ignore

try:                                              # Cognitive Services engine (Microsoft.CognitiveServices)
    from core import azure_cognitiveservices_core as cogs_engine
except ImportError:
    import azure_cognitiveservices_core as cogs_engine   # type: ignore

try:                                              # Azure DNS engine (Microsoft.Network/dnsZones)
    from core import azure_dns_core as dns_engine
except ImportError:
    import azure_dns_core as dns_engine            # type: ignore

try:                                              # Azure Monitor engine (Microsoft.Insights)
    from core import azure_monitor_core as monitor_engine
except ImportError:
    import azure_monitor_core as monitor_engine    # type: ignore

try:                                              # Azure Log Analytics engine (Microsoft.OperationalInsights)
    from core import azure_operationalinsights_core as oi_engine
except ImportError:
    import azure_operationalinsights_core as oi_engine   # type: ignore

try:                                              # Azure Cost Management + Consumption engine
    from core import azure_cost_core as cost_engine
except ImportError:
    import azure_cost_core as cost_engine          # type: ignore
try:                                              # Event Grid event subscriptions (Microsoft.EventGrid, scoped to a topic)
    from core import azure_eventgrid_core as eventgrid_engine
except ImportError:
    import azure_eventgrid_core as eventgrid_engine       # type: ignore

try:                                              # Storage account keys (rotation) + route-specific endpoints
    from core import azure_storage_ext_core as storage_ext
except ImportError:
    import azure_storage_ext_core as storage_ext   # type: ignore

try:                                              # Azure Policy rule engine (custom policyRule evaluation)
    from core import azure_policy_core as policy_engine
except ImportError:
    import azure_policy_core as policy_engine      # type: ignore

try:                                              # Private endpoints / Bastion / Firewall / DDoS / NSG flow logs
    from core import azure_netsvc_core as netsvc
except ImportError:
    import azure_netsvc_core as netsvc             # type: ignore
try:                                              # v4 AZ-07: Network Manager, Front Door / CDN, AKS + Container Apps networking
    from core import azure_netcfg_core as netcfg
except ImportError:
    import azure_netcfg_core as netcfg             # type: ignore
try:                                              # v4 AZ-02..05: KEDA / AKS extensions, Cosmos CORS+gateway+CMK, Service Bus CMK+network rules, App Config CMK, subnet delegation
    from core import azure_cfgext_core as cfgext
except ImportError:
    import azure_cfgext_core as cfgext             # type: ignore
try:                                              # v4: Azure Backup + Site Recovery (Recovery Services vaults) over real Blob artifacts
    from core import azure_backup_core as backup_engine
except ImportError:
    import azure_backup_core as backup_engine      # type: ignore
try:                                              # v4: Azure SQL copy / PITR / restore / geo-replication / LTR over the SqlStore data plane
    from core import azure_sqlbackup_core as sqlbk
except ImportError:
    import azure_sqlbackup_core as sqlbk           # type: ignore
try:                                              # v4 AZ-08: Azure Files, AI Search, Storage Mover, Marketplace, quota/billing extras
    from core import azure_files_core as files_engine, azure_search_core as search_engine
    from core import azure_storagemover_core as mover_engine, azure_marketplace_core as market_engine
    from core import azure_billing_ext_core as billing_ext
except ImportError:
    import azure_files_core as files_engine        # type: ignore
    import azure_search_core as search_engine      # type: ignore
    import azure_storagemover_core as mover_engine # type: ignore
    import azure_marketplace_core as market_engine # type: ignore
    import azure_billing_ext_core as billing_ext   # type: ignore

try:                                              # Management locks (Microsoft.Authorization/locks, scoped to ANY resource)
    from core import azure_locks_core as locks_engine
except ImportError:
    import azure_locks_core as locks_engine        # type: ignore

try:                                              # Microsoft.Support (support requests filed with Vyomi)
    from core import azure_support_core as support_engine
except ImportError:
    import azure_support_core as support_engine    # type: ignore

try:                                              # Resource health + Advisor (derived from the stored resources)
    from core import azure_health_core as health_engine
except ImportError:
    import azure_health_core as health_engine      # type: ignore

try:                                              # checkAccess decision algorithm (wildcard + scope-inheritance +
    from core import azure_iam_core as iam_engine  # notActions/deny) — reused for role assignments created as real
except ImportError:                               # ARM resources scoped to a resource group (this module's own store,
    import azure_iam_core as iam_engine            # type: ignore   not azure_iam_core's separate directory-role store).

try:                                              # Microsoft Defender for Cloud (Microsoft.Security), live over this state
    from core import azure_security_core as security_engine
except ImportError:
    import azure_security_core as security_engine  # type: ignore

try:                                              # AKS Kubernetes object store + kubectl (runCommand)
    from core import azure_aks_k8s_core as k8s_engine
    from core import kubescape_core as kubescape_engine
except ImportError:
    import azure_aks_k8s_core as k8s_engine        # type: ignore
    import kubescape_core as kubescape_engine      # type: ignore

try:                                              # VM size catalog (vcpu/ram/family per real Azure size name)
    from core import instance_catalog
except ImportError:
    import instance_catalog                        # type: ignore

DEFAULT_SUBSCRIPTION = "00000000-0000-0000-0000-cloudlearn01"
DEFAULT_RG = "cloudlearn-rg"
DEFAULT_LOCATION = "eastus"

# The one simulated subscription's offer — a fixed Pay-As-You-Go quota, same shape real ARM's
# GET /subscriptions/{id} returns under subscriptionPolicies. The portal's Overview blade reads
# "Offer"/"Offer ID" off quotaId through its own static offer-name catalog, not a separate field.
SUBSCRIPTION_POLICIES = {"locationPlacementId": "Public_2014-09-01", "quotaId": "PayAsYouGo_2014-09-01", "spendingLimit": "Off"}

# The one simulated signed-in identity (Overview's "My role: Owner", IAM's CURRENT_USER in the
# console) — "My permissions" defaults to full access for it absent any explicit assignment,
# same as the portal shows Owner with no role assignment needed for the account that created
# the subscription.
DEFAULT_PRINCIPAL = "admin@vyomi.local"

# Real Azure built-in policy definition GUID for "Allowed locations" — the one built-in Vyomi's
# policy engine actually evaluates and enforces (Microsoft.Authorization/policyAssignments ->
# AzureArm._policy_block, called from every catalog resource PUT).
POLICY_ALLOWED_LOCATIONS_ID = "e56962a6-4747-49cd-b67b-bf8b01975c4c"

# Settings > Preview features (Microsoft.Features/providers/{ns}/features): a curated sample of
# real preview feature flags, lifecycle-only (register/unregister persists like real ARM; Vyomi
# has no second code path these flags gate, so registering one doesn't change other behavior —
# same ceiling the portal's own flag has for most preview features, which only unlock allow-listing
# on the real control plane rather than changing it locally).
PREVIEW_FEATURES = [
    ("Microsoft.Compute", "EncryptionAtHost"),
    ("Microsoft.Compute", "LiveMigrationAcrossNUMANodes"),
    ("Microsoft.ContainerService", "AKS-AzureKeyVaultSecretsProvider"),
    ("Microsoft.ContainerService", "EnablePodIdentityPreview"),
    ("Microsoft.Network", "AllowApplicationSecurityGroupOnAllProtocols"),
    ("Microsoft.Sql", "AADSecurityAdminDisableFlag"),
    ("Microsoft.Storage", "SkipCertainMgmtOperations"),
    ("Microsoft.Web", "StaticSitesSSR"),
]

# Settings > Usage + quotas: a reduced subset of Azure's published default regional quotas
# (real Azure ships dozens of per-SKU-family compute quotas and several network quotas; Vyomi
# models the two most commonly hit compute ones plus three network ones), counted LIVE off real
# provisioned resources and ENFORCED on create (AzureArm._quota_block — exceeding one fails the
# PUT with a real QuotaExceeded error, not just a report).
#
# Limits are set well above anything a single test/demo session legitimately needs — Nano and
# the offline appliance keep LIVE state across many runs with no automatic reset (deleting a
# resource is the only thing that frees its quota, exactly like real Azure), so a limit tight
# enough to matter in one sitting would eventually block ordinary cumulative VM-service usage
# across unrelated services, not just a deliberate quota test.
COMPUTE_QUOTA = [("cores", "Total Regional vCPUs", 100), ("virtualMachines", "Virtual Machines", 100)]
NETWORK_QUOTA = [("PublicIPAddresses", "Public IP Addresses", 50), ("VirtualNetworks", "Virtual Networks", 100),
                  ("NetworkSecurityGroups", "Network Security Groups", 100)]

_BY_TYPE = {(c["namespace"].lower(), c["type"].lower()): c for c in CATALOG}


def _record_activity(resource_name: str, action: str, detail: str = "") -> None:
    """Best-effort: append to the shared cloudsim event log (core/nano_events.py) so a
    resource's "Activity log" panel has something real to show. Lazily imported — nano_events
    loads AFTER azure_arm_core in the Nano boot order (wasm/nano-boot.js), so a module-level
    import would fail there; by the time a request is served, boot has finished and the
    deferred import always succeeds."""
    try:
        try:
            from core import nano_events
        except ImportError:
            import nano_events  # type: ignore
        nano_events.record("azure", "arm", resource_name, action, "ok", detail)
    except Exception:
        pass


def _parse_odata_ts(s: str):
    try:
        d = datetime.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)   # naive = UTC (comparable)



def _activity_log_query(query: dict) -> dict:
    """GET /subscriptions/{sub}/providers/Microsoft.Insights/eventtypes/management/values —
    the real ARM activity-log read API every resource's "Activity log" blade calls, scoped
    via an OData $filter containing ``resourceUri eq '{id}'`` and/or the timespan picker's
    ``eventTimestamp ge/le '{iso}'`` predicates (ENFORCED — a narrower timespan really narrows
    the result). The rest of the OData grammar (severity/category, other operators) is not
    understood; with no resourceUri filter the unfiltered feed (every resource) is returned,
    matching the subscription-wide Activity log page."""
    try:
        try:
            from core import nano_events
        except ImportError:
            import nano_events  # type: ignore
    except Exception:
        return _ok({"value": []})
    filt = query.get("$filter") or ""
    m = re.search(r"resourceUri\s+eq\s+'([^']*)'", filt)
    resource = (m.group(1).rstrip("/").split("/")[-1]) if m else None
    events = nano_events.list_events(resource=resource)
    since = _parse_odata_ts(m.group(1)) if (m := re.search(r"eventTimestamp\s+ge\s+'([^']*)'", filt)) else None
    until = _parse_odata_ts(m.group(1)) if (m := re.search(r"eventTimestamp\s+le\s+'([^']*)'", filt)) else None
    if since is not None or until is not None:
        def _in_range(e):
            ts = _parse_odata_ts(e["ts"])
            if ts is None:
                return True
            if since is not None and ts < since:
                return False
            if until is not None and ts > until:
                return False
            return True
        events = [e for e in events if _in_range(e)]
    value = [{
        "eventName": {"value": e["action"], "localizedValue": e["action"]},
        "operationName": {"value": e["action"], "localizedValue": f"{e['action']}: {e['detail']}" if e["detail"] else e["action"]},
        "status": {"value": e["status"], "localizedValue": e["status"]},
        "eventTimestamp": e["ts"], "submissionTimestamp": e["ts"],
        "subscriptionId": DEFAULT_SUBSCRIPTION,
        "caller": "vyomi-console",
        "resourceId": e["resource"],
        "resourceGroupName": DEFAULT_RG,
        "level": "Informational",
        "id": str(e["id"]),
    } for e in events]
    return _ok({"value": value})


def _vault_record(state: dict | None, vault: str) -> dict | None:
    """Look up a Microsoft.KeyVault/vaults resource's full record by vault name alone (the
    Key Vault Keys/Secrets/Certificates data planes never learn the subscription/resource
    group — same read-only-snapshot pattern as azure_sql_core._server_props). None if
    `vault` is blank or no such vault exists (callers must treat that as "not enforced", not
    "denied" — an unknown vault name is not evidence of a restriction)."""
    if not state or not vault:
        return None
    want = f"/vaults/{vault}".lower()
    for rec in state.values():
        if isinstance(rec, dict) and rec.get("_type", "").lower() == "microsoft.keyvault/vaults" \
                and rec.get("id", "").lower().endswith(want):
            return rec
    return None


def vault_properties(state: dict | None, vault: str) -> dict:
    """`_vault_record`'s `properties`, or {} if the vault doesn't exist."""
    rec = _vault_record(state, vault)
    return (rec or {}).get("properties") or {}


def keyvault_network_denied(state: dict | None, vault: str) -> bool:
    """True when this vault's ARM-configured networking (Networking blade /
    azure.keyvaults.networking) would reject a data-plane call from the console: public
    network access disabled, or the firewall default action is Deny (Vyomi has no caller
    IP/VNet to match an allow-list entry against, so Deny blocks unconditionally — the same
    simplification real Azure makes for an unrecognized caller)."""
    p = vault_properties(state, vault)
    if not p:
        return False
    if p.get("publicNetworkAccess") == "Disabled":
        return True
    return (p.get("networkAcls") or {}).get("defaultAction") == "Deny"


def acr_registry_properties(state: dict | None, registry: str) -> dict:
    """Look up a Microsoft.ContainerRegistry/registries resource's `properties` by registry
    name alone (the registry's own data plane — core/azure_acr_core.py — never learns the
    subscription/resource group it lives in; the console tells the wire router which registry
    it's showing via the `x-vyomi-registry` header, same mechanism as `vault_properties` above)."""
    if not state or not registry:
        return {}
    want = f"/registries/{registry}".lower()
    for rec in state.values():
        if isinstance(rec, dict) and rec.get("_type", "").lower() == "microsoft.containerregistry/registries" \
                and rec.get("id", "").lower().endswith(want):
            return rec.get("properties") or {}
    return {}


def acr_network_denied(state: dict | None, registry: str) -> bool:
    """True when this registry's ARM-configured networking (Networking blade /
    azure.acr.networking) would reject a data-plane call: public network access disabled
    (Vyomi has no private-endpoint/VNet path to let it through, the same simplification
    keyvault_network_denied makes)."""
    return acr_registry_properties(state, registry).get("publicNetworkAccess") == "Disabled"


def acr_retention_days(state: dict | None, registry: str) -> int | None:
    """The registry's untagged-manifest retention policy (Retention (Preview) blade /
    azure.acr.retention) if enabled, else None — core/azure_acr_core.py's purge sweep uses this
    to actually delete untagged manifests older than the configured window."""
    policy = (acr_registry_properties(state, registry).get("policies") or {}).get("retentionPolicy") or {}
    if policy.get("status") != "enabled":
        return None
    try:
        return int(policy.get("days", 7))
    except (TypeError, ValueError):
        return None


# A single simulated signed-in identity: Vyomi has no multi-user session concept anywhere in
# the product (the whole console acts as one operator), so this is the one principal every
# Key Vault data-plane permission check below is evaluated against. A fresh vault's create
# PUT (see the generic PUT branch's "microsoft.keyvault/vaults" hook) self-grants it full
# access — exactly what `az keyvault create` already does by default (RBAC mode: a Key Vault
# Administrator role assignment; access-policy mode: a self-granting policy entry) — so the
# console's own create-vault-then-add-a-secret path keeps working without a detour through a
# separate "go grant yourself access" step nothing else in the product models either.
CALLER_PRINCIPAL_ID = "11111111-1111-1111-1111-111111111111"

# (resource, bucket) -> the Key Vault dataAction an RBAC role (core/azure_arm_data.py ROLES,
# the "Key Vault *" built-ins) must grant CALLER_PRINCIPAL_ID for azure.keyvaults.
# access_configuration's RBAC mode. "use" is the crypto operations (encrypt/decrypt/sign/
# verify/wrapKey/unwrapKey) — readable/usable by a Crypto User without full key management.
_KV_DATA_ACTIONS = {
    ("keys", "get"): "Microsoft.KeyVault/vaults/keys/read",
    ("keys", "list"): "Microsoft.KeyVault/vaults/keys/read",
    ("keys", "use"): "Microsoft.KeyVault/vaults/keys/use/action",
    ("keys", "create"): "Microsoft.KeyVault/vaults/keys/write",
    ("keys", "delete"): "Microsoft.KeyVault/vaults/keys/delete",
    ("secrets", "get"): "Microsoft.KeyVault/vaults/secrets/getSecret/action",
    ("secrets", "list"): "Microsoft.KeyVault/vaults/secrets/readMetadata/action",
    ("secrets", "create"): "Microsoft.KeyVault/vaults/secrets/write",
    ("secrets", "delete"): "Microsoft.KeyVault/vaults/secrets/delete",
    ("certificates", "get"): "Microsoft.KeyVault/vaults/certificates/read",
    ("certificates", "list"): "Microsoft.KeyVault/vaults/certificates/read",
    ("certificates", "create"): "Microsoft.KeyVault/vaults/certificates/write",
    ("certificates", "delete"): "Microsoft.KeyVault/vaults/certificates/delete",
}
# bucket -> the access-policy permission string (azure.keyvaults.access_policies' Get/List/
# Create/Delete — the console's own AccessPolicies dialog, consoles/src/azure/services/
# keyvaults/KeyVaultBlade.jsx PERMS); a crypto "use" needs at least Get, same simplification.
_KV_POLICY_PERM = {"get": "Get", "list": "List", "create": "Create", "delete": "Delete", "use": "Get"}

_KV_CRYPTO_OPS = ("encrypt", "decrypt", "sign", "verify", "wrapkey", "unwrapkey")


def classify_keyvault_operation(method: str, path: str) -> tuple[str, str] | None:
    """(resource, bucket) for a Key Vault Keys/Secrets/Certificates data-plane request —
    the same (resource, bucket) `_KV_DATA_ACTIONS` / `_KV_POLICY_PERM` key on. `path` is the
    root-shaped Key Vault path (/keys/..., /secrets/..., /certificates/...), the same shape
    both substrates normalize to before calling the *_core dispatch (aws_wire_router.py's own
    `path`; wire_ingress.py's `kv_core_path(path)`). None if the request doesn't map to a
    permission this console checks (unmodelled sub-resources fall through to the core's own
    404/405 — never a silent allow)."""
    method = (method or "GET").upper()
    segs = [s for s in (path or "").split("?", 1)[0].split("/") if s]
    if not segs or segs[0] not in ("keys", "secrets", "certificates"):
        return None
    resource = segs[0]
    if len(segs) == 1:
        return (resource, "list") if method == "GET" else None
    if len(segs) >= 3:
        tail = segs[2]
        if tail in ("create", "import") and method == "POST":
            return (resource, "create")
        if tail == "versions":
            return (resource, "list") if method == "GET" else None
        if tail == "pending":
            if method == "GET":
                return (resource, "get")
            if method == "DELETE":
                return (resource, "delete")
            return None
        if resource == "keys" and tail in _KV_CRYPTO_OPS and method == "POST":
            return (resource, "use")
    if len(segs) == 2:
        if method == "GET":
            return (resource, "get")
        if method == "DELETE":
            return (resource, "delete")
        if method in ("PUT", "PATCH"):
            return (resource, "create")
        return None
    if len(segs) == 3:
        if method == "GET":
            return (resource, "get")
        if method == "PATCH":
            return (resource, "create")
        return None
    if resource == "keys" and len(segs) == 4 and method == "POST" and segs[3] in _KV_CRYPTO_OPS:
        return (resource, "use")
    return None


def _kv_role_data_actions(state: dict | None, sub: str) -> dict:
    """roleName -> (dataActions, notDataActions), the built-in "Key Vault *" roles (core/
    azure_arm_data.py ROLES) merged with any custom role definition created via PUT .../
    roleDefinitions/{name} that carries its own dataActions — mirrors AzureArm._role_catalog's
    actions/notActions merge, over the separate dataActions namespace (control-plane roles
    like Owner/Contributor carry none, matching real Azure: being Owner of a subscription does
    not, by itself, grant Key Vault data access once RBAC authorization is enabled)."""
    out = {}
    for r in ROLES:
        props = r["properties"]
        data_actions, not_data_actions = [], []
        for p in props.get("permissions") or []:
            data_actions.extend(p.get("dataActions") or [])
            not_data_actions.extend(p.get("notDataActions") or [])
        out[props["roleName"]] = (data_actions, not_data_actions)
    for rec in (state or {}).values():
        if not isinstance(rec, dict) or rec.get("_type", "").lower() != "microsoft.authorization/roledefinitions" \
                or rec.get("_sub") != sub:
            continue
        props = rec.get("properties") or {}
        data_actions, not_data_actions = [], []
        for p in props.get("permissions") or []:
            data_actions.extend(p.get("dataActions") or [])
            not_data_actions.extend(p.get("notDataActions") or [])
        out[rec.get("name")] = (data_actions, not_data_actions)
    return out


def _check_data_access(state: dict | None, sub: str, scope_rid: str, principal_id: str, data_action: str) -> bool:
    """True if `principal_id` holds a role assignment covering `scope_rid` (the vault itself,
    or an ancestor scope — resource group / subscription, real Azure's inherited access) whose
    role's dataActions grant `data_action` — the RBAC half of azure.keyvaults.
    access_configuration. Same wildcard + scope-inheritance algorithm as AzureArm._check_access,
    over dataActions instead of actions; deny assignments are a control-plane-only concept here
    (skipped), same simplification azure.keyvaults.access_policies' flat allow-list makes."""
    roles = _kv_role_data_actions(state, sub)
    for rec in (state or {}).values():
        if not isinstance(rec, dict) or rec.get("_type", "").lower() != "microsoft.authorization/roleassignments" \
                or rec.get("_sub") != sub:
            continue
        props = rec.get("properties") or {}
        if props.get("principalId") != principal_id:
            continue
        if str(props.get("kind", "allow")).lower() == "deny":
            continue
        if not iam_engine._scope_covers(props.get("scope", "/"), scope_rid):
            continue
        role_name = props.get("roleName") or (props.get("roleDefinitionId") or "").rsplit("/", 1)[-1]
        data_actions, not_data_actions = roles.get(role_name, ([], []))
        if iam_engine._matches_any(data_actions, data_action) and not iam_engine._matches_any(not_data_actions, data_action):
            return True
    return False


def grant_vault_creator(state: dict, rec: dict, rid: str, sub: str, rg: str | None) -> None:
    """A new vault's creator gets full data-plane access, like `az keyvault create`: a Key Vault
    Administrator role assignment in RBAC mode, an access-policy entry otherwise. Shared by this
    engine and the offline ARM catalog path (providers/azure_services)."""
    props = rec.setdefault("properties", {})
    if props.get("enableRbacAuthorization"):
        ra_name = str(uuid.uuid4())
        ra_rid = f"{rid}/providers/Microsoft.Authorization/roleAssignments/{ra_name}"
        state[ra_rid.lower()] = {
            "id": ra_rid, "name": ra_name, "type": "Microsoft.Authorization/roleAssignments",
            "_type": "microsoft.authorization/roleassignments", "_sub": sub, "_rg": rg,
            "properties": {"principalId": CALLER_PRINCIPAL_ID, "roleName": "Key Vault Administrator",
                          "principalType": "User", "scope": rid},
        }
    else:
        props["accessPolicies"] = [{
            "tenantId": props.get("tenantId", "00000000-0000-0000-0000-000000000000"),
            "objectId": CALLER_PRINCIPAL_ID,
            "permissions": {"keys": ["Get", "List", "Create", "Delete"],
                           "secrets": ["Get", "List", "Create", "Delete"],
                           "certificates": ["Get", "List", "Create", "Delete"]},
        }]


def keyvault_access_denied(state: dict | None, vault: str, resource: str, bucket: str) -> bool:
    """True when this vault's access model (azure.keyvaults.access_configuration's RBAC-vs-
    access-policy switch, azure.keyvaults.access_policies' entries) would reject a data-plane
    call for `resource` ("keys"/"secrets"/"certificates") + `bucket` ("get"/"list"/"create"/
    "delete"/"use") — ENFORCED against the single simulated signed-in principal
    CALLER_PRINCIPAL_ID: RBAC mode checks a real role assignment covering this vault (or an
    ancestor scope); vault access policy mode checks the vault's own accessPolicies list."""
    rec = _vault_record(state, vault)
    if not rec:
        return False
    props = rec.get("properties") or {}
    if props.get("enableRbacAuthorization"):
        sub = rec.get("_sub")
        data_action = _KV_DATA_ACTIONS.get((resource, bucket))
        if not sub or not data_action:
            return False
        return not _check_data_access(state, sub, rec.get("id", ""), CALLER_PRINCIPAL_ID, data_action)
    perm = _KV_POLICY_PERM.get(bucket, bucket.capitalize())
    for p in props.get("accessPolicies") or []:
        if p.get("objectId") != CALLER_PRINCIPAL_ID:
            continue
        if perm in ((p.get("permissions") or {}).get(resource) or []):
            return False
    return True


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _tz_offset_minutes(tz_label: str) -> int:
    """Parse the UTC offset embedded in an Azure-style display string, e.g.
    '(UTC-08:00) Pacific Time (US & Canada)' -> -480. Bare 'UTC' / '(UTC) ...' -> 0
    (no IANA/Windows tz database in stdlib, but every offset Azure shows is spelled
    out in the label itself, so no database is needed)."""
    m = re.match(r"\(UTC([+-]\d{2}):(\d{2})\)", tz_label or "")
    if not m:
        return 0
    sign = 1 if m.group(1)[0] == "+" else -1
    return sign * (int(m.group(1)[1:]) * 60 + int(m.group(2)))


def _apply_auto_shutdown(rec: dict) -> None:
    """azure.vms.auto_shutdown, ENFORCED: if the stored schedule's local time has already
    passed today, flip the virtual machine's own logical power state to stopped — lazily, on
    read, since there is no real background scheduler. `_autoShutdownFiredDate` is a
    once-per-calendar-day guard: without it, a manual Start after the scheduled time would get
    immediately re-stopped by the very next GET."""
    sched = ((rec.get("properties") or {}).get("autoShutdown")) or {}
    if not sched.get("enabled"):
        return
    try:
        hh, mm = (int(x) for x in str(sched.get("time", "")).split(":")[:2])
    except ValueError:
        return
    now_local = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=_tz_offset_minutes(sched.get("timeZone")))
    today = now_local.date().isoformat()
    if now_local.time() >= datetime.time(hh, mm) and rec.get("_autoShutdownFiredDate") != today:
        rec.setdefault("properties", {})["powerState"] = "PowerState/stopped"
        rec["_autoShutdownFiredDate"] = today


# Same fixed Entra tenant every other core that mints a principalId hardcodes (azure_app_core.py,
# azure_appconfiguration_core.py, …) — there is only ever one simulated tenant.
_FIXED_TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"


def _vm_identity_view(rid: str, identity: dict) -> dict:
    """azure.vms.identity, lifted off config_only: real ARM mints identity.principalId/
    tenantId the instant identity.type includes SystemAssigned (never left for the caller to
    invent), and drops them the instant it is turned back to 'None'. The principalId is a
    stable uuid5 of the VM's own resource id (same derivation style as every other core that
    mints one), so it is consistent across repeated reads. This principalId is what Run
    command's IMDS simulation hands back as the token subject, and what a real role
    assignment/Key Vault access policy can be written against (azure.vms.run_command)."""
    itype = str(identity.get("type") or "None")
    out = dict(identity)
    if "systemassigned" in itype.lower():
        out["principalId"] = identity.get("principalId") or str(uuid.uuid5(uuid.NAMESPACE_URL, rid.lower() + "#principal"))
        out["tenantId"] = identity.get("tenantId") or _FIXED_TENANT
    else:
        out.pop("principalId", None)
        out.pop("tenantId", None)
    return out


# ── pure helpers (ported verbatim from azure_services) ─────────────────────
def _set_path(obj: dict, dotted: str, value):
    parts = dotted.split(".")
    cur = obj
    for i, p in enumerate(parts):
        last = i == len(parts) - 1
        nxt = parts[i + 1] if not last else None
        if p.isdigit():
            idx = int(p)
            if not isinstance(cur, list):
                return
            while len(cur) <= idx:
                cur.append({} if (nxt is not None and not nxt.isdigit()) else ([] if nxt is not None else None))
            if last:
                cur[idx] = value
            else:
                if not isinstance(cur[idx], (dict, list)):
                    cur[idx] = [] if nxt.isdigit() else {}
                cur = cur[idx]
        else:
            if last:
                cur[p] = value
            else:
                if not isinstance(cur.get(p), (dict, list)):
                    cur[p] = [] if (nxt and nxt.isdigit()) else {}
                cur = cur[p]


def _get_path(obj, dotted: str):
    cur = obj
    for p in dotted.split("."):
        if isinstance(cur, list) and p.isdigit():
            idx = int(p)
            cur = cur[idx] if idx < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
        if cur is None:
            return None
    return cur


def _merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _h(*parts, n=8):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:n]


def _guid(*parts):
    h = _h(*parts, n=32)
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


_NO_IDENTITY = {"type": "None", "principalId": None, "tenantId": None, "userAssignedIdentities": None}


def missing_identity_ref(state: dict, ua):
    """First ``userAssignedIdentities`` key that is not an existing managed identity, else None."""
    for rid in (ua or {}):
        t = state.get(str(rid).lower())
        if not t or t.get("_type", "").lower() != "microsoft.managedidentity/userassignedidentities":
            return rid
    return None


def resolve_identity_refs(rec: dict, state: dict):
    return _resolve_user_identities(rec, state)


def _resolve_user_identities(rec: dict, state: dict):
    """Fill every ``identity.userAssignedIdentities[<id>]`` with the referenced managed identity's real
    principalId/clientId. Returns the first referenced id that does NOT exist (so the PUT/PATCH can fail like
    ARM does), else ``None``."""
    ua = (rec.get("identity") or {}).get("userAssignedIdentities")
    if not isinstance(ua, dict):
        return None
    for rid in list(ua):
        tgt = state.get(str(rid).lower())
        if not tgt or tgt.get("_type", "").lower() != "microsoft.managedidentity/userassignedidentities":
            return rid
        p = tgt.get("properties") or {}
        ua[rid] = {"principalId": p.get("principalId"), "clientId": p.get("clientId")}
    return None


def _apply_identity(rec: dict, ident: dict) -> None:
    """``identity`` is a top-level sibling of ``properties`` on ANY generic-catalog resource
    (real ARM shape) — generic over every type this engine serves (ACR, APIM, VMs, …), mirroring
    azure_webapp_core.py's own ``_apply_identity`` for Microsoft.Web. A partial PATCH with no
    "type" (e.g. a caller stamping its own principalId) still just MERGES onto whatever identity
    is already there, like any other field. A PATCH that DOES carry "type" re-derives the whole
    block: System-assigned gets a stable, deterministic principal/tenant id (minted once, kept
    across repeat PUT/PATCH like the real RP does), and switching to "None" clears it. User-
    assigned identities are stored by resource id but not resolved (Vyomi has no Managed Identity
    resource of its own)."""
    cur = rec.get("identity") or dict(_NO_IDENTITY)
    if "type" not in ident:
        rec["identity"] = _merge(cur, ident)
        return
    itype = str(ident.get("type") or "None")
    out = {"type": itype, "principalId": None, "tenantId": None,
           "userAssignedIdentities": (ident["userAssignedIdentities"] if isinstance(ident.get("userAssignedIdentities"), dict) else cur.get("userAssignedIdentities")) or {}}
    if "systemassigned" in itype.lower():
        out["principalId"] = cur.get("principalId") or _guid(rec["id"], "principal")
        out["tenantId"] = _guid(rec["_sub"], "tenant")
    rec["identity"] = out


def _public_ip() -> str:
    """A public IPv4 for a new Microsoft.Network/publicIPAddresses (Azure-ish 20.x range)."""
    h = uuid.uuid4().int
    return f"20.{(h >> 8) % 200 + 10}.{(h >> 16) % 254 + 1}.{(h >> 24) % 254 + 1}"


def _expand_tokens(obj, name: str, base: str):
    if isinstance(obj, str):
        return (obj.replace("__UUID__", str(uuid.uuid4()))
                   .replace("__NAME__", name)
                   .replace("__BASE__", base)
                   .replace("__NOW__", _now())
                   .replace("__PUBLICIP__", _public_ip()))
    if isinstance(obj, dict):
        return {k: _expand_tokens(v, name, base) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_tokens(v, name, base) for v in obj]
    return obj


# ── ARM template deployment: literal [parameters('x')] / [variables('y')] substitution only
# (no expression language, no resourceId()/concat()/etc, no dependsOn ordering beyond
# template order) — a bounded but real evaluator, see AzureArm._execute_deployment.
_PARAM_EXPR = re.compile(r"^\[\s*parameters\(\s*'([^']*)'\s*\)\s*\]$")
_VAR_EXPR = re.compile(r"^\[\s*variables\(\s*'([^']*)'\s*\)\s*\]$")


def _resolve_template_expr(value, params: dict, variables: dict):
    if isinstance(value, str):
        m = _PARAM_EXPR.match(value.strip())
        if m:
            return params.get(m.group(1))
        m = _VAR_EXPR.match(value.strip())
        if m:
            return variables.get(m.group(1))
        return value
    if isinstance(value, dict):
        return {k: _resolve_template_expr(v, params, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_template_expr(v, params, variables) for v in value]
    return value


_APIM_DEFAULT_POLICY = ("<policies>\r\n  <inbound />\r\n  <backend>\r\n    <forward-request />\r\n"
                        "  </backend>\r\n  <outbound />\r\n  <on-error />\r\n</policies>")


def _apim_default_policy(type_chain, names, state, rid=""):
    """A new API Management service ships with the default global policy, so
    GET .../service/{n}/policies/policy returns it instead of 404 until PUT."""
    if (len(type_chain) == 3 and len(names) == 2 and names[1].lower() == "policy"
            and type_chain[1].lower() == "service" and type_chain[2].lower() == "policies"
            and type_chain[0].lower() == "microsoft.apimanagement"):
        parent = rid.rsplit("/policies/", 1)[0].lower()
        if parent in state:
            return {"id": rid, "name": "policy", "type": "Microsoft.ApiManagement/service/policies",
                    "properties": {"format": "xml", "value": _APIM_DEFAULT_POLICY}}
    return None


def _canonical_id(sub: str, rg, type_chain, names) -> str:
    seg = [f"/subscriptions/{sub}"]
    if rg:
        seg.append(f"resourceGroups/{rg}")
    seg.append("providers")
    ns = type_chain[0]
    seg.append(ns)
    rest_types = type_chain[1:]
    seg.append(rest_types[0])
    for i, nm in enumerate(names):
        seg.append(nm)
        if i + 1 < len(rest_types):
            seg.append(rest_types[i + 1])
    return "/".join(seg)


def _role_assignment_marker(chain):
    """Index of a re-entrant, LIST-only ``['providers', 'Microsoft.Authorization',
    'roleAssignments']`` marker in `chain` (`AzureArm._arm`'s split of everything after the
    FIRST namespace token) — i.e. GET .../<some resource>/providers/Microsoft.Authorization/
    roleAssignments, same shape as the locks/diagnosticSettings extension resources. A bare
    name after the marker (reading ONE assignment scoped that way) isn't modelled and falls
    through to the generic subscription-scoped catalog alternation instead."""
    for i in range(len(chain) - 2):
        if (chain[i].lower() == "providers" and chain[i + 1].lower() == "microsoft.authorization"
                and chain[i + 2].lower() == "roleassignments" and i + 3 == len(chain)):
            return i
    return None


def _check_access_marker(chain):
    """Index of a re-entrant ``['providers', 'Microsoft.Authorization', 'checkAccess']``
    marker in `chain`, same shape as `_role_assignment_marker` — i.e. POST .../<some
    resource>/providers/Microsoft.Authorization/checkAccess, the decision call behind any
    resource's own "Access control (IAM) > Check access / My access" tab (not just the
    resource-group/subscription scope the dedicated branch above already handled)."""
    for i in range(len(chain) - 2):
        if (chain[i].lower() == "providers" and chain[i + 1].lower() == "microsoft.authorization"
                and chain[i + 2].lower() == "checkaccess" and i + 3 == len(chain)):
            return i
    return None


def _parse_kv_secret_identifier(secret_id: str):
    """`https://{vault}.vault.azure.net/secrets/{name}[/{version}]` -> (name, version|None),
    the same shape the azure-keyvault-secrets SDK parses a secret `id` back out of
    (core/azure_keyvault_secrets_core.py) — used in reverse here to resolve an APIM named
    value's `keyVault.secretIdentifier` against this space's own KV secrets store."""
    try:
        segs = [s for s in urlsplit(secret_id).path.split("/") if s]
    except Exception:
        return None, None
    if len(segs) < 2 or segs[0] != "secrets":
        return None, None
    return segs[1], (segs[2] if len(segs) > 2 else None)


def _view(rec: dict) -> dict:
    if rec.get("_type", "").lower() == "microsoft.compute/virtualmachines":
        _apply_auto_shutdown(rec)
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _rg_from_id(rid: str):
    parts = rid.split("/")
    for i, p in enumerate(parts):
        if p.lower() == "resourcegroups" and i + 1 < len(parts):
            return parts[i + 1]
    return None


# GET .../Microsoft.Compute/locations/{location}/vmSizes and GET .../virtualMachines/{vm}/vmSizes
# (azure.vms.size): real ARM VirtualMachineSize shape plus two reference-only extras (series,
# maxIops) the console's Size table shows — all numbers derived from instance_catalog.AZURE
# (the same catalog CloudSimBridge uses), never baked into the console itself.
_VM_SIZE_OS_DISK_MB = 1047552  # real Azure constant: max OS disk size for a generalized image
_SERIES_LABEL = {"burstable": "B-series", "general": "Dsv5-series", "compute": "Fsv2-series",
                  "memory": "Esv5-series", "storage": "Lsv3-series", "gpu": "NC-series"}
# Real published Azure max uncached disk IOPS, by vCPU count — shared across the general /
# compute / memory families at the same vCPU count (confirmed against Dsv5/Fsv2/Esv5 docs).
_IOPS_BY_VCPU = {1: 400, 2: 3750, 4: 6400, 8: 12800, 16: 25600, 32: 51200}
_IOPS_BURSTABLE = {1: 400, 2: 1300, 4: 2400, 8: 4800}


def _max_iops(family: str, vcpu: int) -> int:
    if family == "burstable":
        return _IOPS_BURSTABLE.get(vcpu, min(vcpu * 600, 4800))
    if family in ("storage", "gpu"):
        return 20000
    return _IOPS_BY_VCPU.get(vcpu, min(vcpu * 1600, 80000))


def _vm_size_entry(name: str, shape: dict) -> dict:
    vcpu, ram_mb, family = shape["vcpu"], shape["ram_mb"], shape["family"]
    max_data_disks = min(vcpu * (4 if family == "gpu" else 2), 64 if family == "gpu" else 32)
    resource_disk_gib = {"burstable": vcpu * 4, "storage": vcpu * 240, "gpu": vcpu * 55}.get(family, 0)
    series = "M-series" if name.startswith("Standard_M") else _SERIES_LABEL.get(family, "General purpose")
    return {
        "name": name, "numberOfCores": vcpu, "memoryInMB": ram_mb,
        "osDiskSizeInMB": _VM_SIZE_OS_DISK_MB, "resourceDiskSizeInMB": resource_disk_gib * 1024,
        "maxDataDiskCount": max_data_disks, "series": series, "maxIops": _max_iops(family, vcpu),
    }


def _vm_sizes() -> list:
    return [_vm_size_entry(name, shape) for name, shape in sorted(instance_catalog.AZURE.items())]


def _ok(body, status=200, headers=None):
    return {"status": status, "headers": headers or {}, "body": body}


def _ok_(body, status=200):
    return {"status": status, "body": body}


def _err(status: int, code: str, message: str):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


class AzureArm:
    """In-memory Azure Resource Manager control plane (one per Nano instance)."""

    def __init__(self, base: str = ""):
        self.state: dict = {}
        self.operations: dict = {}
        self._base = base                       # endpoint/LRO URL prefix (relative by default)
        self.sub_names: dict = {}               # subscription id (lower) -> displayName (Microsoft.Subscription/rename)
        self.sub_tags: dict = {}                # subscription id (lower) -> tags (Microsoft.Resources/tags/default)
        self.providers: dict = {}               # namespace (lower) -> "Registered" | "NotRegistered"
        self.kv_secrets_store = None             # set by aws_wire_router.py: this space's Key Vault secrets store (APIM named-value listValue)
        self.sql_store = None                    # set by the platform: the Azure SQL data plane's SqlStore (database export/import)
        self.blob_store = None                   # set by the platform: the simulator's Azure Blob store (.bacpac target/source)
        self._vm_tokens: dict = {}               # minted managed-identity token (string) -> {principalId, resource, vmRid}
                                                   # — Run command's IMDS simulation (azure.vms.identity / azure.vms.run_command)
        self.billing_properties: dict = {}       # {"accountAdmin": …} — Settings > Billing properties (PATCH .../Microsoft.Billing/billingProperties)
        self.feature_state: dict = {}            # sub (lower) -> "ns/featureName" (lower) -> "Registered"|"NotRegistered"
        self.deployment_credentials: dict = {}   # sub (lower) -> credential name -> {appId, secret, scope, roleAssignmentName, ...}

    # ── per-resource ARM activity entries (Microsoft.Insights/eventtypes rows) ──
    # Kept IN self.state (so they persist with the rest of ARM, offline and Nano alike) by the one
    # writer, azure_webapp_core._record_event — the Microsoft.Web engine records its own writes
    # through it, and anything else here can via _record_activity. Read back by the single
    # eventtypes handler in _arm, merged with the shared nano_events feed.
    def _record_activity(self, rid: str, operation_name: str, sub: str, status: str = "Succeeded"):
        try:   # a real write/delete raises the resource group's (and subscription's) Event Grid system event
            low = operation_name.lower()
            if "eventgrid" not in low and (low.endswith("/write") or low.endswith("/delete")) and "/resourcegroups/" in rid.lower():
                evt = "Microsoft.Resources.ResourceWriteSuccess" if low.endswith("/write") else "Microsoft.Resources.ResourceDeleteSuccess"
                if status != "Succeeded":
                    evt = "Microsoft.Resources.ResourceWriteFailure"
                eventgrid_engine.emit_system_event(self.state, rid, evt, rid, {"operationName": operation_name, "resourceUri": rid,
                                                                              "status": status}, sb_store=getattr(self, "sb_store", None))
        except Exception:
            pass
        web_engine._record_event(self.state, sub, _rg_from_id(rid), rid, operation_name, operation_name, status)

    def _activity_log(self, method: str, query: dict, sub: str = DEFAULT_SUBSCRIPTION):
        if method != "GET":
            return _err(405, "MethodNotAllowed", "The activity log supports GET only.")
        r = monitor_engine.dispatch(self.state, "GET", sub, None, ["eventtypes", "management", "values"], [], {}, query)
        return {"status": r["status"], "headers": {}, "body": r["body"]}

    # ── public entry ──────────────────────────────────────────────────────
    def handle(self, method: str, path: str, query=None, body=None):
        """Every ARM request. Wraps the dispatcher with user-assigned identity validation/resolution that is
        generic over EVERY engine (generic catalog, web apps, Cognitive Services, Container Apps, App Configuration …)."""
        m = (method or "GET").upper()
        ua = ((body or {}).get("identity") or {}).get("userAssignedIdentities") if m in ("PUT", "PATCH") and isinstance(body, dict) else None
        missing = missing_identity_ref(self.state, ua)
        if missing:
            return _err(400, "ResourceNotFound", f"The Resource '{missing}' of type 'Microsoft.ManagedIdentity/userAssignedIdentities' was not found.")
        out = self._handle_raw(method, path, query, body)
        if m != "GET" and isinstance(out, dict):   # security audit feed (core/secscan_core.py classifier)
            sub_m = re.search(r"/subscriptions/([^/]+)", str(path))
            if sub_m:
                security_engine.record_call(self.state, sub_m.group(1), m, str(path).split("?")[0], body, out.get("status", 200))
        if ua and isinstance(out, dict) and out.get("status", 500) < 300:
            self._resolve_identity_at(path, out)
        return out

    def _resolve_identity_at(self, path, out):
        rid = "/subscriptions/" + str(path).split("?")[0].split("/subscriptions/", 1)[-1].strip("/")
        rec = self.state.get(rid.lower())
        if rec is not None:
            resolve_identity_refs(rec, self.state)
            if isinstance(out.get("body"), dict) and out["body"].get("identity") is not None:
                out["body"]["identity"] = _view(rec).get("identity")

    def _handle_raw(self, method: str, path: str, query=None, body=None):
        method = (method or "GET").upper()
        query = query or {}
        # LRO poll — every operation completes immediately in the sim.
        if "/api/azure/operations/" in path:
            op_id = path.split("/api/azure/operations/", 1)[1].split("?", 1)[0].strip("/")
            op = self.operations.get(op_id)
            base = {"status": "Succeeded", "properties": {"provisioningState": "Succeeded"}}
            if op:
                base.update({"id": op["id"], "name": op["name"], "startTime": op["startTime"], "endTime": op["endTime"]})
                base.update(op.get("result") or {})
            return _ok(base)
        # Microsoft.ResourceGraph/resources ("Open query" on any browse list's command bar):
        # real Azure Resource Graph is TENANT-scoped (no /subscriptions/{sub}/ prefix — the
        # subscriptions to search are in the request body instead), so it's handled before the
        # /subscriptions/ prefix check below, same URL shape the Resource Graph Explorer uses.
        if "/providers/Microsoft.ResourceGraph/resources" in path:
            if method != "POST":
                return _err(405, "MethodNotAllowed", "Use POST to run a Resource Graph query.")
            return self._resource_graph(body if isinstance(body, dict) else {})
        i = path.find("/subscriptions/")
        if i == -1:
            return _err(404, "NotFound", f"Not an ARM path: {path}")
        rest = path[i + len("/subscriptions/"):].split("?", 1)[0]
        return self._arm(method, rest, query, body if isinstance(body, dict) else {})

    # ── Microsoft.ResourceGraph/resources: a real, minimal KQL subset (table "Resources" or
    # "ResourceContainers" | where <field> ==/=~/contains '<value>' [and ...] | project <fields>
    # | limit <n> | order by <field> [asc|desc] | count) evaluated over THIS engine's own
    # resource store — genuine cross-type/cross-subscription query results, not a canned
    # response (azure.acr.registry.listactions' "Open query"). ──────────────────────────────
    _RG_FIELDS = {
        "id": lambda r: r.get("id"), "name": lambda r: r.get("name"), "type": lambda r: r.get("type"),
        "kind": lambda r: r.get("kind"), "location": lambda r: r.get("location"),
        "resourcegroup": lambda r: r.get("_rg") or "", "subscriptionid": lambda r: r.get("_sub") or "",
        "tenantid": lambda r: "00000000-0000-0000-0000-000000000000",
        "tags": lambda r: r.get("tags") or {}, "properties": lambda r: r.get("properties") or {},
    }
    _RG_DEFAULT_COLUMNS = ["id", "name", "type", "tenantid", "kind", "location", "resourcegroup", "subscriptionid"]
    _RG_WHERE_RE = re.compile(r"^\s*(\w+)\s*(=~|==|contains)\s*'([^']*)'\s*$")

    def _resource_graph(self, payload: dict):
        q = str((payload or {}).get("query") or "").strip()
        if not q:
            return _err(400, "BadRequest", "The query field is required.")
        subs = {str(s).lower() for s in (payload.get("subscriptions") or [])}
        stages = [s.strip() for s in q.split("|")]
        table = stages[0].strip().lower()
        if table not in ("resources", "resourcecontainers"):
            return _err(400, "BadRequest", f"Table '{stages[0].strip()}' is not supported. Only 'Resources' and 'ResourceContainers' are simulated.")
        is_rg_table = table == "resourcecontainers"
        rows = [rec for rec in self.state.values()
                if isinstance(rec, dict) and rec.get("id") and "/__event__/" not in rec.get("id", "")
                and (not subs or str(rec.get("_sub", "")).lower() in subs)
                and (rec.get("_type", "").lower() == "microsoft.resources/resourcegroups") == is_rg_table]
        columns = list(self._RG_DEFAULT_COLUMNS)
        limit, count_only = None, False
        for stage in stages[1:]:
            s = stage.strip()
            low = s.lower()
            if low.startswith("where "):
                for clause in re.split(r"\s+and\s+", s[6:], flags=re.IGNORECASE):
                    m = self._RG_WHERE_RE.match(clause)
                    if not m:
                        return _err(400, "BadRequest", f"Unsupported 'where' clause: {clause.strip()}")
                    field, op, value = m.group(1).lower(), m.group(2), m.group(3)
                    getter = self._RG_FIELDS.get(field)
                    if getter is None:
                        return _err(400, "BadRequest", f"Unknown column '{field}'.")
                    def _match(rec, getter=getter, op=op, value=value):
                        v = str(getter(rec) or "")
                        return (value.lower() in v.lower()) if op == "contains" else \
                               (v.lower() == value.lower()) if op == "=~" else (v == value)
                    rows = [r for r in rows if _match(r)]
            elif low.startswith("project "):
                fields = [f.strip().lower() for f in s[8:].split(",") if f.strip()]
                unknown = [f for f in fields if f not in self._RG_FIELDS]
                if unknown:
                    return _err(400, "BadRequest", f"Unknown column(s) in project: {', '.join(unknown)}.")
                columns = fields
            elif low.startswith("limit "):
                try:
                    limit = int(s[6:].strip())
                except ValueError:
                    return _err(400, "BadRequest", "limit requires an integer.")
            elif low == "count":
                count_only = True
            elif low.startswith("order by "):
                field = s[9:].strip().split()[0].lower()
                getter = self._RG_FIELDS.get(field)
                if getter is not None:
                    rows = sorted(rows, key=lambda r: str(getter(r) or ""), reverse="desc" in low)
            else:
                return _err(400, "BadRequest", f"Unsupported query stage: {stage.strip()}")
        if count_only:
            return _ok({"totalRecords": len(rows), "count": len(rows), "data": [{"Count": len(rows)}], "resultTruncated": "false"})
        if limit is not None:
            rows = rows[:limit]
        out_rows = [[self._RG_FIELDS[c](r) for c in columns] for r in rows]
        return _ok({"totalRecords": len(out_rows), "count": len(out_rows),
                    "data": {"columns": [{"name": c, "type": "string"} for c in columns], "rows": out_rows},
                    "facets": [], "resultTruncated": "false"})

    # ── ARM dispatcher (port of handle_arm) ───────────────────────────────
    def _arm(self, method, rest, query, payload):
        base = self._base
        segs = [s for s in rest.split("/") if s != ""]
        if not segs:
            return _err(400, "BadRequest", "Missing subscription id.")
        sub = segs[0]
        rest_segs = segs[1:]

        if not rest_segs:
            return _ok({"id": f"/subscriptions/{sub}", "subscriptionId": sub,
                        "displayName": self.sub_names.get(sub.lower(), "CloudLearn Subscription"),
                        "state": "Enabled", "tags": self.sub_tags.get(sub.lower(), {}),
                        "subscriptionPolicies": SUBSCRIPTION_POLICIES})

        # resource groups
        if rest_segs[0].lower() == "resourcegroups" and len(rest_segs) <= 2:
            if len(rest_segs) == 1:
                if method == "GET":
                    return _ok({"value": self._list_resource_groups(sub)})
                return _err(405, "MethodNotAllowed", "Use PUT /resourcegroups/{name}.")
            return self._resource_group_item(method, sub, rest_segs[1], payload)

        rg = None
        idx = 0
        if rest_segs[0].lower() == "resourcegroups":
            if len(rest_segs) < 2:
                return _err(400, "BadRequest", "Missing resource group name.")
            rg = rest_segs[1]
            idx = 2

        # POST .../resourceGroups/{rg}/exportTemplate — every blade's "Export template" (ARM tab
        # + Bicep/Terraform renderings), core/azure_templates_core.py.
        if rg is not None and idx < len(rest_segs) and rest_segs[idx].lower() == "exporttemplate" and len(rest_segs) == idx + 1:
            if method != "POST":
                return _err(405, "MethodNotAllowed", "Use POST to export a template.")
            from core import azure_templates_core as _tpl
            r = _tpl.export_group(self.state, sub, rg, (payload or {}).get("resources"),
                                  {c["type"].lower(): c["api_version"] for c in CATALOG},
                                  (payload or {}).get("vyomiIncludeParameters", True) is not False)
            if r["status"] >= 300:
                return _err(r["status"], r["body"]["error"]["code"], r["body"]["error"]["message"])
            return _ok(r["body"])

        # GET .../resourceGroups/{rg}/resources — the generic "resources in this group"
        # list every resource-group blade's Overview/Resources tab and delete confirmation
        # call (az resource list -g / Resources.list_by_resource_group), scoped across every
        # catalog type at once (not alternating type/name like the "providers" branch below).
        if rg is not None and idx < len(rest_segs) and rest_segs[idx].lower() == "resources" and len(rest_segs) == idx + 1:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Use GET to list resources in a resource group.")
            items = [_view(r) for r in self.state.values()
                     if r.get("_sub") == sub and (r.get("_rg") or "").lower() == rg.lower()
                     and r.get("_type", "").lower() not in ("microsoft.resources/resourcegroups", web_engine.EVENT_TYPE)
                     and not r.get("_type", "").lower().startswith(security_engine.TYPE_PREFIX)]
            return _ok({"value": items})

        # GET /subscriptions/{sub}/resources — every resource across every resource group in
        # the subscription (az resource list / Resources.list), the Subscription blade's
        # Settings > Resources panel.
        if rg is None and idx < len(rest_segs) and rest_segs[idx].lower() == "resources" and len(rest_segs) == idx + 1:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Use GET to list resources in a subscription.")
            items = [_view(r) for r in self.state.values()
                     if r.get("_sub") == sub
                     and r.get("_type", "").lower() not in ("microsoft.resources/resourcegroups", web_engine.EVENT_TYPE)
                     and not r.get("_type", "").lower().startswith(security_engine.TYPE_PREFIX)]
            return _ok({"value": items})

        if idx >= len(rest_segs) or rest_segs[idx].lower() != "providers":
            return _err(400, "BadRequest", f"Unrecognized ARM path: /subscriptions/{rest}")
        after = rest_segs[idx + 1:]

        # provider registration probes (Settings > Resource providers: Register/Unregister/Refresh)
        if len(after) == 0 and method == "GET":
            return _ok({"value": [self._provider_info(n) for n in sorted({c["namespace"] for c in CATALOG})]})
        if len(after) == 1 and method == "GET":
            return _ok(self._provider_info(after[0]))
        if len(after) == 2 and after[1].lower() == "register" and method == "POST":
            self.providers[after[0].lower()] = "Registered"
            return _ok(self._provider_info(after[0]))
        if len(after) == 2 and after[1].lower() == "unregister" and method == "POST":
            self.providers[after[0].lower()] = "NotRegistered"
            return _ok(self._provider_info(after[0]))
        if len(after) < 2:
            return _err(400, "BadRequest", "Missing provider namespace/type.")

        namespace = after[0]
        chain = after[1:]

        # Microsoft.Support: services, problem classifications, checkNameAvailability, supportTickets
        # (+ communications) — core/azure_support_core.py. Subscription scoped.
        if namespace.lower() == "microsoft.support" and rg is None and support_engine.find_marker(chain):
            r = support_engine.dispatch(self.state, method, sub, chain, payload or {}, query or {},
                                        lambda rid: rid.lower() in self.state)
            return {"status": r["status"], "headers": {}, "body": r["body"]}
        # v4 AZ-08 engines (Files, AI Search, Storage Mover, Marketplace/SaaS, quota + billing extras).
        _x = self._az08(method, sub, rg, namespace, chain, payload, query)
        if _x is not None:
            return _x

        # Microsoft.Subscription/rename: the subscription blade's "Rename" header action.
        if namespace.lower() == "microsoft.subscription" and chain and chain[0].lower() == "rename":
            if method != "POST":
                return _err(405, "MethodNotAllowed", "Use POST to rename a subscription.")
            name = (payload or {}).get("subscriptionName")
            if not name:
                return _err(400, "BadRequest", "subscriptionName is required.")
            self.sub_names[sub.lower()] = name
            _record_activity(sub, "Update", f"Microsoft.Subscription rename to '{name}'")
            return _ok({"id": f"/subscriptions/{sub}", "subscriptionId": sub, "displayName": name,
                        "state": "Enabled", "tags": self.sub_tags.get(sub.lower(), {}),
                        "subscriptionPolicies": SUBSCRIPTION_POLICIES})

        # Microsoft.Resources/tags/default: tags at subscription scope (Tags - CreateOrUpdateAtScope),
        # the subscription blade's Tags panel (Microsoft.Authorization/locks aside, subscriptions
        # aren't a PUT/PATCH-able catalog resource, so tags live on this generic extension instead).
        if namespace.lower() == "microsoft.resources" and chain[:1] == ["tags"] and chain[1:2] == ["default"] and len(chain) == 2:
            key = sub.lower()
            if method == "GET":
                return _ok({"id": f"/subscriptions/{sub}/providers/Microsoft.Resources/tags/default",
                            "type": "Microsoft.Resources/tags", "properties": {"tags": self.sub_tags.get(key, {})}})
            if method in ("PUT", "PATCH"):
                tags = (payload or {}).get("properties", {}).get("tags")
                if not isinstance(tags, dict):
                    return _err(400, "BadRequest", "properties.tags is required.")
                self.sub_tags[key] = dict(tags) if method == "PUT" else _merge(self.sub_tags.get(key, {}), tags)
                _record_activity(sub, "Update", "Microsoft.Resources/tags 'default'")
                return _ok({"id": f"/subscriptions/{sub}/providers/Microsoft.Resources/tags/default",
                            "type": "Microsoft.Resources/tags", "properties": {"tags": self.sub_tags[key]}})
            if method == "DELETE":
                self.sub_tags.pop(key, None)
                return _ok(None, status=200)
            return _err(405, "MethodNotAllowed", f"{method} not allowed.")
        # Microsoft.Compute/.../vmSizes (azure.vms.size): subscription+location scoped
        # (.../providers/Microsoft.Compute/locations/{location}/vmSizes) or resource-scoped to
        # an existing VM (.../virtualMachines/{vm}/vmSizes) — a derived read, not a stored
        # resource, so it's caught before the generic type/name alternation below (which would
        # 404 "locations" as an unknown Microsoft.Compute type).
        if namespace.lower() == "microsoft.compute" and chain and chain[-1].lower() == "vmsizes":
            if method != "GET":
                return _err(405, "MethodNotAllowed", "vmSizes supports GET only.")
            return _ok({"value": _vm_sizes()})

        # Microsoft.Compute/virtualMachines/{vm}/providers/Microsoft.Compute/restorePoints[/{name}
        # [/restore]] (azure.vms.backup, lifted off not_simulated): "backups as snapshots" per
        # AGENT-UI.md — a real, stateful sub-resource capturing the VM's own ARM properties
        # document, never a stored-but-inert stub. Re-entrant "providers" shape like locks/
        # diagnostic settings above, but scoped to virtualMachines only (not every catalog
        # type) since that's the only resource this restore-point collection is modelled for.
        if namespace.lower() == "microsoft.compute" and len(chain) >= 2 and chain[0].lower() == "virtualmachines":
            rp_idx = next((i for i in range(len(chain) - 2)
                          if chain[i].lower() == "providers" and chain[i + 1].lower() == "microsoft.compute"
                          and chain[i + 2].lower() == "restorepoints"), None)
            if rp_idx is not None:
                vm_rid = _canonical_id(sub, rg, ["Microsoft.Compute", "virtualMachines"], [chain[1]])
                if self.state.get(vm_rid.lower()) is None:
                    return _err(404, "ResourceNotFound", f"Virtual machine '{chain[1]}' not found.")
                return self._vm_backup(method, sub, vm_rid, chain[rp_idx + 3:], payload)

        # Microsoft.Compute|Network/locations/{location}/usages (Settings > Usage + quotas): a
        # derived read, counted LIVE off real provisioned resources — caught here (same reason as
        # vmSizes above) before the generic alternation would 404 "locations".
        if (namespace.lower() in ("microsoft.compute", "microsoft.network") and chain
                and chain[-1].lower() == "usages" and len(chain) >= 2 and chain[0].lower() == "locations"):
            if method != "GET":
                return _err(405, "MethodNotAllowed", "usages supports GET only.")
            return self._usages(sub, namespace, chain[1])

        # Microsoft.Authorization/permissions ("My permissions"): the actions/notActions
        # DEFAULT_PRINCIPAL holds at this scope, derived from the SAME role assignments/roles
        # checkAccess uses — not a separate store.
        if namespace.lower() == "microsoft.authorization" and chain and chain[0].lower() == "permissions" and len(chain) == 1:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "permissions supports GET only.")
            scope_rid = f"/subscriptions/{sub}/resourceGroups/{rg}" if rg is not None else f"/subscriptions/{sub}"
            return self._my_permissions(sub, scope_rid)

        # Microsoft.Authorization/deploymentCredentials (Settings > Programmatic deployment):
        # Vyomi's own name for this blade's API — generates a real Contributor roleAssignment
        # for a simulated service principal (observable in Access control (IAM), enforced by
        # checkAccess), not a literal mirror of an uncaptured real endpoint.
        if namespace.lower() == "microsoft.authorization" and chain and chain[0].lower() == "deploymentcredentials":
            return self._deployment_credentials(method, sub, rg, chain[1:], payload)

        # Microsoft.Features (Settings > Preview features): feature-flag lifecycle, generic
        # over every resource-provider namespace — not itself a catalog resource type.
        if namespace.lower() == "microsoft.features":
            return self._features(method, sub, chain)

        # Microsoft.PolicyInsights/policyStates (Settings > Policies' Compliance tab): live
        # compliance of every resource in this subscription against every policyAssignment
        # (azure_arm_core._policy_block runs the SAME check at create time to actually enforce it).
        if namespace.lower() == "microsoft.policyinsights":
            return self._policy_states(method, sub, chain, rg, query)
        # Microsoft.Authorization/policyDefinitions: built-ins (by real GUID) alongside custom ones.
        if namespace.lower() == "microsoft.authorization" and chain and chain[0].lower() == "policydefinitions" and method == "GET" and rg is None:
            if len(chain) == 1:
                custom = [_view(r) for r in self.state.values() if r.get("_type", "").lower() == "microsoft.authorization/policydefinitions" and r.get("_sub") == sub]
                return _ok({"value": list(policy_engine.BUILTINS.values()) + custom})
            if len(chain) == 2 and chain[1].lower() in policy_engine.BUILTINS:
                return _ok(policy_engine.BUILTINS[chain[1].lower()])

        # Microsoft.Billing/invoices (Billing > Invoices): derived from the real cost engine —
        # Vyomi keeps no historical cost ledger, so only the current, still-accruing period exists.
        if namespace.lower() == "microsoft.billing" and chain and chain[0].lower() == "invoices":
            if method != "GET":
                return _err(405, "MethodNotAllowed", "invoices supports GET only.")
            return self._invoices(sub)

        # Microsoft.Billing/billingProperties (Settings > Billing properties): real ARM makes
        # this a TENANT-scoped singleton (no /subscriptions/{sub} prefix) — Vyomi keeps it
        # subscription-scoped instead, since it models exactly one subscription anyway and every
        # other ARM entry point here already requires the /subscriptions/{sub} prefix to dispatch.
        if namespace.lower() == "microsoft.billing" and chain and chain[0].lower() == "billingproperties":
            return self._billing_properties(method, payload)

        # Microsoft.Insights/eventtypes/management/values: the subscription-wide ARM activity
        # log read API (not resource-scoped — no "providers" re-entry — so it must be caught
        # before the generic type/name alternation below, which would misparse it).
        if namespace.lower() == "microsoft.insights" and chain and chain[0].lower() == "eventtypes":
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Activity log supports GET only.")
            # One feed, two sources: the per-resource ARM entries this engine records
            # (eventtypes rows in self.state — e.g. Microsoft.Web writes) and the shared cloudsim event log
            # (nano_events — e.g. Event Grid / locks). Newest first, same $filter scoping.
            own = self._activity_log(method, query, sub)["body"].get("value", [])
            shared = _activity_log_query(query)["body"].get("value", [])
            seen = {e.get("id") for e in own}
            events = own + [e for e in shared if e.get("id") not in seen]
            # the timespan picker (eventTimestamp ge/le) narrows BOTH sources
            filt = query.get("$filter") or ""
            since = _parse_odata_ts(m.group(1)) if (m := re.search(r"eventTimestamp\s+ge\s+'([^']*)'", filt)) else None
            until = _parse_odata_ts(m.group(1)) if (m := re.search(r"eventTimestamp\s+le\s+'([^']*)'", filt)) else None
            if since is not None or until is not None:
                def _in_range(e):
                    ts = _parse_odata_ts(str(e.get("eventTimestamp") or ""))
                    return ts is None or ((since is None or ts >= since) and (until is None or ts <= until))
                events = [e for e in events if _in_range(e)]
            # sort by the parsed instant: the two sources write ms vs µs precision, which
            # string order gets wrong ("…47.463Z" > "…47.463441Z")
            _epoch = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
            events.sort(key=lambda e: _parse_odata_ts(str(e.get("eventTimestamp") or "")) or _epoch, reverse=True)
            return _ok({"value": events})

        # Microsoft.ServiceBus/namespaces/{ns}/disasterRecoveryConfigs[/{alias}[/failOver]]:
        # Geo-disaster recovery (paired namespaces + alias failover, 2022-10-01-preview
        # DisasterRecoveryConfigs). A plain nested child of the namespace, but handled here
        # (before the generic type/name alternation) because listing/reading it must also
        # surface the mirrored "Secondary" view on the PARTNER namespace, and failover has to
        # move the stored record's key — the generic engine only knows PUT/GET/DELETE on one
        # fixed id. See _servicebus_georecovery / azure.servicebus.namespace.georecovery.
        if (namespace.lower() == "microsoft.servicebus" and len(chain) >= 3
                and chain[0].lower() == "namespaces" and chain[2].lower() == "disasterrecoveryconfigs"):
            return self._servicebus_georecovery(method, sub, rg, chain, payload)

        # Microsoft.Authorization/locks scoped directly to the RESOURCE GROUP (or, with no
        # resourceGroups segment, the SUBSCRIPTION) itself — not a resource inside it:
        # .../resourceGroups/{rg}/providers/Microsoft.Authorization/locks or
        # .../subscriptions/{sub}/providers/Microsoft.Authorization/locks — namespace IS
        # Microsoft.Authorization already (no resource type precedes it), so the marker search
        # below (which looks for a re-entrant "providers" INSIDE chain) never fires; caught
        # here instead, scope_rid = the resource group's (or subscription's) own id.
        if namespace.lower() == "microsoft.authorization" and chain and chain[0].lower() == "locks":
            scope_rid = f"/subscriptions/{sub}/resourceGroups/{rg}" if rg is not None else f"/subscriptions/{sub}"
            return self._locks_crud(method, scope_rid, chain[1:], payload, rg or sub)

        # Microsoft.Authorization/checkAccess at the resource-group (or subscription) scope
        # itself — the real decision call behind the "Access control (IAM) > Check access" /
        # "My access" tabs: resolves the principal's role assignments AT OR ABOVE this scope
        # against the role's actions/notActions, same wildcard + explicit-deny-wins algorithm
        # azure_iam_core.py's checkAccess uses, applied to THIS store's own roleAssignments
        # (created as real, resource-group-scoped ARM resources — see the generic PUT branch
        # below, which stamps `properties.scope` from the containing resource group).
        if namespace.lower() == "microsoft.authorization" and chain and chain[0].lower() == "checkaccess":
            if method != "POST":
                return _err(405, "MethodNotAllowed", "checkAccess is a POST-only action.")
            scope_rid = f"/subscriptions/{sub}/resourceGroups/{rg}" if rg is not None else f"/subscriptions/{sub}"
            return self._check_access(sub, scope_rid, payload)

        # Microsoft.Authorization/classicAdministrators (subscription scope, GET-only like the real
        # 2015-06-01 API): the legacy co-administrator list. A modern subscription has exactly its
        # Account Administrator / Service Administrator — the one simulated signed-in user.
        if (namespace.lower() == "microsoft.authorization" and chain
                and chain[0].lower() == "classicadministrators" and rg is None and len(chain) == 1):
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Classic administrators can only be listed (the legacy model is retired).")
            return _ok({"value": [{
                "id": f"/subscriptions/{sub}/providers/Microsoft.Authorization/classicAdministrators/admin@vyomi.local",
                "name": "admin@vyomi.local", "type": "Microsoft.Authorization/classicAdministrators",
                "properties": {"emailAddress": "admin@vyomi.local", "role": "ServiceAdministrator;AccountAdministrator"}}]})

        # Microsoft.Authorization/roleDefinitions collection GET: the built-in Owner /
        # Contributor / Reader / … roles (ROLES, core/azure_arm_data.py — never provisioned as
        # catalog records, so the generic engine's own store never carries them) merged with
        # any custom role definitions created via PUT (which DO live in the generic catalog).
        if (namespace.lower() == "microsoft.authorization" and chain
                and chain[0].lower() == "roledefinitions" and len(chain) == 1):
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            return self._role_definitions_list(sub)

        # Microsoft Defender for Cloud (Microsoft.Security): subscription / resource-group scope,
        # computed live over this state (core/azure_security_core.py).
        if namespace.lower() == "microsoft.security":
            return self._security(method, sub, rg, chain, payload, query, None)
        # ...and resource-scoped (.../{type}/{name}/providers/Microsoft.Security/assessments[/…]).
        sec_marker = security_engine.find_marker(chain)
        if sec_marker is not None:
            stc, snames = [namespace], []
            for n, token in enumerate(chain[:sec_marker]):
                (stc if n % 2 == 0 else snames).append(token)
            scope_rid = _canonical_id(sub, rg, stc, snames)
            if self.state.get(scope_rid.lower()) is None:
                return _err(404, "ResourceNotFound", f"Resource '{scope_rid}' not found.")
            return self._security(method, sub, rg, chain[sec_marker + 2:], payload, query, scope_rid)

        # Microsoft.Advisor/recommendations (+ suppressions) and Microsoft.ResourceHealth/
        # availabilityStatuses (subscription / resource-group scope, or re-entering any resource's
        # own id): derived from the stored resources, core/azure_health_core.py.
        if namespace.lower() == "microsoft.advisor" and chain and chain[0].lower() == "recommendations":
            if len(chain) == 1 and method == "GET":
                r = health_engine.recommendations(self.state, sub, query)
            elif len(chain) == 4 and chain[2].lower() == "suppressions":
                r = health_engine.suppress(self.state, sub, chain[1], chain[3], method, payload)
            else:
                return _err(405, "MethodNotAllowed", "Unsupported Advisor recommendations operation.")
            return _ok(r["body"], r["status"]) if r["status"] < 300 else _err(r["status"], r["body"]["error"]["code"], r["body"]["error"]["message"])
        if namespace.lower() == "microsoft.resourcehealth" and chain and chain[0].lower() == "availabilitystatuses":
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Resource health is read-only.")
            scope_rid = f"/subscriptions/{sub}/resourceGroups/{rg}" if rg is not None else None
            r = health_engine.health(self.state, sub, scope_rid, False)
            return _ok(r["body"], r["status"])
        health_marker = health_engine.find_health_marker(chain)
        if health_marker is not None:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Resource health is read-only.")
            stc, snames = [namespace], []
            for n, token in enumerate(chain[:health_marker]):
                (stc if n % 2 == 0 else snames).append(token)
            rest = chain[health_marker + 3:]
            r = health_engine.health(self.state, sub, _canonical_id(sub, rg, stc, snames).lower(), bool(rest) and rest[0].lower() == "current")
            return _ok(r["body"], r["status"]) if r["status"] < 300 else _err(r["status"], r["body"]["error"]["code"], r["body"]["error"]["message"])
        # Microsoft.EventGrid/eventSubscriptions scoped to a resource group / the subscription (system events).
        if namespace.lower() == "microsoft.eventgrid" and chain and chain[0].lower() == "eventsubscriptions":
            scope_rid = f"/subscriptions/{sub}/resourceGroups/{rg}" if rg is not None else f"/subscriptions/{sub}"
            return self._eg_scoped(method, sub, scope_rid, chain[1:], payload)
        # …and scoped to any other (non-topic) resource: storage / key vault / App Configuration / API Management / …
        if not (namespace.lower() == "microsoft.eventgrid" and chain and chain[0].lower() == "topics"):
            _eg_marker = eventgrid_engine.find_scoped_marker(chain)
            if _eg_marker is not None:
                stc, snames = [namespace], []
                for n, token in enumerate(chain[:_eg_marker]):
                    (stc if n % 2 == 0 else snames).append(token)
                return self._eg_scoped(method, sub, _canonical_id(sub, rg, stc, snames), chain[_eg_marker + 3:], payload)

        # Microsoft.Authorization/locks: a real ARM extension resource scoped to ANY other
        # resource's own id (the chain re-enters "providers", like Event Grid's event
        # subscriptions) — generic over every catalog type, so caught before the alternation.
        lock_marker = locks_engine.find_marker(chain)
        if lock_marker is not None:
            return self._locks(method, sub, rg, namespace, chain, lock_marker, payload)

        # Microsoft.Insights/diagnosticSettings: a real ARM extension resource scoped to ANY
        # other resource's own id (chain re-enters "providers", same shape as locks above) —
        # generic over every catalog type, so caught before the alternation too.
        diag_marker = monitor_engine.find_diagnostic_marker(chain)
        if diag_marker is not None:
            return self._diagnostic_settings(method, sub, rg, namespace, chain, diag_marker, payload)

        # Microsoft.Insights/metricDefinitions and metrics: the real Azure Monitor metrics
        # data-plane pass-through, resource-scoped (same re-entrant "providers" shape as
        # diagnostic settings) — generic over every catalog type; storage accounts also expose
        # their real storage metrics (v4 WAVE 5b, monitor_engine.get_metrics + self.blob_store).
        metrics_marker = monitor_engine.find_metrics_marker(chain)
        if metrics_marker is not None:
            return self._metrics(method, sub, rg, namespace, chain, metrics_marker, query)

        # Microsoft.Insights/dataCollectionRuleAssociations: a real ARM extension resource
        # scoped to ANY other resource's own id (same shape as diagnostic settings above) —
        # the "Observability agents (preview)" association behind VM insights data collection.
        dcra_marker = monitor_engine.find_dcra_marker(chain)
        if dcra_marker is not None:
            return self._dcr_associations(method, sub, rg, namespace, chain, dcra_marker, payload)

        # Microsoft.Authorization/roleAssignments: a real ARM extension resource that can be
        # READ scoped to ANY other resource's own id (chain re-enters "providers", same shape
        # as locks/diagnostic settings above) — real Azure's IAM blade lists assignments at that
        # exact scope plus its subscription/resource-group ancestors (inherited access), not the
        # whole subscription. Generic over every catalog type; GET-only (assignments are still
        # CREATED at the subscription scope, matching how az role assignment create/Entra work
        # today — this only narrows the READ for a resource's own IAM blade).
        role_marker = _role_assignment_marker(chain)
        if role_marker is not None:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Use the subscription-scoped roleAssignments path to write.")
            stc, snames = [namespace], []
            for n, token in enumerate(chain[:role_marker]):
                (stc if n % 2 == 0 else snames).append(token)
            scope_rid = _canonical_id(sub, rg, stc, snames).lower()
            ancestors = {scope_rid, f"/subscriptions/{sub}".lower()}
            if rg is not None:
                ancestors.add(f"/subscriptions/{sub}/resourcegroups/{rg}".lower())
            items = [_view(r) for r in self.state.values()
                     if r.get("_type", "").lower() == "microsoft.authorization/roleassignments"
                     and ((r.get("properties") or {}).get("scope") or "").rstrip("/").lower() in ancestors | {""}]
            return _ok({"value": items})

        # Microsoft.Authorization/checkAccess, resource-scoped: same re-entrant shape as the
        # roleAssignments READ above, generic over every catalog type — the decision call
        # behind any resource's own "Check access" / "My access" tab (the dedicated branch
        # near the top of this method only covers the resource-group/subscription scope).
        check_marker = _check_access_marker(chain)
        if check_marker is not None:
            if method != "POST":
                return _err(405, "MethodNotAllowed", "checkAccess is a POST-only action.")
            stc, snames = [namespace], []
            for n, token in enumerate(chain[:check_marker]):
                (stc if n % 2 == 0 else snames).append(token)
            scope_rid = _canonical_id(sub, rg, stc, snames)
            return self._check_access(sub, scope_rid, payload)

        # ARM type path alternates type/name: providers/<ns>/<t1>/<n1>/<t2>/<n2>...
        type_chain = [namespace]
        names: list = []
        for n, token in enumerate(chain):
            if n % 2 == 0:
                type_chain.append(token)
            else:
                names.append(token)
        is_collection = (len(chain) % 2 == 1)

        # Microsoft.AppConfiguration: the substrate-free engine owns the store / key-value semantics;
        # this class's flat store is its resource map (so it persists with the rest of ARM).
        if namespace.lower() in ("microsoft.appconfiguration", "microsoft.cognitiveservices"):
            _pr = netsvc.pec_request(self.state, method, sub, rg, list(chain), payload)
            if _pr is not None:
                return _pr
        if namespace.lower() == "microsoft.appconfiguration":
            return self._appconfig(method, sub, rg, chain, payload, query)

        # Microsoft.ApiManagement/deletedservices: soft-deleted services (restore = PUT service with properties.restore).
        if namespace.lower() == "microsoft.apimanagement" and rg is None and chain and chain[0].lower() in ("deletedservices", "locations"):
            return cfgext.apim_deleted_dispatch(self.state, method, sub, chain, payload)

        # Microsoft.Network/dnsZones (+ record sets): the Azure DNS engine owns the zone semantics.
        if namespace.lower() == "microsoft.network" and dns_engine.handles(chain):
            return self._dns(method, sub, rg, chain, payload, query)

        # Resource-group-scoped metrics (RG blade Metrics tab): ActivityOperations across everything under the group.
        if (namespace.lower() == "microsoft.insights" and rg and len(chain) == 1 and chain[0].lower() in ("metricdefinitions", "metrics")):
            if method != "GET":
                return _err(405, "MethodNotAllowed", "GET required.")
            if self._resource_group_item("GET", sub, rg, None)["status"] != 200:
                return _err(404, "ResourceGroupNotFound", f"Resource group '{rg}' could not be found.")
            scope_rid = f"/subscriptions/{sub}/resourceGroups/{rg}"
            r = (monitor_engine.list_metric_definitions(self.state, scope_rid, self.blob_store, rg_exists=True) if chain[0].lower() == "metricdefinitions"
                 else monitor_engine.get_metrics(self.state, scope_rid, query, self.blob_store, rg_exists=True))
            return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

        # Microsoft.Insights (action groups, metric / activity log alerts, autoscale): the Azure Monitor engine.
        if namespace.lower() == "microsoft.insights" and monitor_engine.handles(chain):
            return self._monitor(method, sub, rg, chain, payload, query)

        # Microsoft.OperationalInsights (Log Analytics workspaces, saved searches, tables, data sources).
        if namespace.lower() == "microsoft.operationalinsights" and oi_engine.handles(chain):
            return self._oi(method, sub, rg, chain, payload, query)

        if namespace.lower() == "microsoft.cognitiveservices":
            return self._cogs(method, sub, rg, chain, payload, query)

        # Microsoft.CostManagement (cost query, alerts, exports) / Microsoft.Consumption
        # (budgets): the Cost Management engine owns both namespaces, sub/RG scoped, no
        # per-resource-group catalog entry (real Cost Management has none either).
        if namespace.lower() == "microsoft.costmanagement":
            return self._cost_cm(method, sub, rg, chain, payload, query)
        if namespace.lower() == "microsoft.consumption":
            return self._cost_consumption(method, sub, rg, chain, payload, query)
        if namespace.lower() == "microsoft.billingbenefits":
            return self._cost_billingbenefits(method, sub, rg, chain, payload, query)
        if namespace.lower() == "microsoft.capacity":
            return self._cost_capacity(method, sub, rg, chain, payload, query)
        # Microsoft.EventGrid/topics/{name}/providers/Microsoft.EventGrid/eventSubscriptions/{name}:
        # a real ARM extension resource (scoped to the topic), so the chain re-enters "providers"
        # instead of alternating type/name — the eventgrid engine owns that shape.
        if namespace.lower() == "microsoft.eventgrid" and eventgrid_engine.handles(chain):
            return self._eventgrid(method, sub, rg, chain, payload, query)

        # Microsoft.Web (App Service: web apps + function apps by `kind`, App Service plans): the
        # substrate-free engine owns the semantics (and writes the Activity log rows the
        # Microsoft.Insights eventtypes feed in the monitor engine reads back); this class's flat
        # store is its resource map (so it persists with the rest of ARM).
        if namespace.lower() == "microsoft.web":
            return self._web(method, sub, rg, chain, payload, query)

        if monprod_engine.handles(namespace, chain):
            return self._monprod(method, sub, rg, namespace, chain, payload, query)

        top = _BY_TYPE.get((namespace.lower(), type_chain[1].lower()))
        if top is None:
            supported = ", ".join(sorted(c["namespace"] + "/" + c["type"] for c in CATALOG))
            return _err(404, "ResourceTypeNotSupported",
                        f"Type '{namespace}/{type_chain[1]}' is not simulated. Supported: {supported}.")

        # Microsoft.App (Container Apps): the substrate-free engine owns the semantics; this
        # class's flat store is its resource map (so it persists with the rest of ARM).
        if namespace.lower() == "microsoft.app":
            return self._app(method, sub, rg, chain, payload, query)

        # Network Watcher diagnostics → the shared netsim evaluator (same engine as Nano + enforcement)
        if (method == "POST" and namespace.lower() == "microsoft.network" and len(chain) == 3
                and chain[0].lower() == "networkwatchers" and chain[2].lower() in (
                    "ipflowverify", "nexthop", "connectivitycheck", "querynetworkconfigurationdiagnostic")):
            if self.state.get(_canonical_id(sub, rg, type_chain[:2], names[:1]).lower()) is None:
                return _err(404, "ResourceNotFound", f"Network watcher '{names[0]}' not found.")
            return self._network_watcher(chain[2].lower(), payload or {})
        # Azure Firewall rule evaluation (simulator action, not a real ARM action): POST .../azureFirewalls/{fw}/evaluate
        if (method == "POST" and namespace.lower() == "microsoft.network" and len(chain) == 3
                and chain[0].lower() == "azurefirewalls" and chain[2].lower() == "evaluate"):
            from core import azure_firewall_eval as _fwe
            fw_id = _canonical_id(sub, rg, type_chain[:2], names[:1])
            if self.state.get(fw_id.lower()) is None:
                return _err(404, "ResourceNotFound", f"Azure Firewall '{names[0]}' not found.")
            return _ok(_fwe.evaluate(self.state, fw_id, payload or {}))
        # POST action verbs (listKeys / start / powerOff / runCommand / …)
        if method == "POST" and is_collection and len(type_chain) >= 3 and names:
            parent_rid = _canonical_id(sub, rg, type_chain[:-1], names)
            return self._arm_action(type_chain[-1].lower(), type_chain, names[-1], parent_rid, payload, sub=sub, rg=rg)

        full_type = "/".join(type_chain)
        if is_collection:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            # Nested child resources (e.g. registries/{reg}/webhooks) alternate type/name one
            # level deeper than their top catalog type — scope the list to the specific parent
            # instance, else two sibling parents' children would bleed into each other's list.
            parent_prefix = _canonical_id(sub, rg, type_chain[:-1], names).lower() + "/" if len(type_chain) > 2 else None
            return self._list(sub, rg, full_type, parent_prefix)

        rid = _canonical_id(sub, rg, type_chain, names)
        key = rid.lower()
        leaf_name = names[-1]
        api_version = query.get("api-version") or top.get("api_version") or "2023-01-01"
        lro = (len(type_chain) == 2 and namespace.lower() != "microsoft.authorization")

        if method == "GET":
            rec = self.state.get(key)
            if not rec:
                rec = _apim_default_policy(type_chain, names, self.state, rid)
            if not rec:
                return _err(404, "ResourceNotFound", f"Resource '{rid}' not found.")
            return _ok(_view(rec))
        if method in ("PUT", "PATCH"):
            blocked = self._lock_block(rid, full_type, for_delete=False)
            if blocked:
                return blocked
            blocked = self._servicebus_tier_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            blocked = self._aks_stopped_block(type_chain, names, sub, rg)
            if blocked:
                return blocked
            blocked = self._aks_namespace_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            blocked = self._storage_encryption_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            blocked = self._storage_hns_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            blocked = self._cosmos_validate_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            blocked = self._apim_tier_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            blocked = self._apim_locations_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            blocked = self._apim_protocol_value_block(type_chain, payload)
            if blocked:
                return blocked
            blocked = self._acr_validate_block(type_chain, names, payload, sub, rg)
            if blocked:
                return blocked
            if full_type.lower() == "microsoft.authorization/policydefinitions":
                _pe = policy_engine.validate_definition(payload)
                if _pe:
                    return _err(400, "InvalidPolicyRule", _pe)
            blocked = self._policy_block(sub, rg, full_type, payload, names[-1] if names else '', self.state.get(key))
            if blocked:
                return blocked
            blocked = self._quota_block(sub, full_type, key, payload)
            if blocked:
                return blocked
            _net_prev = self.state.get(key)
            if netsvc.handles(full_type):
                blocked = netsvc.validate(self.state, full_type, rid, payload, _net_prev, sub, rg)
                if blocked:
                    return blocked
            if netcfg.handles(full_type):
                blocked = netcfg.validate(self.state, full_type, rid, payload, _net_prev, sub, rg)
                if blocked:
                    return blocked
            if cfgext.handles(full_type):
                blocked = cfgext.validate(self.state, full_type, rid, payload, _net_prev, sub, rg)
                if blocked:
                    return blocked
            if sqlbk.handles(full_type):
                blocked = sqlbk.validate(self.state, full_type, rid, payload, _net_prev, sub, rg, self.sql_store)
                if blocked:
                    return blocked
            if full_type.lower() == "microsoft.authorization/roleassignments":
                # Real ARM derives a role assignment's scope from the resource ID it was PUT
                # under — not from a client-supplied properties.scope — so checkAccess and the
                # Role assignments list are genuinely scoped to the resource group they were
                # created at, instead of trusting whatever the caller sent (or sent nothing).
                # A client scope NARROWER than the path (a resource inside this group/subscription —
                # role assignments are written at the subscription/group path here) is kept;
                # anything else (missing, wider, unrelated) becomes the path's own scope.
                payload = dict(payload or {})
                path_scope = f"/subscriptions/{sub}/resourceGroups/{rg}" if rg is not None else f"/subscriptions/{sub}"
                asked = str((payload.get("properties") or {}).get("scope") or "").rstrip("/")
                inside = asked.lower().startswith(path_scope.lower() + "/")
                payload["properties"] = {**(payload.get("properties") or {}),
                                         "scope": asked if inside else path_scope}
            resp = self._upsert(rid, key, full_type, leaf_name, top, payload, base, patch=(method == "PATCH"))
            if resp["status"] >= 300:          # validation error from a type hook (e.g. NIC IP allocation)
                return resp
            if netsvc.handles(full_type) and key in self.state:
                netsvc.after_put(self.state, self.state[key], payload, _net_prev)
                resp["body"] = _view(self.state[key])
            if netcfg.handles(full_type) and key in self.state:
                netcfg.after_put(self.state, self.state[key], payload, _net_prev)
                resp["body"] = _view(self.state[key])
            if cfgext.handles(full_type) and key in self.state:
                cfgext.after_put(self.state, self.state[key], payload, _net_prev)
                resp["body"] = _view(self.state[key])
            if full_type.lower() == "microsoft.storage/storageaccounts" and key in self.state:
                backup_engine.storage_after_put(self.state, self.state[key])
                resp["body"] = _view(self.state[key])
            if sqlbk.handles(full_type) and key in self.state:
                blocked = sqlbk.after_put(self.state, self.state[key], payload, _net_prev, self.sql_store, self.blob_store)
                if blocked:
                    return blocked
                resp["body"] = _view(self.state[key])
            deployment_failed = False
            if full_type.lower() == "microsoft.resources/deployments":
                # A bounded but REAL template evaluator (literal parameter/variable
                # substitution only — no expression language, no dependsOn ordering, no
                # nested/linked templates): every resource listed in properties.template.resources
                # is actually PUT through this same ARM dispatcher, not just stored inert.
                provisioned, errors = self._execute_deployment(sub, rg, self.state[key])
                rec = self.state[key]
                rec["properties"]["outputResources"] = provisioned
                if errors:
                    rec["properties"]["provisioningState"] = "Failed"
                    rec["properties"]["error"] = {"code": "DeploymentFailed", "details": errors}
                    deployment_failed = True
                resp["body"] = _view(rec)
            if full_type.lower() == "microsoft.keyvault/vaults" and resp["status"] == 201:
                # azure.keyvaults.access_configuration / azure.keyvaults.access_policies,
                # ENFORCED by keyvault_access_denied() below: real Azure default-denies a
                # fresh vault's data plane until a role/access-policy entry is explicitly
                # granted, which would lock this console's own create-vault-then-add-a-secret
                # path since nothing else in the product has a signed-in identity to grant one
                # — so, exactly like `az keyvault create` does by default (and unlike a raw
                # ARM/Bicep deploy, which doesn't), self-grant the one simulated signed-in
                # principal full access at creation time.
                rec = self.state[key]
                grant_vault_creator(self.state, rec, rid, sub, rg)
                resp["body"] = _view(rec)
            if full_type.lower() == "microsoft.storage/storageaccounts" and key in self.state:
                storage_ext.apply_endpoints(self.state[key])
                resp["body"] = _view(self.state[key])
            if full_type.lower() == "microsoft.resources/deploymentstacks":
                # Same bounded template evaluator as a plain deployment — but a stack also
                # tracks the resources it manages so DELETE can cascade-delete them for real
                # (actionOnUnmanage.resources: "delete" by default, "detach" to leave them).
                provisioned, errors = self._execute_deployment(sub, rg, self.state[key])
                rec = self.state[key]
                rec["properties"]["resources"] = provisioned
                rec["properties"].setdefault("actionOnUnmanage", {"resources": "delete"})
                if errors:
                    rec["properties"]["provisioningState"] = "Failed"
                    rec["properties"]["error"] = {"code": "DeploymentFailed", "details": errors}
                resp["body"] = _view(rec)
            if lro:
                resp["status"] = 200
                op_id = self._make_operation(rid, method)
                url = f"{base}/api/azure/operations/{op_id}?api-version={api_version}"
                resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
            # One ARM-native eventtypes row per mutation (exact resourceId + real
            # resourceGroupName) — supersedes the generic nano_events feed for this call site,
            # so a resource group's Activity log can aggregate every resource inside it. A real
            # template evaluation failure (deployment_failed above) is the one path in this
            # generic engine that genuinely fails AFTER being accepted, so it is the one real
            # status="Failed" row the Activity log ever carries — the signal Monitor's Issues
            # and Health models pages read back (core/azure_monitor_core.py list_failed_activity).
            self._record_activity(rid, f"{full_type}/write", sub, status="Failed" if deployment_failed else "Succeeded")
            return resp
        if method == "DELETE":
            blocked = self._lock_block(rid, full_type, for_delete=True)
            if blocked:
                return blocked
            blocked = self._aks_stopped_block(type_chain, names, sub, rg)
            if blocked:
                return blocked
            if full_type.lower() == "microsoft.resources/deploymentstacks":
                stack = self.state.get(key)
                action = str((query or {}).get("unmanageAction.Resources") or ((stack or {}).get("properties") or {}).get("actionOnUnmanage", {}).get("resources", "delete")).lower()
                if stack and action != "detach":
                    for pr in (stack.get("properties") or {}).get("resources") or []:
                        pid = (pr.get("id") or "").lower()
                        if pid and pid != key:
                            self.state.pop(pid, None)
            _net_rec = self.state.get(key)
            if _net_rec is not None:
                blocked = netsvc.before_delete(self.state, _net_rec) or netcfg.before_delete(self.state, _net_rec)
                if blocked:
                    return blocked
                if cfgext.handles(_net_rec.get("_type") or ""):
                    blocked = cfgext.before_delete(self.state, _net_rec)
                    if blocked:
                        return blocked
                if sqlbk.handles(_net_rec.get("_type") or ""):
                    blocked = sqlbk.before_delete(self.state, _net_rec)
                    if blocked:
                        return blocked
            rec = self.state.pop(key, None)
            if rec is not None and sqlbk.handles(rec.get("_type") or ""):
                sqlbk.on_delete(self.state, rec, self.sql_store, self.blob_store)
            if rec is not None:
                if rec.get("_ipam_alloc"):
                    self._release_ipam_pool(rec["_ipam_alloc"])
                # Both extension resources (locks, … keyed "{parent id}/providers/<ext ns>/…")
                # and plain nested children (e.g. managedClusters/{c}/agentPools/{p}, keyed
                # "{parent id}/agentPools/{p}") cascade-delete with their parent in real ARM —
                # but NOT its own Activity log rows ("/__event__/" keys): real Azure keeps a
                # deleted resource's history in the log, it doesn't erase it.
                prefix = key + "/"
                for child_key in [k for k in self.state if k.startswith(prefix) and "/__event__/" not in k]:
                    del self.state[child_key]
                netsvc.on_delete(self.state, rec)
                netcfg.on_delete(self.state, rec)
                self._record_activity(rid, f"{full_type}/delete", sub)
            return _ok(None, status=200 if rec is not None else 204)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")

    # ── Policy enforcement (Settings > Policies): the one built-in Vyomi actually evaluates,
    # by its real GUID (POLICY_ALLOWED_LOCATIONS_ID) — a policyAssignment referencing it denies
    # any catalog resource PUT whose location isn't in its listOfAllowedLocations parameter.
    # Custom policyRule JSON is stored (generic catalog CRUD) but not evaluated — "limited". ──
    def _policy_assignments_for(self, sub, rg):
        out = []
        for r in self.state.values():
            if r.get("_type", "").lower() != "microsoft.authorization/policyassignments" or r.get("_sub") != sub:
                continue
            rec_rg = r.get("_rg")
            if rec_rg is not None and (rg is None or rec_rg.lower() != rg.lower()):
                continue
            if str((r.get("properties") or {}).get("enforcementMode", "Default")).lower() == "donotenforce":
                continue
            out.append(r)
        return out

    def _policy_skip(self, defn, res):
        """Allowed-locations never applies to region-less / global resources (budgets, role records…)."""
        loc = str(res.get("location") or "").lower()
        if (defn or {}).get("name", "").lower() == policy_engine.ALLOWED_LOCATIONS_ID and (not loc or loc == "global"):
            return True
        return False

    def _policy_block(self, sub, rg, full_type, payload, name="", existing=None):
        ft = full_type.lower()
        if ft in ("microsoft.authorization/policyassignments", "microsoft.authorization/policydefinitions",
                  "microsoft.resources/resourcegroups") or ft.startswith("microsoft.authorization/"):
            return None
        pl = payload or {}
        res = {"type": full_type, "name": name, "location": pl.get("location") or (existing or {}).get("location"),
               "kind": pl.get("kind") or (existing or {}).get("kind"), "tags": pl.get("tags") if "tags" in pl else (existing or {}).get("tags") or {},
               "properties": {**((existing or {}).get("properties") or {}), **(pl.get("properties") or {})},
               "sku": pl.get("sku") or (existing or {}).get("sku"), "identity": pl.get("identity") or (existing or {}).get("identity")}
        for r in self._policy_assignments_for(sub, rg):
            defn = policy_engine.find_definition(self.state, sub, (r.get("properties") or {}).get("policyDefinitionId"))
            if not defn or self._policy_skip(defn, res):
                continue
            st, eff = policy_engine.evaluate(defn, r, res)
            if st == "NonCompliant" and eff == "deny":
                props = r.get("properties") or {}
                allowed = ((props.get("parameters") or {}).get("listOfAllowedLocations") or {}).get("value")
                if defn.get("name", "").lower() == policy_engine.ALLOWED_LOCATIONS_ID and allowed:
                    msg = (f"Resource '{str(res.get('location')).lower()}' location is not permitted by the policy assignment "
                           f"'{r.get('name')}'. Allowed locations: {', '.join(str(x).lower() for x in allowed)}.")
                else:
                    msg = (f"Resource '{name}' was disallowed by policy. Policy identifiers: "
                           f"'[{{\"policyAssignment\":{{\"name\":\"{r.get('name')}\",\"id\":\"{r.get('id')}\"}},"
                           f"\"policyDefinition\":{{\"name\":\"{(defn.get('properties') or {}).get('displayName') or defn.get('name')}\"}}}}]'.")
                return _err(403, "RequestDisallowedByPolicy", msg)
        return None

    # ── Quota enforcement (Settings > Usage + quotas): counted LIVE off real provisioned
    # resources, on the same reduced subset (COMPUTE_QUOTA/NETWORK_QUOTA) the report shows. ──
    def _vm_cores(self, rec_or_payload):
        size = ((rec_or_payload or {}).get("properties") or {}).get("hardwareProfile", {}).get("vmSize") or "Standard_B1s"
        return instance_catalog.lookup_azure(size).get("vcpu", 1)

    # ── v4 AZ-08: engines that own their namespace; returns None when the path is not theirs ──
    def _az08(self, method, sub, rg, namespace, chain, payload, query):
        ns = namespace.lower()
        low = [c.lower() for c in chain]
        if files_engine.handles(namespace, chain) and rg is not None:
            r = files_engine.dispatch(self.state, method, sub, rg, chain, payload, query)
            return {"status": r["status"], "headers": {}, "body": r["body"]}
        if ns == "microsoft.search":
            r = search_engine.dispatch(self.state, method, sub, rg, chain, payload, query, blob_store=self.blob_store, base=self._base)
            return {"status": r["status"], "headers": {}, "body": r["body"]}
        if ns == "microsoft.storagemover" and (rg is not None or len(chain) == 1):
            r = mover_engine.dispatch(self.state, method, sub, rg, chain, payload, query, blob_store=self.blob_store, base=self._base)
            return {"status": r["status"], "headers": {}, "body": r["body"]}
        if ns == "microsoft.storage" and rg is not None and len(chain) == 3 and chain[0].lower() == "storageaccounts" and chain[2].lower() == "failover" and method == "POST":
            rec = self.state.get(f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts/{chain[1]}".lower())
            if rec is None:
                return _err(404, "ResourceNotFound", f"The Resource 'Microsoft.Storage/storageAccounts/{chain[1]}' under resource group '{rg}' was not found.")
            r = backup_engine.storage_failover(self.state, rec, query or {})
            return {"status": r["status"], "headers": {}, "body": r["body"]}
        if ns == "microsoft.sql" and chain and sqlbk.owns(chain) and (rg is not None or chain[0].lower() == "locations"):
            r = sqlbk.dispatch(self.state, method, sub, rg, chain, payload, query, sql_store=self.sql_store, blob_store=self.blob_store)
            return {"status": r["status"], "headers": {}, "body": r["body"]}
        if ns == "microsoft.recoveryservices" and (rg is not None or len(chain) == 1 or (chain and chain[0].lower() == "locations")):
            r = backup_engine.dispatch(self.state, method, sub, rg, chain, payload, query, blob_store=self.blob_store, base=self._base,
                                       arm_put=lambda rid, api, body: self.handle("PUT", rid, {"api-version": api}, body))
            return {"status": r["status"], "headers": r.get("headers") or {}, "body": r["body"]}
        if ns == "microsoft.marketplace":
            r = market_engine.catalog(chain, query)
            return {"status": r["status"], "headers": {}, "body": r["body"]}
        if ns == "microsoft.saas":
            r = market_engine.saas_dispatch(self.state, method, sub, rg, chain, payload)
            return {"status": r["status"], "headers": {}, "body": r["body"]}
        if ns == "microsoft.managementpartner" and chain and low[0] == "partners":
            r = billing_ext.partner_dispatch(self.state, method, sub, chain[1:], payload)
            return {"status": r["status"], "headers": {}, "body": r["body"]}
        if ns == "microsoft.subscription" and chain and low[0] == "managementcertificates":
            r = billing_ext.certs_dispatch(self.state, method, sub, chain[1:], payload)
            return {"status": r["status"], "headers": {}, "body": r["body"]}
        if ns == "microsoft.billing" and chain and low[0] in ("transferrequests", "freeservices", "costsaved", "invoices"):
            if low[0] == "transferrequests":
                self.billing_properties.setdefault("accountAdmin", DEFAULT_PRINCIPAL)
                r = billing_ext.transfers_dispatch(self.state, method, sub, chain[1:], payload, self.billing_properties)
            elif method != "GET":
                return _err(405, "MethodNotAllowed", f"{chain[0]} supports GET only.")
            elif low[0] == "freeservices":
                r = _ok_(billing_ext.free_services(self.state, sub, self.blob_store))
            elif low[0] == "costsaved":
                r = _ok_(billing_ext.cost_saved(self.state, sub))
            else:
                invs = billing_ext.invoices(self.state, sub)
                if len(chain) > 1:
                    inv = next((i for i in invs if i["name"].lower() == chain[1].lower()), None)
                    r = _ok_(inv) if inv else {"status": 404, "body": {"error": {"code": "ResourceNotFound", "message": f"Invoice '{chain[1]}' was not found."}}}
                else:
                    r = _ok_({"value": invs})
            return {"status": r["status"], "headers": {}, "body": r["body"]}
        if ns == "microsoft.quota" and chain and low[0] == "quotarequests":
            rows = [billing_ext._view(x) for x in self.state.values() if isinstance(x, dict)
                    and str(x.get("_type", "")).lower() == "microsoft.quota/quotarequests" and x.get("_sub") == sub]
            return _ok({"value": list(reversed(rows))})
        if ns in ("microsoft.compute", "microsoft.network") and len(chain) >= 5 and low[0] == "locations" \
                and low[2] == "providers" and low[3] == "microsoft.quota":
            loc = chain[1].lower()
            usage = {u["name"]["value"]: u["currentValue"] for u in self._usages(sub, namespace, loc)["body"]["value"]}
            defaults = COMPUTE_QUOTA if ns == "microsoft.compute" else NETWORK_QUOTA
            r = billing_ext.quota_dispatch(self.state, method, sub, namespace, loc, chain[4:], payload, lambda n: usage.get(n, 0), defaults)
            return {"status": r["status"], "headers": {}, "body": r["body"]}
        return None

    def _quota_err(self, label, loc, limit):
        return _err(403, "QuotaExceeded",
                    f"Operation results in exceeding approved {label} quota (limit {limit}) in "
                    f"location '{loc}'. Request an increase from Settings > Usage + quotas.")

    def _quota_block(self, sub, full_type, key, payload):
        if key in self.state:
            return None   # an update, not a new allocation
        ft = full_type.lower()
        loc = str((payload or {}).get("location") or DEFAULT_LOCATION).lower()
        if ft == "microsoft.compute/virtualmachines":
            vms = [r for r in self.state.values() if r.get("_type", "").lower() == ft
                   and r.get("_sub") == sub and str(r.get("location", "")).lower() == loc]
            limit_vms = billing_ext.limit_for(self.state, sub, "Microsoft.Compute", loc, "virtualMachines", next(l for n, _, l in COMPUTE_QUOTA if n == "virtualMachines"))
            if len(vms) + 1 > limit_vms:
                return self._quota_err("Virtual Machines", loc, limit_vms)
            limit_cores = billing_ext.limit_for(self.state, sub, "Microsoft.Compute", loc, "cores", next(l for n, _, l in COMPUTE_QUOTA if n == "cores"))
            if sum(self._vm_cores(r) for r in vms) + self._vm_cores(payload) > limit_cores:
                return self._quota_err("Total Regional vCPUs", loc, limit_cores)
        elif ft == "microsoft.network/publicipaddresses":
            cnt = sum(1 for r in self.state.values() if r.get("_type", "").lower() == ft
                      and r.get("_sub") == sub and str(r.get("location", "")).lower() == loc)
            limit = billing_ext.limit_for(self.state, sub, "Microsoft.Network", loc, "PublicIPAddresses", next(l for n, _, l in NETWORK_QUOTA if n == "PublicIPAddresses"))
            if cnt + 1 > limit:
                return self._quota_err("Public IP Addresses", loc, limit)
        return None

    def _usage_row(self, name, label, used, limit, resource_names):
        # "resources" isn't part of real Azure's usages shape — Vyomi adds it so the live count
        # is independently verifiable (and the UI-conformance liveness probe has a resource
        # name, created over the native wire, to look for).
        return {"name": {"value": name, "localizedValue": label}, "unit": "Count",
                "currentValue": used, "limit": limit, "resources": sorted(n for n in resource_names if n)}

    def _usages(self, sub, namespace, location):
        loc = str(location or DEFAULT_LOCATION).lower()
        rows = []
        if namespace.lower() == "microsoft.compute":
            vms = [r for r in self.state.values() if r.get("_type", "").lower() == "microsoft.compute/virtualmachines"
                   and r.get("_sub") == sub and str(r.get("location", "")).lower() == loc]
            names = [r.get("name") for r in vms]
            cores_used = sum(self._vm_cores(r) for r in vms)
            for name, label, limit in COMPUTE_QUOTA:
                used = cores_used if name == "cores" else len(vms)
                rows.append(self._usage_row(name, label, used, billing_ext.limit_for(self.state, sub, "Microsoft.Compute", loc, name, limit), names))
        else:
            tmap = {"microsoft.network/publicipaddresses": "PublicIPAddresses",
                    "microsoft.network/virtualnetworks": "VirtualNetworks",
                    "microsoft.network/networksecuritygroups": "NetworkSecurityGroups"}
            buckets = {label: [] for _, label, _ in [(0, v, 0) for v in tmap.values()]}
            for r in self.state.values():
                if r.get("_sub") != sub or str(r.get("location", "")).lower() != loc:
                    continue
                k = tmap.get(r.get("_type", "").lower())
                if k:
                    buckets[k].append(r.get("name"))
            for name, label, limit in NETWORK_QUOTA:
                rows.append(self._usage_row(name, label, len(buckets[name]), billing_ext.limit_for(self.state, sub, "Microsoft.Network", loc, name, limit), buckets[name]))
        return _ok({"value": rows})

    # ── My permissions (Microsoft.Authorization/permissions): the actions/notActions
    # DEFAULT_PRINCIPAL holds at a scope, derived from the SAME role catalog/assignments
    # checkAccess uses — absent any explicit assignment it defaults to Owner, matching the
    # Overview tab's hardcoded "My role: Owner". ──
    def _my_permissions(self, sub, scope_rid):
        roles = self._role_catalog(sub)
        actions, not_actions, matched = set(), set(), False
        for rec in self._role_assignments(sub):
            props = rec.get("properties") or {}
            if props.get("principalId") != DEFAULT_PRINCIPAL:
                continue
            if not iam_engine._scope_covers(props.get("scope", "/"), scope_rid):
                continue
            matched = True
            if str(props.get("kind", "allow")).lower() == "deny":
                continue
            role_name = props.get("roleName") or (props.get("roleDefinitionId") or "").rsplit("/", 1)[-1]
            role = roles.get(role_name)
            if not role:
                continue
            actions.update(role["actions"])
            not_actions.update(role["notActions"])
        if not matched:
            actions = {"*"}
        return _ok({"value": [{"actions": sorted(actions), "notActions": sorted(not_actions),
                               "dataActions": [], "notDataActions": []}]})

    # ── Policies compliance (Microsoft.PolicyInsights/policyStates): re-runs the SAME
    # allowed-locations check _policy_block enforces at create time, over every existing
    # resource, for the Policies blade's Compliance tab. ──
    def _policy_states(self, method, sub, chain, rg=None, query=None):
        low = [c.lower() for c in chain]
        if not low or low[0] != "policystates":
            return _err(404, "NotFound", "Only policyStates/latest/queryResults is simulated.")
        if method != "POST":
            return _err(405, "MethodNotAllowed", "Use POST for policyStates queryResults.")
        assignments = [r for r in self.state.values()
                       if r.get("_type", "").lower() == "microsoft.authorization/policyassignments" and r.get("_sub") == sub]
        only = str((query or {}).get("$filter") or "").lower()
        results = []
        for key, rec in self.state.items():
            rtype = rec.get("_type", "").lower()
            loc = str(rec.get("location") or "").lower()
            if (rec.get("_sub") != sub or "/__event__/" in key or rtype == "microsoft.resources/resourcegroups"
                    or rtype.startswith("microsoft.authorization") or rtype.startswith("microsoft.resources/")
                    or (rg and (rec.get("_rg") or "").lower() != rg.lower())):
                continue
            if only and only.split("'")[1:2] and only.split("'")[1] not in str(rec.get("id", "")).lower():
                continue
            res = {"type": rec.get("_type"), "name": rec.get("name"), "location": rec.get("location"), "kind": rec.get("kind"),
                   "tags": rec.get("tags") or {}, "properties": rec.get("properties") or {}, "sku": rec.get("sku"), "identity": rec.get("identity")}
            for a in assignments:
                arg = a.get("_rg")
                if arg is not None and (rec.get("_rg") or "").lower() != arg.lower():
                    continue
                props = a.get("properties") or {}
                defid = str(props.get("policyDefinitionId") or "")
                defn = policy_engine.find_definition(self.state, sub, defid)
                if not defn or self._policy_skip(defn, res):
                    continue
                st, eff = policy_engine.evaluate(defn, a, res)
                if st == "Disabled":
                    continue
                state = {"Compliant": "Compliant", "NonCompliant": "NonCompliant"}.get(st, "NotStarted")
                results.append({"resourceId": rec.get("id"), "resourceType": rec.get("_type"), "resourceGroup": rec.get("_rg"),
                                "policyAssignmentId": a.get("id"), "policyAssignmentName": a.get("name"),
                                "policyDefinitionId": defid, "policyDefinitionName": (defn.get("properties") or {}).get("displayName") or defn.get("name"),
                                "policyDefinitionAction": eff or None, "complianceState": state,
                                "isCompliant": state == "Compliant"})
        return _ok({"@odata.count": len(results), "value": results})

    # ── Invoices (Microsoft.Billing/invoices): derived from the real cost engine — Vyomi keeps
    # no historical cost ledger (every cost query recomputes live), so only the current,
    # still-accruing period exists, honestly marked "InProgress" rather than a fabricated
    # archive of past, finalized invoices. ──
    def _invoices(self, sub):
        q = cost_engine.run_cost_query(self.state, sub, None, {
            "type": "ActualCost", "timeframe": "MonthToDate",
            "dataset": {"aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}}}})
        rows = (q.get("properties") or {}).get("rows") or [[0]]
        total = rows[0][0] if rows else 0
        period = _now()[:7]
        name = f"{period}-estimate"
        return _ok({"value": [{
            "id": f"/subscriptions/{sub}/providers/Microsoft.Billing/invoices/{name}", "name": name,
            "type": "Microsoft.Billing/invoices",
            "properties": {"invoicePeriodStartDate": f"{period}-01", "status": "InProgress",
                           "amountDue": {"currency": "USD", "value": total},
                           "billedAmount": {"currency": "USD", "value": total},
                           "documentType": "Invoice"},
        }]})

    # ── Billing properties (Microsoft.Billing/billingProperties, kept subscription-scoped —
    # see the PUT branch's comment): the one field real PATCH/GET round-trips here —
    # "Account admin". ──
    def _billing_properties(self, method, payload):
        if method not in ("GET", "PATCH"):
            return _err(405, "MethodNotAllowed", "billingProperties supports GET/PATCH.")
        if method == "PATCH":
            admin = (payload or {}).get("accountAdmin")
            if admin:
                self.billing_properties["accountAdmin"] = admin
        return _ok({"id": "/providers/Microsoft.Billing/billingProperties", "name": "billingProperties",
                   "type": "Microsoft.Billing/billingProperties", "accountAdmin": self.billing_properties.get("accountAdmin", DEFAULT_PRINCIPAL),
                   "currency": "USD", "channel": "PayAsYouGo", "cloudType": "Public",
                   "billingAccountId": DEFAULT_SUBSCRIPTION})

    # ── Preview features (Microsoft.Features/providers/{ns}/features): register/unregister
    # lifecycle, persisted exactly like real ARM. ──
    def _features(self, method, sub, chain):
        low = [c.lower() for c in chain]
        store = self.feature_state.setdefault(sub.lower(), {})

        def view(ns, name):
            full = f"{ns}/{name}"
            return {"id": f"/subscriptions/{sub}/providers/Microsoft.Features/providers/{ns}/features/{name}",
                    "name": full, "type": "Microsoft.Features/providers/features",
                    "properties": {"state": store.get(full.lower(), "NotRegistered")}}

        if not low:
            return _err(400, "BadRequest", "Missing Microsoft.Features resource.")
        if low[0] == "features" and len(chain) == 1:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "features supports GET only.")
            return _ok({"value": [view(ns, nm) for ns, nm in PREVIEW_FEATURES]})
        if low[0] == "providers" and len(chain) >= 2:
            ns = chain[1]
            avail = [nm for n2, nm in PREVIEW_FEATURES if n2.lower() == ns.lower()]
            if len(chain) == 2 or (len(chain) == 3 and low[2] == "features"):
                if method != "GET":
                    return _err(405, "MethodNotAllowed", "features supports GET only.")
                return _ok({"value": [view(ns, nm) for nm in avail]})
            if len(chain) >= 4 and low[2] == "features":
                name = chain[3]
                if name not in avail:
                    return _err(404, "NotFound", f"Feature '{ns}/{name}' is not simulated.")
                if len(chain) == 4:
                    if method != "GET":
                        return _err(405, "MethodNotAllowed", "features supports GET only.")
                    return _ok(view(ns, name))
                if len(chain) == 5 and low[4] in ("register", "unregister"):
                    if method != "POST":
                        return _err(405, "MethodNotAllowed", "register/unregister is POST-only.")
                    store[f"{ns}/{name}".lower()] = "Registered" if low[4] == "register" else "NotRegistered"
                    return _ok(view(ns, name))
        return _err(404, "NotFound", "Unknown Microsoft.Features path.")

    # ── Programmatic deployment credentials (Settings > Programmatic deployment): generates a
    # real Contributor roleAssignment for a simulated service principal — observable in Access
    # control (IAM) and enforced by checkAccess, not inert stored config. Vyomi's own API shape
    # (the real blade's exact wire call was never captured); no Entra token endpoint exists for
    # the returned secret to actually redeem, which the capability registry's limitations note. ──
    def _deployment_credentials(self, method, sub, rg, rest, payload):
        scope_rid = f"/subscriptions/{sub}/resourceGroups/{rg}" if rg is not None else f"/subscriptions/{sub}"
        store = self.deployment_credentials.setdefault(sub.lower(), {})
        if not rest:
            if method == "GET":
                return _ok({"value": [{k: v for k, v in rec.items() if k != "secret"} for rec in store.values()]})
            if method == "POST":
                name = f"sp-{uuid.uuid4().hex[:8]}"
                app_id, secret, ra_name = str(uuid.uuid4()), uuid.uuid4().hex, str(uuid.uuid4())
                ra_key = f"{scope_rid}/providers/microsoft.authorization/roleassignments/{ra_name}".lower()
                self.state[ra_key] = {
                    "id": f"{scope_rid}/providers/Microsoft.Authorization/roleAssignments/{ra_name}", "name": ra_name,
                    "type": "Microsoft.Authorization/roleAssignments", "_type": "microsoft.authorization/roleassignments",
                    "_sub": sub, "_rg": rg, "tags": {},
                    "properties": {"roleName": "Contributor", "principalId": app_id,
                                   "principalType": "ServicePrincipal", "scope": scope_rid},
                }
                rec = {"name": name, "appId": app_id, "secret": secret,
                       "tenantId": "00000000-0000-0000-0000-000000000000",
                       "scope": scope_rid, "roleAssignmentName": ra_name, "createdAt": _now()}
                store[name] = rec
                return _ok(rec, status=201)
            return _err(405, "MethodNotAllowed", f"{method} not allowed.")
        name = rest[0]
        if method == "DELETE":
            rec = store.pop(name, None)
            if rec:
                self.state.pop(f"{rec['scope']}/providers/microsoft.authorization/roleassignments/{rec['roleAssignmentName']}".lower(), None)
            return _ok(None, status=200 if rec else 204)
        if method == "GET":
            rec = store.get(name)
            if not rec:
                return _err(404, "NotFound", f"Deployment credential '{name}' not found.")
            return _ok({k: v for k, v in rec.items() if k != "secret"})
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")

    def _lock_block(self, rid, full_type, for_delete):
        # Enforcement is scoped to Microsoft.ServiceBus (namespaces/queues/topics) and
        # Microsoft.EventGrid/topics only — every other resource type in this generic engine
        # still leaves Microsoft.Authorization/locks config_only (stored, not enforced),
        # matching their own capability registries.
        ft = full_type.lower()
        # Deployment stack deny settings: a resource MANAGED by a stack whose denySettings.mode is
        # denyDelete / denyWriteAndDelete cannot be deleted (and, for denyWriteAndDelete, written) directly.
        if ft != "microsoft.resources/deploymentstacks":
            for st in self.state.values():
                if st.get("_type", "").lower() != "microsoft.resources/deploymentstacks":
                    continue
                mode = str(((st.get("properties") or {}).get("denySettings") or {}).get("mode") or "none").lower()
                if mode in ("none", "") or (mode == "denydelete" and not for_delete):
                    continue
                if any(str(m.get("id") or "").lower() == rid.lower() for m in (st.get("properties") or {}).get("resources") or []):
                    return _err(403, "DenyAssignmentAuthorizationFailed",
                                f"The client does not have permission to perform this action on '{rid}': it is managed by deployment stack '{st.get('name')}' "
                                f"with deny settings mode '{(st.get('properties') or {}).get('denySettings', {}).get('mode')}'.")
        if not (ft.startswith("microsoft.servicebus/") or ft == "microsoft.eventgrid/topics"):
            return None
        levels = {(r.get("properties") or {}).get("level")
                  for r in self.state.values() if r.get("_lock_scope") == rid.lower()}
        if not levels:
            return None
        if for_delete or "ReadOnly" in levels:
            verb = "delete" if for_delete else "write"
            return _err(409, "ScopeLocked",
                        f"The scope '{rid}' cannot perform {verb} operation because the "
                        f"following scope(s) are locked: '{rid}'. Please remove the lock and try again.")
        return None

    def _servicebus_tier_block(self, type_chain, names, payload, sub, rg):
        # Real Service Bus rejects topics and session/duplicate-detection queues on a Basic
        # namespace, and messaging units / partitions are a Premium-only field — Vyomi now
        # ENFORCES those tier limits instead of just round-tripping whatever sku/properties
        # the caller sends (azure.servicebus.namespace.scale).
        if type_chain[0].lower() != "microsoft.servicebus" or type_chain[1].lower() != "namespaces":
            return None
        props = (payload or {}).get("properties") or {}
        if len(type_chain) == 2:
            existing = self.state.get(_canonical_id(sub, rg, type_chain, names).lower())
            sku = (payload or {}).get("sku") or {}
            tier = sku.get("tier") or sku.get("name") or (existing or {}).get("sku", {}).get("tier")
            if tier != "Premium":
                if sku.get("capacity") is not None:
                    return _err(400, "BadRequest",
                                "Messaging units (sku.capacity) require a Premium namespace.")
                if props.get("premiumMessagingPartitions") is not None:
                    return _err(400, "BadRequest",
                                "premiumMessagingPartitions requires a Premium namespace.")
            return None
        if len(type_chain) == 3 and type_chain[2].lower() in ("queues", "topics"):
            parent = self.state.get(_canonical_id(sub, rg, type_chain[:-1], names[:-1]).lower())
            tier = (parent or {}).get("sku", {}).get("tier")
            if tier != "Basic":
                return None
            if type_chain[2].lower() == "topics":
                return _err(400, "BadRequest",
                            "Topics are not supported on a Basic-tier Service Bus namespace.")
            if props.get("requiresSession"):
                return _err(400, "BadRequest",
                            "Sessions are not supported on a Basic-tier Service Bus namespace.")
            if props.get("requiresDuplicateDetection"):
                return _err(400, "BadRequest",
                            "Duplicate detection is not supported on a Basic-tier Service Bus namespace.")
        return None

    _SB_DR_TYPE = "microsoft.servicebus/namespaces/disasterrecoveryconfigs"

    def _servicebus_georecovery(self, method, sub, rg, chain, payload):
        """Microsoft.ServiceBus/namespaces/{ns}/disasterRecoveryConfigs — Geo-disaster
        recovery (paired namespaces + alias failover). ENFORCED: both namespaces of a pairing
        must exist, be different, and be Premium tier (real Geo-DR requirement); FailOver
        actually moves the Primary role to the partner (azure.servicebus.namespace.georecovery)
        — no message data moves with it, since this simulator's Service Bus data plane is one
        store shared by every namespace (azure.servicebus.queue.explorer) and has nothing of
        its own to replicate per namespace.

        Only ONE record is ever stored per pairing, keyed under whichever namespace currently
        holds the Primary role — the Secondary's own list/get is a derived, read-only mirror
        (found by scanning for a record whose partnerNamespace is this namespace's id), so
        failover never leaves a stale duplicate behind."""
        ns_name = chain[1]
        ns_rid = _canonical_id(sub, rg, ["Microsoft.ServiceBus", "namespaces"], [ns_name])
        ns_rec = self.state.get(ns_rid.lower())
        if ns_rec is None:
            return _err(404, "ResourceNotFound", f"Namespace '{ns_name}' not found.")
        rest = chain[3:]

        def own_records():
            prefix = ns_rid.lower() + "/disasterrecoveryconfigs/"
            return [r for k, r in self.state.items() if k.startswith(prefix) and "/__event__/" not in k]

        def mirrored_records():
            # this namespace is someone else's partnerNamespace: show their record back as our
            # own Secondary-role view (never stored — always derived from the Primary's record).
            out = []
            for r in self.state.values():
                if (r.get("_type") or "") != self._SB_DR_TYPE:
                    continue
                if str((r.get("properties") or {}).get("partnerNamespace") or "").lower() != ns_rid.lower():
                    continue
                v = _view(r)
                v["id"] = f"{ns_rid}/disasterRecoveryConfigs/{r['name']}"
                v["properties"] = {**v["properties"], "role": "Secondary", "partnerNamespace": r["id"]}
                out.append(v)
            return out

        if not rest:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            return _ok({"value": [_view(r) for r in own_records()] + mirrored_records()})

        alias = rest[0]
        rid = f"{ns_rid}/disasterRecoveryConfigs/{alias}"
        key = rid.lower()

        if len(rest) >= 2 and rest[1].lower() == "failover":
            if method != "POST":
                return _err(405, "MethodNotAllowed", "failOver is a POST-only action.")
            rec = self.state.get(key)
            mirror = next((m for m in mirrored_records() if m["name"].lower() == alias.lower()), None)
            if rec is None and mirror is None:
                return _err(404, "ResourceNotFound", f"Disaster recovery config '{alias}' not found.")
            if rec is not None:
                return _err(400, "BadRequest",
                            "FailOver must be called on the SECONDARY namespace's alias, not the primary's.")
            # mirror != None: this namespace is the Secondary — promote it to Primary, demote
            # the old primary to the new Secondary end of the (now reversed) pairing.
            old_primary_rid = mirror["properties"]["partnerNamespace"].rsplit("/disasterRecoveryConfigs/", 1)[0]
            old_key = f"{old_primary_rid}/disasterRecoveryConfigs/{alias}".lower()
            del self.state[old_key]
            new_rec = {"id": rid, "name": alias, "type": "Microsoft.ServiceBus/namespaces/disasterRecoveryConfigs",
                      "_type": self._SB_DR_TYPE,
                      "properties": {"provisioningState": "Succeeded", "role": "Primary",
                                     "partnerNamespace": old_primary_rid, "pendingReplicationOperationsCount": 0}}
            self.state[key] = new_rec
            self._record_activity(rid, f"{self._SB_DR_TYPE}/failOver/action", sub)
            return _ok(_view(new_rec))

        if method == "GET":
            rec = self.state.get(key)
            if rec is not None:
                return _ok(_view(rec))
            mirror = next((m for m in mirrored_records() if m["name"].lower() == alias.lower()), None)
            if mirror is not None:
                return _ok(mirror)
            return _err(404, "ResourceNotFound", f"Disaster recovery config '{alias}' not found.")

        if method == "PUT":
            partner_id = str(((payload or {}).get("properties") or {}).get("partnerNamespace") or "")
            partner_rec = self.state.get(partner_id.lower())
            if not partner_id or partner_rec is None:
                return _err(400, "BadRequest", "properties.partnerNamespace must reference an existing Service Bus namespace.")
            if partner_id.lower() == ns_rid.lower():
                return _err(400, "BadRequest", "A namespace cannot be paired with itself.")
            if (ns_rec.get("sku") or {}).get("tier") != "Premium" or (partner_rec.get("sku") or {}).get("tier") != "Premium":
                return _err(400, "BadRequest", "Geo-disaster recovery pairing requires both namespaces to be Premium tier.")
            if own_records() or mirrored_records():
                return _err(400, "BadRequest", f"Namespace '{ns_name}' is already part of a disaster recovery pairing.")
            rec = {"id": rid, "name": alias, "type": "Microsoft.ServiceBus/namespaces/disasterRecoveryConfigs",
                  "_type": self._SB_DR_TYPE,
                  "properties": {"provisioningState": "Succeeded", "role": "Primary",
                                 "partnerNamespace": partner_id, "pendingReplicationOperationsCount": 0}}
            self.state[key] = rec
            self._record_activity(rid, f"{self._SB_DR_TYPE}/write", sub)
            return _ok(_view(rec), status=201)

        if method == "DELETE":
            # Breaking the pairing is allowed from EITHER end: called on the Secondary's own
            # (derived, never-stored) path, there is nothing under `key` to pop — redirect to
            # the actually-owned record under the Primary instead.
            del_key = key
            if del_key not in self.state:
                mirror = next((m for m in mirrored_records() if m["name"].lower() == alias.lower()), None)
                if mirror is not None:
                    del_key = f"{mirror['properties']['partnerNamespace'].rsplit('/disasterRecoveryConfigs/', 1)[0]}/disasterRecoveryConfigs/{alias}".lower()
            rec = self.state.pop(del_key, None)
            if rec is not None:
                self._record_activity(rid, f"{self._SB_DR_TYPE}/delete", sub)
            return _ok(None, status=200 if rec is not None else 204)

        return _err(405, "MethodNotAllowed", f"{method} not allowed.")

    def _apim_tier_block(self, type_chain, names, payload, sub, rg):
        """Microsoft.ApiManagement/service sku.capacity — real APIM rejects a scale unit count
        the tier doesn't allow: Consumption is serverless (no scale units at all) and Developer
        is capped at exactly 1 (no scale-out, no SLA) — Vyomi now ENFORCES both instead of
        storing whatever sku the caller sends (azure.apim.scaletier). Checked against the
        EFFECTIVE sku (payload over existing), so a tier-only PATCH that would leave a stale,
        now-invalid capacity in place is rejected too, not just a capacity-only PATCH."""
        if type_chain[0].lower() != "microsoft.apimanagement" or type_chain[1].lower() != "service" or len(type_chain) != 2:
            return None
        sku = (payload or {}).get("sku")
        if not isinstance(sku, dict):
            return None
        existing_sku = (self.state.get(_canonical_id(sub, rg, type_chain, names).lower()) or {}).get("sku") or {}
        tier = sku.get("name", existing_sku.get("name"))
        capacity = sku.get("capacity", existing_sku.get("capacity"))
        if tier == "Consumption" and capacity not in (None, 0):
            return _err(400, "BadRequest", "The Consumption tier has no scale units — sku.capacity must be 0.")
        if tier == "Developer" and capacity not in (None, 1):
            return _err(400, "BadRequest", "The Developer tier is capped at exactly 1 unit (no scale-out, no SLA).")
        return None

    def _apim_locations_block(self, type_chain, names, payload, sub, rg):
        """Microsoft.ApiManagement/service properties.additionalLocations — real APIM only
        offers multi-region deployment on the Basic/Standard/Premium (v1 and v2) tiers; the
        serverless Consumption tier and the single-unit Developer tier have no "Add region"
        button at all. Vyomi now ENFORCES that instead of silently storing extra locations a
        Consumption/Developer service could never actually have (azure.apim.deployment),
        checked against the EFFECTIVE sku (payload over existing) like _apim_tier_block."""
        if type_chain[0].lower() != "microsoft.apimanagement" or type_chain[1].lower() != "service" or len(type_chain) != 2:
            return None
        props = (payload or {}).get("properties") or {}
        locations = props.get("additionalLocations")
        if not locations:
            return None
        sku = (payload or {}).get("sku") or {}
        existing = self.state.get(_canonical_id(sub, rg, type_chain, names).lower()) or {}
        tier = sku.get("name", (existing.get("sku") or {}).get("name"))
        if tier in ("Consumption", "Developer"):
            return _err(400, "BadRequest",
                        f"The {tier} tier does not support additional locations (multi-region deployment).")
        return None

    # The portal's "Protocols + ciphers" legacy-protocol toggles (azure.apim.service.protocols)
    # are the literal strings "True"/"False", same as real APIM's customProperties — Vyomi now
    # validates that shape instead of round-tripping whatever value the caller sends.
    _APIM_PROTOCOL_PREFIX = "microsoft.windowsazure.apimanagement.gateway.security."

    def _apim_protocol_value_block(self, type_chain, payload):
        if type_chain[0].lower() != "microsoft.apimanagement" or type_chain[1].lower() != "service" or len(type_chain) != 2:
            return None
        custom = ((payload or {}).get("properties") or {}).get("customProperties")
        if not isinstance(custom, dict):
            return None
        for k, v in custom.items():
            if k.lower().startswith(self._APIM_PROTOCOL_PREFIX) and v not in ("True", "False"):
                return _err(400, "BadRequest", f"customProperties['{k}'] must be the string 'True' or 'False'.")

    _ACR_PREMIUM_CHILD = {
        "replications": "Geo-replication", "cacherules": "Cache rules",
        "connectedregistries": "Connected registries", "tokens": "Tokens", "scopemaps": "Scope maps",
    }
    _ACR_SCOPE_PERMS = {"content/read", "content/write", "content/delete", "metadata/read", "metadata/write"}

    def _acr_scope_action_valid(self, action: str) -> bool:
        if ":" not in action:
            return False
        repo, perms = action.split(":", 1)
        return bool(repo) and bool(perms) and all(p in self._ACR_SCOPE_PERMS for p in perms.split(","))

    def _acr_validate_block(self, type_chain, names, payload, sub, rg):
        """Microsoft.ContainerRegistry — real ACR tier gates (geo-replication, cache rules,
        connected registries, repository-scoped tokens/scope maps and ACR Tasks are Premium/
        Standard-only features; customer-managed-key encryption, zone redundancy and disabling
        public network access are Premium-only too) plus the cross-field validation real ACR
        applies to those child resources (region/target uniqueness, well-formed scope-map
        actions, a token's scopeMapId must reference a real scope map) — Vyomi now ENFORCES
        these instead of just storing whatever the caller sends (azure.acr.georeplications,
        .cache, .connectedregistries, .tokens, .scopemaps, .tasks, .encryption, .networking)."""
        if type_chain[0].lower() != "microsoft.containerregistry" or type_chain[1].lower() != "registries":
            return None
        props = (payload or {}).get("properties") or {}
        if len(type_chain) == 2:
            existing = self.state.get(_canonical_id(sub, rg, type_chain, names).lower()) or {}
            sku = (payload or {}).get("sku") or {}
            # ACR's sku.name IS its tier (Basic/Standard/Premium, no separate tier label) —
            # checked before sku.tier, which the generic catalog default always stamps
            # "Standard" unless a caller explicitly overrides it too.
            tier = sku.get("name") or sku.get("tier") or (existing.get("sku") or {}).get("name") or (existing.get("sku") or {}).get("tier")
            if tier != "Premium":
                if (props.get("encryption") or {}).get("status") == "enabled":
                    return _err(400, "BadRequest", "Customer-managed key encryption requires a Premium registry.")
                if props.get("zoneRedundancy") == "Enabled":
                    return _err(400, "BadRequest", "Zone redundancy requires a Premium registry.")
                if props.get("publicNetworkAccess") == "Disabled":
                    return _err(400, "BadRequest", "Disabling public network access requires a Premium registry.")
                if (props.get("networkRuleSet") or {}).get("ipRules"):
                    return _err(400, "BadRequest", "IP network rules require a Premium registry.")
            return None
        if len(type_chain) != 3:
            return None
        child = type_chain[2].lower()
        parent_rid = _canonical_id(sub, rg, type_chain[:-1], names[:-1]).lower()
        parent = self.state.get(parent_rid) or {}
        tier = (parent.get("sku") or {}).get("name") or (parent.get("sku") or {}).get("tier")
        if child in self._ACR_PREMIUM_CHILD and tier != "Premium":
            return _err(400, "BadRequest", f"{self._ACR_PREMIUM_CHILD[child]} require a Premium registry.")
        if child == "tasks" and tier == "Basic":
            return _err(400, "BadRequest", "Tasks require a Standard or Premium registry.")
        if child == "replications":
            region = str(payload.get("location") or "").lower()
            if region and region == str(parent.get("location") or "").lower():
                return _err(400, "BadRequest", "A registry cannot be replicated to its own primary location.")
            for k, rec in self.state.items():
                if k == parent_rid or not k.startswith(parent_rid + "/replications/"):
                    continue
                if rec.get("name") != names[-1] and region and str(rec.get("location") or "").lower() == region:
                    return _err(409, "Conflict", f"A replication to '{region}' already exists on this registry.")
        if child == "scopemaps" and isinstance(props.get("actions"), list):
            bad = [a for a in props["actions"] if not self._acr_scope_action_valid(a)]
            if bad:
                return _err(400, "BadRequest", f"Invalid scope map action(s): {', '.join(bad)}. Use '<repository>:<content|metadata>/<read|write|delete>'.")
        if child == "tokens":
            smid = props.get("scopeMapId")
            if smid and not self.state.get(str(smid).lower()):
                return _err(400, "BadRequest", f"scopeMapId '{smid}' does not reference an existing scope map.")
        if child == "cacherules":
            target = props.get("targetRepository")
            if target:
                for k, rec in self.state.items():
                    if k == parent_rid or not k.startswith(parent_rid + "/cacherules/"):
                        continue
                    if rec.get("name") != names[-1] and (rec.get("properties") or {}).get("targetRepository") == target:
                        return _err(409, "Conflict", f"Target repository '{target}' is already mapped by cache rule '{rec.get('name')}'.")
        return None

    def _aks_stopped_block(self, type_chain, names, sub, rg):
        # Real AKS rejects node-pool create/scale/upgrade/delete while the cluster itself is
        # Stopped ("start the cluster before performing this operation") — Vyomi now ENFORCES
        # that instead of letting agentPools writes silently succeed against a stopped cluster
        # (azure.aks.cluster.power / azure.aks.node_pools.crud).
        if len(type_chain) != 3 or type_chain[0].lower() != "microsoft.containerservice" \
                or type_chain[1].lower() != "managedclusters" or type_chain[2].lower() != "agentpools":
            return None
        cluster = self.state.get(_canonical_id(sub, rg, type_chain[:-1], names[:-1]).lower())
        if (cluster or {}).get("properties", {}).get("powerState", {}).get("code") == "Stopped":
            return _err(409, "ClusterNotRunning",
                        "The cluster is stopped. Start the cluster before performing operations on its node pools.")
        return None

    _AKS_PROTECTED_NAMESPACES = {"default", "kube-system", "kube-public", "kube-node-lease"}

    def _aks_namespace_block(self, type_chain, names, payload, sub, rg):
        # A write to properties.namespaces goes through the cluster's own generic PUT/PATCH
        # (api.js's addNamespace/deleteNamespace send the whole array back) — this is the one
        # AKS-specific validation layered on top of that: the console's Namespaces blade never
        # lets default/kube-system/kube-public/kube-node-lease be deleted (same restriction the
        # real "Managed namespaces" preview enforces), and a namespace write needs the same
        # running API server a node-pool write does (azure.aks.namespaces).
        if len(type_chain) != 2 or type_chain[0].lower() != "microsoft.containerservice" \
                or type_chain[1].lower() != "managedclusters":
            return None
        new_ns = (payload or {}).get("properties", {}).get("namespaces")
        if new_ns is None:
            return None
        rid = _canonical_id(sub, rg, type_chain, names)
        cluster = self.state.get(rid.lower())
        current = {n.get("name") for n in (cluster or {}).get("properties", {}).get("namespaces") or []}
        requested = {n.get("name") for n in new_ns}
        removed = current - requested
        protected_removed = removed & self._AKS_PROTECTED_NAMESPACES
        if protected_removed:
            return _err(409, "ProtectedNamespace",
                        f"The namespace(s) {', '.join(sorted(protected_removed))} are system namespaces and cannot be deleted.")
        if removed or (requested - current):
            if (cluster or {}).get("properties", {}).get("powerState", {}).get("code") == "Stopped":
                return _err(409, "ClusterNotRunning",
                            "The cluster is stopped. Start the cluster before creating or deleting namespaces.")
        return None

    _VAULT_URI_RE = re.compile(r"^https?://([a-z0-9-]+)\.vault\.azure\.net/?$", re.I)

    def _storage_encryption_block(self, type_chain, names, payload, sub, rg):
        # v4 WAVE 5b (azure.storage.encryption): real Azure rejects a customer-managed-key
        # selection that doesn't actually name a Key Vault key — Vyomi now ENFORCES the
        # structural shape (keyvaulturi + keyname required) and that the vault URI resolves
        # to a REAL Key Vault in this subscription, instead of round-tripping whatever
        # encryption.keySource/keyvaultproperties the caller sends. The named KEY's own
        # existence/enabled state inside that vault is still not checked (core/azure_arm_core.py
        # is checked through the cfgext key-lookup seam when the substrate injects it).
        if type_chain[0].lower() != "microsoft.storage" or type_chain[1].lower() != "storageaccounts" \
                or len(type_chain) != 2:
            return None
        props = (payload or {}).get("properties") or {}
        enc = props.get("encryption")
        if not isinstance(enc, dict) or enc.get("keySource") != "Microsoft.Keyvault":
            return None
        kv = enc.get("keyvaultproperties") or {}
        uri, key_name = kv.get("keyvaulturi"), kv.get("keyname")
        if not uri or not key_name:
            return _err(400, "BadRequest",
                        "encryption.keyvaultproperties.keyvaulturi and .keyname are required "
                        "when encryption.keySource is 'Microsoft.Keyvault'.")
        m = self._VAULT_URI_RE.match(uri)
        vault_exists = bool(m) and any(
            r.get("_type", "").lower() == "microsoft.keyvault/vaults"
            and r.get("id", "").lower().endswith(f"/vaults/{m.group(1).lower()}")
            for r in self.state.values())
        if not vault_exists:
            return _err(400, "BadRequest",
                        f"The Key Vault referenced by encryption.keyvaultproperties.keyvaulturi "
                        f"('{uri}') does not exist in this subscription.")
        try:
            from core.azure_cfgext_core import check_key_exists
        except ImportError:  # pragma: no cover - Pyodide flat layout
            from azure_cfgext_core import check_key_exists  # type: ignore
        return check_key_exists(m.group(1), key_name, kv.get("keyversion"), "encryption.keyvaultproperties")

    def _storage_hns_block(self, type_chain, names, payload, sub, rg):
        # v4 WAVE 5b (azure.storage.datalakegen2upgrade): the Data Lake Gen2 upgrade flips
        # isHnsEnabled false -> true on an EXISTING account — a one-way migration real Azure
        # only allows from a general-purpose v2 (or Premium block blob) account. Vyomi now
        # ENFORCES both the eligibility and the one-way-ness instead of round-tripping
        # whatever isHnsEnabled the caller sends.
        if type_chain[0].lower() != "microsoft.storage" or type_chain[1].lower() != "storageaccounts" \
                or len(type_chain) != 2:
            return None
        props = (payload or {}).get("properties") or {}
        _fe = files_engine.validate_account(self.state.get(_canonical_id(sub, rg, type_chain, names).lower()), payload)
        if _fe:
            return _err(400, _fe["error"]["code"], _fe["error"]["message"])
        if "isHnsEnabled" not in props:
            return None
        existing = self.state.get(_canonical_id(sub, rg, type_chain, names).lower())
        was = bool((existing or {}).get("properties", {}).get("isHnsEnabled"))
        now = bool(props["isHnsEnabled"])
        if was == now:
            return None
        if was and not now:
            return _err(400, "BadRequest",
                        "Hierarchical namespace cannot be disabled once enabled (Data Lake "
                        "Gen2 upgrade is one-way).")
        kind = (payload or {}).get("kind") or (existing or {}).get("kind")
        if existing is not None and kind not in ("StorageV2", "BlockBlobStorage"):
            return _err(400, "BadRequest",
                        "Hierarchical namespace (Data Lake Gen2) requires a general-purpose v2 "
                        "or premium block blob storage account.")
        return None

    def _cosmos_validate_block(self, type_chain, names, payload, sub, rg):
        # Real Cosmos DB ARM rejects an invalid consistencyPolicy / backupPolicy / locations
        # shape outright — Vyomi now ENFORCES that contract instead of round-tripping whatever
        # the caller sends (azure.cosmos.default_consistency, azure.cosmos.backup_restore,
        # azure.cosmos.replicate_data_globally); the underlying behaviour (read consistency,
        # taking/restoring a backup, provisioning a second region) is still not simulated.
        if (len(type_chain) >= 4 and type_chain[0].lower() == "microsoft.documentdb" and type_chain[-1].lower() == "throughputsettings"):
            try:
                from core.azure_cosmos_core import validate_throughput_settings
            except ImportError:  # pragma: no cover - Pyodide flat layout
                from azure_cosmos_core import validate_throughput_settings  # type: ignore
            msg = validate_throughput_settings((payload or {}).get("properties") or {})
            return _err(400, "BadRequest", msg) if msg else None
        if type_chain[0].lower() != "microsoft.documentdb" or type_chain[1].lower() != "databaseaccounts" or len(type_chain) != 2:
            return None
        existing_props = (self.state.get(_canonical_id(sub, rg, type_chain, names).lower()) or {}).get("properties") or {}
        payload_props = (payload or {}).get("properties") or {}
        props = _merge(existing_props, payload_props) if payload_props else existing_props

        cp = props.get("consistencyPolicy")
        if isinstance(cp, dict):
            level = cp.get("defaultConsistencyLevel", "Session")
            if level not in ("Strong", "BoundedStaleness", "Session", "ConsistentPrefix", "Eventual"):
                return _err(400, "BadRequest", f"Unsupported consistencyPolicy.defaultConsistencyLevel '{level}'.")
            if level == "BoundedStaleness":
                prefix, interval = cp.get("maxStalenessPrefix"), cp.get("maxIntervalInSeconds")
                if not isinstance(prefix, int) or not isinstance(interval, int):
                    return _err(400, "BadRequest",
                                "BoundedStaleness requires integer consistencyPolicy.maxStalenessPrefix and maxIntervalInSeconds.")
                if not (10 <= prefix <= 2147483647):
                    return _err(400, "BadRequest", "consistencyPolicy.maxStalenessPrefix must be between 10 and 2147483647.")
                if not (5 <= interval <= 86400):
                    return _err(400, "BadRequest", "consistencyPolicy.maxIntervalInSeconds must be between 5 and 86400.")

        bp = props.get("backupPolicy")
        if isinstance(bp, dict):
            btype = bp.get("type", "Periodic")
            if btype not in ("Periodic", "Continuous"):
                return _err(400, "BadRequest", f"Unsupported backupPolicy.type '{btype}'.")
            existing_type = (existing_props.get("backupPolicy") or {}).get("type", "Periodic")
            if existing_type == "Continuous" and btype == "Periodic":
                return _err(400, "BadRequest",
                            "Migrating an account's backup policy from Continuous to Periodic mode is not supported.")
            if btype == "Periodic":
                pm = bp.get("periodicModeProperties") or {}
                interval = pm.get("backupIntervalInMinutes", 240)
                retention = pm.get("backupRetentionIntervalInHours", 8)
                redundancy = pm.get("backupStorageRedundancy", "Geo")
                if not isinstance(interval, int) or not (60 <= interval <= 1440):
                    return _err(400, "BadRequest", "periodicModeProperties.backupIntervalInMinutes must be between 60 and 1440.")
                if not isinstance(retention, int) or not (8 <= retention <= 720):
                    return _err(400, "BadRequest", "periodicModeProperties.backupRetentionIntervalInHours must be between 8 and 720.")
                if redundancy not in ("Geo", "Zone", "Local"):
                    return _err(400, "BadRequest", f"Unsupported periodicModeProperties.backupStorageRedundancy '{redundancy}'.")
            else:
                tier = (bp.get("continuousModeProperties") or {}).get("tier", "Continuous30Days")
                if tier not in ("Continuous7Days", "Continuous30Days"):
                    return _err(400, "BadRequest", f"Unsupported continuousModeProperties.tier '{tier}'.")

        locations = props.get("locations")
        if isinstance(locations, list) and locations:
            loc_names = [l.get("locationName") for l in locations]
            if len(set(loc_names)) != len(loc_names):
                return _err(400, "BadRequest", "properties.locations cannot repeat the same locationName.")
            prios = sorted(l.get("failoverPriority") for l in locations)
            if prios != list(range(len(locations))):
                return _err(400, "BadRequest",
                            "properties.locations.failoverPriority must be a 0-based, gap-free sequence with exactly one region at priority 0.")
        return None

    def _acr_images(self):
        """Scanned images of the registry data plane (core/vuln_scan_core.py) for Defender for Containers."""
        store = getattr(self, "acr_store", None)
        if store is None:
            try:
                from core import appliance_stores as _aps
                store = _aps.acr_store()
            except Exception:
                return []
        try:
            try:
                from core import vuln_scan_core
            except ImportError:
                import vuln_scan_core  # type: ignore
            reports = None
            try:   # offline appliance only: upgrade images to a real Trivy report when the container is available
                from providers import trivy_runner
                trivy_runner.request_scan(store)
                reports = trivy_runner.cached_reports()
            except Exception:
                pass
            return vuln_scan_core.scan_acr_store(store, reports)
        except Exception:
            return []

    def _security(self, method, sub, rg, chain, payload, query, scope_rid):
        ctx = {"images": self._acr_images()} if security_engine.plan_on(self.state, sub, "Containers") else {}
        r = security_engine.dispatch(self.state, method, sub, rg, chain, payload or {}, query or {}, scope_rid, ctx)
        if r["status"] < 300 and method in ("PUT", "PATCH") and chain[:1] and chain[0].lower() == "pricings":
            self._record_activity(f"/subscriptions/{sub}/providers/Microsoft.Security/pricings/{chain[1] if len(chain) > 1 else ''}",
                                  "Microsoft.Security/pricings/write", sub)
        return {"status": r["status"], "headers": r.get("headers") or {}, "body": r["body"]}

    def _locks(self, method, sub, rg, namespace, chain, marker, payload):
        # Replay the SAME type/name alternation the main dispatcher uses (see `_arm` above)
        # over everything before the "providers/Microsoft.Authorization/locks" marker.
        stc, snames = [namespace], []
        for n, token in enumerate(chain[:marker]):
            (stc if n % 2 == 0 else snames).append(token)
        scope_rid = _canonical_id(sub, rg, stc, snames)
        rest = chain[marker + 3:]
        return self._locks_crud(method, scope_rid, rest, payload, snames[-1] if snames else scope_rid)

    def _locks_crud(self, method, scope_rid, rest, payload, activity_name):
        if not rest:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            r = locks_engine.list_for(self.state, scope_rid)
        else:
            name = rest[0]
            if method == "GET":
                r = locks_engine.get(self.state, scope_rid, name)
            elif method in ("PUT", "PATCH"):
                r = locks_engine.upsert(self.state, scope_rid, name, payload)
                if r["status"] in (200, 201):
                    _record_activity(activity_name, "Create lock" if r["status"] == 201 else "Update lock", name)
            elif method == "DELETE":
                r = locks_engine.remove(self.state, scope_rid, name)
                if r["status"] == 200:
                    _record_activity(activity_name, "Delete lock", name)
            else:
                return _err(405, "MethodNotAllowed", f"{method} not allowed.")
        return {"status": r["status"], "headers": {}, "body": r["body"]}

    # ── Azure RBAC (role assignments created as real, resource-group-scoped ARM resources) ──
    def _role_catalog(self, sub):
        """{roleName: {actions, notActions, custom, description, id}} — the built-in roles
        (ROLES, never provisioned as catalog records) merged with any custom role definitions
        created via PUT .../roleDefinitions/{name} (which DO live in self.state)."""
        out = {}
        for r in ROLES:
            props = r["properties"]
            actions, not_actions = [], []
            for p in props.get("permissions") or []:
                actions.extend(p.get("actions") or [])
                not_actions.extend(p.get("notActions") or [])
            out[props["roleName"]] = {"roleName": props["roleName"], "actions": actions, "notActions": not_actions,
                                      "custom": False, "description": props.get("description", ""), "id": r["id"]}
        for rec in self.state.values():
            if rec.get("_type", "").lower() != "microsoft.authorization/roledefinitions" or rec.get("_sub") != sub:
                continue
            props = rec.get("properties") or {}
            actions, not_actions = [], []
            for p in props.get("permissions") or []:
                actions.extend(p.get("actions") or [])
                not_actions.extend(p.get("notActions") or [])
            out[rec["name"]] = {"roleName": rec["name"], "actions": actions, "notActions": not_actions,
                                "custom": True, "description": props.get("description", ""), "id": rec["id"]}
        return out

    def _role_assignments(self, sub):
        return [rec for rec in self.state.values()
                if rec.get("_type", "").lower() == "microsoft.authorization/roleassignments" and rec.get("_sub") == sub]

    def _role_definitions_list(self, sub):
        roles = self._role_catalog(sub)
        counts = {}
        for rec in self._role_assignments(sub):
            props = rec.get("properties") or {}
            if str(props.get("kind", "allow")).lower() == "deny":
                continue
            role_name = props.get("roleName") or (props.get("roleDefinitionId") or "").rsplit("/", 1)[-1]
            counts[role_name] = counts.get(role_name, 0) + 1
        value = [{
            "id": info["id"], "name": name,
            "properties": {
                "roleName": name, "type": "CustomRole" if info["custom"] else "BuiltInRole",
                "description": info["description"], "assignableScopes": ["/"],
                "permissions": [{"actions": info["actions"], "notActions": info["notActions"]}],
            },
            "assignmentCount": counts.get(name, 0),
        } for name, info in roles.items()]
        return _ok({"value": value})

    def _check_access(self, sub, scope_rid, payload):
        payload = payload or {}
        subject = payload.get("subject") or {}
        principal_id = payload.get("principalId") or subject.get("principalId") or ""
        actions = payload.get("actions")
        if actions is None:
            single = payload.get("action") or ""
            actions = [{"id": single}] if single else []
        roles = self._role_catalog(sub)
        assignments = self._role_assignments(sub)
        results = []
        for a in actions:
            act = a.get("id") if isinstance(a, dict) else str(a)
            allowed, denied, granting = False, False, []
            for rec in assignments:
                props = rec.get("properties") or {}
                if props.get("principalId") != principal_id:
                    continue
                if not iam_engine._scope_covers(props.get("scope", "/"), scope_rid):
                    continue
                if str(props.get("kind", "allow")).lower() == "deny":
                    if iam_engine._matches_any(props.get("denyActions"), act):
                        denied = True
                    continue
                role_name = props.get("roleName") or (props.get("roleDefinitionId") or "").rsplit("/", 1)[-1]
                role = roles.get(role_name)
                if not role:
                    continue
                if iam_engine._matches_any(role["actions"], act) and not iam_engine._matches_any(role["notActions"], act):
                    allowed = True
                    granting.append(role_name)
            results.append({"actionId": act, "accessDecision": "Allowed" if (allowed and not denied) else "NotAllowed",
                            "roles": granting})
        return _ok({"value": results})

    # ── deployments (Microsoft.Resources/deployments): a bounded real template evaluator ────
    def _execute_deployment(self, sub, rg, rec):
        """PUT every resource listed in properties.template.resources through THIS SAME ARM
        dispatcher — so a deployment actually provisions something, not just stores a record
        of what was asked for. [parameters('x')] / [variables('y')] resolve to literal values
        (properties.parameters, falling back to the template's own defaultValue); any other
        ARM template function (concat/resourceId/reference/copy loops) is left as-is, so that
        resource's own PUT will fail its own validation rather than silently "succeed"."""
        props = rec.get("properties") or {}
        template = props.get("template") or {}
        resources = template.get("resources")
        if not isinstance(resources, list) or not resources:
            return [], []
        values = {k: v.get("defaultValue") for k, v in (template.get("parameters") or {}).items()}
        for k, v in (props.get("parameters") or {}).items():
            values[k] = v.get("value", v) if isinstance(v, dict) else v
        variables = template.get("variables") or {}
        provisioned, errors = [], []
        for entry in resources:
            entry = _resolve_template_expr(entry, values, variables)
            rtype, rname = entry.get("type"), entry.get("name")
            if not rtype or not rname:
                errors.append({"error": "a template resource is missing type/name"})
                continue
            path = (f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{rtype}/{rname}" if rg is not None
                   else f"/subscriptions/{sub}/providers/{rtype}/{rname}")
            body = {k: v for k, v in entry.items() if k not in ("type", "name", "apiVersion", "dependsOn", "condition", "comments")}
            resp = self.handle("PUT", path, {"api-version": entry.get("apiVersion")} if entry.get("apiVersion") else {}, body)
            if resp["status"] >= 400:
                errors.append({"resource": f"{rtype}/{rname}", "status": resp["status"], "error": resp["body"]})
            else:
                provisioned.append({"id": resp["body"].get("id", path), "resourceType": rtype, "resourceName": rname})
        return provisioned, errors

    def _deployment_action(self, action, name, rid, sub, rg):
        rec = self.state.get(rid.lower())
        if not rec:
            return _err(404, "DeploymentNotFound", f"Deployment '{name}' could not be found.")
        if action == "cancel":
            # Every simulated deployment completes synchronously (see the generic PUT branch),
            # so by the time a Cancel call can reach it, it is already in a terminal state —
            # the same conflict a real deployment that finished before Cancel arrived returns.
            state_now = (rec.get("properties") or {}).get("provisioningState", "Succeeded")
            return _err(409, "DeploymentNotCancellable",
                        f"Deployment '{name}' cannot be cancelled: it is already in the terminal "
                        f"state '{state_now}'.")
        # redeploy: re-run the SAME stored template/parameters against current state.
        provisioned, errors = self._execute_deployment(sub, rg, rec)
        rec["properties"]["outputResources"] = provisioned
        if errors:
            rec["properties"]["provisioningState"] = "Failed"
            rec["properties"]["error"] = {"code": "DeploymentFailed", "details": errors}
        else:
            rec["properties"]["provisioningState"] = "Succeeded"
            rec["properties"].pop("error", None)
        rec["properties"]["timestamp"] = _now()
        self._record_activity(rid, "Microsoft.Resources/deployments/redeploy/action", sub, status="Failed" if errors else "Succeeded")
        return _ok(_view(rec))

    def _diagnostic_settings(self, method, sub, rg, namespace, chain, marker, payload):
        # Replay the SAME type/name alternation the main dispatcher uses (see `_arm` above)
        # over everything before the "providers/Microsoft.Insights/diagnosticSettings" marker.
        stc, snames = [namespace], []
        for n, token in enumerate(chain[:marker]):
            (stc if n % 2 == 0 else snames).append(token)
        scope_rid = _canonical_id(sub, rg, stc, snames)
        rest = chain[marker + 3:]
        activity_name = snames[-1] if snames else scope_rid
        if not rest:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            r = monitor_engine.list_diagnostic_settings(self.state, scope_rid)
        else:
            name = rest[0]
            if method == "GET":
                r = monitor_engine.get_diagnostic_setting(self.state, scope_rid, name)
            elif method in ("PUT", "PATCH"):
                r = monitor_engine.upsert_diagnostic_setting(self.state, scope_rid, name, payload)
                if r["status"] in (200, 201):
                    _record_activity(activity_name, "Create diagnostic setting" if r["status"] == 201 else "Update diagnostic setting", name)
            elif method == "DELETE":
                r = monitor_engine.remove_diagnostic_setting(self.state, scope_rid, name)
                if r["status"] == 200:
                    _record_activity(activity_name, "Delete diagnostic setting", name)
            else:
                return _err(405, "MethodNotAllowed", f"{method} not allowed.")
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _metrics(self, method, sub, rg, namespace, chain, marker, query):
        if method != "GET":
            return _err(405, "MethodNotAllowed", "GET required.")
        stc, snames = [namespace], []
        for n, token in enumerate(chain[:marker]):
            (stc if n % 2 == 0 else snames).append(token)
        scope_rid = _canonical_id(sub, rg, stc, snames)
        kind = chain[marker + 2].lower()
        r = (monitor_engine.list_metric_definitions(self.state, scope_rid, self.blob_store) if kind == "metricdefinitions"
             else monitor_engine.get_metrics(self.state, scope_rid, query, self.blob_store))
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _dcr_associations(self, method, sub, rg, namespace, chain, marker, payload):
        stc, snames = [namespace], []
        for n, token in enumerate(chain[:marker]):
            (stc if n % 2 == 0 else snames).append(token)
        scope_rid = _canonical_id(sub, rg, stc, snames)
        rest = chain[marker + 3:]
        activity_name = snames[-1] if snames else scope_rid
        if not rest:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            r = monitor_engine.list_dcr_associations(self.state, scope_rid)
        else:
            name = rest[0]
            if method == "GET":
                r = monitor_engine.get_dcr_association(self.state, scope_rid, name)
            elif method in ("PUT", "PATCH"):
                r = monitor_engine.upsert_dcr_association(self.state, scope_rid, name, payload)
                if r["status"] in (200, 201):
                    _record_activity(activity_name, "Create data collection rule association" if r["status"] == 201
                                      else "Update data collection rule association", name)
            elif method == "DELETE":
                r = monitor_engine.remove_dcr_association(self.state, scope_rid, name)
                if r["status"] == 200:
                    _record_activity(activity_name, "Delete data collection rule association", name)
            else:
                return _err(405, "MethodNotAllowed", f"{method} not allowed.")
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _dns(self, method, sub, rg, chain, payload, query):
        dn = dns_engine
        r = dn.dispatch(self.state, method, sub, rg, chain, [], payload, query, base=self._base)
        resp = {"status": r["status"], "headers": {}, "body": r["body"]}
        if r["lro"] and r["status"] < 300:
            op_id = self._make_operation(r["rid"], method)
            url = f"{self._base}/api/azure/operations/{op_id}?api-version={query.get('api-version') or dn.API_VERSION}"
            resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
        return resp

    def _monitor(self, method, sub, rg, chain, payload, query):
        r = monitor_engine.dispatch(self.state, method, sub, rg, chain, [], payload, query, base=self._base)
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _oi(self, method, sub, rg, chain, payload, query):
        r = oi_engine.dispatch(self.state, method, sub, rg, chain, [], payload, query, base=self._base)
        resp = {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}
        if r["lro"] and r["status"] < 300:
            op_id = self._make_operation(r["rid"], method)
            url = f"{self._base}/api/azure/operations/{op_id}?api-version={query.get('api-version') or oi_engine.API_VERSION}"
            resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
        # oi_engine owns workspace CRUD itself (unlike the generic alternating-type path above,
        # which stamps every write/delete via self._record_activity at the call site) — stamp the
        # SAME eventtypes row here so a workspace's own Activity log panel (and the generic
        # subscription-wide feed the KQL AzureActivity table reads) see workspace mutations too.
        if r.get("rid") and r["status"] < 300:
            self._record_activity(r["rid"], f"{oi_engine.WS_TYPE}/{'delete' if r['verb'] == 'delete' else 'write'}", sub)
        return resp

    def _cogs(self, method, sub, rg, chain, payload, query):
        cs = cogs_engine
        r = cs.dispatch(self.state, method, sub, rg, chain, [], payload, query)
        resp = {"status": r["status"], "headers": {}, "body": r["body"]}
        if r["lro"] and r["status"] < 300:
            resp["status"] = 200 if r["status"] == 201 else r["status"]
            op_id = self._make_operation(r["rid"], method)
            url = f"{self._base}/api/azure/operations/{op_id}?api-version={query.get('api-version') or cs.API_VERSION}"
            resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
        return resp

    def _eg_scoped(self, method, sub, scope_rid, rest, payload):
        if method == "POST" and len(rest) == 1 and rest[0].lower() == "simulateevent":
            # Simulator-internal: raise a system event ON this resource (a resource group's writes raise real ones).
            p = payload or {}
            if eventgrid_engine.scope_kind(scope_rid) not in eventgrid_engine.SYSTEM_EVENT_TYPES:
                return _err(400, "InvalidRequest", "This resource type does not raise Event Grid system events in Vyomi.")
            outs = eventgrid_engine.emit_system_event(self.state, scope_rid, str(p.get("eventType") or ""), str(p.get("subject") or scope_rid),
                                                      p.get("data") or {}, sb_store=getattr(self, "sb_store", None))
            return _ok({"deliveries": outs})
        r = eventgrid_engine.scoped_dispatch(self.state, method, sub, scope_rid, rest, payload)
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _eventgrid(self, method, sub, rg, chain, payload, query):
        r = eventgrid_engine.dispatch(self.state, method, sub, rg, chain, [], payload, query, base=self._base)
        # chain: ['topics', '<topic>', 'providers', 'Microsoft.EventGrid', 'eventSubscriptions', '<name>?']
        if method in ("PUT", "PATCH", "DELETE") and r["status"] in (200, 201, 204) and len(chain) >= 6:
            verb = {"PUT": "Update" if r["status"] == 200 else "Create", "PATCH": "Update", "DELETE": "Delete"}[method]
            _record_activity(chain[1], f"{verb} subscription", chain[5])
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _appconfig(self, method, sub, rg, chain, payload, query):
        ac = appconfig_engine
        r = ac.dispatch(self.state, method, sub, rg, chain, [], payload, query)
        resp = {"status": r["status"], "headers": {}, "body": r["body"]}
        if r["lro"] and r["status"] < 300:
            resp["status"] = 200 if r["status"] == 201 else r["status"]
            op_id = self._make_operation(r["rid"], method)
            url = f"{self._base}/api/azure/operations/{op_id}?api-version={query.get('api-version') or ac.API_VERSION}"
            resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
        return resp

    def _app(self, method, sub, rg, chain, payload, query):
        app = app_engine
        if method in ("PUT", "PATCH") and len(chain) == 2 and chain[0].lower() == "managedenvironments":
            _eid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.App/managedEnvironments/{chain[1]}"
            _blocked = netcfg.validate_aca_env(self.state, _eid, payload or {}, self.state.get(_eid.lower()))
            if _blocked:
                return _blocked
        r = app.dispatch(self.state, method, sub, rg, chain, [], payload, query)
        resp = {"status": r["status"], "headers": {}, "body": r["body"]}
        if r["lro"] and r["status"] < 300:
            resp["status"] = 200 if r["status"] == 201 else r["status"]
            result = r["body"] if r["verb"] == "start" and chain[0].lower() == "jobs" else None
            op_id = self._make_operation(r["rid"], method, result)
            url = f"{self._base}/api/azure/operations/{op_id}?api-version={query.get('api-version') or app.API_VERSION}"
            resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
        return resp

    def _cost_cm(self, method, sub, rg, chain, payload, query):
        r = cost_engine.dispatch_costmanagement(self.state, method, sub, rg, chain, payload, query, base=self._base)
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _cost_consumption(self, method, sub, rg, chain, payload, query):
        r = cost_engine.dispatch_consumption(self.state, method, sub, rg, chain, payload, query, base=self._base)
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _cost_billingbenefits(self, method, sub, rg, chain, payload, query):
        r = cost_engine.dispatch_billingbenefits(self.state, method, sub, chain, payload, query, base=self._base)
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _cost_capacity(self, method, sub, rg, chain, payload, query):
        r = cost_engine.dispatch_capacity(self.state, method, sub, chain, payload, query, base=self._base)
        return {"status": r["status"], "headers": dict(r["headers"]), "body": r["body"]}

    def _monprod(self, method, sub, rg, namespace, chain, payload, query):
        r = monprod_engine.dispatch(self.state, method, sub, rg, namespace, chain, payload, query)
        resp = {"status": r["status"], "headers": {}, "body": r["body"]}
        if r["status"] < 300 and r["rid"] and method in ("PUT", "PATCH", "DELETE"):
            self._record_activity(r["rid"], f"{'/'.join(r['rid'].split('/providers/')[1].split('/')[:2])}/{'delete' if method == 'DELETE' else 'write'}", sub)
        if r["lro"] and r["status"] < 300:
            resp["status"] = 200 if r["status"] == 201 else r["status"]
            op_id = self._make_operation(r["rid"], method)
            url = f"{self._base}/api/azure/operations/{op_id}?api-version={query.get('api-version') or monprod_engine.API_VERSIONS[namespace.lower()]}"
            resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
        return resp

    def _web(self, method, sub, rg, chain, payload, query):
        r = web_engine.dispatch(self.state, method, sub, rg, chain, [], payload, query)
        resp = {"status": r["status"], "headers": {}, "body": r["body"]}
        if r["lro"] and r["status"] < 300:
            resp["status"] = 200 if r["status"] == 201 else r["status"]
            op_id = self._make_operation(r["rid"], method)
            url = f"{self._base}/api/azure/operations/{op_id}?api-version={query.get('api-version') or web_engine.API_VERSION}"
            resp["headers"].update({"Azure-AsyncOperation": url, "Location": url, "Retry-After": "0"})
        return resp

    # ── CRUD primitives ───────────────────────────────────────────────────
    def _list(self, sub, rg, full_type, parent_prefix=None):
        ft = full_type.lower()
        items = []
        for rec in self.state.values():
            if rec.get("_type", "").lower() != ft:
                continue
            if rec.get("_sub") != sub:
                continue
            if rg is not None and (rec.get("_rg") or "").lower() != rg.lower():
                continue
            if parent_prefix and not rec.get("id", "").lower().startswith(parent_prefix):
                continue
            items.append(_view(rec))
        return _ok({"value": items})

    def _upsert(self, rid, key, full_type, name, catalog, payload, base, patch=False):
        existed = key in self.state
        is_top = full_type.lower() == (catalog["namespace"] + "/" + catalog["type"]).lower()
        defaults = _expand_tokens(catalog.get("defaults", {}), name, base) if is_top else {"properties": {"provisioningState": "Succeeded"}}
        endpoints = catalog.get("endpoints", {}) if is_top else {}

        if patch and existed:
            rec = self.state[key]
        else:
            rec = {"id": rid, "name": name, "type": full_type,
                   "location": payload.get("location") or DEFAULT_LOCATION,
                   "tags": {}, "properties": {},
                   "_type": full_type, "_sub": rid.split("/")[2],
                   "_rg": _rg_from_id(rid), "_created": _now()}
            for dk, dv in defaults.items():
                rec[dk] = dv if not isinstance(dv, dict) else dict(dv)

        for fld in ("location", "kind"):
            if payload.get(fld) is not None:
                rec[fld] = payload[fld]
        if isinstance(payload.get("tags"), dict):
            rec["tags"] = _merge(rec.get("tags", {}), payload["tags"])
        if isinstance(payload.get("sku"), dict):
            rec["sku"] = _merge(rec.get("sku", {}), payload["sku"])
        if isinstance(payload.get("identity"), dict):
            _before_ident = rec.get("identity")
            _apply_identity(rec, payload["identity"])
            _missing = _resolve_user_identities(rec, self.state)
            if _missing:
                rec["identity"] = _before_ident
                if not existed:
                    self.state.pop(key, None)
                return _err(400, "ResourceNotFound", f"The Resource '{_missing}' of type 'Microsoft.ManagedIdentity/userAssignedIdentities' was not found.")
            if full_type.lower() == "microsoft.compute/virtualmachines":   # Run command's IMDS token subject
                rec["identity"] = _vm_identity_view(rid, rec["identity"])
        if isinstance(payload.get("properties"), dict):
            rec["properties"] = _merge(rec.get("properties", {}), payload["properties"])

        rec.setdefault("properties", {})
        rec["properties"].setdefault("provisioningState", "Succeeded")
        for path_expr, suffix in endpoints.items():
            if _get_path(rec, path_expr) in (None, ""):
                _set_path(rec, path_expr, base + suffix.replace("__NAME__", name))
        # systemData.createdAt/lastModifiedAt: real ARM returns this on every resource; the
        # Overview "Created"/"Updated" fields some blades show read it back.
        rec["systemData"] = {"createdAt": rec.get("_created", _now()), "lastModifiedAt": _now()}

        if full_type.lower() == "microsoft.network/networkinterfaces":
            bad = self._nic_ips(key, rec)
            if bad is not None:
                if not existed:
                    self.state.pop(key, None)
                return bad
        if full_type.lower() == "microsoft.network/virtualnetworks":
            bad = self._allocate_ipam_pool(rec)
            if bad is not None:
                if not existed:
                    self.state.pop(key, None)
                return bad
            self._sync_inline_subnets(rid, rec)
        if full_type.lower() == "microsoft.containerservice/managedclusters" and not existed:
            # The disk/file CSI driver add-ons provision these StorageClasses on every new AKS
            # cluster, from the moment it comes up — same seeding convention as the default
            # namespaces above (properties.namespaces, via the catalog defaults).
            k8s_engine.seed_storage_classes(rec)
        self.state[key] = rec
        return _ok(_view(rec), status=200 if existed else 201)

    # ── IPAM pool allocation (Microsoft.Network/networkManagers/{nm}/ipamPools/{pool}) ────
    # A vnet created/updated with properties.addressSpace.ipamPoolPrefixAllocations (the real
    # ARM shape the portal's "Allocate using IP address pools" checkbox produces, instead of a
    # literal addressPrefixes list) gets a REAL non-overlapping CIDR block carved out of the
    # named pool's own addressPrefixes — same enforcement style as _nic_ips allocating a NIC's
    # private IP from its subnet. The pool tracks its outstanding allocations in `_allocated`
    # (never serialised to ARM clients); a vnet remembers what it was given in `_ipam_alloc` so
    # a later PATCH/delete can release the old block before taking a new one.
    def _allocate_ipam_pool(self, rec):
        import ipaddress
        import math
        props = rec.setdefault("properties", {})
        addr_space = props.get("addressSpace") or {}
        allocs_in = addr_space.get("ipamPoolPrefixAllocations")
        old_allocs = rec.get("_ipam_alloc")
        if not allocs_in:
            if old_allocs:
                self._release_ipam_pool(old_allocs)
                rec.pop("_ipam_alloc", None)
            return None
        if not isinstance(allocs_in, list):
            return _err(400, "BadRequest", "The property 'addressSpace.ipamPoolPrefixAllocations' must be an array.")
        requested = []
        for a in allocs_in:
            pool_id = str(((a or {}).get("pool") or {}).get("id") or "").lower()
            if not pool_id:
                return _err(400, "BadRequest", "Each ipamPoolPrefixAllocations entry needs 'pool.id'.")
            requested.append((pool_id, str((a or {}).get("numberOfIpAddresses") or "")))
        if old_allocs and [(o["pool"], o["count"]) for o in old_allocs] == requested:
            return None          # idempotent PATCH: same request as last time, keep the block
        if old_allocs:
            self._release_ipam_pool(old_allocs)
            rec.pop("_ipam_alloc", None)
        prefixes, new_allocs = [], []
        for pool_key, count_s in requested:
            pool = self.state.get(pool_key)
            if pool is None or not pool.get("_type", "").lower().endswith("/ipampools"):
                return _err(400, "ParentResourceNotFound", f"The IPAM pool '{pool_key}' was not found.")
            try:
                count = int(count_s)
                if count <= 0:
                    raise ValueError
            except ValueError:
                return _err(400, "BadRequest", "The property 'numberOfIpAddresses' must be a positive integer.")
            prefixlen = 32 - max(0, math.ceil(math.log2(count)))
            pool_prefixes = (pool.get("properties") or {}).get("addressPrefixes") or []
            if not pool_prefixes:
                return _err(400, "BadRequest", f"The IPAM pool '{pool.get('name')}' has no address prefixes to allocate from.")
            allocated = pool.setdefault("_allocated", [])
            used_nets = [ipaddress.ip_network(a) for a in allocated]
            block = None
            for prefix in pool_prefixes:
                net = ipaddress.ip_network(prefix, strict=False)
                if prefixlen < net.prefixlen:
                    continue
                for cand in net.subnets(new_prefix=prefixlen):
                    if not any(cand.overlaps(u) for u in used_nets):
                        block = cand
                        break
                if block:
                    break
            if block is None:
                return _err(400, "AddressSpaceExhausted",
                            f"The IPAM pool '{pool.get('name')}' does not have {count} contiguous free IP addresses left.")
            allocated.append(str(block))
            prefixes.append(str(block))
            new_allocs.append({"pool": pool_key, "count": count_s, "prefix": str(block)})
        addr_space["addressPrefixes"] = prefixes
        props["addressSpace"] = addr_space
        rec["_ipam_alloc"] = new_allocs
        return None

    def _release_ipam_pool(self, allocs):
        for a in allocs:
            pool = self.state.get(a["pool"])
            allocated = (pool or {}).get("_allocated")
            if allocated and a["prefix"] in allocated:
                allocated.remove(a["prefix"])

    def _sync_inline_subnets(self, vnet_rid, vnet_rec):
        """A virtualNetwork PUT/PATCH may define its subnets inline (properties.subnets) —
        real Azure's much more common pattern than the dedicated .../subnets/{name} PUT, and
        treats both the same: one shared subnet collection, individually gettable and listable
        either way. Mirror each inline subnet into its own flat state entry (the same shape
        the dedicated PUT creates) so GET/LIST on the nested subnets path — and anything built
        on it, e.g. the NSG blade's Subnets/Effective security rules association scan — sees it too."""
        for s in (vnet_rec.get("properties") or {}).get("subnets") or []:
            name = s.get("name")
            if not name:
                continue
            sid = f"{vnet_rid}/subnets/{name}"
            key = sid.lower()
            rec = self.state.get(key) or {
                "id": sid, "name": name, "type": "Microsoft.Network/virtualNetworks/subnets",
                "_type": "microsoft.network/virtualnetworks/subnets",
                "_sub": vnet_rec.get("_sub"), "_rg": vnet_rec.get("_rg"), "_created": _now(),
            }
            rec["properties"] = dict(s.get("properties") or {})
            rec["properties"].setdefault("provisioningState", "Succeeded")
            rec["systemData"] = {"createdAt": rec.get("_created", _now()), "lastModifiedAt": _now()}
            self.state[key] = rec

    # ── netsim: NIC private-IP allocation + Network Watcher (IP flow verify / next hop) ──
    def _subnet_prefix(self, subnet_id: str):
        sid = str(subnet_id or "").lower()
        rec = self.state.get(sid)
        if rec:
            p = rec.get("properties") or {}
            return p.get("addressPrefix") or (p.get("addressPrefixes") or [None])[0]
        vnet_id, _, name = sid.rpartition("/subnets/")
        vnet = self.state.get(vnet_id)
        for s in ((vnet or {}).get("properties") or {}).get("subnets") or []:
            if str(s.get("name", "")).lower() == name:
                p = s.get("properties") or {}
                return p.get("addressPrefix") or (p.get("addressPrefixes") or [None])[0]
        return None

    def _nic_ips(self, key: str, rec: dict):
        """Azure allocates a NIC ipConfiguration's private IP from its subnet (first four and the
        last address reserved); a Static address must be in the subnet and free."""
        import ipaddress
        used = {}
        for k, other in self.state.items():
            if k == key or "/providers/microsoft.network/networkinterfaces/" not in k or k.count("/") != 8:
                continue
            for ipc in (other.get("properties") or {}).get("ipConfigurations") or []:
                p = ipc.get("properties") or {}
                used.setdefault(str((p.get("subnet") or {}).get("id", "")).lower(), set()).add(p.get("privateIPAddress"))
        for ipc in (rec.get("properties") or {}).get("ipConfigurations") or []:
            p = ipc.setdefault("properties", {})
            sid = str((p.get("subnet") or {}).get("id", "")).lower()
            prefix = self._subnet_prefix(sid) if sid else None
            if not prefix:
                continue
            net = ipaddress.ip_network(prefix, strict=False)
            taken = used.setdefault(sid, set())
            want = p.get("privateIPAddress")
            static = str(p.get("privateIPAllocationMethod", "Dynamic")).lower() == "static"
            if want and (static or ipaddress.ip_address(want) in net):
                ip = ipaddress.ip_address(want)
                if ip not in net or not (int(net.network_address) + 4 <= int(ip) <= int(net.broadcast_address) - 1):
                    return _err(400, "PrivateIPAddressNotInSubnet",
                                f"IP address {want} is not within the usable range of subnet {sid}.")
                if want in taken:
                    return _err(400, "PrivateIPAddressInUse", f"IP configuration {ipc.get('name')} is using the private IP "
                                                              f"address {want} which is already allocated.")
                taken.add(want)
                p.setdefault("privateIPAllocationMethod", "Static" if static else "Dynamic")
                continue
            for n in range(int(net.network_address) + 4, int(net.broadcast_address)):
                cand = str(ipaddress.ip_address(n))
                if cand not in taken:
                    p["privateIPAddress"], p["privateIPAllocationMethod"] = cand, "Dynamic"
                    taken.add(cand)
                    break
            else:
                return _err(400, "SubnetIsFull", f"Subnet {sid} has no free IP addresses.")
            p.setdefault("privateIPAddressVersion", "IPv4")
        return None

    def _nw_target_iface(self, topo, payload: dict):
        nic = str(payload.get("targetNicResourceId") or "").lower()
        if nic and nic in topo.interfaces:
            return topo.interfaces[nic]
        target = str(payload.get("targetResourceId") or "").lower()
        if target in topo.interfaces:
            return topo.interfaces[target]
        vm = self.state.get(target)
        for n in (((vm or {}).get("properties") or {}).get("networkProfile") or {}).get("networkInterfaces") or []:
            nid = str(n.get("id", "")).lower()
            if nid in topo.interfaces:
                return topo.interfaces[nid]
        return None

    def _nw_connectivity_check(self, topo, ev, payload: dict):
        """Microsoft.Network/networkWatchers/{nw}/connectivityCheck — real Azure's
        source/destination shape ({source: {resourceId}, destination: {resourceId|address, port},
        protocol}), answered by the SAME netsim `reach()` the AWS Reachability Analyzer / GCP
        Connectivity Tests analyzers use. `hops[].type` carries this evaluator's own component
        names (route-table / nsg / peering / ...), not real Network Watcher's hop-type enum —
        see the azure.vnets.network_watcher limitation."""
        source = payload.get("source") or {}
        src_iface = self._nw_target_iface(topo, {"targetResourceId": source.get("resourceId"),
                                                 "targetNicResourceId": source.get("networkInterfaceId")})
        if src_iface is None:
            return _err(400, "InvalidSourceResource", "source.resourceId must be a virtual machine (or NIC) "
                                                      "with a network interface in a simulated subnet.")
        destination = payload.get("destination") or {}
        dst_iface = self._nw_target_iface(topo, {"targetResourceId": destination.get("resourceId")}) if destination.get("resourceId") else None
        dst = dst_iface if dst_iface is not None else str(destination.get("address") or "")
        if not dst:
            return _err(400, "InvalidDestination", "destination.resourceId or destination.address is required.")
        port = destination.get("port")
        protocol = str(payload.get("protocol", "TCP")).lower()
        v = ev.reach(topo, src_iface, dst, protocol, int(port) if str(port).isdigit() else None)
        hops = [{"type": h.component, "id": h.id, "address": "", "issues": [] if h.decision != "deny" else
                [{"origin": "Outbound", "severity": "Error", "type": h.decision, "context": [{"key": "detail", "value": h.detail}]}]}
                for h in v.hops]
        reachable = v.reachable
        return _ok({"hops": hops, "connectionStatus": "Reachable" if reachable else "Unreachable",
                    "avgLatencyInMs": 1 if reachable else 0, "minLatencyInMs": 1 if reachable else 0,
                    "maxLatencyInMs": 1 if reachable else 0, "probesSent": 100, "probesFailed": 0 if reachable else 100})

    def _nw_config_diagnostic(self, topo, ev, nm, payload: dict):
        """Microsoft.Network/networkWatchers/{nw}/queryNetworkConfigurationDiagnostic — real
        Azure's NSG-focused diagnostic reached from the NSG blade's 'Diagnose and solve
        problems' page ('Network configuration diagnostics' tile): for each
        {direction, protocol, source, destination, destinationPort} profile it reports EVERY
        network security group evaluated on the path (NIC NSG and/or subnet NSG) with its
        matched rule and decision — unlike ipFlowVerify, which only returns the single combined
        verdict. Same netsim `_layers` pass as ipFlowVerify — see azure.nsgs.network_watcher."""
        iface = self._nw_target_iface(topo, payload)
        if iface is None:
            return _err(400, "InvalidTargetResource", "targetResourceId must be a virtual machine (or targetNicResourceId a NIC) "
                                                      "with a network interface in a simulated subnet.")
        sub = topo.subnet_of(iface)
        results = []
        for profile in payload.get("profiles") or []:
            direction = nm.INGRESS if str(profile.get("direction", "Inbound")).lower() == "inbound" else nm.EGRESS
            proto = str(profile.get("protocol", "TCP")).lower()
            remote = str((profile.get("source") if direction == nm.INGRESS else profile.get("destination")) or "")
            port = profile.get("destinationPort")
            dport = int(port) if str(port).isdigit() else None
            remote_iface = topo.iface_by_ip(remote)
            v = ev.Verdict()
            ok = ev._layers(topo, iface, direction, proto, dport, remote, remote_iface, True, v)
            nsgs = []
            for h in v.hops:
                if h.component != "nsg":
                    continue
                applied_to = "networkInterface" if h.id in iface.rulesets else ("subnet" if h.id in sub.rulesets else "unknown")
                rule_name = h.detail.split(" ")[0] if h.detail else ""
                access = "Allow" if h.decision == "allow" else "Deny"
                nsgs.append({"networkSecurityGroupId": h.id, "appliedTo": applied_to,
                            "matchedRule": {"name": rule_name, "action": access},
                            "rulesEvaluationResult": [{"name": rule_name, "destinationPort": str(port or "*"),
                                                      "destinationAddress": remote, "decision": access}]})
            results.append({"profile": {"direction": profile.get("direction", "Inbound"), "protocol": profile.get("protocol", "TCP"),
                                        "source": profile.get("source", ""), "destination": profile.get("destination", ""),
                                        "destinationPort": str(port or "")},
                            "networkSecurityGroupResult": {"securityRuleAccessResult": "Allow" if ok else "Deny",
                                                            "evaluatedNetworkSecurityGroups": nsgs}})
        return _ok({"results": results})

    def _network_watcher(self, verb: str, payload: dict):
        try:
            from core.netsim import evaluate as ev, from_azure as fz, model as nm
        except ImportError:                              # pragma: no cover - flat layout
            from netsim import evaluate as ev, from_azure as fz, model as nm   # type: ignore
        topo = fz.from_azure(self.state)
        if verb == "connectivitycheck":
            return self._nw_connectivity_check(topo, ev, payload or {})
        if verb == "querynetworkconfigurationdiagnostic":
            return self._nw_config_diagnostic(topo, ev, nm, payload or {})
        iface = self._nw_target_iface(topo, payload or {})
        if iface is None:
            return _err(400, "InvalidTargetResource", "targetResourceId must be a virtual machine (or targetNicResourceId a NIC) "
                                                      "with a network interface in a simulated subnet.")
        if verb == "nexthop":
            dst = str(payload.get("destinationIPAddress") or "")
            r = ev.route_lookup(topo, topo.subnet_of(iface), dst, iface)
            kind_map = {nm.LOCAL: "VnetLocal", nm.IGW: "Internet", nm.PEERING: "VNetPeering", nm.BLACKHOLE: "None",
                        nm.INSTANCE: "VirtualAppliance", nm.NAT: "Internet"}
            if r is None:
                return _ok({"nextHopType": "None", "nextHopIpAddress": "", "routeTableId": "System Route"})
            hop_ip = topo.interfaces[r.target].ip if r.kind == nm.INSTANCE and r.target in topo.interfaces else ""
            rt = r.name.split("/routes/")[0] if r.origin == "user" and "/routes/" in r.name else "System Route"
            return _ok({"nextHopType": kind_map.get(r.kind, "VirtualNetworkGateway"), "nextHopIpAddress": hop_ip,
                        "routeTableId": rt})
        # ipFlowVerify: NSG verdict (subnet NSG + NIC NSG) for one packet in one direction
        direction = nm.INGRESS if str(payload.get("direction", "Inbound")).lower() == "inbound" else nm.EGRESS
        proto = str(payload.get("protocol", "TCP")).lower()
        lport, rport = str(payload.get("localPort", "")), str(payload.get("remotePort", ""))
        remote = str(payload.get("remoteIPAddress") or "")
        dport = int(lport if direction == nm.INGRESS else rport) if (lport if direction == nm.INGRESS else rport).isdigit() else None
        sport = int(rport if direction == nm.INGRESS else lport) if (rport if direction == nm.INGRESS else lport).isdigit() else None
        remote_iface = topo.iface_by_ip(remote)
        v = ev.Verdict()
        ok = ev._layers(topo, iface, direction, proto, dport, remote, remote_iface, True, v, sport)
        rule_name = ""
        hop = next((h for h in v.hops if h.decision == "deny"), None) if not ok else (v.hops[-1] if v.hops else None)
        if hop is not None:
            name = hop.detail.split(" ")[0]
            rs = topo.rulesets.get(hop.id)
            rule = next((r for r in (rs.rules if rs else []) if r.name == name), None)
            if rule is not None:
                rule_name = f"{'defaultSecurityRules' if rule.implied else 'securityRules'}/{name}"
        return _ok({"access": "Allow" if ok else "Deny", "ruleName": rule_name})

    def _arm_action(self, action, type_chain, resource_name, parent_rid="", payload=None, sub=None, rg=None):
        ns = type_chain[0].lower() if type_chain else ""
        typ = type_chain[1].lower() if len(type_chain) > 1 else ""
        if ns == "microsoft.resources" and typ == "deployments" and action in ("cancel", "redeploy"):
            return self._deployment_action(action, resource_name, parent_rid, sub, rg)
        if ns == "microsoft.containerregistry" and typ == "registries" and len(type_chain) == 3 and action == "schedulerun":
            rec = self.state.get(parent_rid.lower()) if parent_rid else None
            if not rec:
                return _err(404, "ResourceNotFound", f"Registry '{resource_name}' not found.")
            try:
                from core import azure_acr_tasks_core as _acrt
            except ImportError:                      # Pyodide flat layout
                import azure_acr_tasks_core as _acrt  # type: ignore
            return _acrt.schedule_run(self.state, parent_rid, rec, payload, sub, rg)
        if ns == "microsoft.containerregistry" and typ == "registries" and action in ("listcredentials", "regeneratecredential"):
            rec = self.state.get(parent_rid.lower()) if parent_rid else None
            if not rec:
                return _err(404, "ResourceNotFound", f"Registry '{resource_name}' not found.")
            if not rec.get("properties", {}).get("adminUserEnabled"):
                return _err(400, "AdminUserCredentialsNotEnabled", "Admin user is not enabled on this registry.")
            creds = rec.setdefault("_credentials", {"password": uuid.uuid4().hex, "password2": uuid.uuid4().hex})
            if action == "regeneratecredential":
                target = (payload or {}).get("name", "password")
                if target not in creds:
                    return _err(400, "BadRequest", f"Unknown credential name '{target}'.")
                creds[target] = uuid.uuid4().hex
            return _ok({"username": resource_name, "passwords": [
                {"name": "password", "value": creds["password"]},
                {"name": "password2", "value": creds["password2"]},
            ]})
        if ns == "microsoft.storage" and typ == "storageaccounts" and len(type_chain) == 3 and action in ("listkeys", "regeneratekey"):
            rec = self.state.get(parent_rid.lower()) if parent_rid else None
            if not rec:
                return _err(404, "ResourceNotFound", f"Storage account '{resource_name}' not found.")
            if action == "regeneratekey":
                r = storage_ext.regenerate(rec, payload or {})
                return _ok(r["body"]) if r["status"] == 200 else _err(r["status"], r["body"]["error"]["code"], r["body"]["error"]["message"])
            return _ok(storage_ext.list_keys(rec))
        if ns == "microsoft.sql" and typ == "servers" and action in ("export", "import"):
            return self._sql_import_export(action, type_chain, parent_rid, payload or {}, sub, rg)
        if ns == "microsoft.containerservice" and typ == "managedclusters":
            return self._aks_action(action, resource_name, parent_rid, payload or {})
        if ns == "microsoft.documentdb" and typ == "databaseaccounts" and action in (
                "listkeys", "listreadonlykeys", "listconnectionstrings", "regeneratekey"):
            return self._cosmos_keys_action(action, resource_name, parent_rid, payload or {})
        if ns == "microsoft.documentdb" and typ == "databaseaccounts" and action == "failoverprioritychange":
            return self._cosmos_failover_action(resource_name, parent_rid, payload or {})
        if ns == "microsoft.apimanagement" and typ == "service" and len(type_chain) > 2 and type_chain[2].lower() == "namedvalues" and action == "listvalue":
            return self._apim_namedvalue_listvalue(resource_name, parent_rid)
        if ns == "microsoft.apimanagement" and typ == "service" and len(type_chain) > 2 and type_chain[2].lower() == "apis" and action == "testconnect":
            return self._apim_test_connect(resource_name, parent_rid, payload or {})
        if action in ("start", "poweroff", "restart", "deallocate"):
            if ns != "microsoft.compute" or typ != "virtualmachines":
                return _err(400, "ActionNotSupported",
                            f"Action '{action}' is only supported on Microsoft.Compute/virtualMachines.")
            rec = self.state.get(parent_rid.lower()) if parent_rid else None
            if not rec:
                return _err(404, "ResourceNotFound", f"Virtual machine '{resource_name}' not found.")
            new_status = {"start": "running", "restart": "running",
                          "poweroff": "stopped", "deallocate": "deallocated"}[action]
            props = rec.setdefault("properties", {})
            props.setdefault("runtime", {})["containerStatus"] = new_status
            props["powerState"] = f"PowerState/{new_status}"
            return _ok({"status": "Succeeded", "action": action, "containerStatus": new_status,
                        "note": "metadata-only (no runtime backing in-browser); logical state updated"})
        if ns == "microsoft.eventgrid" and typ == "topics" and action == "listeventgridmetrics":
            # Simulator-internal read of the topic's REAL, activity-derived counters
            # (core/azure_eventgrid_core.py publish/deliver) — not the generic
            # Microsoft.Insights/metrics time-series API (out of scope; see
            # azure.eventgrid.topic.monitoring), so it rides the same listKeys-style
            # action-verb mechanism instead of pretending to be that API.
            rec = self.state.get(parent_rid.lower()) if parent_rid else None
            if not rec:
                return _err(404, "ResourceNotFound", f"Topic '{resource_name}' not found.")
            return _ok({"metrics": {k: rec.get("_metrics", {}).get(k, 0) for k in eventgrid_engine.METRIC_NAMES}})
        if action == "runcommand":
            if ns != "microsoft.compute" or typ != "virtualmachines":
                return _err(400, "ActionNotSupported",
                            "Action 'runCommand' is only supported on Microsoft.Compute/virtualMachines.")
            rec = self.state.get(parent_rid.lower()) if parent_rid else None
            if not rec:
                return _err(404, "ResourceNotFound", f"Virtual machine '{resource_name}' not found.")
            if rec.get("properties", {}).get("powerState", "PowerState/running") != "PowerState/running":
                return _err(409, "OperationNotAllowed", "The VM must be in the running state to run commands.")
            result = self._vm_run_command(rec, payload or {}, sub or DEFAULT_SUBSCRIPTION)
            self._record_activity(parent_rid, "Microsoft.Compute/virtualMachines/runCommand/action", sub or DEFAULT_SUBSCRIPTION)
            return _ok(result)
        if action == "resetpassword":
            if ns != "microsoft.compute" or typ != "virtualmachines":
                return _err(400, "ActionNotSupported",
                            "Action 'resetPassword' is only supported on Microsoft.Compute/virtualMachines.")
            rec = self.state.get(parent_rid.lower()) if parent_rid else None
            if not rec:
                return _err(404, "ResourceNotFound", f"Virtual machine '{resource_name}' not found.")
            username = str((payload or {}).get("username") or "").strip()
            if not username:
                return _err(400, "InvalidParameter", "username is required.")
            osp = rec.setdefault("properties", {}).setdefault("osProfile", {})
            osp["adminUsername"] = username
            password = (payload or {}).get("password")
            if password:
                osp["adminPassword"] = password
                osp.pop("linuxConfiguration", None)
            self._record_activity(parent_rid, "Microsoft.Compute/virtualMachines/extensions/write", sub or DEFAULT_SUBSCRIPTION)
            return _ok({"status": "Succeeded"})
        if action in ("redeploy", "reapply"):
            if ns != "microsoft.compute" or typ != "virtualmachines":
                return _err(400, "ActionNotSupported",
                            f"Action '{action}' is only supported on Microsoft.Compute/virtualMachines.")
            rec = self.state.get(parent_rid.lower()) if parent_rid else None
            if not rec:
                return _err(404, "ResourceNotFound", f"Virtual machine '{resource_name}' not found.")
            props = rec.setdefault("properties", {})
            iv = dict(props.get("instanceView") or {})
            if action == "redeploy":
                # Real redeploy moves the VM to a new host and re-specializes it — Vyomi has no
                # hosts to move between, but it DOES really reset the logical power state and
                # tags the event so Change tracking / Activity log show it happened.
                props["powerState"] = "PowerState/running"
                iv["lastRedeployTimestamp"] = _now()
            else:
                iv["lastReapplyTimestamp"] = _now()
            props["instanceView"] = iv
            self._record_activity(parent_rid, f"Microsoft.Compute/virtualMachines/{action}/action", sub or DEFAULT_SUBSCRIPTION)
            return _ok({"status": "Succeeded"})
        if action in ("listkeys", "regeneratekey"):
            return _ok({"keys": [{"keyName": "key1", "value": "c2ltdWxhdGVk", "permissions": "FULL"},
                                 {"keyName": "key2", "value": "c2ltdWxhdGVk", "permissions": "FULL"}]})
        if action == "listconnectionstrings":
            return _ok({"connectionStrings": []})
        if action == "listsecrets":
            return _ok({})
        return _ok({})

    # ── VM backup (Microsoft.Compute/virtualMachines/{vm}/providers/Microsoft.Compute/
    # restorePoints): real, stateful "backup as a snapshot" of the VM's own ARM properties
    # document — list/create/get/delete plus a restore action that really overwrites the
    # VM's current properties with the captured ones (azure.vms.backup). ─────────────────
    def _vm_backup(self, method, sub, vm_rid, rest, payload):
        vm = self.state[vm_rid.lower()]
        snaps = vm.setdefault("_restorePoints", {})
        if not rest:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            return _ok({"value": [self._vm_backup_view(vm_rid, n, s) for n, s in snaps.items()]})
        name = rest[0]
        if len(rest) == 2 and rest[1].lower() == "restore":
            if method != "POST":
                return _err(405, "MethodNotAllowed", "restore is a POST-only action.")
            snap = snaps.get(name)
            if not snap:
                return _err(404, "ResourceNotFound", f"Restore point '{name}' not found.")
            vm["properties"] = json.loads(json.dumps(snap["properties"]))
            self._record_activity(vm_rid, "Microsoft.Compute/virtualMachines/restorePoints/restore/action", sub)
            return _ok({"status": "Succeeded"})
        if len(rest) != 1:
            return _err(404, "NotFound", "Unknown restore point path.")
        if method == "GET":
            snap = snaps.get(name)
            if not snap:
                return _err(404, "ResourceNotFound", f"Restore point '{name}' not found.")
            return _ok(self._vm_backup_view(vm_rid, name, snap))
        if method == "PUT":
            existed = name in snaps
            snap = {"createdAt": _now(), "properties": json.loads(json.dumps(vm.get("properties", {})))}
            snaps[name] = snap
            self._record_activity(vm_rid, "Microsoft.Compute/virtualMachines/restorePoints/write", sub)
            return _ok(self._vm_backup_view(vm_rid, name, snap), status=200 if existed else 201)
        if method == "DELETE":
            existed = snaps.pop(name, None) is not None
            return _ok(None, status=200 if existed else 204)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")

    @staticmethod
    def _vm_backup_view(vm_rid, name, snap):
        props = snap["properties"]
        return {"id": f"{vm_rid}/providers/Microsoft.Compute/restorePoints/{name}", "name": name,
                "type": "Microsoft.Compute/virtualMachines/restorePoints",
                "properties": {"provisioningState": "Succeeded", "timeCreated": snap["createdAt"],
                               "sourceMetadata": {"hardwareProfile": props.get("hardwareProfile"),
                                                  "storageProfile": props.get("storageProfile"),
                                                  "osProfile": props.get("osProfile")}}}

    # ── Run command (POST .../virtualMachines/{vm}/runCommand): a bounded, deterministic
    # script interpreter — NOT a general-purpose shell (no guest OS process exists in a
    # browser/WASM simulator to attach one to). It recognizes a small fixed set of whole-script
    # shapes end to end: plain echo/hostname/whoami/date/uname, and the IMDS-token-then-Key-
    # Vault-secret-fetch pattern that demonstrates a system-assigned managed identity's token
    # really being checked against a real role assignment (azure.vms.identity /
    # azure.vms.run_command) — never a fabricated success for scripts it doesn't recognize. ──
    _IMDS_RE = re.compile(r"169\.254\.169\.254[^\s\"']*oauth2/token[^\s\"']*", re.IGNORECASE)
    _RESOURCE_RE = re.compile(r"resource=([^&\s\"']+)")
    _KV_SECRET_RE = re.compile(r"https://([a-z0-9-]+)\.vault\.azure\.net/secrets/([A-Za-z0-9-]+)", re.IGNORECASE)
    _ECHO_RE = re.compile(r'^(?:echo|Write-Output|Write-Host)\s+(.*)$', re.IGNORECASE)

    def _vm_run_command(self, rec: dict, payload: dict, sub: str) -> dict:
        lines = payload.get("script")
        script = "\n".join(str(x) for x in lines) if isinstance(lines, list) else str(lines or "")
        stripped = script.strip()
        identity = rec.get("identity") or {}
        principal_id = identity.get("principalId") if "systemassigned" in str(identity.get("type") or "").lower() else None

        out, exit_code = [], 0
        imds_m = self._IMDS_RE.search(script)
        token = None
        if imds_m:
            res_m = self._RESOURCE_RE.search(imds_m.group(0))
            resource = unquote(res_m.group(1)) if res_m else "https://management.azure.com/"
            if not principal_id:
                out.append(json.dumps({"error": "invalid_request", "error_description":
                    "Identity not found. The requested identity has not been assigned to this "
                    "resource, or multiple identities were found and none was specified."}))
                exit_code = 1
            else:
                token = f"vyomi.{uuid.uuid4().hex}"
                self._vm_tokens[token] = {"principalId": principal_id, "resource": resource, "vmRid": rec["id"]}
                out.append(json.dumps({"access_token": token, "client_id": principal_id, "expires_in": "3599",
                                       "expires_on": str(int(datetime.datetime.now(datetime.timezone.utc).timestamp()) + 3599),
                                       "resource": resource, "token_type": "Bearer"}))

        kv_m = self._KV_SECRET_RE.search(script)
        if kv_m:
            if not token:
                out.append("curl: the script has no Authorization bearer token to send — mint one from "
                           "the IMDS endpoint first.")
                exit_code = 1
            else:
                vault_name, secret_name = kv_m.group(1), kv_m.group(2)
                vault_rec = next((r for r in self.state.values() if r.get("_type", "").lower() == "microsoft.keyvault/vaults"
                                  and r.get("name", "").lower() == vault_name.lower()), None)
                if not vault_rec:
                    out.append(json.dumps({"error": {"code": "VaultNotFound", "message": f"Vault '{vault_name}' was not found."}}))
                    exit_code = 1
                else:
                    decision = self._check_access(sub, vault_rec["id"],
                        {"principalId": principal_id, "action": "Microsoft.KeyVault/vaults/secrets/getSecret/action"})
                    allowed = decision["body"]["value"][0]["accessDecision"] == "Allowed"
                    if not allowed:
                        out.append(json.dumps({"error": {"code": "Forbidden", "message":
                            f"The managed identity does not have secrets/get permission on vault '{vault_name}'."}}))
                        exit_code = 1
                    elif self.kv_secrets_store is None:
                        out.append(json.dumps({"error": {"code": "ServiceUnavailable", "message":
                            "Key Vault secrets are not wired on this platform."}}))
                        exit_code = 1
                    else:
                        secret_rec = self.kv_secrets_store.get_secret(secret_name)
                        if not secret_rec or secret_rec.get("deleted") or not secret_rec.get("versions"):
                            out.append(json.dumps({"error": {"code": "SecretNotFound", "message":
                                f"A secret with (name/id) {secret_name} was not found in this key vault."}}))
                            exit_code = 1
                        else:
                            ver = secret_rec["versions"].get(secret_rec["current"])
                            out.append(json.dumps({"value": ver.get("value") if ver else None}))

        if not imds_m and not kv_m:
            echo_m = self._ECHO_RE.match(stripped)
            osp = rec.get("properties", {}).get("osProfile", {})
            if echo_m:
                out.append(echo_m.group(1).strip().strip("\"'"))
            elif re.fullmatch(r"hostname", stripped, re.IGNORECASE):
                out.append(osp.get("computerName") or rec.get("name") or "")
            elif re.fullmatch(r"whoami", stripped, re.IGNORECASE):
                out.append(osp.get("adminUsername") or "")
            elif re.fullmatch(r"date|Get-Date", stripped, re.IGNORECASE):
                out.append(_now())
            elif re.fullmatch(r"uname(?:\s+-a)?", stripped, re.IGNORECASE):
                img = rec.get("properties", {}).get("storageProfile", {}).get("imageReference", {})
                out.append(f"Linux {rec.get('name')} {img.get('publisher', '')}/{img.get('offer', '')}:{img.get('sku', '')}")
            else:
                exit_code = 1
                out.append("Vyomi's Run command simulator only understands echo/Write-Output/Write-Host, hostname, "
                           "whoami, date/Get-Date, uname, and the IMDS-token + Key Vault secret-fetch pattern used to "
                           "demonstrate managed-identity authorization — this script was not recognized, so nothing "
                           "was executed.")

        message = "\n".join(out)
        return {"value": [
            {"code": "ComponentStatus/StdOut/succeeded" if exit_code == 0 else "ComponentStatus/StdOut/failed",
             "level": "Info", "displayStatus": "Provisioning succeeded" if exit_code == 0 else "Provisioning failed",
             "message": message},
            {"code": "ComponentStatus/StdErr/succeeded", "level": "Info",
             "displayStatus": "Provisioning succeeded", "message": ""},
        ]}

    def _sql_import_export(self, action, type_chain, parent_rid, payload, sub, rg):
        """Microsoft.Sql database export (POST .../databases/{db}/export) and import
        (POST .../databases/{db}/import, or .../servers/{s}/import for a new database):
        the .bacpac goes to / comes from the SIMULATOR's Azure Blob store at storageUri
        (core/azure_sql_core.export_database / import_database) — never the internet."""
        from core import azure_sql_core as az_sql
        on_database = len(type_chain) >= 4 and type_chain[2].lower() == "databases"
        parts = parent_rid.split("/")
        low = [x.lower() for x in parts]
        server = parts[low.index("servers") + 1] if "servers" in low else ""
        if not self.state.get(parent_rid.lower()):
            what = "Database" if on_database else "Server"
            return _err(404, "ResourceNotFound", f"{what} '{parts[-1]}' not found.")
        uri = str(payload.get("storageUri") or "").strip()
        if not uri:
            return _err(400, "InvalidParameterValue", "storageUri is required.")
        if on_database:
            database = parts[-1]
        else:
            database = str(payload.get("databaseName") or "").strip()
            if not database:
                return _err(400, "InvalidParameterValue", "databaseName is required to import a new database.")
        if self.sql_store is None or self.blob_store is None:
            return _err(503, "ServiceUnavailable", "Database import/export is not wired on this platform.")
        if action == "export":
            ok, code, message, _size = az_sql.export_database(self.sql_store, server, database, self.blob_store,
                                                             uri, arm_state=self.state)
        else:
            ok, code, message = az_sql.import_database(self.sql_store, server, database, self.blob_store,
                                                       uri, arm_state=self.state)
        if not ok:
            return _err(404 if code.endswith("NotFound") else 400, code, message)
        db_rid = (parent_rid if on_database else
                  f"{parent_rid}/databases/{database}")
        if not on_database and not self.state.get(db_rid.lower()):
            server_rec = self.state.get(parent_rid.lower()) or {}
            self.handle("PUT", db_rid, {"api-version": "2021-11-01"},
                        {"location": server_rec.get("location", "eastus"), "properties": {}})
        self._record_activity(db_rid, f"Microsoft.Sql/servers/databases/{action}/action", sub)
        return _ok({"id": f"{db_rid}/importExportOperationResults/{uuid.uuid4()}",
                    "type": "Microsoft.Sql/servers/databases/importExportOperationResults",
                    "properties": {"requestType": "Export" if action == "export" else "Import",
                                   "serverName": server, "databaseName": database, "status": "Succeeded",
                                   "lastModifiedTime": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                   "blobUri": uri, "errorMessage": None}})

    def _cosmos_keys_action(self, action, account_name, parent_rid, payload):
        """Microsoft.DocumentDB/databaseAccounts listKeys / listReadOnlyKeys /
        listConnectionStrings / regenerateKey — the real Cosmos ARM response shapes
        (NOT the generic storage-style {"keys": [...]}), so the account's Keys blade
        shows the same fields az cosmosdb / azure-mgmt-cosmosdb would get back."""
        rec = self.state.get(parent_rid.lower()) if parent_rid else None
        if not rec:
            return _err(404, "ResourceNotFound", f"Database account '{account_name}' not found.")
        keys = rec.setdefault("_cosmoskeys", {
            k: base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes).decode()
            for k in ("primaryMasterKey", "secondaryMasterKey", "primaryReadonlyMasterKey", "secondaryReadonlyMasterKey")
        })
        if action == "listkeys":
            return _ok({k: keys[k] for k in ("primaryMasterKey", "secondaryMasterKey", "primaryReadonlyMasterKey", "secondaryReadonlyMasterKey")})
        if action == "listreadonlykeys":
            return _ok({k: keys[k] for k in ("primaryReadonlyMasterKey", "secondaryReadonlyMasterKey")})
        if action == "listconnectionstrings":
            uri = f"https://{account_name}.documents.azure.com:443/"
            cs = lambda desc, key: {"connectionString": f"AccountEndpoint={uri};AccountKey={key};", "description": desc}
            return _ok({"connectionStrings": [
                cs("Primary SQL Connection String", keys["primaryMasterKey"]),
                cs("Secondary SQL Connection String", keys["secondaryMasterKey"]),
                cs("Primary Read-Only SQL Connection String", keys["primaryReadonlyMasterKey"]),
                cs("Secondary Read-Only SQL Connection String", keys["secondaryReadonlyMasterKey"]),
            ]})
        # regenerateKey: body {"keyKind": "primary" | "secondary" | "primaryReadonly" | "secondaryReadonly"}
        field = {"primary": "primaryMasterKey", "secondary": "secondaryMasterKey",
                "primaryreadonly": "primaryReadonlyMasterKey", "secondaryreadonly": "secondaryReadonlyMasterKey",
                }.get(str(payload.get("keyKind", "primary")).lower())
        if not field:
            return _err(400, "BadRequest", f"Unknown keyKind '{payload.get('keyKind')}'.")
        keys[field] = base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes).decode()
        return _ok({"status": "Succeeded"})

    def _cosmos_failover_action(self, account_name, parent_rid, payload):
        """Microsoft.DocumentDB/databaseAccounts/{name}/failoverPriorityChange — the real
        action behind the Replicate data globally blade's Manual Failover button. ENFORCED for
        real: it reassigns which configured region is the write region (failoverPriority 0) and
        updates location/writeLocations/readLocations to match — Vyomi still has one logical
        region underneath, so the promoted region doesn't get its own separate data-plane copy
        (azure.cosmos.replicate_data_globally)."""
        rec = self.state.get(parent_rid.lower()) if parent_rid else None
        if not rec:
            return _err(404, "ResourceNotFound", f"Database account '{account_name}' not found.")
        policies = payload.get("failoverPolicies")
        if not isinstance(policies, list) or not policies:
            return _err(400, "BadRequest", "failoverPolicies is required.")
        locations = rec.get("properties", {}).get("locations") or []
        by_name = {l.get("locationName"): dict(l) for l in locations}
        if not by_name:
            return _err(400, "BadRequest", "This account has no configured regions to fail over between.")
        seen = set()
        for p in policies:
            name, prio = p.get("locationName"), p.get("failoverPriority")
            if name not in by_name:
                return _err(400, "BadRequest", f"Location '{name}' is not configured on this account.")
            if not isinstance(prio, int) or prio < 0:
                return _err(400, "BadRequest", "failoverPriority must be a non-negative integer.")
            by_name[name]["failoverPriority"] = prio
            seen.add(name)
        if seen != set(by_name.keys()):
            return _err(400, "BadRequest", "failoverPolicies must list every region configured on the account.")
        prios = sorted(l["failoverPriority"] for l in by_name.values())
        if prios != list(range(len(prios))):
            return _err(400, "BadRequest",
                        "failoverPriority values must be a 0-based, gap-free sequence with exactly one region at priority 0.")
        new_locations = sorted(by_name.values(), key=lambda l: l["failoverPriority"])
        rec["properties"]["locations"] = new_locations
        primary = new_locations[0]["locationName"]
        rec["location"] = primary
        rec["properties"]["writeLocations"] = [{"locationName": primary, "failoverPriority": 0}]
        rec["properties"]["readLocations"] = [{"locationName": l["locationName"], "failoverPriority": l["failoverPriority"]} for l in new_locations]
        _record_activity(account_name, "Failover", f"Microsoft.DocumentDB/databaseAccounts '{account_name}' promoted '{primary}' to the write region")
        return _ok(None, status=202)

    def _apim_namedvalue_listvalue(self, nv_name, parent_rid):
        """Microsoft.ApiManagement/service/namedValues/{name}/listValue — the real action behind
        a named value's "Show value" eye icon. For a plain/secret named value this is just
        `properties.value`; for a Key Vault reference (`properties.keyVault.secretIdentifier`)
        the real portal resolves it against the live vault — ENFORCED here for real against
        THIS space's OWN Key Vault secrets store (azure_keyvault_secrets_core's KvStore, shared
        via aws_wire_router.AwsWireRouter.__init__), since a Key Vault reference pointing at a
        vault/secret that was never created (or has been deleted) is a genuine 400 in Azure too
        (azure.apim.namedvalues.keyvaultref)."""
        rec = self.state.get(parent_rid.lower()) if parent_rid else None
        if not rec:
            return _err(404, "ResourceNotFound", f"Named value '{nv_name}' not found.")
        props = rec.get("properties") or {}
        secret_id = (props.get("keyVault") or {}).get("secretIdentifier")
        if not secret_id:
            return _ok({"value": props.get("value") or ""})
        secret_name, version = _parse_kv_secret_identifier(secret_id)
        store = self.kv_secrets_store
        secret_rec = store.get_secret(secret_name) if store and secret_name else None
        if not secret_rec or secret_rec.get("deleted") or not secret_rec.get("versions"):
            return _err(400, "KeyVaultErrorSecretNotFound",
                        f"Named value '{nv_name}' references Key Vault secret '{secret_name}', which was not found.")
        ver = secret_rec["versions"].get(version or secret_rec["current"])
        if not ver:
            return _err(400, "KeyVaultErrorSecretNotFound",
                        f"Named value '{nv_name}' references a version of '{secret_name}' that was not found.")
        return _ok({"value": ver.get("value") or ""})

    # Client-side legacy-protocol customProperties keys that gate a test connection's
    # `protocol`, keyed by the same short name the console's dialog sends.
    _APIM_CLIENT_PROTOCOL_KEYS = {
        "tls10": "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls10",
        "tls11": "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls11",
        "ssl30": "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Ssl30",
    }

    def _apim_test_connect(self, api_name, parent_rid, payload):
        """Microsoft.ApiManagement/service/apis/{name}/testConnect — a Vyomi-only action (real
        Azure's "Test" console tab makes a live HTTPS call to the managed gateway, which this
        simulator never does — see "Nothing leaves the simulator"). It instead replays the two
        checks the real gateway performs before it would ever forward a request, so toggling
        either setting has a genuine, observable effect instead of being pure stored config:

        1. The client TLS protocol (`protocol`, one of tls10/tls11/ssl30/tls12) against this
           service's own Protocols + ciphers customProperties (azure.apim.service.protocols) —
           tls12 is always accepted (Vyomi doesn't model disabling the modern default).
        2. The subscription key (`subscriptionKey`) against this service's real Subscriptions
           (azure.apim.subscriptions.crud) — any ACTIVE subscription grants access, since
           product<->API association isn't modeled (azure.apim.apis.crud limitation)."""
        api_rec = self.state.get(parent_rid.lower()) if parent_rid else None
        if not api_rec:
            return _err(404, "ResourceNotFound", f"API '{api_name}' not found.")
        svc_rid = "/".join(parent_rid.split("/")[:-2])
        svc_rec = self.state.get(svc_rid.lower())
        if not svc_rec:
            return _err(404, "ResourceNotFound", "API Management service not found.")

        protocol = str(payload.get("protocol") or "tls12").lower()
        custom = (svc_rec.get("properties") or {}).get("customProperties") or {}
        prop_key = self._APIM_CLIENT_PROTOCOL_KEYS.get(protocol)
        if prop_key and custom.get(prop_key) != "True":
            return _err(400, "TlsVersionNotSupported",
                        f"The gateway does not accept {protocol.upper()} client connections — "
                        f"it is disabled under Protocols + ciphers.")

        sub_key = payload.get("subscriptionKey") or ""
        if not sub_key:
            return _err(401, "AccessDenied",
                        "Access denied due to missing subscription key. Include a subscription key.")
        sub_prefix = (svc_rid + "/subscriptions/").lower()
        matched = next((r for k, r in self.state.items()
                         if k.startswith(sub_prefix)
                         and sub_key in ((r.get("properties") or {}).get("primaryKey"), (r.get("properties") or {}).get("secondaryKey"))), None)
        if not matched or (matched.get("properties") or {}).get("state", "active") != "active":
            return _err(401, "AccessDenied", "Access denied due to invalid subscription key.")
        return _ok({"status": 200, "message": "Connection accepted", "api": api_name,
                    "subscriptionId": matched.get("name"), "protocol": protocol})

    def _aks_action(self, action, cluster_name, parent_rid, payload):
        """POST actions on Microsoft.ContainerService/managedClusters/{name}/<action> — start/stop
        (metadata-only power state, same convention as VM start/poweroff), runCommand (the AKS
        `az aks command invoke` action: kubectl against the cluster's Kubernetes object store in
        core/azure_aks_k8s_core.py — objects are stored, never scheduled; an object change triggers
        a Kubescape rescan for Defender for Cloud when its Containers plan is on) and the two
        listCluster*Credential actions (a deterministic, clearly-fake kubeconfig — enough for the
        "Connect" blade to show *something* shaped like the real response)."""
        rec = self.state.get(parent_rid.lower()) if parent_rid else None
        if not rec:
            return _err(404, "ResourceNotFound", f"Managed cluster '{cluster_name}' not found.")
        props = rec.setdefault("properties", {})
        if action in ("start", "stop"):
            props["powerState"] = {"code": "Running" if action == "start" else "Stopped"}
            return _ok({"status": "Succeeded", "action": action, "powerState": props["powerState"],
                        "note": "metadata-only (no node VMs backing this cluster in-browser); logical state updated"})
        if action == "runcommand":
            if props.get("powerState", {}).get("code") == "Stopped":
                return _err(409, "ClusterNotRunning",
                            "The cluster is stopped. Start the cluster before running a command against it.")
            command = (payload or {}).get("command", "")
            if not str(command).strip():
                return _err(400, "InvalidParameter", "The value of parameter command is invalid: it must not be empty.")
            # kubectl against the cluster's Kubernetes object store (core/azure_aks_k8s_core.py):
            # objects are stored, never scheduled — no kubelet or container runtime runs.
            started = _now()
            res = k8s_engine.run_command(rec, str(command), (payload or {}).get("context"))
            if res["changed"]:
                sub = parent_rid.split("/")[2] if parent_rid.count("/") >= 2 else DEFAULT_SUBSCRIPTION
                if security_engine.plan_on(self.state, sub, "Containers"):
                    kubescape_engine.on_objects_changed(rec, rec.get("id") or parent_rid)
            rid = str(uuid.uuid4()).replace("-", "")
            result = {"provisioningState": "Succeeded", "exitCode": res["exitCode"], "startedAt": started,
                      "finishedAt": _now(), "logs": res["logs"], "reason": "" if res["exitCode"] == 0 else "CommandFailed"}
            # RunCommandResult ({id, properties}) as az aks command invoke reads it, plus the flat
            # fields earlier Vyomi clients read.
            return _ok({"id": rid, "properties": result, **result})
        if action in ("listclusterusercredential", "listclusteradmincredential"):
            user = "clusterUser" if action == "listclusterusercredential" else "clusterAdmin"
            fqdn = props.get("fqdn") or f"{cluster_name}.hcp.azmk8s.io"
            kubeconfig = (
                "apiVersion: v1\nkind: Config\nclusters:\n- name: " + cluster_name +
                "\n  cluster:\n    server: https://" + fqdn + ":443\n    certificate-authority-data: c2ltdWxhdGVk\n"
                "users:\n- name: " + user + "_" + cluster_name +
                "\n  user:\n    token: c2ltdWxhdGVk-not-a-real-credential\n"
                "contexts:\n- name: " + cluster_name + "\n  context:\n    cluster: " + cluster_name +
                "\n    user: " + user + "_" + cluster_name + "\ncurrent-context: " + cluster_name + "\n"
            )
            import base64
            return _ok({"kubeconfigs": [{"name": user, "value": base64.b64encode(kubeconfig.encode()).decode()}]})
        return _ok({})

    def _provider_info(self, namespace):
        types = [{"resourceType": c["type"], "apiVersions": [c["api_version"]],
                  "locations": [DEFAULT_LOCATION], "capabilities": "None"}
                 for c in CATALOG if c["namespace"].lower() == namespace.lower()]
        return {"id": f"/subscriptions/{DEFAULT_SUBSCRIPTION}/providers/{namespace}",
                "namespace": namespace, "registrationState": self.providers.get(namespace.lower(), "Registered"),
                "registrationPolicy": "RegistrationRequired", "resourceTypes": types}

    def _rg_key(self, sub, rg):
        return f"/subscriptions/{sub}/resourcegroups/{rg}".lower()

    def _default_rg_view(self, sub, rg):
        return {"id": f"/subscriptions/{sub}/resourceGroups/{rg}", "name": rg,
                "type": "Microsoft.Resources/resourceGroups", "location": DEFAULT_LOCATION,
                "tags": {}, "properties": {"provisioningState": "Succeeded"}}

    def _list_resource_groups(self, sub):
        out, seen = [], set()
        for rec in self.state.values():
            if rec.get("_sub") == sub and rec.get("_type", "").lower() == "microsoft.resources/resourcegroups":
                out.append(_view(rec))
                seen.add(rec["name"])
        for rec in self.state.values():   # implicit groups: resources created without an explicit PUT on the group
            if rec.get("_sub") == sub and rec.get("_rg") and rec["_rg"] not in seen:
                seen.add(rec["_rg"])
                out.append(self._default_rg_view(sub, rec["_rg"]))
        if DEFAULT_RG not in seen:
            out.append(self._default_rg_view(sub, DEFAULT_RG))
        return out

    def _resource_group_item(self, method, sub, rg, payload):
        payload = payload or {}
        key = self._rg_key(sub, rg)
        rid = f"/subscriptions/{sub}/resourceGroups/{rg}"
        implicit = any(r.get("_sub") == sub and r.get("_rg") == rg for r in self.state.values()) or rg == DEFAULT_RG

        if method == "GET":
            rec = self.state.get(key)
            if rec:
                return _ok(_view(rec))
            if implicit:
                return _ok(self._default_rg_view(sub, rg))
            return _err(404, "ResourceGroupNotFound", f"Resource group '{rg}' could not be found.")

        if method in ("PUT", "PATCH"):
            prior = self.state.get(key)
            # A PUT replaces the tag set exactly (like any generic catalog resource — see
            # AzureArm._upsert); a PATCH on an existing group merges it instead.
            rec = dict(prior) if (method == "PATCH" and prior) else {
                "id": rid, "name": rg, "type": "Microsoft.Resources/resourceGroups",
                "location": DEFAULT_LOCATION, "tags": {},
                "_type": "Microsoft.Resources/resourceGroups", "_sub": sub, "_created": _now(),
            }
            if payload.get("location"):
                rec["location"] = payload["location"]
            if isinstance(payload.get("tags"), dict):
                rec["tags"] = _merge(rec.get("tags", {}), payload["tags"]) if (method == "PATCH" and prior) else dict(payload["tags"])
            rec["id"], rec["name"], rec["type"] = rid, rg, "Microsoft.Resources/resourceGroups"
            rec["properties"] = {"provisioningState": "Succeeded"}
            self.state[key] = rec
            self._record_activity(rid, "Microsoft.Resources/resourceGroups/write", sub)
            return _ok(_view(rec), status=200)

        if method == "DELETE":
            existed = self.state.pop(key, None) is not None
            # Deleting a resource group cascades to every resource it contains (real ARM
            # behaviour) — including that group's own locks, extension resources, … but NOT
            # Activity log rows ("/__event__/" keys): real Azure keeps a deleted group's
            # history in the subscription-wide feed, it doesn't erase it.
            removed_any = False
            for k in [k for k, r in self.state.items()
                      if "/__event__/" not in k
                      and ((r.get("_sub") == sub and (r.get("_rg") or "") == rg) or k.startswith(key + "/providers/"))]:
                del self.state[k]
                removed_any = True
            if not (existed or removed_any or implicit):
                return _err(404, "ResourceGroupNotFound", f"Resource group '{rg}' could not be found.")
            self._record_activity(rid, "Microsoft.Resources/resourceGroups/delete", sub)
            return _ok(None, status=200)

        return _err(405, "MethodNotAllowed", f"{method} not allowed.")

    def _make_operation(self, resource_id, method, result=None):
        op_id = uuid.uuid4().hex
        now = _now()
        self.operations[op_id] = {"id": op_id, "name": op_id, "status": "Succeeded",
                                   "startTime": now, "endTime": now,
                                   "resourceId": resource_id, "method": method}
        if result:
            self.operations[op_id]["result"] = result
        return op_id
