"""Azure network configuration control plane, part 2 (Nano / dev_server / unified-ingress core, substrate-free).

Real ARM resources with real validation and cross-resource checks, stored in the flat ARM state map used by
``azure_arm_core`` (keyed by lower-cased resource id). Hooks mirror ``azure_netsvc_core`` (handles / validate /
after_put / before_delete / on_delete).

* ``Microsoft.Network/networkManagers`` + ``networkGroups`` (+ ``staticMembers``), ``connectivityConfigurations``,
  ``securityAdminConfigurations`` (+ ``ruleCollections`` / ``rules``) -- scope-access gating (a Connectivity config
  needs the manager to have the ``Connectivity`` scope access), target groups must exist in the same manager,
  hub-and-spoke needs an existing hub vnet, members must be existing vnets/subnets, rule priority 1..4096 and unique.
* ``Microsoft.Cdn/profiles`` (Azure Front Door Standard/Premium + classic CDN SKUs) with ``afdEndpoints``,
  ``originGroups`` (+ ``origins``), ``afdEndpoints/routes``, ``ruleSets`` (+ ``rules``), ``customDomains`` and classic
  ``endpoints`` -- sku-gated children, route -> origin group / rule set / custom domain cross references, origin
  priority/weight/port ranges, an in-use origin group or rule set cannot be deleted, endpoint host names derived.
* AKS ``networkProfile`` (plugin / plugin mode / policy / dataplane / CIDRs / outbound type / subnets) validated at create.
* Container Apps environment ``vnetConfiguration`` (infrastructure subnet exists and is large enough, internal needs a
  subnet, immutable once set).
* Virtual network ``advertisedAddressPrefixes`` / gateway route advertisement (validated CIDRs, must be a subset of the
  address space).

NOT modelled (honest limits, see core/capabilities/azure/*.json): Front Door/CDN control plane only -- no edge request
is ever served, no WAF/caching/TLS termination, custom-domain validation stays Pending; Network Manager configurations
are stored but there is no "deploy/commit" push that creates peerings or applies security rules to traffic; AKS /
Container Apps networking is validated configuration, packets are not routed through a CNI.
"""
from __future__ import annotations

import datetime
import hashlib
import ipaddress
import re
import uuid

NET = "microsoft.network"
NM = "microsoft.network/networkmanagers"
NM_GROUP = NM + "/networkgroups"
NM_MEMBER = NM_GROUP + "/staticmembers"
NM_CONN = NM + "/connectivityconfigurations"
NM_SEC = NM + "/securityadminconfigurations"
NM_COLL = NM_SEC + "/rulecollections"
NM_RULE = NM_COLL + "/rules"
VNET = "microsoft.network/virtualnetworks"
CDN = "microsoft.cdn/profiles"
AFD_EP = CDN + "/afdendpoints"
AFD_ROUTE = AFD_EP + "/routes"
AFD_OG = CDN + "/origingroups"
AFD_ORIGIN = AFD_OG + "/origins"
AFD_RS = CDN + "/rulesets"
AFD_RULE = AFD_RS + "/rules"
AFD_DOMAIN = CDN + "/customdomains"
CDN_EP = CDN + "/endpoints"
AKS = "microsoft.containerservice/managedclusters"

NM_ACCESS = ("Connectivity", "SecurityAdmin", "Routing")
AFD_SKUS = ("Standard_AzureFrontDoor", "Premium_AzureFrontDoor")
CDN_SKUS = ("Standard_Microsoft", "Standard_Verizon", "Premium_Verizon", "Standard_Akamai", "Standard_ChinaCdn", "Standard_955BandWidth_ChinaCdn",
            "Standard_AvgBandWidth_ChinaCdn", "StandardPlus_ChinaCdn", "StandardPlus_955BandWidth_ChinaCdn", "StandardPlus_AvgBandWidth_ChinaCdn",
            "Custom_Verizon", "Premium_ChinaCdn")
RULE_CONDITIONS = {"RemoteAddress", "RequestMethod", "QueryString", "PostArgs", "RequestUri", "RequestHeader", "RequestBody", "RequestScheme",
                   "UrlPath", "UrlFileExtension", "UrlFileName", "HttpVersion", "Cookies", "IsDevice", "SocketAddr", "ClientPort", "ServerPort",
                   "HostName", "SslProtocol"}
RULE_ACTIONS = {"CacheExpiration", "CacheKeyQueryString", "ModifyRequestHeader", "ModifyResponseHeader", "UrlRedirect", "UrlRewrite", "UrlSigning",
                "OriginGroupOverride", "RouteConfigurationOverride"}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status: int, code: str, message: str) -> dict:
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def _ref(obj) -> str:
    return str((obj or {}).get("id") or "") if isinstance(obj, dict) else ""


def _h(*parts, n=8) -> str:
    return hashlib.sha256("|".join(str(p).lower() for p in parts).encode()).hexdigest()[:n]


def _parent(rid: str, levels: int = 1) -> str:
    out = rid
    for _ in range(levels):
        out = out.rsplit("/", 2)[0]
    return out


def _cidr(v):
    try:
        return ipaddress.ip_network(str(v), strict=False)
    except ValueError:
        return None


def handles(full_type: str) -> bool:
    ft = full_type.lower()
    return (ft in (NM, NM_GROUP, NM_MEMBER, NM_CONN, NM_SEC, NM_COLL, NM_RULE, VNET, AKS) or ft == CDN or ft.startswith(CDN + "/"))


def _vnet_address_space(vnet: dict):
    return [n for n in (_cidr(p) for p in ((vnet.get("properties") or {}).get("addressSpace") or {}).get("addressPrefixes") or []) if n]


def _find_vnet(state, rid):
    r = state.get(str(rid).lower())
    return r if r is not None and (r.get("_type") or "").lower() == VNET else None


def _subnet_net(state, subnet_id):
    vid, _, name = str(subnet_id).lower().rpartition("/subnets/")
    v = state.get(vid)
    if v is None or (v.get("_type") or "").lower() != VNET:
        return None, None
    for s in (v.get("properties") or {}).get("subnets") or []:
        if str(s.get("name", "")).lower() == name:
            p = s.get("properties") or {}
            return _cidr(p.get("addressPrefix") or (p.get("addressPrefixes") or [""])[0]), v
    return None, v


