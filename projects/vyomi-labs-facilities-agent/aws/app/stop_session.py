import boto3

ac = boto3.client("bedrock-agentcore-control")
dp = boto3.client("bedrock-agentcore")
arn = next(r["agentRuntimeArn"] for r in ac.list_agent_runtimes()["agentRuntimes"] if r["agentRuntimeName"] == "facilities_supervisor")
dp.stop_runtime_session(agentRuntimeArn=arn, runtimeSessionId="facilities-session-" + "b" * 20)
print("stopped session b; runtime still", ac.get_agent_runtime(agentRuntimeId=arn.split("/")[-1])["status"])
