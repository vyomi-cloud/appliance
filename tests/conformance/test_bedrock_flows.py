"""Bedrock Flows node types + execution tracing (Agent, KnowledgeBase, LambdaFunction, Iterator/Collector, Loop, Retrieval, Storage) through the REAL boto3 clients (lane limflows).
Run: PYTHONPATH=. CLOUDLEARN_STATE_FILE=/tmp/x.sqlite3 /private/tmp/ai-probe-venv13/bin/python tests/conformance/test_bedrock_flows.py
Batch inference runs over the deterministic TEST STUB llm (tools/llm_stub); customization/provisioned/marketplace are metadata only."""
import asyncio, json, os, socket, sys, threading, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "llm_stub"))
import stub_llm_server  # noqa: E402
os.environ["VYOMI_LLM_ENDPOINT"] = stub_llm_server.start()
os.environ["VYOMI_LIST_BEDROCK_ALIASES"] = "1"  # the default routers/system profiles come from the opt-in alias set
os.environ.setdefault("CLOUDLEARN_STATE_FILE", "/tmp/bedrock-flows-test.sqlite3")
import anyio, boto3, uvicorn  # noqa: E402
from botocore.config import Config  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from core import wire_ingress  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def code(fn):
    try:
        fn()
    except ClientError as e:
        return e.response["Error"]["Code"]
    return None


app, router = FastAPI(), wire_ingress.appliance_router()


@app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def any_(p: str, request: Request):
    body = await request.body()
    return await anyio.to_thread.run_sync(lambda: asyncio.run(wire_ingress.serve(router, request, body=body)))

s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
threading.Thread(target=srv.run, daemon=True).start()
while not srv.started:
    time.sleep(0.05)
kw = dict(endpoint_url=f"http://127.0.0.1:{port}", region_name="us-east-1", aws_access_key_id="AKIAFAKE", aws_secret_access_key="x", config=Config(retries={"max_attempts": 1}))
ba, bar = boto3.client("bedrock-agent", **kw), boto3.client("bedrock-agent-runtime", **kw)
b, br, s3 = boto3.client("bedrock", **kw), boto3.client("bedrock-runtime", **kw), boto3.client("s3", **kw)



import io, zipfile
lam = boto3.client("lambda", **kw)
ROLE = "arn:aws:iam::123456789012:role/r"
ACC = "123456789012"


def evs(r):
    return list(r["responseStream"])


def run(fid, text, alias="TSTALIASID", trace=False):
    return evs(bar.invoke_flow(flowIdentifier=fid, flowAliasIdentifier=alias, enableTrace=trace, inputs=[{"nodeName": "In", "nodeOutputName": "document", "content": {"document": text}}]))


def outs(es):
    return [e["flowOutputEvent"]["content"]["document"] for e in es if "flowOutputEvent" in e]


def D(name, src, so, tgt, ti):
    return {"name": name, "type": "Data", "source": src, "target": tgt, "configuration": {"data": {"sourceOutput": so, "targetInput": ti}}}


def N(name, typ, cfg, ins=(), outs_=()):
    return {"name": name, "type": typ, "configuration": cfg, "inputs": [{"name": i, "type": "String", "expression": "$.data"} for i in ins], "outputs": [{"name": o, "type": "String"} for o in outs_]}


IN = N("In", "Input", {"input": {}}, (), ("document",))
OUT = N("Out", "Output", {"output": {}}, ("document",))


def mkflow(name, nodes, conns):
    fid = ba.create_flow(name=name, executionRoleArn=ROLE, definition={"nodes": nodes, "connections": conns})["id"]
    ba.prepare_flow(flowIdentifier=fid)
    return fid


def lam_fn(name, code):
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("index.py", code)
    return lam.create_function(FunctionName=name, Runtime="python3.12", Role=ROLE, Handler="index.handler", Code={"ZipFile": zb.getvalue()})["FunctionArn"]


# ── Lambda + Storage + Retrieval (S3)
s3.create_bucket(Bucket="flowb")
s3.put_object(Bucket="flowb", Key="in/note.txt", Body=b"hello from s3")
fn = lam_fn("upper", "def handler(e, c):\n    return {'shout': str(e).upper()[:40], 'n': 7}\n")
f1 = mkflow("lambda-flow", [IN, N("Fn", "LambdaFunction", {"lambdaFunction": {"lambdaArn": fn}}, ("codeHookInput",), ("functionResponse",)), OUT],
            [D("a", "In", "document", "Fn", "codeHookInput"), D("b", "Fn", "functionResponse", "Out", "document")])
