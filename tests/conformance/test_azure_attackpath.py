"""Defender CSPM attack path analysis + Cloud Security Explorer over live ARM state.
Run: PYTHONPATH=. python tests/conformance/test_azure_attackpath.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
AzureArm.STRICT_SUBSCRIPTION = False
RG = "ap-rg"
SEC = f"/subscriptions/{SUB}/providers/Microsoft.Security"


def check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


arm = AzureArm()
arm.handle("PUT", f"/subscriptions/{SUB}/resourcegroups/{RG}", {"api-version": "2021-04-01"}, {"location": "eastus"})
rid = lambda t, n: f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/{t}/{n}"
def put(r, body, av="2023-09-01"):
    x = arm.handle("PUT", r, {"api-version": av}, {"location": "eastus", **body})
    assert x["status"] in (200, 201), x
    return x["body"]
def paths():
    return arm.handle("GET", SEC + "/attackPaths", {"api-version": "2022-11-20-preview"})
def explore(**q):
    return arm.handle("POST", SEC + "/cloudSecurityExplorer", {"api-version": "2022-11-20-preview"}, q)

check("needs Defender CSPM plan", paths()["status"] == 403)
arm.handle("PUT", SEC + "/pricings/CloudPosture", {"api-version": "2024-01-01"}, {"properties": {"pricingTier": "Standard"}})
check("no resources -> no paths", paths()["body"]["value"] == [])

nsg = put(rid("Microsoft.Network/networkSecurityGroups", "nsg1"), {"properties": {"securityRules": [
    {"name": "ssh", "properties": {"priority": 100, "direction": "Inbound", "access": "Allow", "protocol": "Tcp", "sourceAddressPrefix": "*", "sourcePortRange": "*", "destinationAddressPrefix": "*", "destinationPortRange": "22"}}]}})
pip = put(rid("Microsoft.Network/publicIPAddresses", "pip1"), {"properties": {"publicIPAllocationMethod": "Static"}})
nic = put(rid("Microsoft.Network/networkInterfaces", "nic1"), {"properties": {"networkSecurityGroup": {"id": nsg["id"]},
    "ipConfigurations": [{"name": "ip", "properties": {"publicIPAddress": {"id": pip["id"]}}}]}})
vm = put(rid("Microsoft.Compute/virtualMachines", "web1"), {"identity": {"type": "SystemAssigned"}, "properties": {"networkProfile": {"networkInterfaces": [{"id": nic["id"]}]}}})
pid = vm.get("identity", {}).get("principalId")
check("VM got a managed identity principal", bool(pid))
kv = put(rid("Microsoft.KeyVault/vaults", "kv1"), {"properties": {"tenantId": "t", "sku": {"family": "A", "name": "standard"}, "accessPolicies": []}}, "2023-07-01")
st = put(rid("Microsoft.Storage/storageAccounts", "stpub1"), {"sku": {"name": "Standard_LRS"}, "kind": "StorageV2", "properties": {"allowBlobPublicAccess": True}}, "2023-01-01")
check("exposed VM but identity has no role -> no path", paths()["body"]["value"] == [])
KVADMIN = "00482a5a-887f-4fb3-b363-3b7fe8e74483"
def assign(name, role_guid, scope):
    r = arm.handle("PUT", f"{scope}/providers/Microsoft.Authorization/roleAssignments/{name}", {"api-version": "2022-04-01"},
                   {"properties": {"principalId": pid, "roleDefinitionId": f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/{role_guid}"}})
    assert r["status"] in (200, 201), r
assign("11111111-1111-1111-1111-111111111111", "4633458b-17de-408a-b874-0445c86b69e6", kv["id"])   # Key Vault Secrets User
p = paths()["body"]["value"]
check("path found: internet -> VM -> identity -> Key Vault", len(p) == 1 and p[0]["steps"][1]["via"][0]["port"] == 22 and p[0]["steps"][3]["type"] == "microsoft.keyvault/vaults")
check("data-role path is High", p[0]["riskLevel"] in ("High", "Critical"))
assign("22222222-2222-2222-2222-222222222222", "b24988ac-6180-42a0-ab88-20f7382dd24c", f"/subscriptions/{SUB}/resourceGroups/{RG}")   # Contributor on RG
p = paths()["body"]["value"]
tgts = {x["target"].rsplit("/", 1)[-1] for x in p}
check("Contributor on RG adds paths to the storage account and vault", {"stpub1", "kv1"} <= tgts)
sp = next(x for x in p if x["target"].endswith("stpub1"))
check("privileged + public-blob insight => Critical", sp["riskLevel"] == "Critical" and any("public" in i["name"].lower() for i in sp["steps"][3]["insights"]))
check("remediation lists the NSG rule", "ssh" in sp["remediation"][0])
one = arm.handle("GET", SEC + "/attackPaths/" + sp["id"], {"api-version": "2022-11-20-preview"})
check("get one by id", one["status"] == 200 and one["body"]["id"] == sp["id"])
# explorer
r = explore(nodeType="microsoft.compute/virtualmachines", filters=["exposedToInternet", "hasIdentity", "canAccess:microsoft.keyvault/vaults"])
check("explorer: exposed VM with identity that can reach a Key Vault", r["status"] == 200 and r["body"]["count"] == 1 and r["body"]["results"][0]["name"] == "web1")
check("explorer: privileged filter", explore(nodeType="microsoft.compute/virtualmachines", filters=["privileged"])["body"]["count"] == 1)
check("explorer: storage with recommendations", explore(nodeType="microsoft.storage/storageaccounts", filters=["hasRecommendation"])["body"]["count"] == 1)
check("explorer: unknown filter 400", explore(filters=["nope"])["status"] == 400)
# fix the NSG: remove exposure -> paths vanish (live)
put(rid("Microsoft.Network/networkSecurityGroups", "nsg1"), {"properties": {"securityRules": []}})
check("closing SSH removes every attack path (computed live)", paths()["body"]["value"] == [] and explore(filters=["exposedToInternet"])["body"]["count"] == 0)
print("PASS")
