import json
import boto3

def _pick():
    """The models are the ones this simulator hosts: in-browser models on Nano, the Mesh model pool on a Mesh. Ask it, never hard-code a vendor id."""
    ms = [m for m in boto3.client("bedrock").list_foundation_models()["modelSummaries"] if m["modelId"].startswith("vyomi.")]
    chat = [m["modelId"] for m in ms if "EMBEDDING" not in m["outputModalities"]]
    emb = [m["modelId"] for m in ms if "EMBEDDING" in m["outputModalities"]]
    return chat[0], emb[0]


CHAT_MODEL, EMBED_MODEL = _pick()
_rt = boto3.client("bedrock-runtime")


def _text(resp):
    return "".join(b.get("text", "") for b in resp["output"]["message"]["content"])


def chat(prompt):
    r = _rt.converse(modelId=CHAT_MODEL, messages=[{"role": "user", "content": [{"text": prompt}]}], inferenceConfig={"maxTokens": 200})
    return _text(r)


def chat_with_tools(prompt, tools):
    r = _rt.converse(modelId=CHAT_MODEL, messages=[{"role": "user", "content": [{"text": prompt}]}], toolConfig={"tools": tools})
    tool = next((b["toolUse"] for b in r["output"]["message"]["content"] if "toolUse" in b), None)
    return {"stop_reason": r["stopReason"], "tool_use": tool, "text": _text(r)}


def embed(text, dimensions=None):
    """dimensions: ask for a shorter vector when the model supports it (your RAG design sets this); None keeps the model's own size."""
    body = {"inputText": text}
    if dimensions:
        body["dimensions"] = dimensions
    r = _rt.invoke_model(modelId=EMBED_MODEL, body=json.dumps(body))
    return json.loads(r["body"].read())["embedding"]
