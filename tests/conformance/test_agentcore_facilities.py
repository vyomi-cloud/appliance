"""AgentCore reference slice (lane agentcore) through the REAL boto3 clients: Memory (events + extracted long-term records, persisting
across sessions), Policy engine + Gateway (MCP tool catalog, semantic search, Cedar deny of a write tool for a non-manager from JWT
claims) and a Runtime `facilities-supervisor` whose supervisor agent routes to a sub-agent that calls gateway tools.
Run: PYTHONPATH=. python tests/conformance/test_agentcore_facilities.py
"""
import base64
import io
import json
import os
import sys
import threading
import time
import urllib.request
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
        print(f"  FAIL {name} {str(extra)[:700]}")


from jwt_issuer import Issuer  # noqa: E402
ISS = Issuer()


def jwt(sub, groups):
    return ISS.mint(sub, extra={"cognito:groups": groups, "username": sub})


def script(body):
    msgs, sysmsg = body["messages"], next((m["content"] for m in body["messages"] if m["role"] == "system"), "")
    last = msgs[-1]
    first = msgs[0]["content"] if msgs[0]["role"] != "system" else msgs[1]["content"]
    if last["role"] == "user" and last["content"].startswith("Extract"):
        return {"content": json.dumps(["User prefers building B"]) if "building B" in last["content"] else "[]"}
    if last["role"] == "tool":
        return {"content": "RESULT: " + last["content"][:300]}
    if "SUPERVISOR" in sysmsg:
        return {"tool_calls": [{"name": "ask_maintenance", "arguments": {"query": "create a work order for the leaking tap"}}]}
    if "MAINTENANCE" in sysmsg:
        return {"tool_calls": [{"name": "create_work_order", "arguments": {"description": "leaking tap"}}]}
    return {"content": "ok"}


