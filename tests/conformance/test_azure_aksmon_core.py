"""AKS Container Insights / Managed Prometheus / Grafana toggles backed by DCR + Monitor workspace + Grafana.
Run: PYTHONPATH=. python tests/conformance/test_azure_aksmon_core.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
AzureArm.STRICT_SUBSCRIPTION = False


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    RG = f"/subscriptions/{SUB}/resourceGroups/am-rg"
    code = lambda r: (r["body"] or {}).get("error", {}).get("code") if isinstance(r["body"], dict) else None
    put = lambda p, b, v="2024-09-01": a.handle("PUT", p, {"api-version": v}, b)
    get = lambda p, v="2024-09-01": a.handle("GET", p, {"api-version": v})
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    WS = f"{RG}/providers/Microsoft.OperationalInsights/workspaces/law1"
    put(WS, {"location": "eastus"}, "2022-10-01")
    C = f"{RG}/providers/Microsoft.ContainerService/managedClusters/aks1"
    DCRS = f"{RG}/providers/Microsoft.Insights/dataCollectionRules"
    ci = lambda wid, en=True: {"location": "eastus", "properties": {"addonProfiles": {"omsagent": {"enabled": en, "config": {"logAnalyticsWorkspaceResourceID": wid}}}}}
    _check("CI: missing workspace id rejected", code(put(C, {"location": "eastus", "properties": {"addonProfiles": {"omsagent": {"enabled": True}}}})) == "InvalidAddonProfile")
    _check("CI: unknown workspace rejected + cluster not created", code(put(C, ci(WS + "x"))) == "InvalidLogAnalyticsWorkspace" and get(C)["status"] == 404)
    r = put(C, ci(WS))
    _check("CI: cluster created", r["status"] in (200, 201))
    dcr = get(f"{DCRS}/MSCI-eastus-aks1", "2023-03-11")
    _check("CI: real DCR to the workspace", dcr["status"] == 200 and dcr["body"]["properties"]["destinations"]["logAnalytics"][0]["workspaceResourceId"].lower() == WS.lower())
    asc = get(f"{C}/providers/Microsoft.Insights/dataCollectionRuleAssociations/ContainerInsightsExtension", "2023-03-11")
    _check("CI: association on the cluster", asc["status"] == 200 and asc["body"]["properties"]["dataCollectionRuleId"].endswith("MSCI-eastus-aks1"))
    # Prometheus (default workspace) + Grafana (default)
    r = put(C, {"location": "eastus", "properties": {"azureMonitorProfile": {"metrics": {"enabled": True, "createGrafana": True}}}})
    m = r["body"]["properties"]["azureMonitorProfile"]["metrics"]
    _check("Prom: default Monitor workspace created + linked", m["azureMonitorWorkspaceResourceId"].endswith("/accounts/DefaultAzureMonitorWorkspace-eastus"))
    _check("Prom: DCR to the Monitor workspace", get(f"{DCRS}/MSProm-eastus-aks1", "2023-03-11")["body"]["properties"]["destinations"]["monitoringAccounts"][0]["accountResourceId"] == m["azureMonitorWorkspaceResourceId"])
    gr = get(m["grafanaResourceId"], "2023-09-01")
    _check("Grafana: created and integrated with the workspace", gr["status"] == 200 and gr["body"]["properties"]["grafanaIntegrations"]["azureMonitorWorkspaceIntegrations"][0]["azureMonitorWorkspaceResourceId"] == m["azureMonitorWorkspaceResourceId"])
    _check("CI survives the Prometheus update", get(f"{DCRS}/MSCI-eastus-aks1", "2023-03-11")["status"] == 200)
    _check("bad Monitor workspace rejected, state unchanged", code(put(C, {"location": "eastus", "properties": {"azureMonitorProfile": {"metrics": {"enabled": True, "azureMonitorWorkspaceResourceId": RG + "/providers/Microsoft.Monitor/accounts/ghost"}}}})) == "InvalidAzureMonitorWorkspace")
    _check("monitor workspace can't be deleted while Grafana integrates", a.handle("DELETE", m["azureMonitorWorkspaceResourceId"], {"api-version": "2023-04-03"})["status"] in (409,))
    r = put(C, {"location": "eastus", "properties": {"addonProfiles": {"omsagent": {"enabled": False}}, "azureMonitorProfile": {"metrics": {"enabled": False}}}})
    _check("toggles off remove DCRs + associations", get(f"{DCRS}/MSCI-eastus-aks1", "2023-03-11")["status"] == 404 and get(f"{DCRS}/MSProm-eastus-aks1", "2023-03-11")["status"] == 404
           and get(f"{C}/providers/Microsoft.Insights/dataCollectionRuleAssociations/ContainerInsightsExtension", "2023-03-11")["status"] == 404)
    gr = get(m["grafanaResourceId"], "2023-09-01")
    _check("Grafana integration removed", gr["body"]["properties"]["grafanaIntegrations"]["azureMonitorWorkspaceIntegrations"] == [])
    put(C, ci(WS))
    a.handle("DELETE", C, {"api-version": "2024-09-01"})
    _check("cluster delete cascades DCR", get(f"{DCRS}/MSCI-eastus-aks1", "2023-03-11")["status"] == 404)
    print("PASS")


if __name__ == "__main__":
    run()
