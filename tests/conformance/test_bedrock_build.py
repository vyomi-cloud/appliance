"""Bedrock prompts/flows/evaluations/logging/guardrails through the REAL boto3 clients (lane uiaws).
Run: PYTHONPATH=. /private/tmp/ai-probe-venv13/bin/python tests/conformance/test_bedrock_build.py
Batch inference runs over the deterministic TEST STUB llm (tools/llm_stub); customization/provisioned/marketplace are metadata only."""
import asyncio, json, os, socket, sys, threading, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "llm_stub"))
import stub_llm_server  # noqa: E402
os.environ["VYOMI_LLM_ENDPOINT"] = stub_llm_server.start()
os.environ["VYOMI_LIST_BEDROCK_ALIASES"] = "1"  # the default routers/system profiles come from the opt-in alias set
os.environ.setdefault("CLOUDLEARN_STATE_FILE", "/tmp/bedrock-build-test.sqlite3")
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


import gzip
# ── prompt management
pr = ba.create_prompt(name="facilities-summary", defaultVariant="v1", variants=[{"name": "v1", "templateType": "TEXT", "modelId": "amazon.nova-lite-v1:0",
     "templateConfiguration": {"text": {"text": "Summarize for {{audience}}: {{body}}"}}}])
pid = pr["id"]
check("create_prompt infers inputVariables", [v["name"] for v in pr["variants"][0]["templateConfiguration"]["text"]["inputVariables"]] == ["audience", "body"])
check("bad prompt name -> ValidationException", code(lambda: ba.create_prompt(name="bad name!")) == "ValidationException")
ba.update_prompt(promptIdentifier=pid, name="facilities-summary", description="d2", defaultVariant="v1", variants=pr["variants"])
v1 = ba.create_prompt_version(promptIdentifier=pid)
check("create_prompt_version -> 1", v1["version"] == "1" and v1["arn"].endswith(":1"))
check("get_prompt version 1 + DRAFT", ba.get_prompt(promptIdentifier=pid, promptVersion="1")["version"] == "1" and ba.get_prompt(promptIdentifier=pid)["description"] == "d2")
check("list_prompts", [p["name"] for p in ba.list_prompts()["promptSummaries"]] == ["facilities-summary"])
check("list_prompts(identifier) shows versions", len(ba.list_prompts(promptIdentifier=pid)["promptSummaries"]) == 2)
check("missing prompt -> ResourceNotFound", code(lambda: ba.get_prompt(promptIdentifier="ZZZZZZZZZZ")) == "ResourceNotFoundException")

# ── flows (Input -> Prompt(managed) -> Output, and a Condition)
defn = {"nodes": [
  {"name": "In", "type": "Input", "configuration": {"input": {}}, "outputs": [{"name": "document", "type": "String"}]},
  {"name": "Sum", "type": "Prompt", "configuration": {"prompt": {"sourceConfiguration": {"inline": {"modelId": "amazon.nova-lite-v1:0", "templateType": "TEXT",
        "templateConfiguration": {"text": {"text": "Say hello to {{who}}", "inputVariables": [{"name": "who"}]}}}}}},
   "inputs": [{"name": "who", "type": "String", "expression": "$.data"}], "outputs": [{"name": "modelCompletion", "type": "String"}]},
  {"name": "Out", "type": "Output", "configuration": {"output": {}}, "inputs": [{"name": "document", "type": "String", "expression": "$.data"}]}],
  "connections": [{"name": "c1", "type": "Data", "source": "In", "target": "Sum", "configuration": {"data": {"sourceOutput": "document", "targetInput": "who"}}},
                  {"name": "c2", "type": "Data", "source": "Sum", "target": "Out", "configuration": {"data": {"sourceOutput": "modelCompletion", "targetInput": "document"}}}]}
