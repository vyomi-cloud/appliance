"""REAL chat-model LoRA fine-tuning behind Bedrock / Vertex / Azure OpenAI customization jobs (lane meshlora), through real SDKs / REST.
Trains SmolLM2-135M-Instruct for real with trainer/lora_train.py (PEFT, CPU), converts the adapter to f16 GGUF, stores models/<id>/adapter.gguf,
and serves it through the llm_core `lora` seam. Serving is checked two ways, BOTH WITHOUT a real llama-server:
  (a) a deterministic registered llm backend (routing + adapter selection + base model id), and
  (b) a tiny fake llama-server over real HTTP implementing GET /lora-adapters and POST /v1/chat/completions with the `lora` field (proves the wire contract).
Needs: VYOMI_TRAINER_PYTHON (venv with torch/transformers/peft/gguf) and VYOMI_LLAMACPP_DIR (llama.cpp checkout with convert_lora_to_gguf.py, see trainer/fetch_llamacpp.sh)
and the HF model cache (downloads SmolLM2-135M once, ~270 MB). Without them the training sections are SKIPPED (validation sections still run).
Run: PYTHONPATH=.:<openai-pkgs> VYOMI_TRAINER_PYTHON=... VYOMI_LLAMACPP_DIR=... /private/tmp/ai-probe-venv13/bin/python tests/conformance/test_chat_lora_jobs.py"""
import asyncio, json, os, random, socket, sys, tempfile, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
os.environ.pop("VYOMI_LLM_ENDPOINT", None)
os.environ["VYOMI_LLM_DISABLE"] = "1"
os.environ.setdefault("CLOUDLEARN_STATE_FILE", "/tmp/chat-lora-test.sqlite3")
ADIR = tempfile.mkdtemp(prefix="vyomi-adapters-")
os.environ["VYOMI_LLM_ADAPTER_DIR"] = ADIR
os.environ["VYOMI_TRAINER"] = "venv"
import anyio, boto3, uvicorn  # noqa: E402
from botocore.config import Config  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from core import wire_ingress, training_core as tc, bedrock_ctl_core as ctl, llm_core as llm, llm_runtime  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "trainer"))
import sample_data  # noqa: E402

PASS = FAIL = 0
CAN_TRAIN = bool(os.environ.get("VYOMI_TRAINER_PYTHON") and os.path.exists(os.environ["VYOMI_TRAINER_PYTHON"]) and os.environ.get("VYOMI_LLAMACPP_DIR"))
BASE = "smollm2-135m-instruct"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:400] if detail and not ok else ''}")


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
jl = lambda rs: "\n".join(json.dumps(r) for r in rs).encode()


