"""Bedrock Agents Round-8 limits through the REAL boto3 clients (in-process server): multi-agent collaboration (SUPERVISOR / SUPERVISOR_ROUTER),
AMAZON.UserInput, AMAZON.CodeInterpreter (real sandbox), requireConfirmation, custom prompts + parser Lambdas, apiSchema from S3, session
summaries on idle expiry, InvokeInlineAgent, and the Azure Assistants code_interpreter / file_search tools.
The model is a scripted OpenAI-compatible fake: it proves orchestration and wire behaviour, not model quality.
Run: PYTHONPATH=. python tests/conformance/test_bedrock_agents_limits.py
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


SEEN = {"temps": [], "systems": []}


def script(body):
    msgs = body["messages"]
    sysm = next((m["content"] for m in msgs if m["role"] == "system"), "")
    last = msgs[-1]
    tools = [t["function"]["name"] for t in body.get("tools") or []]
    rf = body.get("response_format")
    first_user = next((m["content"] for m in msgs if m["role"] == "user"), "")
    u = last["content"] if last["role"] == "user" else ""
    SEEN["temps"].append(body.get("temperature"))
    SEEN["systems"].append(sysm)

    def call(name, args):
        if rf:
            return {"content": json.dumps({"tool_calls": [{"name": name, "arguments": args}]})}
        return {"tool_calls": [{"name": name, "arguments": args}]}
    if u.startswith("KBRG-TEMPLATE"):
        return {"content": "KBRG-GENERATED: the lobby wifi password is Aurora-2026"}
    if u.startswith("Summarise this conversation"):
        return {"content": "SUMMARY: the user asked about the pump and is waiting for B2."}
    if "<category>" in u or "CLASSIFY-INPUT" in u:
        return {"content": "<category>A</category>" if "evil" in u else "<category>E</category>"}
    if last["role"] == "tool" or (rf and "Tool result for" in last["content"]):
        return {"content": "RESULT: " + last["content"][:2500]}
    if sysm.startswith("You route requests"):
        if "invoice" in first_user.lower():
            return call("agentcollaborator__billing", {"input": first_user})
        if "facility-q" in first_user:
            return call("agentcollaborator__facilities", {"input": first_user})
        return {"content": "SUPERVISOR"}
    if "code_interpreter" in tools and "azure-ci" in first_user:
        return call("code_interpreter", {"input": "print(6*7)\nopen('result.txt','w').write('42')"})
    if "file excerpts" in sysm:
        return {"content": "According to the file: " + sysm.split("\n[0]", 1)[-1][:160]}
    if tools or (rf and "You can call tools" in sysm):
        if "AMAZON_CodeInterpreter__execute" in tools or "AMAZON_CodeInterpreter__execute" in sysm:
            if "compute" in first_user:
                return call("AMAZON_CodeInterpreter__execute", {"code": "print(sum(range(10)))\nopen('out.csv','w').write('a,b\\n1,2')"})
            if "readfile" in first_user:
                return call("AMAZON_CodeInterpreter__execute", {"code": "print(open('data.csv').read().upper())"})
            if "breakit" in first_user:
                return call("AMAZON_CodeInterpreter__execute", {"code": "import os\nos.system('echo hi')"})
        if "AMAZON_UserInput__askuser" in tools or "AMAZON_UserInput__askuser" in sysm:
            if "book" in first_user and not any(m["role"] == "assistant" for m in msgs):
                return call("AMAZON_UserInput__askuser", {"question": "Which room should I book?"})
        if "work order" in first_user and "ops__createWorkOrder" in str(tools + [sysm]):
            return call("ops__createWorkOrder", {"description": "leaking tap"})
        if "schema-s3" in first_user:
            return call("s3api__getRoom", {"room": "B2"})
        if "delegate" in first_user and "agentcollaborator__billing" in tools:
            return call("agentcollaborator__billing", {"input": "invoice 42 status"})
    if "BILLING-AGENT" in sysm:
        return {"content": "BILLING-ANSWER: invoice 42 is paid"}
    if "FACILITIES-AGENT" in sysm:
        return {"content": "FACILITIES-ANSWER: room B2 is free"}
    return {"content": "plain answer. system-has-custom=" + str("CUSTOM-TEMPLATE" in sysm)}


def events(resp):
    return list(resp["completion"])


def chunks(evs):
    return "".join(e["chunk"]["bytes"].decode() for e in evs if "chunk" in e)


def traces(evs):
    return [e["trace"] for e in evs if "trace" in e]


def main():
    import boto3
    import uvicorn
    from botocore.config import Config
    from fastapi import FastAPI, Request
    from core import llm_core as llm
    from core import wire_ingress, bedrock_agents_core as bac
    from core.aws_wire_router import AwsWireRouter
    fake = FakeLLM(handler=script, delay=0.0)
    llm.set_backend(None)
    llm._state.update(endpoint=fake.url, no_rf=False, no_native=False)
    llm._state["embed_fn"] = lambda texts: [llm.hash_embed(t) for t in texts]
    os.environ.pop("VYOMI_LLM_DISABLE", None)
    router = AwsWireRouter()
    from core.azure_arm_core import AzureArm
    router.az_arm = AzureArm()
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
    ag, rt, lam, s3 = (boto3.client(n, **kw) for n in ("bedrock-agent", "bedrock-agent-runtime", "lambda", "s3"))
    ROLE = "arn:aws:iam::123456789012:role/r"
    FM = "amazon.nova-lite-v1:0"
    ACCT_ALIAS = "arn:aws:bedrock:us-east-1:123456789012:agent-alias/{}/{}"

    def mk(name, code):
        zb = io.BytesIO()
        with zipfile.ZipFile(zb, "w") as z:
            z.writestr("index.py", code)
        return lam.create_function(FunctionName=name, Runtime="python3.12", Role=ROLE, Handler="index.handler", Code={"ZipFile": zb.getvalue()})["FunctionArn"]
    fn_arn = mk("ops-fn", """import json
