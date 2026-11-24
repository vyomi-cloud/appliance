import io
import json
import zipfile
import requests
from azure.mgmt.eventgrid import EventGridManagementClient
from azure.mgmt.eventgrid.models import AzureFunctionEventSubscriptionDestination, EventSubscription, EventSubscriptionFilter, SystemTopic
from azure.mgmt.web import WebSiteManagementClient
from azure.mgmt.web.models import StringDictionary
from azlab import arm, rid, RG, LOC, ENDPOINT, HTTP_ENDPOINT
from azdata import search_endpoint, search_key

APP = "facilities-ingest"
web = arm(WebSiteManagementClient)
web.app_service_plans.begin_create_or_update(RG, APP + "-plan", {"location": LOC, "sku": {"name": "Y1", "tier": "Dynamic"}, "kind": "functionapp"}).result()
web.web_apps.begin_create_or_update(RG, APP, {"location": LOC, "kind": "functionapp,linux", "server_farm_id": rid("Microsoft.Web", "serverfarms", APP + "-plan")}).result()
web.web_apps.update_application_settings(RG, APP, StringDictionary(properties={
    "FUNCTIONS_WORKER_RUNTIME": "python", "SEARCH_ENDPOINT": search_endpoint().replace(ENDPOINT, HTTP_ENDPOINT, 1), "SEARCH_KEY": search_key(), "INDEXER_NAME": "docs-indexer"}))
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("host.json", json.dumps({"version": "2.0"}))
    z.writestr("on-blob/__init__.py", open("fn_ingest_docs.py").read())
    z.writestr("on-blob/function.json", json.dumps({"scriptFile": "__init__.py", "bindings": [
        {"authLevel": "function", "type": "httpTrigger", "direction": "in", "name": "req", "methods": ["get", "post"]}, {"type": "http", "direction": "out", "name": "$return"}]}))
requests.post(f"{ENDPOINT}/azure-data/functions/{APP}/api/zipdeploy", data=buf.getvalue(), timeout=60).raise_for_status()

eg = arm(EventGridManagementClient)
eg.system_topics.begin_create_or_update(RG, "facilitiesdocs-topic", SystemTopic(
    location=LOC, source=rid("Microsoft.Storage", "storageAccounts", "facilitiesdocs"), topic_type="Microsoft.Storage.StorageAccounts")).result()
sub = eg.system_topic_event_subscriptions.begin_create_or_update(RG, "facilitiesdocs-topic", "blob-created", EventSubscription(
    destination=AzureFunctionEventSubscriptionDestination(resource_id=rid("Microsoft.Web", "sites", APP) + "/functions/on-blob"),
    filter=EventSubscriptionFilter(included_event_types=["Microsoft.Storage.BlobCreated"]))).result()
print("function app", APP, "deployed; event subscription blob-created:", getattr(sub.provisioning_state, "value", sub.provisioning_state))
