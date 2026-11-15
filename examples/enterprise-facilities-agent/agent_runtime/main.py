"""AgentCore Runtime entrypoint for the Facilities agent: the supervisor + 3 sub-agents (LangGraph, facilities/agents.py) hosted
behind the AgentCore contract (POST /invocations, GET /ping). Deployed as a code zip (facilities/ package + this file).
Same shape as a bedrock-agentcore app:   @app.entrypoint def invoke(payload, context).
The agent finds its collaborators the way a real hosted agent does: standard AWS SDK env (AWS_ENDPOINT_URL, region, credentials)
and service discovery by the reference names - nothing is passed in from the caller's process."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from facilities import agents, mcp
from facilities.runtime import Ctx, NAMES


def _wire(ctx):
    sf = ctx.client("stepfunctions")
    for sm in sf.list_state_machines()["stateMachines"]:
        if sm["name"] == NAMES["sm"]:
            ctx.state["sm_arn"] = sm["stateMachineArn"]
    try:
        ac = ctx.client("bedrock-agentcore-control")
        gw = next(g for g in ac.list_gateways()["items"] if g["name"] == NAMES["gateway"])
        names = {t["name"] for t in mcp.call(ctx, gw["gatewayId"], "tools/list")["tools"]}
        if any("kb_search" in n for n in names) and any("asset_status" in n for n in names):
            ctx.state.update(gateway_id=gw["gatewayId"], mcp_tools=names, gateway_tools_ok=True)
    except Exception as e:                       # no gateway: tools fall back to direct Lambda invoke (recorded per tool call as `via`)
        ctx.state["gateway_error"] = f"{type(e).__name__}: {str(e)[:100]}"


def handler(payload, context):
    payload = payload if isinstance(payload, dict) else {"prompt": str(payload)}
    ctx = Ctx(os.environ["AWS_ENDPOINT_URL"], os.environ.get("AWS_REGION", "us-east-1"), out=lambda *_: None)
    _wire(ctx)
    st = agents.ask(ctx, payload.get("prompt") or payload.get("question", ""), payload.get("user", "anonymous"))
    res = {k: st.get(k) for k in ("answer", "route", "citations", "analytics", "approval", "llm_used", "tools", "spans")}
    res.update(response=st.get("answer"), sessionId=getattr(context, "session_id", None), gateway=ctx.state.get("gateway_id"),
               gateway_error=ctx.state.get("gateway_error"), pid=os.getpid())
    if payload.get("stream"):
        def events():
            yield {"event": "route", "route": res["route"]}
            for s in res["spans"] or []:
                yield {"event": "span", "name": s["name"]}
            yield {"event": "final", **res}
        return events()
    return res
