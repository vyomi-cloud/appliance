import json
from azure.mgmt.apimanagement.models import ApiCreateOrUpdateParameter
from azlab import rid, RG
from gw import apim, SERVICE, mcp

apim().api.begin_create_or_update(RG, SERVICE, "tools-mcp", ApiCreateOrUpdateParameter(
    display_name="facilities-tools-mcp", path="mcp", protocols=["https"], subscription_required=True, api_type="mcp",
    source_api_id=rid("Microsoft.ApiManagement", "service", SERVICE) + "/apis/tools")).result()
names = sorted(t["name"] for t in mcp("tools/list")["tools"])
print("MCP tools/list:", names)
tool = next(n for n in names if n.replace("-", "_").endswith("asset_status"))
res = mcp("tools/call", {"name": tool, "arguments": {"asset_id": "B-12"}})
print("MCP tools/call", tool, "-> isError:", bool(res.get("isError")), "| status:", json.loads(res["content"][0]["text"])["asset"]["status"])
