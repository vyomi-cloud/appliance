"""Shared local-LLM seam + Bedrock Runtime / Vertex AI Gemini / Azure OpenAI adapters (hermetic: stub backend, no container).

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_local_llm_seam.py
"""
import base64
import json
import struct
import sys

from core import llm_core as llm
from core.aws_wire_router import AwsWireRouter

BR = "AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/bedrock/aws4_request, SignedHeaders=host, Signature=0"
PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def stub(messages, system, max_tokens, temperature, stop):
    last = [m for m in messages if m["role"] == "user"][-1]["content"]
    system = system or next((m["content"] for m in messages if m["role"] == "system"), "")
    return {"text": f"echo[{system or ''}]:{last}"[:max_tokens * 4], "finish_reason": "stop"}


r = AwsWireRouter()


def js(o):
    return (json.loads(o["body"]) if o["body"] else {})


def bedrock(path, payload=None, method="POST", query=None):
    return r.handle(method, path, query or {}, {"authorization": BR, "content-type": "application/json"},
                    json.dumps(payload).encode() if payload is not None else b"")


def frames(buf):
    out, i = [], 0
    while i < len(buf):
        total, hl = struct.unpack(">II", buf[i:i + 8])
        h, j = {}, i + 12
        while j < i + 12 + hl:
            n = buf[j]; name = buf[j + 1:j + 1 + n].decode(); j += 1 + n + 1
            vl = struct.unpack(">H", buf[j:j + 2])[0]; h[name] = buf[j + 2:j + 2 + vl].decode(); j += 2 + vl
        out.append((h, json.loads(buf[i + 12 + hl:i + total - 4])))
        i += total
    return out


# ── no backend: honest unavailability, never a canned answer
llm.set_backend(None)
import os
os.environ["VYOMI_LLM_DISABLE"] = "1"
os.environ.pop("VYOMI_LLM_ENDPOINT", None)
o = bedrock("/model/amazon.nova-micro-v1:0/converse", {"messages": [{"role": "user", "content": [{"text": "hi"}]}]})
check("no model running -> ModelNotReadyException (429), not a fake answer", o["status"] == 429 and o["headers"]["x-amzn-errortype"] == "ModelNotReadyException", o)
check("status() reports unavailable", llm.status(probe=False)["available"] is False)

llm.set_backend(stub)
check("status() reports registered backend", llm.status()["available"] is True)

# ── Bedrock
o = bedrock("/foundation-models", method="GET")
ids = [m["modelId"] for m in js(o)["modelSummaries"]]
check("ListFoundationModels", o["status"] == 200 and "anthropic.claude-3-haiku-20240307-v1:0" in ids)
o = bedrock("/foundation-models", method="GET", query={"byProvider": "amazon"})
check("ListFoundationModels byProvider", all(m["providerName"] == "Amazon" for m in js(o)["modelSummaries"]))
check("GetFoundationModel 404", bedrock("/foundation-models/nope.x", method="GET")["status"] == 404)

o = bedrock("/model/anthropic.claude-3-haiku-20240307-v1:0/invoke", {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 50,
            "system": "S", "messages": [{"role": "user", "content": "hello"}]})
b = js(o)
check("InvokeModel Claude messages shape", o["status"] == 200 and b["content"][0]["text"] == "echo[S]:hello" and b["stop_reason"] == "end_turn"
      and b["usage"]["output_tokens"] > 0 and o["headers"]["x-amzn-bedrock-input-token-count"], o)
o = bedrock("/model/us.anthropic.claude-3-haiku-20240307-v1:0/invoke", {"max_tokens": 5, "messages": [{"role": "user", "content": "x"}]})
check("cross-Region inference profile id accepted", o["status"] == 200)
o = bedrock("/model/anthropic.claude-3-haiku-20240307-v1:0/invoke", {"messages": [{"role": "user", "content": "x"}]})
check("missing max_tokens -> ValidationException", o["status"] == 400 and o["headers"]["x-amzn-errortype"] == "ValidationException")
o = bedrock("/model/amazon.titan-text-express-v1/invoke", {"inputText": "ping", "textGenerationConfig": {"maxTokenCount": 20}})
check("InvokeModel Titan Text", js(o)["results"][0]["outputText"] == "echo[]:ping" and js(o)["inputTextTokenCount"] > 0)
o = bedrock("/model/meta.llama3-8b-instruct-v1:0/invoke", {"prompt": "yo", "max_gen_len": 20})
check("InvokeModel Llama", js(o)["generation"] == "echo[]:yo")
o = bedrock("/model/amazon.nova-lite-v1:0/invoke", {"messages": [{"role": "user", "content": [{"text": "n"}]}], "inferenceConfig": {"max_new_tokens": 9}})
check("InvokeModel Nova", js(o)["output"]["message"]["content"][0]["text"] == "echo[]:n")
o = bedrock("/model/amazon.titan-embed-text-v2:0/invoke", {"inputText": "the cat sat", "dimensions": 256})
e1 = js(o)["embedding"]
e2 = js(bedrock("/model/amazon.titan-embed-text-v2:0/invoke", {"inputText": "the cat sat down", "dimensions": 256}))["embedding"]
e3 = js(bedrock("/model/amazon.titan-embed-text-v2:0/invoke", {"inputText": "quarterly revenue forecast", "dimensions": 256}))["embedding"]
check("Titan embeddings dims + similarity ordering", len(e1) == 256 and llm.cosine(e1, e2) > llm.cosine(e1, e3))
check("bad dimensions -> 400", bedrock("/model/amazon.titan-embed-text-v2:0/invoke", {"inputText": "x", "dimensions": 7})["status"] == 400)
check("unknown model -> ValidationException", bedrock("/model/foo.bar/invoke", {"x": 1})["status"] == 400)

