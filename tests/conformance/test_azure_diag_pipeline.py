"""Diagnostic settings deliver for real: a resource operation lands as a row in the chosen Log Analytics workspace (queryable
with KQL) and as a JSON-lines blob in the chosen storage account (whose firewall is honoured); a disabled category, a missing
destination and an Event Hub destination are NOT delivered. Run: PYTHONPATH=. python tests/conformance/test_azure_diag_pipeline.py"""
import json

from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
from core import azure_blob_core as blob

AzureArm.STRICT_SUBSCRIPTION = False
a = AzureArm()
a.blob_store = blob.AzureBlobStore()
RG = f"/subscriptions/{SUB}/resourceGroups/dg-rg"
put = lambda path, body, v="2024-05-01": a.handle("PUT", path, {"api-version": v}, body)


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


put(RG, {"location": "eastus"}, "2021-04-01")
WS = f"{RG}/providers/Microsoft.OperationalInsights/workspaces/dg-law"
ST = f"{RG}/providers/Microsoft.Storage/storageAccounts/dgstore"
KV = f"{RG}/providers/Microsoft.KeyVault/vaults/dgvault"
ok("workspace", put(WS, {"location": "eastus"}, "2022-10-01")["status"] in (200, 201))
ok("storage", put(ST, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}, "2023-01-01")["status"] in (200, 201, 202))
ok("vault", put(KV, {"location": "eastus", "properties": {"tenantId": "00000000-0000-0000-0000-000000000000", "sku": {"family": "A", "name": "standard"}, "accessPolicies": []}}, "2023-07-01")["status"] in (200, 201, 202))
DS = KV + "/providers/Microsoft.Insights/diagnosticSettings/ds1"
r = put(DS, {"properties": {"workspaceId": WS, "storageAccountId": ST, "logs": [{"category": "AuditEvent", "enabled": True}],
                            "metrics": [{"category": "AllMetrics", "enabled": True}]}}, "2021-05-01-preview")
ok("diagnostic setting", r["status"] in (200, 201), r)
put(KV, {"location": "eastus", "tags": {"x": "1"}, "properties": {"tenantId": "00000000-0000-0000-0000-000000000000", "sku": {"family": "A", "name": "standard"}, "accessPolicies": []}}, "2023-07-01")

q = lambda kql: a.handle("POST", WS + "/api/query", {"api-version": "2022-10-01"}, {"query": kql})
r = q("AzureDiagnostics | where Category == 'AuditEvent'")
rows = (r["body"].get("tables") or [{}])[0].get("rows") or []
ok("workspace received the AuditEvent log (queryable with KQL)", r["status"] == 200 and len(rows) >= 1, r)
r = q("AzureMetrics | where MetricName == 'ActivityOperations'")
ok("workspace received the ActivityOperations metric", r["status"] == 200 and len((r["body"].get("tables") or [{}])[0].get("rows") or []) >= 1, r)
bl = a.blob_store.blobs.get("dgstore/insights-logs-auditevent", {})
ok("storage account received insights-logs-auditevent JSON lines", len(bl) == 1 and b"AuditEvent" in next(iter(bl.values()))["data"], list(a.blob_store.blobs))
n0 = len(rows)

# a category that is not enabled / a different resource is not delivered
emit = __import__("core.azure_diag_pipeline", fromlist=["x"])
ok("a category not enabled on the setting is not delivered", emit.emit_log(a.state, KV, "AzurePolicyEvaluationDetails", "x") == 0)
ok("a resource without settings is not delivered", emit.emit_log(a.state, ST, "AuditEvent", "x") == 0)

# storage firewall on the destination: Deny + no trusted bypass -> delivery fails; bypass=AzureServices -> delivered
a.state[ST.lower()]["properties"]["networkAcls"] = {"defaultAction": "Deny", "bypass": "None"}
before = a.state[DS.lower()]["_delivery"]["failed"]
emit.emit_log(a.state, KV, "AuditEvent", "blocked-op")
ok("storage firewall (Deny, no bypass) BLOCKS the delivery", a.state[DS.lower()]["_delivery"]["failed"] == before + 1 and "firewall" in a.state[DS.lower()]["_delivery"]["lastError"])
ok("...and the blob was not written", b"blocked-op" not in next(iter(a.blob_store.blobs["dgstore/insights-logs-auditevent"].values()))["data"])
a.state[ST.lower()]["properties"]["networkAcls"]["bypass"] = "AzureServices"
emit.emit_log(a.state, KV, "AuditEvent", "allowed-op")
ok("trusted-service bypass lets the delivery through", b"allowed-op" in next(iter(a.blob_store.blobs["dgstore/insights-logs-auditevent"].values()))["data"])

