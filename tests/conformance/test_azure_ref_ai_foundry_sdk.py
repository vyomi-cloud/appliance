"""Azure ref-arch lane 2 (part 2): Foundry project endpoint (`<host>/api/projects/<project>`) with the REAL azure-ai-projects (AIProjectClient)
and azure-ai-agents (AgentsClient) SDKs against the REAL appliance app (server.py, in-process). Model = the local-LLM stub seam.
Covered (azure-ai-projects 2.11.0, azure-ai-agents 1.1.0): see docs/architecture/v4.0/branches/az-ref-ai.md.
Run: PYTHONPATH=. <venv>/bin/python tests/conformance/test_azure_ref_ai_foundry_sdk.py   (skips cleanly without the SDKs)"""
import os, sys, warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "examples", "ref-arch-probe", "azure"))
warnings.filterwarnings("ignore")
try:
    from azure.ai.projects import AIProjectClient
    from azure.ai.agents import AgentsClient
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
    from _common import endpoint, ensure_rg, ensure_openai, Cred
    from azure.core.pipeline.policies import SansIOHTTPPolicy
    B = endpoint(); ensure_rg(B); ensure_openai(B)
    from core import llm_core
    llm_core.set_backend(lambda m, sy, mt, t, st: {"text": "Approvals above 500 dollars need a manager.", "finish_reason": "stop"})
    ep = B + "/api/projects/facilities-project"

    class _Bearer(SansIOHTTPPolicy):          # the SDK's own BearerTokenCredentialPolicy refuses non-TLS endpoints; same header, plain-http local simulator
        def on_request(self, request):
            request.http_request.headers["Authorization"] = "Bearer vyomi-local-token"
    pc = AIProjectClient(endpoint=ep, credential=Cred(), authentication_policy=_Bearer())
    ac = AgentsClient(endpoint=ep, credential=Cred(), authentication_policy=_Bearer())
    S = {}

    check("AIProjectClient.connections.list/get/get_default", lambda: (
        [c.name for c in pc.connections.list()],
        pc.connections.get("aoai1").target,
        pc.connections.get("aoai1", include_credentials=True).credentials is not None,
        pc.connections.get_default("AzureOpenAI").name))
    check("AIProjectClient.deployments.list/get", lambda: ([d.name for d in pc.deployments.list()], pc.deployments.get("chat").model_name))

    def agents_v2():
        a = pc.agents.create_version(agent_name="facilities_supervisor", definition={"kind": "prompt", "model": "chat", "instructions": "Route facilities requests."})
        assert a.name == "facilities_supervisor" and a.version == "1"
        a2 = pc.agents.create_version(agent_name="facilities_supervisor", definition={"kind": "prompt", "model": "chat", "instructions": "v2"})
        assert a2.version == "2"
        assert pc.agents.get(agent_name="facilities_supervisor").versions.latest.version == "2"
        assert "facilities_supervisor" in [x.name for x in pc.agents.list()]
        assert [v.version for v in pc.agents.list_versions(agent_name="facilities_supervisor")] == ["2", "1"]
        assert pc.agents.get_version(agent_name="facilities_supervisor", agent_version="1").definition["instructions"].startswith("Route")
    check("agents v2: create_version x2 / get / list / list_versions / get_version", agents_v2)

    def v2_responses():
        oc = pc.get_openai_client()
        conv = oc.conversations.create()
        S["conv"] = conv.id
        r = oc.responses.create(conversation=conv.id, input="Who approves 900 dollars?", extra_body={"agent_reference": {"name": "facilities_supervisor", "type": "agent_reference"}})
        assert r.output_text.startswith("Approvals"), r.output_text
        assert oc.conversations.retrieve(conv.id).id == conv.id
        items = list(oc.conversations.items.list(conv.id))
        assert [i.role for i in items] == ["assistant", "user"], [i.role for i in items]
        oc.conversations.items.create(conv.id, items=[{"type": "message", "role": "user", "content": "again"}])
        assert len(list(oc.conversations.items.list(conv.id))) == 3
        assert oc.conversations.delete(conv.id).deleted
    check("agents v2 invoke via responses(agent_reference) + conversations create/items/delete", v2_responses)

    check("agents v2: delete_version / delete", lambda: (pc.agents.delete_version(agent_name="facilities_supervisor", agent_version="2"), pc.agents.delete(agent_name="facilities_supervisor")))

    def classic():
        a = ac.create_agent(model="chat", name="facilities_supervisor", instructions="x", tools=[{"type": "file_search"}]); S["a"] = a
        assert ac.get_agent(a.id).name == "facilities_supervisor"
        assert a.id in [x.id for x in ac.list_agents()]
        th = ac.threads.create(); S["th"] = th
        m = ac.messages.create(th.id, role="user", content="Who approves 900 dollars?")
        assert ac.messages.get(th.id, m.id).id == m.id
        r = ac.runs.create_and_process(th.id, agent_id=a.id)
        assert r.status == "completed", (r.status, r.last_error)
        msgs = list(ac.messages.list(th.id))
        assert any(x.role == "assistant" for x in msgs)
        assert list(ac.run_steps.list(th.id, r.id))
        assert ac.runs.get(th.id, r.id).status == "completed"
    check("azure-ai-agents classic: create_agent/get/list, thread, message, run (create_and_process), messages.list, run_steps", classic)

    def classic_rag():
        import io
        f = ac.files.upload_and_poll(file=("policy.txt", io.BytesIO(b"Approvals above 500 dollars need a manager sign off.")), purpose="assistants")
        vs = ac.vector_stores.create_and_poll(file_ids=[f.id], name="kb")
        assert vs.file_counts.completed == 1
        from azure.ai.agents.models import FileSearchTool
        fs = FileSearchTool(vector_store_ids=[vs.id])
        ac.update_agent(S["a"].id, tools=fs.definitions, tool_resources=fs.resources)
        th = ac.threads.create(); ac.messages.create(th.id, role="user", content="Who approves 900 dollars?")
        r = ac.runs.create_and_process(th.id, agent_id=S["a"].id)
        assert r.status == "completed", (r.status, r.last_error)
        ann = [a for m in ac.messages.list(th.id) for c in m.content if getattr(c, "text", None) for a in c.text.annotations]
        assert ann, "no citations"
        assert [x.id for x in ac.vector_store_files.list(vs.id)] == [f.id]
        ac.vector_stores.delete(vs.id); ac.files.delete(f.id)
    check("azure-ai-agents classic: files.upload_and_poll, vector_stores.create_and_poll, file_search run with citations, vector_store_files.list", classic_rag)
    check("azure-ai-agents classic: delete thread / agent", lambda: (ac.threads.delete(S["th"].id), ac.delete_agent(S["a"].id)))
    print(f"{PASS} passed, {FAIL} failed")
    sys.stdout.flush()
    os._exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