o = outs(run(f1, "abc"))
check("LambdaFunction node invokes the function; object response kept as JSON", len(o) == 1 and o[0].get("n") == 7 and "ABC" in o[0]["shout"], o)
f2 = mkflow("s3-flow", [IN, N("Get", "Retrieval", {"retrieval": {"serviceConfiguration": {"s3": {"bucketName": "flowb"}}}}, ("objectKey",), ("s3Content",)),
                       N("Put", "Storage", {"storage": {"serviceConfiguration": {"s3": {"bucketName": "flowb"}}}}, ("content", "objectKey"), ("s3Uri",)), OUT,
                       N("Key", "Prompt", {"prompt": {"sourceConfiguration": {"inline": {"modelId": "amazon.nova-lite-v1:0", "templateType": "TEXT", "templateConfiguration": {"text": {"text": "{{x}}", "inputVariables": [{"name": "x"}]}}}}}}, ("x",), ("modelCompletion",))],
            [D("a", "In", "document", "Get", "objectKey"), D("b", "Get", "s3Content", "Put", "content"), D("c", "In", "document", "Put", "objectKey"), D("d", "Put", "s3Uri", "Out", "document")])
o = outs(run(f2, "in/note.txt"))
check("Retrieval reads S3, Storage writes S3 (waits for both inputs) and returns the s3Uri", o == ["s3://flowb/in/note.txt"], o)
f2b = mkflow("s3-copy", [IN, N("Get", "Retrieval", {"retrieval": {"serviceConfiguration": {"s3": {"bucketName": "flowb"}}}}, ("objectKey",), ("s3Content",)),
                         N("Put", "Storage", {"storage": {"serviceConfiguration": {"s3": {"bucketName": "flowb"}}}}, ("content", "objectKey"), ("s3Uri",)),
                         N("Fx", "LambdaFunction", {"lambdaFunction": {"lambdaArn": lam_fn("mkkey", "def handler(e, c):\n    return 'out/copy.txt'\n")}}, ("codeHookInput",), ("functionResponse",)), OUT],
             [D("a", "In", "document", "Get", "objectKey"), D("b", "Get", "s3Content", "Put", "content"), D("c", "In", "document", "Fx", "codeHookInput"), D("c2", "Fx", "functionResponse", "Put", "objectKey"), D("d", "Put", "s3Uri", "Out", "document")])
o = outs(run(f2b, "in/note.txt"))
check("Retrieval -> Storage copy lands in S3 under the Lambda-computed key", o == ["s3://flowb/out/copy.txt"] and s3.get_object(Bucket="flowb", Key="out/copy.txt")["Body"].read() == b"hello from s3", o)
miss = run  # missing object -> modeled failure
try:
    run(f2, "no/such.txt")
    check("Retrieval of a missing object -> DependencyFailedException", False)
except Exception as e:
    check("Retrieval of a missing object -> DependencyFailedException", "DependencyFailed" in str(e) or "no/such.txt" in str(e), e)

# ── Iterator / Collector (fan-out + ordered join)
f3 = mkflow("iter-flow", [IN, N("It", "Iterator", {"iterator": {}}, ("array",), ("arrayItem", "arraySize")),
                          N("Fn", "LambdaFunction", {"lambdaFunction": {"lambdaArn": lam_fn("dbl", "def handler(e, c):\n    return int(e) * 2\n")}}, ("codeHookInput",), ("functionResponse",)),
                          N("Col", "Collector", {"collector": {}}, ("arrayItem",), ("collectedArray",)), OUT],
            [D("a", "In", "document", "It", "array"), D("b", "It", "arrayItem", "Fn", "codeHookInput"), D("c", "Fn", "functionResponse", "Col", "arrayItem"), D("d", "Col", "collectedArray", "Out", "document")])
fv3 = ba.get_flow(flowIdentifier=f3)
o = outs(run(f3, [1, 2, 3, 4]))
check("Iterator fans out per item, Lambda runs per item, Collector joins the results in order", o == [[2, 4, 6, 8]], o)
o = outs(run(f3, []))
check("Iterator over an empty array completes with no output (nothing to collect)", o in ([], [[]]), o)
try:
    run(f3, "not-an-array")
    check("Iterator on a non-array -> ValidationException", False)
except Exception as e:
    check("Iterator on a non-array -> ValidationException", "array" in str(e), e)