# ── validation ─────────────────────────────────────────────────────────────────────────
def validate(state: dict, full_type: str, rid: str, payload: dict, existing: dict | None, sub: str, rg: str | None):
    ft = full_type.lower()
    props = (payload or {}).get("properties") or {}
    if ft == NM:
        return _v_nm(state, props, existing)
    if ft == NM_GROUP:
        return _v_group(state, rid, props)
    if ft == NM_MEMBER:
        return _v_member(state, rid, props)
    if ft == NM_CONN:
        return _v_conn(state, rid, props)
    if ft == NM_SEC:
        return _v_secadmin(state, rid, props)
    if ft == NM_COLL:
        return _v_coll(state, rid, props)
    if ft == NM_RULE:
        return _v_nmrule(state, rid, props)
    if ft == VNET:
        return _v_vnet_advertised(props)
    if ft == AKS:
        return _v_aks(state, rid, payload, props, existing)
    if ft == CDN or ft.startswith(CDN + "/"):
        return _v_cdn(state, ft, rid, payload, props, existing)
    return None


def _nm_of(state, rid, levels):
    nm = state.get(_parent(rid, levels).lower())
    return nm if nm is not None and (nm.get("_type") or "").lower() == NM else None


def _v_nm(state, props, existing):
    scopes = props.get("networkManagerScopes") or {}
    subs, mgs = scopes.get("subscriptions") or [], scopes.get("managementGroups") or []
    if not subs and not mgs:
        return _err(400, "NetworkManagerScopesRequired", "networkManagerScopes must list at least one subscription or management group.")
    for s in subs:
        if not re.match(r"^/subscriptions/[\w-]{8,64}$", str(s)):
            return _err(400, "InvalidNetworkManagerScope", f"Scope '{s}' is not a valid subscription id (/subscriptions/{{guid}}).")
    acc = props.get("networkManagerScopeAccesses") or []
    if not acc:
        return _err(400, "NetworkManagerScopeAccessesRequired", f"networkManagerScopeAccesses must contain at least one of {', '.join(NM_ACCESS)}.")
    for a in acc:
        if a not in NM_ACCESS:
            return _err(400, "InvalidNetworkManagerScopeAccess", f"Scope access '{a}' is not valid. Allowed: {', '.join(NM_ACCESS)}.")
    if existing is not None:
        old = set((existing.get("properties") or {}).get("networkManagerScopeAccesses") or [])
        dropped = old - set(acc)
        if dropped:
            for r in state.values():
                t = (r.get("_type") or "").lower() if isinstance(r, dict) else ""
                if r.get("id", "").lower().startswith(existing["id"].lower() + "/") if isinstance(r, dict) else False:
                    if ("Connectivity" in dropped and t == NM_CONN) or ("SecurityAdmin" in dropped and t == NM_SEC):
                        return _err(409, "NetworkManagerScopeAccessInUse", f"Scope access cannot be removed while {r['name']} ({t.rsplit('/', 1)[-1]}) exists.")
    return None


def _v_group(state, rid, props):
    if _nm_of(state, rid, 1) is None:
        return _err(404, "ParentResourceNotFound", "The network manager for this network group was not found.")
    mt = props.get("memberType")
    if mt is not None and mt not in ("VirtualNetwork", "Subnet"):
        return _err(400, "InvalidNetworkGroupMemberType", "memberType must be VirtualNetwork or Subnet.")
    return None


def _v_member(state, rid, props):
    grp = state.get(_parent(rid, 1).lower())
    if grp is None:
        return _err(404, "ParentResourceNotFound", "The network group for this static member was not found.")
    target = str(props.get("resourceId") or "")
    if not target:
        return _err(400, "StaticMemberResourceIdRequired", "properties.resourceId is required.")
    mt = (grp.get("properties") or {}).get("memberType") or "VirtualNetwork"
    if mt == "VirtualNetwork":
        if _find_vnet(state, target) is None:
            return _err(400, "InvalidStaticMember", f"Static member {target} must be an existing virtual network (the group's member type is VirtualNetwork).")
    else:
        n, _v = _subnet_net(state, target)
        if n is None:
            return _err(400, "InvalidStaticMember", f"Static member {target} must be an existing subnet (the group's member type is Subnet).")
    return None


def _groups_exist(state, nm, groups, label):
    for g in groups or []:
        gid = str(g.get("networkGroupId") or "")
        gr = state.get(gid.lower())
        if gr is None or (gr.get("_type") or "").lower() != NM_GROUP or not gr["id"].lower().startswith(nm["id"].lower() + "/networkgroups/"):
            return _err(400, "NetworkGroupNotFound", f"{label}: network group {gid or '(missing networkGroupId)'} does not exist in network manager {nm['name']}.")
    return None


def _v_conn(state, rid, props):
    nm = _nm_of(state, rid, 1)
    if nm is None:
        return _err(404, "ParentResourceNotFound", "The network manager for this connectivity configuration was not found.")
    if "Connectivity" not in (nm.get("properties") or {}).get("networkManagerScopeAccesses", []):
        return _err(400, "NetworkManagerScopeAccessMissing", f"Network manager {nm['name']} does not have the 'Connectivity' scope access.")
    topo = props.get("connectivityTopology")
    if topo not in ("HubAndSpoke", "Mesh"):
        return _err(400, "InvalidConnectivityTopology", "connectivityTopology must be HubAndSpoke or Mesh.")
    groups = props.get("appliesToGroups") or []
    if not groups:
        return _err(400, "AppliesToGroupsRequired", "appliesToGroups must contain at least one network group.")
    e = _groups_exist(state, nm, groups, "appliesToGroups")
    if e:
        return e
    for g in groups:
        if g.get("groupConnectivity", "None") not in ("None", "DirectlyConnected"):
            return _err(400, "InvalidGroupConnectivity", "groupConnectivity must be None or DirectlyConnected.")
        if topo == "Mesh" and g.get("useHubGateway") in ("True", True):
            return _err(400, "UseHubGatewayRequiresHub", "useHubGateway is only valid with a HubAndSpoke topology.")
    hubs = props.get("hubs") or []
    if topo == "HubAndSpoke":
        if len(hubs) != 1:
            return _err(400, "HubRequired", "A HubAndSpoke configuration needs exactly one hub (properties.hubs[0].resourceId).")
        if _find_vnet(state, hubs[0].get("resourceId") or "") is None:
            return _err(400, "InvalidHub", f"Hub {hubs[0].get('resourceId')} must be an existing virtual network.")
    elif hubs:
        return _err(400, "HubNotAllowed", "A Mesh configuration cannot specify hubs.")
    return None