def handler(e, c):
    return {'messageVersion': '1.0', 'response': {'actionGroup': e['actionGroup'], 'function': e['function'],
            'functionResponse': {'responseBody': {'TEXT': {'body': 'WORK-ORDER-CREATED ' + json.dumps(e['parameters'])}}}}}
""")
    api_arn = mk("room-api", """import json
def handler(e, c):
    return {'messageVersion': '1.0', 'response': {'actionGroup': e['actionGroup'], 'apiPath': e['apiPath'], 'httpMethod': e['httpMethod'], 'httpStatusCode': 200,
            'responseBody': {'application/json': {'body': 'ROOM-API ' + e['apiPath'] + json.dumps(e['parameters'])}}}}
""")
    parser_arn = mk("parser-fn", """def handler(e, c):
    t, raw = e['promptType'], e['invokeModelRawResponse']
    base = {'messageVersion': '1.0', 'promptType': t}
    if t == 'PRE_PROCESSING':
        base['preProcessingParsedResponse'] = {'isValid': 'category>A' not in raw, 'rationale': 'parser saw ' + raw[:30]}
    elif t == 'ORCHESTRATION':
        base['orchestrationParsedResponse'] = {'rationale': 'custom parser', 'responseDetails': {'invocationType': 'FINISH', 'agentFinalResponse': {'responseText': 'PARSED<' + raw + '>'}}}
    elif t == 'POST_PROCESSING':
        base['postProcessingParsedResponse'] = {'responseText': 'POST<' + raw + '>'}
    return base
