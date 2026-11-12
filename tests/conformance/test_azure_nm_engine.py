"""Virtual Network Manager deploy + effective rules. Run: PYTHONPATH=. python tests/conformance/test_azure_nm_engine.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
AzureArm.STRICT_SUBSCRIPTION = False
RG = f"/subscriptions/{SUB}/resourceGroups/nm-rg"
NMID = RG + "/providers/Microsoft.Network/networkManagers/avnm"


def check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


a = AzureArm()
a.handle("PUT", f"/subscriptions/{SUB}/resourcegroups/nm-rg", {"api-version": "2021-04-01"}, {"location": "eastus"})
def put(rid, body, av="2023-09-01"):
    r = a.handle("PUT", rid, {"api-version": av}, body)
    assert r["status"] in (200, 201), r
    return r["body"]
vn = {}
for i, name in enumerate(["hub", "s1", "s2"]):
    vn[name] = put(f"{RG}/providers/Microsoft.Network/virtualNetworks/{name}", {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": [f"10.{i}.0.0/16"]}}})
put(NMID, {"location": "eastus", "properties": {"networkManagerScopes": {"subscriptions": [f"/subscriptions/{SUB}"]}, "networkManagerScopeAccesses": ["Connectivity", "SecurityAdmin"]}})
g = put(NMID + "/networkGroups/spokes", {"properties": {}})
for n in ("s1", "s2"):
    put(f"{NMID}/networkGroups/spokes/staticMembers/{n}", {"properties": {"resourceId": vn[n]["id"]}})
mesh = put(NMID + "/connectivityConfigurations/mesh", {"properties": {"connectivityTopology": "Mesh", "appliesToGroups": [{"networkGroupId": g["id"], "groupConnectivity": "DirectlyConnected"}]}})
hub = put(NMID + "/connectivityConfigurations/hs", {"properties": {"connectivityTopology": "HubAndSpoke", "hubs": [{"resourceId": vn["hub"]["id"], "resourceType": "Microsoft.Network/virtualNetworks"}], "appliesToGroups": [{"networkGroupId": g["id"], "groupConnectivity": "None", "useHubGateway": "False"}]}})
EP = NMID + "/providers/Microsoft.Vyomi/networkManagerEngine"
post = lambda act, body: a.handle("POST", f"{EP}/{act}", {"api-version": "2023-09-01"}, body)
peers = lambda n: (a.state[vn[n]["id"].lower()]["properties"].get("virtualNetworkPeerings") or [])

check("nothing peered before deploy", all(not peers(n) for n in vn))
r = post("deploy", {"commitType": "Connectivity", "configurationIds": [mesh["id"]]})
check("mesh deploy peers the two spokes both ways", r["status"] == 200 and r["body"]["peeringsCreated"] == 2 and len(peers("s1")) == 1 and len(peers("s2")) == 1
      and peers("s1")[0]["properties"]["remoteVirtualNetwork"]["id"] == vn["s2"]["id"] and peers("s1")[0]["properties"]["peeringState"] == "Connected")
r = post("deploy", {"commitType": "Connectivity", "configurationIds": [hub["id"]]})
check("a new commit REPLACES managed peerings (hub-and-spoke)", len(peers("s1")) == 1 and peers("s1")[0]["properties"]["remoteVirtualNetwork"]["id"] == vn["hub"]["id"] and len(peers("hub")) == 2 and peers("s1")[0]["name"].startswith("ANM_hs"))
check("bad config id rejected", post("deploy", {"commitType": "Connectivity", "configurationIds": [NMID + "/connectivityConfigurations/nope"]})["status"] == 400)
check("status lists commits", len(a.handle("GET", f"{EP}/status", {"api-version": "2023-09-01"})["body"]["commits"]) == 2)

sec = put(NMID + "/securityAdminConfigurations/sa", {"properties": {}})
col = put(NMID + "/securityAdminConfigurations/sa/ruleCollections/c1", {"properties": {"appliesToGroups": [{"networkGroupId": g["id"]}]}})
rule = lambda n, prio, acc, **kw: put(f"{NMID}/securityAdminConfigurations/sa/ruleCollections/c1/rules/{n}", {"kind": "Custom", "properties": {
    "priority": prio, "access": acc, "direction": "Inbound", "protocol": "Tcp", "sources": [{"addressPrefixType": "IPPrefix", "addressPrefix": "*"}],
    "destinations": [{"addressPrefixType": "IPPrefix", "addressPrefix": "*"}], "destinationPortRanges": ["22"], **kw}})
rule("denyssh", 100, "Deny"); rule("allowall22", 200, "AlwaysAllow")
ev = lambda **k: post("evaluate", {"vnetId": vn["s1"]["id"], "direction": "Inbound", "protocol": "Tcp", "sourceAddress": "8.8.8.8", "destinationAddress": "10.1.0.4", "destinationPort": 22, **k})["body"]
check("evaluate before deploy: falls to NSGs", ev()["deployed"] is False and ev()["nextHop"] == "networkSecurityGroups")
post("deploy", {"commitType": "SecurityAdmin", "configurationIds": [sec["id"]]})
e = ev()
check("lowest priority number wins: Deny", e["verdict"] == "Denied" and e["matchedRule"]["rule"] == "denyssh" and e["nextHop"] == "none")
check("other port is not matched", ev(destinationPort=443)["verdict"] == "NoAdminRuleMatched")
check("VNet outside the groups is unaffected", post("evaluate", {"vnetId": vn["hub"]["id"], "direction": "Inbound", "protocol": "Tcp", "sourceAddress": "8.8.8.8", "destinationPort": 22})["body"]["rulesConsidered"] == 0)
put(f"{NMID}/securityAdminConfigurations/sa/ruleCollections/c1/rules/denyssh", {"kind": "Custom", "properties": {"priority": 300, "access": "Deny", "direction": "Inbound", "protocol": "Tcp",
    "sources": [{"addressPrefixType": "IPPrefix", "addressPrefix": "*"}], "destinations": [{"addressPrefixType": "IPPrefix", "addressPrefix": "*"}], "destinationPortRanges": ["22"]}})
e = ev()
check("re-prioritising changes the verdict live (AlwaysAllow now first)", e["verdict"] == "Allowed" and e["nextHop"] == "destination")
print("PASS")
