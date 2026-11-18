"""Azure ref-arch lane 2 (part 1): the REAL `openai` AzureOpenAI SDK against the REAL appliance app (server.py, in-process).
Regression for the /openai GET/DELETE/PATCH routing gap (routes/aws_s3.py only sent POST to the Azure OpenAI core): assistants, threads,
messages, runs, run steps, vector stores, file batches, vector-store file list, and file_search citations (model = the local-LLM stub seam).
Run: PYTHONPATH=. <venv-with-openai>/bin/python tests/conformance/test_azure_ref_ai_openai_sdk.py   (skips cleanly without `openai`)"""
import os, sys, warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "examples", "ref-arch-probe", "azure"))
warnings.filterwarnings("ignore")
try:
    import openai  # noqa: F401
    from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient  # noqa: F401
except ImportError as e:
    print(f"SKIP: optional dependency missing ({e})")
    sys.exit(0)

PASS = FAIL = 0


def check(name, fn):
    global PASS, FAIL
    try:
        ev = fn()
        PASS += 1
        print(f"  [PASS] {name} {'' if ev is None else str(ev)[:120]}")
    except Exception as e:  # noqa: BLE001
        FAIL += 1
        print(f"  [FAIL] {name} {type(e).__name__}: {str(e)[:300]}")


def main():
    from _common import endpoint, ensure_rg, ensure_openai, aoai
    B = endpoint(); ensure_rg(B); ensure_openai(B)
    from core import llm_core
    llm_core.set_backend(lambda m, sy, mt, t, st: {"text": "Approvals above 500 dollars need a manager.", "finish_reason": "stop"})
    oc = aoai(B, "2025-03-01-preview")
    S = {}

    def asst():
        a = oc.beta.assistants.create(model="chat", name="sup", instructions="x", tools=[{"type": "file_search"}, {"type": "function", "function": {"name": "f", "parameters": {"type": "object", "properties": {}}}}])
        S["a"] = a
        assert oc.beta.assistants.retrieve(a.id).name == "sup"
        assert a.id in [x.id for x in oc.beta.assistants.list().data]
        assert oc.beta.assistants.update(a.id, name="sup2").name == "sup2"
        return a.id
    check("assistants create/get/list/update", asst)

    def thread():
        th = oc.beta.threads.create(messages=[{"role": "user", "content": "hello"}]); S["th"] = th
        assert oc.beta.threads.retrieve(th.id).id == th.id
        assert oc.beta.threads.update(th.id, metadata={"k": "v"}).metadata == {"k": "v"}
        m = oc.beta.threads.messages.create(th.id, role="user", content="second")
        assert oc.beta.threads.messages.retrieve(m.id, thread_id=th.id).id == m.id
        assert len(oc.beta.threads.messages.list(th.id).data) == 2
        assert oc.beta.threads.messages.update(m.id, thread_id=th.id, metadata={"a": "b"}).metadata == {"a": "b"}
        d = oc.beta.threads.messages.delete(m.id, thread_id=th.id); assert d.deleted
    check("thread create/get/update + message create/get/list/update/delete", thread)

    # vector store + files + batches
    def vs():
        v = oc.vector_stores.create(name="kb"); S["vs"] = v
        f1 = oc.files.create(file=("policy.txt", b"Approvals above 500 dollars need a manager sign off. Water leaks are reported to facilities."), purpose="assistants")
        f2 = oc.files.create(file=("safety.txt", b"Fire drills run every quarter."), purpose="assistants")
        oc.vector_stores.files.create(v.id, file_id=f1.id)
        S["f1"] = f1
        assert [x.id for x in oc.vector_stores.files.list(v.id).data] == [f1.id]
        assert oc.vector_stores.files.retrieve(f1.id, vector_store_id=v.id).id == f1.id
        b = oc.vector_stores.file_batches.create(v.id, file_ids=[f2.id])
        assert oc.vector_stores.file_batches.retrieve(b.id, vector_store_id=v.id).id == b.id
        assert len(oc.vector_stores.file_batches.list_files(b.id, vector_store_id=v.id).data) == 1
        assert len(oc.vector_stores.files.list(v.id).data) == 2
        assert oc.vector_stores.retrieve(v.id).id == v.id
        assert v.id in [x.id for x in oc.vector_stores.list().data]
        assert oc.vector_stores.update(v.id, name="kb2").name == "kb2"
        return v.id
    check("vector store create/get/list/update + files create/list/get + file batches create/get/list_files", vs)

    def run():
        a = oc.beta.assistants.update(S["a"].id, tool_resources={"file_search": {"vector_store_ids": [S["vs"].id]}}, tools=[{"type": "file_search"}])
        th = oc.beta.threads.create(messages=[{"role": "user", "content": "Who must approve 900 dollars?"}])
        r = oc.beta.threads.runs.create(th.id, assistant_id=a.id); S["r"], S["th2"] = r, th
        assert r.status == "completed", (r.status, r.last_error)
        assert oc.beta.threads.runs.retrieve(r.id, thread_id=th.id).status == "completed"
        assert r.id in [x.id for x in oc.beta.threads.runs.list(th.id).data]
        return r.status
    check("run create (stub model) + get + list", run)

    def citations():
        ms = oc.beta.threads.messages.list(S["th2"].id).data
        ann = [x for m in ms if m.role == "assistant" for c in m.content for x in c.text.annotations]
        assert ann and ann[0].type == "file_citation" and ann[0].file_citation.file_id == S["f1"].id, ann
    check("file_search run yields file_citation annotations", citations)

    def steps():
        ss = oc.beta.threads.runs.steps.list(S["r"].id, thread_id=S["th2"].id).data
        assert ss
        assert oc.beta.threads.runs.steps.retrieve(ss[0].id, thread_id=S["th2"].id, run_id=S["r"].id).id == ss[0].id
        assert {s.type for s in ss} == {"tool_calls", "message_creation"}, [s.type for s in ss]
        return [s.type for s in ss]
    check("run steps list + get", steps)

    def deletes():
        assert oc.vector_stores.files.delete(S["f1"].id, vector_store_id=S["vs"].id).deleted
        assert oc.vector_stores.delete(S["vs"].id).deleted
        assert oc.beta.threads.delete(S["th"].id).deleted
        assert oc.beta.assistants.delete(S["a"].id).deleted
        try:
            oc.beta.threads.retrieve(S["th"].id); raise AssertionError("thread still there")
        except openai.NotFoundError:
            pass
    check("DELETE vector-store file / vector store / thread / assistant, then 404", deletes)
    print(f"{PASS} passed, {FAIL} failed")
    sys.stdout.flush()
    os._exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
