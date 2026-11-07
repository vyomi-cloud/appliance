"""Seam v2 (core/llm_core): tools / tool-call translation, structured output, real streaming, per-request model.
Hermetic: a deterministic OpenAI-compatible fake server (llm_fakes.FakeLLM) and registered backends.

Run: PYTHONPATH=. python tests/conformance/test_llm_seam_v2.py     (or pytest)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import llm_core as llm  # noqa: E402
from llm_fakes import FakeLLM  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {str(extra)[:400]}")


WEATHER = {"name": "get_weather", "description": "Current weather for a city", "parameters": {
    "type": "object", "properties": {"city": {"type": "string"}, "unit": {"type": "string", "enum": ["c", "f"]}}, "required": ["city"]}}
TIME = {"name": "get_time", "description": "Local time", "parameters": {"type": "object", "properties": {"tz": {"type": "string"}}, "required": ["tz"]}}
U = [{"role": "user", "content": "weather in Paris?"}]


def reset(**kw):
    llm.set_backend(None)
    os.environ.pop("VYOMI_LLM_TOOL_MODE", None)
    os.environ.pop("VYOMI_LLM_MODEL_MAP", None)
    os.environ.pop("VYOMI_LLM_DISABLE", None)
    llm._state.update(no_rf=False, no_native=False, endpoint=kw.get("endpoint"))


# ── validator / extractor
check("extract_json: fenced + prose + trailing comma + truncated",
      llm.extract_json('Sure!\n```json\n{"a": 1,}\n```')[0] == {"a": 1} and llm.extract_json('x {"a":[1,2]} y')[0] == {"a": [1, 2]}
      and llm.extract_json('{"name":"x","arguments":{"k":"v')[0] == {"name": "x", "arguments": {"k": "v"}} and llm.extract_json("no json")[1] is False)
check("validate: required/type/enum/anyOf", llm.validate(WEATHER["parameters"], {"city": "P", "unit": "c"}) == []
      and llm.validate(WEATHER["parameters"], {"unit": "k"}) != [] and llm.validate({"anyOf": [{"type": "string"}, {"type": "integer"}]}, True) != [])

# ── native tools over HTTP (server supports tools): tools in, tool_calls out, then a multi-turn result
fake = FakeLLM()
reset(endpoint=fake.url)


def h_native(body):
    if any(m["role"] == "tool" for m in body["messages"]):
        tool = [m for m in body["messages"] if m["role"] == "tool"][-1]
        return {"content": "Result: " + tool["content"]}
    return {"tool_calls": [{"name": "get_weather", "arguments": {"city": "Paris"}}]}


fake.handler = h_native
r = llm.chat(U, tools=[WEATHER, TIME])
check("native tool call: tool_calls out, finish_reason tool_calls", r["finish_reason"] == "tool_calls" and r["tool_calls"][0]["name"] == "get_weather"
      and r["tool_calls"][0]["arguments"] == {"city": "Paris"} and r["tool_calls"][0]["id"], r)
sent = fake.requests[-1]
check("native: OpenAI tools[] + tool_choice sent upstream", sent["tools"][0]["function"]["name"] == "get_weather" and sent["tool_choice"] == "auto")
hist = U + [{"role": "assistant", "content": "", "tool_calls": r["tool_calls"]}, {"role": "tool", "tool_call_id": r["tool_calls"][0]["id"], "name": "get_weather", "content": '{"temp":21}'}]
r2 = llm.chat(hist, tools=[WEATHER, TIME])
up = fake.requests[-1]["messages"]
check("multi-turn: toolResult reaches the model as role=tool with the call id; assistant tool_calls echoed",
      r2["text"] == 'Result: {"temp":21}' and up[-1]["role"] == "tool" and up[-1]["tool_call_id"] == r["tool_calls"][0]["id"]
      and up[-2]["tool_calls"][0]["function"]["arguments"] == '{"city": "Paris"}', up)
check("tool_choice none -> no tools upstream", "tools" not in (llm.chat(U, tools=[WEATHER], tool_choice="none") and fake.requests[-1]))
fake.handler = lambda b: {"tool_calls": [{"name": "get_time", "arguments": {"tz": "UTC"}}]}
check("tool_choice named is sent as a function choice", llm.chat(U, tools=[WEATHER, TIME], tool_choice={"name": "get_time"})["tool_calls"][0]["name"] == "get_time"
      and fake.requests[-1]["tool_choice"] == {"type": "function", "function": {"name": "get_time"}})

# native but the model emits an invalid call (unknown tool / bad args) -> prompt-translation fallback with constrained schema
seq = iter([{"tool_calls": [{"name": "nope", "arguments": {}}]}, {"content": '```json\n{"tool_calls":[{"name":"get_weather","arguments":{"city":"Rome"}}]}\n```'}])
fake.handler = lambda b: next(seq)
r = llm.chat(U, tools=[WEATHER])
check("invalid native call -> retried through the constrained envelope", r["tool_calls"] and r["tool_calls"][0]["arguments"] == {"city": "Rome"}
      and fake.requests[-1]["response_format"]["type"] == "json_schema", r)
# native: call printed as text -> rescued
fake.handler = lambda b: {"content": 'I will call it: {"name":"get_weather","arguments":{"city":"Oslo"}}'}
r = llm.chat(U, tools=[WEATHER])
check("tool call printed as prose is rescued into tool_calls", r["tool_calls"] and r["tool_calls"][0]["arguments"] == {"city": "Oslo"}, r)
fake.close()

# ── server without tool support (Ollama smollm style): prompt translation, constrained decoding, retries
fake = FakeLLM(tools_supported=False)
reset(endpoint=fake.url)
replies = iter(["Let me check the weather for you!", 'garbage {"tool_calls":[{"name":"get_weather","arguments":{"unit":"k"}}]}',
                '{"tool_calls":[{"name":"get_weather","arguments":{"city":"Lima","unit":"c"}}]}'])
fake.handler = lambda b: {"content": next(replies)}
r = llm.chat(U, system="Be useful.", tools=[WEATHER, TIME])
last = fake.requests[-1]
check("prompt mode: bad prose and schema-invalid args are retried; valid call returned",
      r["tool_calls"][0]["name"] == "get_weather" and r["tool_calls"][0]["arguments"] == {"city": "Lima", "unit": "c"} and r["finish_reason"] == "tool_calls", r)
check("prompt mode: tool schemas in the system prompt, JSON-schema (grammar) constraint requested, corrective turns appended",
      "get_weather" in last["messages"][0]["content"] and "Be useful." in last["messages"][0]["content"] and last["response_format"]["type"] == "json_schema"
      and "rejected" in last["messages"][-1]["content"] and "tools" not in last, last)
check("tokens are summed across attempts", r["input_tokens"] > 0 and r["output_tokens"] > 0)
# answers without a tool
fake.handler = lambda b: {"content": '{"content":"It is sunny."}'}
r = llm.chat(U, tools=[WEATHER])
check("envelope content branch -> plain text answer", r["text"] == "It is sunny." and r["tool_calls"] == [] and r["finish_reason"] == "stop", r)
# history with tool results is flattened into alternating plain turns
fake.handler = lambda b: {"content": '{"content":"done"}'}
llm.chat(hist, tools=[WEATHER])
roles = [m["role"] for m in fake.requests[-1]["messages"]]
check("prompt mode: tool turns flattened to alternating user/assistant", roles == ["system", "user", "assistant", "user"] and
      "Tool result for get_weather" in fake.requests[-1]["messages"][-1]["content"], fake.requests[-1]["messages"])
# forced tool never produced -> clear error, not a fake call
fake.handler = lambda b: {"content": "I refuse to call tools"}
try:
    llm.chat(U, tools=[WEATHER], tool_choice="required")
    check("forced tool call never produced -> LlmStructuredError", False)
except llm.LlmStructuredError as e:
    check("forced tool call never produced -> LlmStructuredError", "valid tool call" in str(e))
fake.close()

# server that can't constrain (400 on response_format): remembered, validation + retry take over
fake = FakeLLM(tools_supported=False, rf_supported=False)
reset(endpoint=fake.url)
fake.handler = lambda b: {"content": '{"tool_calls":[{"name":"get_time","arguments":{"tz":"CET"}}]}'}
r = llm.chat(U, tools=[TIME])
check("server rejecting response_format -> falls back unconstrained and still returns a validated call", r["tool_calls"][0]["arguments"] == {"tz": "CET"}
      and llm._state["no_rf"] is True)
fake.close()

# ── structured output
fake = FakeLLM()
reset(endpoint=fake.url)
SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}, "age": {"type": "integer"}}, "required": ["name", "age"], "additionalProperties": False}
rf = {"type": "json_schema", "name": "person", "schema": SCHEMA}
seq = iter(['{"name": "Ann"}', '```json\n{"name":"Ann","age":"x"}\n```', 'Here: {"name":"Ann","age":31}'])
fake.handler = lambda b: {"content": next(seq)}
r = llm.chat([{"role": "user", "content": "extract"}], response_format=rf)
check("json_schema: honoured via retries, output is exactly the validated JSON", json.loads(r["text"]) == {"name": "Ann", "age": 31}, r)
sent = fake.requests[0]
check("json_schema passed upstream for grammar-constrained decoding + schema stated in prompt", sent["response_format"]["json_schema"]["schema"] == SCHEMA
      and "JSON schema" in sent["messages"][0]["content"])
fake.handler = lambda b: {"content": "never json"}
try:
    llm.chat([{"role": "user", "content": "x"}], response_format=rf)
    check("unsatisfiable structured output -> clear error", False)
except llm.LlmStructuredError as e:
    check("unsatisfiable structured output -> clear error (not silently ignored)", "structured output" in str(e))
fake.handler = lambda b: {"content": '{"a": 1}'}
check("json_object mode", json.loads(llm.chat([{"role": "user", "content": "x"}], response_format={"type": "json_object"})["text"]) == {"a": 1})
fake.close()

# ── per-request model selection
fake = FakeLLM()
reset(endpoint=fake.url)
os.environ["VYOMI_LLM_MODEL_MAP"] = json.dumps({"anthropic.*": "qwen2.5-3b", "gpt-4o": "llama3.2-1b"})
llm.chat(U, model="anthropic.claude-3-haiku")
llm.chat(U, model="gpt-4o")
llm.chat(U, model="unmapped")
check("per-request model: map by exact id and prefix*, default otherwise",
      [r["model"] for r in fake.requests] == ["qwen2.5-3b", "llama3.2-1b", llm.DEFAULT_MODEL], [r["model"] for r in fake.requests])
fake.close()

# ── real upstream streaming: first event arrives while the server is still generating
fake = FakeLLM(delay=0.15)
reset(endpoint=fake.url)
fake.handler = lambda b: {"content": "abcd" * 6}
t0 = time.time()
it = llm.chat_stream(U, max_tokens=64)
first = next(it)
t_first = time.time() - t0
rest = list(it)
t_all = time.time() - t0
txt = first["text"] + "".join(e["text"] for e in rest if e["type"] == "text")
done = rest[-1]
check("streaming is upstream-incremental (first token well before the last)", first["type"] == "text" and t_first < 0.5 and t_all > 0.8, (t_first, t_all))
check("stream: full text + usage from the backend's final chunk", txt == "abcd" * 6 and done["type"] == "done" and done["output_tokens"] > 0 and done["finish_reason"] == "stop", done)
check("stream asked include_usage", fake.requests[-1]["stream"] is True and fake.requests[-1]["stream_options"] == {"include_usage": True})
fake.handler = lambda b: {"tool_calls": [{"name": "get_weather", "arguments": {"city": "Paris", "unit": "c"}}]}
ev = list(llm.chat_stream(U, tools=[WEATHER]))
frag = "".join(e["fragment"] for e in ev if e["type"] == "tool_args")
check("native tool-call stream: tool_start, argument fragments (JSON assembles), done carries the parsed call",
      ev[0]["type"] == "tool_start" and ev[0]["name"] == "get_weather" and sum(e["type"] == "tool_args" for e in ev) > 1 and json.loads(frag) == {"city": "Paris", "unit": "c"}
      and ev[-1]["tool_calls"][0]["arguments"] == {"city": "Paris", "unit": "c"} and ev[-1]["finish_reason"] == "tool_calls", ev)
fake.close()
# unreachable -> error on first next()
reset(endpoint="http://127.0.0.1:9")
try:
    next(llm.chat_stream(U))
    check("stream against a dead endpoint raises on the first next()", False)
except llm.LlmUnavailable:
    check("stream against a dead endpoint raises on the first next()", True)

# ── registered backends: native-tools fn, plain fn (prompt translation), stream_fn
reset()
seen = {}


def native_fn(messages, system, max_tokens, temperature, stop, tools=None, tool_choice=None, response_format=None, model=None):
    seen.update(tools=tools, tool_choice=tool_choice, model=model)
    return {"text": "", "tool_calls": [{"name": "get_time", "arguments": {"tz": "UTC"}}], "input_tokens": 5, "output_tokens": 2}


llm.set_backend(native_fn)
r = llm.chat(U, tools=[WEATHER, TIME], model="m1")
check("registered fn declaring `tools` gets them natively (+ model)", r["tool_calls"][0]["name"] == "get_time" and seen["tools"][1]["name"] == "get_time" and seen["model"] == "m1"
      and r["input_tokens"] == 5)
llm.set_backend(lambda m, s, mt, t, st: '{"tool_calls":[{"name":"get_weather","arguments":{"city":"Kyiv"}}]}')
check("registered plain fn -> prompt translation", llm.chat(U, tools=[WEATHER])["tool_calls"][0]["arguments"] == {"city": "Kyiv"})


def sfn(messages, system, max_tokens, temperature, stop):
    for p in ("one ", "two ", "three"):
        yield p


llm.set_backend(lambda *a: "x", stream_fn=sfn)
ev = list(llm.chat_stream(U))
check("registered stream_fn streams pieces", [e["text"] for e in ev if e["type"] == "text"] == ["one ", "two ", "three"] and ev[-1]["type"] == "done")
reset()

print(f"{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
