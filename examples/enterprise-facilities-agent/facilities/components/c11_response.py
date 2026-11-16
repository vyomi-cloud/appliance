"""C11: response generation: grounded answer with citations, output guardrail (PII), RetrieveAndGenerate."""
from ..runtime import NAMES


def run(ctx):
    br, rt = ctx.client("bedrock-runtime"), ctx.client("bedrock-agent-runtime")
    res = ctx.state.get("result", {})

    def cites():
        assert res.get("citations"), "the agent returned no citations"
        assert res["answer"].strip(), "empty answer"
        srcs = {c["source"] for c in res["citations"]}
        assert any("boiler-sop" in s for s in srcs), srcs
        assert "[1]" in res["answer"] or "30 psi" in res["answer"], res["answer"][:120]
        return f"answer grounded in {len(srcs)} cited sources; first: {sorted(srcs)[0]}"
    ctx.step("answer is grounded in retrieved documents and cites them", cites)

    def out_guard():
        gid = ctx.state["guardrail_id"]
        r = br.apply_guardrail(guardrailIdentifier=gid, guardrailVersion="DRAFT", source="OUTPUT",
                               content=[{"text": {"text": res["answer"] + " Contact the duty engineer at jane.doe@example.com."}}])
        assert r["action"] == "GUARDRAIL_INTERVENED", r["action"]
        txt = r["outputs"][0]["text"]
        assert "jane.doe@example.com" not in txt, txt
        return "output guardrail anonymised an email address in the answer"
    if ctx.state.get("guardrail_id"):
        ctx.step("guardrail output: PII is anonymised before the user sees the answer", out_guard)
        ctx.step("guardrail output: the agent answer itself passes the output filter", lambda: (lambda a: a == "NONE" or (_ for _ in ()).throw(AssertionError(a)) or "ok")(
            br.apply_guardrail(guardrailIdentifier=ctx.state["guardrail_id"], guardrailVersion="DRAFT", source="OUTPUT", content=[{"text": {"text": res["answer"]}}])["action"]))

    def rag():
        r = rt.retrieve_and_generate(
            input={"text": "What should I do when boiler pressure exceeds 30 psi?"},
            retrieveAndGenerateConfiguration={"type": "KNOWLEDGE_BASE", "knowledgeBaseConfiguration": {
                "knowledgeBaseId": ctx.state["kb_id"], "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
                "generationConfiguration": {"guardrailConfiguration": {"guardrailId": ctx.state.get("guardrail_id", ""), "guardrailVersion": "DRAFT"}}}})
        assert r["output"]["text"] and r["citations"], r
        return f"generated answer with {len(r['citations'])} citation block(s)"
    if ctx.state.get("kb_id"):
        ctx.step("bedrock-agent-runtime: RetrieveAndGenerate (model answer + citations + guardrail)", rag, lane="local model")
    ctx.state["_answer_shown"] = res.get("answer", "")
