"""Azure network-service control plane (Nano / dev_server / unified-ingress core, substrate-free).

Real ARM resources with real validation and cross-resource checks, stored in the same flat ARM state map
the rest of ``azure_arm_core`` uses (keyed by lower-cased resource id):

* ``Microsoft.Network/privateEndpoints`` -- subnet must exist, target resource must exist, ``groupIds`` must be a
  valid sub-resource of that target type, a private IP is allocated from the subnet (NIC + customDnsConfigs
  produced), and a ``privateEndpointConnections/{pe}.{guid}`` child is written on the target. Connections are
  auto-approved for ``privateLinkServiceConnections`` and Pending for ``manualPrivateLinkServiceConnections``;
  approving / rejecting the target-side connection flows back to the endpoint.
* ``Microsoft.Network/bastionHosts`` -- needs an ``AzureBastionSubnet`` of at least /26 in the vnet and a Standard
  static public IP; SKU-gated features (Basic/Developer/Standard/Premium) and scale units.
* ``Microsoft.Network/azureFirewalls`` (+ ``firewallPolicies``) -- ``AzureFirewallSubnet`` >= /26, Standard static
  public IP, tier must match the attached policy's tier, Basic needs ``AzureFirewallManagementSubnet`` + a management
  IP, rule-collection priorities 100..65000 and unique; a private IP is allocated from the subnet.
* ``Microsoft.Network/ddosProtectionPlans`` -- attaching to a vnet (``enableDdosProtection`` + plan id) is validated
  and tracked; a plan in use cannot be deleted.
* ``Microsoft.Network/networkWatchers/{nw}/flowLogs`` -- target NSG/vnet and storage account must exist, same region as
  the watcher, retention 0..365, version 1|2, one flow log per target.

NOT modelled (honest limits, see core/capabilities/azure/vnets.json + nsgs.json): no packet is ever routed through a
private endpoint / firewall / bastion, no DDoS mitigation happens, and flow logs record configuration only -- no flow
tuples are produced because there is no packet-level data plane in the simulator.
"""
from __future__ import annotations

import datetime
import ipaddress
import uuid

NET = "microsoft.network"
PE = "microsoft.network/privateendpoints"
BASTION = "microsoft.network/bastionhosts"
FIREWALL = "microsoft.network/azurefirewalls"
POLICY = "microsoft.network/firewallpolicies"
POLICY_RCG = "microsoft.network/firewallpolicies/rulecollectiongroups"
DDOS = "microsoft.network/ddosprotectionplans"
FLOWLOG = "microsoft.network/networkwatchers/flowlogs"
VNET = "microsoft.network/virtualnetworks"
STORAGE = "microsoft.storage/storageaccounts"
SQL_VNET_RULE = "microsoft.sql/servers/virtualnetworkrules"
PEC_SUFFIX = "/privateendpointconnections"

# target resource type -> valid private-link sub-resources (groupIds) and DNS zone suffix per group
PRIVATE_LINK = {
    "microsoft.storage/storageaccounts": {"blob": "privatelink.blob.core.windows.net", "blob_secondary": "privatelink.blob.core.windows.net",
                                          "file": "privatelink.file.core.windows.net", "queue": "privatelink.queue.core.windows.net",
                                          "table": "privatelink.table.core.windows.net", "web": "privatelink.web.core.windows.net",
                                          "dfs": "privatelink.dfs.core.windows.net"},
    "microsoft.keyvault/vaults": {"vault": "privatelink.vaultcore.azure.net"},
    "microsoft.sql/servers": {"sqlserver": "privatelink.database.windows.net"},
    "microsoft.documentdb/databaseaccounts": {"sql": "privatelink.documents.azure.com", "mongodb": "privatelink.mongo.cosmos.azure.com",
                                              "cassandra": "privatelink.cassandra.cosmos.azure.com", "gremlin": "privatelink.gremlin.cosmos.azure.com",
                                              "table": "privatelink.table.cosmos.azure.com"},
    "microsoft.containerregistry/registries": {"registry": "privatelink.azurecr.io"},
    "microsoft.cache/redis": {"rediscache": "privatelink.redis.cache.windows.net"},
    "microsoft.servicebus/namespaces": {"namespace": "privatelink.servicebus.windows.net"},
    "microsoft.eventgrid/topics": {"topic": "privatelink.eventgrid.azure.net"},
    "microsoft.eventgrid/domains": {"domain": "privatelink.eventgrid.azure.net"},
    "microsoft.appconfiguration/configurationstores": {"configurationstores": "privatelink.azconfig.io"},
    "microsoft.cognitiveservices/accounts": {"account": "privatelink.cognitiveservices.azure.com"},
    "microsoft.web/sites": {"sites": "privatelink.azurewebsites.net"},
    "microsoft.containerservice/managedclusters": {"management": "privatelink.eastus.azmk8s.io"},
}
# resource types whose own engine owns the privateEndpointConnections list (not mirrored as flat children here)
OWN_ENGINE_PEC = {"microsoft.appconfiguration/configurationstores", "microsoft.cognitiveservices/accounts"}

BASTION_SKUS = ("Basic", "Standard", "Developer", "Premium")
FIREWALL_TIERS = ("Basic", "Standard", "Premium")
FLOWLOG_VERSIONS = (1, 2)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status: int, code: str, message: str) -> dict:
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def handles(full_type: str) -> bool:
    ft = full_type.lower()
    return ft in (PE, BASTION, FIREWALL, POLICY, POLICY_RCG, DDOS, FLOWLOG, VNET, STORAGE, SQL_VNET_RULE) or ft.endswith(PEC_SUFFIX)