""")

    def new_agent(name, instr, **extra):
        a = ag.create_agent(agentName=name, foundationModel=FM, agentResourceRoleArn=ROLE, instruction=instr + " " * (40 - len(instr)) if len(instr) < 40 else instr, **extra)["agent"]
        return a["agentId"]

    def prep(aid, alias="live"):
        ag.prepare_agent(agentId=aid)
        return ag.create_agent_alias(agentId=aid, agentAliasName=alias)["agentAlias"]["agentAliasId"]

    def invoke(aid, al, sid, text=None, **k):
        a = dict(agentId=aid, agentAliasId=al, sessionId=sid, **k)
        if text is not None:
            a["inputText"] = text
        return events(rt.invoke_agent(**a))

    # ───────────────────────── code interpreter
    print("== AMAZON.CodeInterpreter")
    aid = new_agent("ci-agent", "You analyse data by writing and running python code in the sandbox.")
    try:
        ag.create_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupName="ci", parentActionGroupSignature="AMAZON.Bogus")
        check("unknown parentActionGroupSignature -> ValidationException", False)
    except ag.exceptions.ValidationException:
        check("unknown parentActionGroupSignature -> ValidationException", True)
    ag.create_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupName="CodeInterpreterAction", parentActionGroupSignature="AMAZON.CodeInterpreter", actionGroupState="ENABLED")
    al = prep(aid)
    evs = invoke(aid, al, "s-ci", "please compute the sum", enableTrace=True)
    obs = [t["trace"]["orchestrationTrace"]["observation"] for t in traces(evs) if "observation" in t["trace"].get("orchestrationTrace", {})]
    ci = [o["codeInterpreterInvocationOutput"] for o in obs if "codeInterpreterInvocationOutput" in o]
    check("code really executed: stdout 45 in codeInterpreterInvocationOutput", ci and ci[0]["executionOutput"].strip() == "45", obs)
    check("answer carries the real stdout", "45" in chunks(evs), chunks(evs))
    fl = [e["files"] for e in evs if "files" in e]
    check("files written by the code are returned as a files event", fl and fl[0]["files"][0]["name"] == "out.csv" and fl[0]["files"][0]["bytes"] == b"a,b\n1,2", fl)
    inv = [t["trace"]["orchestrationTrace"]["invocationInput"] for t in traces(evs) if "invocationInput" in t["trace"].get("orchestrationTrace", {})]
    check("trace has the code in codeInterpreterInvocationInput", any("codeInterpreterInvocationInput" in i and "sum(range(10))" in i["codeInterpreterInvocationInput"]["code"] for i in inv), inv)
    evs = invoke(aid, al, "s-ci2", "please readfile", enableTrace=True, sessionState={"files": [{"name": "data.csv", "source": {"sourceType": "BYTE_CONTENT", "byteContent": {"mediaType": "text/csv", "data": b"x,y\n3,4"}}, "useCase": "CODE_INTERPRETER"}]})
    check("input file via sessionState.files is readable by the code", "X,Y" in chunks(evs), chunks(evs))
    try:
        invoke(aid, al, "s-ci3", "readfile", sessionState={"files": [{"name": "p.png", "source": {"sourceType": "BYTE_CONTENT", "byteContent": {"mediaType": "image/png", "data": b"1"}}, "useCase": "CHAT"}]})
        check("CHAT-use files rejected", False)
    except Exception as e:  # noqa: BLE001
        check("useCase CHAT attachments rejected with a modeled error", "ValidationException" in str(e), e)
    evs = invoke(aid, al, "s-ci4", "please breakit", enableTrace=True)
    obs = [t["trace"]["orchestrationTrace"]["observation"] for t in traces(evs) if "observation" in t["trace"].get("orchestrationTrace", {})]
    ci = [o["codeInterpreterInvocationOutput"] for o in obs if "codeInterpreterInvocationOutput" in o]
    check("dangerous code (os.system) is blocked and reported as executionError", ci and "blocked" in ci[0].get("executionError", ""), ci)

    # ───────────────────────── user input
    print("== AMAZON.UserInput")
    aid = new_agent("ui-agent", "You book rooms; ask the user for anything that is missing.")
    ag.create_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupName="UserInputAction", parentActionGroupSignature="AMAZON.UserInput", actionGroupState="ENABLED")
    al = prep(aid)
    evs = invoke(aid, al, "s-ui", "please book a room", enableTrace=True)
    check("agent asks the user back: the question is the reply", chunks(evs) == "Which room should I book?", chunks(evs))
    kinds = [t["trace"]["orchestrationTrace"].get("observation", {}).get("type") for t in traces(evs) if "orchestrationTrace" in t["trace"]]
    check("trace observation type ASK_USER", "ASK_USER" in kinds, kinds)
    evs = invoke(aid, al, "s-ui", "room B2")
    check("the user's reply continues the same session (history kept)", "plain answer" in chunks(evs), chunks(evs))

    # ───────────────────────── requireConfirmation
    print("== requireConfirmation")
    aid = new_agent("rc-agent", "You raise work orders after the user confirms them.")
    ag.create_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupName="ops", actionGroupExecutor={"lambda": fn_arn}, functionSchema={"functions": [
        {"name": "createWorkOrder", "description": "create a work order", "parameters": {"description": {"type": "string", "required": True}}, "requireConfirmation": "ENABLED"}]})
    try:
        ag.create_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupName="bad", actionGroupExecutor={"lambda": fn_arn}, functionSchema={"functions": [
            {"name": "f", "description": "d", "parameters": {}, "requireConfirmation": "MAYBE"}]})
        check("bad requireConfirmation rejected", False)
    except Exception as e:  # noqa: BLE001
        check("bad requireConfirmation -> ValidationException", "ValidationException" in str(e) or "Validation" in str(e), e)
    al = prep(aid)
    evs = invoke(aid, al, "s-cf", "raise a work order please", enableTrace=True)
    rcs = [e["returnControl"] for e in evs if "returnControl" in e]
    fi = rcs[0]["invocationInputs"][0]["functionInvocationInput"] if rcs else {}
    check("returnControl with actionInvocationType CONFIRM, Lambda NOT yet invoked", fi.get("actionInvocationType") == "CONFIRM" and fi.get("function") == "createWorkOrder" and not chunks(evs), rcs)
    evs = invoke(aid, al, "s-cf", sessionState={"invocationId": rcs[0]["invocationId"], "returnControlInvocationResults": [
        {"functionResult": {"actionGroup": "ops", "function": "createWorkOrder", "confirmationState": "CONFIRM"}}]}, enableTrace=True)
    check("CONFIRM -> the Lambda runs and its result reaches the model", "WORK-ORDER-CREATED" in chunks(evs), chunks(evs))
    evs = invoke(aid, al, "s-cf2", "raise a work order please")
    rc2 = [e["returnControl"] for e in evs if "returnControl" in e][0]
    evs = invoke(aid, al, "s-cf2", sessionState={"invocationId": rc2["invocationId"], "returnControlInvocationResults": [
        {"functionResult": {"actionGroup": "ops", "function": "createWorkOrder", "confirmationState": "DENY"}}]})
    check("DENY -> the Lambda is never invoked, the model is told it was denied", "WORK-ORDER-CREATED" not in chunks(evs) and "DENIED" in chunks(evs), chunks(evs))
    evs = invoke(aid, al, "s-cf3", "raise a work order please")
    rc3 = [e["returnControl"] for e in evs if "returnControl" in e][0]
    try:
        invoke(aid, al, "s-cf3", sessionState={"invocationId": rc3["invocationId"], "returnControlInvocationResults": [
            {"functionResult": {"actionGroup": "ops", "function": "createWorkOrder", "responseBody": {"TEXT": {"body": "x"}}}}]})
        check("missing confirmationState rejected", False)
    except Exception as e:  # noqa: BLE001
        check("missing confirmationState -> ValidationException", "ValidationException" in str(e), e)

    # ───────────────────────── apiSchema from S3
    print("== apiSchema from S3")
    OPENAPI = {"openapi": "3.0.0", "info": {"title": "r", "version": "1"}, "paths": {"/rooms/{room}": {"get": {"operationId": "getRoom", "description": "room status",
              "parameters": [{"name": "room", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "ok"}}}}}}
    s3.create_bucket(Bucket="schemas")
    s3.put_object(Bucket="schemas", Key="rooms.json", Body=json.dumps(OPENAPI).encode())
    aid = new_agent("s3schema-agent", "You look up rooms with the room API described by an S3 schema.")
    try:
        ag.create_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupName="s3api", actionGroupExecutor={"lambda": api_arn}, apiSchema={"s3": {"s3BucketName": "schemas", "s3ObjectKey": "missing.json"}})
        check("missing S3 schema object -> ValidationException", False)
    except ag.exceptions.ValidationException:
        check("missing S3 schema object -> ValidationException", True)
    ag.create_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupName="s3api", actionGroupExecutor={"lambda": api_arn}, apiSchema={"s3": {"s3BucketName": "schemas", "s3ObjectKey": "rooms.json"}})
    al = prep(aid)
    evs = invoke(aid, al, "s-s3", "schema-s3 room status")
    check("tools derived from the S3 OpenAPI schema and the Lambda really called", "ROOM-API /rooms/{room}" in chunks(evs), chunks(evs))

    # ───────────────────────── custom prompts / parser lambdas
    print("== custom prompts + parser Lambdas")
    try:
        new_agent("bad-parser", "You are an agent with a bad prompt override.", promptOverrideConfiguration={"promptConfigurations": [
            {"promptType": "ORCHESTRATION", "promptCreationMode": "OVERRIDDEN", "basePromptTemplate": "x", "parserMode": "OVERRIDDEN"}]})
        check("parserMode OVERRIDDEN without overrideLambda rejected", False)
    except ag.exceptions.ValidationException:
        check("parserMode OVERRIDDEN without overrideLambda -> ValidationException", True)
    aid = new_agent("tpl-agent", "You are the templated agent for the facilities team.", promptOverrideConfiguration={"promptConfigurations": [
        {"promptType": "ORCHESTRATION", "promptCreationMode": "OVERRIDDEN", "promptState": "ENABLED", "basePromptTemplate": "CUSTOM-TEMPLATE >> $instruction$ << end", "parserMode": "DEFAULT",
         "inferenceConfiguration": {"temperature": 0.11, "topP": 0.9, "topK": 50, "maximumLength": 321, "stopSequences": ["STOPME"]}}]})
    al = prep(aid)
    SEEN["systems"].clear(); SEEN["temps"].clear()
    evs = invoke(aid, al, "s-tpl", "hello there")
    check("ORCHESTRATION template rendered with $instruction$ and used as the system prompt", any("CUSTOM-TEMPLATE >> You are the templated agent" in x for x in SEEN["systems"]) and "system-has-custom=True" in chunks(evs), SEEN["systems"][-1:])
    check("inferenceConfiguration temperature applied", 0.11 in SEEN["temps"], SEEN["temps"])
    aid = new_agent("parser-agent", "You are the parser-lambda agent for the facilities team.", promptOverrideConfiguration={"overrideLambda": parser_arn, "promptConfigurations": [
        {"promptType": "PRE_PROCESSING", "promptCreationMode": "OVERRIDDEN", "promptState": "ENABLED", "basePromptTemplate": "CLASSIFY-INPUT $question$ <category>", "parserMode": "OVERRIDDEN"},
        {"promptType": "ORCHESTRATION", "promptCreationMode": "OVERRIDDEN", "promptState": "ENABLED", "basePromptTemplate": "$instruction$", "parserMode": "OVERRIDDEN"},
        {"promptType": "POST_PROCESSING", "promptCreationMode": "OVERRIDDEN", "promptState": "ENABLED", "basePromptTemplate": "Rewrite: $latest_response$", "parserMode": "OVERRIDDEN"}]})
    al = prep(aid)
    evs = invoke(aid, al, "s-pa", "hello friendly", enableTrace=True)
    check("parser Lambdas shape the answer (POST_PROCESSING parser wraps the rewrite)", chunks(evs).startswith("POST<"), chunks(evs))
    orr = [t["trace"]["orchestrationTrace"] for t in traces(evs) if "orchestrationTrace" in t["trace"]]
    check("ORCHESTRATION parser Lambda decided FINISH (rationale from the Lambda)", any(o.get("rationale", {}).get("text") == "custom parser" for o in orr), orr)
    evs = invoke(aid, al, "s-pb", "do something evil", enableTrace=True)
    check("PRE_PROCESSING parser marks the input invalid -> refused without orchestration", chunks(evs) == "Sorry, I am unable to assist you with this request.", chunks(evs))

    # ───────────────────────── KNOWLEDGE_BASE_RESPONSE_GENERATION prompt applied
    print("== KNOWLEDGE_BASE_RESPONSE_GENERATION")
    s3.create_bucket(Bucket="kbrg")
    s3.put_object(Bucket="kbrg", Key="d/wifi.txt", Body=b"The guest wifi password for the lobby is Aurora-2026. Contact facilities to rotate it.")
    emb = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
    kb = ag.create_knowledge_base(name="kbrg-kb", roleArn=ROLE, knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {"embeddingModelArn": emb}},
                                  storageConfiguration={"type": "OPENSEARCH_SERVERLESS"})["knowledgeBase"]["knowledgeBaseId"]
    dsid = ag.create_data_source(knowledgeBaseId=kb, name="d", dataSourceConfiguration={"type": "S3", "s3Configuration": {"bucketArn": "arn:aws:s3:::kbrg", "inclusionPrefixes": ["d/"]}})["dataSource"]["dataSourceId"]
    ag.start_ingestion_job(knowledgeBaseId=kb, dataSourceId=dsid)
    kbp_arn = mk("kbparser-fn", """def handler(e, c):
    return {'messageVersion': '1.0', 'promptType': e['promptType'], 'knowledgeBaseResponseGenerationParsedResponse': {'generatedResponse': {'generatedResponseParts': [{'text': 'PARSED<' + e['invokeModelRawResponse'] + '>'}]}}}
