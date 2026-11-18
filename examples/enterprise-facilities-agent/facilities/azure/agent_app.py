"""Container App entrypoint for the Facilities supervisor: the LangGraph supervisor + Facilities / Maintenance / Analytics sub-agents (facilities/agents.py)
behind a tiny HTTP API (POST /query). Azure has no hosted-agent runtime like AgentCore or Agent Engine, so the agent code is packaged as a container and run
on Azure Container Apps (ingress on 8080). Collaborators come from environment variables set on the container app; on real Azure these would be
managed-identity endpoints (no key variables). Build: `docker build` a python:3.12 image with this repo's `facilities/` package and run
`uvicorn facilities.azure.agent_app:app --port 8080`."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from fastapi import FastAPI

app = FastAPI(title="facilities-supervisor")
_ctx = None


def ctx():
    global _ctx
    if _ctx is None:
        from facilities.azure.runtime import AzCtx
        _ctx = AzCtx(os.environ["VYOMI_ENDPOINT"], out=lambda *_: None, http_endpoint=os.environ.get("VYOMI_HTTP_ENDPOINT"), amqp_port=os.environ.get("VYOMI_AMQP_PORT"))
        if os.environ.get("FUNC_KEY"):
            _ctx.state["func_key"] = os.environ["FUNC_KEY"]
        if os.environ.get("APIM_KEY"):
            _ctx.state.update(apim_key=os.environ["APIM_KEY"], gateway_tools_ok=os.environ.get("GATEWAY_TOOLS_OK") == "1", apim_mcp_ok=os.environ.get("APIM_MCP_OK") == "1",
                              mcp_tools=set(json.loads(os.environ.get("MCP_TOOLS", "[]"))))
    return _ctx


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/query")
def query(body: dict):
    from facilities import agents
    st = agents.ask(ctx(), body["prompt"], body.get("user", "anonymous"))
    out = {k: st.get(k) for k in ("answer", "route", "citations", "analytics", "approval", "llm_used", "tools", "spans")}
    out["pid"] = os.getpid()
    return out


if __name__ == "__main__":          # the Container Apps entrypoint: listen on $PORT (the simulator's runtime sets it)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8080")))
