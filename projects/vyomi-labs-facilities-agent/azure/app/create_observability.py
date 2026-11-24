import json
from azure.mgmt.applicationinsights import ApplicationInsightsManagementClient
from azure.mgmt.loganalytics import LogAnalyticsManagementClient
from azlab import arm, rid, ensure_rg, RG, LOC, ENDPOINT

ensure_rg()
ws = arm(LogAnalyticsManagementClient).workspaces.begin_create_or_update(RG, "facilities-law", {"location": LOC}).result()
ai = arm(ApplicationInsightsManagementClient).components.create_or_update(RG, "facilities-ai", {
    "location": LOC, "kind": "web", "application_type": "web", "workspace_resource_id": rid("Microsoft.OperationalInsights", "workspaces", "facilities-law")})
ikey = ai.connection_string.split("InstrumentationKey=")[1].split(";")[0]
json.dump({"workspace_id": ws.customer_id, "ingest": f"InstrumentationKey={ikey};IngestionEndpoint={ENDPOINT}/"}, open("obs.json", "w"))
print("workspace facilities-law customerId:", ws.customer_id, "| application insights facilities-ai ready")
