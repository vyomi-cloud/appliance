"""C4: APIM as the tool / MCP gateway: the tool catalog (API + operations), subscription key, rate limit, an APIM policy expression that keeps write tools behind
an approval id, and an MCP server API (tools/list, tools/call). There is NO Cedar equivalent on Azure: the substitute is APIM policy expressions (choose/when)."""
import requests
from ..runtime import NAMES, LANE, Blocked, RG
from ..io import apim_headers, apim_mcp

DENY_WRITE = ('<policies><inbound><base/><choose><when condition="@(string.IsNullOrEmpty(context.Request.Headers.GetValueOrDefault(&quot;x-approval-id&quot;,&quot;&quot;)))">'
              '<return-response><set-status code="403" reason="Forbidden"/><set-header name="Content-Type" exists-action="override"><value>application/json</value></set-header>'
              '<set-body>{"error":"write tools need an approved request (x-approval-id)"}</set-body></return-response></when></choose></inbound>'
              '<backend><base/></backend><outbound><base/></outbound><on-error><base/></on-error></policies>')


def run(ctx):
    apim = ctx.state.get("apim_client")
    if apim is None or not ctx.state.get("apim_key"):
        ctx.step("apim gateway: needs the APIM service and subscription key from component 1", lambda: (_ for _ in ()).throw(Blocked(LANE["gateway"], "APIM tools API was not created (component 1 edge)")))
        return

    def catalog():
        ops = sorted(o.name for o in apim.api_operation.list_by_api(RG, NAMES["apim"], "tools"))
        assert ops == ["asset-status", "create-work-order", "kb-search"], ops
        return f"tool catalog: {ops}"
    ctx.step("apim: the tool catalog lists the three operations (azure-mgmt-apimanagement)", catalog)

    def read_tool():
        r = requests.post(ctx.apim_url("tools/asset-status"), json={"asset_id": "B-12"}, headers=apim_headers(ctx), timeout=60)
        assert r.status_code == 200 and r.json().get("found"), f"HTTP {r.status_code}: {r.text[:200]}"
        ctx.state["gateway_tools_ok"] = True
        return f"asset-status through APIM -> B-12 {r.json()['asset'].get('status')}"
    ctx.step("apim gateway: read-only tool call (asset-status) reaches the Function App", read_tool, lane=LANE["gateway"])

    def ratelimit():
        apim.api_operation_policy.create_or_update(RG, NAMES["apim"], "tools", "asset-status", "policy", {"value": (
            '<policies><inbound><base/><rate-limit calls="1000" renewal-period="60"/></inbound><backend><base/></backend><outbound><base/></outbound><on-error><base/></on-error></policies>'),
            "format": "xml"})
        return "operation policy with rate-limit accepted"
    ctx.step("apim: operation policy (rate-limit) is accepted", ratelimit)

    def policy_write():
        apim.api_operation_policy.create_or_update(RG, NAMES["apim"], "tools", "create-work-order", "policy", {"value": DENY_WRITE, "format": "xml"})
        h = apim_headers(ctx)
        no = requests.post(ctx.apim_url("tools/create-work-order"), json={"request_id": "x"}, headers=h, timeout=30)
        assert no.status_code == 403 and "approved request" in no.text, f"write tool without approval id: HTTP {no.status_code} {no.text[:120]}"
        yes = requests.post(ctx.apim_url("tools/create-work-order"), json={"request_id": "nonexistent"}, headers=dict(h, **{"x-approval-id": "req-none"}), timeout=60)
        assert yes.status_code == 200 and yes.json().get("ok") is False, f"with an approval id the call must reach the function (which refuses an unknown request): HTTP {yes.status_code} {yes.text[:150]}"
        return "policy expression: write tool 403 without x-approval-id; with it the call reaches the function, which refuses (no approved ledger row)"
    ctx.step("apim policy expression: the write tool is denied without an approval id (the Cedar substitute)", policy_write, lane=LANE["gateway"])

    def mcp():
        apim.api.begin_create_or_update(RG, NAMES["apim"], "tools-mcp", {"display_name": "facilities-tools-mcp", "path": "mcp", "protocols": ["https"], "subscription_required": True,
                                                                         "api_type": "mcp", "service_url": f"{ctx.http}/azure-data/functions/{NAMES['functions']}/api"}).result()
        names = {t["name"] for t in apim_mcp(ctx, "tools/list")["tools"]}
        assert names, "tools/list returned no tools"
        ctx.state["mcp_tools"] = names
        return f"MCP tools/list through APIM: {sorted(names)}"
    ctx.step("apim MCP server API: tools/list as JSON-RPC at the gateway", mcp, lane=LANE["gateway"])

    def mcp_call():
        n = [n for n in ctx.state["mcp_tools"] if n.replace("-", "_").endswith("asset_status")][0]
        res = apim_mcp(ctx, "tools/call", {"name": n, "arguments": {"asset_id": "B-12"}})
        assert not res.get("isError"), res
        ctx.state["apim_mcp_ok"] = True
        return "MCP tools/call asset_status -> ok"
    if ctx.state.get("mcp_tools"):
        ctx.step("apim MCP server API: tools/call asset_status", mcp_call, lane=LANE["gateway"])
    ctx.note("Gateway policy on Azure is APIM policy expressions; Azure has no Cedar-style agent policy engine (AWS AgentCore Gateway and Vertex agentPolicies have one).")
