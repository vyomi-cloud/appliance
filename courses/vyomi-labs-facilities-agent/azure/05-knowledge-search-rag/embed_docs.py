from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azlab import aoai, EMBED
from azdata import search_endpoint, search_key, INDEX

sc = SearchClient(search_endpoint(), INDEX, AzureKeyCredential(search_key()))
rows = list(sc.search(search_text="*", select=["id", "source", "content"], top=50))
vectors = [d.embedding for d in aoai().embeddings.create(model=EMBED, input=[r["content"] for r in rows]).data]
results = sc.merge_documents([{"id": r["id"], "content_vector": v} for r, v in zip(rows, vectors)])
print("embedded and merged", sum(1 for r in results if r.succeeded), "documents")
