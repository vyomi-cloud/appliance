"""App Service networking (regional VNet integration, access restrictions, hybrid connections) + Deployment Center
sources (LocalGit, Azure Repos, Bitbucket, container registry). Run: PYTHONPATH=. python tests/conformance/test_azure_webnet_core.py"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    Q = {"api-version": "2023-12-01"}
    RG = f"/subscriptions/{SUB}/resourceGroups/wn-rg"
    W = f"{RG}/providers/Microsoft.Web"
    N = f"{RG}/providers/Microsoft.Network"
    code = lambda r: (r["body"] or {}).get("error", {}).get("code") if isinstance(r["body"], dict) else None
    put = lambda p, b, q=Q: a.handle("PUT", p, q, b)
    get = lambda p, q=Q: a.handle("GET", p, q)
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    sn = lambda name, prefix, deleg=None, ep=None: {"name": name, "properties": {"addressPrefix": prefix,
         **({"delegations": [{"name": "d", "properties": {"serviceName": deleg}}]} if deleg else {}),
         **({"serviceEndpoints": [{"service": ep}]} if ep else {})}}
    a.handle("PUT", f"{N}/virtualNetworks/v1", {"api-version": "2023-11-01"}, {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}, "subnets": [
        sn("web", "10.0.1.0/26", "Microsoft.Web/serverFarms"), sn("plain", "10.0.2.0/26"), sn("tiny", "10.0.3.0/29", "Microsoft.Web/serverFarms"),
        sn("ep", "10.0.4.0/26", None, "Microsoft.Web"), sn("web2", "10.0.5.0/26", "Microsoft.Web/serverFarms")]}})
    a.handle("PUT", f"{N}/virtualNetworks/vw", {"api-version": "2023-11-01"}, {"location": "westus", "properties": {"addressSpace": {"addressPrefixes": ["10.9.0.0/16"]}, "subnets": [sn("web", "10.9.1.0/26", "Microsoft.Web/serverFarms")]}})
    put(f"{W}/serverfarms/b1", {"location": "eastus", "sku": {"name": "B1"}})
    put(f"{W}/serverfarms/b2", {"location": "eastus", "sku": {"name": "B1"}})
    put(f"{W}/serverfarms/free", {"location": "eastus", "sku": {"name": "F1"}})
    site = lambda n, plan="b1", **props: put(f"{W}/sites/{n}", {"location": "eastus", "kind": "app,linux", "properties": {"serverFarmId": f"{W}/serverfarms/{plan}", **props}})
    sid = lambda v, s: f"{N}/virtualNetworks/{v}/subnets/{s}"
    # ── network injection at create
    _check("create: subnet must exist", code(site("app0", virtualNetworkSubnetId=sid("v1", "ghost"))) == "InvalidSubnet")
    _check("create: subnet must be delegated", code(site("app0", virtualNetworkSubnetId=sid("v1", "plain"))) == "SubnetNotDelegated")
    _check("create: subnet min /28", code(site("app0", virtualNetworkSubnetId=sid("v1", "tiny"))) == "SubnetTooSmall")
    _check("create: region must match", code(site("app0", virtualNetworkSubnetId=sid("vw", "web"))) == "VnetRegionMismatch")
    _check("create: free plan cannot integrate", code(site("app0", plan="free", virtualNetworkSubnetId=sid("v1", "web"))) == "VnetIntegrationNotSupportedOnPlan")
    r = site("app1", virtualNetworkSubnetId=sid("v1", "web"))
    _check("injected app created", r["status"] in (200, 201) and r["body"]["properties"]["virtualNetworkSubnetId"].endswith("/subnets/web"))
    _check("subnet used by another plan rejected", code(site("app2", plan="b2", virtualNetworkSubnetId=sid("v1", "web"))) == "SubnetInUseByAnotherPlan")
    _check("same plan may share the subnet", site("app3", virtualNetworkSubnetId=sid("v1", "web"))["status"] in (200, 201))
    S = f"{W}/sites/app1"
    nc = get(f"{S}/networkConfig/virtualNetwork")
    _check("networkConfig reflects integration", nc["status"] == 200 and nc["body"]["properties"]["subnetResourceId"].endswith("/subnets/web"))
    vc = get(f"{S}/virtualNetworkConnections")["body"]["value"]
    _check("virtualNetworkConnections lists the vnet", len(vc) == 1 and vc[0]["name"] == "v1" and vc[0]["properties"]["isSwift"] is True)
    _check("switch subnet via networkConfig", put(f"{S}/networkConfig/virtualNetwork", {"properties": {"subnetResourceId": sid("v1", "web2")}})["status"] == 200)
    _check("route-all via config/web", put(f"{S}/config/web", {"properties": {"vnetRouteAllEnabled": True}})["body"]["properties"]["vnetRouteAllEnabled"] is True)
    _check("route-all needs integration", code(put(f"{W}/sites/app3/config/web", {"properties": {"vnetRouteAllEnabled": True}})) is None)
    a.handle("DELETE", f"{W}/sites/app3/networkConfig/virtualNetwork", Q)
    _check("route-all needs integration (after disconnect)", code(put(f"{W}/sites/app3/config/web", {"properties": {"vnetRouteAllEnabled": True}})) == "VnetRouteAllRequiresIntegration")
    _check("disconnect clears integration", a.handle("DELETE", f"{S}/networkConfig/virtualNetwork", Q)["status"] == 200 and get(f"{S}/networkConfig/virtualNetwork")["status"] == 404)

    # ── access restrictions
    cfg = lambda body, n="app1": put(f"{W}/sites/{n}/config/web", {"properties": body})
    default = get(f"{S}/config/web")["body"]["properties"]["ipSecurityRestrictions"]
    _check("default tail rule Allow all", len(default) == 1 and default[0]["name"] == "Allow all" and default[0]["priority"] == 2147483647)
    rule = lambda **kw: {"name": "r", "action": "Allow", "priority": 100, "ipAddress": "203.0.113.0/24", **kw}
    _check("action validated", code(cfg({"ipSecurityRestrictions": [rule(action="Maybe")]})) == "InvalidRestrictionAction")
    _check("priority validated", code(cfg({"ipSecurityRestrictions": [rule(priority=0)]})) == "InvalidRestrictionPriority")
    _check("duplicate priority", code(cfg({"ipSecurityRestrictions": [rule(), rule(name="r2")]})) == "DuplicateRestrictionPriority")
    _check("ip validated", code(cfg({"ipSecurityRestrictions": [rule(ipAddress="999.1.1.1/24")]})) == "InvalidRestrictionIp")
    _check("service tag validated", code(cfg({"ipSecurityRestrictions": [rule(ipAddress="NotATag", tag="ServiceTag")]})) == "InvalidServiceTag")
    _check("subnet rule needs service endpoint", code(cfg({"ipSecurityRestrictions": [{"name": "s", "action": "Allow", "priority": 5, "vnetSubnetResourceId": sid("v1", "plain")}]})) == "ServiceEndpointRequired")
    _check("subnet rule must exist", code(cfg({"ipSecurityRestrictions": [{"name": "s", "action": "Allow", "priority": 5, "vnetSubnetResourceId": sid("v1", "ghost")}]})) == "RestrictionSubnetNotFound")
    _check("front door id must be a GUID", code(cfg({"ipSecurityRestrictions": [rule(ipAddress="AzureFrontDoor.Backend", tag="ServiceTag", headers={"x-azure-fdid": ["abc"]})]})) == "InvalidFrontDoorId")
    r = cfg({"ipSecurityRestrictions": [rule(priority=200, name="b"), {"name": "sub", "action": "Allow", "priority": 100, "vnetSubnetResourceId": sid("v1", "ep")},
                                        rule(priority=300, name="fd", ipAddress="AzureFrontDoor.Backend", tag="ServiceTag", headers={"x-azure-fdid": ["12345678-1234-1234-1234-123456789abc"]})]})
    rs = r["body"]["properties"]["ipSecurityRestrictions"]
    _check("rules sorted, Deny all tail added, default action Deny", [x["priority"] for x in rs] == [100, 200, 300, 2147483647] and rs[-1]["name"] == "Deny all"
           and r["body"]["properties"]["ipSecurityRestrictionsDefaultAction"] == "Deny")
    r = cfg({"scmIpSecurityRestrictions": [rule(action="Deny", ipAddress="198.51.100.0/24")], "scmIpSecurityRestrictionsUseMain": False})
    _check("deny-only keeps Allow all tail", r["body"]["properties"]["scmIpSecurityRestrictions"][-1]["name"] == "Allow all")

    # ── hybrid connections
    hc = lambda n, ns="relay1", **kw: put(f"{S}/hybridConnectionNamespaces/{ns}/relays/{n}", {"properties": {
        "relayArmUri": f"{RG}/providers/Microsoft.Relay/namespaces/{ns}/hybridConnections/{n}", "hostname": "db.corp.local", "port": 1433, "sendKeyName": "defaultSender", **kw}})
    _check("relay uri validated", code(hc("h0", relayArmUri="/nope")) == "InvalidRelayArmUri")
    _check("hostname required", code(hc("h0", hostname="")) == "EndpointHostRequired")
    _check("port validated", code(hc("h0", port=70000)) == "InvalidEndpointPort")
    _check("send key required", code(hc("h0", sendKeyName="")) == "SendKeyRequired")
    r = hc("h1")
    _check("hybrid connection stored", r["status"] == 200 and r["body"]["properties"]["serviceBusNamespace"] == "relay1.servicebus.windows.net")
    _check("hybrid connections listed", len(get(f"{S}/hybridConnectionRelays")["body"]["value"]) == 1)
    for i in range(2, 6):
        hc(f"h{i}")
    _check("Basic plan limit (5) enforced", code(hc("h6")) == "HybridConnectionLimitReached")
    _check("hybrid connection removed", a.handle("DELETE", f"{S}/hybridConnectionNamespaces/relay1/relays/h1", Q)["status"] == 200 and get(f"{S}/hybridConnectionNamespaces/relay1/relays/h1")["status"] == 404)
    put(f"{W}/sites/freeapp", {"location": "eastus", "kind": "app", "properties": {"serverFarmId": f"{W}/serverfarms/free"}})
    _check("free plan has no hybrid connections", code(put(f"{W}/sites/freeapp/hybridConnectionNamespaces/r/relays/h", {"properties": {"relayArmUri": f"{RG}/providers/Microsoft.Relay/namespaces/r/hybridConnections/h", "hostname": "x", "port": 80, "sendKeyName": "k"}})) == "HybridConnectionsNotSupportedOnPlan")

    # ── Deployment Center sources
    T = f"{W}/sites/app3"
    _check("scmType validated", code(put(f"{T}/config/web", {"properties": {"scmType": "Svn"}})) == "InvalidScmType")
    _check("repo scm types are set through the repository", code(put(f"{T}/config/web", {"properties": {"scmType": "ExternalGit"}})) == "SourceRequiresRepository")
    _check("local git enabled", put(f"{T}/config/web", {"properties": {"scmType": "LocalGit"}})["body"]["properties"]["scmType"] == "LocalGit")
    _check("repo source blocked while LocalGit", code(put(f"{T}/sourcecontrols/web", {"properties": {"repoUrl": "https://example.com/o/r.git"}})) == "SourceControlAlreadyConfigured")
    _check("switching source directly blocked", code(put(f"{T}/config/web", {"properties": {"scmType": "OneDrive"}})) == "SourceControlAlreadyConfigured")
    _check("sync explains local git", "local Git" in a.handle("POST", f"{T}/sync", Q)["body"]["error"]["message"])
    _check("local git disconnected", put(f"{T}/config/web", {"properties": {"scmType": "None"}})["body"]["properties"]["scmType"] == "None")
    _check("azure repos url validated", code(put(f"{T}/sourcecontrols/web", {"properties": {"repoUrl": "https://dev.azure.com/org/only"}})) == "BadRequest")
    r = put(f"{T}/sourcecontrols/web", {"properties": {"repoUrl": "https://dev.azure.com/org/proj/_git/repo", "branch": "main"}})
    _check("azure repos stored, scmType VSTSRM", r["status"] in (200, 201) and r["body"]["properties"]["provider"] == "AzureRepos" and get(f"{T}/config/web")["body"]["properties"]["scmType"] == "VSTSRM")
    r = put(f"{T}/sourcecontrols/web", {"properties": {"repoUrl": "https://bitbucket.org/team/app.git", "branch": "main"}})
    _check("bitbucket scmType", get(f"{T}/config/web")["body"]["properties"]["scmType"] == "BitbucketGit")
    a.handle("DELETE", f"{T}/sourcecontrols/web", Q)
    _check("container image validated", code(put(f"{T}/config/web", {"properties": {"linuxFxVersion": "DOCKER|Bad Image"}})) == "InvalidContainerImage")
    _check("container image accepted", put(f"{T}/config/web", {"properties": {"linuxFxVersion": "DOCKER|myreg.azurecr.io/team/app:v1"}})["body"]["properties"]["linuxFxVersion"] == "DOCKER|myreg.azurecr.io/team/app:v1")
    print("PASS test_azure_webnet_core")


if __name__ == "__main__":
    run()