def wait(fn, done, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = fn()
        if done(r):
            return r
        time.sleep(0.5)
    return fn()


def rest(method, url, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None, headers={"content-type": "application/json", "authorization": "Bearer x"})
    try:
        return 200, json.loads(urllib.request.urlopen(req).read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def mk(name, base=BASE, data="s3://train-data/tickets.jsonl", hp=None):
    return b.create_model_customization_job(jobName=name, customModelName=name + "-m", roleArn=ROLE, baseModelIdentifier=base, customizationType="FINE_TUNING",
                                            trainingDataConfig={"s3Uri": data}, outputDataConfig={"s3Uri": "s3://train-data/out/"}, hyperParameters=hp or {})["jobArn"]


def araw(arn):
    h = {"authorization": "AWS4-HMAC-SHA256 Credential=AKIAFAKE/20260101/us-east-1/bedrock/aws4_request, SignedHeaders=host, Signature=0"}
    return json.loads(urllib.request.urlopen(urllib.request.Request(f"{URL}/model-customization-jobs/{arn.rsplit('/', 1)[1]}", headers=h)).read())


s3.create_bucket(Bucket="train-data")
s3.put_object(Bucket="train-data", Key="tickets.jsonl", Body=jl(sample_data.rows(60)))
s3.put_object(Bucket="train-data", Key="tickets-small.jsonl", Body=jl(sample_data.rows(40, seed=11)))
s3.put_object(Bucket="train-data", Key="big.jsonl", Body=jl(sample_data.rows(2001)))
s3.put_object(Bucket="train-data", Key="bad.jsonl", Body=b'{"text":"a","label":"b"}\n' * 12)
s3.put_object(Bucket="train-data", Key="notlast.jsonl", Body=jl([{"messages": [{"role": "assistant", "content": "x"}, {"role": "user", "content": "y"}]}] * 12))
s3.put_object(Bucket="train-data", Key="few.jsonl", Body=jl(sample_data.rows(3)))

# ================= validation (no trainer needed) =================
check("base id forms resolve to the pool", all(tc.chat_base(x) == "qwen3-4b" for x in ("qwen3-4b", "vyomi.qwen3-4b", "ollama.qwen3:4b-instruct-2507-q4_K_M")) and tc.chat_base("amazon.nova-micro-v1:0") is None
      and tc.chat_base("all-minilm-l6-v2") is None
      and tc.chat_base("qwen2.5-3b") is None and tc.chat_base("deepseek-r1-8b") is None)   # licence traps: non-commercial base and the Llama-derived distill are never trainable
check("bedrock: chat base too large for 16 GB -> ValidationException naming the trainable list", code(lambda: mk("big8b", base="llama3.1-8b")) == "ValidationException")
check("bedrock: head-style rows on a chat base -> ValidationException", code(lambda: mk("badrows", data="s3://train-data/bad.jsonl")) == "ValidationException")
check("bedrock: >2000 rows -> ValidationException", code(lambda: mk("bigrows", data="s3://train-data/big.jsonl")) == "ValidationException")
check("bedrock: last turn not assistant -> ValidationException", code(lambda: mk("notlast", data="s3://train-data/notlast.jsonl")) == "ValidationException")
check("bedrock: too few rows -> ValidationException", code(lambda: mk("few", data="s3://train-data/few.jsonl")) == "ValidationException")
check("bedrock: hyperparameter out of range -> ValidationException", code(lambda: mk("badhp", hp={"loraRank": "9999"})) == "ValidationException")
check("bedrock: vendor base (amazon.nova-micro) stays metadata-only (not silently trained)", araw(mk("nova", base="amazon.titan-text-lite-v1", data="s3://train-data/tickets.jsonl")) is not None
      and "Metadata only" in araw(b.list_model_customization_jobs()["modelCustomizationJobSummaries"][0]["jobArn"]).get("vyomiNote", ""))
os.environ["VYOMI_TRAINER_PYTHON_SAVED"] = os.environ.get("VYOMI_TRAINER_PYTHON", "")
os.environ["VYOMI_TRAINER_PYTHON"] = "/nonexistent/python"
check("bedrock: no trainer installed -> ValidationException with build instructions, no job", code(lambda: mk("notrainer")) == "ValidationException"
      and not [j for j in b.list_model_customization_jobs()["modelCustomizationJobSummaries"] if j["jobName"] == "notrainer"])
os.environ["VYOMI_TRAINER_PYTHON"] = os.environ.pop("VYOMI_TRAINER_PYTHON_SAVED")
tc.set_bridge(lambda *a: None, lambda *a: None)
check("nano: chat LoRA is declared Mesh-only (clear error)", code(lambda: mk("nanotry")) == "ValidationException")
tc.set_bridge(None, None)
a = llm_runtime.lora_args(ADIR)
check("llm_runtime.lora_args: empty dir -> no flags", a == [])

# ================= serving seam: fake llama-server (real HTTP) =================
SEEN = []


class FakeLlama(BaseHTTPRequestHandler):
    loaded = []

    def log_message(self, *a):
        pass

    def _send(self, d):
        raw = json.dumps(d).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def do_GET(self):
        self._send(self.loaded)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
        SEEN.append(body)
        adapted = bool(body.get("lora")) and any(a["id"] == l["id"] and l["path"].endswith(".gguf") for a in body["lora"] for l in self.loaded)
        txt = "category=HVAC; priority=P1" if adapted else "I am a generic assistant."
        self._send({"model": body.get("model"), "choices": [{"index": 0, "message": {"role": "assistant", "content": txt}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 9, "completion_tokens": 7}})


fs = ThreadingHTTPServer(("127.0.0.1", 0), FakeLlama)
threading.Thread(target=fs.serve_forever, daemon=True).start()
llm.set_backend(None, None, None, endpoint=f"http://127.0.0.1:{fs.server_address[1]}")
FakeLlama.loaded = [{"id": 0, "path": "/adapters/other.gguf", "scale": 0.0}, {"id": 1, "path": "/adapters/m123.gguf", "scale": 0.0}]
r = llm.chat([{"role": "user", "content": "hi"}], lora={"name": "m123", "path": "/host/dir/m123.gguf"})
check("seam: per-request lora id resolved from GET /lora-adapters by file name", SEEN[-1]["lora"] == [{"id": 1, "scale": 1.0}] and r["text"].startswith("category="), SEEN[-1])
try:
    llm.chat([{"role": "user", "content": "hi"}], lora={"name": "ghost", "path": "ghost.gguf"}); ok = False
except llm.LlmUnavailable as e:
    ok = "not loaded in the llama-server" in str(e) and "--lora" in str(e)
check("seam: adapter not loaded in llama-server -> clear LlmUnavailable (restart hint)", ok)
r0 = llm.chat([{"role": "user", "content": "hi"}])
check("seam: no lora -> plain base model, no lora field sent", "lora" not in SEEN[-1] and r0["text"].startswith("I am"))

if not CAN_TRAIN:
    print("[SKIP] VYOMI_TRAINER_PYTHON / VYOMI_LLAMACPP_DIR not set: real training sections skipped")
    print(f"{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)

# ================= Bedrock: REAL LoRA job =================
ja = mk("tickets1", hp={"epochCount": "3", "batchSize": "4", "loraRank": "8", "maxSequenceLength": "128"})
seen_steps = []
def poll():
    v = (araw(ja).get("vyomiTraining") or {})
    seen_steps.append(len(v.get("steps") or []))
    return b.get_model_customization_job(jobIdentifier=ja)
g = wait(poll, lambda r: r["status"] != "InProgress")
vt = araw(ja)["vyomiTraining"]
check("bedrock: LoRA job runs for real and Completes (engine lora-peft)", g["status"] == "Completed" and vt["status"] == "Completed" and vt["engine"] == "lora-peft" and vt["taskType"] == "chat-lora", g.get("failureMessage") or vt)
st_ = vt["steps"]
check("bedrock: per-step loss reported into the job record (grew while running), loss falls", len(st_) >= 30 and max(seen_steps) > 0 and len(set(seen_steps)) > 2 and st_[-1]["loss"] < st_[0]["loss"] / 3, (len(st_), st_[:2], st_[-2:]))
check("bedrock: per-epoch metrics + trainingMetrics.trainingLoss via boto3", len(vt["metrics"]) == 3 and abs(g["trainingMetrics"]["trainingLoss"] - vt["metrics"][-1]["loss"]) < 1e-6, vt["metrics"])
ho = vt["heldOut"]
check("bedrock: held-out perplexity improves massively vs base (adapter off)", ho["perplexity"] < ho["baselinePerplexity"] / 10 and ho["exactMatch"] >= ho["baselineExactMatch"], ho)
cm = g["outputModelArn"]
mid = cm.rsplit("/", 1)[1]
key = vt["artifact"].split("s3://vyomi-models/")[1]
blob = s3.get_object(Bucket="vyomi-models", Key=key)["Body"].read()
meta = json.loads(s3.get_object(Bucket="vyomi-models", Key=f"models/{mid}/meta.json")["Body"].read())
check("adapter.gguf stored at models/<id>/adapter.gguf: valid GGUF LoRA, metadata (base, rank, alpha, rows)",
      key == f"models/{mid}/adapter.gguf" and blob[:4] == b"GGUF" and meta["baseModelId"] == BASE and meta["rank"] == 8 and meta["alpha"] == 16 and meta["rows"] == 60 and meta["adapterBytes"] == len(blob) and len(blob) < 8_000_000, meta)
check("outputDataConfig copy of the adapter", s3.list_objects_v2(Bucket="train-data", Prefix="out/")["KeyCount"] == 1)

# serving through the deterministic registered backend (routing + adapter selection), no llama-server
CALLS = []
def stub(msgs, system, max_tokens, temperature, stop, lora=None, model=None):
    CALLS.append({"lora": lora, "model": model, "msgs": msgs})
    return {"text": "category=PLUMBING; priority=P2" if lora else "plain base answer", "input_tokens": 11, "output_tokens": 6, "model": model or "stub"}
llm.set_backend(stub, None, "stub-model")
inv = json.loads(br.invoke_model(modelId=cm, body=json.dumps({"messages": [{"role": "user", "content": [{"text": "Triage this facilities ticket: The toilet in floor 2 is not working."}]}], "inferenceConfig": {"maxTokens": 32}}))["body"].read())
c = CALLS[-1]
check("bedrock: InvokeModel on the custom ARN -> base model + this adapter, vyomiTrained + adapter id", inv["vyomiTrained"] is True and inv["adapterId"] == mid and inv["output"]["message"]["content"][0]["text"].startswith("category=")
      and c["lora"]["name"] == mid and c["model"] == BASE and open(c["lora"]["path"], "rb").read() == blob, (inv, c))
cv = br.converse(modelId=cm, messages=[{"role": "user", "content": [{"text": "ticket please"}]}], system=[{"text": "Be terse."}])
check("bedrock: Converse -> adapter applied, additionalModelResponseFields.vyomiTrained, header", cv["additionalModelResponseFields"]["vyomiTrained"] is True and cv["additionalModelResponseFields"]["adapterId"] == mid
      and cv["ResponseMetadata"]["HTTPHeaders"].get("x-vyomi-adapter") == mid and CALLS[-1]["lora"] is not None and cv["usage"]["inputTokens"] == 11, cv)
pl = json.loads(br.invoke_model(modelId=cm, body=json.dumps({"prompt": "ticket", "max_gen_len": 20}))["body"].read())
check("bedrock: Llama-style prompt body -> generation + vyomiTrained", pl["generation"].startswith("category=") and pl["vyomiTrained"] is True)
check("bedrock: bad body -> ValidationException; streaming -> ValidationException", code(lambda: br.invoke_model(modelId=cm, body=json.dumps({"x": 1}))) == "ValidationException"
      and code(lambda: br.invoke_model_with_response_stream(modelId=cm, body=json.dumps({"prompt": "x"}))) == "ValidationException")
plain = br.converse(modelId="amazon.nova-micro-v1:0", messages=[{"role": "user", "content": [{"text": "hello"}]}])
check("bedrock: the base/vendor model is unaffected (no lora)", CALLS[-1]["lora"] is None and "vyomiTrained" not in json.dumps(plain.get("additionalModelResponseFields") or {}))
# through the fake llama-server over HTTP (the real wire contract of the seam)
llm.set_backend(None, None, None, endpoint=f"http://127.0.0.1:{fs.server_address[1]}")
FakeLlama.loaded = [{"id": 3, "path": f"/adapters/{mid}.gguf", "scale": 0.0}]
cv2 = br.converse(modelId=cm, messages=[{"role": "user", "content": [{"text": "ticket"}]}])
check("bedrock: through a (fake) llama-server: request carries lora [{id,scale}] and model = base pool id", SEEN[-1]["lora"] == [{"id": 3, "scale": 1.0}] and SEEN[-1]["model"] == llm.resolve_model(BASE)
      and cv2["output"]["message"]["content"][0]["text"] == "category=HVAC; priority=P1", SEEN[-1])
FakeLlama.loaded = []
check("bedrock: adapter not loaded in the server -> modeled error, not a 500", code(lambda: br.converse(modelId=cm, messages=[{"role": "user", "content": [{"text": "t"}]}])) not in (None, "InternalServerException"))
check("llm_runtime.lora_args picks up the written adapter (mounted at scale 0)", llm_runtime.lora_args(ADIR) == ["--lora-scaled", f"/adapters/{mid}.gguf:0"])
llm.set_backend(stub, None, "stub-model")
# reload persistence
tc._CHAT.clear(); tc._JOBS.clear(); ctl._JOBS.clear(); ctl._CUSTOM.clear(); ctl._REH["done"] = False
check("bedrock: reload keeps the custom chat model + invocation", [m["modelName"] for m in b.list_custom_models()["modelSummaries"]] == ["tickets1-m"]
      and json.loads(br.invoke_model(modelId=cm, body=json.dumps({"prompt": "again"}))["body"].read())["adapterId"] == mid)

# ================= Bedrock cancel =================
t0 = time.time()
jb = mk("tickets-cancel", hp={"epochCount": "10", "batchSize": "2"})
wait(lambda: len((araw(jb).get("vyomiTraining") or {}).get("steps") or []), lambda n: n >= 2, 300)
b.stop_model_customization_job(jobIdentifier=jb)
jid_ = jb.rsplit("/", 1)[1]
proc = tc._JOBS[jid_]["_proc"]
time.sleep(2)
check("bedrock: stop -> Stopped, trainer process is killed, no adapter published", araw(jb)["status"] == "Stopped" and proc.poll() is not None and araw(jb)["vyomiTraining"]["status"] == "Stopped"
      and not tc.has_model(tc._JOBS[jid_]["model_id"]), (proc.poll(), araw(jb)["status"]))

# ================= Vertex tuningJobs (REST) =================
V = f"{URL}/v1/projects/vyomi-project/locations/us-central1"
st, tj = rest("POST", V + "/tuningJobs", {"baseModel": BASE, "tunedModelDisplayName": "tickets-vtx", "supervisedTuningSpec": {"trainingDatasetUri": "s3://train-data/tickets-small.jsonl", "hyperParameters": {"epochCount": "2", "loraRank": "4"}}})
check("vertex: create tuningJob on a chat base", st == 200 and tj["name"].startswith("projects/vyomi-project/locations/us-central1/tuningJobs/"), tj)
vj = wait(lambda: rest("GET", f"{URL}/v1/{tj['name']}")[1], lambda r: r["state"] in ("JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED"))
check("vertex: SUCCEEDED, lora-peft record with per-step loss + held-out", vj["state"] == "JOB_STATE_SUCCEEDED" and vj["vyomiTraining"]["engine"] == "lora-peft" and len(vj["vyomiTraining"]["steps"]) >= 10
      and vj["vyomiTraining"]["heldOut"]["perplexity"] < vj["vyomiTraining"]["heldOut"]["baselinePerplexity"], vj.get("error") or vj)
ep = vj["tunedModel"]["endpoint"]
llm.set_backend(stub, None, "stub-model")
st, pr = rest("POST", f"{URL}/v1/{ep}:predict", {"instances": [{"prompt": "ticket one"}, {"messages": [{"role": "user", "content": "ticket two"}]}], "parameters": {"maxOutputTokens": 16}})
check("vertex: tuned endpoint :predict -> generations with adapter + vyomiTrained", st == 200 and pr["vyomiTrained"] and len(pr["predictions"]) == 2 and pr["predictions"][0]["content"].startswith("category=") and CALLS[-1]["lora"] is not None, pr)
st, gc = rest("POST", f"{URL}/v1/{ep}:generateContent", {"contents": [{"role": "user", "parts": [{"text": "ticket three"}]}]})
check("vertex: tuned endpoint :generateContent -> candidates + usageMetadata + vyomiTrained", st == 200 and gc["candidates"][0]["content"]["parts"][0]["text"].startswith("category=") and gc["vyomiTrained"] is True
      and gc["usageMetadata"]["totalTokenCount"] == 17, gc)
check("vertex: bad instance -> 400", rest("POST", f"{URL}/v1/{ep}:predict", {"instances": [{"nope": 1}]})[0] == 400)

# ================= Azure OpenAI (real openai SDK) =================
try:
    from openai import AzureOpenAI
except ImportError:
    AzureOpenAI = None
    print("[SKIP] openai SDK not installed (pip install --target <dir> openai)")
if AzureOpenAI:
    SUB = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
    A = SUB + "/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/aoai1"
    rest("PUT", URL + SUB + "/resourcegroups/rg1?api-version=2021-04-01", {"location": "eastus"})
    rest("PUT", URL + A + "?api-version=2024-10-01", {"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {"customSubDomainName": "aoai1"}})
    oc = AzureOpenAI(azure_endpoint=URL, api_key="k", api_version="2024-10-21", max_retries=0)
    f = oc.files.create(file=("tickets.jsonl", jl(sample_data.rows(40, seed=13)), "application/jsonl"), purpose="fine-tune")
    fj = oc.fine_tuning.jobs.create(model=BASE, training_file=f.id, suffix="tickets", hyperparameters={"n_epochs": 2})
    aj = wait(lambda: oc.fine_tuning.jobs.retrieve(fj.id), lambda j: j.status in ("succeeded", "failed", "cancelled"))
    check("azure: fine_tuning.jobs succeeded with ft: model (lora-peft)", aj.status == "succeeded" and aj.fine_tuned_model.startswith(f"ft:{BASE}:tickets:") and aj.model_extra["vyomiTraining"]["engine"] == "lora-peft", aj.model_extra.get("error") or aj)
    evs = [e for e in oc.fine_tuning.jobs.list_events(fj.id).data if e.type == "metrics"]
    check("azure: events carry per-step training loss", len(evs) >= 10 and all("train_loss" in e.data for e in evs), len(evs))
    rr_ = rest("PUT", URL + A + "/deployments/tickets-ft?api-version=2024-10-01", {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": aj.fine_tuned_model, "version": "1"}}})
    check("azure: ARM deployment of the fine-tuned model", rr_[0] in (200, 201), rr_)
    cc = oc.chat.completions.create(model="tickets-ft", messages=[{"role": "user", "content": "ticket four"}], max_tokens=20)
    check("azure: chat/completions on the ft deployment -> adapter applied, vyomiTrained + adapter id", cc.choices[0].message.content.startswith("category=") and cc.model_extra["vyomiTrained"] is True
          and cc.model_extra["vyomiAdapter"] == "azft-" + fj.id[6:] and CALLS[-1]["lora"]["name"] == "azft-" + fj.id[6:] and cc.usage.prompt_tokens == 11, cc)
    check("azure: stream=true on the fine-tuned model -> 400", rest("POST", URL + "/openai/deployments/tickets-ft/chat/completions?api-version=2024-10-21", {"messages": [{"role": "user", "content": "x"}], "stream": True})[0] in (400, 401))

for d in os.listdir(ADIR):
    os.remove(os.path.join(ADIR, d))
print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
