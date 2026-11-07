"""Native-SDK conformance for the two hosted-agent lanes (Dev Simplified), over real HTTP via core.wire_ingress, with the
deterministic fake model server of llm_fakes.py behind the llm_core seam (the same lanes use the booster model when it is up):

  GCP : Vertex AI Agent Engine reasoningEngines - google-cloud-aiplatform gapic clients (REST transport): create (LRO) / get /
        list / update / delete, ReasoningEngineExecutionServiceClient.query_reasoning_engine + stream_query_reasoning_engine,
        sessions, plus raw httpx. The agent is a Vyomi agent spec (core/agent_spec_core) carried in spec.deploymentSpec.env.
  AWS : Bedrock AgentCore - boto3 'bedrock-agentcore-control' (runtimes, endpoints, versions) + 'bedrock-agentcore'
        invoke_agent_runtime running the agent spec (tool loop, session memory, SSE) + aws CLI smoke.

Skips a lane when its SDK is missing. Run: PYTHONPATH=. python tests/conformance/test_ai_agent_runtimes.py
"""
import base64
import json
import os
import shutil
import socket
import subprocess
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
        print(f"  FAIL {name} {str(extra)[:600]}")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


WX = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
SPEC = {"instructions": "You are a weather agent. Use get_weather for any weather question.", "max_steps": 4,
        "tools": [{"name": "get_weather", "description": "Weather for a city", "parameters": WX, "type": "static",
                   "cases": [{"match": {"city": "Paris"}, "result": {"temp_c": 21, "sky": "clear"}}], "result": {"temp_c": 0, "sky": "unknown"}},
                  {"name": "calc", "description": "Evaluate arithmetic", "type": "builtin", "builtin": "calculator",
                   "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}]}


def agent(body):
    """Scripted model: weather question -> call get_weather, then answer from the tool result; arithmetic -> calc."""
    msgs = body["messages"]
    if msgs[-1]["role"] == "tool":
        return {"content": "Tool said: " + msgs[-1]["content"]}
    last_user = msgs[-1]["content"].lower()
    if body.get("tools"):
        if "weather" in last_user:
            return {"tool_calls": [{"name": "get_weather", "arguments": {"city": "Paris"}}]}
        if "calc" in last_user:
            return {"tool_calls": [{"name": "calc", "arguments": {"expression": "6*7"}}]}
    return {"content": "plain answer; history=" + str(len([m for m in msgs if m["role"] in ("user", "assistant")]))}


def main():
    import uvicorn
    from fastapi import FastAPI, Request
    from core import llm_core as llm
    from core.aws_wire_router import AwsWireRouter
    from core import wire_ingress

    fake = FakeLLM(handler=agent, delay=0.01)
    llm.set_backend(None)
    llm._state.update(endpoint=fake.url, no_rf=False, no_native=False)
    os.environ.pop("VYOMI_LLM_DISABLE", None)
    router = AwsWireRouter()
    app = FastAPI()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)

    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"

    gcp_lane(url, fake)
    aws_lane(url, fake)
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


# ═════════════════════════════════ GCP: Vertex AI Agent Engine ═════════════════════════════════
def gcp_lane(url, fake):
    try:
        import httpx
        from google.api_core.client_options import ClientOptions
        from google.auth.credentials import AnonymousCredentials
        from google.cloud import aiplatform_v1 as av
        from google.api_core import exceptions as gex
    except ImportError as e:
        print(f"google-cloud-aiplatform missing ({e}) - skipping Agent Engine")
        return
    print("== Vertex AI Agent Engine")
    parent = "projects/vyomi-proj/locations/us-central1"
    opts = ClientOptions(api_endpoint=url)
    mk = lambda cls: cls(transport="rest", client_options=opts, credentials=AnonymousCredentials())  # noqa: E731
    # pin the REST scheme: the gapic client builds https:// from api_endpoint, so give it a full http URL via the transport host
    svc = av.ReasoningEngineServiceClient(transport="rest", client_options=opts, credentials=AnonymousCredentials())
    svc.transport._host = url
    ex = av.ReasoningEngineExecutionServiceClient(transport="rest", client_options=opts, credentials=AnonymousCredentials())
    ex.transport._host = url
    fake.handler = agent

    env = [av.EnvVar(name="VYOMI_AGENT_SPEC", value=json.dumps(SPEC))]
    eng = av.ReasoningEngine(display_name="weather-agent", description="spec agent",
                             spec=av.ReasoningEngineSpec(deployment_spec=av.ReasoningEngineSpec.DeploymentSpec(env=env)))
    op = svc.create_reasoning_engine(parent=parent, reasoning_engine=eng)
    res = op.result(timeout=30)
    check("create_reasoning_engine returns an LRO that resolves to the engine", res.name.startswith(parent + "/reasoningEngines/") and res.display_name == "weather-agent", res)
    check("create_reasoning_engine fills default class_methods", {"query", "stream_query"} <= {dict(m)["name"] for m in res.spec.class_methods}, res.spec.class_methods)
    got = svc.get_reasoning_engine(name=res.name)
    check("get_reasoning_engine round-trips the spec env", got.spec.deployment_spec.env[0].name == "VYOMI_AGENT_SPEC" and json.loads(got.spec.deployment_spec.env[0].value)["max_steps"] == 4)
    lst = list(svc.list_reasoning_engines(parent=parent))
    check("list_reasoning_engines lists it", [e.name for e in lst] == [res.name])
    try:
        svc.get_reasoning_engine(name=parent + "/reasoningEngines/123")
        check("get unknown engine -> NotFound", False)
    except gex.NotFound:
        check("get unknown engine -> NotFound", True)
    try:
        svc.create_reasoning_engine(parent=parent, reasoning_engine=av.ReasoningEngine(
            display_name="bad", spec=av.ReasoningEngineSpec(deployment_spec=av.ReasoningEngineSpec.DeploymentSpec(
                env=[av.EnvVar(name="VYOMI_AGENT_SPEC", value=json.dumps({"tools": [{"name": "x", "type": "nope"}]}))])))).result()
        check("create with an invalid agent spec -> InvalidArgument", False)
    except gex.BadRequest:
        check("create with an invalid agent spec -> InvalidArgument", True)

    from google.protobuf import struct_pb2
    n0 = len(fake.requests)
    inp = struct_pb2.Struct()
    inp.update({"message": "What is the weather in Paris?"})
    r = ex.query_reasoning_engine(request=av.QueryReasoningEngineRequest(name=res.name, input=inp, class_method="query"))
    from google.protobuf.json_format import MessageToDict
    out = MessageToDict(r._pb.output)
    check("query_reasoning_engine ran a real tool loop (model -> get_weather -> model)", "21" in json.dumps(out) and len(fake.requests) - n0 == 2, (out, len(fake.requests) - n0))
    check("query output carries the tool trace + usage", [s["type"] for s in out["steps"]] == ["model", "tool_result", "model"] and out["usage"]["output_tokens"] > 0, out)
    check("the model got the spec's instructions + tool schema", fake.requests[n0]["messages"][0]["content"].startswith("You are a weather agent")
          and any(t["function"]["name"] == "get_weather" for t in fake.requests[n0]["tools"]), fake.requests[n0])

    # sessions + :streamQuery
    sin = struct_pb2.Struct()
    sin.update({"user_id": "u1"})
    sess = MessageToDict(ex.query_reasoning_engine(request=av.QueryReasoningEngineRequest(name=res.name, input=sin, class_method="create_session"))._pb.output)
    check("create_session returns a session id", bool(sess.get("id")) and sess["userId"] == "u1", sess)
    qin = struct_pb2.Struct()
    qin.update({"message": "What is the weather in Paris?", "user_id": "u1", "session_id": sess["id"]})
    evs, stamps = [], []
    for chunk in ex.stream_query_reasoning_engine(request=av.StreamQueryReasoningEngineRequest(name=res.name, input=qin, class_method="stream_query")):
        evs.append(json.loads(chunk.data))
        stamps.append(time.time())
    parts = [p for e in evs for p in e["content"]["parts"]]
    check("stream_query_reasoning_engine yields ADK-shaped events: function_call, function_response, final text",
          [("function_call" in p) * 1 + ("function_response" in p) * 2 + ("text" in p) * 4 for p in parts] == [1, 2, 4] and "21" in parts[-1]["text"], evs)
    check("final event is turn_complete with usage_metadata", evs[-1].get("turn_complete") is True and evs[-1]["usage_metadata"]["total_token_count"] > 0, evs[-1])
    gin = struct_pb2.Struct()
    gin.update({"user_id": "u1", "session_id": sess["id"]})
    sg = MessageToDict(ex.query_reasoning_engine(request=av.QueryReasoningEngineRequest(name=res.name, input=gin, class_method="get_session"))._pb.output)
    check("session remembers the turn (user + model events)", len(sg["events"]) == 2, sg)
    qin2 = struct_pb2.Struct()
    qin2.update({"message": "and again?", "user_id": "u1", "session_id": sess["id"]})
    n1 = len(fake.requests)
    list(ex.stream_query_reasoning_engine(request=av.StreamQueryReasoningEngineRequest(name=res.name, input=qin2, class_method="stream_query")))
    prior = [m for m in fake.requests[n1]["messages"] if m["role"] in ("user", "assistant", "tool")]
    check("second streamed turn replays the session history to the model", len(prior) >= 4, fake.requests[n1]["messages"])

    # update + raw httpx
    with httpx.Client(base_url=url, timeout=30) as h:
        sp2 = dict(SPEC, instructions="Updated instructions.")
        r = h.patch(f"/v1/{res.name}", params={"updateMask": "spec"}, json={"spec": {"vyomiAgentSpec": sp2}})
        check("PATCH ...?updateMask=spec -> done LRO with the new spec (REST vyomiAgentSpec field)", r.status_code == 200 and r.json()["done"] and r.json()["response"]["spec"]["vyomiAgentSpec"]["instructions"] == "Updated instructions.", r.text)
        n2 = len(fake.requests)
        r = h.post(f"/v1/{res.name}:query", json={"classMethod": "query", "input": {"message": "hello"}})
        check("httpx :query (no tools called) -> output.output + the updated instructions reached the model",
              r.status_code == 200 and r.json()["output"]["output"].startswith("plain answer") and fake.requests[n2]["messages"][0]["content"] == "Updated instructions.", r.text)
        r = h.post(f"/v1/{res.name}:query", json={"classMethod": "query", "input": {}})
        check(":query without input.message -> 400 INVALID_ARGUMENT", r.status_code == 400 and r.json()["error"]["status"] == "INVALID_ARGUMENT", r.text)
        r = h.post(f"/v1/{res.name}:streamQuery", json={"classMethod": "stream_query", "input": {"message": "calc please"}})
        arr = r.json()
        evs2 = [json.loads(base64.b64decode(x["data"])) for x in arr]
        check("httpx :streamQuery is a JSON array of HttpBody (base64 events) with the calc tool result 42",
              r.status_code == 200 and "42" in json.dumps(evs2) and arr[0]["contentType"] == "application/json", r.text[:300])
        r = h.post(f"/v1/{res.name}:query", json={"classMethod": "stream_query", "input": {"message": "x"}})
        check(":query on a streaming class method -> 400", r.status_code == 400, r.text)
        r = h.post(f"/v1/{parent}/reasoningEngines", json={"displayName": "no-spec"})
        nid = r.json()["response"]["name"]
        r = h.post(f"/v1/{nid}:query", json={"input": {"message": "hi"}})
        check("engine without an agent spec: control plane ok, :query -> FAILED_PRECONDITION (honest)", r.status_code == 400 and r.json()["error"]["status"] == "FAILED_PRECONDITION", r.text)
        fake.tools_supported = True
    from core import llm_core as llm
    saved = llm._state.get("endpoint")
    llm._state["endpoint"] = "http://127.0.0.1:9"        # model backend down -> 503 UNAVAILABLE, never a canned answer
    with httpx.Client(base_url=url, timeout=30) as h:
        r = h.post(f"/v1/{res.name}:query", json={"input": {"message": "hello"}})
        check("model backend down -> 503 UNAVAILABLE (no fake answer)", r.status_code == 503 and r.json()["error"]["status"] == "UNAVAILABLE", r.text)
    llm._state["endpoint"] = saved

    # delete
    try:
        svc.delete_reasoning_engine(request=av.DeleteReasoningEngineRequest(name=res.name))
        check("delete with sessions and no force -> FailedPrecondition", False)
    except gex.BadRequest as e:
        check("delete with sessions and no force -> 400 FAILED_PRECONDITION", "child resources" in str(e))
    svc.delete_reasoning_engine(request=av.DeleteReasoningEngineRequest(name=res.name, force=True)).result(timeout=30)
    try:
        svc.get_reasoning_engine(name=res.name)
        check("deleted engine is gone", False)
    except gex.NotFound:
        check("deleted engine is gone", True)

    gc = shutil.which("gcloud")
    if gc:
        r = subprocess.run([gc, "ai", "reasoning-engines", "--help"], capture_output=True, text=True, timeout=60)
        has = r.returncode == 0
        print(f"  note gcloud ai reasoning-engines {'present' if has else 'absent in this gcloud (REST/gapic cover it)'}")


# ═════════════════════════════════ AWS: Bedrock AgentCore ═════════════════════════════════
def aws_lane(url, fake):
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("boto3 missing - skipping AgentCore")
        return
    print("== Bedrock AgentCore")
    kw = dict(region_name="us-east-1", endpoint_url=url, aws_access_key_id="x", aws_secret_access_key="y", config=Config(retries={"max_attempts": 1}))
    ctl = boto3.client("bedrock-agentcore-control", **kw)
    dp = boto3.client("bedrock-agentcore", **kw)
    fake.handler = agent
    art = {"containerConfiguration": {"containerUri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/vyomi-agent:latest"}}
    c = ctl.create_agent_runtime(agentRuntimeName="weather_agent", agentRuntimeArtifact=art, roleArn="arn:aws:iam::123456789012:role/r",
                                 networkConfiguration={"networkMode": "PUBLIC"}, environmentVariables={"VYOMI_AGENT_SPEC": json.dumps(SPEC)})
    arn, rid = c["agentRuntimeArn"], c["agentRuntimeId"]
    check("CreateAgentRuntime (PUT /runtimes/) -> CREATING with ARN + version 1", c["status"] == "CREATING" and c["agentRuntimeVersion"] == "1" and arn.endswith("runtime/" + rid), c)
    for _ in range(40):
        g = ctl.get_agent_runtime(agentRuntimeId=rid)
        if g["status"] == "READY":
            break
        time.sleep(0.25)
    check("GetAgentRuntime reaches READY and echoes the env/spec", g["status"] == "READY" and json.loads(g["environmentVariables"]["VYOMI_AGENT_SPEC"])["max_steps"] == 4, g)
    check("ListAgentRuntimes (POST /runtimes/) lists it", [r["agentRuntimeId"] for r in ctl.list_agent_runtimes()["agentRuntimes"]] == [rid])
    eps = ctl.list_agent_runtime_endpoints(agentRuntimeId=rid)["runtimeEndpoints"]
    check("a DEFAULT endpoint exists after create", [e["name"] for e in eps] == ["DEFAULT"], eps)

    n0 = len(fake.requests)
    inv = dp.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId="s" * 33, payload=json.dumps({"prompt": "What is the weather in Paris?"}).encode())
    body = json.loads(inv["response"].read())
    check("InvokeAgentRuntime runs the agent spec: tool loop -> answer built from get_weather result",
          inv["statusCode"] == 200 and "21" in body["response"] and body["toolCalls"][0]["name"] == "get_weather" and len(fake.requests) - n0 == 2, (inv.get("statusCode"), body))
    check("InvokeAgentRuntime echoes the runtime session id", inv["runtimeSessionId"] == "s" * 33, inv.get("runtimeSessionId"))
    n1 = len(fake.requests)
    inv = dp.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId="s" * 33, payload=json.dumps({"prompt": "thanks"}).encode())
    json.loads(inv["response"].read())
    prior = [m for m in fake.requests[n1]["messages"] if m["role"] in ("user", "assistant", "tool")]
    check("the same runtimeSessionId carries the earlier turn (session memory)", len(prior) >= 4, fake.requests[n1]["messages"])
    n2 = len(fake.requests)
    inv = dp.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId="t" * 33, payload=json.dumps({"prompt": "thanks"}).encode())
    json.loads(inv["response"].read())
    check("a different session does not see it", len([m for m in fake.requests[n2]["messages"] if m["role"] != "system"]) == 1)
    inv = dp.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId="u" * 33, accept="text/event-stream", payload=json.dumps({"prompt": "calc please"}).encode())
    raw = inv["response"].read().decode()
    evs = [json.loads(l[6:]) for l in raw.split("\n\n") if l.startswith("data: ")]
    check("Accept: text/event-stream -> SSE tool_use / tool_result / final events (42)", [e["event"] for e in evs] == ["tool_use", "tool_result", "message", "final"] and "42" in raw
          and inv["contentType"].startswith("text/event-stream"), raw[:300])
    hook = lambda params, **kw: params["headers"].__setitem__("X-Amzn-Bedrock-AgentCore-Runtime-Session-Id", "short")  # noqa: E731 - bypass client-side length check
    dp.meta.events.register("before-call.bedrock-agentcore.InvokeAgentRuntime", hook)
    try:
        dp.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId="s" * 33, payload=b'{"prompt":"x"}')
        check("short runtime session id (server side) -> ValidationException", False)
    except dp.exceptions.ValidationException:
        check("short runtime session id (server side) -> ValidationException", True)
    dp.meta.events.unregister("before-call.bedrock-agentcore.InvokeAgentRuntime", hook)
    try:
        dp.invoke_agent_runtime(agentRuntimeArn=arn.replace(rid, "nope_abc123"), runtimeSessionId="s" * 33, payload=b'{"prompt":"x"}')
        check("invoke unknown runtime -> ResourceNotFoundException", False)
    except dp.exceptions.ResourceNotFoundException:
        check("invoke unknown runtime -> ResourceNotFoundException", True)
    st = dp.stop_runtime_session(agentRuntimeArn=arn, runtimeSessionId="s" * 33)
    check("StopRuntimeSession ends the session", st["statusCode"] == 200, st)

    # endpoints + versions + update
    up = ctl.update_agent_runtime(agentRuntimeId=rid, agentRuntimeArtifact=art, roleArn="arn:aws:iam::123456789012:role/r", networkConfiguration={"networkMode": "PUBLIC"},
                                  environmentVariables={"VYOMI_AGENT_SPEC": json.dumps(dict(SPEC, instructions="v2 instructions"))})
    check("UpdateAgentRuntime bumps the version to 2", up["agentRuntimeVersion"] == "2", up)
    vs = ctl.list_agent_runtime_versions(agentRuntimeId=rid)["agentRuntimes"]
    check("ListAgentRuntimeVersions lists v1 and v2", [v["agentRuntimeVersion"] for v in vs] == ["1", "2"], vs)
    ce = ctl.create_agent_runtime_endpoint(agentRuntimeId=rid, name="prod", agentRuntimeVersion="2")
    check("CreateAgentRuntimeEndpoint -> prod @ v2", ce["endpointName"] == "prod" and ce["targetVersion"] == "2", ce)
    time.sleep(1.2)
    ge = ctl.get_agent_runtime_endpoint(agentRuntimeId=rid, endpointName="prod")
    check("GetAgentRuntimeEndpoint READY, liveVersion 2", ge["status"] == "READY" and ge["liveVersion"] == "2", ge)
    n3 = len(fake.requests)
    inv = dp.invoke_agent_runtime(agentRuntimeArn=arn, qualifier="prod", runtimeSessionId="p" * 33, payload=b'{"prompt":"hello"}')
    json.loads(inv["response"].read())
    check("invoke with qualifier=prod runs the updated spec", fake.requests[n3]["messages"][0]["content"] == "v2 instructions", fake.requests[n3]["messages"][0])
    try:
        dp.invoke_agent_runtime(agentRuntimeArn=arn, qualifier="ghost", runtimeSessionId="p" * 33, payload=b'{"prompt":"hello"}')
        check("unknown qualifier -> ResourceNotFoundException", False)
    except dp.exceptions.ResourceNotFoundException:
        check("unknown qualifier -> ResourceNotFoundException", True)
    ctl.delete_agent_runtime_endpoint(agentRuntimeId=rid, endpointName="prod")
    check("DeleteAgentRuntimeEndpoint removes it", [e["name"] for e in ctl.list_agent_runtime_endpoints(agentRuntimeId=rid)["runtimeEndpoints"]] == ["DEFAULT"])
    # no spec -> honest 424; model down -> 503
    c2 = ctl.create_agent_runtime(agentRuntimeName="container_only", agentRuntimeArtifact=art, roleArn="arn:aws:iam::123456789012:role/r", networkConfiguration={"networkMode": "PUBLIC"})
    time.sleep(1.2)
    try:
        dp.invoke_agent_runtime(agentRuntimeArn=c2["agentRuntimeArn"], runtimeSessionId="q" * 33, payload=b'{"prompt":"hi"}')
        check("runtime without an agent spec -> RuntimeClientError (container not run)", False)
    except dp.exceptions.RuntimeClientError as e:
        check("runtime without an agent spec -> RuntimeClientError (container not run)", "does not run" in str(e), e)
    from core import llm_core as llm
    from core import llm_core as llm
    saved = llm._state.get("endpoint")
    llm._state["endpoint"] = "http://127.0.0.1:9"
    try:
        dp.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId="z" * 33, payload=b'{"prompt":"hi"}')
        check("model down -> 503 (no canned answer)", False)
    except Exception as e:  # noqa: BLE001
        check("model down -> 503 ServiceUnavailable (no canned answer)", "503" in str(e) or "ServiceUnavailable" in str(e), e)
    llm._state["endpoint"] = saved

    # aws CLI smoke
    aws = shutil.which("aws")
    if aws:
        env = dict(os.environ, AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="y", AWS_DEFAULT_REGION="us-east-1", AWS_PAGER="")

        def cli(*a):
            return subprocess.run([aws, "--endpoint-url", url, *a], capture_output=True, text=True, env=env, timeout=60)
        r = cli("bedrock-agentcore-control", "get-agent-runtime", "--agent-runtime-id", rid)
        check("aws bedrock-agentcore-control get-agent-runtime", r.returncode == 0 and json.loads(r.stdout)["agentRuntimeId"] == rid, r.stderr[:300] or r.stdout[:200])
        r = cli("bedrock-agentcore-control", "list-agent-runtimes")
        check("aws bedrock-agentcore-control list-agent-runtimes", r.returncode == 0 and len(json.loads(r.stdout)["agentRuntimes"]) == 2, r.stderr[:300])
        out = os.path.join(os.environ.get("TMPDIR", "/tmp"), "vyomi-agentcore-cli.json")
        r = cli("bedrock-agentcore", "invoke-agent-runtime", "--agent-runtime-arn", arn, "--runtime-session-id", "c" * 33, "--cli-binary-format", "raw-in-base64-out",
                "--payload", json.dumps({"prompt": "What is the weather in Paris?"}), out)
        ok = r.returncode == 0 and "21" in open(out).read()
        check("aws bedrock-agentcore invoke-agent-runtime runs the spec agent", ok, r.stderr[:300])
    else:
        print("  note aws CLI absent - skipping CLI smoke")
    ctl.delete_agent_runtime(agentRuntimeId=rid)
    try:
        ctl.get_agent_runtime(agentRuntimeId=rid)
        check("DeleteAgentRuntime removes it", False)
    except ctl.exceptions.ResourceNotFoundException:
        check("DeleteAgentRuntime removes it", True)


if __name__ == "__main__":
    main()
