"""AWS driver: boto3 bedrock-runtime Converse tool loop (+ Titan embeddings). Native SDK, only the endpoint differs from production.
    VYOMI_ENDPOINT=http://127.0.0.1:8099 python agent_aws.py ["Where is my order A1001?"]
"""
import json
import os
import time

import boto3
from botocore.config import Config

import triage_tools as tools

MODEL = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")   # any id: Vyomi maps it to the local model


def client():
    return boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"), endpoint_url=tools.endpoint(),
                        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"), aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
                        config=Config(read_timeout=600, retries={"max_attempts": 1}))


def titan_embed(br):
    def embed(texts):
        out = []
        for t in texts:
            r = br.invoke_model(modelId="amazon.titan-embed-text-v2:0", body=json.dumps({"inputText": t, "dimensions": 512}))
            out.append(json.loads(r["body"].read())["embedding"])
        return out
    return embed


def run_agent(question, trace):
    br = client()
    tools.set_embedder(titan_embed(br))
    tool_config = {"tools": [{"toolSpec": {"name": t["name"], "description": t["description"], "inputSchema": {"json": t["parameters"]}}} for t in tools.TOOLS]}
    messages = [{"role": "user", "content": [{"text": question}]}]
    for step in range(1, tools.MAX_STEPS + 1):
        t0 = time.time()
        r = br.converse(modelId=MODEL, system=[{"text": tools.SYSTEM}], messages=messages, toolConfig=tool_config,
                        inferenceConfig={"maxTokens": 300, "temperature": 0})
        msg = r["output"]["message"]
        messages.append(msg)
        uses = [b["toolUse"] for b in msg["content"] if "toolUse" in b]
        text = "".join(b.get("text", "") for b in msg["content"])
        trace.append({"step": step, "seconds": time.time() - t0, "text": text, "tool_calls": [{"name": u["name"], "args": u["input"]} for u in uses]})
        if r["stopReason"] != "tool_use" or not uses:
            return text
        results = []
        for u in uses:
            res = tools.execute(u["name"], u["input"])
            results.append({"toolResult": {"toolUseId": u["toolUseId"], "content": [{"json": res}], **({"status": "error"} if "error" in res else {})}})
        messages.append({"role": "user", "content": results})
    return "(gave up: no final answer within MAX_STEPS)"


if __name__ == "__main__":
    raise SystemExit(tools.cli(run_agent, "aws/bedrock"))
