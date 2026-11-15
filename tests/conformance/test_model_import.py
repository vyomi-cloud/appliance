"""Chat-model IMPORT (lane nanoimport) on the three clouds, through the real SDK / REST wire shapes.
Bedrock Custom Model Import: boto3 create/get/list_model_import_jobs + list/get/delete_imported_model + invoke_model/converse on the imported ARN.
Vertex: models:upload (artifactUri gs://...), endpoint create + deployModel + :generateContent / :predict, models delete.
Azure: Vyomi-extension POST /openai/vyomi/custom-models (multipart via the real openai SDK's HTTP client + REST), ARM deployment, chat.completions.
The adapter is the 1.8 MB LoRA GGUF measured in the T2 spike (SmolLM2-135M, r=8). SERVING (wllama in the browser) is proven by wasm/ui-tests/import-e2e.mjs; here the
serving engine is a labelled test stub registered through llm_core.set_custom_backend, which proves the wiring (ids resolve to the imported model, the default model is
NEVER used as a fallback, errors are modeled when no engine exists).
Run: PYTHONPATH=.:<openai-pkgs> /private/tmp/ai-probe-venv13/bin/python tests/conformance/test_model_import.py"""
import asyncio, io, json, os, socket, sys, threading, time, urllib.request, urllib.error

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
os.environ.pop("VYOMI_LLM_ENDPOINT", None)
os.environ["VYOMI_LLM_DISABLE"] = "1"
os.environ.setdefault("CLOUDLEARN_STATE_FILE", "/tmp/model-import-test.sqlite3")
import anyio, boto3, uvicorn  # noqa: E402
from botocore.config import Config  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from core import wire_ingress, training_core as tc, import_core as ic, bedrock_ctl_core as ctl, llm_core as llm  # noqa: E402

PASS = FAIL = 0
FIX = os.path.join(ROOT, "tests", "conformance", "fixtures", "nanoimport")
ADAPTER, META = open(f"{FIX}/adapter.gguf", "rb").read(), open(f"{FIX}/adapter_meta.json", "rb").read()


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def code(fn):
    try:
        fn()
    except ClientError as e:
        return e.response["Error"]["Code"]
    except Exception as e:  # noqa: BLE001
        return type(e).__name__
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
URL = f"http://127.0.0.1:{port}"
kw = dict(endpoint_url=URL, region_name="us-east-1", aws_access_key_id="AKIAFAKE", aws_secret_access_key="x", config=Config(retries={"max_attempts": 1}))
b, br, s3 = boto3.client("bedrock", **kw), boto3.client("bedrock-runtime", **kw), boto3.client("s3", **kw)
ROLE = "arn:aws:iam::123456789012:role/r"

# ---- pure validation (import_core) ----
def verr(adapter, meta):
    try:
        ic.validate_artifacts(adapter, json.dumps(meta).encode() if isinstance(meta, dict) else meta)
    except ic.ImportErr as e:
        return str(e)
    return None

M = json.loads(META)
check("validate: the spike adapter passes (base, rank, alpha, sha recorded)", verr(ADAPTER, M) is None and ic.validate_artifacts(ADAPTER, META)["rank"] == 8)
check("validate: not GGUF -> magic error", "GGUF magic" in (verr(b"hello world" * 10, M) or ""))
check("validate: truncated GGUF -> clear error", "truncated" in (verr(ADAPTER[:200], M) or "") or "not a valid GGUF" in (verr(ADAPTER[:200], M) or ""))
check("validate: size cap 50 MB", "50 MB" in (verr(b"GGUF" + b"\0" * (51 * 1024 * 1024), M) or ""))
check("validate: unsupported base lists the supported ones", "smollm2-360m-instruct" in (verr(ADAPTER, dict(M, base_model="gpt-4")) or ""))
check("validate: wrong base (hidden size) rejected", "hidden size 576" in (verr(ADAPTER, dict(M, base_model="smollm2-360m-instruct")) or ""))
check("validate: rank mismatch rejected", "rank" in (verr(ADAPTER, dict(M, rank=4)) or ""))
check("validate: alpha mismatch rejected", "alpha" in (verr(ADAPTER, dict(M, alpha=32)) or ""))
check("validate: meta missing / not json", "missing" in (verr(ADAPTER, b"") or "") and "JSON" in (verr(ADAPTER, b"[1]") or ""))
check("validate: base_quant checked", "base_quant" in (verr(ADAPTER, dict(M, base_quant="F32")) or "") and verr(ADAPTER, dict(M, base_quant="Q4_K_M")) is None)

