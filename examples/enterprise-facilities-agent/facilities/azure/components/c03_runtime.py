"""C3: agent runtime. Foundry Agents (Assistants) for the supervisor + three sub-agents; the LangGraph app (facilities/agents.py) hosted on an Azure Container App.
ASSEMBLED, not native: Azure has no hosted-agent runtime like AgentCore Runtime or Vertex Agent Engine, so the agent code runs as a container."""
import time
from ..runtime import NAMES, LANE, Blocked, RG, LOC
from ... import agents

QUESTION = "Boiler B-12 is at 34 psi. What does the SOP say, and please raise a work order for it. How many work orders are open?"
TOOL_DEFS = [{"type": "function", "function": {"name": "kb_search", "description": "Search the facilities knowledge base (read-only).",
                                                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
             {"type": "function", "function": {"name": "asset_status", "description": "Look up an asset and its work orders (read-only).",
                                                "parameters": {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}}},
             {"type": "function", "function": {"name": "create_work_order", "description": "Request a work order (needs human approval).",
                                                "parameters": {"type": "object", "properties": {"asset_id": {"type": "string"}, "summary": {"type": "string"}}, "required": ["asset_id", "summary"]}}}]


def run(ctx):
    def foundry():
        a = ctx.agents()
        made = {}
        for name, instr, tools in ((NAMES["supervisor"], "You route facilities requests to the Facilities, Maintenance and Analytics agents and combine their answers.", TOOL_DEFS),
                                   ("facilities_facilities", "Answer from the knowledge base only, with citations.", TOOL_DEFS[:1]),
                                   ("facilities_maintenance", "Look up assets and raise work orders (approval required).", TOOL_DEFS[1:]),
                                   ("facilities_analytics", "Count and summarise work orders.", [])):
            made[name] = a.create_agent(model=NAMES["chat"], name=name, instructions=instr, tools=tools).id
        ctx.state["foundry_agents"] = made
        got = {x.name for x in a.list_agents()}
        assert set(made) <= got, got
        return f"project {NAMES['project']}: supervisor + 3 sub-agents created and listed ({sorted(made)})"
    ctx.step("foundry agents: create supervisor + Facilities/Maintenance/Analytics agents (azure-ai-agents)", foundry, lane=LANE["ai"])

    def run_agent():
        a = ctx.agents()
        sid = ctx.state["foundry_agents"][NAMES["supervisor"]]
        th = a.threads.create()
        a.messages.create(thread_id=th.id, role="user", content=QUESTION)
        r = a.runs.create(thread_id=th.id, agent_id=sid)
        for _ in range(60):
            r = a.runs.get(thread_id=th.id, run_id=r.id)
            if str(r.status).lower().split(".")[-1] not in ("queued", "in_progress"):
                break
            time.sleep(0.5)
        st = str(r.status).lower().split(".")[-1]
        if st == "failed":
            raise RuntimeError(f"run failed: {getattr(r.last_error, 'message', r.last_error)}")
        assert st in ("completed", "requires_action"), st
        msgs = list(a.messages.list(thread_id=th.id))
        assert msgs, "no messages on the thread"
        return f"supervisor run {st}; thread has {len(msgs)} message(s)"
    if ctx.state.get("foundry_agents"):
        ctx.step("foundry agents: a run of the supervisor on a thread completes (needs a model)", run_agent, lane=LANE["ai"])

    def host():
        from azure.mgmt.appcontainers import ContainerAppsAPIClient
        c = ctx.arm(ContainerAppsAPIClient)
        c.managed_environments.begin_create_or_update(RG, NAMES["capp_env"], {"location": LOC, "properties": {}}).result()
        env = ctx.rid("Microsoft.App", "managedEnvironments", NAMES["capp_env"])
        app = c.container_apps.begin_create_or_update(RG, NAMES["capp"], {"location": LOC, "properties": {"managedEnvironmentId": env, "configuration": {"ingress": {"external": True, "targetPort": 8080}},
            "template": {"containers": [{"name": "supervisor", "image": "mcr.microsoft.com/k8se/quickstart:latest", "env": [
                {"name": "VYOMI_ENDPOINT", "value": ctx.endpoint}, {"name": "VYOMI_HTTP_ENDPOINT", "value": ctx.http}, {"name": "VYOMI_AMQP_PORT", "value": str(ctx.amqp_port)}]}]}}}).result()
        ctx.state["capp"] = app
        return f"container app {app.name} fqdn={app.latest_revision_fqdn} state={app.provisioning_state}"
    ctx.step("container apps: environment + facilities-supervisor app via ARM (azure-mgmt-appcontainers)", host)

    def ingress():
        import requests
        app = ctx.state["capp"]
        fqdn = app.latest_revision_fqdn or (app.configuration.ingress.fqdn if app.configuration and app.configuration.ingress else "")
        assert fqdn, "the container app has no ingress FQDN"
        base = fqdn if fqdn.startswith("http") else f"https://{fqdn}"
        try:
            r = requests.post(base + "/query", json={"prompt": QUESTION, "user": ctx.state.get("user", "anonymous")}, timeout=60)
        except Exception as e:
            raise Blocked(LANE["host"], f"the simulator does not run the container image or expose a reachable ingress ({type(e).__name__}: {str(e)[:100]})")
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        out = r.json()
        names = {s["name"] for s in out["spans"]}
        assert {"supervisor.plan", "agent:facilities", "agent:maintenance", "agent:analytics", "supervisor.synthesize"} <= names, names
        ctx.state["result"] = out
        return f"hosted in pid {out['pid']} route={out['route']}"
    if ctx.state.get("capp") is not None:
        ctx.step("container app: POST /query on the ingress runs the LangGraph supervisor + sub-agents in the hosted container", ingress)

    if "result" not in ctx.state:       # hosted run unavailable: keep downstream components testable with the in-process graph
        def run_graph():
            try:
                ctx.state["result"] = agents.ask(ctx, QUESTION, ctx.state.get("user", "anonymous"))
            except Exception as e:
                ctx.state["agent_error"] = f"{type(e).__name__}: {str(e)[:160]}"
                ctx.state["agent_blocked_by"] = ctx.blocked_lane(e, None) or LANE["runtime"]
                raise
            return "fallback: supervisor graph run client-side (hosted run unavailable); this does NOT count as the hosted runtime"
        ctx.step("langgraph: client-side fallback so later components can run", run_graph)
    ctx.note("Runtime is ASSEMBLED: Foundry Agents for the agent definitions plus a LangGraph app in a Container App. Azure has no hosted-agent runtime comparable to AgentCore Runtime.")
