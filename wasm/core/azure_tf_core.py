# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure <-> Terraform (azurerm) mapping for the Export template / Import Terraform flows.

EXPORT: ``to_terraform(template, sub, rg, rg_location)`` evaluates the exported ARM template (defaults)
and emits ``azurerm_*`` resources for every ARM type in ``SPECS`` with real cross-references
(``azurerm_virtual_network.vnet1.name``, ``azurerm_subnet.app.id`` ...), secrets as ``sensitive``
variables, deterministic ordering. ARM types without a mapping fall back to the generic ``azapi_resource``
(lossless) and are listed in a trailing comment so nothing is silently dropped.

IMPORT: ``terraform_to_arm(text)`` parses HCL and builds an ARM deployment template (parameters from
``variable`` blocks, ``resourceId()``/``concat()`` expressions from references, ``dependsOn`` from
``depends_on``). Blocks it cannot model are returned in ``unsupported`` with a reason - never guessed.
"""
from __future__ import annotations

import re

try:
    from core import azure_tf_hcl as H
    from core import azure_deploy_core as D
except ImportError:      # flat import (Nano/dev)
    import azure_tf_hcl as H  # type: ignore
    import azure_deploy_core as D  # type: ignore

Raw, Blocks = H.Raw, H.Blocks


class Unsup(Exception):
    pass


def _sym(name):
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(name))
    if not s or s[0].isdigit():
        s = "r_" + s
    return s


def _loc(v):
    return str(v).lower().replace(" ", "") if v else v


def _g(d, *path, default=None):
    for p in path:
        if isinstance(d, dict):
            k = next((x for x in d if str(x).lower() == str(p).lower()), None)
            if k is None:
                return default
            d = d[k]
        else:
            return default
    return d


def _clean(d):
    return {k: v for k, v in d.items() if v is not None and v != "" and not (isinstance(v, (list, dict)) and not v and not isinstance(v, Blocks))}


_TIERS = {"F": "Free", "D": "Shared", "B": "Basic", "S": "Standard", "P": "Premium", "I": "Isolated", "Y": "Dynamic", "EP": "ElasticPremium", "WS": "WorkflowStandard"}


def _plan_tier(sku):
    s = str(sku).upper()
    if s.startswith("EP"):
        return "ElasticPremium"
    if s.startswith("WS"):
        return "WorkflowStandard"
    if re.match(r"^P\d+V3$", s):
        return "PremiumV3"
    if re.match(r"^P\d+V2$", s):
        return "PremiumV2"
    if re.match(r"^I\d+V2$", s):
        return "IsolatedV2"
    return _TIERS.get(s[:1], "Standard")


_ROLES = {"Owner": "8e3af657-a8ff-443c-a75c-2fe8c4bcb635", "Contributor": "b24988ac-6180-42a0-ab88-dd4b3b8d5b64", "Reader": "acdd72a7-3385-48ef-bd42-f606fba81ae7",
          "Storage Blob Data Contributor": "ba92f5b4-2d11-453d-a403-e96b0029c9fe", "Storage Blob Data Reader": "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1",
          "Key Vault Administrator": "00482a5a-887f-4fb3-b363-3b7fe8e74483", "Key Vault Secrets User": "4633458b-17de-408a-b874-0445c86b69e6",
          "AcrPull": "7f951dda-4ed3-4680-a7ca-43fe172d538d", "AcrPush": "8311e382-0749-4cb8-b61a-304f252e45ec",
          "Azure Service Bus Data Owner": "090c5cfd-751d-490a-894a-3ce6f1109419", "User Access Administrator": "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9"}
_ROLE_BY_GUID = {v: k for k, v in _ROLES.items()}

# ═══════════════════════════ SPEC TABLE (ARM <-> azurerm) ═══════════════════════════════════════
SPECS = []          # ordered; one per azurerm resource type


def spec(arm, tf, **kw):
    def deco(fns):
        s = {**dict(arm=arm, tf=tf, loc=True, names=1, parent=None, api="2023-01-01"), **kw}
        s["to"], s["frm"] = fns
        SPECS.append(s)
        return fns
    return deco


def common_to(res, X, extra_blocks=None):
    """name / resource_group_name / location head shared by every located resource."""
    return {"name": res["leaf"], "resource_group_name": X.rg_name, "location": X.loc(res)}


# ── resource group (the container; created by the target RG on import) ──
# ── user-assigned identity ──
def _uami_to(res, X):
    return {**common_to(res, X), "tags": res["tags"] or None}


def _uami_from(a, imp):
    return {"properties": {}}


spec("Microsoft.ManagedIdentity/userAssignedIdentities", "azurerm_user_assigned_identity", api="2023-01-31")((_uami_to, _uami_from))


# ── virtual network / subnet ──
def _vnet_to(res, X):
    p = res["props"]
    return {**common_to(res, X), "address_space": _g(p, "addressSpace", "addressPrefixes") or [],
            "dns_servers": _g(p, "dhcpOptions", "dnsServers") or None, "tags": res["tags"] or None}


def _vnet_from(a, imp):
    props = {"addressSpace": {"addressPrefixes": a.v("address_space", [])}}
    if a.v("dns_servers"):
        props["dhcpOptions"] = {"dnsServers": a.v("dns_servers")}
    return {"properties": props}


spec("Microsoft.Network/virtualNetworks", "azurerm_virtual_network", api="2023-05-01")((_vnet_to, _vnet_from))


def _subnet_to(res, X):
    p = res["props"]
    pre = p.get("addressPrefixes") or ([p["addressPrefix"]] if p.get("addressPrefix") else [])
    ep = [e.get("service") if isinstance(e, dict) else e for e in p.get("serviceEndpoints") or []]
    out = {"name": res["leaf"], "resource_group_name": X.rg_name, "virtual_network_name": X.ref_id(res["parent_ids"][0], "name"),
           "address_prefixes": pre, "service_endpoints": ep or None}
    pe = p.get("privateEndpointNetworkPolicies")
    if pe:
        out["private_endpoint_network_policies"] = pe
    pl = p.get("privateLinkServiceNetworkPolicies")
    if pl:
        out["private_link_service_network_policies_enabled"] = str(pl).lower() == "enabled"
    dl = []
    for d in p.get("delegations") or []:
        dp = d.get("properties") or {}
        dl.append({"name": d.get("name"), "service_delegation": Blocks([{"name": dp.get("serviceName")}])})
    if dl:
        out["delegation"] = Blocks(dl)
    return out


def _subnet_extras(res, X):
    p, out = res["props"], []
    nsg = _g(p, "networkSecurityGroup", "id")
    if nsg and X.known(nsg):
        out.append(("azurerm_subnet_network_security_group_association", X.label_for(res) + "_nsg",
                    {"subnet_id": Raw(f"azurerm_subnet.{X.label_for(res)}.id"), "network_security_group_id": X.ref_id(nsg, "id")}))
    rt = _g(p, "routeTable", "id")
    if rt and X.known(rt):
        out.append(("azurerm_subnet_route_table_association", X.label_for(res) + "_rt",
                    {"subnet_id": Raw(f"azurerm_subnet.{X.label_for(res)}.id"), "route_table_id": X.ref_id(rt, "id")}))
    return out


def _subnet_from(a, imp):
    props = {}
    pre = a.v("address_prefixes", [])
    if len(pre) == 1:
        props["addressPrefix"] = pre[0]
    elif pre:
        props["addressPrefixes"] = pre
    if a.v("service_endpoints"):
        props["serviceEndpoints"] = [{"service": s} for s in a.v("service_endpoints")]
    if a.has("private_endpoint_network_policies"):
        props["privateEndpointNetworkPolicies"] = a.v("private_endpoint_network_policies")
    if a.has("private_link_service_network_policies_enabled"):
        props["privateLinkServiceNetworkPolicies"] = "Enabled" if a.v("private_link_service_network_policies_enabled") in (True, "true") else "Disabled"
    dl = []
    for d in a.b("delegation"):
        sd = (d.b("service_delegation") or [None])[0]
        dl.append({"name": d.v("name"), "properties": {"serviceName": sd.v("name") if sd else None}})
    if dl:
        props["delegations"] = dl
    return {"properties": props}


spec("Microsoft.Network/virtualNetworks/subnets", "azurerm_subnet", loc=False, names=2, parent=("virtual_network_name", "name"), api="2023-05-01", extras=_subnet_extras)((_subnet_to, _subnet_from))


SPECS.append(dict(arm=None, tf="azurerm_subnet_network_security_group_association", patch=("subnet_id", "network_security_group_id", "networkSecurityGroup")))
SPECS.append(dict(arm=None, tf="azurerm_subnet_route_table_association", patch=("subnet_id", "route_table_id", "routeTable")))


# ── network security group ──
def _plural(p, single, plural):
    if p.get(single) not in (None, ""):
        return {single_tf(single): p[single]}
    if p.get(plural):
        return {single_tf(plural): p[plural]}
    return {}


def single_tf(k):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()


def _nsg_to(res, X):
    rules = []
    for r in sorted(res["props"].get("securityRules") or [], key=lambda x: (_g(x, "properties", "priority", default=0), x.get("name", ""))):
        rp = r.get("properties") or {}
        d = {"name": r.get("name"), "priority": rp.get("priority"), "direction": rp.get("direction"), "access": rp.get("access"), "protocol": rp.get("protocol")}
        for s, pl in (("sourcePortRange", "sourcePortRanges"), ("destinationPortRange", "destinationPortRanges"),
                      ("sourceAddressPrefix", "sourceAddressPrefixes"), ("destinationAddressPrefix", "destinationAddressPrefixes")):
            d.update(_plural(rp, s, pl))
        if rp.get("description"):
            d["description"] = rp["description"]
        rules.append(d)
    out = {**common_to(res, X)}
    if rules:
        out["security_rule"] = Blocks(rules)
    out["tags"] = res["tags"] or None
    return out


def _nsg_from(a, imp):
    rules = []
    for b in a.b("security_rule"):
        rp = {"priority": b.v("priority"), "direction": b.v("direction"), "access": b.v("access"), "protocol": b.v("protocol")}
        for k in ("source_port_range", "source_port_ranges", "destination_port_range", "destination_port_ranges", "source_address_prefix",
                  "source_address_prefixes", "destination_address_prefix", "destination_address_prefixes", "description"):
            if b.has(k):
                rp[re.sub(r"_(\w)", lambda m: m.group(1).upper(), k)] = b.v(k)
        rules.append({"name": b.v("name"), "properties": rp})
    return {"properties": {"securityRules": rules}}


spec("Microsoft.Network/networkSecurityGroups", "azurerm_network_security_group", api="2023-05-01")((_nsg_to, _nsg_from))


# ── public IP ──
def _pip_to(res, X):
    p, sku = res["props"], res["sku"] or {}
    return {**common_to(res, X), "allocation_method": p.get("publicIPAllocationMethod") or "Dynamic", "sku": sku.get("name") or "Basic",
            "sku_tier": sku.get("tier") if sku.get("tier") and sku.get("tier") != "Regional" else None,
            "ip_version": p.get("publicIPAddressVersion") if p.get("publicIPAddressVersion") not in (None, "IPv4") else None,
            "idle_timeout_in_minutes": p.get("idleTimeoutInMinutes") if p.get("idleTimeoutInMinutes") not in (None, 4) else None,
            "domain_name_label": _g(p, "dnsSettings", "domainNameLabel"), "zones": res["body"].get("zones") or None, "tags": res["tags"] or None}


def _pip_from(a, imp):
    props = {"publicIPAllocationMethod": a.v("allocation_method", "Dynamic")}
    if a.has("ip_version"):
        props["publicIPAddressVersion"] = a.v("ip_version")
    if a.has("idle_timeout_in_minutes"):
        props["idleTimeoutInMinutes"] = a.v("idle_timeout_in_minutes")
    if a.has("domain_name_label"):
        props["dnsSettings"] = {"domainNameLabel": a.v("domain_name_label")}
    sku = {"name": a.v("sku", "Basic")}
    if a.has("sku_tier"):
        sku["tier"] = a.v("sku_tier")
    out = {"sku": sku, "properties": props}
    if a.has("zones"):
        out["zones"] = a.v("zones")
    return out


spec("Microsoft.Network/publicIPAddresses", "azurerm_public_ip", api="2023-05-01")((_pip_to, _pip_from))


# ── storage account ──
def _st_to(res, X):
    p = res["props"]
    tier, _, repl = str((res["sku"] or {}).get("name", "Standard_LRS")).partition("_")
    out = {**common_to(res, X), "account_tier": tier, "account_replication_type": repl or "LRS",
           "account_kind": res["body"].get("kind") or "StorageV2", "access_tier": p.get("accessTier"),
           "min_tls_version": p.get("minimumTlsVersion"), "https_traffic_only_enabled": p.get("supportsHttpsTrafficOnly"),
           "allow_nested_items_to_be_public": p.get("allowBlobPublicAccess"), "shared_access_key_enabled": p.get("allowSharedKeyAccess"),
           "is_hns_enabled": p.get("isHnsEnabled") or None}
    if p.get("publicNetworkAccess") is not None:
        out["public_network_access_enabled"] = str(p["publicNetworkAccess"]).lower() != "disabled"
    out["tags"] = res["tags"] or None
    return out


def _st_from(a, imp):
    props = {}
    for tf, arm in (("access_tier", "accessTier"), ("min_tls_version", "minimumTlsVersion"), ("https_traffic_only_enabled", "supportsHttpsTrafficOnly"),
                    ("allow_nested_items_to_be_public", "allowBlobPublicAccess"), ("shared_access_key_enabled", "allowSharedKeyAccess"), ("is_hns_enabled", "isHnsEnabled")):
        if a.has(tf):
            props[arm] = a.v(tf)
    if a.has("public_network_access_enabled"):
        props["publicNetworkAccess"] = "Enabled" if a.v("public_network_access_enabled") in (True, "true") else "Disabled"
    tier, repl = a.v("account_tier", "Standard"), a.v("account_replication_type", "LRS")
    sku = f"{tier}_{repl}" if isinstance(tier, str) and isinstance(repl, str) and not tier.startswith("[") and not repl.startswith("[") else f"[concat({imp.body_of(a.raw('account_tier'))}, '_', {imp.body_of(a.raw('account_replication_type'))})]"
    return {"kind": a.v("account_kind", "StorageV2"), "sku": {"name": sku}, "properties": props}


spec("Microsoft.Storage/storageAccounts", "azurerm_storage_account", api="2023-01-01")((_st_to, _st_from))


# ── key vault ──
def _kv_to(res, X):
    p = res["props"]
    out = {**common_to(res, X), "tenant_id": p.get("tenantId"), "sku_name": _g(p, "sku", "name") or "standard",
           "soft_delete_retention_days": p.get("softDeleteRetentionInDays"), "purge_protection_enabled": p.get("enablePurgeProtection") or None,
           "rbac_authorization_enabled": p.get("enableRbacAuthorization") or None,
           "enabled_for_deployment": p.get("enabledForDeployment") or None, "enabled_for_disk_encryption": p.get("enabledForDiskEncryption") or None,
           "enabled_for_template_deployment": p.get("enabledForTemplateDeployment") or None}
    if p.get("publicNetworkAccess") is not None:
        out["public_network_access_enabled"] = str(p["publicNetworkAccess"]).lower() != "disabled"
    na = p.get("networkAcls") or {}
    if na.get("defaultAction"):
        out["network_acls"] = Blocks([{"default_action": na["defaultAction"], "bypass": na.get("bypass") or "AzureServices",
                                       "ip_rules": [r.get("value") for r in na.get("ipRules") or []] or None}])
    aps = []
    for ap in p.get("accessPolicies") or []:
        perm = ap.get("permissions") or {}
        aps.append({"tenant_id": ap.get("tenantId"), "object_id": ap.get("objectId"), "key_permissions": perm.get("keys") or None,
                    "secret_permissions": perm.get("secrets") or None, "certificate_permissions": perm.get("certificates") or None,
                    "storage_permissions": perm.get("storage") or None})
    if aps:
        out["access_policy"] = Blocks([_clean(x) for x in aps])
    out["tags"] = res["tags"] or None
    return out


def _kv_from(a, imp):
    props = {"tenantId": a.v("tenant_id", "[subscription().tenantId]"), "sku": {"family": "A", "name": a.v("sku_name", "standard")}}
    for tf, arm in (("soft_delete_retention_days", "softDeleteRetentionInDays"), ("purge_protection_enabled", "enablePurgeProtection"),
                    ("rbac_authorization_enabled", "enableRbacAuthorization"), ("enabled_for_deployment", "enabledForDeployment"),
                    ("enabled_for_disk_encryption", "enabledForDiskEncryption"), ("enabled_for_template_deployment", "enabledForTemplateDeployment")):
        if a.has(tf):
            props[arm] = a.v(tf)
    if a.has("public_network_access_enabled"):
        props["publicNetworkAccess"] = "Enabled" if a.v("public_network_access_enabled") in (True, "true") else "Disabled"
    props["enableSoftDelete"] = True
    nb = a.b("network_acls")
    if nb:
        n = nb[0]
        props["networkAcls"] = {"defaultAction": n.v("default_action", "Allow"), "bypass": n.v("bypass", "AzureServices"),
                                "ipRules": [{"value": x} for x in n.v("ip_rules", [])]}
    aps = []
    for ap in a.b("access_policy"):
        aps.append({"tenantId": ap.v("tenant_id"), "objectId": ap.v("object_id"),
                    "permissions": {"keys": ap.v("key_permissions", []), "secrets": ap.v("secret_permissions", []),
                                    "certificates": ap.v("certificate_permissions", []), "storage": ap.v("storage_permissions", [])}})
    props["accessPolicies"] = aps
    return {"properties": props}


spec("Microsoft.KeyVault/vaults", "azurerm_key_vault", api="2023-02-01")((_kv_to, _kv_from))


# ── Azure SQL ──
def _sql_to(res, X):
    p = res["props"]
    out = {**common_to(res, X), "version": p.get("version") or "12.0", "administrator_login": p.get("administratorLogin"),
           "administrator_login_password": Raw(f"var.{X.label_for(res)}_administrator_login_password"),
           "minimum_tls_version": p.get("minimalTlsVersion")}
    if p.get("publicNetworkAccess") is not None:
        out["public_network_access_enabled"] = str(p["publicNetworkAccess"]).lower() != "disabled"
    out["tags"] = res["tags"] or None
    X.secret_vars.append((f"{X.label_for(res)}_administrator_login_password", "SQL server administrator password"))
    return out


def _sql_from(a, imp):
    props = {"version": a.v("version", "12.0"), "administratorLogin": a.v("administrator_login")}
    if a.has("administrator_login_password"):
        props["administratorLoginPassword"] = a.v("administrator_login_password")
    if a.has("minimum_tls_version"):
        props["minimalTlsVersion"] = a.v("minimum_tls_version")
    if a.has("public_network_access_enabled"):
        props["publicNetworkAccess"] = "Enabled" if a.v("public_network_access_enabled") in (True, "true") else "Disabled"
    return {"properties": props}


spec("Microsoft.Sql/servers", "azurerm_mssql_server", api="2022-05-01-preview")((_sql_to, _sql_from))


def _sqldb_to(res, X):
    p = res["props"]
    out = {"name": res["leaf"], "server_id": X.ref_id(res["parent_ids"][0], "id"), "collation": p.get("collation"),
           "max_size_gb": (int(p["maxSizeBytes"]) // 1073741824 if p.get("maxSizeBytes") else None), "sku_name": (res["sku"] or {}).get("name"),
           "zone_redundant": p.get("zoneRedundant") or None, "license_type": p.get("licenseType"), "tags": res["tags"] or None}
    return out


def _sqldb_from(a, imp):
    props = {}
    if a.has("collation"):
        props["collation"] = a.v("collation")
    if a.has("max_size_gb"):
        gb = a.v("max_size_gb")
        props["maxSizeBytes"] = int(gb) * 1073741824 if isinstance(gb, (int, float)) else f"[mul({imp.body_of(a.raw('max_size_gb'))}, 1073741824)]"
    if a.has("zone_redundant"):
        props["zoneRedundant"] = a.v("zone_redundant")
    if a.has("license_type"):
        props["licenseType"] = a.v("license_type")
    out = {"properties": props}
    if a.has("sku_name"):
        out["sku"] = {"name": a.v("sku_name")}
    return out


spec("Microsoft.Sql/servers/databases", "azurerm_mssql_database", loc=True, names=2, parent=("server_id", "id"), api="2022-05-01-preview")((_sqldb_to, _sqldb_from))


# ── Cosmos DB ──
def _cosmos_to(res, X):
    p = res["props"]
    cp = p.get("consistencyPolicy") or {}
    cons = {"consistency_level": cp.get("defaultConsistencyLevel") or "Session"}
    if cons["consistency_level"] == "BoundedStaleness":
        cons.update({"max_interval_in_seconds": cp.get("maxIntervalInSeconds"), "max_staleness_prefix": cp.get("maxStalenessPrefix")})
    geo = [{"location": _loc(x.get("locationName")), "failover_priority": x.get("failoverPriority", 0), "zone_redundant": x.get("isZoneRedundant") or None}
           for x in sorted(p.get("locations") or [], key=lambda z: z.get("failoverPriority", 0))]
    out = {**common_to(res, X), "offer_type": p.get("databaseAccountOfferType") or "Standard", "kind": res["body"].get("kind") or "GlobalDocumentDB",
           "automatic_failover_enabled": p.get("enableAutomaticFailover") or None, "free_tier_enabled": p.get("enableFreeTier") or None,
           "multiple_write_locations_enabled": p.get("enableMultipleWriteLocations") or None,
           "consistency_policy": Blocks([_clean(cons)]), "geo_location": Blocks([_clean(g) if "zone_redundant" in g else g for g in geo])}
    if p.get("publicNetworkAccess") is not None:
        out["public_network_access_enabled"] = str(p["publicNetworkAccess"]).lower() != "disabled"
    caps = [{"name": c.get("name")} for c in p.get("capabilities") or []]
    if caps:
        out["capabilities"] = Blocks(caps)
    out["tags"] = res["tags"] or None
    return out


def _cosmos_from(a, imp):
    props = {"databaseAccountOfferType": a.v("offer_type", "Standard")}
    cp = (a.b("consistency_policy") or [None])[0]
    if cp:
        c = {"defaultConsistencyLevel": cp.v("consistency_level", "Session")}
        if cp.has("max_interval_in_seconds"):
            c["maxIntervalInSeconds"] = cp.v("max_interval_in_seconds")
        if cp.has("max_staleness_prefix"):
            c["maxStalenessPrefix"] = cp.v("max_staleness_prefix")
        props["consistencyPolicy"] = c
    props["locations"] = [{"locationName": g.v("location"), "failoverPriority": g.v("failover_priority", 0), "isZoneRedundant": bool(g.v("zone_redundant", False))}
                          for g in a.b("geo_location")]
    for tf, arm in (("automatic_failover_enabled", "enableAutomaticFailover"), ("free_tier_enabled", "enableFreeTier"),
                    ("multiple_write_locations_enabled", "enableMultipleWriteLocations")):
        if a.has(tf):
            props[arm] = a.v(tf)
    if a.has("public_network_access_enabled"):
        props["publicNetworkAccess"] = "Enabled" if a.v("public_network_access_enabled") in (True, "true") else "Disabled"
    caps = [{"name": c.v("name")} for c in a.b("capabilities")]
    if caps:
        props["capabilities"] = caps
    return {"kind": a.v("kind", "GlobalDocumentDB"), "properties": props}


spec("Microsoft.DocumentDB/databaseAccounts", "azurerm_cosmosdb_account", api="2023-04-15")((_cosmos_to, _cosmos_from))


# ── Service Bus ──
def _sbns_to(res, X):
    p, sku = res["props"], res["sku"] or {}
    out = {**common_to(res, X), "sku": sku.get("name") or "Standard", "capacity": sku.get("capacity") if sku.get("name") == "Premium" else None,
           "minimum_tls_version": p.get("minimumTlsVersion"), "premium_messaging_partitions": None}
    if p.get("disableLocalAuth") is not None:
        out["local_auth_enabled"] = not p["disableLocalAuth"]
    if p.get("publicNetworkAccess") is not None:
        out["public_network_access_enabled"] = str(p["publicNetworkAccess"]).lower() != "disabled"
    out["tags"] = res["tags"] or None
    return out


def _sbns_from(a, imp):
    props = {}
    if a.has("minimum_tls_version"):
        props["minimumTlsVersion"] = a.v("minimum_tls_version")
    if a.has("local_auth_enabled"):
        props["disableLocalAuth"] = a.v("local_auth_enabled") not in (True, "true")
    if a.has("public_network_access_enabled"):
        props["publicNetworkAccess"] = "Enabled" if a.v("public_network_access_enabled") in (True, "true") else "Disabled"
    sku = {"name": a.v("sku", "Standard"), "tier": a.v("sku", "Standard")}
    if a.has("capacity"):
        sku["capacity"] = a.v("capacity")
    return {"sku": sku, "properties": props}


spec("Microsoft.ServiceBus/namespaces", "azurerm_servicebus_namespace", api="2022-10-01-preview")((_sbns_to, _sbns_from))

_SB_Q = (("max_delivery_count", "maxDeliveryCount"), ("lock_duration", "lockDuration"), ("default_message_ttl", "defaultMessageTimeToLive"),
         ("requires_session", "requiresSession"), ("requires_duplicate_detection", "requiresDuplicateDetection"),
         ("dead_lettering_on_message_expiration", "deadLetteringOnMessageExpiration"), ("partitioning_enabled", "enablePartitioning"),
         ("max_size_in_megabytes", "maxSizeInMegabytes"), ("batched_operations_enabled", "enableBatchedOperations"),
         ("duplicate_detection_history_time_window", "duplicateDetectionHistoryTimeWindow"), ("auto_delete_on_idle", "autoDeleteOnIdle"))
_SB_T = (("default_message_ttl", "defaultMessageTimeToLive"), ("max_size_in_megabytes", "maxSizeInMegabytes"), ("partitioning_enabled", "enablePartitioning"),
         ("requires_duplicate_detection", "requiresDuplicateDetection"), ("support_ordering", "supportOrdering"), ("batched_operations_enabled", "enableBatchedOperations"),
         ("duplicate_detection_history_time_window", "duplicateDetectionHistoryTimeWindow"), ("auto_delete_on_idle", "autoDeleteOnIdle"))
_SB_S = (("max_delivery_count", "maxDeliveryCount"), ("lock_duration", "lockDuration"), ("default_message_ttl", "defaultMessageTimeToLive"),
         ("requires_session", "requiresSession"), ("dead_lettering_on_message_expiration", "deadLetteringOnMessageExpiration"),
         ("batched_operations_enabled", "enableBatchedOperations"), ("auto_delete_on_idle", "autoDeleteOnIdle"))


def _sb_child(tbl, parent_attr, parent_id_idx=0, defaults=None):
    def to(res, X):
        p = res["props"]
        out = {"name": res["leaf"], parent_attr: X.ref_id(res["parent_ids"][parent_id_idx], "id")}
        for tf, arm in tbl:
            if p.get(arm) is not None:
                out[tf] = p[arm]
        for k, v in (defaults or {}).items():
            out.setdefault(k, v)
        return out

    def frm(a, imp):
        props = {arm: a.v(tf) for tf, arm in tbl if a.has(tf)}
        return {"properties": props}
    return to, frm


spec("Microsoft.ServiceBus/namespaces/queues", "azurerm_servicebus_queue", loc=False, names=2, parent=("namespace_id", "id"), api="2022-10-01-preview")(_sb_child(_SB_Q, "namespace_id"))
spec("Microsoft.ServiceBus/namespaces/topics", "azurerm_servicebus_topic", loc=False, names=2, parent=("namespace_id", "id"), api="2022-10-01-preview")(_sb_child(_SB_T, "namespace_id"))
spec("Microsoft.ServiceBus/namespaces/topics/subscriptions", "azurerm_servicebus_subscription", loc=False, names=3, parent=("topic_id", "id"), api="2022-10-01-preview")(
    _sb_child(_SB_S, "topic_id", parent_id_idx=1, defaults={"max_delivery_count": 10}))


# ── App Service plan / web / function apps ──
def _plan_to(res, X):
    sku = res["sku"] or {}
    reserved = bool(res["props"].get("reserved")) or "linux" in str(res["body"].get("kind") or "").lower()
    return {**common_to(res, X), "os_type": "Linux" if reserved else "Windows", "sku_name": sku.get("name") or "B1",
            "worker_count": sku.get("capacity") if sku.get("capacity") not in (None, 1) else None, "tags": res["tags"] or None}


def _plan_from(a, imp):
    os_ = a.v("os_type", "Windows")
    sku = a.v("sku_name", "B1")
    out = {"sku": {"name": sku, "tier": _plan_tier(sku) if isinstance(sku, str) and not sku.startswith("[") else "Standard"},
           "properties": {"reserved": str(os_).lower() == "linux"}}
    if str(os_).lower() == "linux":
        out["kind"] = "linux"
    if a.has("worker_count"):
        out["sku"]["capacity"] = a.v("worker_count")
    return out


spec("Microsoft.Web/serverfarms", "azurerm_service_plan", api="2022-09-01")((_plan_to, _plan_from))

_STACKS = {"NODE": "node_version", "PYTHON": "python_version", "DOTNETCORE": "dotnet_version", "PHP": "php_version", "RUBY": "ruby_version", "GO": "go_version"}
_STACK_BY_TF = {v: k for k, v in _STACKS.items()}


def _site_to(linux, func):
    def to(res, X):
        p = res["props"]
        sc = p.get("siteConfig") or {}
        out = {**common_to(res, X), "service_plan_id": X.ref_id(p.get("serverFarmId"), "id"), "https_only": p.get("httpsOnly")}
        if func:
            st = X.first_storage()
            if st:
                out["storage_account_name"] = Raw(f"azurerm_storage_account.{st}.name")
                out["storage_account_access_key"] = Raw(f"azurerm_storage_account.{st}.primary_access_key")
            else:
                out["storage_account_name"] = Raw(f"var.{X.label_for(res)}_storage_account_name")
                out["storage_account_access_key"] = Raw(f"var.{X.label_for(res)}_storage_account_access_key")
                X.secret_vars.append((f"{X.label_for(res)}_storage_account_name", "Storage account backing the function app", False))
                X.secret_vars.append((f"{X.label_for(res)}_storage_account_access_key", "Storage account access key for the function app"))
        if p.get("clientAffinityEnabled") is not None and not func:
            out["client_affinity_enabled"] = p["clientAffinityEnabled"]
        cfg = {}
        if sc.get("alwaysOn") is not None:
            cfg["always_on"] = sc["alwaysOn"]
        if sc.get("ftpsState"):
            cfg["ftps_state"] = sc["ftpsState"]
        if sc.get("minTlsVersion"):
            cfg["minimum_tls_version"] = sc["minTlsVersion"]
        fx = sc.get("linuxFxVersion") or ""
        stack = {}
        if linux and "|" in fx:
            lang, _, ver = fx.partition("|")
            if lang.upper() in _STACKS:
                stack[_STACKS[lang.upper()]] = ver
            elif lang.upper() == "DOCKER":
                reg, _, rest = ver.partition("/")
                stack["docker_image_name"] = rest or ver
                stack["docker_registry_url"] = f"https://{reg}" if rest else "https://index.docker.io"
        elif not linux and sc.get("netFrameworkVersion") and not func:
            stack["current_stack"] = "dotnet"
            stack["dotnet_version"] = sc["netFrameworkVersion"]
        if stack:
            cfg["application_stack"] = Blocks([stack])
        out["site_config"] = Blocks([cfg])
        if res["body"].get("identity", {}).get("type") not in (None, "None"):
            ident = res["body"]["identity"]
            ib = {"type": ident["type"]}
            if ident.get("userAssignedIdentities"):
                ib["identity_ids"] = [X.ref_id(k, "id") for k in sorted(ident["userAssignedIdentities"])]
            out["identity"] = Blocks([ib])
        out["tags"] = res["tags"] or None
        return out
    return to


def _site_from(linux, func):
    def frm(a, imp):
        props = {"serverFarmId": a.v("service_plan_id"), "httpsOnly": a.v("https_only", False)}
        if a.has("client_affinity_enabled"):
            props["clientAffinityEnabled"] = a.v("client_affinity_enabled")
        sc = {}
        scb = (a.b("site_config") or [None])[0]
        if scb:
            if scb.has("always_on"):
                sc["alwaysOn"] = scb.v("always_on")
            if scb.has("ftps_state"):
                sc["ftpsState"] = scb.v("ftps_state")
            if scb.has("minimum_tls_version"):
                sc["minTlsVersion"] = scb.v("minimum_tls_version")
            st = (scb.b("application_stack") or [None])[0]
            if st:
                if linux:
                    for tf, lang in _STACK_BY_TF.items():
                        if st.has(tf):
                            sc["linuxFxVersion"] = f"{lang}|{st.v(tf)}"
                    if st.has("docker_image_name"):
                        reg = str(st.v("docker_registry_url", "")).replace("https://", "")
                        sc["linuxFxVersion"] = f"DOCKER|{reg + '/' if reg else ''}{st.v('docker_image_name')}"
                elif st.has("dotnet_version"):
                    sc["netFrameworkVersion"] = st.v("dotnet_version")
        if sc:
            props["siteConfig"] = sc
        for k in ("storage_account_name", "storage_account_access_key"):
            if a.has(k):
                imp.warn(f"{a.addr}: '{k}' is accepted but the function app's storage binding is not modelled by the simulator")
        kind = ("functionapp" if func else "app") + (",linux" if linux else "")
        out = {"kind": kind, "properties": props}
        ib = (a.b("identity") or [None])[0]
        if ib:
            ident = {"type": ib.v("type", "SystemAssigned")}
            ids = ib.v("identity_ids", [])
            if ids:
                ident["userAssignedIdentities"] = {i: {} for i in ids}
            out["identity"] = ident
        return out
    return frm


spec("Microsoft.Web/sites", "azurerm_linux_web_app", api="2022-09-01", match=lambda r: "functionapp" not in str(r["body"].get("kind") or "").lower() and "linux" in str(r["body"].get("kind") or "").lower())(
    (_site_to(True, False), _site_from(True, False)))
spec("Microsoft.Web/sites", "azurerm_windows_web_app", api="2022-09-01", match=lambda r: "functionapp" not in str(r["body"].get("kind") or "").lower() and "linux" not in str(r["body"].get("kind") or "").lower())(
    (_site_to(False, False), _site_from(False, False)))
spec("Microsoft.Web/sites", "azurerm_linux_function_app", api="2022-09-01", match=lambda r: "functionapp" in str(r["body"].get("kind") or "").lower() and "linux" in str(r["body"].get("kind") or "").lower())(
    (_site_to(True, True), _site_from(True, True)))
spec("Microsoft.Web/sites", "azurerm_windows_function_app", api="2022-09-01", match=lambda r: "functionapp" in str(r["body"].get("kind") or "").lower() and "linux" not in str(r["body"].get("kind") or "").lower())(
    (_site_to(False, True), _site_from(False, True)))


# ── container registry ──
def _acr_to(res, X):
    p = res["props"]
    out = {**common_to(res, X), "sku": (res["sku"] or {}).get("name") or "Basic", "admin_enabled": p.get("adminUserEnabled") or False}
    if p.get("publicNetworkAccess") is not None:
        out["public_network_access_enabled"] = str(p["publicNetworkAccess"]).lower() != "disabled"
    if p.get("zoneRedundancy") == "Enabled":
        out["zone_redundancy_enabled"] = True
    out["tags"] = res["tags"] or None
    return out


def _acr_from(a, imp):
    props = {"adminUserEnabled": a.v("admin_enabled", False)}
    if a.has("public_network_access_enabled"):
        props["publicNetworkAccess"] = "Enabled" if a.v("public_network_access_enabled") in (True, "true") else "Disabled"
    if a.has("zone_redundancy_enabled"):
        props["zoneRedundancy"] = "Enabled" if a.v("zone_redundancy_enabled") in (True, "true") else "Disabled"
    return {"sku": {"name": a.v("sku", "Basic")}, "properties": props}


spec("Microsoft.ContainerRegistry/registries", "azurerm_container_registry", api="2023-07-01")((_acr_to, _acr_from))


# ── AKS ──
def _pool_attrs(pl):
    return {"vm_size": pl.get("vmSize"), "node_count": pl.get("count"), "os_disk_size_gb": pl.get("osDiskSizeGB"),
            "max_pods": pl.get("maxPods"), "auto_scaling_enabled": pl.get("enableAutoScaling") or None,
            "min_count": pl.get("minCount") if pl.get("enableAutoScaling") else None, "max_count": pl.get("maxCount") if pl.get("enableAutoScaling") else None}


def _aks_pools(res):
    pools = list(res["props"].get("agentPoolProfiles") or [])
    sysi = next((i for i, p in enumerate(pools) if str(p.get("mode", "System")).lower() == "system"), 0)
    return pools, sysi


def _aks_to(res, X):
    p = res["props"]
    pools, sysi = _aks_pools(res)
    out = {**common_to(res, X), "dns_prefix": p.get("dnsPrefix"), "kubernetes_version": p.get("kubernetesVersion"),
           "sku_tier": (res["sku"] or {}).get("tier") if (res["sku"] or {}).get("tier") in ("Free", "Standard", "Premium") else None,
           "role_based_access_control_enabled": p.get("enableRBAC"), "oidc_issuer_enabled": _g(p, "oidcIssuerProfile", "enabled") or None}
    if pools:
        d = pools[sysi]
        out["default_node_pool"] = Blocks([_clean({"name": d.get("name"), **_pool_attrs(d)})])
    ident = res["body"].get("identity") or {}
    ib = {"type": ident.get("type") or "SystemAssigned"}
    if ident.get("userAssignedIdentities"):
        ib["identity_ids"] = [X.ref_id(k, "id") for k in sorted(ident["userAssignedIdentities"])]
    out["identity"] = Blocks([ib])
    npf = p.get("networkProfile") or {}
    if npf.get("networkPlugin"):
        out["network_profile"] = Blocks([_clean({"network_plugin": npf.get("networkPlugin"), "network_plugin_mode": npf.get("networkPluginMode"),
                                                  "network_policy": npf.get("networkPolicy"), "load_balancer_sku": npf.get("loadBalancerSku"),
                                                  "service_cidr": npf.get("serviceCidr"), "dns_service_ip": npf.get("dnsServiceIP"), "outbound_type": npf.get("outboundType")})])
    out["tags"] = res["tags"] or None
    return out


def _aks_extras(res, X):
    pools, sysi = _aks_pools(res)
    out = []
    for i, pl in enumerate(pools):
        if i == sysi:
            continue
        at = {"name": pl.get("name"), "kubernetes_cluster_id": Raw(f"azurerm_kubernetes_cluster.{X.label_for(res)}.id"), **_pool_attrs(pl),
              "mode": pl.get("mode") or "User", "os_type": pl.get("osType")}
        out.append(("azurerm_kubernetes_cluster_node_pool", f"{X.label_for(res)}_{_sym(pl.get('name'))}", _clean(at)))
    return out


def _pool_arm(b):
    pl = {"name": b.v("name"), "count": b.v("node_count", 1), "vmSize": b.v("vm_size"), "mode": b.v("mode", "System"), "osType": b.v("os_type", "Linux")}
    for tf, arm in (("os_disk_size_gb", "osDiskSizeGB"), ("max_pods", "maxPods"), ("auto_scaling_enabled", "enableAutoScaling"), ("min_count", "minCount"), ("max_count", "maxCount")):
        if b.has(tf):
            pl[arm] = b.v(tf)
    return pl


def _aks_from(a, imp):
    props = {"dnsPrefix": a.v("dns_prefix")}
    if a.has("kubernetes_version"):
        props["kubernetesVersion"] = a.v("kubernetes_version")
    if a.has("role_based_access_control_enabled"):
        props["enableRBAC"] = a.v("role_based_access_control_enabled")
    if a.v("oidc_issuer_enabled") in (True, "true"):
        props["oidcIssuerProfile"] = {"enabled": True}
    d = (a.b("default_node_pool") or [None])[0]
    if d is None:
        raise Unsup("default_node_pool block is required")
    pool = _pool_arm(d)
    pool["mode"] = "System"
    props["agentPoolProfiles"] = [pool]
    nb = (a.b("network_profile") or [None])[0]
    if nb:
        props["networkProfile"] = _clean({"networkPlugin": nb.v("network_plugin"), "networkPluginMode": nb.v("network_plugin_mode"), "networkPolicy": nb.v("network_policy"),
                                          "loadBalancerSku": nb.v("load_balancer_sku"), "serviceCidr": nb.v("service_cidr"), "dnsServiceIP": nb.v("dns_service_ip"),
                                          "outboundType": nb.v("outbound_type")})
    out = {"properties": props}
    ib = (a.b("identity") or [None])[0]
    ident = {"type": ib.v("type", "SystemAssigned") if ib else "SystemAssigned"}
    if ib and ib.v("identity_ids"):
        ident["userAssignedIdentities"] = {i: {} for i in ib.v("identity_ids")}
    out["identity"] = ident
    if a.has("sku_tier"):
        out["sku"] = {"name": "Base", "tier": a.v("sku_tier")}
    return out


spec("Microsoft.ContainerService/managedClusters", "azurerm_kubernetes_cluster", api="2023-08-01", extras=_aks_extras)((_aks_to, _aks_from))


SPECS.append(dict(arm=None, tf="azurerm_kubernetes_cluster_node_pool", append=("kubernetes_cluster_id", "agentPoolProfiles", _pool_arm)))


# ── DNS ──
def _dnsz_to(res, X):
    return {"name": res["leaf"], "resource_group_name": X.rg_name, "tags": res["tags"] or None}


def _dnsz_from(a, imp):
    return {"location": "global", "properties": {"zoneType": "Public"}}


spec("Microsoft.Network/dnsZones", "azurerm_dns_zone", loc=False, api="2018-05-01", global_loc=True)((_dnsz_to, _dnsz_from))


def _rec_to(rtype, tf_attr, fld, conv):
    def to(res, X):
        p = res["props"]
        out = {"name": res["leaf"], "resource_group_name": X.rg_name, "zone_name": X.ref_id(res["parent_ids"][0], "name"), "ttl": p.get("TTL", 3600)}
        out.update(conv(p.get(fld)))
        return out
    return to


def _rec_from(fld, tf_attr, conv):
    def frm(a, imp):
        props = {"TTL": a.v("ttl", 3600)}
        props.update(conv(a))
        return {"properties": props}
    return frm


def _mk_rec(rtype, tf_type, to_conv, from_conv, fld):
    spec(f"Microsoft.Network/dnsZones/{rtype}", tf_type, loc=False, names=2, parent=("zone_name", "name"), api="2018-05-01", dnsrt=rtype)(
        (_rec_to(rtype, None, fld, to_conv), _rec_from(fld, None, from_conv)))


_mk_rec("A", "azurerm_dns_a_record", lambda v: {"records": [x.get("ipv4Address") for x in v or []]}, lambda a: {"ARecords": [{"ipv4Address": x} for x in a.v("records", [])]}, "ARecords")
_mk_rec("AAAA", "azurerm_dns_aaaa_record", lambda v: {"records": [x.get("ipv6Address") for x in v or []]}, lambda a: {"AAAARecords": [{"ipv6Address": x} for x in a.v("records", [])]}, "AAAARecords")
_mk_rec("CNAME", "azurerm_dns_cname_record", lambda v: {"record": (v or {}).get("cname")}, lambda a: {"CNAMERecord": {"cname": a.v("record")}}, "CNAMERecord")
_mk_rec("TXT", "azurerm_dns_txt_record", lambda v: {"record": Blocks([{"value": "".join(x.get("value") or [])} for x in v or []])},
        lambda a: {"TXTRecords": [{"value": [b.v("value")]} for b in a.b("record")]}, "TXTRecords")
_mk_rec("MX", "azurerm_dns_mx_record", lambda v: {"record": Blocks([{"preference": x.get("preference"), "exchange": x.get("exchange")} for x in v or []])},
        lambda a: {"MXRecords": [{"preference": b.v("preference"), "exchange": b.v("exchange")} for b in a.b("record")]}, "MXRecords")


# ── Log Analytics / Application Insights ──
def _law_to(res, X):
    p = res["props"]
    out = {**common_to(res, X), "sku": _g(p, "sku", "name") or "PerGB2018", "retention_in_days": p.get("retentionInDays")}
    dq = _g(p, "workspaceCapping", "dailyQuotaGb")
    if dq not in (None, -1, -1.0):
        out["daily_quota_gb"] = dq
    if p.get("publicNetworkAccessForIngestion"):
        out["internet_ingestion_enabled"] = str(p["publicNetworkAccessForIngestion"]).lower() == "enabled"
    if p.get("publicNetworkAccessForQuery"):
        out["internet_query_enabled"] = str(p["publicNetworkAccessForQuery"]).lower() == "enabled"
    out["tags"] = res["tags"] or None
    return out


def _law_from(a, imp):
    props = {"sku": {"name": a.v("sku", "PerGB2018")}}
    if a.has("retention_in_days"):
        props["retentionInDays"] = a.v("retention_in_days")
    if a.has("daily_quota_gb"):
        props["workspaceCapping"] = {"dailyQuotaGb": a.v("daily_quota_gb")}
    if a.has("internet_ingestion_enabled"):
        props["publicNetworkAccessForIngestion"] = "Enabled" if a.v("internet_ingestion_enabled") in (True, "true") else "Disabled"
    if a.has("internet_query_enabled"):
        props["publicNetworkAccessForQuery"] = "Enabled" if a.v("internet_query_enabled") in (True, "true") else "Disabled"
    return {"properties": props}


spec("Microsoft.OperationalInsights/workspaces", "azurerm_log_analytics_workspace", api="2022-10-01")((_law_to, _law_from))


def _appi_to(res, X):
    p = res["props"]
    out = {**common_to(res, X), "application_type": p.get("Application_Type") or res["body"].get("kind") or "web",
           "workspace_id": X.ref_id(p.get("WorkspaceResourceId"), "id") if p.get("WorkspaceResourceId") else None,
           "retention_in_days": p.get("RetentionInDays"), "sampling_percentage": p.get("SamplingPercentage"),
           "disable_ip_masking": (not p["DisableIpMasking"]) if False else None, "tags": res["tags"] or None}
    return out


def _appi_from(a, imp):
    props = {"Application_Type": a.v("application_type", "web"), "Flow_Type": "Bluefield", "Request_Source": "rest"}
    if a.has("workspace_id"):
        props["WorkspaceResourceId"] = a.v("workspace_id")
    if a.has("retention_in_days"):
        props["RetentionInDays"] = a.v("retention_in_days")
    if a.has("sampling_percentage"):
        props["SamplingPercentage"] = a.v("sampling_percentage")
    return {"kind": a.v("application_type", "web"), "properties": props}


spec("Microsoft.Insights/components", "azurerm_application_insights", api="2020-02-02")((_appi_to, _appi_from))


# ── role assignment ──
def _ra_to(res, X):
    p = res["props"]
    rid = str(p.get("roleDefinitionId") or "")
    guid = rid.rsplit("/", 1)[-1].lower()
    out = {"name": res["leaf"], "scope": X.ref_id(p.get("scope") or X.rg_id, "id")}
    if guid in _ROLE_BY_GUID:
        out["role_definition_name"] = _ROLE_BY_GUID[guid]
    else:
        out["role_definition_id"] = rid
    out["principal_id"] = p.get("principalId")
    out["principal_type"] = p.get("principalType")
    return out


def _ra_from(a, imp):
    props = {"principalId": a.v("principal_id")}
    if a.has("role_definition_id"):
        props["roleDefinitionId"] = a.v("role_definition_id")
    elif a.has("role_definition_name"):
        nm = a.v("role_definition_name")
        if nm not in _ROLES:
            raise Unsup(f"role_definition_name '{nm}' is not a built-in role known to the importer; use role_definition_id")
        props["roleDefinitionId"] = f"[subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '{_ROLES[nm]}')]"
    else:
        raise Unsup("role_definition_id or role_definition_name is required")
    if a.has("principal_type"):
        props["principalType"] = a.v("principal_type")
    out = {"properties": props}
    if a.has("scope"):
        out["_scope"] = a.v("scope")
    return out


spec("Microsoft.Authorization/roleAssignments", "azurerm_role_assignment", loc=False, api="2022-04-01", literal_name=True)((_ra_to, _ra_from))

BY_TF = {s["tf"]: s for s in SPECS}
_ARM_SPECS = {}
for _s in SPECS:
    if _s.get("arm") and _s.get("to"):
        _ARM_SPECS.setdefault(_s["arm"].lower(), []).append(_s)
CANON = {s["arm"].lower(): s["arm"] for s in SPECS if s.get("arm")}


def mapped_types():
    return sorted({s["arm"] for s in SPECS if s.get("arm")})


def canon_type(t):
    return CANON.get(str(t).lower(), t)


# ═══════════════════════════ EXPORT ═════════════════════════════════════════════════════════════
_IGNORED_CHILD = {"microsoft.sql/servers/auditingsettings", "microsoft.sql/servers/securityalertpolicies", "microsoft.sql/servers/encryptionprotector",
                  "microsoft.sql/servers/databases/transparentdataencryption", "microsoft.sql/servers/databases/backuplongtermretentionpolicies",
                  "microsoft.sql/servers/databases/backupshorttermretentionpolicies", "microsoft.servicebus/namespaces/authorizationrules",
                  "microsoft.sql/servers/connectionpolicies", "microsoft.sql/servers/devopsauditingsettings", "microsoft.sql/servers/databases/auditingsettings"}


class _Exp:
    def __init__(self, resolved, sub, rg, rg_location):
        self.sub, self.rg, self.rg_location = sub, rg, _loc(rg_location)
        self.rg_id = f"/subscriptions/{sub}/resourceGroups/{rg}"
        self.rg_name = Raw("azurerm_resource_group.rg.name")
        self.labels = {}       # id.lower() -> (tf_type, label)
        self.secret_vars = []
        self.by_id = {r["id"].lower(): r for r in resolved}

    def known(self, rid):
        return rid and str(rid).lower() in self.labels

    def label_for(self, res):
        return self.labels[res["id"].lower()][1]

    def ref_id(self, rid, attr):
        if rid is None:
            return None
        k = str(rid).lower()
        if k == self.rg_id.lower():
            return Raw(f"azurerm_resource_group.rg.{attr if attr in ('name', 'id', 'location') else 'id'}")
        if k in self.labels:
            t, l = self.labels[k]
            return Raw(f"{t}.{l}.{attr}")
        return str(rid) if attr == "id" else str(rid).rstrip("/").rsplit("/", 1)[-1]

    def loc(self, res):
        v = _loc(res["body"].get("location"))
        if v and self.rg_location and v == self.rg_location:
            return Raw("azurerm_resource_group.rg.location")
        return v

    def first_storage(self):
        for k in sorted(self.labels):
            if self.labels[k][0] == "azurerm_storage_account":
                return self.labels[k][1]
        return None


def _pick_spec(res):
    cands = _ARM_SPECS.get(res["type"].lower()) or []
    for s in cands:
        if s.get("match") is None or s["match"](res):
            return s
    return None


def _prepare(r, sub, rg):
    names = [x for x in str(r["name"]).split("/")]
    b = r["body"]
    res = {"id": r["id"], "api": r.get("apiVersion"), "type": canon_type(r["type"]), "name": r["name"], "names": names, "leaf": names[-1], "body": b,
           "props": b.get("properties") or {}, "sku": b.get("sku"), "tags": b.get("tags") or {}}
    segs = r["id"].split("/providers/", 1)[-1].split("/")
    ns, rest = segs[0], segs[1:]
    chain = []
    for i in range(0, len(rest) - 2, 2):
        chain.append(f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{ns}/" + "/".join(rest[:i + 2]))
    res["parent_ids"] = chain
    return res


def to_terraform(template: dict, subscription: str, rg: str, rg_location: str = None, source_unmapped: bool = True) -> str:
    ctx = D.Ctx(subscription, rg, template.get("parameters"), template.get("variables"), rg_location or "eastus")
    for pn, pd in (template.get("parameters") or {}).items():
        dv = (pd or {}).get("defaultValue")
        try:
            ctx.param_vals[pn] = D.evaluate(ctx, dv) if dv is not None else ""
        except D.TemplateError:
            ctx.param_vals[pn] = ""
    steps = D.plan(ctx, template)
    X = _Exp(steps, subscription, rg, rg_location or (steps[0]["body"].get("location") if steps else "eastus"))
    # pass 1: choose spec + label (stable, unique per tf type)
    chosen, used = [], set()
    for r in steps:
        res = _prepare(r, subscription, rg)
        sp = _pick_spec(res)
        if sp is None:
            chosen.append((res, None))
            continue
        base = _sym(res["leaf"] if sp.get("names", 1) == 1 else "_".join(res["names"][-2:]))
        label, i = base, 2
        while (sp["tf"], label) in used:
            label, i = f"{base}_{i}", i + 1
        used.add((sp["tf"], label))
        X.labels[res["id"].lower()] = (sp["tf"], label)
        chosen.append((res, sp))
    blocks, skipped, fallback = [], [], []
    rg_attrs = {"name": Raw("var.resource_group_name"), "location": Raw("var.location")}
    blocks.append(H.resource_text("azurerm_resource_group", "rg", rg_attrs))
    for res, sp in chosen:
        if res["type"].lower() in _IGNORED_CHILD:
            skipped.append(f"{res['type']}/{res['name']} (platform default child resource, not managed by azurerm)")
            continue
        if sp is None:
            blocks.append(_azapi_block(res, X, subscription, rg))
            fallback.append(f"{res['type']}/{res['name']}")
            continue
        tf, label = X.labels[res["id"].lower()]
        attrs = sp["to"](res, X)
        attrs = {k: v for k, v in attrs.items() if v is not None}
        blocks.append(H.resource_text(tf, label, attrs))
        if sp.get("extras"):
            for etf, elabel, eattrs in sp["extras"](res, X):
                blocks.append(H.resource_text(etf, elabel, {k: v for k, v in eattrs.items() if v is not None}))
    head = ["terraform {", "  required_providers {", "    azurerm = {", '      source  = "hashicorp/azurerm"', '      version = "~> 4.0"', "    }"]
    if fallback:
        head += ["    azapi = {", '      source = "Azure/azapi"', "    }"]
    head += ["  }", "}", "", 'provider "azurerm" {', "  features {}", "  subscription_id = var.subscription_id", "}", ""]
    variables = [("subscription_id", subscription, "Azure subscription id", False),
                 ("resource_group_name", rg, "Resource group that holds the resources", False),
                 ("location", (X.rg_location or "eastus"), "Azure region of the resource group", False)]
    vtxt = ""
    for n, d, desc, sens in variables:
        vtxt += f'variable "{n}" {{\n  type        = string\n  description = {H.hq(desc)}\n  default     = {H.hq(d)}\n}}\n\n'
    seen = set()
    for item in X.secret_vars:
        n, desc = item[0], item[1]
        sens = item[2] if len(item) > 2 else True
        if n in seen:
            continue
        seen.add(n)
        vtxt += f'variable "{n}" {{\n  type        = string\n  description = {H.hq(desc)}\n' + ("  sensitive   = true\n" if sens else "") + "}\n\n"
    out = "\n".join(head) + "\n" + vtxt + "\n".join(blocks)
    notes = []
    if skipped:
        notes += ["# Skipped (not representable as an azurerm resource):"] + [f"#   - {s}" for s in skipped]
    if fallback:
        notes += ["# Exported with the generic azapi_resource (no azurerm mapping for these ARM types):"] + [f"#   - {s}" for s in fallback]
    return out.rstrip() + "\n" + ("\n" + "\n".join(notes) + "\n" if notes else "")


def _azapi_block(res, X, sub, rg):
    tf = "azapi_resource"
    label = _sym(res["type"].split("/", 1)[-1].replace("/", "_") + "_" + res["name"].replace("/", "_"))
    parent = res["parent_ids"][-1] if res["parent_ids"] else f"/subscriptions/{sub}/resourceGroups/{rg}"
    attrs = {"type": f"{res['type']}@{res.get('api') or '2023-01-01'}", "name": res["leaf"], "parent_id": X.ref_id(parent, "id") if parent != X.rg_id else Raw("azurerm_resource_group.rg.id")}
    b = res["body"]
    if b.get("location"):
        attrs["location"] = X.loc(res)
    if b.get("tags"):
        attrs["tags"] = b["tags"]
    body = {k: v for k, v in b.items() if k in ("properties", "sku", "kind", "identity")}
    if body:
        attrs["body"] = body
    X.labels.setdefault(res["id"].lower(), ("azapi_resource", label))
    return H.resource_text(tf, label, attrs)


# ═══════════════════════════ IMPORT ═════════════════════════════════════════════════════════════
def _q(s):
    return "'" + str(s).replace("'", "''") + "'"


class A:
    """Accessor over one parsed resource/nested block, converting attribute values to ARM template values."""

    def __init__(self, imp, body, addr):
        self.imp, self.body, self.addr = imp, body, addr

    def has(self, k):
        return k in self.body.attrs

    def raw(self, k):
        return self.body.attrs.get(k)

    def v(self, k, default=None):
        if k not in self.body.attrs:
            return default
        return self.imp.conv(self.body.attrs[k], self.addr)

    def b(self, k):
        out = [A(self.imp, bl[2], self.addr) for bl in self.body.blocks if bl[0] == k]
        if not out and isinstance(self.body.attrs.get(k), list):    # attr-style list of objects
            for o in self.body.attrs[k]:
                if isinstance(o, dict):
                    bd = H.Body()
                    bd.attrs = o
                    out.append(A(self.imp, bd, self.addr))
        return out


class _Imp:
    def __init__(self):
        self.addr = {}          # (tf_type, label) -> {"arm","names":[body exprs], "spec"}
        self.warnings = []
        self.unsupported = []
        self.params = {}

    def warn(self, m):
        self.warnings.append(m)

    # expression body (no [ ]) for a node
    def body_of(self, node, ctx_addr=None):
        if isinstance(node, str):
            return _q(node)
        if isinstance(node, bool):
            return "true" if node else "false"
        if node is None:
            return "null"
        if isinstance(node, (int, float)):
            return str(node)
        if isinstance(node, H.Interp):
            parts = [self.body_of(p) for p in node]
            return parts[0] if len(parts) == 1 else "concat(" + ", ".join(parts) + ")"
        if isinstance(node, H.Ref):
            return self.ref_body(node)
        if isinstance(node, H.Call):
            return self.call_body(node)
        if isinstance(node, H.Expr):
            raise Unsup(f"expression '{str(node)[:60]}' is not supported")
        if isinstance(node, (list, dict)):
            return f"json({_q(__import__('json').dumps(self.conv(node)))})"
        raise Unsup(f"unsupported value {node!r}")

    def call_body(self, c):
        n = c.name.lower()
        m = {"lower": "toLower", "upper": "toUpper", "concat": "concat", "format": None, "trimspace": "trim", "length": "length", "replace": "replace",
             "substr": "substring", "join": None}
        if n in m and m[n]:
            return f"{m[n]}(" + ", ".join(self.body_of(x) for x in c.args) + ")"
        raise Unsup(f"function {c.name}() is not supported")

    def target(self, t, label):
        e = self.addr.get((t, label))
        if e is None:
            raise Unsup(f"reference to {t}.{label}, which is not defined in this configuration")
        return e

    def id_body(self, e):
        return f"resourceId({_q(e['arm'])}, " + ", ".join(e["names"]) + ")"

    def ref_body(self, r):
        s = list(r)
        if s[0] == "var" and len(s) >= 2:
            self.used_var = getattr(self, "used_var", set())
            self.used_var.add(s[1])
            return f"parameters({_q(s[1])})"
        if s[0] == "data" and len(s) >= 4:
            if s[1] == "azurerm_client_config":
                m = {"tenant_id": "subscription().tenantId", "subscription_id": "subscription().subscriptionId"}
                if s[3] in m:
                    return m[s[3]]
            if s[1] == "azurerm_subscription":
                m = {"id": "subscription().id", "subscription_id": "subscription().subscriptionId", "tenant_id": "subscription().tenantId"}
                if s[3] in m:
                    return m[s[3]]
            raise Unsup(f"data source reference {'.'.join(map(str, s[:4]))} is not supported")
        if s[0] == "local" or s[0] == "locals":
            raise Unsup("locals are not supported (inline the value or use a variable)")
        if s[0] in ("count", "each", "path", "terraform", "module"):
            raise Unsup(f"reference to {s[0]}.* is not supported")
        if len(s) >= 3 and s[0] == "azurerm_resource_group":
            m = {"name": "resourceGroup().name", "id": "resourceGroup().id", "location": "resourceGroup().location"}
            if s[2] in m:
                return m[s[2]]
        if len(s) >= 3:
            e = self.target(s[0], s[1])
            attr = s[2]
            if attr == "id":
                return self.id_body(e)
            if attr == "name":
                return e["names"][-1]
            if attr == "location":
                return f"reference({self.id_body(e)}, {_q(e['api'])}, 'Full').location"
            if attr in ("principal_id", "client_id", "tenant_id") and s[0] in ("azurerm_user_assigned_identity",):
                return f"reference({self.id_body(e)}, {_q(e['api'])}).{ {'principal_id': 'principalId', 'client_id': 'clientId', 'tenant_id': 'tenantId'}[attr] }"
            raise Unsup(f"attribute {s[0]}.{s[1]}.{attr} is not supported (computed at apply time)")
        raise Unsup(f"reference {'.'.join(map(str, s))} is not supported")

    def conv(self, node, addr=None):
        if isinstance(node, (str, int, float, bool)) or node is None:
            if isinstance(node, str) and node.startswith("["):
                return "[" + node
            return node
        if isinstance(node, (H.Interp, H.Ref, H.Call)):
            return "[" + self.body_of(node) + "]"
        if isinstance(node, H.Expr):
            raise Unsup(f"expression '{str(node)[:60]}' is not supported")
        if isinstance(node, list):
            return [self.conv(x, addr) for x in node]
        if isinstance(node, dict):
            return {k: self.conv(v, addr) for k, v in node.items()}
        raise Unsup(f"unsupported value {node!r}")


def _dep(imp, body):
    out = []
    node = body.attrs.get("depends_on")
    if isinstance(node, list):
        for r in node:
            if isinstance(r, H.Ref) and len(r) >= 2:
                if r[0] == "azurerm_resource_group":
                    continue
                e = imp.target(r[0], r[1])
                out.append("[" + imp.id_body(e) + "]")
    return out


_TFT = {"string": "string", "number": "int", "bool": "bool"}


def terraform_to_arm(text: str, default_location: str = None) -> dict:
    """HCL -> {template, unsupported:[{address, reason}], warnings:[...], mapped:[...]}"""
    try:
        mod = H.parse(text)
    except H.HclError as e:
        return {"template": None, "error": f"Terraform syntax error: {e}", "unsupported": [], "warnings": [], "mapped": []}
    imp = _Imp()
    unsupported, mapped = [], []
    params = {}
    for typ, labels, body, line in mod.blocks:
        if typ == "variable" and labels:
            name = labels[0]
            a = A(imp, body, f"var.{name}")
            tf_t = body.attrs.get("type")
            tname = tf_t.text() if isinstance(tf_t, H.Ref) else (tf_t if isinstance(tf_t, str) else "string")
            tname = str(tname).split("(")[0] if not isinstance(tf_t, H.Call) else tf_t.name
            if isinstance(tf_t, H.Call):
                tname = tf_t.name
            at = {"string": "string", "number": "int", "bool": "bool", "list": "array", "set": "array", "tuple": "array", "map": "object", "object": "object", "any": "string"}.get(tname, "string")
            if body.attrs.get("sensitive") is True and at == "string":
                at = "securestring"
            pd = {"type": at}
            if "default" in body.attrs:
                try:
                    pd["defaultValue"] = a.v("default")
                except Unsup:
                    pass
            if "description" in body.attrs and isinstance(body.attrs["description"], str):
                pd["metadata"] = {"description": body.attrs["description"]}
            params[name] = pd
    rg_blocks = {}
    # pass 1: addresses
    res_blocks = []
    for typ, labels, body, line in mod.blocks:
        if typ != "resource" or len(labels) != 2:
            continue
        t, label = labels
        addr = f"{t}.{label}"
        if t == "azurerm_resource_group":
            rg_blocks[label] = body
            imp.addr[(t, label)] = {"arm": "Microsoft.Resources/resourceGroups", "names": ["resourceGroup().name"], "api": "2021-04-01"}
            continue
        sp = BY_TF.get(t)
        if t == "azapi_resource":
            res_blocks.append((t, label, body, None, addr))
            continue
        if sp is None:
            unsupported.append({"address": addr, "reason": f"resource type {t} is not supported by the importer"})
            continue
        res_blocks.append((t, label, body, sp, addr))
    for t, label, body, sp, addr in res_blocks:
        try:
            if sp is None or sp.get("arm") is None:
                if t == "azapi_resource":
                    _azapi_names(imp, t, label, body, addr)
                continue
            names = _names_for(imp, sp, body, addr)
            imp.addr[(t, label)] = {"arm": sp["arm"], "names": names, "api": sp["api"], "spec": sp}
        except Unsup as e:
            unsupported.append({"address": addr, "reason": str(e)})
    resources, patches = [], []
    for t, label, body, sp, addr in res_blocks:
        if (t, label) not in imp.addr and not (sp and (sp.get("patch") or sp.get("append"))):
            if not any(u["address"] == addr for u in unsupported):
                unsupported.append({"address": addr, "reason": "could not be resolved"})
            continue
        try:
            for meta in ("count", "for_each", "provider"):
                if meta in body.attrs:
                    raise Unsup(f"meta-argument '{meta}' is not supported")
            if t == "azapi_resource":
                resources.append(_azapi_to_arm(imp, t, label, body, addr))
                mapped.append(addr)
                continue
            if sp.get("patch"):
                patches.append((sp, body, addr))
                continue
            if sp.get("append"):
                patches.append((sp, body, addr))
                continue
            a = A(imp, body, addr)
            e = imp.addr[(t, label)]
            out = sp["frm"](a, imp)
            scope = out.pop("_scope", None)
            names = e["names"]
            lit = all(n.startswith("'") and n.endswith("'") and "''" not in n[1:-1] for n in names)
            name_val = "/".join(n[1:-1] for n in names) if lit else "[" + ("concat(" + ", '/', ".join(names) + ")" if len(names) > 1 else names[0]) + "]"
            r = {"type": sp["arm"], "apiVersion": sp["api"], "name": name_val}
            if sp.get("loc") or sp.get("global_loc"):
                r["location"] = "global" if sp.get("global_loc") else (a.v("location") if a.has("location") else "[resourceGroup().location]")
            for k in ("kind", "sku", "identity"):
                if out.get(k):
                    r[k] = out[k]
            if body.attrs.get("tags") is not None and (sp.get("loc") or sp.get("global_loc") or sp.get("tags_ok")):
                tg = a.v("tags")
                if tg:
                    r["tags"] = tg
            if sp.get("global_loc") and a.has("tags"):
                r["tags"] = a.v("tags")
            r["properties"] = out.get("properties") or {}
            if scope is not None:
                r["scope"] = scope
            if not r["properties"]:
                r.pop("properties")
            deps = _dep(imp, body)
            if deps:
                r["dependsOn"] = deps
            r["_addr"] = (t, label)
            resources.append(r)
            mapped.append(addr)
        except Unsup as ex:
            unsupported.append({"address": addr, "reason": str(ex)})
    byaddr = {r["_addr"]: r for r in resources if "_addr" in r}
    for sp, body, addr in patches:
        try:
            a = A(imp, body, addr)
            if sp.get("patch"):
                sub_attr, val_attr, arm_key = sp["patch"]
                node = body.attrs.get(sub_attr)
                if not isinstance(node, H.Ref) or len(node) < 2 or (node[0], node[1]) not in byaddr:
                    raise Unsup(f"{sub_attr} must reference an azurerm_subnet defined in this configuration")
                tgt = byaddr[(node[0], node[1])]
                tgt.setdefault("properties", {})[arm_key] = {"id": a.v(val_attr)}
                mapped.append(addr)
            else:
                cl_attr, key, mk = sp["append"]
                node = body.attrs.get(cl_attr)
                if not isinstance(node, H.Ref) or len(node) < 2 or (node[0], node[1]) not in byaddr:
                    raise Unsup(f"{cl_attr} must reference an azurerm_kubernetes_cluster defined in this configuration")
                pool = mk(a)
                pool.setdefault("mode", "User")
                byaddr[(node[0], node[1])]["properties"].setdefault(key, []).append(pool)
                mapped.append(addr)
        except Unsup as ex:
            unsupported.append({"address": addr, "reason": str(ex)})
    for r in resources:
        r.pop("_addr", None)
    outputs = {}
    for typ, labels, body, line in mod.blocks:
        if typ == "output" and labels and "value" in body.attrs:
            try:
                outputs[labels[0]] = {"type": "string", "value": imp.conv(body.attrs["value"])}
            except Unsup as ex:
                unsupported.append({"address": f"output.{labels[0]}", "reason": str(ex)})
    for typ, labels, body, line in mod.blocks:
        if typ == "data" and len(labels) == 2 and labels[0] not in ("azurerm_client_config", "azurerm_subscription"):
            unsupported.append({"address": f"data.{labels[0]}.{labels[1]}", "reason": "data sources are not supported (use literal ids)"})
        elif typ == "module":
            unsupported.append({"address": f"module.{labels[0] if labels else ''}", "reason": "modules are not supported"})
    tpl = {"$schema": D_SCHEMA, "contentVersion": "1.0.0.0", "parameters": params, "variables": {}, "resources": resources}
    if outputs:
        tpl["outputs"] = outputs
    rgb = next(iter(rg_blocks.values()), None)
    info = {}
    if rgb is not None:
        try:
            info = {"name": A(imp, rgb, "azurerm_resource_group").v("name"), "location": A(imp, rgb, "azurerm_resource_group").v("location")}
        except Unsup:
            info = {}
    return {"template": tpl, "unsupported": unsupported, "warnings": imp.warnings, "mapped": mapped, "resourceGroup": info}


D_SCHEMA = "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#"


def _names_for(imp, sp, body, addr):
    nm = body.attrs.get("name")
    if nm is None:
        if sp.get("literal_name"):
            nm = "[guid]"
        else:
            raise Unsup("attribute 'name' is required")
    own = "guid(" + ", ".join([imp.body_of(body.attrs.get("scope", "rg")), imp.body_of(body.attrs.get("principal_id")), imp.body_of(body.attrs.get("role_definition_name") or body.attrs.get("role_definition_id"))]) + ")" if nm == "[guid]" else imp.body_of(nm)
    parent = sp.get("parent")
    if not parent:
        return [own]
    attr, kind = parent
    node = body.attrs.get(attr)
    if node is None:
        raise Unsup(f"attribute '{attr}' is required")
    if isinstance(node, H.Ref) and len(node) >= 3 and node[0] in BY_TF:
        e = imp.target(node[0], node[1])
        return list(e["names"]) + [own]
    if isinstance(node, str) and kind == "name":
        # literal parent name (the parent lives outside this configuration)
        base = [_q(node)]
        if sp["names"] == 3:
            raise Unsup("literal parent names are not supported for this resource type")
        return base + [own]
    if isinstance(node, str) and kind == "id":
        m = re.search(r"/providers/[^/]+/(?:[^/]+/[^/]+/)*", node)
        segs = node.split("/providers/", 1)[-1].split("/")[1:]
        pn = [_q(segs[i]) for i in range(1, len(segs), 2)]
        if pn:
            return pn + [own]
    raise Unsup(f"cannot resolve the parent resource from '{attr}'")


def _azapi_names(imp, t, label, body, addr):
    typ = body.attrs.get("type")
    if not isinstance(typ, str) or "@" not in typ:
        raise Unsup("azapi_resource 'type' must be a literal like 'Microsoft.X/y@2023-01-01'")
    arm, _, ver = typ.partition("@")
    own = imp.body_of(body.attrs.get("name"))
    pid = body.attrs.get("parent_id")
    names = [own]
    if isinstance(pid, H.Ref) and len(pid) >= 2 and (pid[0], pid[1]) in imp.addr and pid[0] != "azurerm_resource_group":
        names = list(imp.addr[(pid[0], pid[1])]["names"]) + [own]
    elif isinstance(pid, str) and "/providers/" in pid:
        segs = pid.split("/providers/", 1)[-1].split("/")[1:]
        names = [_q(segs[i]) for i in range(1, len(segs), 2)] + [own]
    imp.addr[(t, label)] = {"arm": arm, "names": names, "api": ver}


def _azapi_to_arm(imp, t, label, body, addr):
    e = imp.addr[(t, label)]
    names = e["names"]
    lit = all(n.startswith("'") and n.endswith("'") for n in names)
    name_val = "/".join(n[1:-1] for n in names) if lit else "[" + ("concat(" + ", '/', ".join(names) + ")" if len(names) > 1 else names[0]) + "]"
    r = {"type": e["arm"], "apiVersion": e["api"], "name": name_val}
    if "location" in body.attrs:
        r["location"] = imp.conv(body.attrs["location"])
    if "tags" in body.attrs:
        r["tags"] = imp.conv(body.attrs["tags"])
    b = body.attrs.get("body")
    if isinstance(b, dict):
        for k, v in imp.conv(b).items():
            r[k] = v
    deps = _dep(imp, body)
    if deps:
        r["dependsOn"] = deps
    return r
