"""C3: Vertex AI Agent Engine hosting the supervisor + sub-agents. The agent code is facilities/agents.py (LangGraph), packaged from source."""
import json, os, shutil, tempfile
from ..runtime import NAMES, LANE, Blocked
from .. import deploy
from ... import agents

QUESTION = "Boiler B-12 is at 34 psi. What does the SOP say, and please raise a work order for it. How many work orders are open?"


def package_dir():
    """Source package for Agent Engine: facilities/ (the LangGraph agents + GCP adapter) next to the engine entry module."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    d = os.path.relpath(tempfile.mkdtemp(prefix="facilities-engine-", dir=os.path.realpath(os.getcwd())))     # the SDK requires source packages inside the project (cwd)
    shutil.copytree(os.path.join(root, "facilities"), os.path.join(d, "facilities"), ignore=shutil.ignore_patterns("__pycache__", "lambdas", "functions"))
    shutil.copy(os.path.join(root, "facilities", "gcp", "agent_engine_app.py"), os.path.join(d, "agent_engine_app.py"))
    with open(os.path.join(d, "requirements.txt"), "w") as f:
        f.write("google-cloud-aiplatform\ngoogle-cloud-pubsub\ngoogle-cloud-firestore\ngoogle-genai\nlanggraph\nrequests\n")
    return d


def run(ctx):
    def create():
        os.environ.setdefault("STORAGE_EMULATOR_HOST", ctx.endpoint)       # the standard google-cloud-storage emulator variable (the SDK stages the package in GCS)
        src = package_dir()
        client = ctx.vertex("v1beta1")
        gcs = ctx.storage()
        try:
            gcs.create_bucket("facilities-agent-staging")
        except Exception:
            pass
        env = {"VYOMI_ENDPOINT": ctx.endpoint, "GOOGLE_CLOUD_PROJECT": ctx.project, "KB_URI": ctx.state.get("kb_uri", ""), "ASSET_URI": ctx.state.get("asset_uri", ""),
               "GATEWAY_MCP_URL": ctx.state.get("gateway_mcp_url", ""), "MCP_TOOLS": json.dumps(sorted(ctx.state.get("mcp_tools", [])))}
        eng = client.agent_engines.create(config={
            "display_name": NAMES["engine"], "staging_bucket": "gs://facilities-agent-staging", "source_packages": [src], "entrypoint_module": "agent_engine_app",
            "entrypoint_object": "agent", "requirements_file": os.path.join(src, "requirements.txt"), "env_vars": env,
            "class_methods": [{"name": "query", "api_mode": "", "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}, "user": {"type": "string"}}, "required": ["prompt"]}}]})
        ctx.state["engine"] = eng
        name = getattr(getattr(eng, "api_resource", None), "name", None) or getattr(eng, "name", "")
        ctx.state["engine_name"] = name
        return f"Agent Engine {name}"
    ctx.step("vertex agent engine: create from source (supervisor + sub-agents, entrypoint agent_engine_app.agent)", create, lane=LANE["engine"])
    eng = ctx.state.get("engine")

    def invoke():
        out = eng.query(prompt=QUESTION, user=ctx.state.get("user", "anonymous"))
        assert out["pid"] != os.getpid(), "agent ran in the caller's process"
        names = {s["name"] for s in out["spans"]}
        for need in ("supervisor.plan", "agent:facilities", "agent:maintenance", "agent:analytics", "supervisor.synthesize"):
            assert need in names, f"{need} did not run in the hosted agent; route={out['route']}"
        tools = [t["tool"] for t in out["tools"]]
        assert "kb_search" in tools and "asset_status" in tools, tools
        ctx.state["result"], ctx.state["runtime_pid"] = out, out["pid"]
        return f"hosted in pid {out['pid']} route={out['route']} tools={tools} via={sorted({t['via'] for t in out['tools']})}"
    if eng is not None:
        ctx.step("agent engine: query runs the supervisor + Facilities/Maintenance/Analytics sub-agents in the hosted runtime", invoke, lane=LANE["engine"])
    if "result" not in ctx.state:       # hosted run unavailable: keep downstream components testable with the in-process graph
        def run_graph():
            try:
                ctx.state["result"] = agents.ask(ctx, QUESTION, ctx.state.get("user", "anonymous"))
            except Exception as e:
                ctx.state["agent_error"] = f"{type(e).__name__}: {str(e)[:160]}"
                ctx.state["agent_blocked_by"] = ctx.blocked_lane(e, None) or LANE["sandbox"]
                raise
            return "fallback: supervisor graph run client-side (hosted run unavailable); this does NOT count as the hosted runtime"
        ctx.step("langgraph: client-side fallback so later components can run", run_graph)
