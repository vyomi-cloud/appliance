"""C12: knowledge processing pipeline: Blob upload -> Event Grid (BlobCreated) -> Function -> AI Search indexer run -> the document becomes searchable.
Also the initial load: a blob data source + indexer fill the facilities-kb index from the docs container."""
import os, time, uuid
from ..runtime import NAMES, LANE, RG, LOC, STORAGE, ACCOUNT_KEY, fixture_dir
from .. import deploy, search

INGEST_APP = "facilities-ingest"


def _wait(fn, secs=40, every=1.0):
    t0 = time.time()
    last = None
    while time.time() - t0 < secs:
        last = fn()
        if last:
            return last
        time.sleep(every)
    return last


def run(ctx):
    ctx.ensure_rg()
    docs = fixture_dir() + "/docs"

    def upload():
        from azure.mgmt.storage import StorageManagementClient
        ctx.arm(StorageManagementClient).storage_accounts.begin_create(RG, NAMES["docs_account"], {"location": LOC, "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}).result()
        bs = ctx.blob()
        try:
            bs.create_container(NAMES["container"])
        except Exception as e:
            if "ContainerAlreadyExists" not in str(e):
                raise
        for f in sorted(os.listdir(docs)):
            bs.get_blob_client(NAMES["container"], f).upload_blob(open(os.path.join(docs, f), "rb").read(), overwrite=True)
        names = [b.name for b in bs.get_container_client(NAMES["container"]).list_blobs()]
        assert len(names) == 4, names
        assert bs.get_blob_client(NAMES["container"], "boiler-sop.md").download_blob().readall().startswith(b"# SOP-101")
        return f"4 documents uploaded to container {NAMES['container']} (azure-storage-blob) and read back"
    ctx.step("blob storage: create container + upload the four SOP documents (azure-storage-blob)", upload)

    def index_and_indexer():
        from azure.search.documents.indexes.models import (FieldMapping, SearchIndexer, SearchIndexerDataContainer, SearchIndexerDataSourceConnection)
        search.ensure_search(ctx)
        search.index_client(ctx).create_or_update_index(search.kb_index())
        ic = search.indexer_client(ctx)
        cs = f"DefaultEndpointsProtocol=http;AccountName={STORAGE};AccountKey={ACCOUNT_KEY};BlobEndpoint={ctx.http}/{STORAGE};"
        ic.create_or_update_data_source_connection(SearchIndexerDataSourceConnection(name="docs-blob", type="azureblob", connection_string=cs, container=SearchIndexerDataContainer(name=NAMES["container"])))
        ic.create_or_update_indexer(SearchIndexer(name="docs-indexer", data_source_name="docs-blob", target_index_name=NAMES["index"], field_mappings=[
            FieldMapping(source_field_name="metadata_storage_path", target_field_name="id", mapping_function={"name": "base64Encode"}),
            FieldMapping(source_field_name="metadata_storage_name", target_field_name="source"), FieldMapping(source_field_name="metadata_storage_name", target_field_name="title")]))
        ic.run_indexer("docs-indexer")

        def done():
            st = ic.get_indexer_status("docs-indexer")
            return st.last_result and str(st.last_result.status).lower().endswith("success")
        assert _wait(done, 40), "the indexer did not finish successfully"
        return "data source (azureblob) + indexer created and run with SearchIndexerClient: status success"
    ctx.step("ai search: blob data source + indexer fill facilities-kb from the container (SearchIndexerClient)", index_and_indexer, lane=LANE["messaging"])

    def searchable():
        rows = list(search.search_client(ctx).search(search_text="boiler pressure", select=["id", "source", "content"], top=3))
        assert rows and "boiler" in rows[0]["source"].lower(), [(r["source"]) for r in rows]
        n = len(list(search.search_client(ctx).search(search_text="*", top=50)))
        assert n == 4, f"{n} documents in the index, expected 4"
        return f"4 documents indexed; 'boiler pressure' -> {rows[0]['source']}"
    ctx.step("ai search: the initial load made all four documents searchable", searchable, lane=LANE["messaging"])

    def func():
        deploy.create_function_app(ctx, INGEST_APP, {"on-blob": "ingest_docs"})
        return f"function app {INGEST_APP} with on-blob (runs the indexer on BlobCreated)"
    ctx.step("function app: ingest function that runs the indexer (ARM + zip deploy)", func, lane=LANE["runtime"])

    def subscribe():
        from azure.mgmt.eventgrid import EventGridManagementClient
        c = ctx.arm(EventGridManagementClient)
        scope = ctx.rid("Microsoft.Storage", "storageAccounts", NAMES["docs_account"])
        c.system_topics.begin_create_or_update(RG, "facilitiesdocs-topic", {"location": LOC, "source": scope, "topic_type": "Microsoft.Storage.StorageAccounts"}).result()
        s = c.system_topic_event_subscriptions.begin_create_or_update(RG, "facilitiesdocs-topic", "blob-created", {"destination": {"endpoint_type": "WebHook", "properties": {
            "endpoint_url": f"{ctx.http}/azure-data/functions/{INGEST_APP}/api/on-blob"}}, "filter": {"included_event_types": ["Microsoft.Storage.BlobCreated"]}}).result()
        ctx.state["eg_ready"] = True
        return f"system topic on storage account {NAMES['docs_account']} + WebHook subscription blob-created -> function ({s.provisioning_state})"
    if ctx.state.get("search_ready"):
        ctx.step("event grid: system topic on the storage account + WebHook subscription to the function (azure-mgmt-eventgrid)", subscribe, lane=LANE["messaging"])

    def reingest():
        word = "zebrafish" + uuid.uuid4().hex[:6]
        ctx.blob().get_blob_client(NAMES["container"], "water-leak-sop.md").upload_blob(f"# SOP-205 Water leak\nReport a {word} water leak in the lobby to facilities immediately.".encode(), overwrite=True)
        sc = search.search_client(ctx)

        def found():
            return [r["source"] for r in sc.search(search_text=word, select=["source"], top=3)]
        got = _wait(found, 45)
        assert got and got[0] == "water-leak-sop.md", f"the new document never became searchable after the upload (event grid -> function -> indexer): {got}"
        return f"upload -> BlobCreated -> function -> indexer: '{word}' searchable in {got[0]}"
    if ctx.state.get("eg_ready"):
        ctx.step("pipeline: a newly uploaded blob is re-ingested automatically (BlobCreated -> function -> indexer -> searchable)", reingest, lane=LANE["messaging"])