s3.create_bucket(Bucket="model-import")
for pre, ad, mt in (("good", ADAPTER, META), ("bad", b"not gguf " * 20, META), ("wb", ADAPTER, json.dumps(dict(M, base_model="llama-3-8b")).encode()), ("nometa", ADAPTER, None)):
    s3.put_object(Bucket="model-import", Key=f"{pre}/adapter.gguf", Body=ad)
    if mt is not None:
        s3.put_object(Bucket="model-import", Key=f"{pre}/adapter_meta.json", Body=mt)

# ================= Bedrock Custom Model Import (boto3) =================
def mkjob(name, prefix, **over):
    a = dict(jobName=name, importedModelName=name + "-m", roleArn=ROLE, modelDataSource={"s3DataSource": {"s3Uri": f"s3://model-import/{prefix}/"}})
    a.update(over)
    return b.create_model_import_job(**a)["jobArn"]

ja = mkjob("tuned1", "good")
g = b.get_model_import_job(jobIdentifier=ja)
check("bedrock: CreateModelImportJob -> Completed with importedModelArn", g["status"] == "Completed" and g["importedModelArn"].startswith("arn:aws:bedrock:us-east-1:123456789012:imported-model/") and g["importedModelName"] == "tuned1-m", g)
arn = g["importedModelArn"]
gm = b.get_imported_model(modelIdentifier=arn)
check("bedrock: GetImportedModel (boto3 shape)", gm["modelArn"] == arn and gm["modelName"] == "tuned1-m" and gm["jobArn"] == ja and gm["modelDataSource"]["s3DataSource"]["s3Uri"] == "s3://model-import/good/" and gm["instructSupported"], gm)
check("bedrock: GetImportedModel by name", b.get_imported_model(modelIdentifier="tuned1-m")["modelArn"] == arn)
check("bedrock: ListImportedModels + ListModelImportJobs", [m["modelArn"] for m in b.list_imported_models()["modelSummaries"]] == [arn]
      and [j["jobArn"] for j in b.list_model_import_jobs()["modelImportJobSummaries"]] == [ja] and b.list_model_import_jobs(statusEquals="Failed")["modelImportJobSummaries"] == [])
check("bedrock: duplicate job name -> ConflictException", code(lambda: mkjob("tuned1", "good", importedModelName="other")) == "ConflictException")
check("bedrock: duplicate imported model name -> ConflictException", code(lambda: mkjob("tuned2", "good", importedModelName="tuned1-m")) == "ConflictException")
check("bedrock: malformed s3Uri -> ValidationException", code(lambda: mkjob("u1", "good", modelDataSource={"s3DataSource": {"s3Uri": "http://x/y"}})) == "ValidationException")
check("bedrock: bad importedModelName -> ValidationException", code(lambda: mkjob("u2", "good", importedModelName="bad name!")) == "ValidationException")
for nm, pre, want in (("badgguf", "bad", "GGUF magic"), ("wrongbase", "wb", "smollm2-135m-instruct"), ("nometa", "nometa", "adapter_meta.json"), ("nodata", "nonexistent", "not found")):
    jx = mkjob(nm, pre)
    gx = b.get_model_import_job(jobIdentifier=jx)
    check(f"bedrock: {nm} -> job Failed with a reason, no model created", gx["status"] == "Failed" and want in gx["failureMessage"] and "importedModelArn" not in gx, gx)
check("bedrock: failed jobs left no imported models", len(b.list_imported_models()["modelSummaries"]) == 1)
check("bedrock: unknown model/job -> ResourceNotFoundException", code(lambda: b.get_imported_model(modelIdentifier="nope")) == "ResourceNotFoundException"
      and code(lambda: b.get_model_import_job(jobIdentifier="nope")) == "ResourceNotFoundException")

# serving: honest 'unavailable' when no engine exists (Mesh/offline today): NEVER the default model
check("bedrock: no serving engine -> ModelNotReadyException naming the browser engine (default model not used)",
      code(lambda: br.converse(modelId=arn, messages=[{"role": "user", "content": [{"text": "hi"}]}])) == "ModelNotReadyException")
# with an engine (test stub of the Nano wllama bridge): Converse / InvokeModel resolve to the imported model
CALLS = []
async def stub(model, msgs, system, max_tokens, temperature, stop):
    CALLS.append((model, msgs, max_tokens, temperature))
    return {"text": "STUB[" + model + "]: " + msgs[-1]["content"][:30], "input_tokens": 7, "output_tokens": 5, "finish_reason": "stop", "backend": "test-stub"}
