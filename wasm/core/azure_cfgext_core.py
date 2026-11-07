# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure configuration-extension control plane (Nano / dev_server / unified-ingress core, substrate-free).

Real ARM validation + derived state for configuration surfaces that are plain ARM properties / children, stored in
the same flat ARM state map as ``azure_arm_core`` (keyed by lower-cased resource id). Hooks mirror
``azure_netsvc_core`` (handles / validate / after_put / before_delete):

* AKS ``managedClusters`` -- ``workloadAutoScalerProfile.keda.enabled`` (needs Kubernetes >= 1.23) and
  ``apiServerAccessProfile`` (authorizedIPRanges must be valid CIDRs, <= 200, not combined with a private cluster).
* ``Microsoft.KubernetesConfiguration/extensions`` on a managed cluster -- extensionType must be a known extension,
  version XOR autoUpgradeMinorVersion, releaseTrain, scope, one instance of a non-multi-instance extension per cluster.
* Cosmos DB accounts -- ``cors`` rules (<= 10, origins/methods/headers shape, maxAgeInSeconds) and the customer-managed
  key (``keyVaultKeyUri`` shape + vault must exist + ``defaultIdentity``); ``databaseAccounts/services/SqlDedicatedGateway``
  (NoSQL accounts only, instance size / count).
* Service Bus namespaces -- ``encryption`` (Premium only, Key Vault key + identity) and ``networkRuleSets/default``
  (Premium only, subnet must exist, IP rules valid).
* App Configuration stores -- the customer-managed key check lives in azure_appconfiguration_core._cmk_check (uses _check_key_uri here).
* API Management ``service/gateways/{gw}/apis/{api}`` -- gateway and API must exist (restricts an API to a self-hosted gateway).
* Virtual network subnets -- ``serviceEndpoints`` names, ``delegations`` serviceName, and the rule that a delegated
  subnet cannot also carry a private endpoint.

