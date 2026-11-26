import json
import time

import boto3

import mcp_client

ac, ddb = boto3.client("bedrock-agentcore-control"), boto3.client("dynamodb")
gw = next(g for g in ac.list_gateways()["items"] if g["name"] == "facilities-gateway")
gid = gw["gatewayId"]
engine = next(e for e in ac.list_policy_engines()["policyEngines"] if e["name"] == "facilities_policies")

ac.create_gateway_target(
    gatewayIdentifier=gid, name="create-work-order",
    targetConfiguration={"mcp": {"lambda": {"lambdaArn": "arn:aws:lambda:us-east-1:123456789012:function:facilities-create-work-order", "toolSchema": {"inlinePayload": [
        {"name": "create_work_order", "description": "Create a work order (WRITE: needs approval).",
         "inputSchema": {"type": "object", "properties": {"request_id": {"type": "string"}, "asset_id": {"type": "string"}, "summary": {"type": "string"}}, "required": ["request_id", "asset_id", "summary"]}}]}}}},
    credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}])
for _ in range(30):
    if all(t["status"] == "READY" for t in ac.list_gateway_targets(gatewayIdentifier=gid)["items"]):
        break
    time.sleep(0.5)
cur = ac.get_gateway(gatewayIdentifier=gid)
ac.update_gateway(gatewayIdentifier=gid, name=cur["name"], roleArn=cur["roleArn"], protocolType="MCP", authorizerType=cur["authorizerType"],
                  policyEngineConfiguration={"arn": engine["policyEngineArn"], "mode": "ENFORCE"})
assert ac.get_gateway(gatewayIdentifier=gid)["policyEngineConfiguration"]["mode"] == "ENFORCE"
names = {t["name"]: t for t in mcp_client.call(gid, "tools/list")["tools"]}
read = next(n for n in names if "asset_status" in n)
assert not any("create_work_order" in n for n in names), "the policy must hide the write tool from discovery, catalog is %s" % sorted(names)
print("catalog the agent can discover:", sorted(names), "(the write tool is registered but invisible)")
write = "create-work-order___create_work_order"          # an attacker does not need the catalog: it guesses the name
before = len(ddb.scan(TableName="facilities-work-orders")["Items"])

ok = mcp_client.call(gid, "tools/call", {"name": read, "arguments": {"asset_id": "B-12"}})
assert not ok.get("isError") and json.loads(ok["content"][0]["text"])["found"] is True, "the permitted read must work"
print("permitted read through the gateway: ok")

try:
    res = mcp_client.call(gid, "tools/call", {"name": write, "arguments": {"request_id": "req-gw-attack1", "asset_id": "B-12", "summary": "give myself a work order"}})
    denied = bool(res.get("isError"))
    detail = json.dumps(res)[:140]
except RuntimeError as e:
    denied, detail = True, str(e)[:140]
assert denied, "the forbidden write must be refused by the gateway policy"
assert len(ddb.scan(TableName="facilities-work-orders")["Items"]) == before, "a refused write must not create a work order"
print("forbidden write refused by policy:", detail)

bad = mcp_client.call(gid, "tools/call", {"name": read, "arguments": {"asset_id": "B-12'; DROP TABLE x;--"}})
payload = json.loads(bad["content"][0]["text"]) if bad.get("content") and not bad.get("isError") else {"error": "invalid_input"}
assert payload.get("error") == "invalid_input", "hostile arguments must be refused by the tool behind the gateway"
print("hostile argument to the permitted tool: refused by the tool")
print("gateway policy enforcement verified")