def main():
    import boto3
    import uvicorn
    from botocore.config import Config
    from fastapi import FastAPI, Request
    from core import llm_core as llm
    from core.aws_wire_router import AwsWireRouter
    from core import wire_ingress
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
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    kw = dict(region_name="us-east-1", endpoint_url=url, aws_access_key_id="x", aws_secret_access_key="y", config=Config(retries={"max_attempts": 1}))
    ctl, dp, lam = boto3.client("bedrock-agentcore-control", **kw), boto3.client("bedrock-agentcore", **kw), boto3.client("lambda", **kw)
    ROLE = "arn:aws:iam::123456789012:role/r"

    print("== Memory")
    mem = ctl.create_memory(name="facilities_memory", eventExpiryDuration=30, memoryStrategies=[
        {"userPreferenceMemoryStrategy": {"name": "prefs", "namespaces": ["/users/{actorId}/preferences"]}}])["memory"]
    mid = mem["id"]
    check("CreateMemory -> id/arn/strategies", mem["arn"].endswith("memory/" + mid) and mem["strategies"][0]["type"] == "USER_PREFERENCE", mem)
    time.sleep(0.7)
    g = ctl.get_memory(memoryId=mid)["memory"]
    check("GetMemory reaches ACTIVE", g["status"] == "ACTIVE", g)
    check("ListMemories", [m["id"] for m in ctl.list_memories()["memories"]] == [mid])
    try:
        ctl.create_memory(name="facilities_memory", eventExpiryDuration=30); check("duplicate memory -> ConflictException", False)
    except ctl.exceptions.ConflictException:
        check("duplicate memory -> ConflictException", True)
    ev = dp.create_event(memoryId=mid, actorId="alice", sessionId="s1", eventTimestamp=time.time(),
                         payload=[{"conversational": {"role": "USER", "content": {"text": "I prefer building B for all my requests."}}},
                                  {"conversational": {"role": "ASSISTANT", "content": {"text": "Noted."}}}])["event"]
    check("CreateEvent returns event id", ev["sessionId"] == "s1" and ev["eventId"], ev)
    evs = dp.list_events(memoryId=mid, actorId="alice", sessionId="s1", includePayloads=True)["events"]
    check("ListEvents returns the short-term event with payload", len(evs) == 1 and evs[0]["payload"][0]["conversational"]["role"] == "USER", evs)
    check("ListSessions / ListActors", dp.list_sessions(memoryId=mid, actorId="alice")["sessionSummaries"][0]["sessionId"] == "s1" and dp.list_actors(memoryId=mid)["actorSummaries"][0]["actorId"] == "alice")
    rr = dp.retrieve_memory_records(memoryId=mid, namespace="/users/alice/", searchCriteria={"searchQuery": "which building does the user like", "topK": 3})["memoryRecordSummaries"]
    check("long-term record extracted + retrievable in a NEW session scope", rr and "building B" in rr[0]["content"]["text"] and rr[0]["namespaces"] == ["/users/alice/preferences"], rr)
    check("other user's namespace is empty", dp.retrieve_memory_records(memoryId=mid, namespace="/users/bob/", searchCriteria={"searchQuery": "building"})["memoryRecordSummaries"] == [])
    rid0 = rr[0]["memoryRecordId"]
    check("GetMemoryRecord", dp.get_memory_record(memoryId=mid, memoryRecordId=rid0)["memoryRecord"]["memoryRecordId"] == rid0)

    print("== Lambda tools + policy engine + gateway")
    def mk(name, code):
        zb = io.BytesIO()
        with zipfile.ZipFile(zb, "w") as z:
            z.writestr("index.py", code)
        return lam.create_function(FunctionName=name, Runtime="python3.12", Role=ROLE, Handler="index.handler", Code={"ZipFile": zb.getvalue()})["FunctionArn"]
    kb_arn = mk("kb-search", "def handler(e, c):\n    return {'passages': ['Tap washers are replaced by Maintenance.'], 'q': e.get('query')}\n")
    wo_arn = mk("wo-create", "def handler(e, c):\n    return {'workOrderId': 'WO-1001', 'description': e.get('description')}\n")
    pe = ctl.create_policy_engine(name="facilities_policies")
    check("CreatePolicyEngine", pe["status"] == "ACTIVE" and pe["policyEngineArn"].endswith(pe["policyEngineId"]), pe)
    eid = pe["policyEngineId"]
    ctl.create_policy(policyEngineId=eid, name="read_for_all", definition={"cedar": {"statement": 'permit(principal, action == AgentCore::Action::"kb___search_knowledge", resource);'}})
    pol = ctl.create_policy(policyEngineId=eid, name="write_managers_only", definition={"cedar": {"statement":
        'permit(principal, action == AgentCore::Action::"wo___create_work_order", resource) when { principal.hasTag("cognito:groups") && principal.getTag("cognito:groups") like "*managers*" };'}})
    check("CreatePolicy / ListPolicies", len(ctl.list_policies(policyEngineId=eid)["policies"]) == 2 and pol["status"] == "ACTIVE", pol)
    try:
        ctl.create_policy(policyEngineId=eid, name="bad", definition={"cedar": {"statement": "permit(principal action resource nonsense" * 3}}); check("invalid Cedar -> ValidationException", False)
    except ctl.exceptions.ValidationException:
        check("invalid Cedar -> ValidationException", True)
    gw = ctl.create_gateway(name="facilities-gateway", roleArn=ROLE, authorizerType="CUSTOM_JWT",
                            authorizerConfiguration={"customJWTAuthorizer": {"discoveryUrl": ISS.discovery_url}},
                            protocolConfiguration={"mcp": {"searchType": "SEMANTIC"}}, policyEngineConfiguration={"arn": pe["policyEngineArn"], "mode": "ENFORCE"})
    gid = gw["gatewayId"]
    ts = lambda n, d: {"mcp": {"lambda": {"lambdaArn": kb_arn if n == "search_knowledge" else wo_arn, "toolSchema": {"inlinePayload": [
        {"name": n, "description": d, "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "description": {"type": "string"}}}}]}}}}
    ctl.create_gateway_target(gatewayIdentifier=gid, name="kb", targetConfiguration=ts("search_knowledge", "Search the facilities knowledge base for policies and procedures"))
    ctl.create_gateway_target(gatewayIdentifier=gid, name="wo", targetConfiguration=ts("create_work_order", "Create a maintenance work order"))
    check("GetGateway echoes policy engine config", ctl.get_gateway(gatewayIdentifier=gid)["policyEngineConfiguration"]["mode"] == "ENFORCE")
    time.sleep(1.2)

    def mcp(method, params, token):
        req = urllib.request.Request(f"{url}/gateways/{gid}/mcp", method="POST", data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                     headers={"content-type": "application/json", "authorization": "Bearer " + token,
                                              "x-amz-date": "20261115T000000Z"})
        # the router keys the service from SigV4 scope; send one
        req.add_header("authorization", "AWS4-HMAC-SHA256 Credential=T/20261115/us-east-1/bedrock-agentcore/aws4_request, SignedHeaders=host, Signature=0")
        req.add_header("x-amzn-bedrock-agentcore-runtime-custom-authorization", "Bearer " + token)
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    mgr, staff = jwt("mona", ["managers"]), jwt("sam", ["staff"])
    names = lambda t: [x["name"] for x in mcp("tools/list", {}, t)["result"]["tools"]]  # noqa: E731
    check("manager tools/list = search + kb + wo", names(mgr) == ["x_amz_bedrock_agentcore_search", "kb___search_knowledge", "wo___create_work_order"], names(mgr))
    check("staff tools/list hides the write tool (policy-filtered)", names(staff) == ["x_amz_bedrock_agentcore_search", "kb___search_knowledge"], names(staff))
    hit = mcp("tools/call", {"name": "x_amz_bedrock_agentcore_search", "arguments": {"query": "raise a maintenance work order"}}, mgr)["result"]["structuredContent"]["tools"]
    check("semantic tool search ranks the work-order tool first", hit[0]["name"] == "wo___create_work_order", hit)
    r = mcp("tools/call", {"name": "wo___create_work_order", "arguments": {"description": "x"}}, staff)
    check("staff create_work_order DENIED by Cedar", "error" in r and "policy" in r["error"]["message"], r)
    r = mcp("tools/call", {"name": "wo___create_work_order", "arguments": {"description": "x"}}, mgr)
    check("manager create_work_order ALLOWED and runs the Lambda", "WO-1001" in r["result"]["content"][0]["text"], r)
    r = mcp("tools/call", {"name": "kb___search_knowledge", "arguments": {"query": "tap"}}, staff)
    check("staff read tool allowed", "Tap washers" in r["result"]["content"][0]["text"], r)

    print("== Runtime facilities-supervisor (supervisor -> sub-agent -> gateway tool, with memory)")
    maint = {"instructions": "You are the MAINTENANCE agent.", "tools": [{"name": "create_work_order", "type": "gateway", "gateway": "facilities-gateway", "tool": "wo___create_work_order",
                                                                         "description": "Create a work order", "parameters": {"type": "object", "properties": {"description": {"type": "string"}}}}]}
    sup = {"instructions": "You are the facilities SUPERVISOR. Route requests to sub-agents.", "memory": {"memory": "facilities_memory", "namespace": "/users/{actorId}/"},
           "tools": [{"name": "ask_maintenance", "type": "agent", "spec": maint, "description": "Maintenance sub-agent",
                      "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}]}
    art = {"containerConfiguration": {"containerUri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/facilities:latest"}}
    rt = ctl.create_agent_runtime(agentRuntimeName="facilities_supervisor", agentRuntimeArtifact=art, roleArn=ROLE, networkConfiguration={"networkMode": "PUBLIC"},
                                  environmentVariables={"VYOMI_AGENT_SPEC": json.dumps(sup)})
    time.sleep(1.2)

    def invoke(sid, prompt, token):
        h = lambda params, **k: params["headers"].__setitem__("X-Amzn-Bedrock-AgentCore-Runtime-Custom-Authorization", "Bearer " + token)  # noqa: E731
        dp.meta.events.register("before-call.bedrock-agentcore.InvokeAgentRuntime", h)
        try:
            out = dp.invoke_agent_runtime(agentRuntimeArn=rt["agentRuntimeArn"], runtimeSessionId=sid, payload=json.dumps({"prompt": prompt}).encode())
            return json.loads(out["response"].read())
        finally:
            dp.meta.events.unregister("before-call.bedrock-agentcore.InvokeAgentRuntime", h)
    o = invoke("m" * 33, "Please raise a work order for the leaking tap", mgr)
    check("manager: supervisor routes to sub-agent which creates WO-1001 via the gateway", "WO-1001" in o["response"] and o["toolCalls"][0]["name"] == "ask_maintenance", o)
    o = invoke("n" * 33, "Please raise a work order for the leaking tap", staff)
    check("staff: same flow, gateway DENIES the write tool (policy text surfaces)", "WO-1001" not in o["response"] and "policy" in o["response"].lower(), o)
    n0 = len(fake.requests)
    invoke("p" * 33, "Where should my request go?", jwt("alice", ["managers"]))   # alice has a stored preference from the Memory section? (actor=sub)
    sup_calls = [r for r in fake.requests[n0:] if "SUPERVISOR" in json.dumps(r["messages"][0])]
    check("memory: stored preference injected into a brand-new session for the same user", any("building B" in json.dumps(r["messages"]) for r in sup_calls), sup_calls[:1])
    n1 = len(fake.requests)
    invoke("q" * 33, "Where should my request go?", jwt("carol", ["staff"]))
    check("memory: another user does not receive alice's preference", not any("building B" in json.dumps(r["messages"]) for r in fake.requests[n1:] if "SUPERVISOR" in json.dumps(r["messages"][0])))
    check("runtime wrote events into facilities_memory for that session", len(dp.list_events(memoryId=mid, actorId="alice", sessionId="p" * 33)["events"]) == 1)
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
