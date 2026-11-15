"""Bedrock Infer + Tune control plane through the REAL boto3 clients (lane bedrockui-b).
Run: PYTHONPATH=. /private/tmp/ai-probe-venv13/bin/python tests/conformance/test_bedrock_ctl.py
Batch inference runs over the deterministic TEST STUB llm (tools/llm_stub); customization/provisioned/marketplace are metadata only."""
import asyncio, json, os, socket, sys, threading, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "llm_stub"))
import stub_llm_server  # noqa: E402
os.environ["VYOMI_LLM_ENDPOINT"] = stub_llm_server.start()
os.environ.setdefault("CLOUDLEARN_STATE_FILE", "/tmp/bedrock-ctl-test.sqlite3")
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
b, br, s3 = boto3.client("bedrock", **kw), boto3.client("bedrock-runtime", **kw), boto3.client("s3", **kw)

# inference profiles
sysp = b.list_inference_profiles(typeEquals="SYSTEM_DEFINED")["inferenceProfileSummaries"]
check("system profiles for us/eu/apac with per-region models", {"us", "eu", "apac"} <= {p["inferenceProfileId"].split(".")[0] for p in sysp}
      and any(p["inferenceProfileId"].startswith("eu.") and len(p["models"]) == 6 for p in sysp))
r0 = b.list_inference_profiles(typeEquals="APPLICATION")["inferenceProfileSummaries"]
check("application tab empty at start", r0 == [], r0[:1])
arn = b.create_inference_profile(inferenceProfileName="facilities-haiku", modelSource={"copyFrom": "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-3-haiku-20240307-v1:0"}, tags=[{"key": "app", "value": "fac"}])["inferenceProfileArn"]
check("create application profile + list/get", any(p["inferenceProfileArn"] == arn and p["type"] == "APPLICATION" for p in b.list_inference_profiles(typeEquals="APPLICATION")["inferenceProfileSummaries"])
      and b.get_inference_profile(inferenceProfileIdentifier=arn)["status"] == "ACTIVE")
check("duplicate name -> ConflictException", code(lambda: b.create_inference_profile(inferenceProfileName="facilities-haiku", modelSource={"copyFrom": "anthropic.claude-3-haiku-20240307-v1:0"})) == "ConflictException")
check("converse via application profile ARN", br.converse(modelId=arn, messages=[{"role": "user", "content": [{"text": "hi"}]}])["stopReason"] == "end_turn")
b.delete_inference_profile(inferenceProfileIdentifier=arn)
check("delete application profile", b.list_inference_profiles(typeEquals="APPLICATION")["inferenceProfileSummaries"] == [])

# batch inference over S3 jsonl + local llm
s3.create_bucket(Bucket="bi-input")
s3.put_object(Bucket="bi-input", Key="in/data.jsonl", Body="\n".join(json.dumps({"recordId": f"R{i}", "modelInput": {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 30, "messages": [{"role": "user", "content": "Reply with the single word OK."}]}}) for i in range(3)).encode())
jarn = b.create_model_invocation_job(jobName="j1", roleArn="arn:aws:iam::123456789012:role/r", modelId="anthropic.claude-3-haiku-20240307-v1:0",
    inputDataConfig={"s3InputDataConfig": {"s3Uri": "s3://bi-input/in/"}}, outputDataConfig={"s3OutputDataConfig": {"s3Uri": "s3://bi-input/out/"}})["jobArn"]
j = b.get_model_invocation_job(jobIdentifier=jarn)
check("batch job Completed", j["status"] == "Completed", j)
keys = [o["Key"] for o in s3.list_objects_v2(Bucket="bi-input").get("Contents", [])]
check("batch output + manifest written", any(k.endswith("data.jsonl.out") for k in keys) and any(k.endswith("manifest.json.out") for k in keys), keys)
out = [json.loads(l) for l in s3.get_object(Bucket="bi-input", Key=next(k for k in keys if k.endswith("data.jsonl.out")))["Body"].read().decode().splitlines()]
check("batch output has model answers per recordId", len(out) == 3 and out[0]["recordId"] == "R0" and out[0]["modelOutput"]["content"][0]["text"], out)
check("list batch jobs", len(b.list_model_invocation_jobs()["invocationJobSummaries"]) == 1)
check("stop completed job -> ConflictException", code(lambda: b.stop_model_invocation_job(jobIdentifier=jarn)) == "ConflictException")

