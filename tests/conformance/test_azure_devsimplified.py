"""core/azure_devsimplified_core.py + the new Event Grid / resource group task templates, via AzureArm.
Run: PYTHONPATH=. python tests/conformance/test_azure_devsimplified.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0
SUB = "00000000-0000-0000-0000-cloudlearn01"
RG = "dsrg"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


arm = AzureArm()
h = lambda m, p, av, b=None: arm.handle(m, f"/subscriptions/{SUB}{p}", {"api-version": av}, b)
h("PUT", f"/resourceGroups/{RG}", "2021-04-01", {"location": "eastus"})
P = f"/resourceGroups/{RG}/providers"
INS = "/providers/Microsoft.Vyomi/defenderInsights"

# Defender insights computed from resources
r = h("GET", f"{INS}/dataSecurity", "2024-01-01")
check("data security empty with no resources", r["status"] == 200 and r["body"]["findings"] == [] and r["body"]["dataSource"] == "Dev Simplified", r)
h("PUT", f"{P}/Microsoft.Storage/storageAccounts/dssa1", "2023-01-01", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"},
                                                                         "properties": {"allowBlobPublicAccess": True, "supportsHttpsTrafficOnly": False}})
h("PUT", f"{P}/Microsoft.KeyVault/vaults/dskv1", "2023-07-01", {"location": "eastus", "properties": {"tenantId": "t", "sku": {"family": "A", "name": "standard"}}})
f = h("GET", f"{INS}/dataSecurity", "2024-01-01")["body"]["findings"]
check("storage public blob + http findings computed", any(x["resourceName"] == "dssa1" and "public access" in x["finding"] for x in f)
      and any(x["resourceName"] == "dssa1" and "Secure transfer" in x["finding"] for x in f), f)
check("key vault finding computed", any(x["resourceName"] == "dskv1" for x in f), f)
h("PATCH", f"{P}/Microsoft.Storage/storageAccounts/dssa1", "2023-01-01", {"properties": {"allowBlobPublicAccess": False}})
f2 = h("GET", f"{INS}/dataSecurity", "2024-01-01")["body"]["findings"]
check("findings change when the resource changes", not any(x["resourceName"] == "dssa1" and "public access" in x["finding"] for x in f2), f2)
w = h("GET", f"{INS}/workloadProtections", "2024-01-01")["body"]["plans"]
check("workload protections count resources", next(p for p in w if p["plan"] == "Storage")["resources"] == 1, w)
h("PUT", f"{P}/Microsoft.Network/networkSecurityGroups/nsg1", "2023-09-01", {"location": "eastus", "properties": {"securityRules": [
    {"name": "allow-ssh", "properties": {"priority": 100, "direction": "Inbound", "access": "Allow", "protocol": "Tcp", "sourceAddressPrefix": "*",
                                          "sourcePortRange": "*", "destinationAddressPrefix": "*", "destinationPortRange": "22"}}]}})
n = h("GET", f"{INS}/firewallManager", "2024-01-01")["body"]["networkSecurityGroups"]
check("firewall manager flags open inbound rule", n and n[0]["openInboundRules"] == ["allow-ssh"], n)
check("unknown insight 404", h("GET", f"{INS}/nope", "2024-01-01")["status"] == 404)
check("insight is read-only", h("PUT", f"{INS}/dataSecurity", "2024-01-01", {})["status"] in (400, 405))

# Fabric mirroring record
h("PUT", f"{P}/Microsoft.Sql/servers/dssql", "2023-05-01-preview", {"location": "eastus", "properties": {"administratorLogin": "a", "administratorLoginPassword": "P@ssw0rd123!"}})
h("PUT", f"{P}/Microsoft.Sql/servers/dssql/databases/appdb", "2023-05-01-preview", {"location": "eastus"})
M = f"{P}/Microsoft.Vyomi/fabricMirrors"
body = {"location": "eastus", "properties": {"sqlServerName": "dssql", "databaseName": "appdb", "fabricWorkspace": "analytics-ws", "tables": ["dbo.orders"]}}
check("mirror for a missing database -> 404", h("PUT", f"{M}/m0", "2024-01-01", {"properties": {**body["properties"], "databaseName": "nope"}})["status"] == 404)
check("mirror without workspace -> 400", h("PUT", f"{M}/m0", "2024-01-01", {"properties": {"sqlServerName": "dssql", "databaseName": "appdb"}})["status"] == 400)
r = h("PUT", f"{M}/m1", "2024-01-01", body)
check("mirror created Running with simulated sync", r["status"] == 201 and r["body"]["properties"]["state"] == "Running" and r["body"]["properties"]["simulatedSync"]["syncCount"] == 1, r["body"])
check("sync bumps the counter", h("POST", f"{M}/m1/sync", "2024-01-01")["body"]["properties"]["simulatedSync"]["syncCount"] == 2)
check("stop then sync -> 409", h("POST", f"{M}/m1/stop", "2024-01-01")["body"]["properties"]["state"] == "Stopped" and h("POST", f"{M}/m1/sync", "2024-01-01")["status"] == 409)
check("mirror listed", len(h("GET", M, "2024-01-01")["body"]["value"]) == 1)
check("mirror deleted", h("DELETE", f"{M}/m1", "2024-01-01")["status"] == 200 and h("GET", f"{M}/m1", "2024-01-01")["status"] == 404)

# Tasks: Event Grid topic + resource group
h("PUT", f"{P}/Microsoft.EventGrid/topics/t1", "2022-06-15", {"location": "eastus"})
q = lambda rt: arm.handle("GET", f"/subscriptions/{SUB}/providers/Microsoft.Logic/vyomiTaskTemplates", {"api-version": "2019-05-01", "resourceType": rt}, None)["body"]["value"]
check("event grid templates listed", {"eventgrid-disable-public-access", "eventgrid-subscriptions-report"} <= {t["id"] for t in q("Microsoft.EventGrid/topics")})
check("resource group templates listed", {"rg-resources-report", "rg-set-tag"} <= {t["id"] for t in q("Microsoft.Resources/resourceGroups")})
tid = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.EventGrid/topics/t1"
c = h("POST", f"{P}/Microsoft.Logic/vyomiCreateTask", "2019-05-01", {"templateId": "eventgrid-disable-public-access", "resourceId": tid, "name": "eg-off"})
check("event grid task created", c["status"] == 201, c)
rr = h("POST", f"{P}/Microsoft.Logic/workflows/eg-off/triggers/Recurrence/run", "2019-05-01")
check("event grid task run really disables public access", rr["status"] == 200 and rr["body"]["status"] == "Succeeded"
      and h("GET", f"{P}/Microsoft.EventGrid/topics/t1", "2022-06-15")["body"]["properties"]["publicNetworkAccess"] == "Disabled", rr)
rgid = f"/subscriptions/{SUB}/resourceGroups/{RG}"
c = h("POST", f"{P}/Microsoft.Logic/vyomiCreateTask", "2019-05-01", {"templateId": "rg-set-tag", "resourceId": rgid, "name": "rg-tag", "parameters": {"tagName": "reviewed", "tagValue": "yes"}})
check("resource group task created", c["status"] == 201, c)
rr = h("POST", f"{P}/Microsoft.Logic/workflows/rg-tag/triggers/Recurrence/run", "2019-05-01")
check("resource group task run really stamps the tag", rr["body"]["status"] == "Succeeded" and h("GET", f"/resourceGroups/{RG}", "2021-04-01")["body"]["tags"].get("reviewed") == "yes", rr)
c = h("POST", f"{P}/Microsoft.Logic/vyomiCreateTask", "2019-05-01", {"templateId": "rg-resources-report", "resourceId": rgid, "name": "rg-rep"})
rr = h("POST", f"{P}/Microsoft.Logic/workflows/rg-rep/triggers/Recurrence/run", "2019-05-01")
check("resource group report run succeeds", rr["body"]["status"] == "Succeeded", rr)
check("template/type mismatch rejected", h("POST", f"{P}/Microsoft.Logic/vyomiCreateTask", "2019-05-01", {"templateId": "rg-resources-report", "resourceId": tid, "name": "x"})["status"] == 400)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