def _v_secadmin(state, rid, props):
    nm = _nm_of(state, rid, 1)
    if nm is None:
        return _err(404, "ParentResourceNotFound", "The network manager for this security admin configuration was not found.")
    if "SecurityAdmin" not in (nm.get("properties") or {}).get("networkManagerScopeAccesses", []):
        return _err(400, "NetworkManagerScopeAccessMissing", f"Network manager {nm['name']} does not have the 'SecurityAdmin' scope access.")
    v = props.get("applyOnNetworkIntentPolicyBasedServices")
    if v is not None and not (isinstance(v, list) and all(x in ("None", "All", "AllowRulesOnly") for x in v)):
        return _err(400, "InvalidApplyOnNetworkIntentPolicyBasedServices", "applyOnNetworkIntentPolicyBasedServices entries must be None, All or AllowRulesOnly.")
    return None


def _v_coll(state, rid, props):
    cfg = state.get(_parent(rid, 1).lower())
    if cfg is None:
        return _err(404, "ParentResourceNotFound", "The security admin configuration for this rule collection was not found.")
    nm = _nm_of(state, cfg["id"], 1)
    groups = props.get("appliesToGroups") or []
    if not groups:
        return _err(400, "AppliesToGroupsRequired", "A rule collection must apply to at least one network group.")
    return _groups_exist(state, nm, groups, "appliesToGroups") if nm else None


def _v_nmrule(state, rid, props):
    coll = state.get(_parent(rid, 1).lower())
    if coll is None:
        return _err(404, "ParentResourceNotFound", "The rule collection for this rule was not found.")
    if props.get("kind", "Custom") not in ("Custom", "Default") and False:
        return None
    pr = props.get("priority")
    if not isinstance(pr, int) or pr < 1 or pr > 4096:
        return _err(400, "InvalidSecurityAdminRulePriority", "priority must be an integer between 1 and 4096.")
    if props.get("access") not in ("Allow", "Deny", "AlwaysAllow"):
        return _err(400, "InvalidSecurityAdminRuleAccess", "access must be Allow, Deny or AlwaysAllow.")
    if props.get("direction") not in ("Inbound", "Outbound"):
        return _err(400, "InvalidSecurityAdminRuleDirection", "direction must be Inbound or Outbound.")
    if props.get("protocol") not in ("Tcp", "Udp", "Icmp", "Esp", "Any", "Ah"):
        return _err(400, "InvalidSecurityAdminRuleProtocol", "protocol must be Tcp, Udp, Icmp, Esp, Ah or Any.")
    for key in ("sourcePortRanges", "destinationPortRanges"):
        for pr_ in props.get(key) or []:
            m = re.match(r"^(\*|\d{1,5}(-\d{1,5})?)$", str(pr_))
            if not m or any(int(x) > 65535 for x in re.findall(r"\d+", str(pr_))):
                return _err(400, "InvalidSecurityAdminRulePortRange", f"{key} entry '{pr_}' is not a port, a port range or '*'.")
    for key in ("sources", "destinations"):
        for a in props.get(key) or []:
            if a.get("addressPrefixType") not in ("IPPrefix", "ServiceTag"):
                return _err(400, "InvalidAddressPrefixType", f"{key}[].addressPrefixType must be IPPrefix or ServiceTag.")
            if a["addressPrefixType"] == "IPPrefix" and a.get("addressPrefix") != "*" and _cidr(a.get("addressPrefix")) is None:
                return _err(400, "InvalidAddressPrefix", f"{key}[].addressPrefix '{a.get('addressPrefix')}' is not a valid CIDR.")
    prefix = coll["id"].lower() + "/rules/"
    for r in state.values():
        if isinstance(r, dict) and r.get("id", "").lower().startswith(prefix) and r["id"].lower() != rid.lower():
            if (r.get("properties") or {}).get("priority") == pr and (r.get("properties") or {}).get("direction") == props.get("direction"):
                return _err(400, "SecurityAdminRulePriorityConflict", f"Priority {pr} is already used by rule {r['name']} for {props.get('direction')} traffic in this collection.")
    return None


def _v_vnet_advertised(props):
    adv = props.get("advertisedAddressPrefixes")
    if adv is None:
        return None
    space = [n for n in (_cidr(p) for p in (props.get("addressSpace") or {}).get("addressPrefixes") or []) if n]
    if not isinstance(adv, list):
        return _err(400, "InvalidAdvertisedAddressPrefixes", "advertisedAddressPrefixes must be a list of CIDR prefixes.")
    seen = set()
    for a in adv:
        n = _cidr(a)
        if n is None or "/" not in str(a):
            return _err(400, "InvalidAdvertisedAddressPrefix", f"Advertised prefix '{a}' is not a valid CIDR.")
        if space and not any(n.subnet_of(s) for s in space if s.version == n.version):
            return _err(400, "AdvertisedPrefixOutsideAddressSpace", f"Advertised prefix {a} must be within the virtual network address space.")
        if str(n) in seen:
            return _err(400, "DuplicateAdvertisedAddressPrefix", f"Advertised prefix {a} is listed twice.")
        seen.add(str(n))
    return None


