"""C9: AgentCore Memory: short-term events per session, long-term records retrieved by the agent."""
import time
from ..runtime import NAMES, Blocked


def run(ctx):
    ac, dp = ctx.client("bedrock-agentcore-control"), ctx.client("bedrock-agentcore")

    def create():
        r = ac.create_memory(name="facilities_memory", eventExpiryDuration=30,
                             memoryStrategies=[{"semanticMemoryStrategy": {"name": "facts"}}])["memory"]
        ctx.state["memory_id"] = r["id"]
        return r["id"]
    ctx.step("agentcore-control: CreateMemory facilities-memory", create, lane="agentcore")
    mid = ctx.state.get("memory_id")
    if not mid:
        return
    res = ctx.state.get("result", {})

    def write():
        for role, text in (("USER", res.get("question", "q")), ("ASSISTANT", res.get("answer", "a"))):
            dp.create_event(memoryId=mid, actorId="maria", sessionId="s1", eventTimestamp=time.time(),
                            payload=[{"conversational": {"content": {"text": text}, "role": role}}])
        return "2 conversational events written"
    ctx.step("bedrock-agentcore: CreateEvent (user + assistant turn)", write, lane="agentcore")

    def read():
        ev = dp.list_events(memoryId=mid, actorId="maria", sessionId="s1", includePayloads=True)["events"]
        assert len(ev) >= 2, ev
        return f"{len(ev)} events read back for the session"
    ctx.step("bedrock-agentcore: ListEvents (session replay)", read, lane="agentcore")

    def longterm():
        r = dp.retrieve_memory_records(memoryId=mid, namespace="/facts/maria/", searchCriteria={"searchQuery": "boiler", "topK": 3})
        return f"{len(r.get('memoryRecordSummaries', []))} long-term records"
    ctx.step("bedrock-agentcore: RetrieveMemoryRecords (long-term)", longterm, lane="agentcore")
