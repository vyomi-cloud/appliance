"""Hosted-agent demo (Dev Simplified): one Vyomi agent spec on Bedrock AgentCore Runtime (boto3) and Vertex AI Agent Engine (REST).
    VYOMI_ENDPOINT=http://127.0.0.1:8099 python agent_hosted_spec.py
The simulator does not run your container / pickled class. The "agent" is a JSON spec (instructions + declarative tools) executed
in-process as a tool-calling loop over the local model (core/agent_spec_core.py). Quality is the small model's; the wire is real.
"""
import json
import os
import time

import boto3
import httpx
from botocore.config import Config

ENDPOINT = os.environ.get("VYOMI_ENDPOINT", "http://127.0.0.1:8099")
SPEC = {"instructions": "You are a support bot. Use lookup_order for any order question.", "max_steps": 4,
        "tools": [{"name": "lookup_order", "description": "Look up an order by id", "type": "static",
                   "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
                   "cases": [{"match": {"order_id": "A100"}, "result": {"status": "shipped", "eta": "2 days"}}], "result": {"status": "unknown"}}]}

# ── Bedrock AgentCore: the runtime carries the spec in its environment variables
kw = dict(region_name="us-east-1", endpoint_url=ENDPOINT, aws_access_key_id="test", aws_secret_access_key="test", config=Config(read_timeout=600, retries={"max_attempts": 1}))
ctl, data = boto3.client("bedrock-agentcore-control", **kw), boto3.client("bedrock-agentcore", **kw)
rt = ctl.create_agent_runtime(agentRuntimeName="support_bot", roleArn="arn:aws:iam::123456789012:role/r", networkConfiguration={"networkMode": "PUBLIC"},
                              agentRuntimeArtifact={"containerConfiguration": {"containerUri": "vyomi/agent-spec:latest"}},
                              environmentVariables={"VYOMI_AGENT_SPEC": json.dumps(SPEC)})
while ctl.get_agent_runtime(agentRuntimeId=rt["agentRuntimeId"])["status"] != "READY":
    time.sleep(0.5)
out = data.invoke_agent_runtime(agentRuntimeArn=rt["agentRuntimeArn"], runtimeSessionId="demo-session-" + "x" * 24,
                                payload=json.dumps({"prompt": "Where is order A100?"}).encode())
print("AgentCore:", json.loads(out["response"].read())["response"])

# ── Vertex AI Agent Engine: same spec, REST (or the google-cloud-aiplatform gapic client with transport="rest")
parent = "/v1/projects/demo/locations/us-central1/reasoningEngines"
with httpx.Client(base_url=ENDPOINT, timeout=600) as h:
    eng = h.post(parent, json={"displayName": "support-bot", "spec": {"vyomiAgentSpec": SPEC}}).json()["response"]["name"]
    r = h.post(f"/v1/{eng}:query", json={"classMethod": "query", "input": {"message": "Where is order A100?"}}).json()
    print("Agent Engine:", r["output"]["output"])
