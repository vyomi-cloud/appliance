from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (HnswAlgorithmConfiguration, SearchField, SearchFieldDataType, SearchIndex, SearchableField,
                                                   SemanticConfiguration, SemanticField, SemanticPrioritizedFields, SemanticSearch, SimpleField,
                                                   VectorSearch, VectorSearchProfile)
from azdata import search_endpoint, search_key, INDEX
from vymodels import embed
import rag_design

# the vector size: your design when it sets one, otherwise that of the embedding model this simulator hosts (it differs between Nano and a Mesh)
DIMS = rag_design.dimensions() or len(embed("dimension probe"))


def kb_index():
    fields = [SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
              SimpleField(name="source", type=SearchFieldDataType.String, filterable=True),
              SearchableField(name="title", type=SearchFieldDataType.String),
              SearchableField(name="content", type=SearchFieldDataType.String),
              SearchField(name="content_vector", type=SearchFieldDataType.Collection(SearchFieldDataType.Single), searchable=True,
                          vector_search_dimensions=DIMS, vector_search_profile_name="vp")]
    return SearchIndex(name=INDEX, fields=fields,
                       vector_search=VectorSearch(algorithms=[HnswAlgorithmConfiguration(name="h")],
                                                  profiles=[VectorSearchProfile(name="vp", algorithm_configuration_name="h")]),
                       semantic_search=SemanticSearch(configurations=[SemanticConfiguration(name="sem", prioritized_fields=SemanticPrioritizedFields(
                           title_field=SemanticField(field_name="title"), content_fields=[SemanticField(field_name="content")]))]))


def index_client():
    return SearchIndexClient(search_endpoint(), AzureKeyCredential(search_key()))


if __name__ == "__main__":
    ic = index_client()
    ic.create_or_update_index(kb_index())
    print("index", INDEX, "fields:", [f.name for f in ic.get_index(INDEX).fields])
