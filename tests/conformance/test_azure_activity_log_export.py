"""Activity log "Export Activity Logs" = a SUBSCRIPTION-scope Microsoft.Insights/diagnosticSettings that really delivers:
an ARM write lands as a row in the chosen Log Analytics workspace (queryable with KQL) and as a JSON-lines blob in
insights-activity-logs of the chosen storage account; categories are the real Activity log ones; deleting the setting
stops delivery. Run: PYTHONPATH=. python tests/conformance/test_azure_activity_log_export.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
from core import azure_blob_core as blob

AzureArm.STRICT_SUBSCRIPTION = False
a = AzureArm()
a.blob_store = blob.AzureBlobStore()
RG = f"/subscriptions/{SUB}/resourceGroups/ale-rg"
DS = f"/subscriptions/{SUB}/providers/Microsoft.Insights/diagnosticSettings"
V = "2021-05-01-preview"
req = lambda m, path, body=None, v="2024-05-01", q=None: a.handle(m, path, {"api-version": v, **(q or {})}, body)


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


req("PUT", RG, {"location": "eastus"}, "2021-04-01")
WS = f"{RG}/providers/Microsoft.OperationalInsights/workspaces/ale-law"
ST = f"{RG}/providers/Microsoft.Storage/storageAccounts/alestore"
ok("workspace", req("PUT", WS, {"location": "eastus"}, "2022-10-01")["status"] in (200, 201))
ok("storage", req("PUT", ST, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}, "2023-01-01")["status"] in (200, 201, 202))

cats = req("GET", f"/subscriptions/{SUB}/providers/Microsoft.Insights/diagnosticSettingsCategories", v=V)
ok("categories are the Activity log ones", cats["status"] == 200 and {"Administrative", "Security", "Policy"} <= {c["name"] for c in cats["body"]["value"]}, cats)
ok("list empty before", req("GET", DS, v=V)["body"]["value"] == [])
ok("resource-log category rejected at subscription scope",
   req("PUT", f"{DS}/bad", {"properties": {"workspaceId": WS, "logs": [{"category": "AuditEvent", "enabled": True}]}}, V)["status"] == 400)
ok("no destination rejected", req("PUT", f"{DS}/bad", {"properties": {"logs": [{"category": "Administrative", "enabled": True}]}}, V)["status"] == 400)
r = req("PUT", f"{DS}/export1", {"properties": {"workspaceId": WS, "storageAccountId": ST, "logs": [{"category": "Administrative", "enabled": True}]}}, V)
ok("subscription diagnostic setting created", r["status"] == 200 and r["body"]["name"] == "export1", r)
ok("GET by name", req("GET", f"{DS}/export1", v=V)["status"] == 200)
ok("listed", [x["name"] for x in req("GET", DS, v=V)["body"]["value"]] == ["export1"])

req("PUT", f"{RG}/providers/Microsoft.Network/virtualNetworks/ale-vnet", {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.7.0.0/16"]}}}, "2023-04-01")
rows = lambda: (a.handle("POST", WS + "/api/query", {"api-version": "2022-10-01"},
                         {"query": "AzureDiagnostics | where Category == 'Administrative' | project OperationName, ResourceId"})["body"].get("tables") or [{}])[0].get("rows") or []
ok("workspace received the exported ARM write", any("virtualnetworks/write" in str(r[0]).lower() for r in rows()), rows())
bl = a.blob_store.blobs.get("alestore/insights-activity-logs", {})
ok("storage account received insights-activity-logs JSON lines", len(bl) == 1 and b"virtualNetworks/write" in next(iter(bl.values()))["data"], list(a.blob_store.blobs))

n = len(rows())
ok("delete setting", req("DELETE", f"{DS}/export1", v=V)["status"] == 200)
req("PUT", f"{RG}/providers/Microsoft.Network/virtualNetworks/ale-vnet2", {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.8.0.0/16"]}}}, "2023-04-01")
ok("no delivery after delete", len(rows()) == n)
print("PASS")
