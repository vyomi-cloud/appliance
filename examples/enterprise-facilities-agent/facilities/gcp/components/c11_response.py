"""C11: response generation: grounded, cited answer; output guardrail (Model Armor sanitizeModelResponse); generateContent grounded on the RAG corpus."""
from ..runtime import NAMES, LANE, Blocked, is_model_missing, need_result
from ..io import MODEL


def run(ctx):
    res = ctx.state.get("result", {})

    def cites():
        need_result(ctx, "ground")
        assert res.get("citations"), "the agent returned no citations"
        assert res["answer"].strip(), "empty answer"
        srcs = {x["source"] for x in res["citations"]}
        assert any("boiler-sop" in s for s in srcs), srcs
        assert "[1]" in res["answer"] or "30 psi" in res["answer"], res["answer"][:120]
        return f"answer grounded in {len(srcs)} cited sources; first: {sorted(srcs)[0]}"
    ctx.step("answer is grounded in retrieved documents and cites them", cites)
    tpl = ctx.state.get("armor_template")
    if tpl and res.get("answer") is None:
        ctx.step("model armor sanitizeModelResponse on the agent answer", lambda: need_result(ctx, "guard"))
    elif tpl:
        from google.cloud import modelarmor_v1 as ma
        c = ctx.rest(ma.ModelArmorClient)

        def out_guard():
            r = c.sanitize_model_response(request={"name": tpl, "model_response_data": {"text": res["answer"] + " Contact the duty engineer at ssn 123-45-6789, jane.doe@example.com."}, "user_prompt": "who to call?"})
            assert r.sanitization_result.filter_match_state == ma.FilterMatchState.MATCH_FOUND, r.sanitization_result.filter_match_state
            return "output guardrail flagged sensitive data (SSN) in the answer"
        ctx.step("model armor sanitizeModelResponse: sensitive data in the answer is flagged", out_guard)

        def clean():
            r = c.sanitize_model_response(request={"name": tpl, "model_response_data": {"text": res["answer"]}, "user_prompt": "q"})
            assert r.sanitization_result.filter_match_state == ma.FilterMatchState.NO_MATCH_FOUND, r.sanitization_result.filter_match_state
            return "the agent answer itself passes the output filter"
        ctx.step("model armor sanitizeModelResponse: the agent answer passes the output filter", clean)

    def grounded():
        from google.genai import types, errors
        corpus = ctx.state["rag_corpus"]
        tool = types.Tool(retrieval=types.Retrieval(vertex_rag_store=types.VertexRagStore(rag_resources=[types.VertexRagStoreRagResource(rag_corpus=corpus)], similarity_top_k=2)))
        try:
            r = ctx.genai().models.generate_content(model=MODEL, contents="What should I do when boiler pressure exceeds 30 psi?", config=types.GenerateContentConfig(tools=[tool]))
        except errors.APIError as e:
            if is_model_missing(e):
                raise Blocked(LANE["model"], f"needs a model: {str(e)[:120]}")
            raise
        gm = r.candidates[0].grounding_metadata
        assert gm and (gm.grounding_chunks or gm.retrieval_queries), f"no grounding metadata: {gm}"
        assert r.text, "empty answer"
        return f"model answer grounded with {len(gm.grounding_chunks or [])} chunk(s) from the RAG corpus"
    if ctx.state.get("rag_corpus"):
        ctx.step("vertex ai: generateContent with the RAG retrieval tool returns an answer + groundingMetadata", grounded, lane=LANE["core"])
