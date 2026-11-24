import time

import boto3

ac = boto3.client("bedrock-agentcore-control")
ROLE = "arn:aws:iam::123456789012:role/facilities-role"
TOOLS = [("kb_search", "facilities-kb-search", "Search the facilities knowledge base (read-only).", {"query": {"type": "string"}}),
         ("asset_status", "facilities-asset-status", "Look up an asset and its work orders (read-only).", {"asset_id": {"type": "string"}})]

gw = ac.create_gateway(name="facilities-gateway", roleArn=ROLE, protocolType="MCP", authorizerType="AWS_IAM")
gid = gw["gatewayId"]
for _ in range(30):
    if ac.get_gateway(gatewayIdentifier=gid)["status"] == "READY":
        break
    time.sleep(0.5)
print("gateway", gid, ac.get_gateway(gatewayIdentifier=gid)["status"])

for name, fn, desc, props in TOOLS:
    ac.create_gateway_target(
        gatewayIdentifier=gid, name=name.replace("_", "-"),
        targetConfiguration={"mcp": {"lambda": {"lambdaArn": "arn:aws:lambda:us-east-1:123456789012:function:" + fn, "toolSchema": {"inlinePayload": [
            {"name": name, "description": desc, "inputSchema": {"type": "object", "properties": props, "required": list(props)}}]}}}},
        credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}])
for _ in range(30):
    targets = ac.list_gateway_targets(gatewayIdentifier=gid)["items"]
    if targets and all(t["status"] == "READY" for t in targets):
        break
    time.sleep(0.5)
print(len(targets), "targets", sorted(t["status"] for t in targets))
