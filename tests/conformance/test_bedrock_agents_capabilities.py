"""Bedrock Agents capabilities through the REAL boto3 bedrock-agent + bedrock-agent-runtime + lambda + bedrock clients (in-process server):
function-schema and OpenAPI action groups invoked through the Lambda engine, RETURN_CONTROL round trip, schema-validated tool selection with
bounded retries, orchestration trace parts, agent guardrails (input + output), SESSION_SUMMARY memory (GetAgentMemory / DeleteAgentMemory).
The model is a scripted OpenAI-compatible fake (tests/conformance/llm_fakes.py): it proves the orchestration/wire behaviour, not model quality.
Run: PYTHONPATH=. python tests/conformance/test_bedrock_agents_capabilities.py
"""
import io
import json
import os
import socket
import sys
import threading
import time
import zipfile

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
        print(f"  FAIL {name} {str(extra)[:900]}")


STATE = {"bad_calls": 0, "always_bad": False}


def script(body):
    msgs = body["messages"]
    sysm = next((m["content"] for m in msgs if m["role"] == "system"), "")
    last = msgs[-1]
    tools = [t["function"]["name"] for t in body.get("tools") or []]
    rf = body.get("response_format")
    first_user = next((m["content"] for m in msgs if m["role"] == "user"), "")
    u = last["content"] if last["role"] == "user" else ""

    def call(name, args):
        if rf:      # prompt-translated path (json_schema constrained envelope)
            return {"content": json.dumps({"tool_calls": [{"name": name, "arguments": args}]})}
        return {"tool_calls": [{"name": name, "arguments": args}]}
    if u.startswith("Summarise this conversation"):
        return {"content": "The user asked about room B2 and said they prefer building B."}
    if "SAY-BADWORD" in first_user:
        return {"content": "The answer contains the forbidden word."}
    if last["role"] == "tool" or (rf and "Tool result for" in last["content"]):
        return {"content": "RESULT: " + last["content"][:2500]}
    if tools or (rf and "You can call tools" in sysm):
        if "BAD-ARGS" in first_user:
            STATE["bad_calls"] += 1
            if STATE["always_bad"] or STATE["bad_calls"] == 1:
                return call("facilities__get_room_status", {"room": 123, "extra": True})      # wrong type -> rejected by schema validation
        if "work order" in first_user:
            return call("workorders__createWorkOrder", {"description": "leaking tap", "priority": "high"})
        if "approve" in first_user:
            return call("approval__request_approval", {"summary": "replace the pump"})
        if "room" in first_user.lower():
            return call("facilities__get_room_status", {"room": "B2"})
    return {"content": "Hello from the model. system-has-memory=" + str("previous sessions" in sysm)}


def stream_events(resp):
    out = []
    for ev in resp["completion"]:
        out.append(ev)
    return out


def chunks(evs):
    return "".join(e["chunk"]["bytes"].decode() for e in evs if "chunk" in e)


def traces(evs):
    return [e["trace"]["trace"] for e in evs if "trace" in e]


