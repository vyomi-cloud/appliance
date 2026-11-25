from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azlab import aoai, EMBED
from azdata import search_endpoint, search_key, INDEX
import rag_design

_sc = SearchClient(search_endpoint(), INDEX, AzureKeyCredential(search_key()))


def kb_search(query, mode="text", top=None):
    top = top or rag_design.top_k()                      # your design: how many passages
    vector = None
    if mode in ("vector", "hybrid"):
        dims = {"dimensions": rag_design.dimensions()} if rag_design.dimensions() else {}     # your design: vector size
        emb = aoai().embeddings.create(model=EMBED, input=[query], **dims).data[0].embedding
        vector = [VectorizedQuery(vector=emb, k_nearest_neighbors=top, fields="content_vector")]
    kw = {"query_type": "semantic", "semantic_configuration_name": "sem"} if mode == "semantic" else {}
    rows = _sc.search(search_text=None if mode == "vector" else query, vector_queries=vector, select=["id", "source", "title", "content"], top=top, **kw)
    return [{"source": r["source"], "text": r["content"], "score": r["@search.score"], "reranker": r.get("@search.reranker_score")} for r in rows]
