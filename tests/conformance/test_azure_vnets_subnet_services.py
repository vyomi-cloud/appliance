"""Subnet service endpoints + delegation persist through the ARM core (config-only, see
azure.vnets.subnetservices). Run: PYTHONPATH=. python tests/conformance/test_azure_vnets_subnet_services.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB

def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")

arm = AzureArm()
vnet = f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/v1"
arm.handle("PUT", vnet, {"api-version": "2023-11-01"}, {"location": "eastus"})
body = {"properties": {"addressPrefix": "10.0.2.0/24",
        "serviceEndpoints": [{"service": "Microsoft.Storage", "locations": ["*"]}, {"service": "Microsoft.KeyVault", "locations": ["*"]}],
        "delegations": [{"name": "Microsoft_Web_serverFarms", "properties": {"serviceName": "Microsoft.Web/serverFarms"}}]}}
r = arm.handle("PUT", vnet + "/subnets/s1", {"api-version": "2023-11-01"}, body)
check("subnet with endpoints + delegation accepted", r["status"] in (200, 201))
g = arm.handle("GET", vnet + "/subnets/s1", {"api-version": "2023-11-01"})["body"]["properties"]
check("service endpoints round-trip", [e["service"] for e in g["serviceEndpoints"]] == ["Microsoft.Storage", "Microsoft.KeyVault"])
check("delegation round-trips", g["delegations"][0]["properties"]["serviceName"] == "Microsoft.Web/serverFarms")
print("ALL GREEN")