# ── Condition numeric expression + branches
cond = {"condition": {"conditions": [{"name": "big", "expression": "document > 10"}, {"name": "default", "expression": "default"}]}}
f4 = mkflow("cond-flow", [IN, N("Chk", "Condition", cond, ("document",)), N("Big", "Prompt", {"prompt": {"sourceConfiguration": {"inline": {"modelId": "amazon.nova-lite-v1:0", "templateType": "TEXT", "templateConfiguration": {"text": {"text": "big {{document}}", "inputVariables": [{"name": "document"}]}}}}}}, ("document",), ("modelCompletion",)),
                           N("Out2", "Output", {"output": {}}, ("document",)), OUT],
            [D("a", "In", "document", "Chk", "document"),
             {"name": "t", "type": "Conditional", "source": "Chk", "target": "Big", "configuration": {"conditional": {"condition": "big"}}},
             {"name": "u", "type": "Conditional", "source": "Chk", "target": "Out2", "configuration": {"conditional": {"condition": "default"}}},
             D("bo", "Big", "modelCompletion", "Out", "document")])
check("numeric condition 42 > 10 takes the 'big' branch (Prompt -> Out)", len(outs(run(f4, "42"))) == 1)
check("condition 3 > 10 false -> default branch (Out2, value forwarded)", outs(run(f4, "3")) == ["3"], outs(run(f4, "3")))

# ── Knowledge base node (retrieve and retrieve+generate)
s3.put_object(Bucket="flowb", Key="d/wifi.txt", Body=b"The guest wifi password for the lobby is Aurora-2026. Contact facilities to rotate it.")
emb = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
kb = ba.create_knowledge_base(name="flow-kb", roleArn=ROLE, knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {"embeddingModelArn": emb}},
                              storageConfiguration={"type": "OPENSEARCH_SERVERLESS"})["knowledgeBase"]["knowledgeBaseId"]
ds = ba.create_data_source(knowledgeBaseId=kb, name="d", dataSourceConfiguration={"type": "S3", "s3Configuration": {"bucketArn": "arn:aws:s3:::flowb", "inclusionPrefixes": ["d/"]}})["dataSource"]["dataSourceId"]
ba.start_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds)
f5 = mkflow("kb-flow", [IN, N("Ask", "KnowledgeBase", {"knowledgeBase": {"knowledgeBaseId": kb, "modelId": "amazon.nova-lite-v1:0"}}, ("retrievalQuery",), ("outputText",)), OUT],
            [D("a", "In", "document", "Ask", "retrievalQuery"), D("b", "Ask", "outputText", "Out", "document")])
o = outs(run(f5, "What is the lobby wifi password?"))
check("KnowledgeBase node with modelId = retrieve-and-generate answer text", len(o) == 1 and isinstance(o[0], str) and len(o[0]) > 0, o)
f5b = mkflow("kb-retrieve", [IN, N("Ask", "KnowledgeBase", {"knowledgeBase": {"knowledgeBaseId": kb}}, ("retrievalQuery",), ("outputText",)), OUT],
             [D("a", "In", "document", "Ask", "retrievalQuery"), D("b", "Ask", "outputText", "Out", "document")])
o = outs(run(f5b, "lobby wifi password"))
check("KnowledgeBase node without modelId returns the retrieved chunks (array, with the document text)", len(o) == 1 and isinstance(o[0], list) and "Aurora-2026" in json.dumps(o[0]), o)

# ── Agent node
a = ba.create_agent(agentName="flow-agent", foundationModel="amazon.nova-lite-v1:0", agentResourceRoleArn=ROLE, instruction="You are a helpful facilities assistant who answers briefly and politely.")["agent"]["agentId"]
ba.prepare_agent(agentId=a)
aal = ba.create_agent_alias(agentId=a, agentAliasName="live")["agentAlias"]
f6 = mkflow("agent-flow", [IN, N("Ag", "Agent", {"agent": {"agentAliasArn": aal["agentAliasArn"]}}, ("agentInputText",), ("agentResponse",)), OUT],
            [D("a", "In", "document", "Ag", "agentInputText"), D("b", "Ag", "agentResponse", "Out", "document")])
o = outs(run(f6, "Say hello"))
check("Agent node invokes the Bedrock agent alias and returns its response text", len(o) == 1 and isinstance(o[0], str) and len(o[0]) > 0, o)

# ── Loop node
lp = {"loop": {"definition": {"nodes": [
        N("LIn", "LoopInput", {"loopInput": {}}, (), ("loopInput",)),
        N("Inc", "LambdaFunction", {"lambdaFunction": {"lambdaArn": lam_fn("inc", "def handler(e, c):\n    return int(e) + 1\n")}}, ("codeHookInput",), ("functionResponse",)),
        N("Ctl", "LoopController", {"loopController": {"continueCondition": {"name": "more", "expression": "input < 5"}, "maxIterations": 20}}, ("input",), ())],
      "connections": [D("l1", "LIn", "loopInput", "Inc", "codeHookInput"), D("l2", "Inc", "functionResponse", "Ctl", "input")]}}}