def _v_aks(state, rid, payload, props, existing):
    np = props.get("networkProfile")
    pools = props.get("agentPoolProfiles") or []
    if np is None:
        return None
    plugin = (np.get("networkPlugin") or "kubenet")
    if plugin not in ("azure", "kubenet", "none"):
        return _err(400, "InvalidNetworkPlugin", "networkPlugin must be azure, kubenet or none.")
    mode = np.get("networkPluginMode")
    if mode not in (None, "overlay"):
        return _err(400, "InvalidNetworkPluginMode", "networkPluginMode must be 'overlay'.")
    if mode and plugin != "azure":
        return _err(400, "NetworkPluginModeRequiresAzure", "networkPluginMode 'overlay' requires networkPlugin 'azure'.")
    pol = np.get("networkPolicy")
    if pol not in (None, "azure", "calico", "cilium", "none"):
        return _err(400, "InvalidNetworkPolicy", "networkPolicy must be azure, calico, cilium or none.")
    if pol == "azure" and plugin != "azure":
        return _err(400, "NetworkPolicyIncompatible", "networkPolicy 'azure' requires networkPlugin 'azure'.")
    if pol == "calico" and plugin == "none":
        return _err(400, "NetworkPolicyIncompatible", "networkPolicy 'calico' requires networkPlugin azure or kubenet.")
    dp = np.get("networkDataplane")
    if dp not in (None, "azure", "cilium"):
        return _err(400, "InvalidNetworkDataplane", "networkDataplane must be azure or cilium.")
    pool_pod_subnet = any(p.get("podSubnetID") or p.get("podSubnetId") for p in pools)
    if dp == "cilium" or pol == "cilium":
        if plugin != "azure" or not (mode == "overlay" or pool_pod_subnet):
            return _err(400, "CiliumRequiresAzureCNI", "Cilium requires networkPlugin 'azure' with overlay mode or a dedicated pod subnet.")
        if pol == "cilium" and dp != "cilium":
            return _err(400, "CiliumPolicyRequiresCiliumDataplane", "networkPolicy 'cilium' requires networkDataplane 'cilium'.")
    if dp == "cilium" and pol not in (None, "cilium"):
        return _err(400, "NetworkPolicyIncompatible", "With networkDataplane 'cilium' the only supported networkPolicy is 'cilium'.")
    svc = _cidr(np["serviceCidr"]) if np.get("serviceCidr") else None
    if np.get("serviceCidr") and svc is None:
        return _err(400, "InvalidServiceCidr", f"serviceCidr '{np['serviceCidr']}' is not a valid CIDR.")
    if svc is not None and svc.prefixlen > 24:
        return _err(400, "InvalidServiceCidr", "serviceCidr must be /24 or larger.")
    pod = _cidr(np["podCidr"]) if np.get("podCidr") else None
    if np.get("podCidr"):
        if pod is None:
            return _err(400, "InvalidPodCidr", f"podCidr '{np['podCidr']}' is not a valid CIDR.")
        if plugin == "azure" and not mode:
            return _err(400, "PodCidrNotAllowed", "podCidr cannot be set for Azure CNI without overlay mode; pods take IPs from the VNet subnet.")
        if pod.prefixlen > 24:
            return _err(400, "InvalidPodCidr", "podCidr must be /24 or larger.")
    if np.get("dnsServiceIP"):
        try:
            ip = ipaddress.ip_address(np["dnsServiceIP"])
        except ValueError:
            return _err(400, "InvalidDnsServiceIP", f"dnsServiceIP '{np['dnsServiceIP']}' is not a valid IP address.")
        if svc is not None:
            if ip not in svc:
                return _err(400, "DnsServiceIPNotInServiceCidr", f"dnsServiceIP {ip} must be within serviceCidr {svc}.")
            if int(ip) - int(svc.network_address) < 2:
                return _err(400, "InvalidDnsServiceIP", "dnsServiceIP cannot be the network or the Kubernetes API service address (first two addresses of serviceCidr).")
    elif svc is not None and plugin != "none":
        pass
    if svc is not None and pod is not None and svc.overlaps(pod):
        return _err(400, "PodCidrOverlapsServiceCidr", f"podCidr {pod} overlaps serviceCidr {svc}.")
    ob = np.get("outboundType") or "loadBalancer"
    if ob not in ("loadBalancer", "userDefinedRouting", "managedNATGateway", "userAssignedNATGateway"):
        return _err(400, "InvalidOutboundType", "outboundType must be loadBalancer, userDefinedRouting, managedNATGateway or userAssignedNATGateway.")
    if np.get("loadBalancerSku") not in (None, "standard", "basic", "Standard", "Basic"):
        return _err(400, "InvalidLoadBalancerSku", "loadBalancerSku must be standard or basic.")
    subnets = []
    for p in pools:
        sid = p.get("vnetSubnetID") or p.get("vnetSubnetId")
        psid = p.get("podSubnetID") or p.get("podSubnetId")
        for label, v in (("vnetSubnetID", sid), ("podSubnetID", psid)):
            if v:
                n, vn = _subnet_net(state, v)
                if vn is None or n is None:
                    return _err(400, "SubnetNotFound", f"agentPoolProfiles[{p.get('name')}].{label}: subnet {v} was not found.")
                if label == "vnetSubnetID":
                    subnets.append(n)
        if psid and plugin != "azure":
            return _err(400, "PodSubnetRequiresAzureCNI", "podSubnetID requires networkPlugin 'azure'.")
        if psid and mode:
            return _err(400, "PodSubnetIncompatibleWithOverlay", "podSubnetID cannot be combined with networkPluginMode 'overlay'.")
    if ob == "userDefinedRouting" and pools and not any(p.get("vnetSubnetID") or p.get("vnetSubnetId") for p in pools):
        return _err(400, "UserDefinedRoutingRequiresSubnet", "outboundType 'userDefinedRouting' requires a custom virtual network (agentPoolProfiles[].vnetSubnetID).")
    if ob == "userAssignedNATGateway" and not subnets:
        return _err(400, "NatGatewayRequiresSubnet", "outboundType 'userAssignedNATGateway' requires a custom virtual network subnet with a NAT gateway.")
    if plugin == "azure" and not mode:
        for n in subnets:
            if n.prefixlen > 26 - 0:
                return _err(400, "SubnetTooSmall", f"Subnet {n} is too small for Azure CNI nodes and pods.")
    for n in subnets:
        if svc is not None and svc.overlaps(n):
            return _err(400, "ServiceCidrOverlapsSubnet", f"serviceCidr {svc} overlaps the node subnet {n}.")
        if pod is not None and pod.overlaps(n):
            return _err(400, "PodCidrOverlapsSubnet", f"podCidr {pod} overlaps the node subnet {n}.")
    api = props.get("apiServerAccessProfile") or {}
    for r in api.get("authorizedIPRanges") or []:
        if _cidr(r) is None:
            return _err(400, "InvalidAuthorizedIPRange", f"authorizedIPRanges entry '{r}' is not a valid CIDR.")
    if api.get("enablePrivateCluster") and api.get("authorizedIPRanges"):
        return _err(400, "AuthorizedIPRangesNotSupportedOnPrivateCluster", "authorizedIPRanges cannot be set on a private cluster.")
    if existing is not None:
        old = (existing.get("properties") or {}).get("networkProfile") or {}
        for k in ("networkPlugin", "serviceCidr"):
            if old.get(k) and np.get(k) and old[k] != np[k]:
                return _err(400, "PropertyChangeNotAllowed", f"networkProfile.{k} cannot be changed after the cluster is created.")
    return None