fl = ba.create_flow(name="hello-flow", executionRoleArn="arn:aws:iam::123456789012:role/r", definition=defn)
fid = fl["id"]
check("create_flow NotPrepared", fl["status"] == "NotPrepared")
check("prepare_flow", ba.prepare_flow(flowIdentifier=fid)["status"] == "Prepared")
fv = ba.create_flow_version(flowIdentifier=fid)["version"]
al = ba.create_flow_alias(flowIdentifier=fid, name="live", routingConfiguration=[{"flowVersion": fv}])["id"]
check("list flows/versions/aliases", [f["name"] for f in ba.list_flows()["flowSummaries"]] == ["hello-flow"] and len(ba.list_flow_versions(flowIdentifier=fid)["flowVersionSummaries"]) == 1
      and len(ba.list_flow_aliases(flowIdentifier=fid)["flowAliasSummaries"]) == 1)
r = bar.invoke_flow(flowIdentifier=fid, flowAliasIdentifier=al, inputs=[{"nodeName": "In", "nodeOutputName": "document", "content": {"document": "Maya"}}])
evs = list(r["responseStream"])
outs = [e["flowOutputEvent"] for e in evs if "flowOutputEvent" in e]
check("invoke_flow returns model output + completion", len(outs) == 1 and isinstance(outs[0]["content"]["document"], str) and outs[0]["content"]["document"] != ""
      and any(e.get("flowCompletionEvent", {}).get("completionReason") == "SUCCESS" for e in evs), evs)
bad = dict(defn); bad = {**defn, "nodes": defn["nodes"] + [{"name": "L", "type": "LambdaFunction", "configuration": {"lambdaFunction": {"lambdaArn": "arn:aws:lambda:us-east-1:123456789012:function:f"}}}]}
check("unsupported node type rejected", code(lambda: ba.create_flow(name="bad-flow", executionRoleArn="arn:aws:iam::123456789012:role/r", definition=bad)) == "ValidationException")
check("alias to missing version -> NotFound", code(lambda: ba.create_flow_alias(flowIdentifier=fid, name="x", routingConfiguration=[{"flowVersion": "9"}])) == "ResourceNotFoundException")
ba.delete_flow_alias(flowIdentifier=fid, aliasIdentifier=al)
ba.delete_flow(flowIdentifier=fid)
check("delete flow", ba.list_flows()["flowSummaries"] == [])

# ── evaluations (real scoring against the local model)
s3.create_bucket(Bucket="evalb")
s3.put_object(Bucket="evalb", Key="in/ds.jsonl", Body=("\n".join(json.dumps(x) for x in [{"prompt": "What is 2+2?", "referenceResponse": "4", "category": "math"}, {"prompt": "Capital of France?", "referenceResponse": "Paris", "category": "geo"}])).encode())
cfg = {"automated": {"datasetMetricConfigs": [{"taskType": "QuestionAndAnswer", "dataset": {"name": "qa", "datasetLocation": {"s3Uri": "s3://evalb/in/ds.jsonl"}}, "metricNames": ["Builtin.Accuracy", "Builtin.Robustness", "Builtin.Toxicity"]}]}}
ja = b.create_evaluation_job(jobName="ev1", roleArn="arn:aws:iam::123456789012:role/r", evaluationConfig=cfg,
    inferenceConfig={"models": [{"bedrockModel": {"modelIdentifier": "amazon.nova-lite-v1:0", "inferenceParams": "{\"temperature\":0}"}}]}, outputDataConfig={"s3Uri": "s3://evalb/out/"})["jobArn"]
g = b.get_evaluation_job(jobIdentifier=ja)
check("evaluation job Completed", g["status"] == "Completed", g.get("failureMessages"))
rep = json.loads(s3.get_object(Bucket="evalb", Key=[o["Key"] for o in s3.list_objects_v2(Bucket="evalb", Prefix="out/")["Contents"] if o["Key"].endswith("report.json")][0])["Body"].read())
m = rep["datasets"][0]["metrics"]
check("report has scored metrics in [0,1]", set(m) == {"Builtin.Accuracy", "Builtin.Robustness", "Builtin.Toxicity"} and all(0 <= v <= 1 for v in m.values()), m)
check("list evaluation jobs", [j["jobName"] for j in b.list_evaluation_jobs()["jobSummaries"]] == ["ev1"])
check("unsupported metric rejected", code(lambda: b.create_evaluation_job(jobName="ev2", roleArn="arn:aws:iam::123456789012:role/r", evaluationConfig={"automated": {"datasetMetricConfigs": [{"taskType": "Custom", "dataset": {"name": "d", "datasetLocation": {"s3Uri": "s3://evalb/in/ds.jsonl"}}, "metricNames": ["Builtin.Bogus"]}]}},
    inferenceConfig={"models": [{"bedrockModel": {"modelIdentifier": "amazon.nova-lite-v1:0"}}]}, outputDataConfig={"s3Uri": "s3://evalb/out/"})) == "ValidationException")
