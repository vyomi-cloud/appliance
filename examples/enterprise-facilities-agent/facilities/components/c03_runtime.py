"""C3: AgentCore Runtime hosting the supervisor + sub-agents. The agent code is facilities/agents.py (LangGraph)."""
import json, time
from ..runtime import NAMES, Blocked
from .. import agents

QUESTION = "Boiler B-12 is at 34 psi. What does the SOP say, and please raise a work order for it. How many work orders are open?"


def run(ctx):
    ac = ctx.client("bedrock-agentcore-control")

    def create():
        r = ac.create_agent_runtime(agentRuntimeName="facilities_supervisor",
                                    agentRuntimeArtifact={"containerConfiguration": {"containerUri": f"123456789012.dkr.ecr.{ctx.region}.amazonaws.com/facilities-supervisor:1"}},
                                    roleArn=NAMES["role"], networkConfiguration={"networkMode": "PUBLIC"})
        ctx.state["runtime_arn"], ctx.state["runtime_id"] = r["agentRuntimeArn"], r["agentRuntimeId"]
        return r["agentRuntimeId"]
    ctx.step("agentcore-control: CreateAgentRuntime facilities-supervisor", create, lane="agentcore")
    if ctx.state.get("runtime_id"):
        def ready():
            for _ in range(30):
                s = ac.get_agent_runtime(agentRuntimeId=ctx.state["runtime_id"])["status"]
                if s != "CREATING":
                    break
                time.sleep(0.5)
            assert s == "READY", s
            return f"runtime status {s}"
        ctx.step("agentcore-control: GetAgentRuntime", ready)

    def run_graph():
        st = agents.ask(ctx, QUESTION, ctx.state.get("user", "anonymous"))
        ctx.state["result"] = st
        names = {s["name"] for s in st["spans"]}
        for need in ("agent:facilities", "agent:maintenance", "agent:analytics", "supervisor.synthesize"):
            assert need in names, f"{need} did not run; route={st['route']}"
        tools = [t["tool"] for t in st["tools"]]
        assert "kb_search" in tools and "asset_status" in tools, tools
        return f"route={st['route']} tools={tools} routed_by={'model' if st['llm_used'] else 'keyword rules (no model)'}"
    ctx.step("langgraph: supervisor routes to Facilities, Maintenance, Analytics sub-agents", run_graph)

    def invoke():
        r = ctx.client("bedrock-agentcore").invoke_agent_runtime(agentRuntimeArn=ctx.state["runtime_arn"], payload=json.dumps({"prompt": QUESTION}).encode(),
                                                                 contentType="application/json", accept="application/json")
        body = r["response"].read() if hasattr(r.get("response"), "read") else b""
        assert body, "empty runtime response"
        return f"runtime answered ({len(body)} bytes)"
    if ctx.state.get("runtime_arn"):
        ctx.step("bedrock-agentcore: InvokeAgentRuntime (hosted agent)", invoke, lane="agentcore")
