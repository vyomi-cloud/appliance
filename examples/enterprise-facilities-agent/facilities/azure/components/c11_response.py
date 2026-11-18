"""C11: response generation: grounded, cited answer (agent run over AI Search + Assistants file_search with citations + On Your Data) and the OUTPUT content filter
(Azure AI Content Safety on the answer; completion-side RAI policy)."""
import os, time
from ..runtime import NAMES, LANE, RG, need_result, fixture_dir

API = "2025-03-01-preview"


def run(ctx):
    res = ctx.state.get("result", {})

    def cites():
        need_result(ctx, "ground")
        assert res.get("citations"), "the agent returned no citations"
        assert res["answer"].strip(), "empty answer"
        srcs = {x["source"] for x in res["citations"]}
        assert any("boiler" in s.lower() for s in srcs), srcs
        assert "[1]" in res["answer"] or "30 psi" in res["answer"], res["answer"][:120]
        return f"answer grounded in {len(srcs)} cited sources; first: {sorted(srcs)[0]}"
    ctx.step("answer is grounded in retrieved documents (AI Search) and cites them", cites)

    def guard():
        from azure.ai.contentsafety import ContentSafetyClient
        from azure.ai.contentsafety.models import AnalyzeTextOptions
        from azure.core.credentials import AzureKeyCredential
        c = ContentSafetyClient(ctx.endpoint, AzureKeyCredential("vyomi-local"))
        ok = {x.category: x.severity for x in c.analyze_text(AnalyzeTextOptions(text=res["answer"])).categories_analysis}
        assert all(v == 0 for v in ok.values()), f"the agent answer was flagged: {ok}"
        bad = {x.category: x.severity for x in c.analyze_text(AnalyzeTextOptions(text="You should torture and kill the technician who reports to you.")).categories_analysis}
        assert any(v and v > 0 for v in bad.values()), f"a harmful completion was not flagged: {bad}"
        return f"agent answer passes the output filter {ok}; a harmful completion is flagged {bad}"
    if res.get("answer") is None:
        ctx.step("content safety on the answer (output guardrail)", lambda: need_result(ctx, "guard"))
    else:
        ctx.step("content safety: the agent answer passes the output filter and a harmful completion is flagged", guard, lane=LANE["messaging"])

    oc = ctx.aoai(API)
    S = {}

    def vstore():
        vs = oc.vector_stores.create(name="facilities-kb")
        f = oc.files.create(file=("boiler-sop.md", open(os.path.join(fixture_dir(), "docs", "boiler-sop.md"), "rb").read()), purpose="assistants")
        oc.vector_stores.files.create(vs.id, file_id=f.id)
        S["vs"] = vs
        return vs.id
    ctx.step("assistants: vector store + file upload + attach (openai SDK)", vstore, lane=LANE["ai"])
    if "vs" in S:
        def vlist():
            fs = oc.vector_stores.files.list(S["vs"].id).data
            assert fs, "no files in the vector store"
            return f"{len(fs)} file(s) in the vector store"
        ctx.step("assistants: vector store files list", vlist, lane=LANE["ai"])

        def fsearch():
            a = oc.beta.assistants.create(model=NAMES["chat"], instructions="Answer only from the files.", tools=[{"type": "file_search"}], tool_resources={"file_search": {"vector_store_ids": [S["vs"].id]}})
            th = oc.beta.threads.create(messages=[{"role": "user", "content": "What must I do when boiler pressure exceeds 30 psi?"}])
            r = oc.beta.threads.runs.create(th.id, assistant_id=a.id)
            for _ in range(60):
                if r.status not in ("queued", "in_progress"):
                    break
                time.sleep(0.5)
                r = oc.beta.threads.runs.retrieve(r.id, thread_id=th.id)
            assert r.status == "completed", f"run {r.status}: {getattr(r.last_error, 'message', '')[:140]}"
            S["th"], S["run"] = th, r
            return "file_search run completed"
        ctx.step("assistants: an assistant with file_search runs against the vector store (needs a model)", fsearch, lane=LANE["ai"])

        def annotations():
            ms = oc.beta.threads.messages.list(S["th"].id).data
            ann = [x for m in ms if m.role == "assistant" for c in m.content for x in c.text.annotations]
            assert ann and ann[0].type == "file_citation", ann
            return f"{len(ann)} file_citation annotation(s)"
        if "th" in S:
            ctx.step("assistants: the assistant message carries file_citation annotations", annotations, lane=LANE["ai"])

    def on_your_data():
        r = oc.chat.completions.create(model=NAMES["chat"], messages=[{"role": "user", "content": "What is the boiler pressure rule?"}], extra_body={"data_sources": [{
            "type": "azure_search", "parameters": {"endpoint": ctx.search_endpoint(), "index_name": NAMES["index"], "authentication": {"type": "api_key", "key": ctx.state["search_key"]}}}]})
        ctxm = getattr(r.choices[0].message, "context", None)
        assert ctxm and ctxm.get("citations"), ctxm
        return f"On Your Data answer with {len(ctxm['citations'])} citation(s) from AI Search"
    if ctx.state.get("search_key"):
        ctx.step("azure openai On Your Data: chat grounded on the AI Search index returns citations (needs a model)", on_your_data, lane=LANE["ai"])

    def completion_policy():
        from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
        p = ctx.arm(CognitiveServicesManagementClient).rai_policies.get(RG, NAMES["openai"], NAMES["guardrail"])
        srcs = {str(getattr(f.source, "value", f.source)).lower() for f in (p.properties.content_filters or [])}
        assert any("completion" in s for s in srcs), srcs
        return "the guardrail policy filters the Completion source (output) as well as the Prompt"
    if ctx.state.get("guarded"):
        ctx.step("azure openai content filter: the guardrail policy covers the completion (output) source", completion_policy, lane=LANE["ai"])
