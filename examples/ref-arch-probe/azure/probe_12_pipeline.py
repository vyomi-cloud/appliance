"""Component 12 Pipeline: Blob upload -> Event Grid -> Function -> AI Search indexer run."""
import io, json, time, zipfile, requests
from _common import *

P = Probe(12, "pipeline", "Pipeline: Blob -> Event Grid -> Function -> AI Search indexer")
B = endpoint(); ensure_rg(B)
KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
S = {}
SCOPE = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Storage/storageAccounts/stpipe1"


def blob_upload():
    from azure.mgmt.storage import StorageManagementClient
    arm(StorageManagementClient, B).storage_accounts.begin_create(RG, "stpipe1", {"location": LOC, "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}).result()
    from azure.storage.blob import BlobServiceClient
    cs = f"DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey={KEY};BlobEndpoint={B}/devstoreaccount1;"
    bs = BlobServiceClient.from_connection_string(cs); S["bs"] = bs
    bs.create_container("docs")
    bs.get_blob_client("docs", "policy.txt").upload_blob(b"approvals above 500 need a manager")
    assert bs.get_blob_client("docs", "policy.txt").download_blob().readall().startswith(b"approvals")


def fn_setup():
    from azure.mgmt.web import WebSiteManagementClient
    w = arm(WebSiteManagementClient, B)
    w.app_service_plans.begin_create_or_update(RG, "plan1", {"location": LOC, "sku": {"name": "Y1", "tier": "Dynamic"}, "kind": "functionapp"}).result()
    w.web_apps.begin_create_or_update(RG, "ingest-fn", {"location": LOC, "kind": "functionapp", "server_farm_id": f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Web/serverfarms/plan1"}).result()
    code = "import json\nimport azure.functions as func\ndef main(req: func.HttpRequest) -> func.HttpResponse:\n    ev = req.get_json()\n    return func.HttpResponse(json.dumps({'received': len(ev) if isinstance(ev, list) else 1}), mimetype='application/json')\n"
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("on_blob/__init__.py", code)
    assert requests.post(B + "/azure-data/functions/ingest-fn/api/zipdeploy", data=z.getvalue(), timeout=30).status_code == 200


def eg_subscription():
    """Event Grid system topic on the storage account, subscription with a webhook destination at the function."""
    from azure.mgmt.eventgrid import EventGridManagementClient
    c = arm(EventGridManagementClient, B)
    c.system_topics.begin_create_or_update(RG, "st-topic", {"location": LOC, "source": SCOPE, "topic_type": "Microsoft.Storage.StorageAccounts"}).result()
    s = c.system_topic_event_subscriptions.begin_create_or_update(RG, "st-topic", "blob-created", {"destination": {"endpoint_type": "WebHook", "properties": {"endpoint_url": B + "/azure-data/functions/ingest-fn/api/on_blob"}},
        "filter": {"included_event_types": ["Microsoft.Storage.BlobCreated"]}}).result()
    return s.provisioning_state


def eg_fires_on_blob():
    """Uploading a blob must raise Microsoft.Storage.BlobCreated to the subscription (delivery observable via the subscription's delivery status / function invocation log)."""
    S["bs"].get_blob_client("docs", "second.txt").upload_blob(b"water leak in lobby")
    time.sleep(3)
    r = requests.get(B + f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.EventGrid/systemTopics/st-topic/eventSubscriptions/blob-created/getDeliveryAttributes", params={"api-version": "2022-06-15"})
    from azure.mgmt.eventgrid import EventGridManagementClient
    c = arm(EventGridManagementClient, B)
    ev = [x for x in c.system_topic_event_subscriptions.list_by_system_topic(RG, "st-topic")]
    raise AssertionError("no observable BlobCreated delivery: checked subscription list only (%d subs); see delivery log step" % len(ev)) if not _delivered() else None


def _delivered():
    r = requests.get(B + "/api/azure/eventgrid/deliveries", timeout=5)
    return r.status_code == 200 and "blob-created" in r.text


def search_indexer():
    from azure.mgmt.search import SearchManagementClient
    c = arm(SearchManagementClient, B)
    c.services.begin_create_or_update(RG, "srch1", {"location": LOC, "sku": {"name": "basic"}}).result()
    key = c.admin_keys.get(RG, "srch1").primary_key
    base = f"{B}/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Search/searchServices/srch1"
    H = {"api-key": key, "Content-Type": "application/json"}; Q = {"api-version": "2024-07-01"}
    assert requests.put(base + "/indexes/kbp", params=Q, headers=H, json={"name": "kbp", "fields": [{"name": "id", "type": "Edm.String", "key": True}, {"name": "content", "type": "Edm.String", "searchable": True}]}).status_code in (200, 201)
    r = requests.put(base + "/datasources/ds1", params=Q, headers=H, json={"name": "ds1", "type": "azureblob", "credentials": {"connectionString": "UseDevelopmentStorage=true"}, "container": {"name": "docs"}})
    assert r.status_code in (200, 201), (r.status_code, r.text[:150])
    r = requests.put(base + "/indexers/ix1", params=Q, headers=H, json={"name": "ix1", "dataSourceName": "ds1", "targetIndexName": "kbp"})
    assert r.status_code in (200, 201), (r.status_code, r.text[:150])
    r = requests.post(base + "/indexers/ix1/run", params=Q, headers=H); assert r.status_code in (200, 202), (r.status_code, r.text[:150])
    time.sleep(2)
    st = requests.get(base + "/indexers/ix1/status", params=Q, headers=H).json()
    S["base"], S["H"], S["Q"] = base, H, Q
    return st.get("lastResult", {}).get("status") or st


def indexed_docs():
    r = requests.post(S["base"] + "/indexes/kbp/docs/search", params=S["Q"], headers=S["H"], json={"search": "manager"}).json()
    assert r.get("value"), r
    return len(r["value"])


def indexer_sdk():
    from azure.search.documents.indexes import SearchIndexerClient
    from azure.core.credentials import AzureKeyCredential
    ic = SearchIndexerClient(S["base"], AzureKeyCredential("k"))
    list(ic.get_indexers())


P.step("Blob upload + download (azure-storage-blob)", blob_upload)
P.step("Function App with a blob-event handler (zipdeploy)", fn_setup)
if P.step("Event Grid system topic + WebHook subscription to the function (azure-mgmt-eventgrid)", eg_subscription):
    P.step("blob upload raises BlobCreated and it is delivered to the function", eg_fires_on_blob)
if P.step("AI Search data source + indexer + run (REST, ARM-extension path)", search_indexer):
    P.step("indexer populated the index from the Blob container", indexed_docs)
P.step("SearchIndexerClient (azure-search-documents) against the same service", indexer_sdk)
P.finish()
