"""Azure AI Search plumbing shared by components 6 and 12: the service (ARM), admin key, the facilities-kb index (text + 1536-d vector + semantic configuration)."""
from .runtime import NAMES, RG, LOC

DIMS = 1536


def ensure_search(ctx):
    if ctx.state.get("search_ready"):
        return
    from azure.mgmt.search import SearchManagementClient
    ctx.arm(SearchManagementClient).services.begin_create_or_update(RG, NAMES["search"], {"location": LOC, "sku": {"name": "basic"}}).result()
    ep = ctx.search_endpoint()
    ctx.state["search_endpoint_http"] = ep.replace(ctx.endpoint, ctx.http, 1) if ctx.http != ctx.endpoint else ep
    ctx.state["search_key"] = ctx.search_key()
    ctx.state["search_ready"] = True


def index_client(ctx):
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient
    return SearchIndexClient(ctx.search_endpoint(), AzureKeyCredential(ctx.state["search_key"]))


def indexer_client(ctx):
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexerClient
    return SearchIndexerClient(ctx.search_endpoint(), AzureKeyCredential(ctx.state["search_key"]))


def search_client(ctx):
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    return SearchClient(ctx.search_endpoint(), NAMES["index"], AzureKeyCredential(ctx.state["search_key"]))


def kb_index():
    from azure.search.documents.indexes.models import (HnswAlgorithmConfiguration, SearchField, SearchFieldDataType, SearchIndex, SearchableField, SemanticConfiguration,
                                                       SemanticField, SemanticPrioritizedFields, SemanticSearch, SimpleField, VectorSearch, VectorSearchProfile)
    fields = [SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True), SimpleField(name="source", type=SearchFieldDataType.String, filterable=True),
              SearchableField(name="title", type=SearchFieldDataType.String), SearchableField(name="content", type=SearchFieldDataType.String),
              SearchField(name="content_vector", type=SearchFieldDataType.Collection(SearchFieldDataType.Single), searchable=True, vector_search_dimensions=DIMS, vector_search_profile_name="vp")]
    return SearchIndex(name=NAMES["index"], fields=fields,
                       vector_search=VectorSearch(algorithms=[HnswAlgorithmConfiguration(name="h")], profiles=[VectorSearchProfile(name="vp", algorithm_configuration_name="h")]),
                       semantic_search=SemanticSearch(configurations=[SemanticConfiguration(name="sem", prioritized_fields=SemanticPrioritizedFields(
                           title_field=SemanticField(field_name="title"), content_fields=[SemanticField(field_name="content")]))]))