# ── helpers ────────────────────────────────────────────────────────────────────────────
def _ref(obj) -> str:
    return str((obj or {}).get("id") or "") if isinstance(obj, dict) else ""


def _type_of(rid: str) -> str:
    """Resource type of an ARM id (Microsoft.Storage/storageAccounts) — handles nested children too."""
    parts = [p for p in rid.split("/") if p]
    try:
        i = [p.lower() for p in parts].index("providers")
    except ValueError:
        return ""
    rest = parts[i + 1:]
    ns = rest[0]
    types = rest[1::2]
    return "/".join([ns] + types).lower()


def _subnet_split(subnet_id: str):
    sid = subnet_id.lower()
    vnet_id, _, name = sid.rpartition("/subnets/")
    return vnet_id, name


def _subnet(state: dict, subnet_id: str):
    """(subnet record-ish dict {name, prefix}, vnet rec) or (None, None)."""
    vnet_id, name = _subnet_split(subnet_id)
    vnet = state.get(vnet_id)
    if vnet is None or (vnet.get("_type") or "").lower() != VNET:
        return None, None
    for s in (vnet.get("properties") or {}).get("subnets") or []:
        if str(s.get("name", "")).lower() == name:
            p = s.get("properties") or {}
            pref = p.get("addressPrefix") or (p.get("addressPrefixes") or [None])[0]
            return {"name": s.get("name"), "prefix": pref, "id": s.get("id") or subnet_id}, vnet
    rec = state.get(subnet_id.lower())
    if rec is not None:
        p = rec.get("properties") or {}
        pref = p.get("addressPrefix") or (p.get("addressPrefixes") or [None])[0]
        return {"name": rec.get("name"), "prefix": pref, "id": rec.get("id")}, vnet
    return None, None