# ── Front Door / CDN ───────────────────────────────────────────────────────────────────
def _profile_of(state, rid, chain_len):
    """Profile record for a nested CDN id (chain_len = number of /type/name pairs below the profile)."""
    pid = _parent(rid, chain_len)
    p = state.get(pid.lower())
    return p if p is not None and (p.get("_type") or "").lower() == CDN else None


def _is_afd(profile) -> bool:
    return ((profile.get("sku") or {}).get("name") or "") in AFD_SKUS


def _v_cdn(state, ft, rid, payload, props, existing):
    if ft == CDN:
        sku = (payload.get("sku") or {}).get("name")
        if not sku:
            return _err(400, "SkuRequired", "sku.name is required (e.g. Standard_AzureFrontDoor, Premium_AzureFrontDoor, Standard_Microsoft).")
        if sku not in AFD_SKUS + CDN_SKUS:
            return _err(400, "InvalidSku", f"SKU '{sku}' is not valid for Microsoft.Cdn/profiles.")
        if existing is not None and (existing.get("sku") or {}).get("name") != sku:
            old = (existing.get("sku") or {}).get("name")
            if (old in AFD_SKUS) != (sku in AFD_SKUS):
                return _err(400, "SkuChangeNotAllowed", "A profile cannot move between Azure Front Door and classic CDN SKUs.")
            if old == "Premium_AzureFrontDoor" and sku == "Standard_AzureFrontDoor":
                return _err(400, "SkuDowngradeNotAllowed", "Premium_AzureFrontDoor cannot be downgraded to Standard_AzureFrontDoor.")
        if _afd_loc(payload) is False and sku in AFD_SKUS:
            return _err(400, "InvalidLocation", "Azure Front Door profiles must be created in location 'global'.")
        return None
    profile = _profile_of(state, rid, len([p for p in ft.split("/")[2:]]))
    if profile is None:
        return _err(404, "ParentResourceNotFound", "The Microsoft.Cdn profile for this resource was not found.")
    afd = _is_afd(profile)
    child0 = ft.split("/")[2]
    if child0 in ("afdendpoints", "origingroups", "rulesets", "customdomains") and not afd:
        return _err(400, "OperationNotSupportedForSku", f"'{ft.split('/')[2]}' requires an Azure Front Door profile (Standard_AzureFrontDoor or Premium_AzureFrontDoor).")
    if child0 == "endpoints" and afd:
        return _err(400, "OperationNotSupportedForSku", "Classic CDN endpoints are not available on Azure Front Door profiles; use afdEndpoints.")
    name = rid.rsplit("/", 1)[-1]
    if ft in (AFD_EP, CDN_EP):
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9-]{0,48}[A-Za-z0-9]$|^[A-Za-z0-9]$", name):
            return _err(400, "InvalidEndpointName", "Endpoint names are 1-50 characters, letters/numbers/hyphens, not starting or ending with a hyphen.")
        es = props.get("enabledState")
        if es not in (None, "Enabled", "Disabled"):
            return _err(400, "InvalidEnabledState", "enabledState must be Enabled or Disabled.")
        if ft == CDN_EP and not (props.get("origins") or (existing or {}).get("properties", {}).get("origins")):
            return _err(400, "OriginsRequired", "A CDN endpoint requires at least one origin (properties.origins[].properties.hostName).")
        return None
    if ft == AFD_OG:
        hp = props.get("healthProbeSettings")
        if hp:
            if hp.get("probeProtocol") not in (None, "Http", "Https", "NotSet"):
                return _err(400, "InvalidProbeProtocol", "probeProtocol must be Http, Https or NotSet.")
            if hp.get("probeRequestType") not in (None, "GET", "HEAD", "NotSet"):
                return _err(400, "InvalidProbeRequestType", "probeRequestType must be GET, HEAD or NotSet.")
            if hp.get("probePath") and not str(hp["probePath"]).startswith("/"):
                return _err(400, "InvalidProbePath", "probePath must start with '/'.")
            iv = hp.get("probeIntervalInSeconds")
            if iv is not None and (not isinstance(iv, int) or iv < 1 or iv > 255):
                return _err(400, "InvalidProbeInterval", "probeIntervalInSeconds must be between 1 and 255.")
        lb = props.get("loadBalancingSettings")
        if lb:
            ss, ok = lb.get("sampleSize", 4), lb.get("successfulSamplesRequired", 3)
            if not isinstance(ss, int) or ss < 0 or ss > 255 or not isinstance(ok, int) or ok < 0 or ok > 255:
                return _err(400, "InvalidLoadBalancingSettings", "sampleSize and successfulSamplesRequired must be integers between 0 and 255.")
            if ok > ss:
                return _err(400, "InvalidLoadBalancingSettings", "successfulSamplesRequired cannot be greater than sampleSize.")
            if lb.get("additionalLatencyInMilliseconds", 0) not in range(0, 1001):
                return _err(400, "InvalidLoadBalancingSettings", "additionalLatencyInMilliseconds must be between 0 and 1000.")
        return None
    if ft == AFD_ORIGIN:
        host = str(props.get("hostName") or "")
        if not host:
            return _err(400, "OriginHostNameRequired", "properties.hostName is required.")
        if not re.match(r"^([A-Za-z0-9-]+\.)*[A-Za-z0-9-]+$", host) and _cidr(host) is None:
            return _err(400, "InvalidOriginHostName", f"Origin host name '{host}' is not a valid host name or IP address.")
        for k, d in (("httpPort", 80), ("httpsPort", 443)):
            v = props.get(k, d)
            if not isinstance(v, int) or v < 1 or v > 65535:
                return _err(400, "InvalidOriginPort", f"{k} must be between 1 and 65535.")
        pr = props.get("priority", 1)
        if not isinstance(pr, int) or pr < 1 or pr > 5:
            return _err(400, "InvalidOriginPriority", "priority must be between 1 and 5.")
        w = props.get("weight", 1000)
        if not isinstance(w, int) or w < 1 or w > 1000:
            return _err(400, "InvalidOriginWeight", "weight must be between 1 and 1000.")
        sl = props.get("sharedPrivateLinkResource")
        if sl:
            if profile["sku"]["name"] != "Premium_AzureFrontDoor":
                return _err(400, "PrivateLinkRequiresPremium", "Private Link origins require the Premium_AzureFrontDoor SKU.")
            if not sl.get("privateLink", {}).get("id") or not sl.get("groupId"):
                return _err(400, "InvalidSharedPrivateLinkResource", "sharedPrivateLinkResource needs privateLink.id and groupId.")
        return None
    if ft == AFD_DOMAIN:
        host = str(props.get("hostName") or "")
        if not re.match(r"^([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}$", host):
            return _err(400, "InvalidCustomDomainHostName", f"hostName '{host}' is not a valid domain name.")
        tls = props.get("tlsSettings") or {}
        if tls.get("certificateType") not in (None, "ManagedCertificate", "CustomerCertificate"):
            return _err(400, "InvalidCertificateType", "tlsSettings.certificateType must be ManagedCertificate or CustomerCertificate.")
        if tls.get("minimumTlsVersion") not in (None, "TLS10", "TLS12"):
            return _err(400, "InvalidMinimumTlsVersion", "tlsSettings.minimumTlsVersion must be TLS10 or TLS12.")
        if tls.get("certificateType") == "CustomerCertificate" and not _ref(tls.get("secret")):
            return _err(400, "CustomerCertificateSecretRequired", "A CustomerCertificate requires tlsSettings.secret.id.")
        prefix = profile["id"].lower() + "/customdomains/"
        for r in state.values():
            if isinstance(r, dict) and r.get("id", "").lower().startswith(prefix) and r["id"].lower() != rid.lower():
                if str((r.get("properties") or {}).get("hostName", "")).lower() == host.lower():
                    return _err(409, "CustomDomainAlreadyExists", f"Custom domain host name {host} already exists in profile {profile['name']}.")
        return None
    if ft == AFD_RS:
        if not re.match(r"^[A-Za-z][A-Za-z0-9]{0,59}$", name):
            return _err(400, "InvalidRuleSetName", "Rule set names are 1-60 alphanumeric characters starting with a letter.")
        return None
    if ft == AFD_RULE:
        rs = state.get(_parent(rid, 1).lower())
        if rs is None:
            return _err(404, "ParentResourceNotFound", "The rule set for this rule was not found.")
        if not re.match(r"^[A-Za-z][A-Za-z0-9]{0,259}$", name):
            return _err(400, "InvalidRuleName", "Rule names are alphanumeric and start with a letter.")
        order = props.get("order")
        if not isinstance(order, int) or order < 0:
            return _err(400, "InvalidRuleOrder", "order must be a non-negative integer.")
        for c in props.get("conditions") or []:
            if c.get("name") not in RULE_CONDITIONS:
                return _err(400, "InvalidRuleCondition", f"Condition '{c.get('name')}' is not valid. Allowed: {', '.join(sorted(RULE_CONDITIONS))}.")
        actions = props.get("actions") or []
        if not actions:
            return _err(400, "RuleActionRequired", "A rule needs at least one action.")
        for a in actions:
            if a.get("name") not in RULE_ACTIONS:
                return _err(400, "InvalidRuleAction", f"Action '{a.get('name')}' is not valid. Allowed: {', '.join(sorted(RULE_ACTIONS))}.")
            if a["name"] == "OriginGroupOverride":
                og = _ref(((a.get("parameters") or {}).get("originGroup")))
                if not og or state.get(og.lower()) is None:
                    return _err(400, "OriginGroupNotFound", f"OriginGroupOverride references origin group {og or '(missing)'} which does not exist.")
        prefix = rs["id"].lower() + "/rules/"
        for r in state.values():
            if isinstance(r, dict) and r.get("id", "").lower().startswith(prefix) and r["id"].lower() != rid.lower():
                if (r.get("properties") or {}).get("order") == order:
                    return _err(409, "RuleOrderConflict", f"Rule {r['name']} already uses order {order} in rule set {rs['name']}.")
        return None
    if ft == AFD_ROUTE:
        ep = state.get(_parent(rid, 1).lower())
        if ep is None:
            return _err(404, "ParentResourceNotFound", "The Front Door endpoint for this route was not found.")
        ogid = _ref(props.get("originGroup"))
        og = state.get(ogid.lower()) if ogid else None
        if og is None or (og.get("_type") or "").lower() != AFD_OG or not og["id"].lower().startswith(profile["id"].lower() + "/origingroups/"):
            return _err(400, "OriginGroupNotFound", f"Route origin group {ogid or '(originGroup.id missing)'} does not exist in profile {profile['name']}.")
        origins = [r for r in state.values() if isinstance(r, dict) and r.get("id", "").lower().startswith(og["id"].lower() + "/origins/")]
        if not origins:
            return _err(400, "OriginGroupHasNoOrigins", f"Origin group {og['name']} has no origins; add at least one origin before routing to it.")
        protos = props.get("supportedProtocols") or ["Http", "Https"]
        if not protos or any(p not in ("Http", "Https") for p in protos):
            return _err(400, "InvalidSupportedProtocols", "supportedProtocols entries must be Http or Https.")
        pats = props.get("patternsToMatch") or ["/*"]
        for pt in pats:
            if not str(pt).startswith("/"):
                return _err(400, "InvalidPatternToMatch", f"patternsToMatch entry '{pt}' must start with '/'.")
        fp = props.get("forwardingProtocol")
        if fp not in (None, "HttpOnly", "HttpsOnly", "MatchRequest"):
            return _err(400, "InvalidForwardingProtocol", "forwardingProtocol must be HttpOnly, HttpsOnly or MatchRequest.")
        if props.get("httpsRedirect") not in (None, "Enabled", "Disabled"):
            return _err(400, "InvalidHttpsRedirect", "httpsRedirect must be Enabled or Disabled.")
        if props.get("httpsRedirect") == "Enabled" and "Https" not in protos:
            return _err(400, "HttpsRedirectRequiresHttps", "httpsRedirect cannot be Enabled when Https is not a supported protocol.")
        for ref_key, t in (("customDomains", AFD_DOMAIN), ("ruleSets", AFD_RS)):
            for r in props.get(ref_key) or []:
                rec = state.get(_ref(r).lower())
                if rec is None or (rec.get("_type") or "").lower() != t or not rec["id"].lower().startswith(profile["id"].lower() + "/"):
                    return _err(400, "ReferencedResourceNotFound", f"{ref_key} entry {_ref(r)} does not exist in profile {profile['name']}.")
        if props.get("customDomains") and props.get("linkToDefaultDomain") not in (None, "Enabled", "Disabled"):
            return _err(400, "InvalidLinkToDefaultDomain", "linkToDefaultDomain must be Enabled or Disabled.")
        # a pattern + domain pair can only be claimed by one route on an endpoint
        for r in state.values():
            if isinstance(r, dict) and r.get("id", "").lower().startswith(ep["id"].lower() + "/routes/") and r["id"].lower() != rid.lower():
                rp = r.get("properties") or {}
                if set(rp.get("patternsToMatch") or ["/*"]) & set(pats) and set(map(str.lower, map(_ref, rp.get("customDomains") or []))) & set(map(str.lower, map(_ref, props.get("customDomains") or []))):
                    return _err(409, "RouteConflict", f"Route {r['name']} already matches the same pattern for the same custom domain.")
        return None
    return None


