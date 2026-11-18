"""C6: knowledge search layer: Vertex RAG Engine retrieveContexts (top-k, source URIs for citations); Vertex AI Search over the same text."""
from ..runtime import NAMES, LANE, Blocked


def run(ctx):
    corpus = ctx.state.get("rag_corpus")
    if not corpus:
        ctx.step("retrieveContexts", lambda: (_ for _ in ()).throw(Blocked("knowledge pipeline", "no RAG corpus was created (component 12)")))
        return
    svc = ctx.aiplatform("VertexRagServiceClient")

    def search(q, k=3):
        r = svc.retrieve_contexts(request={"parent": ctx.parent, "query": {"text": q, "rag_retrieval_config": {"top_k": k}},
                                           "vertex_rag_store": {"rag_resources": [{"rag_corpus": corpus}]}})
        return list(r.contexts.contexts)

    def boiler():
        r = search("What should I do when boiler pressure exceeds 30 psi?")
        assert r, "no results"
        assert "boiler-sop" in r[0].source_uri, f"top hit was {r[0].source_uri or r[0].text[:60]}"
        ctx.state["citations"] = [(x.source_uri, x.text) for x in r]
        return f"top hit {r[0].source_uri} score={r[0].score}"
    ctx.step("vertex rag engine: retrieveContexts ranks the boiler SOP first", boiler)

    def hvac():
        r = search("AHU-7 supply air temperature drift chilled water valve")
        assert r and "hvac" in r[0].source_uri, f"top hit {r[0].source_uri if r else None}"
        return f"top hit {r[0].source_uri}"
    ctx.step("vertex rag engine: retrieveContexts ranks the HVAC manual first for an AHU question", hvac)

    def cited():
        r = search("fire alarm evacuation")
        assert r and all(x.text and x.source_uri for x in r), "result without text or source uri"
        return f"{len(r)} contexts each with text + gs:// source"
    ctx.step("retrieved contexts carry source URIs (needed for citations)", cited)

    def vais():
        from google.cloud import discoveryengine_v1 as de
        from google.api_core.client_options import ClientOptions
        ds = ctx.rest(de.DataStoreServiceClient)
        coll = f"projects/{ctx.project}/locations/global/collections/default_collection"
        ds.create_data_store(request={"parent": coll, "data_store_id": "facilities-docs", "data_store": de.DataStore(
            display_name="facilities-docs", industry_vertical=de.IndustryVertical.GENERIC, content_config=de.DataStore.ContentConfig.CONTENT_REQUIRED)}).result(timeout=60)
        doc = ctx.state["citations"][0][1]
        ctx.rest(de.DocumentServiceClient).import_documents(request={"parent": f"{coll}/dataStores/facilities-docs/branches/default_branch", "inline_source": {"documents": [
            {"id": "boiler", "struct_data": {"title": "Boiler SOP", "body": doc}}]}}).result(timeout=60)
        r = ctx.rest(de.SearchServiceClient).search(request={"serving_config": f"{coll}/dataStores/facilities-docs/servingConfigs/default_search", "query": "boiler pressure"})
        hits = list(r)
        assert hits, "Vertex AI Search returned no results"
        return f"Vertex AI Search (Discovery Engine) returned {len(hits)} result(s)"
    if ctx.state.get("citations"):
        ctx.step("vertex ai search: data store + import + search over the same SOP", vais)