def _used_ips(state: dict, subnet_prefix: str) -> set:
    net = ipaddress.ip_network(subnet_prefix, strict=False)
    used = set()

    def scan(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "privateIPAddress" and isinstance(v, str):
                    try:
                        if ipaddress.ip_address(v) in net:
                            used.add(v)
                    except ValueError:
                        pass
                else:
                    scan(v)
        elif isinstance(o, list):
            for v in o:
                scan(v)
    for rec in state.values():
        if isinstance(rec, dict) and rec.get("_type", "").lower().startswith(NET + "/"):
            scan(rec.get("properties"))
            for k in ("_private_ip", "_fw_ip"):
                v = rec.get(k)
                try:
                    if v and ipaddress.ip_address(v) in net:
                        used.add(v)
                except ValueError:
                    pass
    return used


def alloc_ip(state: dict, subnet_prefix: str):
    net = ipaddress.ip_network(subnet_prefix, strict=False)
    used = _used_ips(state, subnet_prefix)
    for h in net.hosts():
        s = str(h)
        # Azure reserves .0 .1 .2 .3 and the broadcast address in every subnet
        if int(h) - int(net.network_address) < 4 or s in used:
            continue
        return s
    return None


def _public_ip(state: dict, pip_id: str, need_standard=True):
    pip = state.get(pip_id.lower())
    if pip is None or (pip.get("_type") or "").lower() != "microsoft.network/publicipaddresses":
        return None, _err(400, "InvalidResourceReference", f"Resource {pip_id} referenced by resource was not found. Please make sure that the referenced resource exists, and that both resources are in the same region.")
    if need_standard:
        sku = ((pip.get("sku") or {}).get("name") or "Basic")
        method = (pip.get("properties") or {}).get("publicIPAllocationMethod") or "Dynamic"
        if sku != "Standard" or method != "Static":
            return None, _err(400, "PublicIPAddressMustBeStandardStatic", f"Public IP address {pip.get('name')} must use the Standard SKU with Static allocation.")
    return pip, None


def _hostmin(prefix: str, bits: int) -> bool:
    try:
        return ipaddress.ip_network(prefix, strict=False).prefixlen <= bits
    except ValueError:
        return False


def _pe_conn_status(conn: dict) -> str:
    return str(((conn.get("properties") or {}).get("privateLinkServiceConnectionState") or {}).get("status") or "Pending")


# ── pre-write validation ────────────────────────────────────────────────────────────────
def validate(state: dict, full_type: str, rid: str, payload: dict, existing: dict | None, sub: str, rg: str | None):
    ft = full_type.lower()
    props = (payload or {}).get("properties") or {}
    if ft == PE:
        return _validate_pe(state, rid, payload, props, existing)
    if ft == BASTION:
        return _validate_bastion(state, rid, payload, props)
    if ft == FIREWALL:
        return _validate_firewall(state, rid, payload, props)
    if ft == POLICY:
        return _validate_policy(state, rid, payload, props)
    if ft == POLICY_RCG:
        return _validate_rcg(state, rid, props)
    if ft == FLOWLOG:
        return _validate_flowlog(state, rid, payload, props, existing)
    if ft == VNET:
        return _validate_vnet_ddos(state, rid, props)
    if ft == STORAGE:
        acls = props.get("networkAcls") or {}
        return _validate_ip_rules(acls.get("ipRules")) or _validate_vnet_rules(state, acls.get("virtualNetworkRules"), "Microsoft.Storage", id_key="id")
    if ft == SQL_VNET_RULE:
        sid = props.get("virtualNetworkSubnetId")
        if not sid:
            return _err(400, "InvalidVirtualNetworkRule", "properties.virtualNetworkSubnetId is required.")
        parent = rid.rsplit("/virtualNetworkRules/", 1)[0]
        if state.get(parent.lower()) is None:
            return _err(404, "ParentResourceNotFound", f"The SQL server {parent} was not found.")
        return _validate_vnet_rules(state, [{"id": sid}], "Microsoft.Sql", id_key="id")
    if ft.endswith(PEC_SUFFIX):
        if existing is None:
            return _err(404, "ResourceNotFound", "Private endpoint connections are created by a private endpoint; there is nothing at this id to approve or reject.")
        return _validate_pec_put(state, rid, props)
    return None


def _validate_pe(state, rid, payload, props, existing):
    subnet_id = _ref(props.get("subnet")) or _ref(((existing or {}).get("properties") or {}).get("subnet"))
    if not subnet_id:
        return _err(400, "MissingSubnet", "Private endpoint must have a subnet (properties.subnet.id).")
    sn, _vnet = _subnet(state, subnet_id)
    if sn is None:
        return _err(400, "InvalidResourceReference", f"Resource {subnet_id} referenced by resource {rid} was not found. Please make sure that the referenced resource exists, and that both resources are in the same region.")
    conns = list(props.get("privateLinkServiceConnections") or []) + list(props.get("manualPrivateLinkServiceConnections") or [])
    if not conns:
        if existing and (existing.get("properties") or {}).get("privateLinkServiceConnections") is not None:
            return None
        return _err(400, "PrivateEndpointRequiresConnection", "Private endpoint must have at least one private link service connection (privateLinkServiceConnections or manualPrivateLinkServiceConnections).")
    for c in conns:
        cp = c.get("properties") or {}
        target = str(cp.get("privateLinkServiceId") or "")
        if not target:
            return _err(400, "PrivateLinkServiceIdRequired", "privateLinkServiceConnections[].properties.privateLinkServiceId is required.")
        trec = state.get(target.lower())
        if trec is None:
            return _err(400, "PrivateLinkServiceNotFound", f"The private link service resource {target} was not found.")
        ttype = _type_of(target)
        groups = PRIVATE_LINK.get(ttype)
        if groups is None:
            return _err(400, "PrivateLinkServiceCannotBeUsed", f"Resource type {trec.get('type')} does not support private endpoints in Vyomi.")
        gids = cp.get("groupIds") or []
        if not gids:
            return _err(400, "PrivateEndpointGroupIdRequired", f"groupIds is required for a private link service of type {trec.get('type')}. Valid values: {', '.join(sorted(groups))}.")
        for g in gids:
            if str(g).lower() not in groups:
                return _err(400, "PrivateEndpointGroupIdNotSupported", f"The group id '{g}' is not valid for {trec.get('type')}. Valid values: {', '.join(sorted(groups))}.")
    names = [str(c.get("name") or "") for c in conns]
    if len(set(n.lower() for n in names)) != len(names):
        return _err(400, "DuplicatePrivateLinkServiceConnectionName", "Private link service connection names must be unique within a private endpoint.")
    return None


def _validate_bastion(state, rid, payload, props):
    sku = (payload.get("sku") or {}).get("name") or "Standard"
    if sku not in BASTION_SKUS:
        return _err(400, "InvalidSku", f"Bastion SKU '{sku}' is not valid. Allowed: {', '.join(BASTION_SKUS)}.")
    if sku == "Developer":
        vnet_id = _ref(props.get("virtualNetwork"))
        if not vnet_id or state.get(vnet_id.lower()) is None:
            return _err(400, "InvalidResourceReference", "Developer SKU bastion needs properties.virtualNetwork.id of an existing virtual network.")
        return None
    cfgs = props.get("ipConfigurations") or []
    if not cfgs:
        return _err(400, "BastionIpConfigurationRequired", "Bastion host requires one IP configuration (subnet + public IP).")
    cp = cfgs[0].get("properties") or {}
    sid = _ref(cp.get("subnet"))
    sn, _v = _subnet(state, sid) if sid else (None, None)
    if sn is None:
        return _err(400, "InvalidResourceReference", f"Resource {sid or '(subnet)'} referenced by the bastion was not found.")
    if str(sn["name"]).lower() != "azurebastionsubnet":
        return _err(400, "InvalidBastionSubnetName", "Bastion must be deployed to a subnet named 'AzureBastionSubnet'.")
    if not sn["prefix"] or not _hostmin(sn["prefix"], 26):
        return _err(400, "InvalidBastionSubnetSize", "AzureBastionSubnet must be /26 or larger.")
    _pip, e = _public_ip(state, _ref(cp.get("publicIPAddress")))
    if e:
        return e
    scale = props.get("scaleUnits")
    if scale is not None:
        lo, hi = (2, 2) if sku == "Basic" else (2, 50)
        if not isinstance(scale, int) or scale < lo or scale > hi:
            return _err(400, "InvalidBastionScaleUnits", f"scaleUnits for the {sku} SKU must be between {lo} and {hi}.")
    if sku == "Basic":
        for f in ("enableTunneling", "enableIpConnect", "enableShareableLink", "enableKerberos", "enableFileCopy", "enableSessionRecording"):
            if props.get(f):
                return _err(400, "BastionFeatureRequiresStandardSku", f"'{f}' requires the Standard or Premium SKU.")
    if props.get("enableSessionRecording") and sku != "Premium":
        return _err(400, "BastionFeatureRequiresPremiumSku", "Session recording requires the Premium SKU.")
    return None


def _validate_rule_collections(colls, label):
    seen = set()
    for c in colls or []:
        p = c.get("properties") if "properties" in c else c
        pr = p.get("priority")
        if not isinstance(pr, int) or pr < 100 or pr > 65000:
            return _err(400, "AzureFirewallRuleCollectionPriorityOutOfRange", f"{label} '{c.get('name')}' priority must be between 100 and 65000.")
        if pr in seen:
            return _err(400, "AzureFirewallRuleCollectionPriorityDuplicate", f"Two rule collections in {label} share priority {pr}.")
        seen.add(pr)
    return None


def _validate_firewall(state, rid, payload, props):
    sku = props.get("sku") or {}
    tier = sku.get("tier") or "Standard"
    if tier not in FIREWALL_TIERS:
        return _err(400, "AzureFirewallInvalidSku", f"Azure Firewall tier '{tier}' is not valid. Allowed: {', '.join(FIREWALL_TIERS)}.")
    if sku.get("name") not in (None, "AZFW_VNet", "AZFW_Hub"):
        return _err(400, "AzureFirewallInvalidSku", "sku.name must be AZFW_VNet or AZFW_Hub.")
    if sku.get("name") == "AZFW_Hub":
        return None
    cfgs = props.get("ipConfigurations") or []
    if not cfgs:
        return _err(400, "AzureFirewallIpConfigurationRequired", "Azure Firewall requires an IP configuration (subnet + public IP).")
    cp = cfgs[0].get("properties") or {}
    sid = _ref(cp.get("subnet"))
    sn, vnet = _subnet(state, sid) if sid else (None, None)
    if sn is None:
        return _err(400, "InvalidResourceReference", f"Resource {sid or '(subnet)'} referenced by the firewall was not found.")
    if str(sn["name"]).lower() != "azurefirewallsubnet":
        return _err(400, "AzureFirewallSubnetNameInvalid", "Azure Firewall must be deployed to a subnet named 'AzureFirewallSubnet'.")
    if not sn["prefix"] or not _hostmin(sn["prefix"], 26):
        return _err(400, "AzureFirewallSubnetTooSmall", "AzureFirewallSubnet must be /26 or larger.")
    _p, e = _public_ip(state, _ref(cp.get("publicIPAddress")))
    if e:
        return e
    if tier == "Basic":
        mcfg = props.get("managementIpConfiguration")
        if not mcfg:
            return _err(400, "AzureFirewallManagementIpConfigurationRequired", "The Basic tier requires a managementIpConfiguration (AzureFirewallManagementSubnet + public IP).")
        mp = mcfg.get("properties") or {}
        msid = _ref(mp.get("subnet"))
        msn, _v = _subnet(state, msid) if msid else (None, None)
        if msn is None or str(msn["name"]).lower() != "azurefirewallmanagementsubnet":
            return _err(400, "AzureFirewallManagementSubnetInvalid", "The management IP configuration must use a subnet named 'AzureFirewallManagementSubnet'.")
        _p, e = _public_ip(state, _ref(mp.get("publicIPAddress")))
        if e:
            return e
    pol_id = _ref(props.get("firewallPolicy"))
    if pol_id:
        pol = state.get(pol_id.lower())
        if pol is None or (pol.get("_type") or "").lower() != POLICY:
            return _err(400, "InvalidResourceReference", f"Resource {pol_id} referenced by the firewall was not found.")
        ptier = ((pol.get("properties") or {}).get("sku") or {}).get("tier") or "Standard"
        if ptier != tier:
            return _err(400, "AzureFirewallPolicyTierMismatch", f"The firewall policy tier ({ptier}) must match the firewall tier ({tier}).")
        classic = any(props.get(k) for k in ("applicationRuleCollections", "networkRuleCollections", "natRuleCollections"))
        if classic:
            return _err(400, "AzureFirewallClassicRulesWithPolicy", "A firewall associated with a firewall policy cannot also define classic rule collections.")
    for k in ("applicationRuleCollections", "networkRuleCollections", "natRuleCollections"):
        e = _validate_rule_collections(props.get(k), k)
        if e:
            return e
    return None


def _validate_policy(state, rid, payload, props):
    tier = (props.get("sku") or {}).get("tier") or "Standard"
    if tier not in FIREWALL_TIERS:
        return _err(400, "FirewallPolicyInvalidSku", f"Firewall policy tier '{tier}' is not valid. Allowed: {', '.join(FIREWALL_TIERS)}.")
    base = _ref(props.get("basePolicy"))
    if base:
        bp = state.get(base.lower())
        if bp is None or (bp.get("_type") or "").lower() != POLICY:
            return _err(400, "InvalidResourceReference", f"Base policy {base} was not found.")
        if base.lower() == rid.lower():
            return _err(400, "FirewallPolicyCannotInheritItself", "A firewall policy cannot be its own base policy.")
    tint = props.get("threatIntelMode")
    if tint is not None and tint not in ("Alert", "Deny", "Off"):
        return _err(400, "InvalidThreatIntelMode", "threatIntelMode must be Alert, Deny or Off.")
    if tier != "Premium" and (props.get("intrusionDetection") or {}).get("mode") not in (None, "Off"):
        return _err(400, "FirewallPolicyIdpsRequiresPremium", "Intrusion detection (IDPS) requires the Premium tier.")
    return None


def _validate_rcg(state, rid, props):
    parent_id = rid.rsplit("/ruleCollectionGroups/", 1)[0]
    parent = state.get(parent_id.lower())
    if parent is None:
        return _err(404, "ParentResourceNotFound", f"The firewall policy {parent_id} was not found.")
    pr = props.get("priority")
    if not isinstance(pr, int) or pr < 100 or pr > 65000:
        return _err(400, "FirewallPolicyRuleCollectionGroupPriorityOutOfRange", "Rule collection group priority must be between 100 and 65000.")
    for sib in state.values():
        if sib.get("_type", "").lower() == POLICY_RCG and sib.get("id", "").lower().startswith(parent_id.lower() + "/") and sib.get("id", "").lower() != rid.lower():
            if (sib.get("properties") or {}).get("priority") == pr:
                return _err(400, "FirewallPolicyRuleCollectionGroupPriorityDuplicate", f"Another rule collection group in this policy already uses priority {pr}.")
    return _validate_rule_collections(props.get("ruleCollections"), "ruleCollections")


def _validate_vnet_ddos(state, rid, props):
    if not props.get("enableDdosProtection") and not props.get("ddosProtectionPlan"):
        return None
    plan_id = _ref(props.get("ddosProtectionPlan"))
    if props.get("enableDdosProtection") and not plan_id:
        return _err(400, "DdosProtectionPlanRequired", "enableDdosProtection requires properties.ddosProtectionPlan.id.")
    if plan_id:
        plan = state.get(plan_id.lower())
        if plan is None or (plan.get("_type") or "").lower() != DDOS:
            return _err(400, "InvalidResourceReference", f"Resource {plan_id} referenced by resource {rid} was not found.")
    return None


def _validate_ip_rules(rules):
    seen = set()
    for r in rules or []:
        v = str((r or {}).get("value") or "")
        try:
            net = ipaddress.ip_network(v, strict=False)
        except ValueError:
            return _err(400, "InvalidIpRule", f"The IP rule '{v}' is not a valid IPv4 address or CIDR range.")
        if net.version != 4:
            return _err(400, "InvalidIpRule", "Only IPv4 address ranges are supported in storage IP rules.")
        if net.prefixlen in (31, 32) and "/" in v:
            return _err(400, "InvalidIpRule", f"The IP rule '{v}' is not allowed: /31 and /32 ranges are not supported (use the plain address).")
        if net.is_private:
            return _err(400, "InvalidIpRule", f"The IP rule '{v}' is in a private range (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), which storage firewall rules do not accept; use a virtual network rule.")
        if v in seen:
            return _err(400, "DuplicateIpRule", f"The IP rule '{v}' appears more than once.")
        seen.add(v)
    return None


def _validate_vnet_rules(state, rules, service, id_key="id"):
    """Each rule's subnet must exist and carry the matching service endpoint (the portal enables it for you; ARM rejects without)."""
    seen = set()
    for r in rules or []:
        sid = str((r or {}).get(id_key) or "")
        sn, _v = _subnet(state, sid) if sid else (None, None)
        if sn is None:
            return _err(400, "InvalidVirtualNetworkRule", f"The subnet {sid or '(missing id)'} of the virtual network rule was not found.")
        if sid.lower() in seen:
            return _err(400, "DuplicateVirtualNetworkRule", f"The subnet {sid} appears more than once in virtualNetworkRules.")
        seen.add(sid.lower())
        rec = state.get(sid.lower()) or {}
        eps = (rec.get("properties") or {}).get("serviceEndpoints")
        if eps is None:
            vnet_id, _, name = sid.lower().rpartition("/subnets/")
            for sub in ((state.get(vnet_id) or {}).get("properties") or {}).get("subnets") or []:
                if str(sub.get("name", "")).lower() == name:
                    eps = (sub.get("properties") or {}).get("serviceEndpoints")
        if not any(str(e.get("service", "")).lower() == service.lower() for e in eps or []):
            return _err(400, "SubnetsHaveNoServiceEndpointsConfigured", f"Subnet {sn['name']} does not have a '{service}' service endpoint configured; add the service endpoint on the subnet first.")
    return None


def _validate_flowlog(state, rid, payload, props, existing):
    nw_id = rid.rsplit("/flowLogs/", 1)[0]
    nw = state.get(nw_id.lower())
    if nw is None:
        return _err(404, "ParentResourceNotFound", f"The network watcher {nw_id} was not found.")
    target_id = _ref({"id": props.get("targetResourceId")}) if props.get("targetResourceId") else ((existing or {}).get("properties") or {}).get("targetResourceId")
    if not target_id:
        return _err(400, "FlowLogTargetResourceIdRequired", "properties.targetResourceId is required (a network security group or virtual network id).")
    target = state.get(str(target_id).lower())
    ttype = (target or {}).get("_type", "").lower()
    if target is None or ttype not in ("microsoft.network/networksecuritygroups", VNET):
        return _err(400, "FlowLogTargetNotFound", f"Target resource {target_id} was not found or is not a network security group / virtual network.")
    if (target.get("location") or "").lower() != (nw.get("location") or "").lower():
        return _err(400, "FlowLogRegionMismatch", f"The flow log's network watcher is in {nw.get('location')} but the target is in {target.get('location')}; they must be in the same region.")
    storage_id = props.get("storageId") or ((existing or {}).get("properties") or {}).get("storageId")
    if not storage_id:
        return _err(400, "FlowLogStorageIdRequired", "properties.storageId is required (a storage account id).")
    st = state.get(str(storage_id).lower())
    if st is None or (st.get("_type") or "").lower() != "microsoft.storage/storageaccounts":
        return _err(400, "FlowLogStorageNotFound", f"Storage account {storage_id} was not found.")
    rp = props.get("retentionPolicy")
    if rp is not None:
        d = rp.get("days", 0)
        if not isinstance(d, int) or d < 0 or d > 365:
            return _err(400, "FlowLogRetentionOutOfRange", "retentionPolicy.days must be between 0 and 365.")
    fmt = props.get("format")
    if fmt is not None:
        if fmt.get("type", "JSON") != "JSON":
            return _err(400, "FlowLogFormatInvalid", "format.type must be JSON.")
        if fmt.get("version", 1) not in FLOWLOG_VERSIONS:
            return _err(400, "FlowLogVersionInvalid", "format.version must be 1 or 2.")
    fa = props.get("flowAnalyticsConfiguration")
    if fa:
        na = fa.get("networkWatcherFlowAnalyticsConfiguration") or {}
        if na.get("enabled"):
            ws = str(na.get("workspaceResourceId") or "")
            wrec = state.get(ws.lower())
            if wrec is None or "operationalinsights/workspaces" not in (wrec.get("_type") or "").lower():
                return _err(400, "FlowLogAnalyticsWorkspaceNotFound", "Traffic Analytics needs an existing Log Analytics workspace (workspaceResourceId).")
            if na.get("trafficAnalyticsInterval") not in (None, 10, 60):
                return _err(400, "FlowLogTrafficAnalyticsIntervalInvalid", "trafficAnalyticsInterval must be 10 or 60 minutes.")
    for sib in state.values():
        if sib.get("_type", "").lower() == FLOWLOG and sib.get("id", "").lower() != rid.lower():
            if str((sib.get("properties") or {}).get("targetResourceId") or "").lower() == str(target_id).lower() and sib.get("id", "").lower().startswith(nw_id.lower() + "/"):
                return _err(409, "FlowLogAlreadyExistsForTarget", f"A flow log already exists for target {target_id} on this network watcher.")
    return None


def _validate_pec_put(state, rid, props):
    st = ((props.get("privateLinkServiceConnectionState") or {}).get("status"))
    if st not in ("Approved", "Rejected", "Pending", "Disconnected"):
        return _err(400, "InvalidPrivateEndpointConnectionState", "privateLinkServiceConnectionState.status must be Approved, Rejected, Pending or Disconnected.")
    return None


# ── post-write derivation ──────────────────────────────────────────────────────────────
def after_put(state: dict, rec: dict, payload: dict, prev: dict | None = None) -> None:
    ft = (rec.get("_type") or "").lower()
    if ft == PE:
        _derive_pe(state, rec)
    elif ft == BASTION:
        _derive_bastion(rec)
    elif ft == FIREWALL:
        _derive_firewall(state, rec)
    elif ft == DDOS:
        _derive_ddos(state, rec)
    elif ft == VNET:
        _sync_ddos_attachments(state)
    elif ft == FLOWLOG:
        _derive_flowlog(rec)
    elif ft.endswith(PEC_SUFFIX):
        if prev:                                   # a PUT rebuilds the record: keep the endpoint linkage
            for k in ("_pe_id", "_pe_conn"):
                rec[k] = prev.get(k)
            rec["properties"].setdefault("groupIds", (prev.get("properties") or {}).get("groupIds") or [])
            rec["properties"].setdefault("privateEndpoint", (prev.get("properties") or {}).get("privateEndpoint"))
        _pec_to_endpoint(state, rec)


def _derive_pe(state, rec):
    props = rec["properties"]
    sid = _ref(props.get("subnet"))
    sn, _v = _subnet(state, sid)
    auto = list(props.get("privateLinkServiceConnections") or [])
    manual = list(props.get("manualPrivateLinkServiceConnections") or [])
    old_ip = None
    for c in rec.get("_nic_cfg") or []:
        old_ip = c
    ip = old_ip or (alloc_ip(state, sn["prefix"]) if sn and sn["prefix"] else None)
    rec["_nic_cfg"] = [ip] if ip else []
    nic_id = f"{rec['id']}/networkInterfaces/{rec['name']}.nic.{(rec.get('_sub') or '0')[:8]}"
    props["networkInterfaces"] = [{"id": nic_id}]
    props["customNetworkInterfaceName"] = props.get("customNetworkInterfaceName") or f"{rec['name']}-nic"
    props["resourceGuid"] = props.get("resourceGuid") or str(uuid.uuid4())
    dns = []
    for lst, is_manual in ((auto, False), (manual, True)):
        for c in lst:
            cp = c.setdefault("properties", {})
            target = str(cp.get("privateLinkServiceId"))
            ttype = _type_of(target)
            conn_id = f"{target}{PEC_SUFFIX}/{rec['name']}.{_guid_for(rec['id'], c.get('name'))}"
            existing = state.get(conn_id.lower())
            status = (((existing or {}).get("properties") or {}).get("privateLinkServiceConnectionState") or {}).get("status")
            if status is None:
                status = "Pending" if is_manual else "Approved"
            msg = (((existing or {}).get("properties") or {}).get("privateLinkServiceConnectionState") or {}).get("description") or cp.get("requestMessage") or ("" if not is_manual else "Please approve my connection")
            cp["privateLinkServiceConnectionState"] = {"status": status, "description": msg, "actionsRequired": "None"}
            cp["provisioningState"] = "Succeeded"
            c["id"] = f"{rec['id']}/{'manualPrivateLinkServiceConnections' if is_manual else 'privateLinkServiceConnections'}/{c.get('name')}"
            c["type"] = "Microsoft.Network/privateEndpoints/" + ("manualPrivateLinkServiceConnections" if is_manual else "privateLinkServiceConnections")
            if ttype in OWN_ENGINE_PEC:
                continue
            trec = state.get(target.lower())
            state[conn_id.lower()] = {
                "id": conn_id, "name": f"{rec['name']}.{_guid_for(rec['id'], c.get('name'))}",
                "type": (trec or {}).get("type", "") + "/privateEndpointConnections",
                "_type": ttype + PEC_SUFFIX, "_sub": rec.get("_sub"), "_rg": (trec or {}).get("_rg"),
                "_created": (existing or {}).get("_created") or _now(),
                "_pe_id": rec["id"], "_pe_conn": c.get("name"),
                "properties": {"provisioningState": "Succeeded", "groupIds": cp.get("groupIds") or [],
                               "privateEndpoint": {"id": rec["id"]},
                               "privateLinkServiceConnectionState": dict(cp["privateLinkServiceConnectionState"])},
            }
            _sync_target_list(state, trec)
            zone_map = PRIVATE_LINK.get(ttype) or {}
            for g in cp.get("groupIds") or []:
                zone = zone_map.get(str(g).lower())
                if zone and ip:
                    dns.append({"fqdn": f"{(trec or {}).get('name', '')}.{zone}", "ipAddresses": [ip]})
    props["customDnsConfigs"] = dns
    props["ipConfigurations"] = props.get("ipConfigurations") or []
    rec["_private_ip"] = ip      # real ARM keeps the private IP on the endpoint's NIC, not the endpoint


def _pec_target(pec_id: str) -> str:
    i = pec_id.lower().rfind(PEC_SUFFIX)
    return pec_id[:i] if i >= 0 else pec_id


def _guid_for(pe_id: str, conn_name) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{pe_id.lower()}|{conn_name}"))


def _sync_target_list(state, trec):
    if trec is None:
        return
    prefix = trec["id"].lower() + PEC_SUFFIX + "/"
    conns = [{k: v for k, v in r.items() if not k.startswith("_")} for r in state.values()
             if isinstance(r, dict) and r.get("id", "").lower().startswith(prefix)
             and "/" not in r["id"][len(prefix):] and r.get("_pe_id")]
    trec.setdefault("properties", {})["privateEndpointConnections"] = conns
    pna = trec["properties"].get("publicNetworkAccess")
    if pna is None:
        trec["properties"]["publicNetworkAccess"] = "Enabled"


def _pec_to_endpoint(state, rec):
    """Approve / reject on the target side flows back to the private endpoint."""
    pe = state.get(str(rec.get("_pe_id") or "").lower())
    if pe is None:
        # connection created directly on a target (no endpoint behind it): keep as provided
        rec["properties"].setdefault("provisioningState", "Succeeded")
        return
    st = rec["properties"].get("privateLinkServiceConnectionState") or {}
    for key in ("privateLinkServiceConnections", "manualPrivateLinkServiceConnections"):
        for c in pe["properties"].get(key) or []:
            if c.get("name") == rec.get("_pe_conn"):
                c["properties"]["privateLinkServiceConnectionState"] = {"status": st.get("status"), "description": st.get("description", ""), "actionsRequired": "None"}
    target = _pec_target(rec["id"])
    _sync_target_list(state, state.get(target.lower()))


def _derive_bastion(rec):
    p = rec["properties"]
    sku = (rec.get("sku") or {}).get("name") or "Standard"
    rec["sku"] = {"name": sku}
    p.setdefault("dnsName", f"bst-{uuid.uuid5(uuid.NAMESPACE_URL, rec['id'].lower())}.bastion.azure.com")
    if sku == "Basic":
        p["scaleUnits"] = 2
    elif sku in ("Standard", "Premium"):
        p.setdefault("scaleUnits", 2)
    for i, c in enumerate(p.get("ipConfigurations") or []):
        c.setdefault("name", f"IpConf{i}")
        c["id"] = f"{rec['id']}/bastionHostIpConfigurations/{c['name']}"
        c.setdefault("properties", {})["provisioningState"] = "Succeeded"
    for f, d in (("enableTunneling", False), ("enableIpConnect", False), ("enableShareableLink", False),
                 ("enableFileCopy", False), ("disableCopyPaste", False), ("enableKerberos", False)):
        p.setdefault(f, d)


def _derive_firewall(state, rec):
    p = rec["properties"]
    p["sku"] = {"name": (p.get("sku") or {}).get("name") or "AZFW_VNet", "tier": (p.get("sku") or {}).get("tier") or "Standard"}
    p.setdefault("threatIntelMode", "Alert")
    p.setdefault("additionalProperties", {})
    for i, c in enumerate(p.get("ipConfigurations") or []):
        c.setdefault("name", f"ipconfig{i}")
        c["id"] = f"{rec['id']}/azureFirewallIpConfigurations/{c['name']}"
        cp = c.setdefault("properties", {})
        cp["provisioningState"] = "Succeeded"
        if not cp.get("privateIPAddress"):
            sn, _v = _subnet(state, _ref(cp.get("subnet")))
            cp["privateIPAddress"] = rec.get("_fw_ip") or (alloc_ip(state, sn["prefix"]) if sn and sn["prefix"] else None)
        rec["_fw_ip"] = cp["privateIPAddress"]
        pip = state.get(_ref(cp.get("publicIPAddress")).lower())
        if pip is not None:
            pip.setdefault("properties", {})["ipConfiguration"] = {"id": c["id"]}


def _derive_ddos(state, rec):
    rec["properties"].setdefault("resourceGuid", str(uuid.uuid4()))
    _sync_ddos_attachments(state)


def _sync_ddos_attachments(state):
    users: dict = {}
    for r in state.values():
        if isinstance(r, dict) and r.get("_type", "").lower() == VNET:
            p = r.get("properties") or {}
            pid = _ref(p.get("ddosProtectionPlan"))
            if pid and p.get("enableDdosProtection", True):
                users.setdefault(pid.lower(), []).append({"id": r["id"]})
    for r in state.values():
        if isinstance(r, dict) and r.get("_type", "").lower() == DDOS:
            r.setdefault("properties", {})["virtualNetworks"] = users.get(r["id"].lower(), [])


def _derive_flowlog(rec):
    p = rec["properties"]
    p.setdefault("enabled", True)
    p.setdefault("retentionPolicy", {"days": 0, "enabled": False})
    p["retentionPolicy"].setdefault("enabled", bool(p["retentionPolicy"].get("days")))
    p.setdefault("format", {"type": "JSON", "version": 1})
    p["format"].setdefault("type", "JSON")
    p["format"].setdefault("version", 1)
    p["targetResourceGuid"] = p.get("targetResourceGuid") or str(uuid.uuid5(uuid.NAMESPACE_URL, str(p.get("targetResourceId")).lower()))
    rec["etag"] = f'W/"{uuid.uuid4()}"'


# ── delete rules / cascades ────────────────────────────────────────────────────────────
def before_delete(state: dict, rec: dict):
    ft = (rec.get("_type") or "").lower()
    if ft == DDOS:
        used = (rec.get("properties") or {}).get("virtualNetworks") or []
        if used:
            return _err(400, "InUseDdosProtectionPlanCannotBeDeleted", f"DDoS protection plan {rec['name']} is in use by {len(used)} virtual network(s); disable DDoS protection on them first.")
    if ft == POLICY:
        for r in state.values():
            if isinstance(r, dict):
                if r.get("_type", "").lower() == FIREWALL and _ref((r.get("properties") or {}).get("firewallPolicy")).lower() == rec["id"].lower():
                    return _err(409, "FirewallPolicyInUse", f"Firewall policy {rec['name']} is attached to firewall {r['name']}.")
                if r.get("_type", "").lower() == POLICY and _ref((r.get("properties") or {}).get("basePolicy")).lower() == rec["id"].lower():
                    return _err(409, "FirewallPolicyInUse", f"Firewall policy {rec['name']} is the base policy of {r['name']}.")
    if ft == "microsoft.network/publicipaddresses":
        for r in state.values():
            if isinstance(r, dict) and r.get("_type", "").lower() in (BASTION, FIREWALL):
                if rec["id"].lower() in repr(r.get("properties")).lower():
                    return _err(400, "PublicIPAddressInUse", f"Public IP address {rec['name']} is in use by {r['name']}.")
    if ft == VNET:
        for r in state.values():
            if isinstance(r, dict) and r.get("_type", "").lower() in (BASTION, FIREWALL, PE):
                if rec["id"].lower() + "/subnets/" in repr(r.get("properties")).lower():
                    return _err(400, "InUseSubnetCannotBeDeleted", f"Virtual network {rec['name']} is in use by {r['name']}.")
    return None


def on_delete(state: dict, rec: dict) -> None:
    ft = (rec.get("_type") or "").lower()
    rid = rec["id"].lower()
    if ft == PE:
        for k in [k for k, r in state.items() if isinstance(r, dict) and r.get("_pe_id", "").lower() == rid]:
            conn = state.pop(k)
            target = _pec_target(conn["id"])
            _sync_target_list(state, state.get(target.lower()))
    elif ft == POLICY:
        for k in [k for k in state if k.startswith(rid + "/rulecollectiongroups/")]:
            state.pop(k, None)
    elif ft.endswith(PEC_SUFFIX) and rec.get("_pe_id"):
        # deleting the target-side connection disconnects the endpoint
        pe = state.get(rec["_pe_id"].lower())
        if pe is not None:
            for key in ("privateLinkServiceConnections", "manualPrivateLinkServiceConnections"):
                for c in pe["properties"].get(key) or []:
                    if c.get("name") == rec.get("_pe_conn"):
                        c["properties"]["privateLinkServiceConnectionState"] = {"status": "Disconnected", "description": "Connection deleted on the target resource", "actionsRequired": "None"}
        _sync_target_list(state, state.get(_pec_target(rec["id"]).lower()))
    elif ft in (DDOS, VNET):
        _sync_ddos_attachments(state)
