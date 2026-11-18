"""Azure OpenAI "On Your Data": the REAL `openai` AzureOpenAI SDK + the REAL azure-search-documents SDK against the REAL appliance app (in-process).
chat.completions with extra_body.data_sources[azure_search] retrieves from the simulator's AI Search index and returns message.context
{citations[{content,title,url,filepath,chunk_id}], intent}, [docN] markers in the text; unsupported data source types -> 400. The model is the
local-LLM stub seam (core.llm_core.set_backend), which echoes the grounding it received so the test proves the retrieved docs reached the model.
Run: PYTHONPATH=. <venv>/bin/python tests/conformance/test_azure_openai_on_your_data.py   (skips cleanly without openai / azure-search-documents)"""
import os, sys, warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "examples", "ref-arch-probe", "azure"))
warnings.filterwarnings("ignore")
try:
    import openai  # noqa: F401
    from azure.search.documents.indexes import SearchIndexClient  # noqa: F401
    from azure.mgmt.search import SearchManagementClient  # noqa: F401
except ImportError as e:
    print(f"SKIP: optional dependency missing ({e})")
    sys.exit(0)

PASS = FAIL = 0


def check(name, fn):
    global PASS, FAIL
    try:
        ev = fn()
        PASS += 1
        print(f"  [PASS] {name} {'' if ev is None else str(ev)[:140]}")
    except Exception as e:  # noqa: BLE001
        FAIL += 1
        print(f"  [FAIL] {name} {type(e).__name__}: {str(e)[:300]}")


def need(c, what):
    if not c:
        raise AssertionError(what)


DOCS = [{"id": "1", "title": "Boiler SOP", "url": "https://kb/boiler", "path": "docs/boiler.md", "category": "plant", "content": "If boiler pressure exceeds 30 psi shut the feed valve and call the plant engineer."},
        {"id": "2", "title": "Leak runbook", "url": "https://kb/leak", "path": "docs/leak.md", "category": "plant", "content": "Report a water leak in the lobby to facilities."},
        {"id": "3", "title": "Badge policy", "url": "https://kb/badge", "path": "docs/badge.md", "category": "security", "content": "A lost badge must be reported to security. Boiler room badges are special."}]