o = bedrock("/model/amazon.nova-micro-v1:0/converse", {"system": [{"text": "SYS"}], "messages": [{"role": "user", "content": [{"text": "hi"}]}],
            "inferenceConfig": {"maxTokens": 100, "temperature": 0.2}})
b = js(o)
check("Converse", b["output"]["message"]["content"][0]["text"] == "echo[SYS]:hi" and b["stopReason"] == "end_turn"
      and b["usage"]["totalTokens"] == b["usage"]["inputTokens"] + b["usage"]["outputTokens"] and "latencyMs" in b["metrics"])
check("Converse toolConfig rejected honestly", bedrock("/model/amazon.nova-micro-v1:0/converse", {"toolConfig": {}, "messages": [{"role": "user", "content": [{"text": "x"}]}]})["status"] == 400)
check("Converse empty messages", bedrock("/model/amazon.nova-micro-v1:0/converse", {"messages": []})["status"] == 400)
o = bedrock("/model/amazon.nova-micro-v1:0/converse-stream", {"messages": [{"role": "user", "content": [{"text": "stream this please"}]}]})
fr = frames(o["body"])
types = [h[":event-type"] for h, _ in fr]
text = "".join(p["delta"]["text"] for h, p in fr if h[":event-type"] == "contentBlockDelta")
check("ConverseStream eventstream framing", o["headers"]["content-type"] == "application/vnd.amazon.eventstream" and types[0] == "messageStart"
      and types[-2:] == ["messageStop", "metadata"] and text == "echo[]:stream this please", types)
o = bedrock("/model/anthropic.claude-3-haiku-20240307-v1:0/invoke-with-response-stream", {"max_tokens": 9, "messages": [{"role": "user", "content": "s"}]})
fr = frames(o["body"])
_ev = [json.loads(base64.b64decode(p["bytes"])) for h, p in fr]
check("InvokeModelWithResponseStream chunks (Claude Messages events)", _ev[0]["type"] == "message_start" and _ev[-1]["type"] == "message_stop"
      and "".join(e["delta"]["text"] for e in _ev if e["type"] == "content_block_delta") == "echo[]:s")

# ── Vertex AI
G = "/v1/projects/p1/locations/us-central1/publishers/google/models/gemini-2.0-flash"


def gcp(op, payload, model=G, query=None):
    return r.handle("POST", f"{model}:{op}", query or {}, {"content-type": "application/json"}, json.dumps(payload).encode())


o = gcp("generateContent", {"contents": [{"role": "user", "parts": [{"text": "hi gemini"}]}], "systemInstruction": {"parts": [{"text": "SI"}]},
                            "generationConfig": {"maxOutputTokens": 100}})
b = js(o)
check("Vertex generateContent", o["status"] == 200 and b["candidates"][0]["content"]["parts"][0]["text"] == "echo[SI]:hi gemini"
      and b["candidates"][0]["finishReason"] == "STOP" and b["usageMetadata"]["totalTokenCount"] > 0, o)