def _afd_loc(payload):
    loc = str((payload or {}).get("location") or "global").lower()
    return loc == "global"


# ── post-write derivation ──────────────────────────────────────────────────────────────
def after_put(state: dict, rec: dict, payload: dict, prev: dict | None = None) -> None:
    ft = (rec.get("_type") or "").lower()
    p = rec.setdefault("properties", {})
    if ft == NM:
        p.setdefault("provisioningState", "Succeeded")
        p.setdefault("resourceGuid", str(uuid.uuid5(uuid.NAMESPACE_URL, rec["id"].lower())))
        p.setdefault("networkManagerScopes", {}).setdefault("subscriptions", [])
        p["networkManagerScopes"].setdefault("managementGroups", [])
    elif ft in (NM_GROUP, NM_CONN, NM_SEC, NM_COLL, NM_RULE, NM_MEMBER):
        p["provisioningState"] = "Succeeded"
        p.setdefault("resourceGuid", str(uuid.uuid5(uuid.NAMESPACE_URL, rec["id"].lower())))
        if ft == NM_GROUP:
            p.setdefault("memberType", "VirtualNetwork")
        if ft == NM_CONN:
            p.setdefault("deleteExistingPeering", "False")
            p.setdefault("isGlobal", "False")
            p.setdefault("connectivityCapabilities", {"connectedGroupPrivateEndpointsScale": "Standard", "connectedGroupAddressOverlap": "Allowed", "peeringEnforcement": "Unenforced"})
        if ft == NM_RULE:
            p.setdefault("kind", "Custom")
        if ft == NM_SEC:
            p.setdefault("applyOnNetworkIntentPolicyBasedServices", ["None"])
            p.setdefault("networkGroupAddressSpaceAggregationOption", "None")
        if ft == NM_MEMBER:
            p["region"] = (state.get(str(p.get("resourceId", "")).lower()) or {}).get("location")
    elif ft == VNET:
        if "advertisedAddressPrefixes" in p:
            p["advertisedAddressPrefixes"] = [str(_cidr(a)) for a in p["advertisedAddressPrefixes"]]
    elif ft == AKS:
        np = p.get("networkProfile")
        if np is not None:
            np.setdefault("networkPlugin", "kubenet")
            np.setdefault("loadBalancerSku", "standard")
            np.setdefault("outboundType", "loadBalancer")
            if np["networkPlugin"] == "kubenet":
                np.setdefault("podCidr", "10.244.0.0/16")
            if np["networkPlugin"] != "none":
                np.setdefault("serviceCidr", "10.0.0.0/16")
                svc = _cidr(np["serviceCidr"])
                if svc is not None and not np.get("dnsServiceIP"):
                    np["dnsServiceIP"] = str(svc.network_address + 10)
                np.setdefault("serviceCidrs", [np["serviceCidr"]])
                if np.get("podCidr"):
                    np.setdefault("podCidrs", [np["podCidr"]])
                np.setdefault("ipFamilies", ["IPv4"])
            np.setdefault("networkPolicy", None)
            if np.get("networkPolicy") is None:
                np.pop("networkPolicy", None)
    elif ft == CDN:
        p["provisioningState"] = "Succeeded"
        p["resourceState"] = "Active"
        p.setdefault("frontDoorId", str(uuid.uuid5(uuid.NAMESPACE_URL, rec["id"].lower())))
        p.setdefault("originResponseTimeoutSeconds", 60)
        rec["kind"] = "frontdoor" if rec["sku"]["name"] in AFD_SKUS else "cdn"
    elif ft.startswith(CDN + "/"):
        _derive_cdn(state, rec, ft, p)


