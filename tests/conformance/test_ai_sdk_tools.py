"""Real-SDK conformance for the AI seam: boto3 bedrock-runtime (Converse/ConverseStream tool loop, structured output),
google-genai (Vertex generateContent function calling, responseSchema, streaming) and openai.AzureOpenAI (tools, json_schema,
streaming, include_usage) against the unified router served over real HTTP by core.wire_ingress (the offline path), backed by a
deterministic OpenAI-compatible fake model server over real HTTP (tests/conformance/llm_fakes.py).

Skips (exit 0) when boto3 / google-genai / openai are not installed.
Run: PYTHONPATH=. python tests/conformance/test_ai_sdk_tools.py
"""
import json
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_fakes import FakeLLM  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {str(extra)[:500]}")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    import uvicorn
    from fastapi import FastAPI, Request
    from core import llm_core as llm
    from core.aws_wire_router import AwsWireRouter
    from core.azure_arm_core import AzureArm
    from core import wire_ingress

    fake = FakeLLM(delay=0.02)
    llm.set_backend(None)
    llm._state.update(endpoint=fake.url, no_rf=False, no_native=False)
    os.environ.pop("VYOMI_LLM_DISABLE", None)
    router = AwsWireRouter()
    router.az_arm = AzureArm()
    base = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/oai1"
    router.az_arm.handle("PUT", base, {"api-version": "2024-10-01"}, {"kind": "OpenAI", "location": "eastus", "sku": {"name": "S0"}})
    router.az_arm.handle("PUT", base + "/deployments/chat", {"api-version": "2024-10-01"},
                         {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-11-20"}}})
    app = FastAPI()
    try:                                   # the account's advertised endpoint: /azure-data/openai/{account}/... (providers/azure_openai_routes)
        from providers import azure_services, azure_openai_routes
        azure_services._state.update(router.az_arm.state)
        azure_openai_routes.register(app)
        have_dp = True
    except Exception as e:
        print("azure data-plane route unavailable:", e)
        have_dp = False

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)

    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"

    WX = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}

    def agent(body):
        msgs = body["messages"]
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        if body.get("response_format"):
            return {"content": '{"city":"Paris","temp":21}'}
        if body.get("tools") and not tool_msgs:
            return {"tool_calls": [{"name": "get_weather", "arguments": {"city": "Paris"}}]}
        if tool_msgs:
            return {"content": "Paris is 21C."}
        return {"content": "hello from the local model"}
    fake.handler = agent

    # ───────── AWS Bedrock (boto3)
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("boto3 missing - skipping Bedrock")
        boto3 = None
    if boto3:
        br = boto3.client("bedrock-runtime", region_name="us-east-1", endpoint_url=url, aws_access_key_id="x", aws_secret_access_key="y",
                          config=Config(retries={"max_attempts": 1}))
        tc = {"tools": [{"toolSpec": {"name": "get_weather", "description": "weather", "inputSchema": {"json": WX}}}], "toolChoice": {"auto": {}}}
        msgs = [{"role": "user", "content": [{"text": "weather in Paris?"}]}]
        r1 = br.converse(modelId="anthropic.claude-3-haiku-20240307-v1:0", messages=msgs, toolConfig=tc, inferenceConfig={"maxTokens": 200, "topP": 0.9})
        tu = [b["toolUse"] for b in r1["output"]["message"]["content"] if "toolUse" in b][0]
        check("boto3 converse: stopReason tool_use + toolUse block", r1["stopReason"] == "tool_use" and tu["name"] == "get_weather" and tu["input"] == {"city": "Paris"}, r1)
        msgs += [r1["output"]["message"], {"role": "user", "content": [{"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"json": {"temp": 21}}]}}]}]
        r2 = br.converse(modelId="anthropic.claude-3-haiku-20240307-v1:0", messages=msgs, toolConfig=tc)
        check("boto3 converse: toolResult round-trip -> final text", r2["stopReason"] == "end_turn" and r2["output"]["message"]["content"][0]["text"] == "Paris is 21C.", r2)
        up = fake.requests[-1]["messages"]
        check("converse toolResult reached the model as a role=tool message with the same id", up[-1]["role"] == "tool" and up[-1]["tool_call_id"] == tu["toolUseId"]
              and up[-2]["tool_calls"][0]["function"]["name"] == "get_weather", up)
        # streaming tool use
        t0 = time.time()
        rs = br.converse_stream(modelId="amazon.nova-lite-v1:0", messages=[msgs[0]], toolConfig=tc)
        got, args, name, stop, first_t = [], "", None, None, None
        for ev in rs["stream"]:
            first_t = first_t or time.time() - t0
            if "contentBlockStart" in ev:
                name = ev["contentBlockStart"]["start"]["toolUse"]["name"]
            if "contentBlockDelta" in ev and "toolUse" in ev["contentBlockDelta"]["delta"]:
                args += ev["contentBlockDelta"]["delta"]["toolUse"]["input"]
            if "messageStop" in ev:
                stop = ev["messageStop"]["stopReason"]
            got.append(list(ev)[0])
        check("boto3 converse_stream: toolUse start + input JSON fragments + stopReason tool_use",
              name == "get_weather" and json.loads(args) == {"city": "Paris"} and stop == "tool_use" and got[-1] == "metadata", (name, args, stop, got))
        fake.handler = lambda b: {"content": "streamed text reply"}
        pieces, ts = [], []
        for ev in br.converse_stream(modelId="amazon.nova-lite-v1:0", messages=[msgs[0]])["stream"]:
            if "contentBlockDelta" in ev:
                pieces.append(ev["contentBlockDelta"]["delta"]["text"])
                ts.append(time.time())
        check("boto3 converse_stream text arrives incrementally (several deltas over time, not one slice)", "".join(pieces) == "streamed text reply" and len(pieces) >= 4
              and ts[-1] - ts[0] > 0.05, (pieces, ts[-1] - ts[0]))
        fake.handler = agent
        # structured output
        so = br.converse(modelId="amazon.nova-lite-v1:0", messages=msgs[:1], outputConfig={"textFormat": {"type": "json_schema", "structure": {"jsonSchema": {
            "name": "wx", "schema": json.dumps({"type": "object", "properties": {"city": {"type": "string"}, "temp": {"type": "integer"}}, "required": ["city", "temp"]})}}}})
        check("boto3 converse outputConfig.textFormat json_schema honoured", json.loads(so["output"]["message"]["content"][0]["text"]) == {"city": "Paris", "temp": 21}, so)
        fake.handler = lambda b: {"content": "not json at all"}
        try:
            br.converse(modelId="amazon.nova-lite-v1:0", messages=msgs[:1], outputConfig={"textFormat": {"type": "json_schema", "structure": {"jsonSchema": {
                "name": "wx", "schema": json.dumps({"type": "object"})}}}})
            check("converse unsatisfiable structured output -> ModelErrorException", False)
        except Exception as e:
            check("converse unsatisfiable structured output -> ModelErrorException (424)", "ModelErrorException" in str(e), e)
        fake.handler = agent
        try:
            br.converse(modelId="amazon.nova-lite-v1:0", messages=msgs[:1], guardrailConfig={"guardrailIdentifier": "g", "guardrailVersion": "1"})
            check("guardrailConfig is rejected, not ignored", False)
        except Exception as e:
            check("guardrailConfig is rejected, not ignored", "ValidationException" in str(e), e)
        # Claude InvokeModel tool use
        body = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 200, "messages": [{"role": "user", "content": "weather in Paris?"}],
                "tools": [{"name": "get_weather", "description": "w", "input_schema": WX}]}
        ir = json.loads(br.invoke_model(modelId="anthropic.claude-3-haiku-20240307-v1:0", body=json.dumps(body))["body"].read())
        check("boto3 invoke_model (Claude) tool_use block + stop_reason", ir["stop_reason"] == "tool_use" and ir["content"][0]["type"] == "tool_use"
              and ir["content"][0]["input"] == {"city": "Paris"}, ir)

    # ───────── Vertex (google-genai)
    try:
        from google import genai
        from google.genai import types
        from google.auth.credentials import Credentials
    except ImportError:
        print("google-genai missing - skipping Vertex")
        genai = None
    if genai:
        class FakeCreds(Credentials):          # google-genai refreshes ADC for Vertex; the simulator ignores the bearer
            def refresh(self, request):
                self.token = "vyomi-test-token"
        fake.handler = agent
        client = genai.Client(vertexai=True, project="p1", location="us-central1", credentials=FakeCreds(),
                              http_options=types.HttpOptions(base_url=url, api_version="v1"))
        fd = types.FunctionDeclaration(name="get_weather", description="weather", parameters=types.Schema(
            type="OBJECT", properties={"city": types.Schema(type="STRING")}, required=["city"]))
        cfg = types.GenerateContentConfig(tools=[types.Tool(function_declarations=[fd])],
                                          automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
        rg = client.models.generate_content(model="gemini-2.0-flash", contents="weather in Paris?", config=cfg)
        fc = rg.function_calls[0]
        check("google-genai generate_content: functionCall part", fc.name == "get_weather" and fc.args == {"city": "Paris"}, rg)
        up = fake.requests[-1]
        check("Gemini OBJECT/STRING schema reached the model as JSON schema (lowercase types)", up["tools"][0]["function"]["parameters"]["type"] == "object"
              and up["tools"][0]["function"]["parameters"]["properties"]["city"]["type"] == "string", up["tools"])
        contents = [types.Content(role="user", parts=[types.Part(text="weather in Paris?")]),
                    types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="get_weather", args={"city": "Paris"}))]),
                    types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(name="get_weather", response={"temp": 21}))])]
        rg2 = client.models.generate_content(model="gemini-2.0-flash", contents=contents, config=cfg)
        check("google-genai functionResponse round-trip -> final text", rg2.text == "Paris is 21C." and rg2.usage_metadata.total_token_count > 0, rg2)
        check("functionResponse reached the model as a tool message for the matching call", fake.requests[-1]["messages"][-1]["role"] == "tool"
              and json.loads(fake.requests[-1]["messages"][-1]["content"]) == {"temp": 21}, fake.requests[-1]["messages"])
        sch = types.GenerateContentConfig(response_mime_type="application/json", response_schema=types.Schema(
            type="OBJECT", properties={"city": types.Schema(type="STRING"), "temp": types.Schema(type="INTEGER")}, required=["city", "temp"]))
        rj = client.models.generate_content(model="gemini-2.0-flash", contents="weather in Paris? as json", config=sch)
        check("google-genai responseSchema honoured (valid JSON matching schema)", json.loads(rj.text) == {"city": "Paris", "temp": 21}, rj)
        fake.handler = lambda b: {"content": "this is not json"}
        try:
            client.models.generate_content(model="gemini-2.0-flash", contents="x", config=sch)
            check("responseSchema unsatisfiable -> error, not prose", False)
        except Exception as e:
            check("responseSchema unsatisfiable -> error, not prose", "INTERNAL" in str(e) or "500" in str(e), e)
        fake.handler = lambda b: {"content": "streamed text reply"}
        ts, parts = [], []
        for ch in client.models.generate_content_stream(model="gemini-2.0-flash", contents="hi"):
            if ch.text:
                parts.append(ch.text)
                ts.append(time.time())
        check("google-genai generate_content_stream incremental", "".join(parts) == "streamed text reply" and len(parts) >= 4 and ts[-1] - ts[0] > 0.05, (parts, ts[-1] - ts[0]))
        fake.handler = agent
        rs = list(client.models.generate_content_stream(model="gemini-2.0-flash", contents="weather in Paris?", config=cfg))
        check("google-genai stream carries the functionCall + usage", any(c.function_calls for c in rs) and rs[-1].usage_metadata.total_token_count > 0, rs)
        try:
            client.models.generate_content(model="gemini-2.0-flash", contents="x", config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]))
            check("unsupported tool kind rejected clearly", False)
        except Exception as e:
            check("unsupported tool kind rejected clearly", "INVALID_ARGUMENT" in str(e) or "400" in str(e), e)

    # ───────── Azure OpenAI (openai SDK)
    try:
        from openai import AzureOpenAI
    except ImportError:
        print("openai missing - skipping Azure")
        AzureOpenAI = None
    if AzureOpenAI:
        fake.handler = agent
        oc = AzureOpenAI(azure_endpoint=url, api_key="k", api_version="2024-10-21", max_retries=0)
        tools = [{"type": "function", "function": {"name": "get_weather", "description": "w", "parameters": WX}}]
        m = [{"role": "user", "content": "weather in Paris?"}]
        c1 = oc.chat.completions.create(model="chat", messages=m, tools=tools)
        tcall = c1.choices[0].message.tool_calls[0]
        check("openai AzureOpenAI tools: finish_reason tool_calls + parsed tool_calls[0].function", c1.choices[0].finish_reason == "tool_calls"
              and tcall.function.name == "get_weather" and json.loads(tcall.function.arguments) == {"city": "Paris"} and c1.choices[0].message.content is None, c1)
        m += [c1.choices[0].message, {"role": "tool", "tool_call_id": tcall.id, "content": '{"temp":21}'}]
        c2 = oc.chat.completions.create(model="chat", messages=m, tools=tools)
        check("openai tool result round-trip -> final text", c2.choices[0].message.content == "Paris is 21C." and c2.usage.total_tokens > 0, c2)
        ts, calls_args, name, usage_chunk = [], "", None, None
        for ch in oc.chat.completions.create(model="chat", messages=m[:1], tools=tools, stream=True, stream_options={"include_usage": True}):
            if ch.usage:
                usage_chunk = ch.usage
            for c in (ch.choices[0].delta.tool_calls or []) if ch.choices else []:
                name = c.function.name or name
                calls_args += c.function.arguments or ""
        check("openai stream: delta.tool_calls fragments assemble + include_usage chunk", name == "get_weather" and json.loads(calls_args) == {"city": "Paris"}
              and usage_chunk is not None and usage_chunk.total_tokens > 0, (name, calls_args, usage_chunk))
        fake.handler = lambda b: {"content": "streamed text reply"}
        ts, txt = [], ""
        for ch in oc.chat.completions.create(model="chat", messages=m[:1], stream=True):
            if ch.choices and ch.choices[0].delta.content:
                txt += ch.choices[0].delta.content
                ts.append(time.time())
        check("openai text stream incremental", txt == "streamed text reply" and len(ts) >= 4 and ts[-1] - ts[0] > 0.05, (txt, len(ts)))
        fake.handler = agent
        rf = {"type": "json_schema", "json_schema": {"name": "wx", "strict": True, "schema": {"type": "object", "properties": {"city": {"type": "string"}, "temp": {"type": "integer"}},
                                                                                              "required": ["city", "temp"]}}}
        cj = oc.chat.completions.create(model="chat", messages=m[:1], response_format=rf)
        check("openai json_schema honoured", json.loads(cj.choices[0].message.content) == {"city": "Paris", "temp": 21}, cj)
        cj = oc.chat.completions.create(model="chat", messages=m[:1], response_format={"type": "json_object"})
        check("openai json_object honoured (valid JSON)", isinstance(json.loads(cj.choices[0].message.content), dict), cj)
        fake.handler = lambda b: {"content": "nope"}
        try:
            oc.chat.completions.create(model="chat", messages=m[:1], response_format=rf)
            check("openai unsatisfiable json_schema -> error", False)
        except Exception as e:
            check("openai unsatisfiable json_schema -> 500 model_error, not prose", "model_error" in str(e) or "500" in str(e), e)
        try:
            oc.chat.completions.create(model="chat", messages=m[:1], tools=[{"type": "function"}])
            check("malformed tools -> 400", False)
        except Exception as e:
            check("malformed tools -> 400 BadRequest", "400" in str(e), e)
        if have_dp:
            fake.handler = agent
            dp = AzureOpenAI(azure_endpoint=url + "/azure-data/openai/oai1", api_key=next(r["_keys"]["key1"] for r in router.az_arm.state.values() if r.get("name") == "oai1"), api_version="2024-10-21", max_retries=0)
            d1 = dp.chat.completions.create(model="chat", messages=m[:1], tools=tools)
            check("UNIFIED: /azure-data/openai/<account> (the endpoint the account advertises) serves tool calls from the same seam",
                  d1.choices[0].message.tool_calls[0].function.name == "get_weather" and "SIMULATED" not in str(d1), d1)
            fake.handler = lambda b: {"content": "streamed text reply"}
            txt = "".join(ch.choices[0].delta.content or "" for ch in dp.chat.completions.create(model="chat", messages=m[:1], stream=True) if ch.choices)
            check("UNIFIED: account endpoint streams from the real model", txt == "streamed text reply", txt)
    fake.close()
    srv.should_exit = True


if __name__ == "__main__":
    main()
    print(f"{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


def test_ai_sdk_tools():
    main()
    assert FAIL == 0