# provisioned throughput
pa = b.create_provisioned_model_throughput(provisionedModelName="pt1", modelId="amazon.nova-lite-v1:0", modelUnits=1, commitmentDuration="OneMonth")["provisionedModelArn"]
g = b.get_provisioned_model_throughput(provisionedModelId=pa)
check("provisioned InService with commitment", g["status"] == "InService" and g["commitmentDuration"] == "OneMonth" and g["modelUnits"] == 1, g)
check("list provisioned", [x["provisionedModelName"] for x in b.list_provisioned_model_throughputs()["provisionedModelSummaries"]] == ["pt1"])
check("provisioned bad model -> ValidationException", code(lambda: b.create_provisioned_model_throughput(provisionedModelName="x", modelId="nope.model", modelUnits=1)) == "ValidationException")

# customization (metadata only)
ja = b.create_model_customization_job(jobName="ft1", customModelName="cm1", roleArn="arn:aws:iam::123456789012:role/r", baseModelIdentifier="amazon.nova-lite-v1:0",
    trainingDataConfig={"s3Uri": "s3://bi-input/train.jsonl"}, outputDataConfig={"s3Uri": "s3://bi-input/ft/"}, hyperParameters={"epochCount": "1"})["jobArn"]
check("customization job starts InProgress", b.get_model_customization_job(jobIdentifier=ja)["status"] == "InProgress")
time.sleep(2.2)
check("customization job Completed + custom model listed", b.get_model_customization_job(jobIdentifier=ja)["status"] == "Completed"
      and [m["modelName"] for m in b.list_custom_models()["modelSummaries"]] == ["cm1"])
cm = b.list_custom_models()["modelSummaries"][0]["modelArn"]
check("get custom model", b.get_custom_model(modelIdentifier=cm)["baseModelArn"].endswith("amazon.nova-lite-v1:0"))
b.create_provisioned_model_throughput(provisionedModelName="pt-custom", modelId=cm, modelUnits=1)
b.delete_provisioned_model_throughput(provisionedModelId="pt-custom")
b.delete_custom_model(modelIdentifier=cm)
check("delete custom model", b.list_custom_models()["modelSummaries"] == [])

# prompt routers
dflt = b.list_prompt_routers(type="default")["promptRouterSummaries"]
check("two default routers", sorted(r["promptRouterName"] for r in dflt) == ["Anthropic Prompt Router", "Nova Prompt Router"])
ra = b.create_prompt_router(promptRouterName="pr1", models=[{"modelArn": "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.amazon.nova-lite-v1:0"}, {"modelArn": "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.amazon.nova-pro-v1:0"}],
    routingCriteria={"responseQualityDifference": 0.2}, fallbackModel={"modelArn": "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.amazon.nova-pro-v1:0"})["promptRouterArn"]
check("custom router listed + get", [r["promptRouterName"] for r in b.list_prompt_routers(type="custom")["promptRouterSummaries"]] == ["pr1"] and b.get_prompt_router(promptRouterArn=ra)["status"] == "AVAILABLE")
check("converse via prompt router ARN", br.converse(modelId=ra, messages=[{"role": "user", "content": [{"text": "hi"}]}])["stopReason"] == "end_turn")
b.delete_prompt_router(promptRouterArn=ra)
check("delete router; default not deletable", b.list_prompt_routers(type="custom")["promptRouterSummaries"] == [] and code(lambda: b.delete_prompt_router(promptRouterArn=dflt[0]["promptRouterArn"])) == "ValidationException")

# marketplace endpoints
ea = b.create_marketplace_model_endpoint(modelSourceIdentifier="arn:aws:sagemaker:us-east-1:123456789012:hub-content/x/Model/y", endpointName="ep1", acceptEula=True,
    endpointConfig={"sageMaker": {"initialInstanceCount": 1, "instanceType": "ml.g5.2xlarge", "executionRole": "arn:aws:iam::123456789012:role/r"}})["marketplaceModelEndpoint"]["endpointArn"]
check("marketplace endpoint listed/get", [e["endpointArn"] for e in b.list_marketplace_model_endpoints()["marketplaceModelEndpoints"]] == [ea]
      and b.get_marketplace_model_endpoint(endpointArn=ea)["marketplaceModelEndpoint"]["status"] == "Registered")
b.delete_marketplace_model_endpoint(endpointArn=ea)
check("delete marketplace endpoint", b.list_marketplace_model_endpoints()["marketplaceModelEndpoints"] == [])
b.delete_provisioned_model_throughput(provisionedModelId=pa)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