f7 = mkflow("loop-flow", [IN, N("Lp", "Loop", lp, ("loopInput",), ("loopOutput",)), OUT], [D("a", "In", "document", "Lp", "loopInput"), D("b", "Lp", "loopOutput", "Out", "document")])
o = outs(run(f7, "0"))
check("Loop node repeats its body until the LoopController condition is false (0 -> 5)", o == [5], o)
lp2 = json.loads(json.dumps(lp)); lp2["loop"]["definition"]["nodes"][2]["configuration"]["loopController"] = {"continueCondition": {"name": "more", "expression": "input < 500"}, "maxIterations": 3}
f7b = mkflow("loop-cap", [IN, N("Lp", "Loop", lp2, ("loopInput",), ("loopOutput",)), OUT], [D("a", "In", "document", "Lp", "loopInput"), D("b", "Lp", "loopOutput", "Out", "document")])
check("Loop stops at maxIterations", outs(run(f7b, "0")) == [3], outs(run(f7b, "0")))

# ── validation
def bad(nodes, conns=()):
    return code(lambda: ba.create_flow(name="vflow", executionRoleArn=ROLE, definition={"nodes": nodes, "connections": list(conns)}))


check("Agent node with a malformed alias ARN -> ValidationException", bad([IN, N("Ag", "Agent", {"agent": {"agentAliasArn": "nope"}}), OUT]) == "ValidationException")
check("Storage node with an empty bucket -> ValidationException", bad([IN, N("S", "Storage", {"storage": {"serviceConfiguration": {"s3": {"bucketName": ""}}}}), OUT]) == "ValidationException")
check("Loop body without LoopController -> ValidationException", bad([IN, N("Lp", "Loop", {"loop": {"definition": {"nodes": [N("LIn", "LoopInput", {"loopInput": {}})], "connections": []}}}), OUT]) == "ValidationException")
check("cyclic flow rejected", bad([IN, N("A", "Collector", {"collector": {}}), N("B", "Collector", {"collector": {}}), OUT],
                                   [D("x", "A", "collectedArray", "B", "arrayItem"), D("y", "B", "collectedArray", "A", "arrayItem")]) == "ValidationException")
check("Lex node still rejected (not simulated)", bad([IN, N("L", "Lex", {"lex": {"botAliasArn": "arn:aws:lex:us-east-1:123456789012:bot-alias/A/B", "localeId": "en_US"}}), OUT]) == "ValidationException")

# ── execution tracing
es = run(f2b, "in/note.txt", trace=True)
tr = [e["flowTraceEvent"]["trace"] for e in es if "flowTraceEvent" in e]
kinds = {k for t in tr for k in t}
check("enableTrace emits flowTraceEvent node input + output traces", {"nodeInputTrace", "nodeOutputTrace"} <= kinds and len(tr) >= 8, kinds)
ni = [t["nodeInputTrace"] for t in tr if "nodeInputTrace" in t and t["nodeInputTrace"]["nodeName"] == "Put"]
check("Storage node input trace carries both fields", len(ni) == 1 and {f["nodeInputName"] for f in ni[0]["fields"]} == {"content", "objectKey"}, ni)
no = [t["nodeOutputTrace"] for t in tr if "nodeOutputTrace" in t and t["nodeOutputTrace"]["nodeName"] == "Put"]
check("Storage node output trace carries the s3Uri", no and no[0]["fields"][0]["nodeOutputName"] == "s3Uri" and no[0]["fields"][0]["content"]["document"] == "s3://flowb/out/copy.txt", no)
check("tracing is off by default", not [e for e in run(f2b, "in/note.txt") if "flowTraceEvent" in e])
es = run(f4, "42", trace=True)
ct = [e["flowTraceEvent"]["trace"]["conditionNodeResultTrace"] for e in es if "conditionNodeResultTrace" in e.get("flowTraceEvent", {}).get("trace", {})]
check("Condition node emits conditionNodeResultTrace with the satisfied condition", len(ct) == 1 and ct[0]["satisfiedConditions"] == [{"conditionName": "big"}], ct)
check("flowOutputEvent nodeType is the real enum FlowOutputNode", [e["flowOutputEvent"]["nodeType"] for e in es if "flowOutputEvent" in e] == ["FlowOutputNode"])
fa = ba.create_flow_version(flowIdentifier=f3)["version"]
al3 = ba.create_flow_alias(flowIdentifier=f3, name="live", routingConfiguration=[{"flowVersion": fa}])["id"]
check("published version + alias execute the same graph", outs(run(f3, [5, 6], alias=al3)) == [[10, 12]])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
