import boto3

import mcp_client

ac = boto3.client("bedrock-agentcore-control")
gid = next(g["gatewayId"] for g in ac.list_gateways()["items"] if g["name"] == "facilities-gateway")
tools = mcp_client.call(gid, "tools/list")["tools"]
print("MCP tools/list:", sorted(t["name"] for t in tools))