# Event Hub destination is honestly not delivered
EH = DS.replace("ds1", "ds2")
put(EH, {"properties": {"eventHubAuthorizationRuleId": f"{RG}/providers/Microsoft.EventHub/namespaces/n/authorizationRules/r", "eventHubName": "h",
                        "logs": [{"categoryGroup": "allLogs", "enabled": True}]}}, "2021-05-01-preview")
emit.emit_log(a.state, KV, "AuditEvent", "to-hub")
ok("Event Hub destination counted as failed, not faked", a.state[EH.lower()]["_delivery"]["failed"] == 1 and a.state[EH.lower()]["_delivery"]["delivered"] == 0)

# Dedicated destination type -> resource-specific table
put(DS, {"properties": {"workspaceId": WS, "logAnalyticsDestinationType": "Dedicated", "logs": [{"category": "AuditEvent", "enabled": True}]}}, "2021-05-01-preview")
emit.emit_log(a.state, KV, "AuditEvent", "dedicated-op")
r = q("AZKVAuditLogs | take 5")
ok("Dedicated destination writes the resource-specific table", r["status"] == 200 and len((r["body"].get("tables") or [{}])[0].get("rows") or []) == 1, r)
print("diag pipeline ok")

# ── data-plane emitters: Cosmos DataPlaneRequests, Service Bus RuntimeAuditLogs, blob StorageWrite, Azure OpenAI RequestResponse
from core import azure_cosmos_core as cz, azure_servicebus_core as sbc, ai_models_core as aim
from core.aws_wire_router import InMemoryMessagingStore
CA = f"{RG}/providers/Microsoft.DocumentDB/databaseAccounts/dgcz"
put(CA, {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {"databaseAccountOfferType": "Standard", "locations": [{"locationName": "East US", "failoverPriority": 0}]}}, "2024-05-15")
put(CA + "/providers/Microsoft.Insights/diagnosticSettings/d", {"properties": {"workspaceId": WS, "logs": [{"category": "DataPlaneRequests", "enabled": True}]}}, "2021-05-01-preview")
cz.dispatch(cz.CosmosStore(), "GET", "/dbs", {}, {"x-vyomi-account": "dgcz"}, b"", arm_state=a.state)
r = q("AzureDiagnostics | where Category == 'DataPlaneRequests'")
ok("Cosmos data-plane request delivered to the workspace", len((r["body"].get("tables") or [{}])[0].get("rows") or []) == 1, r)

NS = f"{RG}/providers/Microsoft.ServiceBus/namespaces/dgns"
put(NS, {"location": "eastus", "sku": {"name": "Standard", "tier": "Standard"}}, "2022-10-01-preview")
put(NS + "/providers/Microsoft.Insights/diagnosticSettings/d", {"properties": {"workspaceId": WS, "logs": [{"category": "RuntimeAuditLogs", "enabled": True}]}}, "2021-05-01-preview")
sbc.dispatch(InMemoryMessagingStore(), "PUT", "/q1", {}, {"x-vyomi-namespace": "dgns"}, b"", arm_state=a.state)
r = q("AzureDiagnostics | where Category == 'RuntimeAuditLogs'")
ok("Service Bus runtime call delivered to the workspace", len((r["body"].get("tables") or [{}])[0].get("rows") or []) == 1, r)

put(ST + "/providers/Microsoft.Insights/diagnosticSettings/d", {"properties": {"workspaceId": WS, "logs": [{"category": "StorageWrite", "enabled": True}, {"category": "StorageRead", "enabled": True}]}}, "2021-05-01-preview")
sk = {"authorization": "SharedKey dgstore:sig", "x-ms-blob-type": "BlockBlob"}
blob.dispatch(a.blob_store, "PUT", "/dgstore/c1", {"restype": "container"}, sk, b"", arm_state=a.state)
blob.dispatch(a.blob_store, "PUT", "/dgstore/c1/b.txt", {}, sk, b"hello", arm_state=a.state)
blob.dispatch(a.blob_store, "GET", "/dgstore/c1/b.txt", {}, sk, b"", arm_state=a.state)
r = q("AzureDiagnostics | where Category == 'StorageWrite'")
w = len((r["body"].get("tables") or [{}])[0].get("rows") or [])
r = q("AzureDiagnostics | where Category == 'StorageRead'")
rd = len((r["body"].get("tables") or [{}])[0].get("rows") or [])
ok("blob PutContainer+PutBlob -> 2 StorageWrite rows; GetBlob -> 1 StorageRead row", (w, rd) == (2, 1), (w, rd))
print("diag data-plane ok")
