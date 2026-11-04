"""Azure Policy rule engine: custom policyRule definitions are evaluated (deny at PUT, audit/deny
compliance via PolicyInsights), built-ins are listed by their real GUID. Run: PYTHONPATH=. python tests/conformance/test_azure_policy_core.py"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


P = f"/subscriptions/{SUB}/providers/Microsoft.Authorization"


def run():
    a = AzureArm()
    a.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/pol-rg", {"api-version": "2021-04-01"}, {"location": "eastus"})
    r = a.handle("GET", f"{P}/policyDefinitions", {"api-version": "2021-06-01"})
    names = [d["name"] for d in r["body"]["value"]]
    _check("built-in definitions listed by real GUID", "e56962a6-4747-49cd-b67b-bf8b01975c4c" in names and len(names) >= 6)
    # existing resources, created before any assignment
    sa = f"/subscriptions/{SUB}/resourceGroups/pol-rg/providers/Microsoft.Storage/storageAccounts/polsa1"
    r = a.handle("PUT", sa, {"api-version": "2023-01-01"}, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"},
                                                          "properties": {"supportsHttpsTrafficOnly": False}})
    _check("storage created pre-policy", r["status"] in (200, 201))
    # custom definition: deny storage accounts without tag costcenter
    bad = a.handle("PUT", f"{P}/policyDefinitions/bad", {"api-version": "2021-06-01"}, {"properties": {"policyRule": {"if": {}}}})
    _check("invalid policyRule rejected", bad["status"] == 400)
    d = {"properties": {"displayName": "Deny storage w/o costcenter", "mode": "Indexed", "policyRule": {
        "if": {"allOf": [{"field": "type", "equals": "Microsoft.Storage/storageAccounts"},
                         {"field": "tags['costcenter']", "exists": "false"}]}, "then": {"effect": "deny"}}}}
    r = a.handle("PUT", f"{P}/policyDefinitions/deny-sa-notag", {"api-version": "2021-06-01"}, d)
    _check("custom definition stored", r["status"] in (200, 201))
    asg = {"properties": {"displayName": "no untagged storage", "policyDefinitionId": f"/subscriptions/{SUB}/providers/Microsoft.Authorization/policyDefinitions/deny-sa-notag"}}
    r = a.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/pol-rg/providers/Microsoft.Authorization/policyAssignments/a1", {"api-version": "2022-06-01"}, asg)
    _check("RG-scoped assignment stored", r["status"] in (200, 201))
    r = a.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/pol-rg/providers/Microsoft.Storage/storageAccounts/polsa2", {"api-version": "2023-01-01"},
                 {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
    _check("custom deny rule blocks untagged storage (403)", r["status"] == 403 and r["body"]["error"]["code"] == "RequestDisallowedByPolicy")
    r = a.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/pol-rg/providers/Microsoft.Storage/storageAccounts/polsa3", {"api-version": "2023-01-01"},
                 {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}, "tags": {"costcenter": "x"}})
    _check("tagged storage allowed", r["status"] in (200, 201))
    # audit built-in: secure transfer
    a.handle("PUT", f"/subscriptions/{SUB}/providers/Microsoft.Authorization/policyAssignments/sec",
             {"api-version": "2022-06-01"}, {"properties": {"policyDefinitionId": "/providers/Microsoft.Authorization/policyDefinitions/404c3081-a854-4457-ae30-26a93ef643f9"}})
    r = a.handle("POST", f"/subscriptions/{SUB}/resourceGroups/pol-rg/providers/Microsoft.PolicyInsights/policyStates/latest/queryResults", {"api-version": "2019-10-01"})
    rows = r["body"]["value"]
    st = {(x["resourceId"].split("/")[-1], x["policyAssignmentName"]): x["complianceState"] for x in rows}
    _check("audit: http-only storage NonCompliant", st.get(("polsa1", "sec")) == "NonCompliant")
    _check("audit: https storage Compliant", st.get(("polsa3", "sec")) == "Compliant")
    _check("deny-rule assignment flags pre-existing untagged account", st.get(("polsa1", "a1")) == "NonCompliant")
    # allowed locations still enforced
    a.handle("PUT", f"/subscriptions/{SUB}/providers/Microsoft.Authorization/policyAssignments/loc", {"api-version": "2022-06-01"},
             {"properties": {"policyDefinitionId": "/providers/Microsoft.Authorization/policyDefinitions/e56962a6-4747-49cd-b67b-bf8b01975c4c",
                             "parameters": {"listOfAllowedLocations": {"value": ["eastus"]}}}})
    r = a.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/pol-rg/providers/Microsoft.Network/virtualNetworks/v1", {"api-version": "2023-11-01"}, {"location": "westeurope"})
    _check("allowed-locations still denies", r["status"] == 403 and "not permitted" in r["body"]["error"]["message"])
    # allowed resource types
    a.handle("PUT", f"/subscriptions/{SUB}/providers/Microsoft.Authorization/policyAssignments/nt", {"api-version": "2022-06-01"},
             {"properties": {"policyDefinitionId": "/providers/Microsoft.Authorization/policyDefinitions/6c112d4e-5bc7-47ae-a041-ea2d9dccd749",
                             "parameters": {"listOfResourceTypesNotAllowed": {"value": ["Microsoft.Network/networkSecurityGroups"]}}}})
    r = a.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/pol-rg/providers/Microsoft.Network/networkSecurityGroups/n1", {"api-version": "2023-11-01"}, {"location": "eastus"})
    _check("not-allowed-types denies NSG", r["status"] == 403)
    print("PASS test_azure_policy_core")


if __name__ == "__main__":
    run()
