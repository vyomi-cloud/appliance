"""Nano WebLLM bridge seam: an ASYNC-only backend answers Bedrock/Vertex/Azure OpenAI through AwsWireRouter.ahandle
(arun replays the request after awaiting the engine); the synchronous path is honestly unavailable.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_llm_async_bridge.py
"""
import asyncio
import json

from core import llm_core as llm
from core.aws_wire_router import AwsWireRouter

BR = "AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/bedrock/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


calls = []


async def fake_webllm(msgs, system, max_tokens, temperature, stop):
    calls.append(msgs[-1]["content"])
    await asyncio.sleep(0)
    return {"text": "WEBLLM: " + msgs[-1]["content"], "input_tokens": 3, "output_tokens": 4}


async def main():
    r = AwsWireRouter()
    body = json.dumps({"messages": [{"role": "user", "content": [{"text": "hi there"}]}], "inferenceConfig": {"maxTokens": 8}}).encode()
    h = {"authorization": BR, "content-type": "application/json"}
    path = "/model/amazon.nova-lite-v1%3A0/converse"
    llm.set_backend()
    import os
    os.environ["VYOMI_LLM_DISABLE"] = "1"
    out = await r.ahandle("POST", path, {}, h, body)
    _check("no backend -> honest ModelNotReady", out["status"] == 429)
    llm.set_async_backend(fake_webllm, model="smollm2-360m-webllm")
    _check("status shows the webllm backend", llm.status()["backend"] == "webllm" and llm.status()["available"])
    out = r.handle("POST", path, {}, h, body)
    _check("sync path with only an async backend is unavailable (never a fake answer)", out["status"] == 429 and b"async" in out["body"])
    out = await r.ahandle("POST", path, {}, h, body)
    doc = json.loads(out["body"])
    _check("ahandle awaits the engine and answers", out["status"] == 200 and doc["output"]["message"]["content"][0]["text"].startswith("WEBLLM: hi there"))
    _check("usage comes from the engine", doc["usage"]["inputTokens"] == 3 and doc["usage"]["outputTokens"] == 4 and len(calls) == 1)
    # agent flow: InvokeAgent through the async front door
    ap = {"agentName": "a1", "foundationModel": "amazon.nova-lite-v1:0", "agentResourceRoleArn": "arn:aws:iam::123456789012:role/r", "instruction": "You are a helpful assistant for the test suite okay."}
    o = await r.ahandle("PUT", "/agents/", {}, h, json.dumps(ap).encode())
    aid = json.loads(o["body"])["agent"]["agentId"]
    await r.ahandle("POST", f"/agents/{aid}/", {}, h, b"")
    out = await r.ahandle("POST", f"/agents/{aid}/agentAliases/TSTALIASID/sessions/s1/text", {}, h, json.dumps({"inputText": "ping"}).encode())
    _check("InvokeAgent works over the async backend", out["status"] == 200 and b"chunk" in out["body"])
    # engine failure -> honest error
    async def boom(*a):
        raise RuntimeError("webgpu lost")
    llm.set_async_backend(boom)
    out = await r.ahandle("POST", path, {}, h, body)
    _check("engine failure -> ModelNotReady, no canned text", out["status"] == 429 and b"webgpu lost" in out["body"])
    # tools over the async (WebLLM) bridge: prompt translation + a corrective retry = two engine calls replayed by arun
    replies = iter(["I would call the tool", '{"tool_calls":[{"name":"get_weather","arguments":{"city":"Paris"}}]}'])
    n = []

    async def scripted(msgs, system, max_tokens, temperature, stop):
        n.append(1)
        return {"text": next(replies)}
    llm.set_async_backend(scripted)
    tb = json.dumps({"messages": [{"role": "user", "content": [{"text": "weather?"}]}], "toolConfig": {"tools": [{"toolSpec": {
        "name": "get_weather", "inputSchema": {"json": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}}]}}).encode()
    out = await r.ahandle("POST", path, {}, h, tb)
    doc = json.loads(out["body"])
    _check("Converse toolUse over the async bridge (retry replayed through arun)", out["status"] == 200 and doc["stopReason"] == "tool_use"
           and doc["output"]["message"]["content"][0]["toolUse"]["input"] == {"city": "Paris"} and len(n) == 2)
    llm.set_async_backend()
    del os.environ["VYOMI_LLM_DISABLE"]
    print("OK")


asyncio.run(main())
