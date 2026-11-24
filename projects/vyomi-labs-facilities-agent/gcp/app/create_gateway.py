import time

import gateway

gateway.api("POST", gateway.BASE + f"/agentGateways?agentGatewayId={gateway.GATEWAY}", {"displayName": "Facilities gateway", "authorization": {"type": "NONE"}})
for _ in range(40):
    gw = gateway.api("GET", gateway.BASE + f"/agentGateways/{gateway.GATEWAY}")
    if gw.get("state") == "ACTIVE":
        break
    time.sleep(0.5)
assert gw["state"] == "ACTIVE", gw
print("gateway ACTIVE, mcp endpoint:", gw["mcpEndpoint"])

import gcp
gateway.api("POST", gateway.BASE + f"/agentGateways/{gateway.GATEWAY}:attachMcpServer", {"mcpServer": f"{gcp.PARENT}/mcpServers/{gateway.MCP_SERVER}"})
gw = gateway.api("GET", gateway.BASE + f"/agentGateways/{gateway.GATEWAY}")
print("attached:", [m.rsplit("/", 1)[-1] for m in gw["attachedMcpServers"]])