def _derive_cdn(state, rec, ft, p):
    p["provisioningState"] = "Succeeded"
    p["deploymentStatus"] = "NotStarted"
    if ft == AFD_EP:
        p.setdefault("enabledState", "Enabled")
        p["hostName"] = f"{rec['name']}-{_h(rec['id'], n=12)}.z01.azurefd.net"
        p["autoGeneratedDomainNameLabelScope"] = p.get("autoGeneratedDomainNameLabelScope") or "TenantReuse"
    elif ft == CDN_EP:
        p.setdefault("resourceState", "Running")
        p["hostName"] = f"{rec['name']}.azureedge.net"
        p.setdefault("isHttpAllowed", True)
        p.setdefault("isHttpsAllowed", True)
        p.setdefault("isCompressionEnabled", False)
        p.setdefault("queryStringCachingBehavior", "IgnoreQueryString")
    elif ft == AFD_OG:
        p.setdefault("sessionAffinityState", "Disabled")
        p.setdefault("trafficRestorationTimeToHealedOrNewEndpointsInMinutes", 10)
        p.setdefault("loadBalancingSettings", {"sampleSize": 4, "successfulSamplesRequired": 3, "additionalLatencyInMilliseconds": 50})
    elif ft == AFD_ORIGIN:
        p.setdefault("httpPort", 80)
        p.setdefault("httpsPort", 443)
        p.setdefault("priority", 1)
        p.setdefault("weight", 1000)
        p.setdefault("enabledState", "Enabled")
        p.setdefault("originHostHeader", p.get("hostName"))
        p.setdefault("enforceCertificateNameCheck", True)
    elif ft == AFD_ROUTE:
        p.setdefault("enabledState", "Enabled")
        p.setdefault("supportedProtocols", ["Http", "Https"])
        p.setdefault("patternsToMatch", ["/*"])
        p.setdefault("forwardingProtocol", "MatchRequest")
        p.setdefault("httpsRedirect", "Enabled")
        p.setdefault("linkToDefaultDomain", "Enabled")
    elif ft == AFD_DOMAIN:
        p.setdefault("domainValidationState", "Pending")
        tls = p.setdefault("tlsSettings", {})
        tls.setdefault("certificateType", "ManagedCertificate")
        tls.setdefault("minimumTlsVersion", "TLS12")
        p["validationProperties"] = {"validationToken": _h(rec["id"], "validate", n=32), "expirationDate": None}
        p["dnsValidation"] = {"recordType": "TXT", "name": f"_dnsauth.{p.get('hostName', '')}", "value": p["validationProperties"]["validationToken"]}
    elif ft == AFD_RS:
        p.setdefault("deploymentStatus", "NotStarted")
    elif ft == AFD_RULE:
        p.setdefault("matchProcessingBehavior", "Continue")
    # profile-level view of every endpoint/rule set/origin group keeps lists consistent
    rec["etag"] = f'"{uuid.uuid4().hex}"'


