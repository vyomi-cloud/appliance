import gateway
import gcp

CEDAR = ('permit(principal, action == AgentCore::Action::"{t}___kb_search", resource);\n'
         'permit(principal, action == AgentCore::Action::"{t}___asset_status", resource);')
server = gateway.MCP_SERVER
gateway.api("POST", gateway.BASE + "/agentPolicies?agentPolicyId=facilities-read-only-tools",
            {"cedarPolicy": CEDAR.format(t=server), "enforcementMode": "ENFORCE", "displayName": "read-only facilities tools"})
allow = gateway.api("POST", gateway.BASE + "/agentPolicies/facilities-read-only-tools:test", {"principal": "maria", "tool": f"{server}___asset_status", "arguments": {}})
deny = gateway.api("POST", gateway.BASE + "/agentPolicies/facilities-read-only-tools:test", {"principal": "maria", "tool": f"{server}___create_work_order", "arguments": {}})
print("read tool:", allow["decision"], "| write tool:", deny["decision"])
assert allow["decision"] == "ALLOW" and deny["decision"] == "DENY"
gateway.api("POST", gateway.BASE + f"/agentGateways/{gateway.GATEWAY}:attachPolicy", {"policy": f"{gcp.PARENT}/agentPolicies/facilities-read-only-tools"})
print("policy attached to", gateway.GATEWAY)