NOT modelled (honest limits, see core/capabilities/azure/*.json): the named Key Vault KEY is not looked up (keys live in the
Key Vault data plane store, outside ARM state), KEDA / extensions install no workload, the dedicated gateway has no cache. (Cosmos CORS rules and Service Bus network rules ARE enforced on the data plane - see
core/azure_cosmos_core.py and core/azure_netaccess.py.)
"""
from __future__ import annotations

try:
    from core import azure_flux_core as flux
except ImportError:                                  # Pyodide flat layout
    import azure_flux_core as flux                   # type: ignore
import ipaddress
import re
import uuid

AKS = "microsoft.containerservice/managedclusters"
COSMOS = "microsoft.documentdb/databaseaccounts"
COSMOS_SVC = "microsoft.documentdb/databaseaccounts/services"
SBNS = "microsoft.servicebus/namespaces"
SB_NETRULES = "microsoft.servicebus/namespaces/networkrulesets"
APPCFG = "microsoft.appconfiguration/configurationstores"
STORAGE = "microsoft.storage/storageaccounts"
SQL_LABEL = "microsoft.sql/servers/databases/schemas/tables/columns/sensitivitylabels"
SQL_RANKS = ("None", "Low", "Medium", "High", "Critical")
APIM = "microsoft.apimanagement/service"
APIM_DELETED = "microsoft.apimanagement/deletedservices"
APIM_GW_API = "microsoft.apimanagement/service/gateways/apis"
VNET = "microsoft.network/virtualnetworks"
PE = "microsoft.network/privateendpoints"
ASG = "microsoft.network/applicationsecuritygroups"
NIC = "microsoft.network/networkinterfaces"
NSG_RULE = "microsoft.network/networksecuritygroups/securityrules"
ENC_SCOPE = "microsoft.storage/storageaccounts/encryptionscopes"
BLOB_CONTAINER = "microsoft.storage/storageaccounts/blobservices/containers"

EXTENSIONS = {
    "microsoft.flux": {"multi": False, "scopes": ("cluster",)},
    "microsoft.azuremonitor.containers": {"multi": False, "scopes": ("cluster",)},
    "microsoft.dapr": {"multi": False, "scopes": ("cluster",)},
    "microsoft.azureml.kubernetes": {"multi": False, "scopes": ("cluster",)},
    "microsoft.azuredefender.kubernetes": {"multi": False, "scopes": ("cluster",)},
    "microsoft.openservicemesh": {"multi": False, "scopes": ("cluster",)},
    "microsoft.azurekeyvaultsecretsprovider": {"multi": False, "scopes": ("cluster",)},
    "microsoft.web.appservice": {"multi": False, "scopes": ("cluster",)},
    "microsoft.azurebackup.kubernetes": {"multi": False, "scopes": ("cluster",)},
    "microsoft.dataprotection.kubernetes": {"multi": False, "scopes": ("cluster",)},
    "microsoft.arc.containerstorage": {"multi": False, "scopes": ("cluster",)},
    "microsoft.workloadiam": {"multi": False, "scopes": ("cluster",)},
    "microsoft.containerstorage": {"multi": False, "scopes": ("cluster",)},
    "microsoft.ai.kaito": {"multi": False, "scopes": ("cluster",)},
    "microsoft.azure.kubernetesconfiguration.sample": {"multi": True, "scopes": ("cluster", "namespace")},
}
SERVICE_ENDPOINTS = {
    "microsoft.storage", "microsoft.sql", "microsoft.azurecosmosdb", "microsoft.keyvault", "microsoft.servicebus",
    "microsoft.eventhub", "microsoft.web", "microsoft.containerregistry", "microsoft.cognitiveservices",
    "microsoft.ai", "microsoft.azureactivedirectory",
}
DELEGATION_SERVICES = {
    "microsoft.web/serverfarms", "microsoft.containerinstance/containergroups", "microsoft.sql/managedinstances",
    "microsoft.dbforpostgresql/flexibleservers", "microsoft.dbformysql/flexibleservers", "microsoft.app/environments",
    "microsoft.netapp/volumes", "microsoft.batch/batchaccounts", "microsoft.databricks/workspaces",
    "microsoft.stream analytics/streamingjobs", "microsoft.kusto/clusters", "microsoft.machinelearningservices/workspaces",
    "microsoft.containerservice/managedclusters", "microsoft.apimanagement/service", "microsoft.logic/integrationserviceenvironments",
}
DEDICATED_SIZES = ("Cosmos.D4s", "Cosmos.D8s", "Cosmos.D16s")
CORS_METHODS = {"GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH", "*"}
KV_KEY_URI = re.compile(r"^https://([a-z][a-z0-9-]{1,22}[a-z0-9])\.vault\.azure\.net(?::443)?/keys/([A-Za-z0-9-]{1,127})(?:/([0-9a-fA-F]{32}))?/?$")


def _err(status: int, code: str, message: str) -> dict:
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def handles(full_type: str) -> bool:
    ft = full_type.lower()
    return flux.handles(ft) or ft in (AKS, COSMOS, COSMOS_SVC, SBNS, SB_NETRULES, VNET, APIM_GW_API, APIM, SQL_LABEL, STORAGE, ENC_SCOPE, BLOB_CONTAINER, ASG, NIC, NSG_RULE) or ft.endswith("/providers/extensions")


def _merged(existing, payload) -> dict:
    p = dict((existing or {}).get("properties") or {})
    p.update((payload or {}).get("properties") or {})
    return p


def _vault_exists(state: dict, name: str) -> bool:
    return any(isinstance(r, dict) and (r.get("_type") or "").lower() == "microsoft.keyvault/vaults"
               and str(r.get("name", "")).lower() == name.lower() for r in state.values())


# Key Vault data-plane lookup, injected by the substrate (offline appliance / Nano registry): callable(key_name, version|None)
# -> True (exists, enabled) | False (exists, disabled) | None (no such key). Unset (hermetic/ARM-only use) = not cross-checked.
# The Key Vault keys store is ONE keyspace shared by all vaults, so the lookup is by key name, not per vault.
KEY_LOOKUP = None


def set_key_lookup(fn) -> None:
    global KEY_LOOKUP
    KEY_LOOKUP = fn


def bind_key_store(store_or_getter) -> None:
    """Point the lookup at the Key Vault keys core's store (or a zero-arg callable returning it, for lazily-built stores)."""
    try:
        from core import azure_keyvault_keys_core as kvk
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import azure_keyvault_keys_core as kvk  # type: ignore

    def _lk(name, version):
        st = store_or_getter() if callable(store_or_getter) else store_or_getter
        if hasattr(st, "adopt"):
            st.adopt()
        return kvk.key_enabled(st, name, version)
    set_key_lookup(_lk)


def check_key_exists(vault: str, key_name: str, version, what: str):
    if KEY_LOOKUP is None or not key_name:
        return None
    try:
        st = KEY_LOOKUP(key_name, version or None)
    except Exception:
        return None
    if st is None:
        return _err(400, "KeyVaultKeyNotFound", f"The key '{key_name}' referenced by {what} was not found in Key Vault '{vault}'.")
    if st is False:
        return _err(400, "KeyVaultKeyDisabled", f"The key '{key_name}' referenced by {what} is disabled in Key Vault '{vault}'; a customer-managed key must be enabled.")
    return None


def _check_key_uri(state: dict, uri: str, what: str):
    m = KV_KEY_URI.match(str(uri or ""))
    if not m:
        return _err(400, "InvalidKeyVaultKeyUri", f"{what} must be a Key Vault key URI of the form https://<vault>.vault.azure.net/keys/<name>[/<version>]; got '{uri}'.")
    if not _vault_exists(state, m.group(1)):
        return _err(400, "KeyVaultNotFound", f"The Key Vault '{m.group(1)}' referenced by {what} does not exist in this subscription.")
    return check_key_exists(m.group(1), m.group(2), m.group(3) if m.lastindex and m.lastindex >= 3 else None, what)


def _has_identity(rec_or_payload: dict) -> bool:
    ident = (rec_or_payload or {}).get("identity") or {}
    t = str(ident.get("type") or "None").lower()
    return t != "none" and (("systemassigned" in t) or bool(ident.get("userAssignedIdentities")))


def _k8s_minor(v) -> tuple:
    m = re.match(r"^(\d+)\.(\d+)", str(v or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _cidr_ok(s: str) -> bool:
    try:
        ipaddress.ip_network(s, strict=False)
        return True
    except ValueError:
        return False


# ── pre-write validation ────────────────────────────────────────────────────────────────
def validate(state: dict, full_type: str, rid: str, payload: dict, existing: dict | None, sub: str, rg: str | None):
    ft = full_type.lower()
    if flux.handles(ft):
        return flux.validate(state, ft, rid, payload, existing, sub, rg)
    props = _merged(existing, payload)
    if ft == AKS:
        return _validate_aks(props, payload, existing)
    if ft.endswith("/providers/extensions"):
        return _validate_extension(state, rid, payload, existing)
    if ft == COSMOS:
        return _validate_cosmos(state, props, payload, existing)
    if ft == COSMOS_SVC:
        return _validate_cosmos_service(state, rid, payload)
    if ft == SBNS:
        return _validate_sb_ns(state, payload, existing, props)
    if ft == SB_NETRULES:
        return _validate_sb_rules(state, rid, payload)
    if ft == VNET:
        return _validate_vnet(state, rid, payload, props)
    if ft == APIM_GW_API:
        return _validate_gw_api(state, rid)
    if ft == APIM:
        return _validate_apim_soft_deleted(state, rid, payload, existing)
    if ft == SQL_LABEL:
        return _validate_sql_label(state, rid, payload)
    if ft == NIC:
        return _validate_asg_refs(state, [g for c in (props.get("ipConfigurations") or []) for g in ((c.get("properties") or {}).get("applicationSecurityGroups") or [])],
                                  (existing or {}).get("location") or (payload or {}).get("location"), "network interface", per_ipconfig=props.get("ipConfigurations"))
    if ft == NSG_RULE:
        return _validate_nsg_rule_asgs(state, props)
    if ft == ENC_SCOPE:
        return _validate_enc_scope(state, rid, payload, existing)
    if ft == BLOB_CONTAINER:
        return _validate_blob_container(state, rid, payload, existing)
    if ft == STORAGE:
        bypass = (props.get("networkAcls") or {}).get("bypass")
        if bypass is not None:
            toks = [t.strip() for t in str(bypass).split(",") if t.strip()]
            if not toks or any(t not in ("None", "AzureServices", "Logging", "Metrics") for t in toks) or ("None" in toks and len(toks) > 1):
                return _err(400, "InvalidNetworkAclsBypass", "networkAcls.bypass must be None or a comma separated combination of AzureServices, Logging and Metrics.")
        return _validate_vnet_rule_endpoints(state, [r.get("id") for r in (props.get("networkAcls") or {}).get("virtualNetworkRules") or []], "Microsoft.Storage")
    return None


def _validate_vnet_rule_endpoints(state: dict, subnet_ids: list, service: str):
    """A virtual-network firewall rule may only name a subnet that exists and carries the service's endpoint (azure.vnets.subnetservices:
    the same endpoint list the data planes check when they evaluate the rule)."""
    for sid in subnet_ids:
        sid = str(sid or "")
        vnet_id, _, sname = sid.lower().rpartition("/subnets/")
        vnet = state.get(vnet_id)
        sub = next((x for x in ((vnet or {}).get("properties") or {}).get("subnets") or [] if str(x.get("name", "")).lower() == sname), None)
        if sub is None:
            return _err(400, "SubnetNotFound", f"The subnet '{sid}' referenced by a virtual network rule does not exist.")
        eps = [str((e.get("service") if isinstance(e, dict) else e) or "").lower() for e in ((sub.get("properties") or {}).get("serviceEndpoints") or [])]
        if service.lower() not in eps:
            return _err(400, "SubnetsHaveNoServiceEndpointsConfigured", f"Subnet '{sub.get('name')}' does not have the {service} service endpoint enabled, so it cannot be used in a virtual network rule.")
    return None


def _validate_asg_refs(state: dict, refs: list, location, what: str, per_ipconfig=None):
    """A NIC ip configuration may join up to 20 application security groups; each must exist and live in the NIC's region."""
    for c in per_ipconfig or []:
        if len((c.get("properties") or {}).get("applicationSecurityGroups") or []) > 20:
            return _err(400, "ApplicationSecurityGroupLimitExceeded", "A network interface IP configuration can be a member of at most 20 application security groups.")
    for g in refs:
        gid = str((g or {}).get("id") or "")
        rec = state.get(gid.lower())
        if rec is None or (rec.get("_type") or "").lower() != ASG:
            return _err(404, "ResourceNotFound", f"The application security group '{gid.rsplit('/', 1)[-1]}' referenced by the {what} was not found.")
        if location and str(rec.get("location") or "").replace(" ", "").lower() != str(location).replace(" ", "").lower():
            return _err(400, "ApplicationSecurityGroupLocationMismatch", f"The application security group '{rec['name']}' is in {rec.get('location')} but the {what} is in {location}; they must share a region.")
    return None


def _validate_nsg_rule_asgs(state: dict, props: dict):
    """Security-rule ASG endpoints must exist and cannot be combined with an address prefix other than '*'."""
    for side in ("source", "destination"):
        groups = props.get(f"{side}ApplicationSecurityGroups") or []
        if not groups:
            continue
        prefixes = [x for x in [props.get(f"{side}AddressPrefix")] + list(props.get(f"{side}AddressPrefixes") or []) if x]
        if any(x != "*" for x in prefixes):
            return _err(400, "SecurityRuleParameterContainsConflictingValues", f"{side}ApplicationSecurityGroups cannot be combined with a {side}AddressPrefix other than '*'.")
        for g in groups:
            gid = str((g or {}).get("id") or "")
            rec = state.get(gid.lower())
            if rec is None or (rec.get("_type") or "").lower() != ASG:
                return _err(404, "ResourceNotFound", f"The application security group '{gid.rsplit('/', 1)[-1]}' referenced by the security rule was not found.")
    return None


_SCOPE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", re.I)


def _acct_of(state: dict, rid: str):
    aid = rid[: rid.lower().index("/storageaccounts/") + len("/storageaccounts/")] + rid.split("/")[8]
    return aid, state.get(aid.lower())


def _validate_enc_scope(state: dict, rid: str, payload: dict, existing):
    """Storage encryption scopes: 3-63 chars, source Microsoft.Storage | Microsoft.KeyVault (the latter needs a Key Vault
    key URI whose vault exists), state Enabled|Disabled, requireInfrastructureEncryption immutable once set."""
    aid, acct = _acct_of(state, rid)
    if acct is None:
        return _err(404, "ResourceNotFound", f"The storage account '{aid.rsplit('/', 1)[-1]}' was not found.")
    name = rid.rsplit("/", 1)[-1]
    if not _SCOPE_NAME.match(name) or "--" in name:
        return _err(400, "InvalidResourceName", "Encryption scope names are 3-63 characters: lowercase letters, numbers and single hyphens.")
    p = _merged(existing, payload)
    src = p.get("source") or "Microsoft.Storage"
    if src not in ("Microsoft.Storage", "Microsoft.KeyVault"):
        return _err(400, "InvalidEncryptionScopeSource", "source must be Microsoft.Storage or Microsoft.KeyVault.")
    if p.get("state") not in (None, "Enabled", "Disabled"):
        return _err(400, "InvalidEncryptionScopeState", "state must be Enabled or Disabled.")
    if existing is not None and (existing.get("properties") or {}).get("source") not in (None, src):
        return _err(400, "EncryptionScopeSourceImmutable", "The source of an encryption scope cannot be changed after creation.")
    if src == "Microsoft.KeyVault":
        kv = p.get("keyVaultProperties") or {}
        bad = _check_key_uri(state, kv.get("keyUri"), "keyVaultProperties.keyUri")
        if bad:
            return bad
    ex_inf = (existing or {}).get("properties", {}).get("requireInfrastructureEncryption")
    if existing is not None and "requireInfrastructureEncryption" in (payload.get("properties") or {}) \
            and bool(payload["properties"]["requireInfrastructureEncryption"]) != bool(ex_inf):
        return _err(400, "RequireInfrastructureEncryptionImmutable", "requireInfrastructureEncryption cannot be changed after the scope is created.")
    return None


def _validate_blob_container(state: dict, rid: str, payload: dict, existing):
    """blobServices/default/containers: defaultEncryptionScope must name an Enabled encryption scope on the account;
    immutableStorageWithVersioning (version-level WORM) needs the account flag, and cannot be switched off once on."""
    aid, acct = _acct_of(state, rid)
    if acct is None:
        return _err(404, "ResourceNotFound", f"The storage account '{aid.rsplit('/', 1)[-1]}' was not found.")
    p = _merged(existing, payload)
    scope = p.get("defaultEncryptionScope")
    if scope and scope != "$account-encryption-key":
        s = state.get(f"{aid}/encryptionScopes/{scope}".lower())
        if s is None:
            return _err(404, "EncryptionScopeNotFound", f"The encryption scope '{scope}' does not exist on this storage account.")
        if (s.get("properties") or {}).get("state", "Enabled") != "Enabled":
            return _err(400, "EncryptionScopeDisabled", f"The encryption scope '{scope}' is disabled.")
    if p.get("denyEncryptionScopeOverride") and not (scope and scope != "$account-encryption-key"):
        return _err(400, "InvalidRequest", "denyEncryptionScopeOverride needs a defaultEncryptionScope.")
    wants = (p.get("immutableStorageWithVersioning") or {}).get("enabled")
    if wants:
        acct_on = ((acct.get("properties") or {}).get("immutableStorageWithVersioning") or {}).get("enabled")
        if not acct_on:
            return _err(409, "ImmutableStorageWithVersioningNotEnabled", "Version-level immutability support must be enabled on the storage account before it can be enabled on a container.")
    if existing is not None and ((existing.get("properties") or {}).get("immutableStorageWithVersioning") or {}).get("enabled") and not wants:
        return _err(409, "ImmutableStorageWithVersioningCannotBeDisabled", "Version-level immutability cannot be disabled on a container once enabled.")
    return None


def _validate_sql_label(state: dict, rid: str, payload: dict):
    """Data Discovery & Classification: a column sensitivity label ('current'). The database must exist; rank is one of
    None/Low/Medium/High/Critical; a label name or an information type is required (strings, at most 128 characters)."""
    db_id = rid[: rid.lower().index("/schemas/")]
    if state.get(db_id.lower()) is None:
        return _err(404, "ResourceNotFound", f"The database '{db_id.rsplit('/', 1)[-1]}' was not found.")
    if rid.rsplit("/", 1)[-1] != "current":
        return _err(400, "InvalidParameter", "The sensitivity label name must be 'current'.")
    p = (payload or {}).get("properties") or {}
    if not (p.get("labelName") or p.get("informationType")):
        return _err(400, "InvalidParameter", "A sensitivity label needs a labelName or an informationType.")
    for k in ("labelName", "labelId", "informationType", "informationTypeId"):
        if p.get(k) is not None and (not isinstance(p[k], str) or len(p[k]) > 128):
            return _err(400, "InvalidParameter", f"{k} must be a string of at most 128 characters.")
    if p.get("rank") is not None and p["rank"] not in SQL_RANKS:
        return _err(400, "InvalidParameter", f"rank must be one of {', '.join(SQL_RANKS)}.")
    return None


# ── API Management soft-delete (deletedservices) ────────────────────────────────────────
def _deleted_key(rid: str, location: str) -> str:
    parts = rid.split("/")
    return f"/subscriptions/{parts[2]}/providers/Microsoft.ApiManagement/locations/{(location or 'eastus').replace(' ', '').lower()}/deletedservices/{parts[-1]}".lower()


def _find_deleted(state: dict, sub: str, name: str):
    pre = f"/subscriptions/{sub}/providers/microsoft.apimanagement/locations/".lower()
    for k, r in state.items():
        if k.startswith(pre) and k.endswith("/deletedservices/" + name.lower()):
            return k, r
    return None, None


def _validate_apim_soft_deleted(state: dict, rid: str, payload: dict, existing):
    if existing is not None:
        return None
    key, gone = _find_deleted(state, rid.split("/")[2], rid.rsplit("/", 1)[-1])
    if gone is None:
        if ((payload or {}).get("properties") or {}).get("restore"):
            return _err(404, "ResourceNotFound", f"There is no soft-deleted API Management service named '{rid.rsplit('/', 1)[-1]}' to restore.")
        return None
    if not ((payload or {}).get("properties") or {}).get("restore"):
        return _err(409, "ServiceAlreadyExistsInSoftDeletedState", f"API Management service '{gone['name']}' is in a soft-deleted state; restore it with properties.restore=true or purge it before reusing the name.")
    return None


def apim_deleted_dispatch(state: dict, method: str, sub: str, chain: list, payload=None):
    """Microsoft.ApiManagement/deletedservices (GET list, GET/DELETE by name at locations/{loc}/deletedservices/{name})."""
    pre = f"/subscriptions/{sub}/providers/microsoft.apimanagement/locations/".lower()
    rows = [r for k, r in state.items() if k.startswith(pre) and (r.get("_type") or "") == APIM_DELETED]
    view = lambda r: {k: v for k, v in r.items() if not k.startswith("_")}
    if len(chain) == 1 and chain[0].lower() == "deletedservices" and method == "GET":
        return {"status": 200, "headers": {}, "body": {"value": [view(r) for r in rows]}}
    if len(chain) == 4 and chain[0].lower() == "locations" and chain[2].lower() == "deletedservices":
        name = chain[3]
        rec = next((r for r in rows if r["name"].lower() == name.lower() and r["id"].lower().split("/locations/")[1].startswith(chain[1].lower() + "/")), None)
        if rec is None:
            return _err(404, "ResourceNotFound", f"The soft-deleted API Management service '{name}' was not found.")
        if method == "GET":
            return {"status": 200, "headers": {}, "body": view(rec)}
        if method == "DELETE":
            state.pop(rec["id"].lower(), None)
            return {"status": 200, "headers": {}, "body": None}
    return _err(405, "MethodNotAllowed", f"{method} is not supported on this deletedservices path.")


def _validate_gw_api(state: dict, rid: str):
    """service/gateways/{gw}/apis/{api}: the self-hosted gateway and the API must both exist in the service."""
    low = rid.lower()
    gw_id = low[: low.index("/apis/")] if "/apis/" in low else low
    svc_id = gw_id[: gw_id.index("/gateways/")]
    api_name = rid.rsplit("/", 1)[-1]
    gw = state.get(gw_id)
    if gw is None:
        return _err(404, "ResourceNotFound", f"The gateway '{gw_id.rsplit('/', 1)[-1]}' was not found.")
    if state.get(f"{svc_id}/apis/{api_name}".lower()) is None:
        return _err(404, "ResourceNotFound", f"The API '{api_name}' was not found in the API Management service.")
    return None


def _validate_aks(props: dict, payload: dict, existing):
    keda = ((props.get("workloadAutoScalerProfile") or {}).get("keda"))
    if keda is not None:
        if not isinstance(keda, dict) or not isinstance(keda.get("enabled"), bool):
            return _err(400, "InvalidParameter", "workloadAutoScalerProfile.keda.enabled must be a boolean.")
        if keda["enabled"] and _k8s_minor(props.get("kubernetesVersion")) < (1, 23) and props.get("kubernetesVersion"):
            return _err(400, "FeatureNotSupportedForKubernetesVersion", f"KEDA requires Kubernetes version 1.23 or later; the cluster runs {props.get('kubernetesVersion')}.")
    api = props.get("apiServerAccessProfile")
    if api is not None:
        ranges = api.get("authorizedIPRanges") or []
        if ranges and api.get("enablePrivateCluster"):
            return _err(400, "InvalidParameter", "Authorized IP ranges cannot be configured on a private cluster.")
        if len(ranges) > 200:
            return _err(400, "InvalidParameter", "A maximum of 200 authorized IP ranges can be specified.")
        for r in ranges:
            if not isinstance(r, str) or not _cidr_ok(r) or "/" not in r:
                return _err(400, "InvalidParameter", f"authorizedIPRanges entry '{r}' is not a valid CIDR range.")
    return None


def _validate_extension(state: dict, rid: str, payload: dict, existing):
    cluster_id = rid[: rid.lower().rindex("/providers/microsoft.kubernetesconfiguration/")] if "/providers/microsoft.kubernetesconfiguration/" in rid.lower() else rid
    cluster = state.get(cluster_id.lower())
    if cluster is None or (cluster.get("_type") or "").lower() != AKS:
        return _err(404, "ParentResourceNotFound", f"The managed cluster '{cluster_id.rsplit('/', 1)[-1]}' was not found.")
    p = (payload or {}).get("properties") or {}
    et = str(p.get("extensionType") or (existing or {}).get("properties", {}).get("extensionType") or "").lower()
    if not et:
        return _err(400, "InvalidParameter", "properties.extensionType is required.")
    spec = EXTENSIONS.get(et)
    if spec is None:
        return _err(400, "ExtensionTypeNotFound", f"Extension type '{et}' was not found in the extension registry.")
    name = rid.rsplit("/", 1)[-1]
    if not re.match(r"^[a-z0-9]([a-z0-9-]{0,251}[a-z0-9])?$", name):
        return _err(400, "InvalidParameter", f"Extension name '{name}' must be lower case alphanumeric/hyphen, 1-253 characters.")
    if p.get("version") and p.get("autoUpgradeMinorVersion") is True:
        return _err(400, "InvalidParameter", "autoUpgradeMinorVersion must be false when an explicit version is specified.")
    if p.get("releaseTrain") and str(p["releaseTrain"]).lower() not in ("stable", "preview"):
        return _err(400, "InvalidParameter", "releaseTrain must be 'Stable' or 'Preview'.")
    scope = p.get("scope") or {}
    kind = "namespace" if scope.get("namespace") else "cluster"
    if kind not in spec["scopes"]:
        return _err(400, "InvalidParameter", f"Extension type '{et}' does not support {kind} scope.")
    for k, v in (p.get("configurationSettings") or {}).items():
        if not isinstance(v, str):
            return _err(400, "InvalidParameter", f"configurationSettings['{k}'] must be a string.")
    if not spec["multi"]:
        for k, r in state.items():
            if isinstance(r, dict) and k.startswith(cluster_id.lower() + "/providers/microsoft.kubernetesconfiguration/extensions/") \
                    and str((r.get("properties") or {}).get("extensionType", "")).lower() == et and r.get("name") != name:
                return _err(409, "ExtensionAlreadyInstalled", f"Extension type '{et}' is already installed on this cluster as '{r.get('name')}'; only one instance is supported.")
    return None


def _validate_cosmos(state: dict, props: dict, payload: dict, existing):
    bad = _validate_vnet_rule_endpoints(state, [r.get("id") for r in props.get("virtualNetworkRules") or [] if isinstance(r, dict)], "Microsoft.AzureCosmosDB")
    if bad:
        return bad
    cors = props.get("cors")
    if cors is not None:
        if not isinstance(cors, list):
            return _err(400, "BadRequest", "properties.cors must be a list of CORS rules.")
        if len(cors) > 10:
            return _err(400, "BadRequest", "A maximum of 10 CORS rules can be specified on a Cosmos DB account.")
        for i, rule in enumerate(cors):
            origins = str((rule or {}).get("allowedOrigins") or "").strip()
            if not origins:
                return _err(400, "BadRequest", f"cors[{i}].allowedOrigins is required.")
            for o in origins.split(","):
                o = o.strip()
                if o != "*" and not re.match(r"^https?://[^\s/]+$|^https?://\*\.[^\s/]+$", o):
                    return _err(400, "BadRequest", f"cors[{i}].allowedOrigins entry '{o}' is not a valid origin (scheme://host[:port], a *.domain wildcard, or *).")
            for m in str(rule.get("allowedMethods") or "").split(","):
                if m.strip() and m.strip().upper() not in CORS_METHODS:
                    return _err(400, "BadRequest", f"cors[{i}].allowedMethods contains unsupported method '{m.strip()}'.")
            age = rule.get("maxAgeInSeconds")
            if age is not None and (not isinstance(age, int) or isinstance(age, bool) or not 0 <= age <= 2147483647):
                return _err(400, "BadRequest", f"cors[{i}].maxAgeInSeconds must be an integer between 0 and 2147483647.")
    uri = props.get("keyVaultKeyUri")
    if uri:
        e = _check_key_uri(state, uri, "properties.keyVaultKeyUri")
        if e:
            return e
        di = props.get("defaultIdentity") or ""
        if not (_has_identity(payload) or _has_identity(existing or {}) or str(di).lower().startswith("userassignedidentity=") or str(di).lower() == "systemassignedidentity"):
            return _err(400, "BadRequest", "A customer-managed key requires a managed identity: assign an identity and set properties.defaultIdentity (e.g. 'SystemAssignedIdentity').")
    elif existing and ((existing.get("properties") or {}).get("keyVaultKeyUri")) and "keyVaultKeyUri" in ((payload or {}).get("properties") or {}):
        return _err(400, "BadRequest", "Customer-managed key encryption cannot be removed from an account once enabled.")
    return None


def _validate_cosmos_service(state: dict, rid: str, payload: dict):
    acct_id = rid[: rid.lower().rindex("/services/")]
    acct = state.get(acct_id.lower())
    if acct is None:
        return _err(404, "ParentResourceNotFound", "The Cosmos DB account was not found.")
    name = rid.rsplit("/", 1)[-1]
    p = (payload or {}).get("properties") or {}
    stype = p.get("serviceType") or "SqlDedicatedGateway"
    if name != "SqlDedicatedGateway" or stype != "SqlDedicatedGateway":
        return _err(400, "BadRequest", "The only supported Cosmos DB service is 'SqlDedicatedGateway'.")
    caps = [str(c.get("name", "")).lower() for c in ((acct.get("properties") or {}).get("capabilities") or [])]
    if (acct.get("kind") or "").lower() == "mongodb" or any(c.startswith("enable") and c != "enableserverless" and c != "enableservicestructure" for c in caps if c in ("enablecassandra", "enablegremlin", "enabletable", "enablemongo")):
        return _err(400, "BadRequest", "The dedicated gateway is only available for Azure Cosmos DB for NoSQL accounts.")
    if "enableserverless" in caps:
        return _err(400, "BadRequest", "The dedicated gateway is not available on serverless accounts.")
    size = p.get("instanceSize")
    if size not in DEDICATED_SIZES:
        return _err(400, "BadRequest", f"properties.instanceSize must be one of {', '.join(DEDICATED_SIZES)}.")
    count = p.get("instanceCount")
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 5:
        return _err(400, "BadRequest", "properties.instanceCount must be an integer between 1 and 5.")
    return None


def _validate_sb_ns(state: dict, payload: dict, existing, props: dict):
    sku = str(((payload or {}).get("sku") or (existing or {}).get("sku") or {}).get("name") or "Standard")
    enc = props.get("encryption")
    if enc:
        if sku.lower() != "premium":
            return _err(400, "BadRequest", "Customer-managed key encryption is only available on Premium namespaces.")
        if not _has_identity(payload) and not _has_identity(existing or {}):
            return _err(400, "BadRequest", "Customer-managed key encryption requires a managed identity assigned to the namespace.")
        kvp = enc.get("keyVaultProperties") or []
        if not kvp:
            return _err(400, "BadRequest", "encryption.keyVaultProperties must name at least one Key Vault key.")
        for k in kvp:
            vuri = str(k.get("keyVaultUri") or "")
            m = re.match(r"^https://([a-z][a-z0-9-]{1,22}[a-z0-9])\.vault\.azure\.net/?$", vuri)
            if not m or not k.get("keyName"):
                return _err(400, "BadRequest", "encryption.keyVaultProperties entries require keyVaultUri (https://<vault>.vault.azure.net) and keyName.")
            if not _vault_exists(state, m.group(1)):
                return _err(400, "KeyVaultNotFound", f"The Key Vault '{m.group(1)}' referenced by encryption.keyVaultProperties does not exist in this subscription.")
            bad = check_key_exists(m.group(1), k.get("keyName"), k.get("keyVersion"), "encryption.keyVaultProperties")
            if bad:
                return bad
        if enc.get("requireInfrastructureEncryption") and not isinstance(enc["requireInfrastructureEncryption"], bool):
            return _err(400, "BadRequest", "encryption.requireInfrastructureEncryption must be a boolean.")
    return None


def _validate_sb_rules(state: dict, rid: str, payload: dict):
    ns_id = rid[: rid.lower().rindex("/networkrulesets/")]
    ns = state.get(ns_id.lower())
    if ns is None:
        return _err(404, "ParentResourceNotFound", "The Service Bus namespace was not found.")
    if rid.rsplit("/", 1)[-1] != "default":
        return _err(400, "BadRequest", "The network rule set name must be 'default'.")
    p = (payload or {}).get("properties") or {}
    sku = str((ns.get("sku") or {}).get("name") or "Standard")
    if sku.lower() != "premium":
        return _err(400, "BadRequest", "Network rule sets are only supported on Premium namespaces.")
    if p.get("defaultAction") not in (None, "Allow", "Deny"):
        return _err(400, "BadRequest", "defaultAction must be 'Allow' or 'Deny'.")
    if p.get("publicNetworkAccess") not in (None, "Enabled", "Disabled", "SecuredByPerimeter"):
        return _err(400, "BadRequest", "publicNetworkAccess must be Enabled, Disabled or SecuredByPerimeter.")
    for r in p.get("ipRules") or []:
        mask = r.get("ipMask")
        if not mask or not _cidr_ok(str(mask)):
            return _err(400, "BadRequest", f"ipRules entry '{mask}' is not a valid IP address or CIDR range.")
        if r.get("action") not in (None, "Allow"):
            return _err(400, "BadRequest", "ipRules action must be 'Allow'.")
    for r in p.get("virtualNetworkRules") or []:
        sid = str(((r.get("subnet") or {}).get("id")) or "")
        vnet_id, _, sname = sid.lower().rpartition("/subnets/")
        vnet = state.get(vnet_id)
        if vnet is None or (vnet.get("_type") or "").lower() != VNET:
            return _err(400, "SubnetNotFound", f"The subnet '{sid}' referenced by virtualNetworkRules does not exist.")
        sub = next((s for s in (vnet.get("properties") or {}).get("subnets") or [] if str(s.get("name", "")).lower() == sname), None)
        if sub is None:
            return _err(400, "SubnetNotFound", f"The subnet '{sid}' referenced by virtualNetworkRules does not exist.")
        eps = [str(e.get("service", "")).lower() for e in ((sub.get("properties") or {}).get("serviceEndpoints") or [])]
        if "microsoft.servicebus" not in eps:
            return _err(400, "SubnetMissingServiceEndpoint", f"Subnet '{sub.get('name')}' must have the Microsoft.ServiceBus service endpoint enabled.")
    return None


def _validate_vnet(state: dict, rid: str, payload: dict, props: dict):
    for s in props.get("subnets") or []:
        sp = (s or {}).get("properties") or {}
        for ep in sp.get("serviceEndpoints") or []:
            svc = str(ep.get("service", "")).lower()
            if svc not in SERVICE_ENDPOINTS:
                return _err(400, "InvalidServiceEndpoint", f"Subnet '{s.get('name')}': service endpoint '{ep.get('service')}' is not supported.")
        dels = sp.get("delegations") or []
        names = set()
        for d in dels:
            svc = str(((d or {}).get("properties") or {}).get("serviceName") or "").lower()
            if svc not in DELEGATION_SERVICES:
                return _err(400, "InvalidSubnetDelegation", f"Subnet '{s.get('name')}': '{((d or {}).get('properties') or {}).get('serviceName')}' is not a service a subnet can be delegated to.")
            if svc in names:
                return _err(400, "InvalidSubnetDelegation", f"Subnet '{s.get('name')}' is delegated to '{svc}' more than once.")
            names.add(svc)
        if dels:
            sid = (s.get("id") or f"{rid}/subnets/{s.get('name')}").lower()
            for r in state.values():
                if isinstance(r, dict) and (r.get("_type") or "").lower() == PE and sid in repr(r.get("properties")).lower():
                    return _err(400, "SubnetIsDelegatedAndHasPrivateEndpoint", f"Subnet '{s.get('name')}' contains private endpoint '{r.get('name')}' and cannot be delegated.")
    return None


# ── derived state ───────────────────────────────────────────────────────────────────────
def after_put(state: dict, rec: dict, payload: dict, prev: dict | None = None) -> None:
    ft = (rec.get("_type") or "").lower()
    p = rec.setdefault("properties", {})
    if flux.handles(ft):
        return flux.after_put(state, rec, payload, prev)
    if ft.endswith("/providers/extensions"):
        et = str(p.get("extensionType", "")).lower()
        p.setdefault("autoUpgradeMinorVersion", not p.get("version"))
        p.setdefault("releaseTrain", "Stable")
        p.setdefault("scope", {"cluster": {"releaseNamespace": et.split(".")[-1]}})
        p["currentVersion"] = p.get("version") or "1.0.0"
        p["installedVersion"] = p["currentVersion"]
        p["provisioningState"] = "Succeeded"
        p["isSystemExtension"] = False
        p["statuses"] = [{"code": "Recorded", "displayStatus": "Extension recorded", "level": "Information", "message": "Vyomi stores the extension configuration; no workload is installed on the cluster."}]
        p.setdefault("identity", None)
        rec["type"] = "Microsoft.KubernetesConfiguration/extensions"
        rec["systemData"] = rec.get("systemData") or {"createdByType": "User"}
    elif ft == COSMOS_SVC:
        count = int(p.get("instanceCount", 1))
        size = p.get("instanceSize")
        p["serviceType"] = "SqlDedicatedGateway"
        p["creationTime"] = p.get("creationTime") or "2026-01-01T00:00:00Z"
        p["status"] = "Running"
        acct = state.get(rec["id"].lower().rsplit("/services/", 1)[0])
        host = (acct or {}).get("name", "account")
        p["sqlDedicatedGatewayEndpoint"] = f"https://{host}.sqlx.cosmos.azure.com/"
        p["locations"] = [{"name": f"{host}-{i}", "location": (acct or {}).get("location", "East US"), "status": "Running"} for i in range(count)]
        p["instanceSize"] = size
        rec["etag"] = f'"{uuid.uuid4()}"'
    elif ft == APIM and (payload or {}).get("properties", {}).get("restore"):
        key, gone = _find_deleted(state, rec["id"].split("/")[2], rec["name"])
        if gone is not None:
            for k, v in (gone.get("_children") or {}).items():
                state.setdefault(k, v)
            prev_p = (gone.get("_svc") or {}).get("properties") or {}
            for k, v in prev_p.items():
                p.setdefault(k, v)
            p.pop("restore", None)
            state.pop(key, None)
    elif ft == SQL_LABEL:
        p.setdefault("rank", "None")
        p["isDisabled"] = bool(p.get("isDisabled", False))
        p.setdefault("managedBy", "Vyomi")
        rec["type"] = "Microsoft.Sql/servers/databases/schemas/tables/columns/sensitivityLabels"
    elif ft == ASG:
        p["provisioningState"] = "Succeeded"
        p.setdefault("resourceGuid", str(uuid.uuid4()))
    elif ft == ENC_SCOPE:
        p.setdefault("source", "Microsoft.Storage")
        p.setdefault("state", "Enabled")
        p["requireInfrastructureEncryption"] = bool(p.get("requireInfrastructureEncryption", False))
        p.setdefault("creationTime", rec.get("systemData", {}).get("createdAt"))
        p["lastModifiedTime"] = rec.get("systemData", {}).get("lastModifiedAt")
        rec["type"] = "Microsoft.Storage/storageAccounts/encryptionScopes"
    elif ft == BLOB_CONTAINER:
        p.setdefault("publicAccess", "None")
        p.setdefault("denyEncryptionScopeOverride", False)
        iw = p.get("immutableStorageWithVersioning")
        if iw is not None:
            iw["enabled"] = bool(iw.get("enabled"))
            iw["state"] = "Enabled" if iw["enabled"] else "Disabled"
        p["hasImmutabilityPolicy"] = False
        p["hasLegalHold"] = False
        p["defaultEncryptionScope"] = p.get("defaultEncryptionScope") or "$account-encryption-key"
        rec["type"] = "Microsoft.Storage/storageAccounts/blobServices/containers"
    elif ft == SB_NETRULES:
        p.setdefault("defaultAction", "Allow")
        p.setdefault("publicNetworkAccess", "Enabled")
        p.setdefault("trustedServiceAccessEnabled", False)
        p.setdefault("ipRules", [])
        p.setdefault("virtualNetworkRules", [])
        rec["type"] = "Microsoft.ServiceBus/Namespaces/NetworkRuleSets"


def _asg_users(state: dict, asg_id: str):
    want = asg_id.lower()
    out = []
    for k, r in state.items():
        t = (r.get("_type") or "").lower() if isinstance(r, dict) else ""
        if t not in (NIC, NSG_RULE, "microsoft.network/networksecuritygroups"):
            continue
        p = r.get("properties") or {}
        refs = [g for c in (p.get("ipConfigurations") or []) for g in ((c.get("properties") or {}).get("applicationSecurityGroups") or [])]
        refs += (p.get("sourceApplicationSecurityGroups") or []) + (p.get("destinationApplicationSecurityGroups") or [])
        refs += [g for sr in (p.get("securityRules") or []) for g in ((sr.get("properties") or {}).get("sourceApplicationSecurityGroups") or []) + ((sr.get("properties") or {}).get("destinationApplicationSecurityGroups") or [])]
        if any(str((g or {}).get("id") or "").lower() == want for g in refs):
            out.append(r.get("name"))
    return out


def before_delete(state: dict, rec: dict):
    ft = (rec.get("_type") or "").lower()
    if flux.handles(ft):
        return flux.before_delete(state, rec)
    if ft == ASG:
        users = _asg_users(state, rec["id"])
        if users:
            return _err(400, "ApplicationSecurityGroupInUse", f"Application security group '{rec['name']}' cannot be deleted: it is used by {', '.join(sorted(set(users)))}.")
    if ft == APIM:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        rid = rec["id"]
        pre = rid.lower() + "/"
        loc = rec.get("location") or "eastus"
        snap = {k: dict(v) if isinstance(v, dict) else v for k, v in state.items() if k.startswith(pre) and "/__event__/" not in k}
        state[_deleted_key(rid, loc)] = {
            "id": f"/subscriptions/{rid.split('/')[2]}/providers/Microsoft.ApiManagement/locations/{loc.replace(' ', '').lower()}/deletedservices/{rid.rsplit('/', 1)[-1]}",
            "name": rid.rsplit("/", 1)[-1], "type": "Microsoft.ApiManagement/deletedservices", "_type": APIM_DELETED,
            "location": loc, "sku": rec.get("sku"),
            "properties": {"serviceId": rid, "scheduledPurgeDate": (now + datetime.timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "deletionDate": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
            "_svc": dict(rec), "_children": snap,
        }
    return None
