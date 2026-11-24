"""Layer 10 reference solution (peek only after you have tried). Same contract as starter/layers/l10_models.py."""
import json

import boto3

CHAT_MODEL = "anthropic.claude-3-haiku-20240307-v1:0"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
_rt = None


def _client():
    global _rt
    if _rt is None:
        _rt = boto3.client("bedrock-runtime")
    return _rt


def _text(resp) -> str:
    return "".join(b.get("text", "") for b in resp["output"]["message"]["content"])


def chat(prompt: str) -> str:
    r = _client().converse(modelId=CHAT_MODEL, messages=[{"role": "user", "content": [{"text": prompt}]}], inferenceConfig={"maxTokens": 200})
    return _text(r)


def chat_with_tools(prompt: str, tools: list) -> dict:
    r = _client().converse(modelId=CHAT_MODEL, messages=[{"role": "user", "content": [{"text": prompt}]}], toolConfig={"tools": tools})
    tool = next((b["toolUse"] for b in r["output"]["message"]["content"] if "toolUse" in b), None)
    return {"stop_reason": r["stopReason"], "tool_use": tool, "text": _text(r)}


def embed(text: str) -> list:
    r = _client().invoke_model(modelId=EMBED_MODEL, body=json.dumps({"inputText": text}))
    return json.loads(r["body"].read())["embedding"]