# ── delete rules / cascades ────────────────────────────────────────────────────────────
def before_delete(state: dict, rec: dict):
    ft = (rec.get("_type") or "").lower()
    rid = rec["id"].lower()
    if ft == AFD_OG:
        for r in state.values():
            if isinstance(r, dict) and (r.get("_type") or "").lower() == AFD_ROUTE and _ref((r.get("properties") or {}).get("originGroup")).lower() == rid:
                return _err(409, "OriginGroupInUse", f"Origin group {rec['name']} is used by route {r['name']}; delete or retarget the route first.")
    if ft == AFD_RS:
        for r in state.values():
            if isinstance(r, dict) and (r.get("_type") or "").lower() == AFD_ROUTE:
                if any(_ref(x).lower() == rid for x in (r.get("properties") or {}).get("ruleSets") or []):
                    return _err(409, "RuleSetInUse", f"Rule set {rec['name']} is associated with route {r['name']}; remove the association first.")
    if ft == AFD_DOMAIN:
        for r in state.values():
            if isinstance(r, dict) and (r.get("_type") or "").lower() == AFD_ROUTE:
                if any(_ref(x).lower() == rid for x in (r.get("properties") or {}).get("customDomains") or []):
                    return _err(409, "CustomDomainInUse", f"Custom domain {rec['name']} is associated with route {r['name']}; remove the association first.")
    if ft == NM_GROUP:
        for r in state.values():
            if isinstance(r, dict) and (r.get("_type") or "").lower() in (NM_CONN, NM_COLL):
                if any(_ref({"id": g.get("networkGroupId")}).lower() == rid for g in (r.get("properties") or {}).get("appliesToGroups") or []):
                    return _err(409, "NetworkGroupInUse", f"Network group {rec['name']} is referenced by {r['name']}; remove the reference first.")
    if ft == NM:
        deployed = [r for r in state.values() if isinstance(r, dict) and r.get("id", "").lower().startswith(rid + "/") and (r.get("_type") or "").lower() in (NM_CONN, NM_SEC)]
        if deployed:
            return _err(409, "NetworkManagerHasConfigurations", f"Network manager {rec['name']} still has {len(deployed)} configuration(s); delete them first.")
    if ft == VNET:
        for r in state.values():
            if isinstance(r, dict) and (r.get("_type") or "").lower() in (NM_MEMBER, NM_CONN):
                p = r.get("properties") or {}
                if str(p.get("resourceId", "")).lower().startswith(rid) or any(str(h.get("resourceId", "")).lower() == rid for h in p.get("hubs") or []):
                    return _err(409, "VirtualNetworkInUseByNetworkManager", f"Virtual network {rec['name']} is referenced by Network Manager resource {r['name']}.")
    return None


def on_delete(state: dict, rec: dict) -> None:
    return None


# ── Container Apps environment networking (Microsoft.App/managedEnvironments is owned by azure_app_core) ──────────
def validate_aca_env(state: dict, rid: str, payload: dict, existing: dict | None):
    props = (payload or {}).get("properties") or {}
    vc = props.get("vnetConfiguration")
    old = ((existing or {}).get("properties") or {}).get("vnetConfiguration") or {}
    if existing is not None and "vnetConfiguration" in props:
        if (old.get("infrastructureSubnetId") or "") != ((vc or {}).get("infrastructureSubnetId") or ""):
            return _err(400, "ManagedEnvironmentVnetImmutable", "The virtual network configuration of a Container Apps environment cannot be changed after it is created.")
    if vc is None:
        if props.get("zoneRedundant"):
            return _err(400, "ManagedEnvironmentZoneRedundantRequiresVnet", "zoneRedundant requires a custom virtual network (vnetConfiguration.infrastructureSubnetId).")
        return None
    sid = vc.get("infrastructureSubnetId")
    if vc.get("internal") and not sid:
        return _err(400, "ManagedEnvironmentInternalRequiresSubnet", "An internal environment requires vnetConfiguration.infrastructureSubnetId.")
    if not sid:
        return None
    net, vnet = _subnet_net(state, sid)
    if vnet is None or net is None:
        return _err(400, "ManagedEnvironmentSubnetNotFound", f"Infrastructure subnet {sid} was not found.")
    profiles = props.get("workloadProfiles") or []
    workload = any(w.get("workloadProfileType") and w.get("workloadProfileType") != "Consumption" for w in profiles) or any(w.get("name") for w in profiles)
    need = 27 if workload else 23
    if net.prefixlen > need:
        return _err(400, "ManagedEnvironmentSubnetTooSmall", f"Infrastructure subnet {net} is too small: environments {'with workload profiles ' if workload else ''}need at least a /{need}.")
    for r in state.values():
        if isinstance(r, dict) and (r.get("_type") or "").lower() == "microsoft.app/managedenvironments" and r["id"].lower() != rid.lower():
            if str(((r.get("properties") or {}).get("vnetConfiguration") or {}).get("infrastructureSubnetId", "")).lower() == str(sid).lower():
                return _err(400, "ManagedEnvironmentSubnetInUse", f"Subnet {sid} is already used by environment {r['name']}; each environment needs its own subnet.")
    pc = vc.get("platformReservedCidr")
    if pc:
        pn = _cidr(pc)
        if pn is None:
            return _err(400, "InvalidPlatformReservedCidr", f"platformReservedCidr '{pc}' is not a valid CIDR.")
        if any(pn.overlaps(s) for s in _vnet_address_space(vnet)):
            return _err(400, "PlatformReservedCidrOverlap", f"platformReservedCidr {pn} overlaps the virtual network address space.")
        dns = vc.get("platformReservedDnsIP")
        if dns and ipaddress.ip_address(dns) not in pn:
            return _err(400, "PlatformReservedDnsIPNotInCidr", "platformReservedDnsIP must be within platformReservedCidr.")
    return None
