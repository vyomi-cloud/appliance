from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azlab import aoai, EMBED
from azdata import search_endpoint, search_key, INDEX

_sc = SearchClient(search_endpoint(), INDEX, AzureKeyCredential(search_key()))


def kb_search(query, mode="text", top=3):
    vector = None
    if mode in ("vector", "hybrid"):
        emb = aoai().embeddings.create(model=EMBED, input=[query]).data[0].embedding
        vector = [VectorizedQuery(vector=emb, k_nearest_neighbors=top, fields="content_vector")]
    kw = {"query_type": "semantic", "semantic_configuration_name": "sem"} if mode == "semantic" else {}
    rows = _sc.search(search_text=None if mode == "vector" else query, vector_queries=vector, select=["id", "source", "title", "content"], top=top, **kw)
    return [{"source": r["source"], "text": r["content"], "score": r["@search.score"], "reranker": r.get("@search.reranker_score")} for r in rows]