""")

    def kb_agent(name, cfgs, **extra):
        a = new_agent(name, "You answer facilities questions from the knowledge base.", promptOverrideConfiguration={"promptConfigurations": cfgs, **extra})
        ag.associate_agent_knowledge_base(agentId=a, agentVersion="DRAFT", knowledgeBaseId=kb, description="facilities docs", knowledgeBaseState="ENABLED")
        return a, prep(a)
    n0 = len(SEEN["systems"])
    a1, al1 = kb_agent("kbrg-agent", [{"promptType": "KNOWLEDGE_BASE_RESPONSE_GENERATION", "promptCreationMode": "OVERRIDDEN", "promptState": "ENABLED",
                                       "basePromptTemplate": "KBRG-TEMPLATE q=$query$ results=$search_results$", "parserMode": "DEFAULT",
                                       "inferenceConfiguration": {"temperature": 0.11, "maximumLength": 120}}])
    evs = invoke(a1, al1, "s-kbrg", "what is the lobby wifi password?", enableTrace=True)
    ot = [t["trace"]["orchestrationTrace"] for t in traces(evs) if "orchestrationTrace" in t["trace"]]
    mi = [o["modelInvocationInput"] for o in ot if o.get("modelInvocationInput", {}).get("type") == "KNOWLEDGE_BASE_RESPONSE_GENERATION"]
    mo = [o["modelInvocationOutput"] for o in ot if "modelInvocationOutput" in o and mi and o["modelInvocationOutput"].get("traceId") == mi[0]["traceId"]]
    check("the agent's own KB response-generation template is rendered ($query$, $search_results$) and run on the model", mi and mi[0]["text"].startswith("KBRG-TEMPLATE q=what is the lobby wifi")
          and "<search_result>" in mi[0]["text"] and "Aurora-2026" in mi[0]["text"], mi)
    check("  modelInvocationInput carries the prompt's inferenceConfiguration; the output trace has the raw generated text + usage",
          mi[0]["inferenceConfiguration"]["temperature"] == 0.11 and mo and mo[0]["rawResponse"]["content"].startswith("KBRG-GENERATED") and mo[0]["metadata"]["usage"]["outputTokens"] > 0, (mi, mo))
    check("  the generated answer (not the raw passages) is what orchestration receives", any("Answer generated from the knowledge base" in x and "KBRG-GENERATED" in x for x in SEEN["systems"][n0:]), SEEN["systems"][n0:][-1:])
    check("  the model call used the prompt's inference temperature", 0.11 in SEEN["temps"][-4:], SEEN["temps"][-4:])
    a2, al2 = kb_agent("kbrg-parser", [{"promptType": "KNOWLEDGE_BASE_RESPONSE_GENERATION", "promptCreationMode": "OVERRIDDEN", "promptState": "ENABLED",
                                        "basePromptTemplate": "KBRG-TEMPLATE $query$", "parserMode": "OVERRIDDEN"}], overrideLambda=kbp_arn)
    n1 = len(SEEN["systems"])
    evs = invoke(a2, al2, "s-kbrg2", "what is the lobby wifi password?", enableTrace=True)
    check("the parser Lambda (KB_RESPONSE_GENERATION) rewrites the generated text (generatedResponseParts)", any("PARSED<KBRG-GENERATED" in x for x in SEEN["systems"][n1:]), SEEN["systems"][n1:][-1:])
    a3, al3 = kb_agent("kbrg-off", [{"promptType": "KNOWLEDGE_BASE_RESPONSE_GENERATION", "promptCreationMode": "OVERRIDDEN", "promptState": "DISABLED", "basePromptTemplate": "KBRG-TEMPLATE $query$", "parserMode": "DEFAULT"}])
    n2 = len(SEEN["systems"])
    evs = invoke(a3, al3, "s-kbrg3", "what is the lobby wifi password?", enableTrace=True)
    check("promptState DISABLED: no extra model call; the retrieved passages go to orchestration verbatim", not any("KBRG-GENERATED" in x for x in SEEN["systems"][n2:]) and any("Aurora-2026" in x for x in SEEN["systems"][n2:]), SEEN["systems"][n2:][-1:])
    a4 = new_agent("kbrg-default", "You answer facilities questions from the knowledge base.")
    ag.associate_agent_knowledge_base(agentId=a4, agentVersion="DRAFT", knowledgeBaseId=kb, description="facilities docs", knowledgeBaseState="ENABLED")
    al4 = prep(a4)
    n3 = len(SEEN["systems"])
    invoke(a4, al4, "s-kbrg4", "what is the lobby wifi password?")
    check("no override configured: behaviour unchanged (passages in the system prompt, no generation step)", any("Aurora-2026" in x and "KBRG-GENERATED" not in x for x in SEEN["systems"][n3:]), SEEN["systems"][n3:][-1:])

    # ───────────────────────── idle-timeout session summary
    print("== session summary on idle timeout")
    aid = new_agent("idle-agent", "You remember users across sessions for the facilities team.", idleSessionTTLInSeconds=60,
                    memoryConfiguration={"enabledMemoryTypes": ["SESSION_SUMMARY"], "storageDays": 30})
    al = prep(aid)
    invoke(aid, al, "s-idle", "hello I am waiting for B2", memoryId="u-idle")
    mem = rt.get_agent_memory(agentId=aid, agentAliasId=al, memoryId="u-idle", memoryType="SESSION_SUMMARY")["memoryContents"]
    check("no summary while the session is still active", mem == [], mem)
    st = bac._state(router.s3)
    st["agents"][aid]["sessions"]["s-idle"]["last"] -= 3600
    mem = rt.get_agent_memory(agentId=aid, agentAliasId=al, memoryId="u-idle", memoryType="SESSION_SUMMARY")["memoryContents"]
    check("after the idle TTL the session is summarised into memory", mem and "SUMMARY:" in mem[0]["sessionSummary"]["summaryText"], mem)
    check("the expired session is gone", "s-idle" not in st["agents"][aid]["sessions"])

    # ───────────────────────── multi-agent collaboration
    print("== multi-agent collaboration")
    bill = new_agent("billing-agent", "BILLING-AGENT: you answer questions about invoices.")
    bill_al = prep(bill)
    fac = new_agent("facilities-agent2", "FACILITIES-AGENT: you answer questions about rooms.")
    fac_al = prep(fac)
    sup = new_agent("supervisor-agent", "You are the supervisor of the billing and facilities agents.", agentCollaboration="SUPERVISOR")
    check("agentCollaboration echoed", ag.get_agent(agentId=sup)["agent"]["agentCollaboration"] == "SUPERVISOR")
    off = new_agent("plain-agent3", "You are a plain agent without collaboration enabled.")
    try:
        ag.associate_agent_collaborator(agentId=off, agentVersion="DRAFT", agentDescriptor={"aliasArn": ACCT_ALIAS.format(bill, bill_al)}, collaboratorName="billing", collaborationInstruction="invoices")
        check("associate on a non-supervisor -> ValidationException", False)
    except ag.exceptions.ValidationException:
        check("associate on an agent with collaboration DISABLED -> ValidationException", True)
    try:
        ag.associate_agent_collaborator(agentId=sup, agentVersion="DRAFT", agentDescriptor={"aliasArn": ACCT_ALIAS.format(sup, "TSTALIASID")}, collaboratorName="self", collaborationInstruction="no")
        check("self collaboration rejected", False)
    except ag.exceptions.ValidationException:
        check("an agent cannot collaborate with itself -> ValidationException", True)
    c1 = ag.associate_agent_collaborator(agentId=sup, agentVersion="DRAFT", agentDescriptor={"aliasArn": ACCT_ALIAS.format(bill, bill_al)}, collaboratorName="billing",
                                         collaborationInstruction="Answers questions about invoices and payments.", relayConversationHistory="TO_COLLABORATOR")["agentCollaborator"]
    ag.associate_agent_collaborator(agentId=sup, agentVersion="DRAFT", agentDescriptor={"aliasArn": ACCT_ALIAS.format(fac, fac_al)}, collaboratorName="facilities",
                                    collaborationInstruction="Answers questions about rooms and buildings.")
    check("AssociateAgentCollaborator echoes the record", c1["collaboratorName"] == "billing" and c1["relayConversationHistory"] == "TO_COLLABORATOR" and c1["collaboratorId"], c1)
    check("ListAgentCollaborators", len(ag.list_agent_collaborators(agentId=sup, agentVersion="DRAFT")["agentCollaboratorSummaries"]) == 2)
    check("GetAgentCollaborator", ag.get_agent_collaborator(agentId=sup, agentVersion="DRAFT", collaboratorId=c1["collaboratorId"])["agentCollaborator"]["collaboratorName"] == "billing")
    up = ag.update_agent_collaborator(agentId=sup, agentVersion="DRAFT", collaboratorId=c1["collaboratorId"], agentDescriptor={"aliasArn": ACCT_ALIAS.format(bill, bill_al)},
                                      collaboratorName="billing", collaborationInstruction="Invoices, payments and refunds.")["agentCollaborator"]
    check("UpdateAgentCollaborator", up["collaborationInstruction"] == "Invoices, payments and refunds.")
    sup_al = prep(sup)
    evs = invoke(sup, sup_al, "s-sup", "please delegate the invoice question", enableTrace=True)
    check("supervisor delegates to the collaborator agent and uses its answer", "BILLING-ANSWER" in chunks(evs), chunks(evs))
    tc = traces(evs)
    collab_tr = [t for t in tc if t.get("collaboratorName") == "billing"]
    check("collaborator traces are relayed with collaboratorName and callerChain", collab_tr and len(collab_tr[0]["callerChain"]) == 2, [t.get("collaboratorName") for t in tc])
    obs = [t["trace"]["orchestrationTrace"]["observation"] for t in tc if "observation" in t["trace"].get("orchestrationTrace", {}) and not t.get("collaboratorName")]
    check("supervisor observation type AGENT_COLLABORATOR with the collaborator output", any(o.get("type") == "AGENT_COLLABORATOR" and "BILLING-ANSWER" in o["agentCollaboratorInvocationOutput"]["output"]["text"] for o in obs), obs)
    # router
    rtr = new_agent("router-agent", "You are the routing supervisor of the billing and facilities agents.", agentCollaboration="SUPERVISOR_ROUTER")
    ag.associate_agent_collaborator(agentId=rtr, agentVersion="DRAFT", agentDescriptor={"aliasArn": ACCT_ALIAS.format(bill, bill_al)}, collaboratorName="billing", collaborationInstruction="invoices")
    ag.associate_agent_collaborator(agentId=rtr, agentVersion="DRAFT", agentDescriptor={"aliasArn": ACCT_ALIAS.format(fac, fac_al)}, collaboratorName="facilities", collaborationInstruction="rooms")
    rtr_al = prep(rtr)
    evs = invoke(rtr, rtr_al, "s-rt", "facility-q is room B2 free?", enableTrace=True)
    check("SUPERVISOR_ROUTER routes a single-domain request straight to the collaborator", chunks(evs) == "FACILITIES-ANSWER: room B2 is free", chunks(evs))
    check("routingClassifierTrace emitted", any("routingClassifierTrace" in t["trace"] for t in traces(evs)), [list(t["trace"]) for t in traces(evs)])
    evs = invoke(rtr, rtr_al, "s-rt2", "hello how are you")
    check("router falls back to the supervisor's own orchestration when no collaborator fits", "plain answer" in chunks(evs), chunks(evs))
    ag.disassociate_agent_collaborator(agentId=sup, agentVersion="DRAFT", collaboratorId=c1["collaboratorId"])
    check("DisassociateAgentCollaborator", len(ag.list_agent_collaborators(agentId=sup, agentVersion="DRAFT")["agentCollaboratorSummaries"]) == 1)
    try:
        ag.associate_agent_collaborator(agentId=bill, agentVersion="DRAFT", agentDescriptor={"aliasArn": ACCT_ALIAS.format(sup, sup_al)}, collaboratorName="sup", collaborationInstruction="loop")
        check("cycle rejected", False)
    except ag.exceptions.ValidationException:
        check("collaboration cycles are rejected", True)

    # ───────────────────────── inline agents
    print("== InvokeInlineAgent")
    r = rt.invoke_inline_agent(foundationModel=FM, instruction="You raise work orders for the facilities team on request.", sessionId="s-inline", inputText="raise a work order please",
                               enableTrace=True, actionGroups=[{"actionGroupName": "ops", "actionGroupExecutor": {"lambda": fn_arn}, "functionSchema": {"functions": [
                                   {"name": "createWorkOrder", "description": "create a work order", "parameters": {"description": {"type": "string", "required": True}}}]}}])
    evs = events(r)
    check("InvokeInlineAgent runs the loop with inline action groups (Lambda invoked)", "WORK-ORDER-CREATED" in chunks(evs), chunks(evs))
    check("inline agent emits traces", any("orchestrationTrace" in t["trace"] for t in traces(evs)))
    r = rt.invoke_inline_agent(foundationModel=FM, instruction="You analyse data by writing python in the code interpreter.", sessionId="s-inline2", inputText="please compute the sum",
                               actionGroups=[{"actionGroupName": "ci", "parentActionGroupSignature": "AMAZON.CodeInterpreter"}])
    check("inline agent with the built-in CodeInterpreter group", "45" in chunks(events(r)))
    try:
        rt.invoke_inline_agent(foundationModel="not-a-model", instruction="You raise work orders for the facilities team on request.", sessionId="s-inline3", inputText="hi")
        check("bad inline model rejected", False)
    except Exception as e:  # noqa: BLE001
        check("inline agent with an unknown foundation model -> ValidationException", "ValidationException" in str(e), e)

    # ───────────────────────── Azure Foundry Assistants
    print("== Azure Foundry Assistants: code_interpreter + file_search (openai SDK)")
    try:
        import openai
    except ImportError:
        openai = None
        print("openai SDK missing - skipping")
    if openai:
        base = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/oai1"
        router.az_arm.handle("PUT", base, {"api-version": "2024-10-01"}, {"kind": "OpenAI", "location": "eastus", "sku": {"name": "S0"}})
        router.az_arm.handle("PUT", base + "/deployments/chat", {"api-version": "2024-10-01"},
                             {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-11-20"}}})
        cl = openai.AzureOpenAI(api_key="k", api_version="2025-03-01-preview", azure_endpoint=url, max_retries=0)
        a = cl.beta.assistants.create(model="chat", name="ci", instructions="You are a data helper.", tools=[{"type": "code_interpreter"}, {"type": "file_search"}])
        check("assistant accepts code_interpreter + file_search tools", [t.type for t in a.tools] == ["code_interpreter", "file_search"], a)
        th = cl.beta.threads.create(messages=[{"role": "user", "content": "azure-ci compute six times seven"}])
        run = cl.beta.threads.runs.create_and_poll(thread_id=th.id, assistant_id=a.id)
        check("code_interpreter run completes", run.status == "completed", run)
        msgs_ = cl.beta.threads.messages.list(thread_id=th.id, order="asc").data
        txt = msgs_[-1].content[0].text
        check("answer carries the real sandbox output (42)", "42" in txt.value, txt.value)
        steps = cl.beta.threads.runs.steps.list(thread_id=th.id, run_id=run.id).data
        tcs = [x for x in steps if x.type == "tool_calls"]
        check("run steps list the code_interpreter call with input and logs", tcs and tcs[0].step_details.tool_calls[0].type == "code_interpreter"
              and "print(6*7)" in tcs[0].step_details.tool_calls[0].code_interpreter.input and "42" in tcs[0].step_details.tool_calls[0].code_interpreter.outputs[0].logs, steps)
        check("file written by the code is saved to /files and annotated", [x.type for x in txt.annotations] == ["file_path"] and cl.files.content(txt.annotations[0].file_path.file_id).read() == b"42", txt.annotations)
        # file_search
        fobj = cl.files.create(file=("facilities-policy.txt", b"The cafeteria on floor 3 opens at 07:30. Booking a meeting room needs approval from the floor manager. Parking permits renew every January."), purpose="assistants")
        vs = cl.vector_stores.create(name="facilities-vs", file_ids=[fobj.id])
        check("vector store created with the file indexed", vs.file_counts.completed == 1 and vs.status == "completed", vs)
        check("vector store list/retrieve/files", cl.vector_stores.retrieve(vs.id).name == "facilities-vs" and [f.id for f in cl.vector_stores.files.list(vs.id).data] == [fobj.id])
        bad = cl.files.create(file=("scan.doc", b"\xd0\xcf\x11\xe0 legacy"), purpose="assistants")
        vf = cl.vector_stores.files.create(vector_store_id=vs.id, file_id=bad.id)
        check("unsupported file is modeled as status=failed with last_error", vf.status == "failed" and vf.last_error.code == "unsupported_file", vf)
        a2 = cl.beta.assistants.create(model="chat", instructions="Answer from the files.", tools=[{"type": "file_search"}], tool_resources={"file_search": {"vector_store_ids": [vs.id]}})
        th2 = cl.beta.threads.create(messages=[{"role": "user", "content": "When does the cafeteria open?"}])
        run2 = cl.beta.threads.runs.create_and_poll(thread_id=th2.id, assistant_id=a2.id)
        m2 = cl.beta.threads.messages.list(thread_id=th2.id, order="asc").data[-1].content[0].text
        check("file_search: retrieved passage reached the model and the answer cites the file", run2.status == "completed" and "07:30" in m2.value
              and m2.annotations and m2.annotations[0].type == "file_citation" and m2.annotations[0].file_citation.file_id == fobj.id, (m2.value, m2.annotations))
        try:
            cl.beta.assistants.create(model="chat", tools=[{"type": "file_search"}], tool_resources={"file_search": {"vector_store_ids": ["vs_nope"]}})
            check("unknown vector store rejected", False)
        except openai.NotFoundError:
            check("unknown vector store -> 404", True)
        cl.vector_stores.delete(vs.id)
        try:
            cl.vector_stores.retrieve(vs.id)
            check("deleted vector store gone", False)
        except openai.NotFoundError:
            check("deleted vector store -> 404", True)
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