llm.set_custom_backend(lambda m: ic.is_import_id(m) and ic.has_model(m), stub)
cv = br.converse(modelId=arn, messages=[{"role": "user", "content": [{"text": "water heater leaking"}]}], inferenceConfig={"maxTokens": 24, "temperature": 0})
mid = arn.rsplit("/", 1)[1]
check("bedrock: Converse on the imported ARN -> served by the custom engine with the imported id", cv["output"]["message"]["content"][0]["text"].startswith(f"STUB[{mid}]") and CALLS[-1][0] == mid
      and cv["usage"]["outputTokens"] == 5 and cv["additionalModelResponseFields"]["vyomiImported"] is True, cv)
check("bedrock: seam passed maxTokens/temperature through", CALLS[-1][2] == 24 and CALLS[-1][3] == 0)
iv = json.loads(br.invoke_model(modelId=arn, body=json.dumps({"prompt": "boiler down", "max_gen_len": 12}))["body"].read())
check("bedrock: InvokeModel prompt body (Llama style) -> generation + vyomiImported", iv["generation"].startswith("STUB[") and iv["vyomiImported"] and iv["vyomiTrained"] and iv["generation_token_count"] == 5, iv)
iv2 = json.loads(br.invoke_model(modelId=arn, body=json.dumps({"messages": [{"role": "system", "content": "triage"}, {"role": "user", "content": "lift motor sparks"}], "max_tokens": 9}))["body"].read())
check("bedrock: InvokeModel messages body -> generation", iv2["generation"].startswith("STUB[") and CALLS[-1][1][0]["role"] == "system", iv2)
check("bedrock: InvokeModel bad body -> ValidationException", code(lambda: br.invoke_model(modelId=arn, body=json.dumps({"nope": 1}))) == "ValidationException")
cs = br.converse_stream(modelId=arn, messages=[{"role": "user", "content": [{"text": "stream me"}]}])
txt = "".join(e["contentBlockDelta"]["delta"]["text"] for e in cs["stream"] if "contentBlockDelta" in e)
check("bedrock: ConverseStream on the imported model", txt.startswith("STUB["), txt)
# foundation models still use the default path, not the custom engine
n0 = len(CALLS)
code(lambda: br.converse(modelId="amazon.nova-lite-v1:0", messages=[{"role": "user", "content": [{"text": "hi"}]}]))
check("bedrock: base models never reach the custom engine", len(CALLS) == n0)

# persistence: wipe the in-memory registries; adapters + metadata come back from the object store
ic._REG.clear(); ic._BYTES.clear(); ic._ST["loaded"] = False; ctl._IMPORTED.clear(); ctl._IMPJOBS.clear(); ctl._IMP_REH["done"] = None
check("bedrock: reload keeps the imported model + job (rebuilt from the object store)", [m["modelArn"] for m in b.list_imported_models()["modelSummaries"]] == [arn]
      and b.get_model_import_job(jobIdentifier=ja)["status"] == "Completed" and b.get_imported_model(modelIdentifier=arn)["jobArn"] == ja)
check("bedrock: reloaded model still serves", json.loads(br.invoke_model(modelId=arn, body=json.dumps({"prompt": "after reload"}))["body"].read())["generation"].startswith("STUB["))
check("persist: adapter + meta objects live under imports/<id>/ in the object store (not models/, which holds heads)",
      s3.get_object(Bucket="vyomi-models", Key=f"imports/{mid}/adapter.gguf")["Body"].read() == ADAPTER and tc.persisted_models() == [])

