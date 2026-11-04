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
* Virtual network subnets -- ``serviceEndpoints`` names, ``delegations`` serviceName, and the rule that a delegated
  subnet cannot also carry a private endpoint.

NOT modelled (honest limits, see core/capabilities/azure/*.json): the named Key Vault KEY is not looked up (keys live in the
Key Vault data plane store, outside ARM state), KEDA / extensions install no workload, CORS rules are not applied to
a Cosmos data plane response, the dedicated gateway has no cache, Service Bus network rules are not evaluated against
connections.
"""
from __future__ import annotations

import ipaddress
import re
import uuid

AKS = "microsoft.containerservice/managedclusters"
COSMOS = "microsoft.documentdb/databaseaccounts"
COSMOS_SVC = "microsoft.documentdb/databaseaccounts/services"
SBNS = "microsoft.servicebus/namespaces"
SB_NETRULES = "microsoft.servicebus/namespaces/networkrulesets"
APPCFG = "microsoft.appconfiguration/configurationstores"
VNET = "microsoft.network/virtualnetworks"
PE = "microsoft.network/privateendpoints"

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
    return ft in (AKS, COSMOS, COSMOS_SVC, SBNS, SB_NETRULES, VNET) or ft.endswith("/providers/extensions")


def _merged(existing, payload) -> dict:
    p = dict((existing or {}).get("properties") or {})
    p.update((payload or {}).get("properties") or {})
    return p


def _vault_exists(state: dict, name: str) -> bool:
    return any(isinstance(r, dict) and (r.get("_type") or "").lower() == "microsoft.keyvault/vaults"
               and str(r.get("name", "")).lower() == name.lower() for r in state.values())


def _check_key_uri(state: dict, uri: str, what: str):
    m = KV_KEY_URI.match(str(uri or ""))
    if not m:
        return _err(400, "InvalidKeyVaultKeyUri", f"{what} must be a Key Vault key URI of the form https://<vault>.vault.azure.net/keys/<name>[/<version>]; got '{uri}'.")
    if not _vault_exists(state, m.group(1)):
        return _err(400, "KeyVaultNotFound", f"The Key Vault '{m.group(1)}' referenced by {what} does not exist in this subscription.")
    return None


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
    elif ft == SB_NETRULES:
        p.setdefault("defaultAction", "Allow")
        p.setdefault("publicNetworkAccess", "Enabled")
        p.setdefault("trustedServiceAccessEnabled", False)
        p.setdefault("ipRules", [])
        p.setdefault("virtualNetworkRules", [])
        rec["type"] = "Microsoft.ServiceBus/Namespaces/NetworkRuleSets"


def before_delete(state: dict, rec: dict):
    return None
