"""core/azure_monitorproducts_core.py via AzureArm: Azure Monitor workspaces (Managed Prometheus) + Managed Grafana.
Run: PYTHONPATH=. python tests/conformance/test_azure_monitorproducts.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0
SUB = "00000000-0000-0000-0000-cloudlearn01"
RG = "prodrg"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


arm = AzureArm()
h = lambda m, p, av, b=None: arm.handle(m, f"/subscriptions/{SUB}{p}", {"api-version": av}, b)
h("PUT", f"/resourceGroups/{RG}", "2021-04-01", {"location": "eastus"})
MA = f"/resourceGroups/{RG}/providers/Microsoft.Monitor/accounts"
GR = f"/resourceGroups/{RG}/providers/Microsoft.Dashboard/grafana"

r = h("PUT", f"{MA}/prom1", "2023-04-03", {"location": "eastus"})
b = r["body"]
check("monitor account created with query endpoint + default ingestion", r["status"] in (200, 201) and b["properties"]["metrics"]["prometheusQueryEndpoint"].startswith("https://prom1-")
      and "dataCollectionRuleResourceId" in b["properties"]["defaultIngestionSettings"], b)
dcr_id = b["properties"]["defaultIngestionSettings"]["dataCollectionRuleResourceId"]
r = arm.handle("GET", f"/subscriptions/{SUB}{dcr_id.split(SUB)[1]}", {"api-version": "2023-03-11"}, None)
check("its managed DCR really exists with the Prometheus stream", r["status"] == 200 and r["body"]["properties"]["dataFlows"][0]["streams"] == ["Microsoft-PrometheusMetrics"], r["body"])
check("bad account name -> 400", h("PUT", f"{MA}/-bad", "2023-04-03", {"location": "eastus"})["status"] == 400)
check("account without location -> 400", h("PUT", f"{MA}/prom2", "2023-04-03", {})["status"] == 400)
check("account listed in the group", len(h("GET", f"{MA}", "2023-04-03")["body"]["value"]) == 1)
acct_id = f"/subscriptions/{SUB}{MA}/prom1"

r = h("PUT", f"{GR}/graf1", "2023-09-01", {"location": "eastus", "sku": {"name": "Standard"}, "identity": {"type": "SystemAssigned"},
      "properties": {"grafanaMajorVersion": "11", "grafanaIntegrations": {"azureMonitorWorkspaceIntegrations": [{"azureMonitorWorkspaceResourceId": acct_id}]}}})
check("grafana created with endpoint, version and system identity", r["status"] in (200, 201) and r["body"]["properties"]["endpoint"].endswith(".grafana.azure.com")
      and r["body"]["identity"]["principalId"] and r["body"]["properties"]["grafanaVersion"].startswith("11."), r["body"])
check("grafana bad sku -> 400", h("PUT", f"{GR}/graf2", "2023-09-01", {"location": "eastus", "sku": {"name": "Gold"}})["status"] == 400)
check("grafana bad major version -> 400", h("PUT", f"{GR}/graf2", "2023-09-01", {"location": "eastus", "properties": {"grafanaMajorVersion": "3"}})["status"] == 400)
r = h("PUT", f"{GR}/graf2", "2023-09-01", {"location": "eastus", "properties": {"grafanaIntegrations": {"azureMonitorWorkspaceIntegrations": [
    {"azureMonitorWorkspaceResourceId": acct_id + "nope"}]}}})
check("integration with a missing Monitor workspace -> 400", r["status"] == 400, r["body"])
check("grafana name too long -> 400", h("PUT", f"{GR}/{'g' * 24}", "2023-09-01", {"location": "eastus"})["status"] == 400)
check("duplicate grafana name in another group -> 409", (h("PUT", "/resourceGroups/other", "2021-04-01", {"location": "eastus"}), h("PUT", f"/resourceGroups/other/providers/Microsoft.Dashboard/grafana/graf1", "2023-09-01", {"location": "eastus"}))[1]["status"] == 409)
check("deleting an integrated Monitor workspace is refused", h("DELETE", f"{MA}/prom1", "2023-04-03")["status"] == 409)
h("PATCH", f"{GR}/graf1", "2023-09-01", {"properties": {"grafanaIntegrations": {"azureMonitorWorkspaceIntegrations": []}}})
r = h("DELETE", f"{MA}/prom1", "2023-04-03")
check("after removing the integration the delete succeeds and the managed DCR is gone",
      r["status"] == 200 and arm.handle("GET", f"/subscriptions/{SUB}{dcr_id.split(SUB)[1]}", {"api-version": "2023-03-11"}, None)["status"] == 404, r)
check("grafana delete", h("DELETE", f"{GR}/graf1", "2023-09-01")["status"] == 200 and h("GET", f"{GR}/graf1", "2023-09-01")["status"] == 404)

# SCOM managed instance (control-plane record) + Azure Local cluster (Vyomi-simulated record)
SC = f"/resourceGroups/{RG}/providers/Microsoft.Scom/managedInstances"
HC = f"/resourceGroups/{RG}/providers/Microsoft.AzureStackHCI/clusters"
SQLMI = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Sql/managedInstances/sqlmi1"
SUBNET = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Network/virtualNetworks/vn1/subnets/s1"
good = {"location": "eastus", "properties": {"dbInstanceId": SQLMI, "vNetSubnetId": SUBNET,
        "domainControllerProperties": {"dnsServer": "10.0.0.4", "domainName": "corp.local"}, "gmsaAccounts": ["scomgmsa"]}}
r = h("PUT", f"{SC}/scom1", "2023-07-07-preview", good)
check("SCOM managed instance created with management endpoint, SQL MI + subnet recorded", r["status"] in (200, 201)
      and r["body"]["properties"]["dbInstanceId"] == SQLMI and r["body"]["properties"]["managementEndpoint"].startswith("https://scom1-"), r["body"])
check("SCOM instance without a SQL MI id is rejected", h("PUT", f"{SC}/scom2", "2023-07-07-preview", {"location": "eastus", "properties": {"vNetSubnetId": SUBNET, "domainControllerProperties": {"dnsServer": "x", "domainName": "y"}}})["status"] == 400)
check("SCOM instance without domain controller settings is rejected", h("PUT", f"{SC}/scom2", "2023-07-07-preview", {"location": "eastus", "properties": {"dbInstanceId": SQLMI, "vNetSubnetId": SUBNET}})["status"] == 400)
check("SCOM instance listed (RG + subscription scope)", len(h("GET", SC, "2023-07-07-preview")["body"]["value"]) == 1
      and len(h("GET", "/providers/Microsoft.Scom/managedInstances", "2023-07-07-preview")["body"]["value"]) == 1)
check("SCOM instance delete", h("DELETE", f"{SC}/scom1", "2023-07-07-preview")["status"] == 200 and h("GET", f"{SC}/scom1", "2023-07-07-preview")["status"] == 404)

r = h("PUT", f"{HC}/local1", "2024-04-01", {"location": "eastus"})
check("Azure Local cluster without nodes is NotYetRegistered", r["status"] in (200, 201) and r["body"]["properties"]["status"] == "NotYetRegistered", r["body"])
r = h("PUT", f"{HC}/local2", "2024-04-01", {"location": "eastus", "properties": {"reportedProperties": {"nodes": [{"name": "n1"}, {"name": "n2", "coreCount": 32}]}}})
check("Azure Local cluster with declared nodes is ConnectedRecently and lists them", r["body"]["properties"]["status"] == "ConnectedRecently"
      and [n["name"] for n in r["body"]["properties"]["reportedProperties"]["nodes"]] == ["n1", "n2"]
      and "Vyomi-simulated" in r["body"]["properties"]["simulation"], r["body"])
r = h("PATCH", f"{HC}/local1", "2024-04-01", {"properties": {"reportedProperties": {"nodes": [{"name": "a"}]}}})
check("registering nodes on an existing cluster flips it to ConnectedRecently", r["body"]["properties"]["status"] == "ConnectedRecently", r["body"])
check("Azure Local bad node rejected", h("PUT", f"{HC}/local3", "2024-04-01", {"location": "eastus", "properties": {"reportedProperties": {"nodes": [{}]}}})["status"] == 400)
check("Azure Local clusters listed", len(h("GET", "/providers/Microsoft.AzureStackHCI/clusters", "2024-04-01")["body"]["value"]) == 2)
check("Azure Local delete", h("DELETE", f"{HC}/local1", "2024-04-01")["status"] == 200 and h("GET", f"{HC}/local1", "2024-04-01")["status"] == 404)


print(f"\n{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
