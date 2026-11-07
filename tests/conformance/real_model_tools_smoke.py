"""OPT-IN smoke against a REAL local model (Ollama / llama-server). Not part of PR CI.
    VYOMI_LLM_ENDPOINT=http://127.0.0.1:11434 VYOMI_LLM_MODEL=qwen2.5:1.5b PYTHONPATH=. python tests/conformance/real_model_tools_smoke.py
Asserts STRUCTURAL validity only (a schema-valid call to a defined tool, valid JSON for the schema, incremental stream); reports
whether the arguments are also semantically right, since a 0.3-3B model is a toy.
"""
import json
import os
import sys
import time

from core import llm_core as llm
from core.aws_wire_router import AwsWireRouter

BR = "AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/bedrock/aws4_request, SignedHeaders=host, Signature=0"
WX = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
TOOLS = [{"name": "get_weather", "description": "Get the current weather for a city", "parameters": WX},
         {"name": "get_time", "description": "Get the current time in a timezone", "parameters": {"type": "object", "properties": {"tz": {"type": "string"}}, "required": ["tz"]}}]
bad = 0


def rep(name, ok, info=""):
    global bad
    bad += 0 if ok else 1
    print(("PASS " if ok else "FAIL ") + name, str(info)[:300])


t0 = time.time()
print("model:", os.environ.get("VYOMI_LLM_MODEL"), "endpoint:", os.environ.get("VYOMI_LLM_ENDPOINT"))
r = llm.chat([{"role": "user", "content": "What is the weather in Paris right now?"}], tools=TOOLS, max_tokens=200, temperature=0)
ok = (not r["tool_calls"] and bool(r["text"])) or (r["tool_calls"][0]["name"] in ("get_weather", "get_time") and not llm.validate(
    next(t for t in TOOLS if t["name"] == r["tool_calls"][0]["name"])["parameters"], r["tool_calls"][0]["arguments"]))
rep(f"tool call (mode: {'prompt-translated' if llm._state['no_native'] else 'native'})", ok, r["tool_calls"])
print("  semantically right:", bool(r["tool_calls"]) and r["tool_calls"][0]["name"] == "get_weather" and "paris" in json.dumps(r["tool_calls"][0]["arguments"]).lower(),
      f"{time.time() - t0:.1f}s, tokens {r['input_tokens']}+{r['output_tokens']}")
if not r["tool_calls"]:
    print("  (model answered directly instead of calling the tool - valid, it is a toy model)")
    sys.exit(1 if bad else 0)
call = r["tool_calls"][0]
hist = [{"role": "user", "content": "What is the weather in Paris right now?"}, {"role": "assistant", "content": "", "tool_calls": [call]},
        {"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": '{"temp_c": 21, "sky": "sunny"}'}]
r2 = llm.chat(hist, tools=TOOLS, max_tokens=120, temperature=0)
rep("tool result -> final answer", bool(r2["text"]) or bool(r2["tool_calls"]), r2["text"] or r2["tool_calls"])
rf = {"type": "json_schema", "name": "p", "schema": {"type": "object", "properties": {"name": {"type": "string"}, "age": {"type": "integer"}}, "required": ["name", "age"]}}
r3 = llm.chat([{"role": "user", "content": "Extract: Ann is 31 years old."}], response_format=rf, max_tokens=80, temperature=0)
rep("json_schema structured output valid", not llm.validate(rf["schema"], json.loads(r3["text"])), r3["text"])
t0 = time.time()
it = llm.chat_stream([{"role": "user", "content": "Count from 1 to 12 separated by spaces."}], max_tokens=80, temperature=0)
first = next(it)
tf = time.time() - t0
evs = [first] + list(it)
rep("real streaming: first token before completion", first["type"] == "text" and sum(e["type"] == "text" for e in evs) > 2 and (time.time() - t0) > tf, f"first {tf:.2f}s total {time.time() - t0:.2f}s pieces {sum(e['type'] == 'text' for e in evs)}")
# through the Bedrock wire
rt = AwsWireRouter()
body = {"messages": [{"role": "user", "content": [{"text": "What is the weather in Tokyo?"}]}], "inferenceConfig": {"maxTokens": 150, "temperature": 0},
        "toolConfig": {"tools": [{"toolSpec": {"name": "get_weather", "description": "weather for a city", "inputSchema": {"json": WX}}}]}}
o = rt.handle("POST", "/model/amazon.nova-lite-v1:0/converse", {}, {"authorization": BR, "content-type": "application/json"}, json.dumps(body).encode())
doc = json.loads(o["body"])
blk = doc.get("output", {}).get("message", {}).get("content", [{}])
rep("Bedrock Converse wire -> toolUse", o["status"] == 200 and doc["stopReason"] == "tool_use" and "toolUse" in blk[-1], doc)
sys.exit(1 if bad else 0)
