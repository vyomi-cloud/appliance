from azure.mgmt.frontdoor import FrontDoorManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import ManagedRuleSet, ManagedRulesDefinition, PolicySettings, WebApplicationFirewallPolicy
from azlab import arm, ensure_rg, RG, LOC

ensure_rg()
fd = arm(FrontDoorManagementClient)
fd.policies.begin_create_or_update(RG, "facilitieswaf", {
    "location": "global", "sku": {"name": "Premium_AzureFrontDoor"}, "policy_settings": {"enabled_state": "Enabled", "mode": "Prevention"},
    "managed_rules": {"managed_rule_sets": [{"rule_set_type": "Microsoft_DefaultRuleSet", "rule_set_version": "2.1"}]}}).result()
got = fd.policies.get(RG, "facilitieswaf")
print("Front Door WAF policy", got.name, "mode:", getattr(got.policy_settings.mode, "value", got.policy_settings.mode))

net = arm(NetworkManagementClient)
net.web_application_firewall_policies.create_or_update(RG, "facilitieswafgw", WebApplicationFirewallPolicy(
    location=LOC, policy_settings=PolicySettings(state="Enabled", mode="Prevention"),
    managed_rules=ManagedRulesDefinition(managed_rule_sets=[ManagedRuleSet(rule_set_type="OWASP", rule_set_version="3.2")])))
gw = net.web_application_firewall_policies.get(RG, "facilitieswafgw")
print("Application Gateway WAF policy", gw.name, "mode:", getattr(gw.policy_settings.mode, "value", gw.policy_settings.mode))