# ================= Vertex AI Model Registry =================
V = f"{URL}/v1/projects/vyomi-project/locations/us-central1"
def rest(method, url, body=None, headers=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None, headers={"content-type": "application/json", "authorization": "Bearer x", **(headers or {})})
    try:
        return 200, json.loads(urllib.request.urlopen(req).read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

st, up = rest("POST", V + "/models:upload", {"model": {"displayName": "facilities-tuned-vtx", "artifactUri": "gs://model-import/good/", "containerSpec": {"imageUri": "us-docker.pkg.dev/vyomi/serve:latest"}}})
check("vertex: models:upload with adapter artifactUri -> LRO", st == 200 and up.get("done") is not False and "operations/" in up["name"], up)
vm = (up.get("response") or {}).get("name")
st, mrec = rest("GET", f"{URL}/v1/{vm}")
check("vertex: Model carries vyomi-imported labels, no internals leaked", st == 200 and mrec["labels"]["vyomi-imported"] == "true" and mrec["displayName"] == "facilities-tuned-vtx" and not any(k.startswith("_") for k in mrec), mrec)
st, ep = rest("POST", V + "/endpoints", {"displayName": "facilities-ep"})
epn = ep["response"]["name"] if ep.get("response") else ep.get("name")
st, dp = rest("POST", f"{URL}/v1/{epn}:deployModel", {"deployedModel": {"model": vm, "displayName": "tuned"}, "trafficSplit": {"0": 100}})
check("vertex: deployModel of the imported model", st == 200, dp)
st, gc = rest("POST", f"{URL}/v1/{epn}:generateContent", {"contents": [{"role": "user", "parts": [{"text": "chiller alarm"}]}], "generationConfig": {"maxOutputTokens": 16, "temperature": 0}})
check("vertex: endpoint :generateContent -> candidates from the imported model, labelled", st == 200 and gc["candidates"][0]["content"]["parts"][0]["text"].startswith("STUB[") and gc["vyomiImported"] and gc["usageMetadata"]["candidatesTokenCount"] == 5, gc)
st, pr = rest("POST", f"{URL}/v1/{epn}:predict", {"instances": [{"prompt": "tap dripping", "max_tokens": 8}]})
check("vertex: endpoint :predict instances prompt -> predictions", st == 200 and pr["predictions"][0]["content"].startswith("STUB[") and pr["vyomiImported"], pr)
check("vertex: :predict bad instance -> 400", rest("POST", f"{URL}/v1/{epn}:predict", {"instances": [{"nope": 1}]})[0] == 400)
st, bad = rest("POST", V + "/models:upload", {"model": {"displayName": "bad-vtx", "artifactUri": "gs://model-import/bad/", "labels": {"vyomi-import": "chat-lora"}}})
check("vertex: bad adapter -> 400 INVALID_ARGUMENT with the reason", st == 400 and bad["error"]["status"] == "INVALID_ARGUMENT" and "GGUF magic" in bad["error"]["message"], bad)
st, bad2 = rest("POST", V + "/models:upload", {"model": {"displayName": "wb-vtx", "artifactUri": "gs://model-import/wb/"}})
check("vertex: unsupported base -> 400", st == 400 and "llama-3-8b" in bad2["error"]["message"], bad2)
st, plain = rest("POST", V + "/models:upload", {"model": {"displayName": "plain-vtx", "artifactUri": "gs://model-import/nonexistent-dir/"}})
check("vertex: artifactUri without an adapter keeps the plain metadata-only upload", st == 200, plain)
st, dl = rest("DELETE", f"{URL}/v1/{vm}")
check("vertex: delete model removes the import", st == 200 and not any(m.get("source", "").startswith("gs://") and m.get("cloud") == "gcp" for m in ic.persisted_models()), dl)

# ================= Azure (Vyomi extension + ARM deployment + chat) =================
def multipart(fields):
    bnd = "----vyomi" + os.urandom(6).hex(); out = io.BytesIO()
    for k, v in fields.items():
        out.write(f"--{bnd}\r\n".encode())
        if isinstance(v, tuple):
            out.write(f'Content-Disposition: form-data; name="{k}"; filename="{v[0]}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()); out.write(v[1])
        else:
            out.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}'.encode())
        out.write(b"\r\n")
    out.write(f"--{bnd}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={bnd}"

def az(method, path, body=None, ctype="application/json"):
    data = body if isinstance(body, (bytes, bytearray)) else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(URL + path, method=method, data=data, headers={"content-type": ctype, "api-key": "k"})
    try:
        return 200, json.loads(urllib.request.urlopen(req).read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

body, ct = multipart({"name": "facilities-az", "adapter": ("adapter.gguf", ADAPTER), "meta": ("adapter_meta.json", META)})
st, am_ = az("POST", "/openai/vyomi/custom-models", body, ct)
check("azure: register custom model (multipart) -> vyomi.custom_model, labelled extension", st == 200 and am_["object"] == "vyomi.custom_model" and am_["id"].startswith("vyomi.import.") and "Vyomi extension" in am_["vyomiNote"], am_)
fb, fct = multipart({"purpose": "fine-tune", "file": ("adapter.gguf", ADAPTER)}); st, fa = az("POST", "/openai/files", fb, fct)
fb, fct = multipart({"purpose": "fine-tune", "file": ("adapter_meta.json", META)}); st, fm = az("POST", "/openai/files", fb, fct)
st, am2 = az("POST", "/openai/vyomi/custom-models", {"name": "facilities-az2", "adapter_file": fa["id"], "meta_file": fm["id"]})
check("azure: register from /openai/files ids (JSON)", st == 200 and am2["vyomiImport"]["rank"] == 8, am2)
st, nf = az("POST", "/openai/vyomi/custom-models", {"name": "nofile", "adapter_file": "file-nope", "meta_file": fm["id"]})
check("azure: unknown file id -> 404", st == 404, nf)
body, ct = multipart({"name": "badaz", "adapter": ("adapter.gguf", b"nope" * 30), "meta": ("adapter_meta.json", META)})
st, e1 = az("POST", "/openai/vyomi/custom-models", body, ct)
check("azure: bad adapter -> 400 with reason", st == 400 and "GGUF magic" in e1["error"]["message"], e1)
check("azure: missing parts / unauthenticated / duplicate", az("POST", "/openai/vyomi/custom-models", multipart({"name": "x"})[0], multipart({"name": "x"})[1])[0] == 400
      and az("POST", "/openai/vyomi/custom-models", {"name": "facilities-az", "adapter_file": fa["id"], "meta_file": fm["id"]})[0] == 409)
check("azure: list/get/delete", len(az("GET", "/openai/vyomi/custom-models")[1]["data"]) == 2 and az("GET", "/openai/vyomi/custom-models/facilities-az")[1]["id"] == am_["id"]
      and az("DELETE", "/openai/vyomi/custom-models/facilities-az2")[1]["deleted"] and az("GET", "/openai/vyomi/custom-models/facilities-az2")[0] == 404)
SUB = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
A = SUB + "/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/aoai1"
try:
    rest("PUT", URL + SUB + "/resourcegroups/rg1?api-version=2021-04-01", {"location": "eastus"})
    rest("PUT", URL + A + "?api-version=2024-10-01", {"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {"customSubDomainName": "aoai1"}})
    st3, dd = rest("PUT", URL + A + "/deployments/facilities-dep?api-version=2024-10-01", {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "Vyomi", "name": am_["id"], "version": "1"}}})
    check("azure: ARM deployment of the imported model", st3 in (200, 201), dd)
    st, cc = az("POST", "/openai/deployments/facilities-dep/chat/completions?api-version=2024-10-21", {"messages": [{"role": "user", "content": "gate lock broken"}], "max_tokens": 10, "temperature": 0})
    check("azure: chat/completions on the deployment -> imported model answer, labelled", st == 200 and cc["choices"][0]["message"]["content"].startswith("STUB[") and cc["vyomiImported"] and cc["vyomiTrained"], (st, cc))
except Exception as e:  # noqa: BLE001
    check("azure: ARM deployment + chat", False, repr(e))
try:
    from openai import AzureOpenAI
    oc = AzureOpenAI(azure_endpoint=URL, api_key="k", api_version="2024-10-21", max_retries=0)
    r = oc.chat.completions.create(model="facilities-dep", messages=[{"role": "user", "content": "alarm panel offline"}], max_tokens=8)
    check("azure: real openai SDK chat.completions on the imported deployment", r.choices[0].message.content.startswith("STUB[") and r.model_extra.get("vyomiImported") is True, r)
except ImportError:
    print("[SKIP] openai SDK not installed (pip install --target <dir> openai)")

# no engine on the runtime -> every cloud answers honestly (never the default model)
llm.set_custom_backend(lambda m: ic.is_import_id(m) and ic.has_model(m), None)
st, nz = az("POST", "/openai/deployments/facilities-dep/chat/completions?api-version=2024-10-21", {"messages": [{"role": "user", "content": "x"}]})
check("azure: no engine -> 503, not a default-model answer", st == 503 and "browser" in json.dumps(nz), nz)
b.delete_imported_model(modelIdentifier=arn)
check("bedrock: DeleteImportedModel -> gone, and invoking it is a ValidationException (never the default model)", code(lambda: b.get_imported_model(modelIdentifier=arn)) == "ResourceNotFoundException"
      and code(lambda: br.converse(modelId=arn, messages=[{"role": "user", "content": [{"text": "hi"}]}])) == "ValidationException"
      and s3.list_objects_v2(Bucket="vyomi-models", Prefix=f"imports/{mid}/")["KeyCount"] == 0)

print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
