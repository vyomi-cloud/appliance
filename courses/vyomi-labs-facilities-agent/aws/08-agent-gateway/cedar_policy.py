import boto3

ac = boto3.client("bedrock-agentcore-control")
engine = ac.create_policy_engine(name="facilities_policies")["policyEngineId"]
statement = 'permit(principal, action == AgentCore::Action::"asset-status___asset_status", resource);'
ac.create_policy(policyEngineId=engine, name="read_only_tools", definition={"cedar": {"statement": statement}})
print("policy engine", engine, "with a Cedar permit policy")
