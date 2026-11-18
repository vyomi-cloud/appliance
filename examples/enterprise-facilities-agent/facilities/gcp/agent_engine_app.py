"""Vertex AI Agent Engine entrypoint for the Facilities supervisor: the LangGraph supervisor + Facilities / Maintenance / Analytics sub-agents (facilities/agents.py).
Deployed from source (vertexai.Client.agent_engines.create with source_packages + entrypoint_module / entrypoint_object + class_methods).
Agent Engine custom-agent contract: a class with set_up() and the registered query method. The agent finds its collaborators from environment variables
set at deploy time; on real GCP it would use ADC and the real endpoints (no *_ENDPOINT variables)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class FacilitiesSupervisor:
    def set_up(self):
        from facilities import agents
        from facilities.gcp.runtime import GcpCtx
        self.agents = agents
        self.ctx = GcpCtx(os.environ["VYOMI_ENDPOINT"], os.environ.get("GOOGLE_CLOUD_REGION", "us-central1"), out=lambda *_: None)
        for k, env in (("kb_uri", "KB_URI"), ("asset_uri", "ASSET_URI"), ("gateway_mcp_url", "GATEWAY_MCP_URL")):
            if os.environ.get(env):
                self.ctx.state[k] = os.environ[env]
        if os.environ.get("MCP_TOOLS"):
            self.ctx.state.update(mcp_tools=set(json.loads(os.environ["MCP_TOOLS"])), gateway_tools_ok=True)

    def query(self, *, prompt: str, user: str = "anonymous") -> dict:
        st = self.agents.ask(self.ctx, prompt, user)
        out = {k: st.get(k) for k in ("answer", "route", "citations", "analytics", "approval", "llm_used", "tools", "spans")}
        out.update(pid=os.getpid(), gateway_error=self.ctx.state.get("gateway_error"))
        return out


agent = FacilitiesSupervisor()