def main():
    import boto3
    import uvicorn
    from botocore.config import Config
    from fastapi import FastAPI, Request
    from core import llm_core as llm
    from core import wire_ingress
    from core.aws_wire_router import AwsWireRouter
    fake = FakeLLM(handler=script, delay=0.0)
    llm.set_backend(None)
    llm._state.update(endpoint=fake.url, no_rf=False, no_native=False)
    llm._state["embed_fn"] = lambda texts: [llm.hash_embed(t) for t in texts]
    os.environ.pop("VYOMI_LLM_DISABLE", None)
    router = AwsWireRouter()
    app = FastAPI()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    kw = dict(region_name="us-east-1", endpoint_url=url, aws_access_key_id="x", aws_secret_access_key="y", config=Config(retries={"max_attempts": 1}))
    ag, rt, lam, br = (boto3.client(n, **kw) for n in ("bedrock-agent", "bedrock-agent-runtime", "lambda", "bedrock"))
    ROLE = "arn:aws:iam::123456789012:role/r"

    def mk(name, code):
        zb = io.BytesIO()
        with zipfile.ZipFile(zb, "w") as z:
            z.writestr("index.py", code)
        return lam.create_function(FunctionName=name, Runtime="python3.12", Role=ROLE, Handler="index.handler", Code={"ZipFile": zb.getvalue()})["FunctionArn"]
    # the Lambda sandbox has no filesystem: each function echoes the event it received as its response body, and the test reads it from the trace
    fn_arn = mk("facilities-actions", """import json
def handler(e, c):
    return {'messageVersion': '1.0', 'response': {'actionGroup': e['actionGroup'], 'function': e['function'],
            'functionResponse': {'responseBody': {'TEXT': {'body': json.dumps(e)}}}},
            'sessionAttributes': {'lastRoom': e['parameters'][0]['value']}}
""")
    api_arn = mk("workorder-api", """import json
def handler(e, c):
    return {'messageVersion': '1.0', 'response': {'actionGroup': e['actionGroup'], 'apiPath': e['apiPath'], 'httpMethod': e['httpMethod'], 'httpStatusCode': 200,
            'responseBody': {'application/json': {'body': json.dumps(e)}}}}
""")

    def lam_events(evs):
        out = []
        for t in traces(evs):
            o = t.get("orchestrationTrace", {}).get("observation", {})
            if o.get("type") == "ACTION_GROUP":
                try:
                    out.append(json.loads(o["actionGroupInvocationOutput"]["text"]))
                except ValueError:
                    pass
        return out

    OPENAPI = {"openapi": "3.0.0", "info": {"title": "wo", "version": "1"}, "paths": {"/work-orders": {"post": {
        "operationId": "createWorkOrder", "description": "Create a maintenance work order", "requestBody": {"required": True, "content": {"application/json": {"schema": {
            "type": "object", "required": ["description"], "properties": {"description": {"type": "string"}, "priority": {"type": "string"}}}}}},
        "responses": {"200": {"description": "ok"}}}}}}
    FN_SCHEMA = {"functions": [{"name": "get_room_status", "description": "Look up the live status of a room", "parameters": {"room": {"type": "string", "description": "room id", "required": True}}}]}

    print("== create agent with Lambda function-schema + OpenAPI + RETURN_CONTROL action groups")
    gr = br.create_guardrail(name="facilities-guardrail", blockedInputMessaging="Input blocked by guardrail.", blockedOutputsMessaging="Output blocked by guardrail.",
                             wordPolicyConfig={"wordsConfig": [{"text": "forbidden"}]},
                             sensitiveInformationPolicyConfig={"piiEntitiesConfig": [{"type": "EMAIL", "action": "ANONYMIZE"}]})
    gv = br.create_guardrail_version(guardrailIdentifier=gr["guardrailId"])["version"]
    try:
        ag.create_agent(agentName="bad-g", foundationModel="amazon.nova-lite-v1:0", agentResourceRoleArn=ROLE, instruction="x" * 50,
                        guardrailConfiguration={"guardrailIdentifier": "nope", "guardrailVersion": "1"})
        check("unknown guardrail -> modeled error", False)
    except ag.exceptions.ResourceNotFoundException:
        check("unknown guardrail -> ResourceNotFoundException", True)
    a = ag.create_agent(agentName="facilities-agent", foundationModel="amazon.nova-lite-v1:0", agentResourceRoleArn=ROLE,
                        instruction="You are the facilities assistant. Use the action groups to look up rooms and raise work orders.",
                        guardrailConfiguration={"guardrailIdentifier": gr["guardrailId"], "guardrailVersion": gv},
                        memoryConfiguration={"enabledMemoryTypes": ["SESSION_SUMMARY"], "storageDays": 30, "sessionSummaryConfiguration": {"maxRecentSessions": 5}})["agent"]
    aid = a["agentId"]
    check("agent echoes guardrail + memory configuration", a["guardrailConfiguration"]["guardrailVersion"] == gv and a["memoryConfiguration"]["storageDays"] == 30, a)
    try:
        ag.create_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupName="x", actionGroupExecutor={"lambda": "not-an-arn"}, functionSchema=FN_SCHEMA)
        check("bad executor ARN -> ValidationException", False)
    except ag.exceptions.ValidationException:
        check("bad executor ARN -> ValidationException", True)
    g1 = ag.create_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupName="facilities", actionGroupExecutor={"lambda": fn_arn}, functionSchema=FN_SCHEMA)["agentActionGroup"]
    ag.create_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupName="workorders", actionGroupExecutor={"lambda": api_arn}, apiSchema={"payload": json.dumps(OPENAPI)})
    ag.create_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupName="approval", actionGroupExecutor={"customControl": "RETURN_CONTROL"},
                                 functionSchema={"functions": [{"name": "request_approval", "description": "Ask the human approver", "parameters": {"summary": {"type": "string", "required": True}}}]})
    check("GetAgentActionGroup", ag.get_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupId=g1["actionGroupId"])["agentActionGroup"]["actionGroupName"] == "facilities")
    upd = ag.update_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupId=g1["actionGroupId"], actionGroupName="facilities",
                                       actionGroupExecutor={"lambda": fn_arn}, functionSchema=FN_SCHEMA, description="rooms")["agentActionGroup"]
    check("UpdateAgentActionGroup", upd["description"] == "rooms")
    ag.prepare_agent(agentId=aid)
    al = ag.create_agent_alias(agentId=aid, agentAliasName="live")["agentAlias"]["agentAliasId"]

    def invoke(sid, text=None, alias=None, **kw2):
        args = dict(agentId=aid, agentAliasId=alias or al, sessionId=sid, **kw2)
        if text is not None:
            args["inputText"] = text
        return rt.invoke_agent(**args)

    print("== Lambda action group (function schema) + trace")
    r = invoke("s-fn", "What is the status of room B2?", enableTrace=True, memoryId="user-1")
    evs = stream_events(r)
    ans = chunks(evs)
    check("model tool call -> Lambda really invoked, result fed back to the model", "RESULT:" in ans and '"get_room_status"' in ans, ans)
    led = lam_events(evs)
    check("Lambda got the Bedrock Agents event (messageVersion/agent/function/parameters/sessionId)",
          led and led[-1]["messageVersion"] == "1.0" and led[-1]["function"] == "get_room_status" and led[-1]["actionGroup"] == "facilities"
          and led[-1]["parameters"] == [{"name": "room", "type": "string", "value": "B2"}] and led[-1]["sessionId"] == "s-fn" and led[-1]["agent"]["id"] == aid, led)
    tp = traces(evs)
    keys = [next(iter(t)) for t in tp]
    check("trace has preProcessing, orchestration and postProcessing parts in order",
          keys.index("preProcessingTrace") < keys.index("orchestrationTrace") < keys.index("postProcessingTrace") and "guardrailTrace" in keys, keys)
    orch = [t["orchestrationTrace"] for t in tp if "orchestrationTrace" in t]
    rat = [o["rationale"] for o in orch if "rationale" in o]
    inv = [o["invocationInput"] for o in orch if "invocationInput" in o]
    obs = [o["observation"] for o in orch if "observation" in o]
    check("trace: modelInvocationInput/Output + rationale", any("modelInvocationInput" in o for o in orch) and any("modelInvocationOutput" in o for o in orch) and rat and rat[0]["text"], orch[:3])
    check("trace: invocationInput ACTION_GROUP (LAMBDA, function, parameters)",
          inv and inv[0]["invocationType"] == "ACTION_GROUP" and inv[0]["actionGroupInvocationInput"]["executionType"] == "LAMBDA"
          and inv[0]["actionGroupInvocationInput"]["function"] == "get_room_status" and inv[0]["actionGroupInvocationInput"]["parameters"][0]["value"] == "B2", inv)
    check("trace: observation ACTION_GROUP output then FINISH final response",
          [o["type"] for o in obs] == ["ACTION_GROUP", "FINISH"] and "get_room_status" in obs[0]["actionGroupInvocationOutput"]["text"] and obs[1]["finalResponse"]["text"] == ans, obs)
    post = [t["postProcessingTrace"] for t in tp if "postProcessingTrace" in t]
    check("trace: postProcessing parsedResponse", any(p_.get("modelInvocationOutput", {}).get("parsedResponse", {}).get("text") == ans for p_ in post), post)
    check("no trace without enableTrace", traces(stream_events(invoke("s-nt", "What is the status of room B2?"))) == [])
    l2 = lam_events(stream_events(invoke("s-fn", "What is the status of room B2 again?", enableTrace=True)))
    check("sessionAttributes returned by the Lambda are passed to the next call", l2 and l2[-1]["sessionAttributes"] == {"lastRoom": "B2"}, l2)

    print("== OpenAPI action group (Lambda executor)")
    evs = stream_events(invoke("s-api", "Please create a work order for the leaking tap", enableTrace=True))
    led = lam_events(evs)[-1]
    check("OpenAPI Lambda event: apiPath, httpMethod, requestBody properties",
          led["apiPath"] == "/work-orders" and led["httpMethod"] == "POST" and led["actionGroup"] == "workorders"
          and {p_["name"]: p_["value"] for p_ in led["requestBody"]["content"]["application/json"]["properties"]} == {"description": "leaking tap", "priority": "high"}, led)
    check("OpenAPI result fed back to the model", '"apiPath": "/work-orders"' in chunks(evs), chunks(evs))

    print("== schema-validated tool selection with bounded retries")
    STATE["bad_calls"] = 0
    STATE["always_bad"] = False
    evs = stream_events(invoke("s-bad1", "BAD-ARGS what is the status of room B2?", enableTrace=True))
    check("invalid arguments are rejected and the model is re-prompted until the call validates", len(lam_events(evs)) == 1 and STATE["bad_calls"] >= 2, (chunks(evs), STATE))
    STATE["always_bad"] = True
    evs = stream_events(invoke("s-bad2", "BAD-ARGS what is the status of room B2?", enableTrace=True))
    ft = [t["failureTrace"] for t in traces(evs) if "failureTrace" in t]
    check("a model that never produces a valid call: Lambda NOT invoked, honest answer + failureTrace", not lam_events(evs) and ft and chunks(evs).startswith("Sorry"), (chunks(evs), ft))
    STATE["always_bad"] = False

    print("== RETURN_CONTROL")
    evs = stream_events(invoke("s-rc", "Please approve the pump replacement", enableTrace=True))
    rc = [e["returnControl"] for e in evs if "returnControl" in e]
    check("returnControl event with functionInvocationInput (no chunk, nothing invoked)", len(rc) == 1 and not chunks(evs), evs)
    fi = rc[0]["invocationInputs"][0]["functionInvocationInput"]
    check("returnControl carries actionGroup, function, parameters", fi["actionGroup"] == "approval" and fi["function"] == "request_approval" and fi["parameters"][0] == {"name": "summary", "type": "string", "value": "replace the pump"}, fi)
    try:
        invoke("s-rc", sessionState={"invocationId": "wrong", "returnControlInvocationResults": [{"functionResult": {"actionGroup": "approval", "function": "request_approval", "responseBody": {"TEXT": {"body": "x"}}}}]})
        check("wrong invocationId -> ValidationException", False)
    except rt.exceptions.ValidationException:
        check("wrong invocationId -> ValidationException", True)
    evs = stream_events(invoke("s-rc", sessionState={"invocationId": rc[0]["invocationId"], "returnControlInvocationResults": [
        {"functionResult": {"actionGroup": "approval", "function": "request_approval", "responseBody": {"TEXT": {"body": "APPROVED by manager"}}}}]}, enableTrace=True))
    check("returnControlInvocationResults fed to the model -> final answer", "APPROVED by manager" in chunks(evs), chunks(evs))
    check("continuation trace has the ACTION_GROUP observation", any(o.get("observation", {}).get("type") == "ACTION_GROUP" for o in (t.get("orchestrationTrace", {}) for t in traces(evs))))

    print("== guardrails on input and output")
    nreq = len(fake.requests)
    evs = stream_events(invoke("s-g1", "this is forbidden content", enableTrace=True))
    gt = [t["guardrailTrace"] for t in traces(evs) if "guardrailTrace" in t]
    check("input guardrail blocks: blockedInputMessaging, model never called, guardrailTrace INTERVENED",
          chunks(evs) == "Input blocked by guardrail." and len(fake.requests) == nreq and gt[0]["action"] == "INTERVENED" and gt[0]["inputAssessments"], (chunks(evs), gt))
    evs = stream_events(invoke("s-g2", "SAY-BADWORD please", enableTrace=True))
    gt = [t["guardrailTrace"] for t in traces(evs) if "guardrailTrace" in t]
    check("output guardrail blocks the model answer -> blockedOutputsMessaging", chunks(evs) == "Output blocked by guardrail." and any(g_.get("outputAssessments") for g_ in gt), (chunks(evs), gt))
    evs = stream_events(invoke("s-g3", "hello, my email is a.b@example.com", enableTrace=True))
    sent = [m["content"] for m in fake.requests[-1]["messages"] if m["role"] == "user"][-1]
    check("PII is anonymised before the model sees it", "a.b@example.com" not in sent and "{EMAIL}" in sent, sent)

    print("== session memory (SESSION_SUMMARY)")
    invoke("s-m1", "hello there", memoryId="user-7")
    invoke("s-m1", "What is the status of room B2?", memoryId="user-7")
    invoke("s-m1", "thanks", memoryId="user-7", endSession=True)
    mem = rt.get_agent_memory(agentId=aid, agentAliasId=al, memoryId="user-7", memoryType="SESSION_SUMMARY")
    ss = mem["memoryContents"][0]["sessionSummary"]
    check("GetAgentMemory returns the session summary", ss["memoryId"] == "user-7" and ss["sessionId"] == "s-m1" and "building B" in ss["summaryText"] and ss["sessionExpiryTime"] > ss["sessionStartTime"], mem)
    ans = chunks(stream_events(invoke("s-m2", "hello again", memoryId="user-7")))
    check("a NEW session with the same memoryId sees the stored summary", "system-has-memory=True" in ans, ans)
    ans = chunks(stream_events(invoke("s-m3", "hello again", memoryId="other-user")))
    check("a different memoryId does not", "system-has-memory=False" in ans, ans)
    try:
        rt.get_agent_memory(agentId=aid, agentAliasId=al, memoryId="user-7", memoryType="BOGUS")
        check("bad memoryType rejected", False)
    except Exception as e:  # noqa: BLE001
        check("bad memoryType rejected", "ValidationException" in type(e).__name__ or "validation" in str(e).lower(), e)
    rt.delete_agent_memory(agentId=aid, agentAliasId=al, memoryId="user-7")
    check("DeleteAgentMemory empties it", rt.get_agent_memory(agentId=aid, agentAliasId=al, memoryId="user-7", memoryType="SESSION_SUMMARY")["memoryContents"] == [])

    print("== action group lifecycle")
    ag.delete_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupId=g1["actionGroupId"])
    try:
        ag.get_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupId=g1["actionGroupId"])
        check("deleted action group -> ResourceNotFoundException", False)
    except ag.exceptions.ResourceNotFoundException:
        check("deleted action group -> ResourceNotFoundException", True)
    check("agent keeps its remaining groups", len(ag.list_agent_action_groups(agentId=aid, agentVersion="DRAFT")["actionGroupSummaries"]) == 2)
    llm.set_backend()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
