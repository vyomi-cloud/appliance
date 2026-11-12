"""Azure Firewall rule evaluation (POST .../azureFirewalls/{fw}/evaluate): DNAT -> Network -> Application, group +
collection priority, base-policy inheritance, implicit deny, FQDN wildcards.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_firewall_eval.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB

RG = f"/subscriptions/{SUB}/resourceGroups/fw-rg"
N = f"{RG}/providers/Microsoft.Network"
Q = {"api-version": "2023-11-01"}


def _check(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


def run():
    a = AzureArm()
    put = lambda p, b, q=Q: a.handle("PUT", p, q, b)
    post = lambda p, b: a.handle("POST", p, Q, b)
    put(RG, {"location": "eastus"}, {"api-version": "2021-04-01"})
    vid = f"{N}/virtualNetworks/v1"
    put(vid, {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
        "subnets": [{"name": "AzureFirewallSubnet", "properties": {"addressPrefix": "10.0.2.0/26"}}]}})
    put(f"{N}/publicIPAddresses/fpip", {"location": "eastus", "sku": {"name": "Standard"}, "properties": {"publicIPAllocationMethod": "Static"}})
    put(f"{N}/firewallPolicies/base", {"location": "eastus", "properties": {"sku": {"tier": "Standard"}}})
    put(f"{N}/firewallPolicies/child", {"location": "eastus", "properties": {"sku": {"tier": "Standard"}, "basePolicy": {"id": f"{N}/firewallPolicies/base"}}})
    net = lambda name, prio, act, rules: {"ruleCollectionType": "FirewallPolicyFilterRuleCollection", "name": name, "priority": prio, "action": {"type": act}, "rules": rules}
    nrule = lambda name, **kw: {"ruleType": "NetworkRule", "name": name, "ipProtocols": ["TCP"], "sourceAddresses": ["10.0.0.0/16"], "destinationAddresses": ["*"], "destinationPorts": ["*"], **kw}
    # base policy: corporate deny of SSH to the internet
    r = put(f"{N}/firewallPolicies/base/ruleCollectionGroups/corp", {"properties": {"priority": 100, "ruleCollections": [
        net("deny-ssh", 100, "Deny", [nrule("ssh", destinationPorts=["22"])])]}})
    _check("base group created", r["status"] in (200, 201), r)
    # child policy: allow everything on 443 (network), allow *.microsoft.com on 80/443 (app), DNAT 1.2.3.4:8080
    put(f"{N}/firewallPolicies/child/ruleCollectionGroups/dnat", {"properties": {"priority": 100, "ruleCollections": [
        {"ruleCollectionType": "FirewallPolicyNatRuleCollection", "name": "d", "priority": 100, "action": {"type": "Dnat"}, "rules": [
            {"ruleType": "NatRule", "name": "web", "ipProtocols": ["TCP"], "sourceAddresses": ["*"], "destinationAddresses": ["20.1.1.1"], "destinationPorts": ["8080"],
             "translatedAddress": "10.0.5.4", "translatedPort": "80"}]}]}})
    put(f"{N}/firewallPolicies/child/ruleCollectionGroups/app", {"properties": {"priority": 200, "ruleCollections": [
        net("allow-ms", 100, "Allow", [{"ruleType": "ApplicationRule", "name": "ms", "sourceAddresses": ["10.0.0.0/16"], "protocols": [{"protocolType": "Https", "port": 443}],
                                        "targetFqdns": ["*.microsoft.com"]}]),
        net("allow-https", 200, "Allow", [nrule("https", destinationPorts=["443"], destinationAddresses=["93.184.216.0/24"])]),
        net("allow-any-ssh", 150, "Allow", [nrule("ssh2", destinationPorts=["22"])])]}})
    r = put(f"{N}/azureFirewalls/fw1", {"location": "eastus", "properties": {"sku": {"name": "AZFW_VNet", "tier": "Standard"},
        "firewallPolicy": {"id": f"{N}/firewallPolicies/child"},
        "ipConfigurations": [{"name": "c", "properties": {"subnet": {"id": f"{vid}/subnets/AzureFirewallSubnet"}, "publicIPAddress": {"id": f"{N}/publicIPAddresses/fpip"}}}]}})
    _check("firewall with child policy created", r["status"] in (200, 201), r)
    ev = lambda **b: post(f"{N}/azureFirewalls/fw1/evaluate", b)["body"]

    o = ev(protocol="TCP", sourceAddress="10.0.1.4", destinationAddress="20.1.1.1", destinationPort=8080)
    _check("DNAT matches first and reports the translation", o["action"] == "Dnat" and o["translatedAddress"] == "10.0.5.4", o)
    o = ev(protocol="TCP", sourceAddress="10.0.1.4", destinationAddress="8.8.8.8", destinationPort=22)
    _check("inherited base-policy Deny wins over the child's Allow (base evaluated first)", o["action"] == "Deny" and o["ruleCollection"] == "deny-ssh", o)
    o = ev(protocol="TCP", sourceAddress="10.0.1.4", destinationAddress="93.184.216.34", destinationPort=443)
    _check("network allow rule", o["action"] == "Allow" and o["rule"] == "https" and o["ruleType"] == "NetworkRule", o)
    o = ev(protocol="Https", sourceAddress="10.0.1.4", destinationFqdn="www.microsoft.com", destinationPort=443)
    _check("application rule matches a wildcard FQDN", o["action"] == "Allow" and o["rule"] == "ms" and o["ruleType"] == "ApplicationRule", o)
    o = ev(protocol="Https", sourceAddress="10.0.1.4", destinationFqdn="evil.example.net", destinationPort=443)
    _check("no match -> implicit Deny", o["action"] == "Deny" and o["ruleType"] == "Default", o)
    o = ev(protocol="Https", sourceAddress="192.168.0.9", destinationFqdn="www.microsoft.com", destinationPort=443)
    _check("source outside the rule's sourceAddresses -> Deny", o["action"] == "Deny", o)
    o = ev(protocol="UDP", sourceAddress="10.0.1.4", destinationAddress="93.184.216.34", destinationPort=443)
    _check("protocol mismatch -> Deny", o["action"] == "Deny", o)
    _check("unknown firewall -> 404", post(f"{N}/azureFirewalls/ghost/evaluate", {})["status"] == 404)
    print("azure firewall evaluation: all checks passed")


if __name__ == "__main__":
    run()
