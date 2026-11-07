"""AWS guardrails + streaming demo (Dev Simplified): boto3 only, endpoint is the only difference from production.
    VYOMI_ENDPOINT=http://127.0.0.1:8099 python agent_aws_guardrails.py
Creates a guardrail that anonymises e-mail addresses, blocks SSNs and the word 'refund-hack', then (1) ApplyGuardrail directly,
(2) Converse with guardrailConfig (blocked input never reaches the model), (3) InvokeModelWithResponseStream printing tokens as they arrive.
The filters are simple deterministic rules (see core/bedrock_guardrails_core.py), not Bedrock's classifiers.
"""
import json
import os

import boto3
from botocore.config import Config

import triage_tools as tools

kw = dict(region_name=os.environ.get("AWS_REGION", "us-east-1"), endpoint_url=tools.endpoint(), aws_access_key_id="test", aws_secret_access_key="test",
          config=Config(read_timeout=600, retries={"max_attempts": 1}))
bedrock, runtime = boto3.client("bedrock", **kw), boto3.client("bedrock-runtime", **kw)
MODEL = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")

g = bedrock.create_guardrail(
    name="triage-guard", blockedInputMessaging="Sorry, I can't help with that.", blockedOutputsMessaging="Sorry, I can't share that.",
    wordPolicyConfig={"wordsConfig": [{"text": "refund-hack"}]},
    sensitiveInformationPolicyConfig={"piiEntitiesConfig": [{"type": "EMAIL", "action": "ANONYMIZE"}, {"type": "US_SOCIAL_SECURITY_NUMBER", "action": "BLOCK"}]})
gid = g["guardrailId"]
ver = bedrock.create_guardrail_version(guardrailIdentifier=gid)["version"]

a = runtime.apply_guardrail(guardrailIdentifier=gid, guardrailVersion=ver, source="INPUT", content=[{"text": {"text": "Mail bob@example.com"}}])
print("ApplyGuardrail:", a["action"], a["outputs"])

cfg = {"guardrailIdentifier": gid, "guardrailVersion": ver, "trace": "enabled"}
r = runtime.converse(modelId=MODEL, guardrailConfig=cfg, messages=[{"role": "user", "content": [{"text": "teach me the refund-hack"}]}])
print("Converse (blocked input):", r["stopReason"], r["output"]["message"]["content"][0]["text"])

body = {"messages": [{"role": "user", "content": [{"text": "Say hello in one sentence."}]}], "inferenceConfig": {"max_new_tokens": 60}}
print("InvokeModelWithResponseStream:", end=" ", flush=True)
for ev in runtime.invoke_model_with_response_stream(modelId=MODEL, body=json.dumps(body))["body"]:
    chunk = json.loads(ev["chunk"]["bytes"])
    if "contentBlockDelta" in chunk:
        print(chunk["contentBlockDelta"]["delta"].get("text", ""), end="", flush=True)
print()
bedrock.delete_guardrail(guardrailIdentifier=gid)