def main():
    from _common import endpoint, ensure_rg, ensure_openai, aoai, arm, RG, LOC
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes.models import SearchFieldDataType, SearchIndex, SearchableField, SimpleField
    B = endpoint(); ensure_rg(B); ensure_openai(B)
    from core import llm_core
    seen = {}

    def stub(messages, system, max_tokens, temperature, stop):
        sysm = system or next((m["content"] for m in messages if m["role"] == "system"), "")
        seen["system"] = sysm
        return {"text": "Per [doc1] shut the feed valve. GROUNDED:" + str(sysm.count("[doc")), "finish_reason": "stop"}
    llm_core.set_backend(lambda m, sy, mt, t, st: stub(m, sy, mt, t, st))
    mc = arm(SearchManagementClient, B)
    mc.services.begin_create_or_update(RG, "srch1", {"location": LOC, "sku": {"name": "basic"}}).result()
    key = mc.admin_keys.get(RG, "srch1").primary_key
    K = AzureKeyCredential(key)
    ep = B + "/azure-data/search/srch1"
    SearchIndexClient(ep, K).create_index(SearchIndex(name="kb", fields=[
        SimpleField(name="id", type=SearchFieldDataType.String, key=True), SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String), SimpleField(name="url", type=SearchFieldDataType.String),
        SimpleField(name="path", type=SearchFieldDataType.String), SimpleField(name="category", type=SearchFieldDataType.String, filterable=True)]))
    SearchClient(ep, "kb", K).upload_documents(DOCS)
    oc = aoai(B, "2025-03-01-preview")
    q = "What is the boiler pressure rule?"

    def src(endpoint=ep, **kw):
        prm = {"endpoint": endpoint, "index_name": "kb", "authentication": {"type": "api_key", "key": key},
               "fields_mapping": {"content_fields": ["content"], "title_field": "title", "url_field": "url", "filepath_field": "path"}}
        prm.update(kw)
        return {"data_sources": [{"type": "azure_search", "parameters": prm}]}

    def ask(**kw):
        return oc.chat.completions.create(model="chat", messages=[{"role": "user", "content": q}], extra_body=src(**kw))

    def basic():
        r = ask(); m = r.choices[0].message
        c = m.context["citations"]
        need(c and c[0]["title"] == "Boiler SOP" and "30 psi" in c[0]["content"], c)
        need(c[0]["url"] == "https://kb/boiler" and c[0]["filepath"] == "docs/boiler.md" and c[0]["chunk_id"] == "0", c[0])
        need("[doc1]" in m.content, m.content)
        need("intent" in m.context and q in m.context["intent"], m.context)
        need("30 psi" in seen["system"] and "[doc1]" in seen["system"], "retrieved docs did not reach the model")
        return f"{len(c)} citations, first={c[0]['title']}"
    check("api_key + /azure-data/search/<svc> endpoint: citations, intent, [doc1] marker, grounding reached the model", basic)

    def forms():
        for e in (B + "/subscriptions/x/resourceGroups/r/providers/Microsoft.Search/searchServices/srch1", B):
            need(ask(endpoint=e).choices[0].message.context["citations"], e)
        return "ARM-extension path form + root endpoint (single service)"
    check("endpoint forms resolve the same service", forms)

    def topn_filter():
        c = ask(top_n_documents=1).choices[0].message.context["citations"]
        need(len(c) == 1, c)
        c2 = ask(filter="category eq 'security'").choices[0].message.context["citations"]
        need(c2 and all(x["title"] == "Badge policy" for x in c2), c2)
        return "top_n_documents=1 -> 1 citation; filter honoured"
    check("top_n_documents and filter honoured", topn_filter)

    def qtypes():
        for qt in ("simple", "semantic"):
            try:
                need(ask(query_type=qt, semantic_configuration="none").choices[0].message.context["citations"] is not None, qt)
            except openai.BadRequestError:
                if qt == "simple":
                    raise
        return "simple ok; semantic answers or is rejected with 400 (index has no semantic config)"
    check("query_type simple/semantic", qtypes)

    def bad_type():
        try:
            oc.chat.completions.create(model="chat", messages=[{"role": "user", "content": q}], extra_body={"data_sources": [{"type": "cosmos_db", "parameters": {}}]})
        except openai.BadRequestError as e:
            need("cosmos_db" in str(e) and "not supported" in str(e), str(e))
            return "400 BadRequest"
        raise AssertionError("no error for cosmos_db")
    check("unsupported data source type -> 400 BadRequest", bad_type)

    def bad_key():
        try:
            ask(authentication={"type": "api_key", "key": "nope"})
        except openai.BadRequestError:
            return "400"
        raise AssertionError("wrong key accepted")
    check("wrong search api-key -> 400", bad_key)

    def bad_index():
        try:
            ask(index_name="missing")
        except openai.BadRequestError:
            return "400"
        raise AssertionError("missing index accepted")
    check("missing index -> 400", bad_index)

    def stream():
        s = oc.chat.completions.create(model="chat", messages=[{"role": "user", "content": q}], stream=True, extra_body=src())
        ctx, text = None, ""
        for i, ch in enumerate(s):
            if not ch.choices:
                continue
            d = ch.choices[0].delta
            cx = getattr(d, "context", None) or (d.model_extra or {}).get("context")
            if cx and ctx is None:
                ctx = cx; need(i == 0, "context not in the first delta")
            text += d.content or ""
        need(ctx and ctx["citations"][0]["title"] == "Boiler SOP" and "[doc1]" in text, (ctx, text))
        return "context in first delta"
    check("stream=true: context arrives in the first delta", stream)

    def plain():
        r = oc.chat.completions.create(model="chat", messages=[{"role": "user", "content": "hi"}])
        need(not getattr(r.choices[0].message, "context", None), "plain chat gained a context")
    check("plain chat unchanged (no context)", plain)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
