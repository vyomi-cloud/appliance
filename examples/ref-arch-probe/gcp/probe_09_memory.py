"""C9 Memory: Agent Platform Sessions + Memory Bank (vertexai.Client.agent_engines.sessions / .memories, and raw REST)."""
from _common import *
import json

s = Step()
P = f"/v1beta1/projects/{PROJECT}/locations/{LOC}"


def engine():
    r = call("POST", P + "/reasoningEngines", {"displayName": "mem-host", "spec": {"vyomiAgentSpec": {"instructions": "x", "tools": []}}})
    s.eng = (r.get("response") or r)["name"]
    return s.eng


def sess_sdk():
    c = vertex_client()
    op = c.agent_engines.sessions.create(name=s.eng, user_id="duty-manager")
    assert op.response and op.response.name, op
    return op.response.name


def mem_sdk():
    c = vertex_client()
    c.agent_engines.memories.create(name=s.eng, fact="Duty manager prefers level 3 chiller reports", scope={"user_id": "duty-manager"})
    got = list(c.agent_engines.memories.retrieve(name=s.eng, scope={"user_id": "duty-manager"}, similarity_search_params={"search_query": "chiller", "top_k": 1}))
    assert got and "chiller" in got[0].memory.fact.lower(), got
    return "memory created and retrieved via vertexai.Client"


def raw():
    call("POST", f"/v1beta1/{s.eng}/sessions", {"userId": "u1"})
    ss = call("GET", f"/v1beta1/{s.eng}/sessions")
    assert ss.get("sessions"), ss
    call("POST", f"/v1beta1/{s.eng}/memories", {"fact": "Prefers level 3 chiller reports", "scope": {"user_id": "u1"}})
    r = call("POST", f"/v1beta1/{s.eng}/memories:retrieve", {"scope": {"user_id": "u1"}, "similaritySearchParams": {"searchQuery": "chiller", "topK": 1}})
    assert r.get("retrievedMemories"), r
    return "raw REST sessions + memories:retrieve ok (embedding = %s)" % str(r["retrievedMemories"][0])[:100]


def generate():
    r = http().post(endpoint() + f"/v1beta1/{s.eng}/memories:generate", json={"directContentsSource": {"events": [{"content": {"role": "user", "parts": [{"text": "I always want the level 3 chiller report on Mondays."}]}}]}, "scope": {"user_id": "u1"}})
    if r.status_code == 503:
        raise Blocked("memories:generate extracts facts with a model: HTTP 503 (no model); shape accepted")
    assert r.status_code == 200, (r.status_code, r.text[:200])
    return r.text[:100]


s("create a reasoning engine to host sessions/memories", engine)
if hasattr(s, "eng"):
    s("Sessions: vertexai.Client.agent_engines.sessions.create", sess_sdk)
    s("Memory Bank: vertexai.Client.agent_engines.memories.create + retrieve", mem_sdk)
    s("Sessions + Memory Bank over raw REST", raw)
    s("Memory Bank memories:generate (LLM fact extraction)", generate)
s.finish()
