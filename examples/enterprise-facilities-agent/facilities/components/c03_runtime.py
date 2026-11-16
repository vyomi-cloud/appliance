"""C3: AgentCore Runtime hosting the supervisor + sub-agents. The agent code is facilities/agents.py (LangGraph)."""
import io, json, os, time, zipfile
from ..runtime import NAMES, Blocked
from .. import agents

QUESTION = "Boiler B-12 is at 34 psi. What does the SOP say, and please raise a work order for it. How many work orders are open?"


def package():
    """The deployment package: facilities/ (the LangGraph agents) + agent_runtime/main.py, the AgentCore entrypoint."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(root, "agent_runtime", "main.py"), "main.py")
        for f in ("__init__.py", "agents.py", "runtime.py", "mcp.py"):
            z.write(os.path.join(root, "facilities", f), "facilities/" + f)
    return b.getvalue()


def run(ctx):
    ac = ctx.client("bedrock-agentcore-control")
    s3 = ctx.client("s3")
    key = "agent-runtime/facilities-supervisor.zip"

    def create():
        s3.put_object(Bucket=NAMES["assets"] if _bucket_ok(s3, NAMES["assets"]) else NAMES["bucket"], Key=key, Body=package())
        bkt = NAMES["assets"] if _bucket_ok(s3, NAMES["assets"]) else NAMES["bucket"]
        r = ac.create_agent_runtime(agentRuntimeName="facilities_supervisor",
                                    agentRuntimeArtifact={"codeConfiguration": {"code": {"s3": {"bucket": bkt, "prefix": key}}, "runtime": "PYTHON_3_12", "entryPoint": ["main.py"]}},
                                    roleArn=NAMES["role"], networkConfiguration={"networkMode": "PUBLIC"}, environmentVariables={"AGENT_NAME": "facilities-supervisor"})
        ctx.state["runtime_arn"], ctx.state["runtime_id"] = r["agentRuntimeArn"], r["agentRuntimeId"]
        return r["agentRuntimeId"]
    ctx.step("agentcore-control: CreateAgentRuntime facilities-supervisor (code deploy: zip in S3 + entryPoint)", create, lane="agentcore")
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

    def invoke(sid):
        r = ctx.client("bedrock-agentcore").invoke_agent_runtime(
            agentRuntimeArn=ctx.state["runtime_arn"], runtimeSessionId=sid, contentType="application/json", accept="application/json",
            payload=json.dumps({"prompt": QUESTION, "user": ctx.state.get("user", "anonymous")}).encode())
        assert r["runtimeSessionId"] == sid
        return json.loads(r["response"].read())

    def hosted():
        sid = "facilities-session-" + "a" * 20
        out = invoke(sid)
        assert out["pid"] != os.getpid(), "agent ran in the caller's process"
        st = dict(out, spans=out["spans"], tools=out["tools"])
        names = {s["name"] for s in st["spans"]}
        for need in ("supervisor.plan", "agent:facilities", "agent:maintenance", "agent:analytics", "supervisor.synthesize"):
            assert need in names, f"{need} did not run in the hosted agent; route={st['route']}"
        tools = [t["tool"] for t in st["tools"]]
        assert "kb_search" in tools and "asset_status" in tools, tools
        ctx.state["result"], ctx.state["runtime_pid"] = st, out["pid"]
        return f"hosted in pid {out['pid']} route={st['route']} tools={tools} via={sorted({t['via'] for t in st['tools']})}"
    if ctx.state.get("runtime_arn"):
        ctx.step("bedrock-agentcore: InvokeAgentRuntime runs the supervisor + Facilities/Maintenance/Analytics sub-agents in the hosted runtime", hosted, lane="agentcore")

        def isolation():
            other = invoke("facilities-session-" + "b" * 20)
            again = invoke("facilities-session-" + "a" * 20)
            assert other["pid"] != ctx.state["runtime_pid"], "two sessions shared one agent process"
            assert again["pid"] == ctx.state["runtime_pid"], "same session did not reuse its agent process"
            return f"session a pid {again['pid']}, session b pid {other['pid']}"
        if ctx.state.get("runtime_pid"):
            ctx.step("bedrock-agentcore: runtimeSessionId isolation (one agent process per session, reused within a session)", isolation, lane="agentcore")

            def stop():
                ctx.client("bedrock-agentcore").stop_runtime_session(agentRuntimeArn=ctx.state["runtime_arn"], runtimeSessionId="facilities-session-" + "b" * 20)
                return "StopRuntimeSession ok"
            ctx.step("bedrock-agentcore: StopRuntimeSession", stop, lane="agentcore")
    if "result" not in ctx.state:       # hosted run failed: keep downstream components testable with the in-process graph
        def run_graph():
            ctx.state["result"] = agents.ask(ctx, QUESTION, ctx.state.get("user", "anonymous"))
            return "fallback: supervisor graph run client-side (hosted run unavailable)"
        ctx.step("langgraph: client-side fallback so later components can run", run_graph)


def _bucket_ok(s3, b):
    try:
        s3.head_bucket(Bucket=b)
        return True
    except Exception:
        return False
