"""C4: agent gateway (Agent Platform agentGateways): MCP server registry over the tool functions + Cedar agent policy (read-only tools)."""
import time
from ..runtime import NAMES, LANE, Blocked
from ..io import mcp_call

CEDAR = ('permit(principal, action == AgentCore::Action::"{t}___kb_search", resource);\n'
         'permit(principal, action == AgentCore::Action::"{t}___asset_status", resource);')


def run(ctx):
    """No Google client library exists for agentGateways / mcpServers / agentPolicies (the control plane is not a public API); the calls use
    google-auth AuthorizedSession against the documented resource paths."""
    P = f"/v1/{ctx.parent}"
    mcp_uri = ctx.state.get("mcp_uri")
    if not mcp_uri:
        ctx.step("agent gateway: needs the MCP tool server function", lambda: (_ for _ in ()).throw(Blocked(LANE["sandbox"], "MCP tool function was not deployed (component 7)")))
        return

    def register():
        r = ctx.api("POST", P + f"/mcpServers?mcpServerId={NAMES['mcp']}", {"endpoint": mcp_uri, "displayName": "Facilities tools (MCP)", "description": "kb_search, asset_status",
                                                                       "authentication": {"apiKey": {"value": "Bearer vyomi-local"}}})   # credential the gateway presents to the tool server (Authorization header)
        return r.get("name", str(r)[:100])
    ctx.step("agent registry: register the facilities MCP server (mcpServers)", register)

    def gw():
        ctx.api("POST", P + f"/agentGateways?agentGatewayId={NAMES['gateway']}", {"displayName": "Facilities gateway", "authorization": {"type": "NONE"}})
        for _ in range(30):
            g = ctx.api("GET", P + f"/agentGateways/{NAMES['gateway']}")
            if g.get("state") == "ACTIVE":
                ctx.state["gateway_mcp_url"] = g["mcpEndpoint"]
                return f"gateway ACTIVE, mcpEndpoint {g['mcpEndpoint']}"
            time.sleep(0.5)
        raise AssertionError(f"gateway state {g.get('state')}")
    ctx.step("agent gateway: create facilities-gateway and wait ACTIVE", gw)
    if "gateway_mcp_url" not in ctx.state:
        return

    def attach():
        ctx.api("POST", P + f"/agentGateways/{NAMES['gateway']}:attachMcpServer", {"mcpServer": f"{ctx.parent}/mcpServers/{NAMES['mcp']}"})
        g = ctx.api("GET", P + f"/agentGateways/{NAMES['gateway']}")
        assert g.get("attachedMcpServers"), g
        return f"MCP server attached: {g['attachedMcpServers']}"
    ctx.step("agent gateway: attach the MCP server", attach)

    def tools():
        for _ in range(20):
            names = {t["name"] for t in mcp_call(ctx, ctx.state["gateway_mcp_url"], "tools/list")["tools"]}
            if names:
                break
            time.sleep(0.5)
        if not names:       # the gateway reaches the MCP server function: find out whether the function itself is the problem
            from .. import deploy
            deploy.call_function(ctx, mcp_uri, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert any(n.endswith("kb_search") for n in names) and any(n.endswith("asset_status") for n in names), names
        ctx.state["mcp_tools"] = names
        return f"MCP tools/list through the gateway: {sorted(names)}"
    ctx.step("gateway data plane: MCP tools/list", tools)

    def call():
        n = [n for n in ctx.state["mcp_tools"] if n.endswith("asset_status")][0]
        res = mcp_call(ctx, ctx.state["gateway_mcp_url"], "tools/call", {"name": n, "arguments": {"asset_id": "B-12"}})
        assert not res.get("isError"), res
        ctx.state["gateway_tools_ok"] = True
        return "MCP tools/call asset_status -> ok"
    if ctx.state.get("mcp_tools"):
        ctx.step("gateway data plane: MCP tools/call", call)

    def cedar():
        target = [n for n in ctx.state.get("mcp_tools", [NAMES["mcp"] + "___x"])][0].split("___")[0]
        ctx.api("POST", P + f"/agentPolicies?agentPolicyId={NAMES['policy']}", {"cedarPolicy": CEDAR.format(t=target), "enforcementMode": "ENFORCE", "displayName": "read-only facilities tools"})
        allow = ctx.api("POST", P + f"/agentPolicies/{NAMES['policy']}:test", {"principal": "maria", "tool": f"{target}___asset_status", "arguments": {}})
        deny = ctx.api("POST", P + f"/agentPolicies/{NAMES['policy']}:test", {"principal": "maria", "tool": f"{target}___create_work_order", "arguments": {}})
        assert allow["decision"] == "ALLOW" and deny["decision"] == "DENY", (allow, deny)
        ctx.api("POST", P + f"/agentGateways/{NAMES['gateway']}:attachPolicy", {"policy": f"{ctx.parent}/agentPolicies/{NAMES['policy']}"})
        return "Cedar: read tool ALLOW, write tool DENY; policy attached to the gateway in ENFORCE mode"
    ctx.step("agent policy: Cedar permit for read-only tools, write tool denied, attached to the gateway", cedar)