check("f1 metric sanity", __import__("core.bedrock_build_core", fromlist=["f1"]).f1("the cat sat", "the cat sat") == 1.0 and __import__("core.bedrock_build_core", fromlist=["f1"]).f1("a", "b") == 0.0)

# ── invocation logging
check("no logging config initially", "loggingConfig" not in b.get_model_invocation_logging_configuration())
b.put_model_invocation_logging_configuration(loggingConfig={"s3Config": {"bucketName": "evalb", "keyPrefix": "bed"}, "cloudWatchConfig": {"logGroupName": "/bedrock/inv", "roleArn": "arn:aws:iam::123456789012:role/r"}, "textDataDeliveryEnabled": True})
check("get logging config", b.get_model_invocation_logging_configuration()["loggingConfig"]["s3Config"]["bucketName"] == "evalb")
br.converse(modelId="amazon.nova-lite-v1:0", messages=[{"role": "user", "content": [{"text": "log me"}]}])
ks = [o["Key"] for o in s3.list_objects_v2(Bucket="evalb", Prefix="bed/AWSLogs/").get("Contents", [])]
check("invocation log delivered to S3 (gzip, real layout)", len(ks) == 1 and "BedrockModelInvocationLogs" in ks[0] and json.loads(gzip.decompress(s3.get_object(Bucket="evalb", Key=ks[0])["Body"].read()))["operation"] == "converse", ks)
cwl = boto3.client("logs", **kw)
check("invocation log delivered to CloudWatch Logs", len(cwl.filter_log_events(logGroupName="/bedrock/inv").get("events", [])) == 1)
check("empty logging config rejected", code(lambda: b.put_model_invocation_logging_configuration(loggingConfig={})) == "ValidationException")
b.delete_model_invocation_logging_configuration()
check("logging config deleted", "loggingConfig" not in b.get_model_invocation_logging_configuration())

# ── model availability, optimize prompt
check("foundation model availability", b.get_foundation_model_availability(modelId="amazon.nova-lite-v1:0")["authorizationStatus"] == "AUTHORIZED")
check("unknown model availability -> NotFound", code(lambda: b.get_foundation_model_availability(modelId="nope.model")) == "ResourceNotFoundException")
o = list(bar.optimize_prompt(input={"textPrompt": {"text": "tell me about {{topic}}"}}, targetModelId="amazon.nova-lite-v1:0")["optimizedPrompt"])
check("optimize_prompt returns an optimizedPromptEvent", any("optimizedPromptEvent" in e for e in o), o)

# ── guardrails over the same client the console uses (create / version / apply / delete)
gr = b.create_guardrail(name="facilities-guardrail", blockedInputMessaging="blocked in", blockedOutputsMessaging="blocked out",
    sensitiveInformationPolicyConfig={"piiEntitiesConfig": [{"type": "EMAIL", "action": "ANONYMIZE"}]}, contentPolicyConfig={"filtersConfig": [{"type": "INSULTS", "inputStrength": "HIGH", "outputStrength": "HIGH"}]})
gv = b.create_guardrail_version(guardrailIdentifier=gr["guardrailId"])["version"]
ap = br.apply_guardrail(guardrailIdentifier=gr["guardrailId"], guardrailVersion=gv, source="INPUT", content=[{"text": {"text": "mail me at a@b.com you idiot"}}])
check("apply_guardrail intervenes", ap["action"] == "GUARDRAIL_INTERVENED", ap)
b.delete_guardrail(guardrailIdentifier=gr["guardrailId"])
check("delete guardrail", b.list_guardrails()["guardrails"] == [])
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
