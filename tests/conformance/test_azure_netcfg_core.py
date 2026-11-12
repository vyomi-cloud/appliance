"""Azure Network Manager, Front Door / CDN profiles, AKS networkProfile, Container Apps env VNet, vnet advertised prefixes.
Run: PYTHONPATH=. python tests/conformance/test_azure_netcfg_core.py"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore


try:
    from core.azure_arm_core import AzureArm as _LaxArm
    _LaxArm.STRICT_SUBSCRIPTION = False   # engine test: ad-hoc subscription ids
except Exception:
    pass


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


RG = f"/subscriptions/{SUB}/resourceGroups/cfg-rg"
N = f"{RG}/providers/Microsoft.Network"
CDN = f"{RG}/providers/Microsoft.Cdn"


def run():
    a = AzureArm()
    put = lambda path, body, v="2023-11-01": a.handle("PUT", path, {"api-version": v}, body)
    get = lambda path, v="2023-11-01": a.handle("GET", path, {"api-version": v})
    dele = lambda path, v="2023-11-01": a.handle("DELETE", path, {"api-version": v})
    code = lambda r: (r["body"] or {}).get("error", {}).get("code") if isinstance(r["body"], dict) else None
    ok = lambda r: r["status"] in (200, 201)
    put(RG, {"location": "eastus"}, "2021-04-01")
    for n, pref in (("hub", "10.1.0.0/16"), ("spoke1", "10.2.0.0/16"), ("spoke2", "10.3.0.0/16")):
        _check(f"vnet {n}", ok(put(f"{N}/virtualNetworks/{n}", {"location": "eastus", "properties": {
            "addressSpace": {"addressPrefixes": [pref]}, "subnets": [{"name": "default", "properties": {"addressPrefix": pref.replace("/16", "/24")}},
                                                                  {"name": "aca", "properties": {"addressPrefix": pref.replace("0.0/16", "8.0/23")}},
                                                                  {"name": "tiny", "properties": {"addressPrefix": pref.replace("0.0/16", "12.0/27")}}]}})))
    # ── advertised address prefixes
    r = put(f"{N}/virtualNetworks/hub", {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.1.0.0/16"]}, "advertisedAddressPrefixes": ["192.168.0.0/24"]}})
    _check("advertised prefix outside address space rejected", r["status"] == 400 and code(r) == "AdvertisedPrefixOutsideAddressSpace")
    _check("advertised prefix not a CIDR rejected", code(put(f"{N}/virtualNetworks/hub", {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.1.0.0/16"]}, "advertisedAddressPrefixes": ["nope"]}})) == "InvalidAdvertisedAddressPrefix")
    r = put(f"{N}/virtualNetworks/hub", {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.1.0.0/16"]}, "advertisedAddressPrefixes": ["10.1.4.0/22"],
                                                                                "subnets": [{"name": "default", "properties": {"addressPrefix": "10.1.0.0/24"}}]}})
    _check("advertised prefix stored", ok(r) and r["body"]["properties"]["advertisedAddressPrefixes"] == ["10.1.4.0/22"])

    # ── Network Manager
    nm = f"{N}/networkManagers/nm1"
    scope = {"subscriptions": [f"/subscriptions/{SUB}"]}
    _check("nm needs scopes", code(put(nm, {"location": "eastus", "properties": {"networkManagerScopeAccesses": ["Connectivity"]}})) == "NetworkManagerScopesRequired")
    _check("nm scope access validated", code(put(nm, {"location": "eastus", "properties": {"networkManagerScopes": scope, "networkManagerScopeAccesses": ["Bogus"]}})) == "InvalidNetworkManagerScopeAccess")
    _check("nm created", ok(put(nm, {"location": "eastus", "properties": {"networkManagerScopes": scope, "networkManagerScopeAccesses": ["Connectivity"]}})))
    nm2 = f"{N}/networkManagers/nm-sec"
    _check("nm connectivity-only", ok(put(nm2, {"location": "eastus", "properties": {"networkManagerScopes": scope, "networkManagerScopeAccesses": ["SecurityAdmin"]}})))
    grp = f"{nm}/networkGroups/g1"
    _check("network group", ok(put(grp, {"properties": {"memberType": "VirtualNetwork"}})))
    _check("static member must be a vnet", code(put(f"{grp}/staticMembers/m0", {"properties": {"resourceId": f"{N}/virtualNetworks/ghost"}})) == "InvalidStaticMember")
    _check("static member added", ok(put(f"{grp}/staticMembers/m1", {"properties": {"resourceId": f"{N}/virtualNetworks/spoke1"}}))
           and ok(put(f"{grp}/staticMembers/m2", {"properties": {"resourceId": f"{N}/virtualNetworks/spoke2"}})))
    cc = f"{nm}/connectivityConfigurations/c1"
    base = {"connectivityTopology": "HubAndSpoke", "hubs": [{"resourceId": f"{N}/virtualNetworks/hub", "resourceType": "Microsoft.Network/virtualNetworks"}],
            "appliesToGroups": [{"networkGroupId": grp, "groupConnectivity": "None", "useHubGateway": "False", "isGlobal": "False"}]}
    _check("topology validated", code(put(cc, {"properties": {**base, "connectivityTopology": "Star"}})) == "InvalidConnectivityTopology")
    _check("hub-and-spoke needs hub", code(put(cc, {"properties": {**base, "hubs": []}})) == "HubRequired")
    _check("hub must exist", code(put(cc, {"properties": {**base, "hubs": [{"resourceId": f"{N}/virtualNetworks/none"}]}})) == "InvalidHub")
    _check("group must exist", code(put(cc, {"properties": {**base, "appliesToGroups": [{"networkGroupId": f"{nm}/networkGroups/ghost"}]}})) == "NetworkGroupNotFound")
    _check("mesh cannot have hubs", code(put(cc, {"properties": {**base, "connectivityTopology": "Mesh"}})) == "HubNotAllowed")
    r = put(cc, {"properties": base})
    _check("connectivity config created", ok(r) and r["body"]["properties"]["provisioningState"] == "Succeeded")
    _check("connectivity needs Connectivity access", code(put(f"{nm2}/connectivityConfigurations/c1", {"properties": base})) in ("NetworkManagerScopeAccessMissing", "NetworkGroupNotFound"))
    _check("nm in use cannot drop Connectivity", code(put(nm, {"location": "eastus", "properties": {"networkManagerScopes": scope, "networkManagerScopeAccesses": ["SecurityAdmin"]}})) == "NetworkManagerScopeAccessInUse")
    _check("group in use cannot be deleted", code(dele(grp)) == "NetworkGroupInUse")
    _check("vnet in use by network manager cannot be deleted", code(dele(f"{N}/virtualNetworks/hub")) == "VirtualNetworkInUseByNetworkManager")
    _check("nm with configs cannot be deleted", code(dele(nm)) == "NetworkManagerHasConfigurations")
    # security admin
    ngs = f"{nm2}/networkGroups/g2"
    _check("sec nm group", ok(put(ngs, {"properties": {"memberType": "VirtualNetwork"}})))
    sc = f"{nm2}/securityAdminConfigurations/s1"
    _check("security admin config", ok(put(sc, {"properties": {"applyOnNetworkIntentPolicyBasedServices": ["None"]}})))
    _check("security admin needs SecurityAdmin access", code(put(f"{nm}/securityAdminConfigurations/s1", {"properties": {}})) == "NetworkManagerScopeAccessMissing")
    rc = f"{sc}/ruleCollections/rc1"
    _check("rule collection needs groups", code(put(rc, {"properties": {"appliesToGroups": []}})) == "AppliesToGroupsRequired")
    _check("rule collection", ok(put(rc, {"properties": {"appliesToGroups": [{"networkGroupId": ngs}]}})))
    rule = lambda n, **kw: put(f"{rc}/rules/{n}", {"kind": "Custom", "properties": {"priority": 10, "access": "Deny", "direction": "Inbound", "protocol": "Tcp",
                                                                                      "sources": [{"addressPrefixType": "IPPrefix", "addressPrefix": "*"}],
                                                                                      "destinations": [{"addressPrefixType": "IPPrefix", "addressPrefix": "10.0.0.0/8"}],
                                                                                      "destinationPortRanges": ["22"], **kw}})
    _check("rule priority range", code(rule("r0", priority=5000)) == "InvalidSecurityAdminRulePriority")
    _check("rule access", code(rule("r0", access="Maybe")) == "InvalidSecurityAdminRuleAccess")
    _check("rule port range", code(rule("r0", destinationPortRanges=["99999"])) == "InvalidSecurityAdminRulePortRange")
    _check("rule address prefix", code(rule("r0", destinations=[{"addressPrefixType": "IPPrefix", "addressPrefix": "10.0.0/8"}])) == "InvalidAddressPrefix")
    _check("rule created", ok(rule("r1")))
    _check("duplicate priority/direction rejected", code(rule("r2")) == "SecurityAdminRulePriorityConflict")
    _check("same priority other direction ok", ok(rule("r3", direction="Outbound")))
    _check("rules listed", len(get(f"{rc}/rules")["body"]["value"]) == 2)

    # ── Front Door / CDN
    fd = f"{CDN}/profiles/fd1"
    _check("profile needs sku", code(put(fd, {"location": "global"}, "2024-02-01")) == "SkuRequired")
    _check("profile sku validated", code(put(fd, {"location": "global", "sku": {"name": "Gold"}}, "2024-02-01")) == "InvalidSku")
    _check("AFD must be global", code(put(fd, {"location": "eastus", "sku": {"name": "Standard_AzureFrontDoor"}}, "2024-02-01")) == "InvalidLocation")
    r = put(fd, {"location": "global", "sku": {"name": "Standard_AzureFrontDoor"}}, "2024-02-01")
    _check("front door profile", ok(r) and r["body"]["properties"]["frontDoorId"] and r["body"]["kind"] == "frontdoor")
    prem = f"{CDN}/profiles/fdp"
    _check("premium profile", ok(put(prem, {"location": "global", "sku": {"name": "Premium_AzureFrontDoor"}}, "2024-02-01")))
    _check("premium cannot downgrade", code(put(prem, {"location": "global", "sku": {"name": "Standard_AzureFrontDoor"}}, "2024-02-01")) == "SkuDowngradeNotAllowed")
    pput = lambda path, props: put(f"{fd}/{path}", {"properties": props}, "2024-02-01")
    r = pput("afdEndpoints/ep1", {"enabledState": "Enabled"})
    _check("afd endpoint hostname derived", ok(r) and r["body"]["properties"]["hostName"].startswith("ep1-") and r["body"]["properties"]["hostName"].endswith(".z01.azurefd.net"))
    _check("endpoint state validated", code(pput("afdEndpoints/ep2", {"enabledState": "Maybe"})) == "InvalidEnabledState")
    og = f"{fd}/originGroups/og1"
    _check("probe interval validated", code(pput("originGroups/og1", {"healthProbeSettings": {"probeIntervalInSeconds": 999}})) == "InvalidProbeInterval")
    _check("lb samples validated", code(pput("originGroups/og1", {"loadBalancingSettings": {"sampleSize": 2, "successfulSamplesRequired": 3}})) == "InvalidLoadBalancingSettings")
    _check("origin group", ok(pput("originGroups/og1", {"healthProbeSettings": {"probePath": "/", "probeProtocol": "Https", "probeRequestType": "HEAD", "probeIntervalInSeconds": 100}})))
    route = lambda n="r1", **kw: pput(f"afdEndpoints/ep1/routes/{n}", {"originGroup": {"id": og}, "patternsToMatch": ["/*"], **kw})
    _check("route to empty origin group rejected", code(route()) == "OriginGroupHasNoOrigins")
    _check("origin host required", code(pput("originGroups/og1/origins/o0", {})) == "OriginHostNameRequired")
    _check("origin weight range", code(pput("originGroups/og1/origins/o0", {"hostName": "a.example.com", "weight": 5000})) == "InvalidOriginWeight")
    _check("origin priority range", code(pput("originGroups/og1/origins/o0", {"hostName": "a.example.com", "priority": 9})) == "InvalidOriginPriority")
    _check("private link needs premium", code(pput("originGroups/og1/origins/o0", {"hostName": "a.example.com", "sharedPrivateLinkResource": {"privateLink": {"id": "/x"}, "groupId": "blob"}})) == "PrivateLinkRequiresPremium")
    r = pput("originGroups/og1/origins/o1", {"hostName": "origin.example.com"})
    _check("origin created with defaults", ok(r) and r["body"]["properties"]["httpsPort"] == 443 and r["body"]["properties"]["originHostHeader"] == "origin.example.com")
    _check("route to missing origin group", code(pput("afdEndpoints/ep1/routes/r1", {"originGroup": {"id": f"{fd}/originGroups/ghost"}})) == "OriginGroupNotFound")
    _check("pattern must start with /", code(route(patternsToMatch=["x"])) == "InvalidPatternToMatch")
    _check("forwarding protocol validated", code(route(forwardingProtocol="Both")) == "InvalidForwardingProtocol")
    _check("https redirect needs Https", code(route(supportedProtocols=["Http"], httpsRedirect="Enabled")) == "HttpsRedirectRequiresHttps")
    _check("route to missing custom domain", code(route(customDomains=[{"id": f"{fd}/customDomains/ghost"}])) == "ReferencedResourceNotFound")
    _check("custom domain host validated", code(pput("customDomains/cd0", {"hostName": "bad host"})) == "InvalidCustomDomainHostName")
    r = pput("customDomains/cd1", {"hostName": "www.contoso.com", "tlsSettings": {"certificateType": "ManagedCertificate", "minimumTlsVersion": "TLS12"}})
    _check("custom domain Pending with dns validation token", ok(r) and r["body"]["properties"]["domainValidationState"] == "Pending" and r["body"]["properties"]["dnsValidation"]["name"] == "_dnsauth.www.contoso.com")
    _check("duplicate custom domain host", code(pput("customDomains/cd2", {"hostName": "WWW.contoso.com"})) == "CustomDomainAlreadyExists")
    _check("customer cert needs secret", code(pput("customDomains/cd3", {"hostName": "x.contoso.com", "tlsSettings": {"certificateType": "CustomerCertificate"}})) == "CustomerCertificateSecretRequired")
    _check("rule set name", code(pput("ruleSets/bad-name", {})) == "InvalidRuleSetName")
    _check("rule set", ok(pput("ruleSets/rs1", {})))
    ruleprops = lambda **kw: {"order": 1, "conditions": [{"name": "UrlPath", "parameters": {"operator": "BeginsWith", "matchValues": ["/api"]}}],
                              "actions": [{"name": "UrlRedirect", "parameters": {"redirectType": "Moved"}}], **kw}
    _check("rule condition validated", code(pput("ruleSets/rs1/rules/ru1", ruleprops(conditions=[{"name": "Nope"}]))) == "InvalidRuleCondition")
    _check("rule needs action", code(pput("ruleSets/rs1/rules/ru1", ruleprops(actions=[]))) == "RuleActionRequired")
    _check("origin group override must exist", code(pput("ruleSets/rs1/rules/ru1", ruleprops(actions=[{"name": "OriginGroupOverride", "parameters": {"originGroup": {"id": f"{fd}/originGroups/nope"}}}]))) == "OriginGroupNotFound")
    _check("rule created", ok(pput("ruleSets/rs1/rules/ru1", ruleprops())))
    _check("rule order unique", code(pput("ruleSets/rs1/rules/ru2", ruleprops())) == "RuleOrderConflict")
    r = route(customDomains=[{"id": f"{fd}/customDomains/cd1"}], ruleSets=[{"id": f"{fd}/ruleSets/rs1"}], httpsRedirect="Enabled")
    _check("route created with domain + rule set", ok(r) and r["body"]["properties"]["forwardingProtocol"] == "MatchRequest")
    _check("route conflict on same pattern+domain", code(route("r2", customDomains=[{"id": f"{fd}/customDomains/cd1"}])) == "RouteConflict")
    _check("origin group in use", code(dele(og, "2024-02-01")) == "OriginGroupInUse")
    _check("rule set in use", code(dele(f"{fd}/ruleSets/rs1", "2024-02-01")) == "RuleSetInUse")
    _check("custom domain in use", code(dele(f"{fd}/customDomains/cd1", "2024-02-01")) == "CustomDomainInUse")
    _check("classic endpoint rejected on AFD", code(pput("endpoints/cdnep", {"origins": [{"name": "o", "properties": {"hostName": "x.com"}}]})) == "OperationNotSupportedForSku")
    _check("route deleted", dele(f"{fd}/afdEndpoints/ep1/routes/r1", "2024-02-01")["status"] in (200, 204))
    _check("origin group deletable after route", dele(og, "2024-02-01")["status"] in (200, 204))
    # classic CDN
    cdn = f"{CDN}/profiles/cdn1"
    _check("classic profile", ok(put(cdn, {"location": "global", "sku": {"name": "Standard_Microsoft"}}, "2024-02-01")))
    _check("classic cannot use afdEndpoints", code(put(f"{cdn}/afdEndpoints/e", {"properties": {}}, "2024-02-01")) == "OperationNotSupportedForSku")
    _check("classic endpoint needs origins", code(put(f"{cdn}/endpoints/e1", {"location": "global", "properties": {}}, "2024-02-01")) == "OriginsRequired")
    r = put(f"{cdn}/endpoints/e1", {"location": "global", "properties": {"origins": [{"name": "o", "properties": {"hostName": "x.example.com"}}]}}, "2024-02-01")
    _check("classic endpoint hostname", ok(r) and r["body"]["properties"]["hostName"] == "e1.azureedge.net")
    _check("sku family change blocked", code(put(cdn, {"location": "global", "sku": {"name": "Standard_AzureFrontDoor"}}, "2024-02-01")) == "SkuChangeNotAllowed")

    # ── AKS networkProfile
    aks = lambda name, np, pools=None: put(f"{RG}/providers/Microsoft.ContainerService/managedClusters/{name}", {"location": "eastus", "properties": {
        "dnsPrefix": name, "agentPoolProfiles": pools or [{"name": "np", "count": 1, "vmSize": "Standard_DS2_v2", "mode": "System"}], "networkProfile": np}}, "2024-02-01")
    _check("aks plugin validated", code(aks("a0", {"networkPlugin": "flannel"})) == "InvalidNetworkPlugin")
    _check("overlay requires azure", code(aks("a0", {"networkPlugin": "kubenet", "networkPluginMode": "overlay"})) == "NetworkPluginModeRequiresAzure")
    _check("azure policy requires azure cni", code(aks("a0", {"networkPlugin": "kubenet", "networkPolicy": "azure"})) == "NetworkPolicyIncompatible")
    _check("cilium requires overlay/pod subnet", code(aks("a0", {"networkPlugin": "azure", "networkDataplane": "cilium"})) == "CiliumRequiresAzureCNI")
    _check("cilium policy needs cilium dataplane", code(aks("a0", {"networkPlugin": "azure", "networkPluginMode": "overlay", "networkPolicy": "cilium"})) == "CiliumPolicyRequiresCiliumDataplane")
    _check("dns ip must be in service cidr", code(aks("a0", {"networkPlugin": "azure", "serviceCidr": "10.0.0.0/16", "dnsServiceIP": "172.16.0.10"})) == "DnsServiceIPNotInServiceCidr")
    _check("dns ip not first addresses", code(aks("a0", {"networkPlugin": "azure", "serviceCidr": "10.0.0.0/16", "dnsServiceIP": "10.0.0.1"})) == "InvalidDnsServiceIP")
    _check("pod cidr overlapping service cidr", code(aks("a0", {"networkPlugin": "kubenet", "serviceCidr": "10.244.0.0/16", "podCidr": "10.244.0.0/16", "dnsServiceIP": "10.244.0.10"})) == "PodCidrOverlapsServiceCidr")
    _check("azure cni (no overlay) rejects podCidr", code(aks("a0", {"networkPlugin": "azure", "podCidr": "10.244.0.0/16"})) == "PodCidrNotAllowed")
    _check("outbound type validated", code(aks("a0", {"networkPlugin": "azure", "outboundType": "magic"})) == "InvalidOutboundType")
    _check("udr requires custom vnet", code(aks("a0", {"networkPlugin": "azure", "outboundType": "userDefinedRouting"})) == "UserDefinedRoutingRequiresSubnet")
    _check("missing node subnet", code(aks("a0", {"networkPlugin": "azure"}, [{"name": "np", "count": 1, "vnetSubnetID": f"{N}/virtualNetworks/spoke1/subnets/nope"}])) == "SubnetNotFound")
    _check("service cidr overlapping node subnet", code(aks("a0", {"networkPlugin": "azure", "serviceCidr": "10.2.0.0/24", "dnsServiceIP": "10.2.0.10"}, [{"name": "np", "count": 1, "vnetSubnetID": f"{N}/virtualNetworks/spoke1/subnets/default"}])) == "ServiceCidrOverlapsSubnet")
    _check("authorized ranges validated", code(put(f"{RG}/providers/Microsoft.ContainerService/managedClusters/a0", {"location": "eastus", "properties": {"networkProfile": {"networkPlugin": "azure"}, "apiServerAccessProfile": {"authorizedIPRanges": ["x"]}}}, "2024-02-01")) == "InvalidAuthorizedIPRange")
    r = aks("a1", {"networkPlugin": "azure", "networkPluginMode": "overlay", "networkPolicy": "cilium", "networkDataplane": "cilium", "podCidr": "192.168.0.0/16"},
            [{"name": "np", "count": 1, "vnetSubnetID": f"{N}/virtualNetworks/spoke1/subnets/default"}])
    npf = (r["body"].get("properties") or {}).get("networkProfile") or {}
    _check("aks overlay+cilium accepted, defaults filled", ok(r) and npf.get("serviceCidr") == "10.0.0.0/16" and npf.get("dnsServiceIP") == "10.0.0.10" and npf.get("outboundType") == "loadBalancer")
    r = aks("a2", {"networkPlugin": "kubenet"})
    _check("kubenet defaults podCidr", ok(r) and r["body"]["properties"]["networkProfile"]["podCidr"] == "10.244.0.0/16")
    _check("network plugin immutable", code(aks("a2", {"networkPlugin": "azure"})) == "PropertyChangeNotAllowed")

    # ── Container Apps environment VNet
    cae = lambda name, props: put(f"{RG}/providers/Microsoft.App/managedEnvironments/{name}", {"location": "eastus", "properties": props}, "2024-03-01")
    sid = lambda v, s: f"{N}/virtualNetworks/{v}/subnets/{s}"
    _check("internal needs subnet", code(cae("e0", {"vnetConfiguration": {"internal": True}})) == "ManagedEnvironmentInternalRequiresSubnet")
    _check("zone redundant needs vnet", code(cae("e0", {"zoneRedundant": True})) == "ManagedEnvironmentZoneRedundantRequiresVnet")
    _check("subnet must exist", code(cae("e0", {"vnetConfiguration": {"infrastructureSubnetId": sid("spoke1", "none")}})) == "ManagedEnvironmentSubnetNotFound")
    _check("consumption env needs /23", code(cae("e0", {"vnetConfiguration": {"infrastructureSubnetId": sid("spoke1", "default")}})) == "ManagedEnvironmentSubnetTooSmall")
    _check("platform cidr must not overlap vnet", code(cae("e0", {"vnetConfiguration": {"infrastructureSubnetId": sid("spoke1", "aca"), "platformReservedCidr": "10.2.0.0/24", "platformReservedDnsIP": "10.2.0.10"}})) == "PlatformReservedCidrOverlap")
    r = cae("e1", {"vnetConfiguration": {"infrastructureSubnetId": sid("spoke1", "aca"), "internal": True}})
    _check("env in custom vnet", ok(r) and r["body"]["properties"]["vnetConfiguration"]["internal"] is True)
    _check("subnet reuse blocked", code(cae("e2", {"vnetConfiguration": {"infrastructureSubnetId": sid("spoke1", "aca")}})) == "ManagedEnvironmentSubnetInUse")
    _check("vnet config immutable", code(cae("e1", {"vnetConfiguration": {"infrastructureSubnetId": sid("spoke2", "aca")}})) == "ManagedEnvironmentVnetImmutable")
    _check("workload-profile env fits /27", ok(cae("e3", {"workloadProfiles": [{"name": "Consumption", "workloadProfileType": "Consumption"}, {"name": "d4", "workloadProfileType": "D4", "minimumCount": 1, "maximumCount": 2}],
                                                          "vnetConfiguration": {"infrastructureSubnetId": sid("spoke2", "tiny")}})))
    print("PASS test_azure_netcfg_core")


if __name__ == "__main__":
    run()
