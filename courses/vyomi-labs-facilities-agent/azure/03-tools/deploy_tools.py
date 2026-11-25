import io
import json
import os
import zipfile
import requests
from azure.mgmt.web import WebSiteManagementClient
from azure.mgmt.web.models import StringDictionary
from azlab import arm, rid, RG, LOC, ENDPOINT, HTTP_ENDPOINT
from azdata import storage_cs, search_endpoint, search_key, function_key, FUNCTION_APP, INDEX

FUNCTIONS = {"kb-search": "fn_kb_search.py", "asset-status": "fn_asset_status.py",
             "approval-decision": "fn_approval_decision.py", "create-work-order": "fn_create_work_order.py"}

web = arm(WebSiteManagementClient)
web.app_service_plans.begin_create_or_update(RG, FUNCTION_APP + "-plan", {"location": LOC, "sku": {"name": "Y1", "tier": "Dynamic"}, "kind": "functionapp"}).result()
web.web_apps.begin_create_or_update(RG, FUNCTION_APP, {"location": LOC, "kind": "functionapp,linux",
                                                       "server_farm_id": rid("Microsoft.Web", "serverfarms", FUNCTION_APP + "-plan")}).result()
web.web_apps.update_application_settings(RG, FUNCTION_APP, StringDictionary(properties={
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "TABLE_CONNECTION_STRING": storage_cs("Table", HTTP_ENDPOINT, "http"),     # the function sandbox reaches the simulator over plain http
    "SEARCH_ENDPOINT": search_endpoint().replace(ENDPOINT, HTTP_ENDPOINT, 1), "SEARCH_KEY": search_key(), "SEARCH_INDEX": INDEX,
    "ASSETS_TABLE": "assets", "WORK_ORDERS_TABLE": "workorders", "LEDGER_TABLE": "approvalledger", "INDEXER_NAME": "docs-indexer"}))

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("host.json", json.dumps({"version": "2.0"}))
    z.writestr("requirements.txt", "azure-functions\nazure-data-tables\nazure-search-documents\n")
    for extra in ("rag_design.py", "rag-design.json"):        # the kb-search tool reads your RAG design at run time
        if os.path.exists(extra):
            z.write(extra)
    for name, path in FUNCTIONS.items():
        z.writestr(f"{name}/__init__.py", open(path).read())
        z.writestr(f"{name}/function.json", json.dumps({"scriptFile": "__init__.py", "bindings": [
            {"authLevel": "function", "type": "httpTrigger", "direction": "in", "name": "req", "methods": ["get", "post"]},
            {"type": "http", "direction": "out", "name": "$return"}]}))
r = requests.post(f"{ENDPOINT}/azure-data/functions/{FUNCTION_APP}/api/zipdeploy", data=buf.getvalue(), timeout=60)
r.raise_for_status()
listed = sorted(f.name.split("/")[-1] for f in web.web_apps.list_functions(RG, FUNCTION_APP))
print("deployed", FUNCTION_APP, listed)
print("host key listed through ARM:", bool(function_key()))
