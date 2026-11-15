"""C4: AgentCore Gateway: tool catalog over the Lambda tools (MCP), Cedar policy."""
import time
from ..runtime import NAMES, Blocked
from .. import mcp as mcp_client

TOOLS = [("kb_search", "facilities-kb-search", "Search the facilities knowledge base (read-only).", {"query": {"type": "string"}}),
         ("asset_status", "facilities-asset-status", "Look up an asset and its work orders (read-only).", {"asset_id": {"type": "string"}})]


def run(ctx):
    ac = ctx.client("bedrock-agentcore-control")

    def gw():
        r = ac.create_gateway(name=NAMES["gateway"], roleArn=NAMES["role"], protocolType="MCP", authorizerType="AWS_IAM")
        ctx.state["gateway_id"] = r["gatewayId"]
        ctx.state["gateway_url"] = r.get("gatewayUrl", "")
        return f"gateway {r['gatewayId']} {r.get('gatewayUrl', '')}"
    ctx.step("agentcore-control: CreateGateway facilities-gateway", gw, lane="agentcore")
    gid = ctx.state.get("gateway_id")
    if not gid:
        return

    def ready():
        for _ in range(30):
            g = ac.get_gateway(gatewayIdentifier=gid)
            if g["status"] == "READY":
                return "gateway READY"
            time.sleep(0.5)
        raise AssertionError(f"gateway status {g['status']}")
    ctx.step("agentcore-control: GetGateway until READY", ready)

    def targets():
        for name, fn, desc, props in TOOLS:
            ac.create_gateway_target(
                gatewayIdentifier=gid, name=name.replace("_", "-"),
                targetConfiguration={"mcp": {"lambda": {"lambdaArn": f"arn:aws:lambda:{ctx.region}:123456789012:function:{fn}",
                                                          "toolSchema": {"inlinePayload": [{"name": name, "description": desc,
                                                                                            "inputSchema": {"type": "object", "properties": props, "required": list(props)}}]}}}},
                credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}])
        return f"{len(TOOLS)} Lambda targets registered"
    ctx.step("agentcore-control: CreateGatewayTarget (Lambda tools)", targets, lane="agentcore")

    def targets_ready():
        for _ in range(30):
            ts = ac.list_gateway_targets(gatewayIdentifier=gid)["items"]
            if ts and all(t["status"] == "READY" for t in ts):
                return f"{len(ts)} targets READY"
            time.sleep(0.5)
        raise AssertionError(f"targets not READY: {[t['status'] for t in ts]}")
    ctx.step("agentcore-control: ListGatewayTargets until READY", targets_ready)

    def mcp(method, params=None):
        return mcp_client.call(ctx, gid, method, params)

    def list_tools():
        tools = mcp("tools/list")["tools"]
        names = {t["name"] for t in tools}
        assert any("kb_search" in n for n in names), names
        ctx.state["mcp_tools"] = names
        return f"MCP tools/list: {sorted(names)}"
    ctx.step("gateway data plane: MCP tools/list", list_tools, lane="agentcore")

    def call_tool():
        n = [n for n in ctx.state["mcp_tools"] if "asset_status" in n][0]
        res = mcp("tools/call", {"name": n, "arguments": {"asset_id": "B-12"}})
        assert not res.get("isError"), res
        ctx.state["gateway_tools_ok"] = True
        return "MCP tools/call asset_status -> ok"
    if ctx.state.get("mcp_tools"):
        ctx.step("gateway data plane: MCP tools/call", call_tool)

    def cedar():
        pe = ac.create_policy_engine(name="facilities_policies")["policyEngineId"]
        stmt = 'permit(principal, action == AgentCore::Action::"asset_status___asset_status", resource);'
        ac.create_policy(policyEngineId=pe, name="read_only_tools", definition={"cedar": {"statement": stmt}})
        return f"policy engine {pe} with a Cedar permit policy"
    ctx.step("agentcore-control: CreatePolicyEngine + Cedar policy (read-only tools)", cedar, lane="agentcore")
