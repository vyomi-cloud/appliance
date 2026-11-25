"""RAG Studio backend for Azure AI Search: inspect API (chunks + retrieve-trace) and Azure OpenAI chat "on your data" through the ARM proxy.

Offline AND Nano use the same Python: run with PYTHONPATH=. (core/) or PYTHONPATH=wasm (vendored wasm/core copies).
Run: PYTHONPATH=. python3 tests/conformance/test_azure_rag_studio.py"""
import json
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
from core.azure_blob_core import AzureBlobStore
from core import azure_blob_core as blob
from core import azure_search_core as sc
from core import llm_core as llm


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    llm.set_backend(lambda m, sy, mt, t, st: {"text": "Per [doc1] the answer. SEEN:" + str((sy or "").count("[doc")), "finish_reason": "stop"})
    a = AzureArm()
    a.blob_store = store = AzureBlobStore()
    h = lambda m, p, b=None, q=None, v="2023-11-01": a.handle(m, p, dict({"api-version": v}, **(q or {})), b)
    h("PUT", f"/subscriptions/{S}/resourceGroups/r", {"location": "eastus"})
    base = f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.Search/searchServices"
    h("PUT", f"{base}/rsvc", {"location": "eastus", "sku": {"name": "standard"}})
    ix, sk, ds, ixr = (f"{base}/rsvc/{x}" for x in ("indexes", "skillsets", "datasources", "indexers"))
    VS = {"algorithms": [{"name": "hnsw1", "kind": "hnsw"}], "vectorizers": [{"name": "aoai", "kind": "azureOpenAI", "azureOpenAIParameters": {"resourceUri": "https://x.openai.azure.com", "deploymentId": "embed", "modelName": "text-embedding-3-small"}}],
          "profiles": [{"name": "p1", "algorithm": "hnsw1", "vectorizer": "aoai"}]}
    h("PUT", f"{ix}/chunks", {"fields": [{"name": "chunk_id", "type": "Edm.String", "key": True}, {"name": "parent_id", "type": "Edm.String", "filterable": True}, {"name": "title", "type": "Edm.String", "searchable": True, "filterable": True},
                                          {"name": "chunk", "type": "Edm.String", "searchable": True}, {"name": "text_vector", "type": "Collection(Edm.Single)", "dimensions": 16, "vectorSearchProfile": "p1"}],
                               "vectorSearch": VS, "semantic": {"defaultConfiguration": "sem", "configurations": [{"name": "sem", "prioritizedFields": {"titleField": {"fieldName": "title"}, "prioritizedContentFields": [{"fieldName": "chunk"}]}}]}})
    h("PUT", f"{ix}/parents", {"fields": [{"name": "doc_id", "type": "Edm.String", "key": True}, {"name": "metadata_storage_name", "type": "Edm.String", "searchable": True}]})
    skillset = {"skills": [
        {"@odata.type": "#Microsoft.Skills.Text.SplitSkill", "name": "split", "textSplitMode": "pages", "maximumPageLength": 300, "pageOverlapLength": 30, "context": "/document",
         "inputs": [{"name": "text", "source": "/document/content"}], "outputs": [{"name": "textItems", "targetName": "pages"}]},
        {"@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill", "name": "emb", "context": "/document/pages/*", "resourceUri": "https://x.openai.azure.com", "deploymentId": "embed", "modelName": "text-embedding-3-small", "dimensions": 16,
         "inputs": [{"name": "text", "source": "/document/pages/*"}], "outputs": [{"name": "embedding", "targetName": "text_vector"}]}],
        "indexProjections": {"selectors": [{"targetIndexName": "chunks", "parentKeyFieldName": "parent_id", "sourceContext": "/document/pages/*",
                                            "mappings": [{"name": "chunk", "source": "/document/pages/*"}, {"name": "text_vector", "source": "/document/pages/*/text_vector"}, {"name": "title", "source": "/document/metadata_storage_name"}]}],
                             "parameters": {"projectionMode": "skipIndexingParentDocuments"}}}
    _check("create skillset", h("PUT", f"{sk}/sksvc", skillset)["status"] == 201)
    store.create_container("acct/kb")
    boiler = " ".join(f"Boiler rule {i}: if boiler pressure exceeds 30 psi shut the feed valve and call the plant engineer." for i in range(6))
    leak = " ".join(f"Leak note {i}: report a water leak in the lobby to facilities immediately." for i in range(6))
    for n, t in (("boiler.txt", boiler), ("leak.txt", leak)):
        blob.dispatch(store, "PUT", f"/kb/{n}", {}, {"x-ms-blob-type": "BlockBlob", "content-type": "text/plain"}, t.encode(), account="acct")
    h("PUT", f"{ds}/blobds", {"type": "azureblob", "credentials": {"connectionString": "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=x"}, "container": {"name": "kb"}})
    h("PUT", f"{ixr}/ix1", {"dataSourceName": "blobds", "targetIndexName": "parents", "skillsetName": "sksvc", "parameters": {"configuration": {"parsingMode": "text"}}})
    h("POST", f"{ixr}/ix1/run")
    st = h("GET", f"{ixr}/ix1/status")["body"]["lastResult"]
    _check("indexer (split + embedding skill + projections) ran", st["status"] == "success" and st["itemsFailed"] == 0)

    # ---- inspect: chunks (ARM-extension path, works offline and in Nano)
    r = h("GET", f"{ix}/chunks/chunks", None, {"vectors": "true"})
    b = r["body"]
    _check("chunks: shape count/dimensions/chunks[]", r["status"] == 200 and b["count"] >= 4 and b["dimensions"] == 16 and len(b["chunks"]) == b["count"])
    c0 = b["chunks"][0]
    _check("chunk row fields", all(k in c0 for k in ("id", "documentUri", "text", "tokenCount", "metadata", "section", "pii", "projection2d", "vector")) and len(c0["vector"]) == 16 and len(c0["projection2d"]) == 2)
    _check("vectors omitted unless asked", h("GET", f"{ix}/chunks/chunks")["body"]["chunks"][0]["vector"] is None)
    _check("chunk text is a page of the source", c0["text"][:30] in boiler or c0["text"][:30] in leak)

    # ---- inspect: retrieve-trace + plain search unchanged
    body = {"search": "boiler pressure shut valve", "vectorQueries": [{"kind": "text", "text": "boiler pressure shut valve", "fields": "text_vector", "k": 20}], "queryType": "semantic", "semanticConfiguration": "sem", "$top": 3, "$select": "chunk_id,chunk"}
    plain = h("POST", f"{ix}/chunks/docs/search", body)["body"]
    tr = h("POST", f"{ix}/chunks/retrieve-trace", body)
    _check("trace 200", tr["status"] == 200)
    t = tr["body"]["trace"]
    cand = {c["chunkId"]: c for c in t["candidates"]}
    _check("trace has every stage", t["searchType"] == "hybrid" and t["semanticRanker"] == "approximation" and all(any(c[k] is not None for c in cand.values()) for k in ("keyword_rank", "vector_rank", "fused_rank", "reranker_score", "final_rank")))
    _check("final order equals plain search (output unchanged)", t["finalOrder"] == [d["chunk_id"] for d in plain["value"]] and [d["chunk_id"] for d in tr["body"]["value"]] == t["finalOrder"])
    _check("plain search has no trace keys", "trace" not in plain and "candidates" not in json.dumps(plain))
    top = cand[t["finalOrder"][0]]
    _check("top result is a boiler chunk with rank 1", top["final_rank"] == 1 and "oiler" in top["text"])
    kw = h("POST", f"{ix}/chunks/retrieve-trace", {"search": "water leak lobby", "$top": 2})["body"]["trace"]
    _check("keyword-only trace", kw["searchType"] == "keyword" and kw["candidates"][0]["vector_rank"] is None and kw["candidates"][0]["keyword_rank"] == 1)
    _check("trace with $filter honours it", h("POST", f"{ix}/chunks/retrieve-trace", {"search": "boiler", "$filter": "title eq 'leak.txt'"})["body"]["value"] == [])
    _check("inspect: unknown index 404", h("GET", f"{ix}/nope/chunks")["status"] == 404)

    # ---- inspect_dispatch (the /_vyomi/azure/search/{svc}/... route)
    svc = next(s for s in sc._services(a.state))
    adm = {"api-key": svc["_admin"]["primary"]}
    d = sc.inspect_dispatch(a.state, "rsvc", "GET", "/indexes/chunks/chunks", {"vectors": "true"}, b"", headers=adm)
    _check("inspect_dispatch chunks == ARM path", d["status"] == 200 and d["body"]["count"] == b["count"])
    d = sc.inspect_dispatch(a.state, "rsvc", "POST", "/indexes/chunks/retrieve-trace", {}, json.dumps(body).encode(), headers=adm)
    _check("inspect_dispatch retrieve-trace", d["status"] == 200 and d["body"]["trace"]["finalOrder"] == t["finalOrder"])
    _check("inspect_dispatch needs admin key", sc.inspect_dispatch(a.state, "rsvc", "GET", "/indexes/chunks/chunks", {}, b"", headers={})["status"] == 403)
    _check("inspect_dispatch unknown service", sc.inspect_dispatch(a.state, "zz", "GET", "/indexes/chunks/chunks", {}, b"", headers=adm)["status"] == 404)

    # ---- chat "on your data" via the ARM proxy (Azure OpenAI account + deployment)
    cog = f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.CognitiveServices/accounts/aoai1"
    h("PUT", cog, {"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {"customSubDomainName": "aoai1"}}, v="2023-05-01")
    h("PUT", f"{cog}/deployments/chat", {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-11-20"}}}, v="2023-05-01")
    ep = f"https://rsvc.search.windows.net/"
    chat = {"messages": [{"role": "user", "content": "What is the boiler pressure rule?"}],
            "data_sources": [{"type": "azure_search", "parameters": {"endpoint": ep, "index_name": "chunks", "authentication": {"type": "api_key", "key": svc["_admin"]["primary"]}, "top_n_documents": 3,
                                                                    "query_type": "vector_semantic_hybrid", "semantic_configuration": "sem", "in_scope": True,
                                                                    "fields_mapping": {"content_fields": ["chunk"], "title_field": "title", "vector_fields": ["text_vector"]}}}]}
    r = h("POST", f"{cog}/openai/deployments/chat/chat/completions", chat, v="2024-10-21")
    _check("on-your-data 200 via ARM proxy", r["status"] == 200)
    m = r["body"]["choices"][0]["message"]
    cits = m["context"]["citations"]
    _check("citations shape + grounded answer", len(cits) == 3 and all(k in cits[0] for k in ("content", "title", "url", "filepath", "chunk_id")) and "oiler" in cits[0]["content"] and "SEEN:5" in m["content"])   # 3 numbered docs + 2 [docN] mentions in the instruction
    _check("intent present", json.loads(m["context"]["intent"]) == ["What is the boiler pressure rule?"])
    bad = dict(chat, data_sources=[dict(chat["data_sources"][0], parameters=dict(chat["data_sources"][0]["parameters"], index_name="nope"))])
    _check("unknown index -> 400", h("POST", f"{cog}/openai/deployments/chat/chat/completions", bad, v="2024-10-21")["status"] == 400)
    print("OK")


run()
