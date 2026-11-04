"""Azure network services: private endpoints (+ target-side approve/reject), Bastion, Azure Firewall/policy,
DDoS plans, NSG/vnet flow logs. Run: PYTHONPATH=. python tests/conformance/test_azure_netsvc_core.py"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


RG = f"/subscriptions/{SUB}/resourceGroups/net-rg"
N = f"{RG}/providers/Microsoft.Network"
Q = {"api-version": "2023-11-01"}


def run():
    a = AzureArm()
    put = lambda path, body, q=Q: a.handle("PUT", path, q, body)
    get = lambda path, q=Q: a.handle("GET", path, q)
    dele = lambda path, q=Q: a.handle("DELETE", path, q)
    put(RG, {"location": "eastus"}, {"api-version": "2021-04-01"})
    vnet = put(f"{N}/virtualNetworks/v1", {"location": "eastus", "properties": {
        "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
        "subnets": [{"name": "default", "properties": {"addressPrefix": "10.0.0.0/24"}},
                    {"name": "AzureBastionSubnet", "properties": {"addressPrefix": "10.0.1.0/26"}},
                    {"name": "AzureFirewallSubnet", "properties": {"addressPrefix": "10.0.2.0/26"}},
                    {"name": "tiny", "properties": {"addressPrefix": "10.0.3.0/28"}}]}})
    _check("vnet with subnets", vnet["status"] in (200, 201))
    vid = f"{N}/virtualNetworks/v1"
    sa = put(f"{RG}/providers/Microsoft.Storage/storageAccounts/netsa1", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}, {"api-version": "2023-01-01"})
    _check("storage target", sa["status"] in (200, 201))
    sid = f"{RG}/providers/Microsoft.Storage/storageAccounts/netsa1"

    # ── private endpoints
    def pe(name, groups, manual=False, subnet=f"{vid}/subnets/default", target=sid):
        key = "manualPrivateLinkServiceConnections" if manual else "privateLinkServiceConnections"
        return put(f"{N}/privateEndpoints/{name}", {"location": "eastus", "properties": {
            "subnet": {"id": subnet}, key: [{"name": "c1", "properties": {"privateLinkServiceId": target, "groupIds": groups}}]}})
    r = pe("pe-bad-group", ["nonsense"])
    _check("invalid groupId rejected", r["status"] == 400 and r["body"]["error"]["code"] == "PrivateEndpointGroupIdNotSupported")
    r = pe("pe-bad-subnet", ["blob"], subnet=f"{vid}/subnets/nope")
    _check("missing subnet rejected", r["status"] == 400)
    r = pe("pe-bad-target", ["blob"], target=f"{RG}/providers/Microsoft.Storage/storageAccounts/ghost")
    _check("missing target rejected", r["status"] == 400 and r["body"]["error"]["code"] == "PrivateLinkServiceNotFound")
    r = pe("pe1", ["blob"])
    _check("private endpoint created", r["status"] in (200, 201))
    c = r["body"]["properties"]["privateLinkServiceConnections"][0]["properties"]["privateLinkServiceConnectionState"]["status"]
    _check("auto connection Approved", c == "Approved")
    _check("customDnsConfigs has privatelink fqdn + IP", r["body"]["properties"]["customDnsConfigs"][0]["fqdn"] == "netsa1.privatelink.blob.core.windows.net"
           and r["body"]["properties"]["customDnsConfigs"][0]["ipAddresses"][0].startswith("10.0.0."))
    ip1 = r["body"]["properties"]["customDnsConfigs"][0]["ipAddresses"][0]
    r2 = pe("pe2", ["file"])
    ip2 = r2["body"]["properties"]["customDnsConfigs"][0]["ipAddresses"][0]
    _check("second endpoint gets a distinct IP, never reserved .0-.3", ip1 != ip2 and not ip2.endswith((".0", ".1", ".2", ".3")))
    tgt = get(sid, {"api-version": "2023-01-01"})
    _check("target lists 2 privateEndpointConnections", len(tgt["body"]["properties"]["privateEndpointConnections"]) == 2)
    r3 = pe("pe3", ["blob"], manual=True)
    _check("manual connection Pending", r3["body"]["properties"]["manualPrivateLinkServiceConnections"][0]["properties"]["privateLinkServiceConnectionState"]["status"] == "Pending")
    lst = get(f"{sid}/privateEndpointConnections", {"api-version": "2023-01-01"})["body"]["value"]
    pend = [x for x in lst if x["properties"]["privateLinkServiceConnectionState"]["status"] == "Pending"]
    _check("target-side list shows Pending", len(pend) == 1)
    r = put(pend[0]["id"], {"properties": {"privateLinkServiceConnectionState": {"status": "Approved", "description": "ok"}}}, {"api-version": "2023-01-01"})
    _check("approve on target", r["status"] in (200, 201))
    st = get(f"{N}/privateEndpoints/pe3")["body"]["properties"]["manualPrivateLinkServiceConnections"][0]["properties"]["privateLinkServiceConnectionState"]
    _check("approval flows back to the endpoint", st["status"] == "Approved" and st["description"] == "ok")
    r = put(pend[0]["id"], {"properties": {"privateLinkServiceConnectionState": {"status": "Bogus"}}}, {"api-version": "2023-01-01"})
    _check("invalid state rejected", r["status"] == 400)
    dele(f"{N}/privateEndpoints/pe3")
    _check("deleting endpoint removes target connection", len(get(sid, {"api-version": "2023-01-01"})["body"]["properties"]["privateEndpointConnections"]) == 2)

    # ── Bastion
    pipb = put(f"{N}/publicIPAddresses/bpip", {"location": "eastus", "sku": {"name": "Standard"}, "properties": {"publicIPAllocationMethod": "Static"}})
    pipd = put(f"{N}/publicIPAddresses/dpip", {"location": "eastus", "sku": {"name": "Basic"}, "properties": {"publicIPAllocationMethod": "Dynamic"}})
    bast = lambda name, subnet, pip, sku="Standard", **extra: put(f"{N}/bastionHosts/{name}", {"location": "eastus", "sku": {"name": sku}, "properties": {
        "ipConfigurations": [{"name": "ip", "properties": {"subnet": {"id": f"{vid}/subnets/{subnet}"}, "publicIPAddress": {"id": f"{N}/publicIPAddresses/{pip}"}}}], **extra}})
    _check("bastion wrong subnet name", bast("b0", "default", "bpip")["body"]["error"]["code"] == "InvalidBastionSubnetName")
    _check("bastion Basic public IP rejected", bast("b0", "AzureBastionSubnet", "dpip")["body"]["error"]["code"] == "PublicIPAddressMustBeStandardStatic")
    _check("bastion Basic SKU can't tunnel", bast("b0", "AzureBastionSubnet", "bpip", "Basic", enableTunneling=True)["body"]["error"]["code"] == "BastionFeatureRequiresStandardSku")
    _check("bastion scaleUnits range", bast("b0", "AzureBastionSubnet", "bpip", "Standard", scaleUnits=99)["status"] == 400)
    r = bast("b1", "AzureBastionSubnet", "bpip", "Standard", enableTunneling=True, scaleUnits=3)
    _check("bastion created with dnsName", r["status"] in (200, 201) and r["body"]["properties"]["dnsName"].endswith(".bastion.azure.com") and r["body"]["properties"]["scaleUnits"] == 3)
    r = dele(f"{N}/publicIPAddresses/bpip")
    _check("public IP in use by bastion can't be deleted", r["status"] == 400)

    # ── Firewall + policy
    pipf = put(f"{N}/publicIPAddresses/fpip", {"location": "eastus", "sku": {"name": "Standard"}, "properties": {"publicIPAllocationMethod": "Static"}})
    pol = put(f"{N}/firewallPolicies/pol1", {"location": "eastus", "properties": {"sku": {"tier": "Premium"}}})
    _check("firewall policy created", pol["status"] in (200, 201))
    fw = lambda name, tier="Standard", **extra: put(f"{N}/azureFirewalls/{name}", {"location": "eastus", "properties": {
        "sku": {"name": "AZFW_VNet", "tier": tier},
        "ipConfigurations": [{"name": "c", "properties": {"subnet": {"id": f"{vid}/subnets/AzureFirewallSubnet"}, "publicIPAddress": {"id": f"{N}/publicIPAddresses/fpip"}}}], **extra}})
    _check("firewall/policy tier mismatch", fw("fw0", "Standard", firewallPolicy={"id": f"{N}/firewallPolicies/pol1"})["body"]["error"]["code"] == "AzureFirewallPolicyTierMismatch")
    _check("firewall Basic needs management IP", fw("fw0", "Basic")["body"]["error"]["code"] == "AzureFirewallManagementIpConfigurationRequired")
    _check("duplicate rule-collection priority", fw("fw0", "Standard", networkRuleCollections=[{"name": "a", "properties": {"priority": 100}}, {"name": "b", "properties": {"priority": 100}}])["status"] == 400)
    _check("bad subnet name", put(f"{N}/azureFirewalls/fw0", {"location": "eastus", "properties": {"ipConfigurations": [{"name": "c", "properties": {
        "subnet": {"id": f"{vid}/subnets/default"}, "publicIPAddress": {"id": f"{N}/publicIPAddresses/fpip"}}}]}})["body"]["error"]["code"] == "AzureFirewallSubnetNameInvalid")
    r = fw("fw1", "Premium", firewallPolicy={"id": f"{N}/firewallPolicies/pol1"})
    _check("firewall created, private IP allocated", r["status"] in (200, 201) and r["body"]["properties"]["ipConfigurations"][0]["properties"]["privateIPAddress"].startswith("10.0.2."))
    r = put(f"{N}/firewallPolicies/pol1/ruleCollectionGroups/g1", {"properties": {"priority": 50}})
    _check("rule collection group priority range", r["status"] == 400)
    _check("rule collection group ok", put(f"{N}/firewallPolicies/pol1/ruleCollectionGroups/g1", {"properties": {"priority": 200}})["status"] in (200, 201))
    _check("duplicate group priority", put(f"{N}/firewallPolicies/pol1/ruleCollectionGroups/g2", {"properties": {"priority": 200}})["status"] == 400)
    _check("policy in use can't be deleted", dele(f"{N}/firewallPolicies/pol1")["status"] == 409)

    # ── DDoS
    _check("vnet -> missing plan rejected", put(vid, {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}, "enableDdosProtection": True,
                                                  "ddosProtectionPlan": {"id": f"{N}/ddosProtectionPlans/ghost"}}})["status"] == 400)
    _check("ddos plan created", put(f"{N}/ddosProtectionPlans/plan1", {"location": "eastus"})["status"] in (200, 201))
    r = put(vid, {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}, "enableDdosProtection": True,
                                                         "ddosProtectionPlan": {"id": f"{N}/ddosProtectionPlans/plan1"}}})
    _check("vnet attached", r["status"] in (200, 201))
    plan = get(f"{N}/ddosProtectionPlans/plan1")["body"]
    _check("plan tracks attached vnet", [v["id"].lower() for v in plan["properties"]["virtualNetworks"]] == [vid.lower()])
    _check("in-use plan can't be deleted", dele(f"{N}/ddosProtectionPlans/plan1")["body"]["error"]["code"] == "InUseDdosProtectionPlanCannotBeDeleted")

    # ── service-endpoint vnet rules (storage + SQL)
    sidn = f"{vid}/subnets/default"
    r = put(sid, {"location": "eastus", "properties": {"networkAcls": {"defaultAction": "Deny", "virtualNetworkRules": [{"id": sidn}]}}}, {"api-version": "2023-01-01"})
    _check("storage vnet rule needs a Microsoft.Storage service endpoint", r["status"] == 400 and r["body"]["error"]["code"] == "SubnetsHaveNoServiceEndpointsConfigured")
    put(f"{vid}/subnets/default", {"properties": {"addressPrefix": "10.0.0.0/24", "serviceEndpoints": [{"service": "Microsoft.Storage"}, {"service": "Microsoft.Sql"}]}})
    r = put(sid, {"location": "eastus", "properties": {"networkAcls": {"defaultAction": "Deny", "virtualNetworkRules": [{"id": sidn}]}}}, {"api-version": "2023-01-01"})
    _check("storage vnet rule accepted once the endpoint exists", r["status"] in (200, 201))
    for bad in ("10.1.2.3", "8.8.8.0/32", "not-an-ip"):
        r = put(sid, {"location": "eastus", "properties": {"networkAcls": {"ipRules": [{"value": bad}]}}}, {"api-version": "2023-01-01"})
        _check(f"IP rule {bad} rejected", r["status"] == 400)
    r = put(sid, {"location": "eastus", "properties": {"networkAcls": {"ipRules": [{"value": "20.1.2.0/24"}, {"value": "8.8.4.4"}]}}}, {"api-version": "2023-01-01"})
    _check("valid public IP rules accepted", r["status"] in (200, 201))
    put(f"{RG}/providers/Microsoft.Sql/servers/netsql", {"location": "eastus", "properties": {"administratorLogin": "a"}}, {"api-version": "2023-05-01-preview"})
    r = put(f"{RG}/providers/Microsoft.Sql/servers/netsql/virtualNetworkRules/r1", {"properties": {"virtualNetworkSubnetId": f"{vid}/subnets/nope"}}, {"api-version": "2023-05-01-preview"})
    _check("sql rule: missing subnet rejected", r["status"] == 400)
    r = put(f"{RG}/providers/Microsoft.Sql/servers/netsql/virtualNetworkRules/r1", {"properties": {"virtualNetworkSubnetId": sidn}}, {"api-version": "2023-05-01-preview"})
    _check("sql vnet rule created", r["status"] in (200, 201))

    # ── Cosmos DB account vnet + IP rules
    ca = f"{RG}/providers/Microsoft.DocumentDB/databaseAccounts/netcosmos"
    cq = {"api-version": "2024-05-15"}
    r = put(ca, {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {"isVirtualNetworkFilterEnabled": True, "virtualNetworkRules": [{"id": sidn}]}}, cq)
    _check("cosmos vnet rule needs the Microsoft.AzureCosmosDB endpoint", r["status"] == 400)
    put(f"{vid}/subnets/default", {"properties": {"addressPrefix": "10.0.0.0/24", "serviceEndpoints": [{"service": "Microsoft.Storage"}, {"service": "Microsoft.Sql"}, {"service": "Microsoft.AzureCosmosDB"}]}})
    r = put(ca, {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {"isVirtualNetworkFilterEnabled": True, "virtualNetworkRules": [{"id": sidn}], "ipRules": [{"ipAddressOrRange": "20.1.2.3"}]}}, cq)
    _check("cosmos account with vnet + IP rules created", r["status"] in (200, 201))
    _check("cosmos bad IP rule", put(ca, {"location": "eastus", "properties": {"ipRules": [{"ipAddressOrRange": "999.1.1.1"}]}}, cq)["status"] == 400)
    cpe = pe("pe-cosmos", ["Sql"], target=ca)
    _check("private endpoint to Cosmos DB", cpe["status"] in (200, 201) and cpe["body"]["properties"]["customDnsConfigs"][0]["fqdn"] == "netcosmos.privatelink.documents.azure.com")

    # ── Flow logs
    nsg = put(f"{N}/networkSecurityGroups/nsg1", {"location": "eastus"})
    nsg2 = put(f"{N}/networkSecurityGroups/nsg-west", {"location": "westus"})
    nw = put(f"{N}/networkWatchers/NetworkWatcher_eastus", {"location": "eastus"})
    fl = lambda name, body: put(f"{N}/networkWatchers/NetworkWatcher_eastus/flowLogs/{name}", {"location": "eastus", "properties": body})
    base = {"targetResourceId": f"{N}/networkSecurityGroups/nsg1", "storageId": sid, "enabled": True}
    _check("flow log: storage required", fl("f0", {"targetResourceId": base["targetResourceId"]})["body"]["error"]["code"] == "FlowLogStorageIdRequired")
    _check("flow log: region mismatch", fl("f0", {**base, "targetResourceId": f"{N}/networkSecurityGroups/nsg-west"})["body"]["error"]["code"] == "FlowLogRegionMismatch")
    _check("flow log: retention range", fl("f0", {**base, "retentionPolicy": {"days": 400, "enabled": True}})["status"] == 400)
    _check("flow log: version", fl("f0", {**base, "format": {"type": "JSON", "version": 3}})["status"] == 400)
    r = fl("f1", {**base, "retentionPolicy": {"days": 30}, "format": {"version": 2}})
    _check("flow log created", r["status"] in (200, 201) and r["body"]["properties"]["format"]["version"] == 2 and r["body"]["properties"]["retentionPolicy"]["enabled"] is True)
    _check("one flow log per target", fl("f2", base)["status"] == 409)
    _check("flow log list", len(get(f"{N}/networkWatchers/NetworkWatcher_eastus/flowLogs")["body"]["value"]) == 1)
    _check("vnet flow log allowed", fl("f3", {**base, "targetResourceId": vid})["status"] in (200, 201))
    _check("analytics needs workspace", fl("f4", {**base, "targetResourceId": f"{N}/networkSecurityGroups/nsg1",
           "flowAnalyticsConfiguration": {"networkWatcherFlowAnalyticsConfiguration": {"enabled": True, "workspaceResourceId": "/x"}}})["status"] in (400, 409))
    print("PASS test_azure_netsvc_core")


if __name__ == "__main__":
    run()
