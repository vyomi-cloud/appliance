"""C11 Response: grounded answer (generateContent with a Vertex RAG retrieval tool -> groundingMetadata citations) + Model Armor sanitizeModelResponse on the output."""
from _common import *

s = Step()
P = f"projects/{PROJECT}/locations/{LOC}"


def corpus():
    from google.cloud import aiplatform_v1 as av
    data = rest_client(av.VertexRagDataServiceClient)
    c = data.create_rag_corpus(request={"parent": P, "rag_corpus": {"display_name": f"g-{TAG}"}}).result(timeout=60)
    call("POST", f"/upload/v1/{c.name}/ragFiles:upload", {"ragFile": {"displayName": "boiler.txt"}, "text": DOC})
    s.corpus = c.name
    return c.name


def grounded():
    from google.genai import types, errors
    c = genai_client()
    tool = types.Tool(retrieval=types.Retrieval(vertex_rag_store=types.VertexRagStore(rag_resources=[types.VertexRagStoreRagResource(rag_corpus=s.corpus)], similarity_top_k=2)))
    try:
        r = c.models.generate_content(model="gemini-2.0-flash", contents="What is the boiler pressure limit?", config=types.GenerateContentConfig(tools=[tool]))
    except errors.APIError as e:
        if "503" in str(e) or "Local LLM" in str(e):
            raise Blocked(f"needs a model; request with vertex_rag_store retrieval tool accepted up to the model call: {str(e)[:120]}")
        raise
    gm = r.candidates[0].grounding_metadata
    assert gm and (gm.grounding_chunks or gm.retrieval_queries), f"no grounding metadata: {gm}"
    assert "30" in (r.text or ""), r.text
    return f"grounded with {len(gm.grounding_chunks or [])} chunks"


def armor_response():
    call("POST", f"/v1/{P}/templates", {"filterConfig": {"sdpSettings": {"basicConfig": {"filterEnforcement": "ENABLED"}},
         "raiSettings": {"raiFilters": [{"filterType": "DANGEROUS", "confidenceLevel": "MEDIUM_AND_ABOVE"}]}}}, params={"templateId": f"out-{TAG}"})
    ok = call("POST", f"/v1/{P}/templates/out-{TAG}:sanitizeModelResponse", {"modelResponseData": {"text": "The boiler limit is 30 psi."}, "userPrompt": "limit?"})
    bad = call("POST", f"/v1/{P}/templates/out-{TAG}:sanitizeModelResponse", {"modelResponseData": {"text": "Sure, email me at bob@example.com, ssn 123-45-6789"}, "userPrompt": "contact?"})
    a, b = ok["sanitizationResult"]["filterMatchState"], bad["sanitizationResult"]["filterMatchState"]
    assert a == "NO_MATCH_FOUND" and b == "MATCH_FOUND", (a, b, bad)
    return "clean output passes, PII output flagged"


s("RAG corpus + file for grounding", corpus)
if hasattr(s, "corpus"):
    s("generateContent with Vertex RAG retrieval tool returns grounded answer + groundingMetadata", grounded)
s("Model Armor sanitizeModelResponse flags PII in the answer", armor_response)
s.finish()
