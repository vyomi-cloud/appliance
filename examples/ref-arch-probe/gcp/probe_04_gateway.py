"""C4 Gateway: Agent Platform agentGateways, mcpServers registry, agentPolicies (Cedar). No public Google SDK exists for these: plain REST in the shapes the simulator documents."""
from _common import *

s = Step()
P = f"/v1/projects/{PROJECT}/locations/{LOC}"
PN = f"projects/{PROJECT}/locations/{LOC}"
CEDAR = 'permit(principal, action == AgentCore::Action::"facility___asset_status", resource);'


def mcp():
    r = call("POST", P + f"/mcpServers?mcpServerId=fac-{TAG}", {"endpoint": "https://tools.example.com/mcp", "displayName": "Facilities tools"})
    assert r.get("name") or r.get("response"), r
    return str(r)[:120]


def gw():
    call("POST", P + f"/agentGateways?agentGatewayId=gw-{TAG}", {"displayName": "Facilities gateway", "authorization": {"type": "NONE"}})
    return str(call("GET", P + f"/agentGateways/gw-{TAG}"))[:140]


def pol():
    call("POST", P + f"/agentPolicies?agentPolicyId=pol-{TAG}", {"cedarPolicy": CEDAR, "enforcementMode": "ENFORCE", "displayName": "facility tools only"})
    t1 = call("POST", P + f"/agentPolicies/pol-{TAG}:test", {"principal": "u1", "tool": "facility___asset_status", "arguments": {}})
    t2 = call("POST", P + f"/agentPolicies/pol-{TAG}:test", {"principal": "u1", "tool": "other___delete_all", "arguments": {}})
    assert t1["decision"] == "ALLOW" and t2["decision"] == "DENY", (t1, t2)
    return "permitted tool ALLOW, other tool DENY"


def attach():
    call("POST", P + f"/agentGateways/gw-{TAG}:attachPolicy", {"policy": PN + f"/agentPolicies/pol-{TAG}"})
    g = call("GET", P + f"/agentGateways/gw-{TAG}")
    return str(g)[:160]


s("mcpServers registry: create", mcp)
s("agentGateways: create + get", gw)
s("agentPolicies (Cedar): create + :test allow/deny", pol)
s("agentGateways:attachPolicy", attach)
s.finish()
