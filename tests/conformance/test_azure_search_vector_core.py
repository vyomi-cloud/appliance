"""Azure AI Search vector fields, vector/hybrid queries, skillsets and integrated vectorization (SplitSkill + embedding skill
+ index projections) over the local embedding seam.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_azure_search_vector_core.py
"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
from core.azure_blob_core import AzureBlobStore
from core import llm_core as llm


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    llm.set_backend()
    a = AzureArm()
    a.blob_store = store = AzureBlobStore()
    av = {"api-version": "2023-11-01"}
    h = lambda m, p, b=None, q=None: a.handle(m, p, dict(av, **(q or {})), b)
    h("PUT", f"/subscriptions/{S}/resourceGroups/r", {"location": "eastus"})
    base = f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.Search/searchServices"
    h("PUT", f"{base}/vsvc", {"location": "eastus", "sku": {"name": "standard"}})
    ix, sk, ds, ixr = (f"{base}/vsvc/{x}" for x in ("indexes", "skillsets", "datasources", "indexers"))
    VS = {"algorithms": [{"name": "hnsw1", "kind": "hnsw"}], "vectorizers": [{"name": "aoai", "kind": "azureOpenAI", "azureOpenAIParameters": {"resourceUri": "https://x.openai.azure.com", "deploymentId": "emb", "modelName": "text-embedding-3-small"}}],
          "profiles": [{"name": "p1", "algorithm": "hnsw1", "vectorizer": "aoai"}, {"name": "p2", "algorithm": "hnsw1"}]}
    flds = lambda prof: [{"name": "id", "type": "Edm.String", "key": True}, {"name": "title", "type": "Edm.String", "searchable": True},
                         {"name": "vec", "type": "Collection(Edm.Single)", "dimensions": 8, "vectorSearchProfile": prof}]
    _check("vector field needs a defined profile", h("PUT", f"{ix}/bad", {"fields": flds("nope"), "vectorSearch": VS})["status"] == 400)
    _check("vector field needs dimensions", h("PUT", f"{ix}/bad", {"fields": [{"name": "id", "type": "Edm.String", "key": True}, {"name": "v", "type": "Collection(Edm.Single)", "vectorSearchProfile": "p1"}], "vectorSearch": VS})["status"] == 400)
    r = h("PUT", f"{ix}/docs1", {"fields": flds("p1"), "vectorSearch": VS})
    _check("create vector index", r["status"] == 201 and r["body"]["fields"][2]["dimensions"] == 8 and r["body"]["vectorSearch"]["profiles"][0]["name"] == "p1")
    up = lambda docs: h("POST", f"{ix}/docs1/docs/index", {"value": [dict(d, **{"@search.action": "upload"}) for d in docs]})
    _check("wrong dimension rejected", up([{"id": "x", "title": "t", "vec": [1, 2, 3]}])["status"] == 207)
    e = [[1, 0, 0, 0, 0, 0, 0, 0], [0.9, 0.1, 0, 0, 0, 0, 0, 0], [0, 0, 1, 0, 0, 0, 0, 0]]
    _check("upload vectors", up([{"id": "a", "title": "red apple", "vec": e[0]}, {"id": "b", "title": "green apple", "vec": e[1]}, {"id": "c", "title": "blue car", "vec": e[2]}])["status"] == 200)
    s = lambda body: h("POST", f"{ix}/docs1/docs/search", body)
    r = s({"vectorQueries": [{"kind": "vector", "vector": e[0], "fields": "vec", "k": 2}], "select": "id", "$select": "id"})
    _check("pure vector: nearest first, cosine score", [d["id"] for d in r["body"]["value"]] == ["a", "b"] and abs(r["body"]["value"][0]["@search.score"] - 1.0) < 1e-6)
    _check("query vector dimension checked", s({"vectorQueries": [{"kind": "vector", "vector": [1, 2], "fields": "vec"}]})["status"] == 400)
    _check("text vector query is embedded through the profile vectorizer", s({"vectorQueries": [{"kind": "text", "text": "x", "fields": "vec"}]})["status"] == 200)
    r = s({"search": "car", "vectorQueries": [{"kind": "vector", "vector": e[0], "fields": "vec", "k": 3}], "$select": "id"})
    _check("hybrid fuses keyword + vector (RRF)", [d["id"] for d in r["body"]["value"]][0] in ("a", "c") and len(r["body"]["value"]) == 3 and r["body"]["value"][0]["@search.score"] < 0.1)
    r = s({"vectorQueries": [{"kind": "vector", "vector": e[0], "fields": "vec"}], "filter": "title ne 'red apple'", "$select": "id"})
    _check("filter applies before vector ranking", [d["id"] for d in r["body"]["value"]][0] == "b")

    # ---- integrated vectorization: blob -> split -> embed -> chunk index
    h("PUT", f"{ix}/chunks", {"fields": [{"name": "chunk_id", "type": "Edm.String", "key": True}, {"name": "parent_id", "type": "Edm.String", "filterable": True}, {"name": "chunk", "type": "Edm.String", "searchable": True},
                                           {"name": "text_vector", "type": "Collection(Edm.Single)", "dimensions": 16, "vectorSearchProfile": "p1"}], "vectorSearch": VS})
    h("PUT", f"{ix}/parents", {"fields": [{"name": "doc_id", "type": "Edm.String", "key": True}, {"name": "metadata_storage_name", "type": "Edm.String", "searchable": True}]})
    skillset = {"skills": [
        {"@odata.type": "#Microsoft.Skills.Text.SplitSkill", "name": "split", "textSplitMode": "pages", "maximumPageLength": 300, "pageOverlapLength": 30, "context": "/document",
         "inputs": [{"name": "text", "source": "/document/content"}], "outputs": [{"name": "textItems", "targetName": "pages"}]},
        {"@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill", "name": "emb", "context": "/document/pages/*", "resourceUri": "https://x.openai.azure.com", "deploymentId": "emb", "modelName": "text-embedding-3-small", "dimensions": 16,
         "inputs": [{"name": "text", "source": "/document/pages/*"}], "outputs": [{"name": "embedding", "targetName": "text_vector"}]}],
        "indexProjections": {"selectors": [{"targetIndexName": "chunks", "parentKeyFieldName": "parent_id", "sourceContext": "/document/pages/*",
                                            "mappings": [{"name": "chunk", "source": "/document/pages/*"}, {"name": "text_vector", "source": "/document/pages/*/text_vector"}]}],
                             "parameters": {"projectionMode": "skipIndexingParentDocuments"}}}
    _check("bad skillset rejected", h("PUT", f"{sk}/bad", {"skills": [{"@odata.type": "nope"}]})["status"] == 400)
    _check("split overlap validated", h("PUT", f"{sk}/bad", {"skills": [dict(skillset["skills"][0], pageOverlapLength=400)]})["status"] == 400)
    _check("create skillset", h("PUT", f"{sk}/sksvc", skillset)["status"] == 201)
    store.create_container("acct/kb")
    long_text = " ".join(f"Sentence number {i} talks about apples and oranges in the orchard." for i in range(30))
    from core import azure_blob_core as blob
    blob.dispatch(store, "PUT", "/kb/guide.txt", {}, {"x-ms-blob-type": "BlockBlob", "content-type": "text/plain"}, long_text.encode(), account="acct")
    h("PUT", f"{ds}/blobds", {"type": "azureblob", "credentials": {"connectionString": "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=x"}, "container": {"name": "kb"}})
    _check("indexer rejects unknown skillset", h("PUT", f"{ixr}/ix0", {"dataSourceName": "blobds", "targetIndexName": "parents", "skillsetName": "missing"})["status"] == 400)
    _check("create indexer with skillset", h("PUT", f"{ixr}/ix1", {"dataSourceName": "blobds", "targetIndexName": "parents", "skillsetName": "sksvc", "parameters": {"configuration": {"parsingMode": "text"}}})["status"] == 201)
    _check("skillset in use cannot be deleted", h("DELETE", f"{sk}/sksvc")["status"] == 409)
    h("POST", f"{ixr}/ix1/run")
    st = h("GET", f"{ixr}/ix1/status")["body"]["lastResult"]
    _check("indexer ran with chunk projections", st["status"] == "success" and st["itemsProcessed"] >= 2 and st["itemsFailed"] == 0)
    cnt = h("GET", f"{ix}/chunks/docs/count")["body"]
    _check("chunks written to the target index, parents skipped", cnt >= 2 and h("GET", f"{ix}/parents/docs/count")["body"] == 0)
    r = h("POST", f"{ix}/chunks/docs/search", {"vectorQueries": [{"kind": "text", "text": "apples and oranges in the orchard", "fields": "text_vector", "k": 3}], "$select": "chunk_id,parent_id,chunk"})
    _check("integrated vectorization: text query embedded by the profile's vectorizer", r["status"] == 200 and len(r["body"]["value"]) == 3 and r["body"]["value"][0]["parent_id"])
    first = r["body"]["value"][0]
    _check("chunk is a slice of the source text", first["chunk"] in long_text.replace("\n", " ") or first["chunk"][:40] in long_text)
    h("PUT", f"{sk}/sk2", {"skills": [{"@odata.type": "#Microsoft.Skills.Vision.OcrSkill", "name": "ocr", "inputs": [{"name": "image", "source": "/document/x"}], "outputs": [{"name": "text"}]}]})
    h("PUT", f"{ixr}/ix2", {"dataSourceName": "blobds", "targetIndexName": "parents", "skillsetName": "sk2", "parameters": {"configuration": {"parsingMode": "text"}}})
    h("POST", f"{ixr}/ix2/run")
    st2 = h("GET", f"{ixr}/ix2/status")["body"]["lastResult"]
    _check("unsupported skill fails the indexer naming the skill", st2["status"] != "success" and "OcrSkill" in str(st2["errors"]))
    print("OK")


run()
