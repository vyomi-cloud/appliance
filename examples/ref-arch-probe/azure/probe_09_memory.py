"""Component 9 Memory: Assistants threads as short-term memory; confirm there is NO managed long-term memory API (not invented)."""
from _common import *

P = Probe(9, "memory", "Memory: Assistants threads (short-term); no managed long-term")
B = endpoint(); ensure_rg(B); ensure_openai(B)
S = {}


def thread_with_history():
    oc = aoai(B, "2025-03-01-preview"); S["oc"] = oc
    th = oc.beta.threads.create(metadata={"session": "s1"})
    for i, t in enumerate(["my badge is 4412", "which floor am I on"]):
        oc.beta.threads.messages.create(th.id, role="user", content=t)
    S["th"] = th
    return th.id


def read_history():
    ms = S["oc"].beta.threads.messages.list(S["th"].id, order="asc").data
    assert [m.content[0].text.value for m in ms] == ["my badge is 4412", "which floor am I on"], ms
    return len(ms)


def metadata_update():
    t = S["oc"].beta.threads.update(S["th"].id, metadata={"session": "s1", "user": "u7"})
    assert t.metadata.get("user") == "u7"


def delete_thread():
    S["oc"].beta.threads.delete(S["th"].id)


def recall_needs_model():
    th = S["oc"].beta.threads.create(messages=[{"role": "user", "content": "my badge is 4412"}])
    a = S["oc"].beta.assistants.create(model="chat", instructions="remember")
    r = S["oc"].beta.threads.runs.create(th.id, assistant_id=a.id)
    assert r.status == "completed", f"run {r.status}"


def no_long_term_api():
    """Azure OpenAI/Foundry expose no managed long-term memory store; a /memory or /memories route must not exist (we do not invent one)."""
    import requests
    codes = [requests.get(B + p, params={"api-version": "2025-03-01-preview"}).status_code for p in ("/openai/memory_stores", "/openai/memories")]
    assert all(c in (404, 405) for c in codes), codes
    return f"no managed long-term memory route (status {codes}); long-term memory is an app pattern on Cosmos/AI Search"


P.step("create thread with metadata + messages (short-term memory)", thread_with_history)
P.step("GET messages (history read-back)", read_history)
P.step("update thread metadata", metadata_update)
P.step("recall across turns via a run (needs a model)", recall_needs_model, blocked="no model")
P.step("delete thread", delete_thread)
P.step("confirm NO managed long-term memory API exists (expected absent)", no_long_term_api)
P.finish()
