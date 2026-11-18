"""C9: memory. SHORT-TERM = Assistants / Foundry threads (managed by the service). LONG-TERM = an application pattern on Azure Table storage that this app writes and reads
itself: Azure has NO managed long-term memory API (unlike AgentCore Memory and Vertex Memory Bank), and this app does not present it as one."""
import time
from ..runtime import NAMES, LANE

API = "2025-03-01-preview"


def run(ctx):
    user = ctx.state.get("user", "anonymous")
    oc = ctx.aoai(API)
    S = {}

    def thread():
        th = oc.beta.threads.create(metadata={"session": "s1", "user": user[:60]})
        for t in ("my badge is 4412", "which floor am I on"):
            oc.beta.threads.messages.create(th.id, role="user", content=t)
        S["th"] = th
        return th.id
    ctx.step("assistants: create a thread with metadata and two user messages (short-term memory)", thread, lane=LANE["ai"])
    if "th" not in S:
        _long_term(ctx, user)
        return

    def history():
        ms = oc.beta.threads.messages.list(S["th"].id, order="asc").data
        assert [m.content[0].text.value for m in ms] == ["my badge is 4412", "which floor am I on"], ms
        return f"{len(ms)} messages read back in order"
    ctx.step("assistants: GET messages returns the session history in order", history, lane=LANE["ai"])

    def meta():
        t = oc.beta.threads.update(S["th"].id, metadata={"session": "s1", "user": user[:60], "topic": "badge"})
        assert t.metadata.get("topic") == "badge"
        assert oc.beta.threads.retrieve(S["th"].id).metadata.get("topic") == "badge"
        return "thread metadata updated and retrieved"
    ctx.step("assistants: update + retrieve thread metadata", meta, lane=LANE["ai"])

    def recall():
        a = oc.beta.assistants.create(model=NAMES["chat"], instructions="Answer from the conversation so far.")
        r = oc.beta.threads.runs.create(S["th"].id, assistant_id=a.id)
        for _ in range(60):
            if r.status not in ("queued", "in_progress"):
                break
            time.sleep(0.5)
            r = oc.beta.threads.runs.retrieve(r.id, thread_id=S["th"].id)
        assert r.status == "completed", f"run {r.status}: {getattr(r.last_error, 'message', '')[:140]}"
        txt = " ".join(c.text.value for m in oc.beta.threads.messages.list(S["th"].id).data if m.role == "assistant" for c in m.content)
        assert "4412" in txt, txt[:200]
        return "the assistant recalled the badge number from the thread"
    ctx.step("assistants: a run recalls a fact from earlier in the thread (needs a model)", recall, lane=LANE["ai"])

    def delete():
        assert oc.beta.threads.delete(S["th"].id).deleted
        return "thread deleted"
    ctx.step("assistants: delete the thread", delete, lane=LANE["ai"])
    _long_term(ctx, user)


def _long_term(ctx, user):
    """Application-level long-term memory on Azure Table storage: facts keyed by user, survive the session thread, injected into the next session."""
    mem = lambda: ctx.table(NAMES["memory"])
    pk = user[:60].replace("/", "_").replace("#", "_").replace("?", "_")

    def write():
        mem().upsert_entity({"PartitionKey": pk, "RowKey": "pref-floor", "fact": "prefers floor 3 east wing for inspections", "source": "session s1", "ts": int(time.time())})
        return f"fact stored for {user} in table {NAMES['memory']} (APPLICATION PATTERN, not a managed Azure memory service)"
    ctx.step("long-term memory (app pattern): store a user fact in Azure Table storage", write, lane=LANE["data"])

    def recall():
        rows = [dict(e) for e in mem().query_entities("PartitionKey eq @u", parameters={"u": pk})]
        assert rows and "floor 3" in rows[0]["fact"], rows
        return f"new session recalls: {rows[0]['fact']}"
    ctx.step("long-term memory (app pattern): a new session recalls the fact", recall, lane=LANE["data"])

    def no_managed_api():
        import requests
        codes = [requests.get(ctx.endpoint + p, params={"api-version": API}, timeout=10).status_code for p in ("/openai/memory_stores", "/openai/memories")]
        assert all(c in (404, 405) for c in codes), codes
        return f"no managed long-term memory route exists on the Azure OpenAI / Foundry surface (HTTP {codes}); this is expected, not invented"
    ctx.step("confirm Azure has no managed long-term memory API (expected absent)", no_managed_api)
    ctx.note("Long-term memory is an APPLICATION PATTERN on Azure Table storage. Azure has no managed long-term memory service (AWS has AgentCore Memory, GCP has Memory Bank).")
