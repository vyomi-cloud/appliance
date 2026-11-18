"""C6 Knowledge: Vertex RAG Engine (google-cloud-aiplatform gapic, REST): corpus, import from GCS, retrieveContexts; Vector Search index + findNeighbors; Vertex AI Search (Discovery Engine REST)."""
from _common import *

s = Step()
P = f"projects/{PROJECT}/locations/{LOC}"


def rag():
    from google.cloud import aiplatform_v1 as av
    data = rest_client(av.VertexRagDataServiceClient)
    s.rag_data = data
    corpus = data.create_rag_corpus(request={"parent": P, "rag_corpus": {"display_name": f"facilities-{TAG}"}}).result(timeout=60)
    s.corpus = corpus.name
    return corpus.name


def gcs_import():
    from google.cloud import aiplatform_v1 as av
    gcs = storage()
    b = gcs.create_bucket(f"kb-{TAG}")
    b.blob("sop/boiler.txt").upload_from_string(DOC.encode(), content_type="text/plain")
    op = s.rag_data.import_rag_files(request={"parent": s.corpus, "import_rag_files_config": {"gcs_source": {"uris": [f"gs://kb-{TAG}/sop/"]}}})
    res = op.result(timeout=120)
    files = list(s.rag_data.list_rag_files(request={"parent": s.corpus}))
    assert files, f"no RAG files after import ({res})"
    return f"{len(files)} rag file(s) imported from GCS"


def retrieve():
    from google.cloud import aiplatform_v1 as av
    svc = rest_client(av.VertexRagServiceClient)
    r = svc.retrieve_contexts(request={"parent": P, "query": {"text": "boiler pressure limit psi", "rag_retrieval_config": {"top_k": 2}},
                                       "vertex_rag_store": {"rag_resources": [{"rag_corpus": s.corpus}]}})
    ctx = list(r.contexts.contexts)
    assert ctx and "boiler" in ctx[0].text.lower(), r
    return f"{len(ctx)} contexts; top source_uri={ctx[0].source_uri}"


def vector():
    op = call("POST", f"/v1/{P}/indexes", {"displayName": "ix", "metadata": {"config": {"dimensions": 2, "distanceMeasureType": "DOT_PRODUCT_DISTANCE"}}})
    iname = op["response"]["name"] if "response" in op else op["metadata"]["genericMetadata"] and op["name"]
    call("POST", f"/v1/{iname}:upsertDatapoints", {"datapoints": [{"datapointId": "a", "featureVector": [1, 0]}, {"datapointId": "b", "featureVector": [0, 1]}]})
    ie = call("POST", f"/v1/{P}/indexEndpoints", {"displayName": "ie"})
    ien = ie["response"]["name"]
    call("POST", f"/v1/{ien}:deployIndex", {"deployedIndex": {"id": "dep1", "index": iname}})
    nn = call("POST", f"/v1/{ien}:findNeighbors", {"deployedIndexId": "dep1", "queries": [{"datapoint": {"featureVector": [1, 0]}, "neighborCount": 1}]})
    top = nn["nearestNeighbors"][0]["neighbors"][0]["datapoint"]["datapointId"]
    assert top == "a", nn
    return "findNeighbors top=a"


def vais():
    D = f"/v1/projects/{PROJECT}/locations/global/collections/default_collection"
    call("POST", D + "/dataStores", {"displayName": "docs", "industryVertical": "GENERIC", "contentConfig": "CONTENT_REQUIRED"}, params={"dataStoreId": f"docs-{TAG}"})
    call("POST", D + f"/dataStores/docs-{TAG}/branches/default_branch/documents:import", {"inlineSource": {"documents": [{"id": "1", "structData": {"title": "Boiler SOP", "body": DOC}}]}})
    r = call("POST", D + f"/dataStores/docs-{TAG}/servingConfigs/default_search:search", {"query": "boiler pressure"})
    assert r.get("totalSize", 0) >= 1, r
    return f"totalSize={r['totalSize']}"


s("RAG Engine: create_rag_corpus (gapic REST)", rag)
if hasattr(s, "corpus"):
    s("RAG Engine: GCS upload (google-cloud-storage) + import_rag_files", gcs_import)
    s("RAG Engine: retrieve_contexts returns the boiler SOP chunk", retrieve)
s("Vector Search: index + upsert + indexEndpoint + deployIndex + findNeighbors", vector)
s("Vertex AI Search: dataStore + import documents + servingConfig search", vais)
s.finish()
