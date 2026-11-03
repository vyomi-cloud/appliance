"""Resource health + Advisor (core/azure_health_core.py via AzureArm)."""
from core.azure_arm_core import AzureArm

SUB = "00000000-0000-0000-0000-cloudlearn01"
RG = f"/subscriptions/{SUB}/resourceGroups/rg1"


def _arm():
    a = AzureArm(); a._base = "http://x"
    a.handle("PUT", f"/subscriptions/{SUB}/resourcegroups/rg1", {"api-version": "2021-04-01"}, {"location": "eastus"})
    return a


def _put(a, path, v, body):
    r = a.handle("PUT", f"{RG}/providers/{path}", {"api-version": v}, body)
    assert r["status"] < 300, r
    return f"{RG}/providers/{path}"


def test_resource_health_current_and_listing():
    a = _arm()
    rid = _put(a, "Microsoft.Network/virtualNetworks/v1", "2023-04-01", {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}}})
    r = a.handle("GET", f"{rid}/providers/Microsoft.ResourceHealth/availabilityStatuses/current", {"api-version": "2022-10-01"})
    assert r["status"] == 200 and r["body"]["properties"]["availabilityState"] == "Available"
    assert r["body"]["name"] == "current"
    r = a.handle("GET", f"{RG}/providers/Microsoft.ResourceHealth/availabilityStatuses", {"api-version": "2022-10-01"})
    assert [x["properties"]["resourceId"] for x in r["body"]["value"]] == [rid]
    r = a.handle("GET", f"{RG}/providers/Microsoft.Network/virtualNetworks/nope/providers/Microsoft.ResourceHealth/availabilityStatuses/current", {"api-version": "2022-10-01"})
    assert r["status"] == 404


def test_advisor_rules_and_suppression():
    a = _arm()
    nsg = _put(a, "Microsoft.Network/networkSecurityGroups/n1", "2023-04-01", {"location": "eastus", "properties": {"securityRules": [
        {"name": "ssh", "properties": {"access": "Allow", "direction": "Inbound", "sourceAddressPrefix": "*", "destinationPortRange": "22", "protocol": "Tcp", "priority": 100, "sourcePortRange": "*", "destinationAddressPrefix": "*"}}]}})
    _put(a, "Microsoft.KeyVault/vaults/k1", "2023-02-01", {"location": "eastus", "properties": {"tenantId": "t", "sku": {"family": "A", "name": "standard"}}})
    q = {"api-version": "2023-01-01"}
    r = a.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Advisor/recommendations", q)
    recs = r["body"]["value"]
    kinds = {x["properties"]["recommendationTypeId"] for x in recs}
    assert "nsg-admin-ports" in kinds and "kv-purge-protection" in kinds
    assert recs[0]["properties"]["impact"] == "High"
    r = a.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Advisor/recommendations", {**q, "$filter": "ResourceGroup eq 'rg1' and Category eq 'Security'"})
    assert len(r["body"]["value"]) == len(recs)
    r = a.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Advisor/recommendations", {**q, "$filter": "Category eq 'Cost'"})
    assert r["body"]["value"] == []
    rec = [x for x in recs if x["properties"]["recommendationTypeId"] == "nsg-admin-ports"][0]
    assert a.handle("PUT", f"/subscriptions/{SUB}/providers/Microsoft.Advisor/recommendations/{rec['name']}/suppressions/snooze1", q, {"properties": {"ttl": "07:00:00:00"}})["status"] == 200
    again = a.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Advisor/recommendations", q)["body"]["value"]
    assert [x for x in again if x["name"] == rec["name"]][0]["properties"]["suppressionIds"] == ["snooze1"]
    assert a.handle("DELETE", f"/subscriptions/{SUB}/providers/Microsoft.Advisor/recommendations/{rec['name']}/suppressions/snooze1", q)["status"] == 204
    assert nsg