check("Vertex countTokens", js(gcp("countTokens", {"contents": [{"role": "user", "parts": [{"text": "12345678"}]}]}))["totalTokens"] == 2)
o = gcp("streamGenerateContent", {"contents": [{"role": "user", "parts": [{"text": "a long enough prompt for chunks to split"}]}]})
arr = js(o)
check("Vertex streamGenerateContent array", isinstance(arr, list) and len(arr) > 1 and arr[-1]["candidates"][0]["finishReason"] == "STOP")
o = gcp("streamGenerateContent", {"contents": [{"role": "user", "parts": [{"text": "sse"}]}]}, query={"alt": "sse"})
check("Vertex SSE", o["body"].startswith(b"data: "))
check("Vertex missing contents -> INVALID_ARGUMENT", js(gcp("generateContent", {}))["error"]["status"] == "INVALID_ARGUMENT")
check("Vertex unknown model -> NOT_FOUND", js(gcp("generateContent", {"contents": []}, model="/v1/projects/p/locations/l/publishers/google/models/gemini-9"))["error"]["status"] == "NOT_FOUND")
check("Vertex inlineData rejected honestly", gcp("generateContent", {"contents": [{"role": "user", "parts": [{"inlineData": {}}]}]})["status"] == 400)
o = gcp("embedContent", {"content": {"parts": [{"text": "vec me"}]}}, model="/v1/projects/p/locations/l/publishers/google/models/text-embedding-005")
check("Vertex embedContent", len(js(o)["embedding"]["values"]) == llm.HASH_DIM)
o = gcp("predict", {"instances": [{"content": "a"}, {"content": "b"}]}, model="/v1/projects/p/locations/l/publishers/google/models/text-embedding-005")
check("Vertex embeddings predict", len(js(o)["predictions"]) == 2)

# ── Azure OpenAI (deployment must exist in ARM state)
from core.azure_arm_core import AzureArm
r.az_arm = AzureArm()
base = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/oai1"
r.az_arm.handle("PUT", base, {"api-version": "2024-10-01"}, {"kind": "OpenAI", "location": "eastus", "sku": {"name": "S0"}})
dr = r.az_arm.handle("PUT", base + "/deployments/chat", {"api-version": "2024-10-01"},
                     {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": "gpt-4o-mini", "version": "2024-07-18"}}})
check("ARM deployment created", dr["status"] in (200, 201), dr)


def az(path, payload, hdr=None):
    return r.handle("POST", path, {"api-version": "2024-10-21"}, {"content-type": "application/json", **({"api-key": "k"} if hdr is None else hdr)},
                    json.dumps(payload).encode())


o = az("/openai/deployments/chat/chat/completions", {"messages": [{"role": "system", "content": "SY"}, {"role": "user", "content": "hello az"}]})
b = js(o)
check("Azure OpenAI chat.completions", o["status"] == 200 and b["object"] == "chat.completion" and b["model"] == "gpt-4o-mini"
      and b["choices"][0]["message"]["content"] == "echo[SY]:hello az" and b["usage"]["total_tokens"] > 0, o)
check("missing api-key -> 401", az("/openai/deployments/chat/chat/completions", {"messages": []}, hdr={})["status"] == 401)
o = az("/openai/deployments/ghost/chat/completions", {"messages": [{"role": "user", "content": "x"}]})
check("unknown deployment -> DeploymentNotFound", o["status"] == 404 and js(o)["error"]["code"] == "DeploymentNotFound")
check("missing messages -> 400", az("/openai/deployments/chat/chat/completions", {})["status"] == 400)
o = az("/openai/deployments/chat/chat/completions", {"messages": [{"role": "user", "content": "s"}], "stream": True})
check("Azure OpenAI SSE stream", o["body"].endswith(b"data: [DONE]\n\n") and b"chat.completion.chunk" in o["body"])
check("embeddings on a chat model -> OperationNotSupported", js(az("/openai/deployments/chat/embeddings", {"input": "x"}))["error"]["code"] == "OperationNotSupported")
o = az("/openai/v1/chat/completions", {"model": "chat", "messages": [{"role": "user", "content": "v1"}]})
check("/openai/v1 with model=deployment", o["status"] == 200 and js(o)["choices"][0]["message"]["content"] == "echo[]:v1")
check("tools rejected honestly", az("/openai/deployments/chat/chat/completions", {"messages": [{"role": "user", "content": "x"}], "tools": [{}]})["status"] == 400)

# ── offline container lifecycle (docker stubbed)
from core import llm_runtime as rt
calls = []
state = {"ps": ""}


def fake(args):
    calls.append(args)
    if args[0] == "ps":
        return 0, state["ps"], ""
    if args[0] == "run":
        state["ps"] = "running"
    return 0, "", ""


try:
    rt.start(run=fake, disk=lambda: 5.0)
    check("start refused below the disk guard", False)
except rt.RuntimeError_:
    check("start refused below the disk guard", not any(c[0] == "run" for c in calls))
st = rt.start(run=fake, disk=lambda: 50.0)
run_args = next(c for c in calls if c[0] == "run")
check("start runs a named llama.cpp container with a model volume + small HF model", run_args[3] == rt.NAME and "-hf" in run_args and "--embeddings" in run_args and st["running"])
check("start is idempotent when running", rt.start(run=fake, disk=lambda: 50.0)["running"] and sum(1 for c in calls if c[0] == "run") == 1)

print(f"{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
