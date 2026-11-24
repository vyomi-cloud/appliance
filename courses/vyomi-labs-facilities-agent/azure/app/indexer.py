import time
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexerClient
from azure.search.documents.indexes.models import FieldMapping, SearchIndexer, SearchIndexerDataContainer, SearchIndexerDataSourceConnection
from azlab import HTTP_ENDPOINT
from azdata import search_endpoint, search_key, storage_cs, INDEX

ic = SearchIndexerClient(search_endpoint(), AzureKeyCredential(search_key()))
ic.create_or_update_data_source_connection(SearchIndexerDataSourceConnection(
    name="docs-blob", type="azureblob", connection_string=storage_cs("Blob", HTTP_ENDPOINT, "http"), container=SearchIndexerDataContainer(name="docs")))
ic.create_or_update_indexer(SearchIndexer(name="docs-indexer", data_source_name="docs-blob", target_index_name=INDEX, field_mappings=[
    FieldMapping(source_field_name="metadata_storage_path", target_field_name="id", mapping_function={"name": "base64Encode"}),
    FieldMapping(source_field_name="metadata_storage_name", target_field_name="source"),
    FieldMapping(source_field_name="metadata_storage_name", target_field_name="title")]))
ic.run_indexer("docs-indexer")
for _ in range(40):
    last = ic.get_indexer_status("docs-indexer").last_result
    if last and str(last.status).lower().endswith("success"):
        break
    time.sleep(1)
print("indexer last run:", str(last.status).split(".")[-1].lower(), "| documents:", last.item_count)
