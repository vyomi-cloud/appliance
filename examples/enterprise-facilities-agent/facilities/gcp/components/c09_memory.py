"""C9: Agent Platform Sessions (short-term events per session) + Memory Bank (long-term facts retrieved by similarity), via vertexai.Client."""
import json, time, uuid
from ..runtime import NAMES, LANE


def run(ctx):
    def host():
        """Sessions and Memory Bank hang off an Agent Engine resource; this one is the memory host (name facilities_memory)."""
        from google.cloud import aiplatform_v1 as av
        svc = ctx.aiplatform("ReasoningEngineServiceClient")
        spec = {"instructions": "Facilities memory host.", "max_steps": 2, "tools": []}
        eng = av.ReasoningEngine(display_name=NAMES["memory"], spec=av.ReasoningEngineSpec(
            deployment_spec=av.ReasoningEngineSpec.DeploymentSpec(env=[av.EnvVar(name="VYOMI_AGENT_SPEC", value=json.dumps(spec))])))
        ctx.state["memory_engine"] = svc.create_reasoning_engine(parent=ctx.parent, reasoning_engine=eng).result(timeout=60).name
        return ctx.state["memory_engine"]
    ctx.step("agent platform: create the memory host engine facilities_memory", host)
    eng = ctx.state.get("memory_engine")
    if not eng:
        return
    c = ctx.vertex("v1beta1")
    res = ctx.state.get("result", {})
    box = {}

    def session():
        op = c.agent_engines.sessions.create(name=eng, user_id="maria")
        box["session"] = op.response.name
        return op.response.name
    ctx.step("sessions: create a session for the user", session)

    def write():
        s = box["session"]
        for author, text in (("user", res.get("question") or "q"), ("agent", res.get("answer") or "a")):
            c.agent_engines.sessions.events.append(name=s, author=author, invocation_id=uuid.uuid4().hex[:8], timestamp=time.time(),
                                                   config={"content": {"role": "user" if author == "user" else "model", "parts": [{"text": text}]}})
        return "2 events appended (user turn + agent turn)"
    if box.get("session"):
        ctx.step("sessions: append events (user + agent turn)", write)

        def read():
            ev = list(c.agent_engines.sessions.events.list(name=box["session"]))
            assert len(ev) >= 2, ev
            return f"{len(ev)} events read back for the session"
        ctx.step("sessions: list events (session replay)", read)

    def remember():
        c.agent_engines.memories.create(name=eng, fact="Maria Ops prefers the boiler B-12 report on Mondays", scope={"user_id": "maria"})
        got = list(c.agent_engines.memories.retrieve(name=eng, scope={"user_id": "maria"}, similarity_search_params={"search_query": "boiler", "top_k": 3}))
        assert got and "boiler" in got[0].memory.fact.lower(), got
        return f"{len(got)} long-term memory retrieved by similarity: {got[0].memory.fact[:50]!r}"
    ctx.step("memory bank: create a fact + retrieve by similarity (long-term)", remember)

    def generate():
        c.agent_engines.memories.generate(name=eng, direct_contents_source={"events": [{"content": {"role": "user", "parts": [{"text": "I always want the level 3 chiller report on Mondays."}]}}]},
                                          scope={"user_id": "maria"})
        return "memories.generate extracted facts with the model"
    ctx.step("memory bank: generate memories from a conversation (LLM fact extraction)", generate)
