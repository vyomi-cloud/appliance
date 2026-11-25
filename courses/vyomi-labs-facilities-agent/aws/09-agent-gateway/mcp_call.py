import json

import boto3

import mcp_client

ac = boto3.client("bedrock-agentcore-control")
gid = next(g["gatewayId"] for g in ac.list_gateways()["items"] if g["name"] == "facilities-gateway")
name = next(t["name"] for t in mcp_client.call(gid, "tools/list")["tools"] if "asset_status" in t["name"])
res = mcp_client.call(gid, "tools/call", {"name": name, "arguments": {"asset_id": "B-12"}})
out = json.loads(res["content"][0]["text"])
print("tools/call", name, "-> found:", out["found"], "| status:", out["asset"]["status"], "| isError:", bool(res.get("isError")))
