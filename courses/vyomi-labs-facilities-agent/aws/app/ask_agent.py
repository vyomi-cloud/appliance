import json

import boto3

_ac = boto3.client("bedrock-agentcore-control")
_dp = boto3.client("bedrock-agentcore")
ARN = next(r["agentRuntimeArn"] for r in _ac.list_agent_runtimes()["agentRuntimes"] if r["agentRuntimeName"] == "facilities_supervisor")
QUESTION = "Boiler B-12 is at 34 psi. What does the SOP say, and please raise a work order for it. How many work orders are open?"


def ask(session_id, prompt=QUESTION, user="maria.ops@example.com"):
    """session_id must be at least 33 characters."""
    r = _dp.invoke_agent_runtime(agentRuntimeArn=ARN, runtimeSessionId=session_id, contentType="application/json", accept="application/json",
                                 payload=json.dumps({"prompt": prompt, "user": user}).encode())
    return json.loads(r["response"].read())
