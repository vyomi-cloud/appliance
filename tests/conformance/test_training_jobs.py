"""REAL head training behind the three clouds' model-customization APIs (lane trainengine), through real SDKs / REST.
Bedrock: boto3 create/get/list/stop_model_customization_job + invoke_model/converse on the custom-model ARN.
Vertex: tuningJobs create/get/list/cancel + endpoint :predict (plain REST, as the aiplatform client sends it).
Azure OpenAI: the real `openai` SDK (AzureOpenAI) files.create + fine_tuning.jobs.* + chat.completions on the fine-tuned deployment.
Embedder here = llm_core's labelled vyomi-hash-embed fallback (no model is running), so this proves plumbing + real learning on held-out rows.
Run: PYTHONPATH=.:<openai-pkgs> /private/tmp/ai-probe-venv13/bin/python tests/conformance/test_training_jobs.py"""
import asyncio, json, os, random, socket, sys, threading, time, urllib.request, urllib.error

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
os.environ.pop("VYOMI_LLM_ENDPOINT", None)
os.environ["VYOMI_LLM_DISABLE"] = "1"
os.environ.setdefault("CLOUDLEARN_STATE_FILE", "/tmp/training-jobs-test.sqlite3")
import anyio, boto3, uvicorn  # noqa: E402
from botocore.config import Config  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from core import wire_ingress, training_core as tc, bedrock_ctl_core as ctl  # noqa: E402

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

# ---- data: 4 intents, shared noisy vocabulary + 8% label noise, so held-out accuracy is real (not 100% by construction) ----
rnd = random.Random(5)
CORE = {"billing": "invoice refund charge payment card bill".split(), "shipping": "package delivery courier tracking parcel shipped".split(),
        "login": "password signin locked account reset token".split(), "cancel": "cancel terminate unsubscribe stop subscription close".split()}
POOL = "please today urgent hello thanks help need my the with about order".split()


def rows(n_each=70, noise=0.08):
    out = []
    for lab, words in CORE.items():
        for _ in range(n_each):
            ws = rnd.sample(words, 2) + rnd.sample(POOL, 3)
            rnd.shuffle(ws)
            out.append({"text": " ".join(ws), "label": lab if rnd.random() > noise else rnd.choice(list(CORE))})
    rnd.shuffle(out)
    return out


def jl(rs):
    return "\n".join(json.dumps(r) for r in rs).encode()


def wait(fn, done, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = fn()
        if done(r):
            return r
        time.sleep(0.15)
    return fn()


s3.create_bucket(Bucket="train-data")
s3.put_object(Bucket="train-data", Key="intents.jsonl", Body=jl(rows()))
PRIOR = {"epochCount": "8", "taskType": "classifier"}

# ================= Bedrock =================
def mk(name, base="nomic-embed-text", data="s3://train-data/intents.jsonl", hp=PRIOR, ctype="FINE_TUNING"):
    return b.create_model_customization_job(jobName=name, customModelName=name + "-m", roleArn=ROLE, baseModelIdentifier=base, customizationType=ctype,
                                             trainingDataConfig={"s3Uri": data}, outputDataConfig={"s3Uri": "s3://train-data/out/"}, hyperParameters=hp)["jobArn"]

def araw(arn):
    """Raw REST read (boto3 drops the Vyomi extension key vyomiTraining): SigV4-looking header routes it to Bedrock."""
    h = {"authorization": "AWS4-HMAC-SHA256 Credential=AKIAFAKE/20260101/us-east-1/bedrock/aws4_request, SignedHeaders=host, Signature=0"}
    return json.loads(urllib.request.urlopen(urllib.request.Request(f"{URL}/model-customization-jobs/{arn.rsplit('/', 1)[1]}", headers=h)).read())


ja = mk("intent1")
raw = lambda: araw(ja)
seen = set()
def poll():
    v = raw().get("vyomiTraining") or {}
    seen.add(v.get("epoch", 0)); return b.get_model_customization_job(jobIdentifier=ja)
g = wait(poll, lambda r: r["status"] != "InProgress")
vt = raw()["vyomiTraining"]
check("bedrock: job runs for real then Completed", g["status"] == "Completed" and vt["status"] == "Completed" and vt["engine"] == "head-py", g)
check("bedrock: per-epoch metrics, loss falls", len(vt["metrics"]) == 8 and vt["metrics"][-1]["loss"] < vt["metrics"][0]["loss"] and len({m["loss"] for m in vt["metrics"]}) == 8, vt["metrics"][:2])
check("bedrock: held-out accuracy beats the baseline", vt["heldOut"]["accuracy"] > vt["heldOut"]["baseline"] + 0.3, vt["heldOut"])
check("bedrock: trainingMetrics.trainingLoss via boto3", abs(g["trainingMetrics"]["trainingLoss"] - vt["metrics"][-1]["loss"]) < 1e-6, g.get("trainingMetrics"))
check("bedrock: states advanced through progress (observed live epochs)", len(seen) >= 1)
cm = g["outputModelArn"]
check("bedrock: custom model listed + get", [m["modelName"] for m in b.list_custom_models()["modelSummaries"]] == ["intent1-m"] and b.get_custom_model(modelIdentifier=cm)["baseModelArn"].endswith("nomic-embed-text"))
key = vt["artifact"].split("s3://vyomi-models/")[1]
head = json.loads(s3.get_object(Bucket="vyomi-models", Key=key)["Body"].read())
check("bedrock: head.json checkpointed in the object store + outputDataConfig", head["kind"] == "classifier" and head["embedder"] and
      s3.list_objects_v2(Bucket="train-data", Prefix="out/")["KeyCount"] == 1)
inv = json.loads(br.invoke_model(modelId=cm, body=json.dumps({"task": "classify", "text": "where is my package courier tracking"}))["body"].read())
check("bedrock: InvokeModel classify -> label + scores + vyomiTrained", inv["label"] == "shipping" and inv["vyomiTrained"] and set(inv["scores"]) == set(CORE), inv)
cv = br.converse(modelId=cm, messages=[{"role": "user", "content": [{"text": "reset my password locked signin"}]}])
check("bedrock: Converse classifies last user message", cv["output"]["message"]["content"][0]["text"] == "login" and cv["additionalModelResponseFields"]["vyomiTrained"] is True, cv)
check("bedrock: bad invoke body -> ValidationException", code(lambda: br.invoke_model(modelId=cm, body=json.dumps({"task": "score", "query": "a", "document": "b"}))) == "ValidationException")
# reload persistence: wipe every in-memory registry; the head and custom model come back from the object store
tc._HEADS.clear(); tc._JOBS.clear(); ctl._JOBS.clear(); ctl._CUSTOM.clear(); ctl._REH["done"] = False
check("bedrock: reload keeps the custom model + invocation", [m["modelName"] for m in b.list_custom_models()["modelSummaries"]] == ["intent1-m"]
      and json.loads(br.invoke_model(modelId=cm, body=json.dumps({"task": "classify", "text": "cancel my subscription terminate"}))["body"].read())["label"] == "cancel")

# caps / validation (modeled ValidationException, no job created)
s3.put_object(Bucket="train-data", Key="big.jsonl", Body=jl(rows(n_each=501)))
s3.put_object(Bucket="train-data", Key="few.jsonl", Body=jl(rows(n_each=2)))
s3.put_object(Bucket="train-data", Key="many-labels.jsonl", Body=jl([{"text": f"t{i} word", "label": f"L{i % 21}"} for i in range(100)]))
s3.put_object(Bucket="train-data", Key="huge.jsonl", Body=jl([{"text": "x" * 3000, "label": "a" if i % 2 else "b"} for i in range(1900)]))
s3.put_object(Bucket="train-data", Key="badshape.jsonl", Body=b'{"foo":1}\n' * 20)
for nm, data, why in (("big", "s3://train-data/big.jsonl", "2000 rows"), ("few", "s3://train-data/few.jsonl", "min rows"), ("lab", "s3://train-data/many-labels.jsonl", "20 labels"),
                      ("huge", "s3://train-data/huge.jsonl", "5 MB"), ("shape", "s3://train-data/badshape.jsonl", "row shape"), ("missing", "s3://train-data/nope.jsonl", "missing object")):
    check(f"bedrock: caps/validation rejects {why}", code(lambda: mk("cap-" + nm, data=data)) == "ValidationException")
check("bedrock: bad customizationType on trainable base rejected", code(lambda: mk("ct", ctype="CONTINUED_PRE_TRAINING")) == "ValidationException")
check("bedrock: rejected jobs left no records", all(not j["jobName"].startswith("cap-") for j in b.list_model_customization_jobs()["modelCustomizationJobSummaries"]))

# cancel
s3.put_object(Bucket="train-data", Key="long.jsonl", Body=jl(rows(n_each=400)))
jc = mk("cancel1", data="s3://train-data/long.jsonl", hp={"epochCount": "50", "taskType": "router"})
time.sleep(0.4)
b.stop_model_customization_job(jobIdentifier=jc)
gc = wait(lambda: b.get_model_customization_job(jobIdentifier=jc), lambda r: r["status"] == "Stopped", 20)
time.sleep(1.0)
cj = araw(jc)
check("bedrock: StopModelCustomizationJob -> Stopped, training thread stops, no custom model", gc["status"] == "Stopped" and cj["vyomiTraining"]["status"] == "Stopped"
      and cj["vyomiTraining"]["epoch"] < 50 and all(m["modelName"] != "cancel1-m" for m in b.list_custom_models()["modelSummaries"]), cj["vyomiTraining"])

# non-trainable base keeps the honest metadata-only behaviour
jn = mk("meta1", base="amazon.nova-lite-v1:0", hp={"epochCount": "1"})
time.sleep(2.3)
gn = b.get_model_customization_job(jobIdentifier=jn)
check("bedrock: non-trainable base still metadata-only and says so", gn["status"] == "Completed" and "Metadata only" in araw(jn)["vyomiNote"] and "vyomiTraining" not in araw(jn))
check("bedrock: stop on finished job -> ConflictException", code(lambda: b.stop_model_customization_job(jobIdentifier=jn)) == "ConflictException")

# reranker head
docs = {"billing": "refund the invoice charge payment", "shipping": "the package courier delivery tracking", "login": "reset password signin account locked", "cancel": "cancel subscription terminate close"}
rr = [{"query": " ".join(rnd.sample(CORE[l], 2) + rnd.sample(POOL, 2)), "positive": docs[l] + " " + rnd.choice(POOL), "negative": docs[rnd.choice([x for x in CORE if x != l])] + " " + rnd.choice(POOL)} for l in CORE for _ in range(60)]
s3.put_object(Bucket="train-data", Key="rerank.jsonl", Body=jl(rr))
jr = mk("rerank1", data="s3://train-data/rerank.jsonl", hp={"epochCount": "12"})
gr = wait(lambda: b.get_model_customization_job(jobIdentifier=jr), lambda r: r["status"] != "InProgress")
vr = araw(jr)["vyomiTraining"]
sc = lambda q, d: json.loads(br.invoke_model(modelId=gr["outputModelArn"], body=json.dumps({"task": "score", "query": q, "document": d}))["body"].read())["score"]
check("bedrock: reranker trains, beats zero-shot cosine baseline", gr["status"] == "Completed" and vr["taskType"] == "reranker" and vr["heldOut"]["accuracy"] >= vr["heldOut"]["baseline"], vr["heldOut"])
check("bedrock: reranker score separates relevant doc", sc("invoice refund charge", docs["billing"]) > sc("invoice refund charge", docs["login"]))

# ================= Vertex tuningJobs (REST) =================
V = f"{URL}/v1/projects/vyomi-project/locations/us-central1"
def rest(method, url, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None, headers={"content-type": "application/json", "authorization": "Bearer x"})
    try:
        return 200, json.loads(urllib.request.urlopen(req).read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

st, tj = rest("POST", V + "/tuningJobs", {"baseModel": "all-minilm-l6-v2", "tunedModelDisplayName": "intents-vtx", "supervisedTuningSpec": {"trainingDatasetUri": "gs://train-data/intents.jsonl", "hyperParameters": {"epochCount": "8"}}})
check("vertex: create tuningJob", st == 200 and tj["name"].startswith("projects/vyomi-project/locations/us-central1/tuningJobs/"), tj)
seen_states = set()
def vpoll():
    _, r = rest("GET", f"{URL}/v1/{tj['name']}"); seen_states.add(r["state"]); return r
vj = wait(vpoll, lambda r: r["state"] in ("JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED"))
check("vertex: job SUCCEEDED with tunedModel + endpoint, real metrics", vj["state"] == "JOB_STATE_SUCCEEDED" and vj["tunedModel"]["endpoint"] and len(vj["vyomiTraining"]["metrics"]) == 8
      and vj["vyomiTraining"]["heldOut"]["accuracy"] > vj["vyomiTraining"]["heldOut"]["baseline"] + 0.3, vj)
check("vertex: list tuningJobs", [j["name"] for j in rest("GET", V + "/tuningJobs")[1]["tuningJobs"]] == [tj["name"]])
st, pr = rest("POST", f"{URL}/v1/{vj['tunedModel']['endpoint']}:predict", {"instances": [{"text": "package delivery courier parcel please"}, {"text": "refund invoice charge billing"}]})
check("vertex: tuned endpoint :predict -> labels + vyomiTrained", st == 200 and [p["label"] for p in pr["predictions"]] == ["shipping", "billing"] and pr["vyomiTrained"] and pr["predictions"][0]["vyomiTrained"], pr)
check("vertex: predict bad instance -> 400", rest("POST", f"{URL}/v1/{vj['tunedModel']['endpoint']}:predict", {"instances": [{"nope": 1}]})[0] == 400)
st, long_ = rest("POST", V + "/tuningJobs?tuningJobId=cx1", {"baseModel": "vyomi.head.demo", "supervisedTuningSpec": {"trainingDatasetUri": "gs://train-data/long.jsonl", "hyperParameters": {"epochCount": "50"}}})
time.sleep(0.4)
st2, _ = rest("POST", f"{URL}/v1/{long_['name']}:cancel", {})
st3, cj = rest("GET", f"{URL}/v1/{long_['name']}")
time.sleep(1.0)
check("vertex: cancel -> JOB_STATE_CANCELLED and training stops", st2 == 200 and cj["state"] == "JOB_STATE_CANCELLED" and rest("GET", f"{URL}/v1/{long_['name']}")[1]["vyomiTraining"]["epoch"] < 50)
check("vertex: caps rejection -> 400 INVALID_ARGUMENT, nothing created", rest("POST", V + "/tuningJobs", {"baseModel": "all-minilm-l6-v2", "supervisedTuningSpec": {"trainingDatasetUri": "gs://train-data/big.jsonl"}})[0] == 400
      and rest("POST", V + "/tuningJobs", {"baseModel": "all-minilm-l6-v2", "supervisedTuningSpec": {}})[0] == 400 and len(rest("GET", V + "/tuningJobs")[1]["tuningJobs"]) == 2)
st, mj = rest("POST", V + "/tuningJobs?tuningJobId=meta", {"baseModel": "gemini-2.0-flash-001", "supervisedTuningSpec": {"trainingDatasetUri": "gs://x/y.jsonl"}})
check("vertex: non-trainable base keeps metadata-only behaviour and says so", st == 200 and "Metadata only" in mj.get("vyomiNote", ""))

# ================= Azure OpenAI (real openai SDK) =================
try:
    from openai import AzureOpenAI, BadRequestError
except ImportError:
    AzureOpenAI = None
    print("[SKIP] openai SDK not installed (pip install --target <dir> openai)")
if AzureOpenAI:
    ar = lambda m, p, body=None, hd=None: rest(m, URL + p, body)
    SUB = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
    A = SUB + "/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/aoai1"
    rest("PUT", URL + SUB + "/resourcegroups/rg1?api-version=2021-04-01", {"location": "eastus"})
    rest("PUT", URL + A + "?api-version=2024-10-01", {"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {"customSubDomainName": "aoai1"}})
    oc = AzureOpenAI(azure_endpoint=URL, api_key="k", api_version="2024-10-21", max_retries=0)
    f = oc.files.create(file=("intents.jsonl", jl(rows())), purpose="fine-tune")
    check("azure: files.create (multipart) -> file object", f.id.startswith("file-") and f.purpose == "fine-tune" and f.bytes > 1000 and oc.files.retrieve(f.id).id == f.id)
    fj = oc.fine_tuning.jobs.create(model="all-minilm-l6-v2", training_file=f.id, suffix="intents", hyperparameters={"n_epochs": 8})
    check("azure: fine_tuning.jobs.create -> fine_tuning.job", fj.id.startswith("ftjob-") and fj.object == "fine_tuning.job" and fj.status in ("queued", "running"), fj)
    seen_ev = set()
    def apoll():
        j = oc.fine_tuning.jobs.retrieve(fj.id); seen_ev.add(j.status); return j
    aj = wait(apoll, lambda j: j.status in ("succeeded", "failed", "cancelled"))
    check("azure: job succeeded with fine_tuned_model", aj.status == "succeeded" and aj.fine_tuned_model.startswith("ft:all-minilm-l6-v2:intents:") and aj.finished_at, aj)
    evs = list(oc.fine_tuning.jobs.list_events(fj.id).data)
    mets = [e for e in evs if e.type == "metrics"]
    check("azure: events carry per-epoch metrics", len(mets) == 8 and len({e.data["train_loss"] for e in mets}) == 8 and any("New fine-tuned model created" in e.message for e in evs))
    check("azure: jobs.list", [j.id for j in oc.fine_tuning.jobs.list().data] == [fj.id])
    dn = aj.fine_tuned_model
    rr_ = rest("PUT", URL + A + "/deployments/intent-ft?api-version=2024-10-01", {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": dn, "version": "1"}}})
    check("azure: ARM deployment of the fine-tuned model", rr_[0] in (200, 201), rr_)
    cc = oc.chat.completions.create(model="intent-ft", messages=[{"role": "user", "content": "cancel my subscription please terminate"}])
    check("azure: chat/completions on the fine-tuned deployment -> label, vyomiTrained", cc.choices[0].message.content == "cancel" and cc.model_extra.get("vyomiTrained") is True, cc)
    tc._HEADS.clear()
    check("azure: reload keeps the fine-tuned model", oc.chat.completions.create(model="intent-ft", messages=[{"role": "user", "content": "invoice refund charge"}]).choices[0].message.content == "billing")
    lf = oc.files.create(file=("long.jsonl", jl(rows(n_each=400))), purpose="fine-tune")
    lj = oc.fine_tuning.jobs.create(model="all-minilm-l6-v2", training_file=lf.id, hyperparameters={"n_epochs": 50})
    time.sleep(0.4)
    cj_ = oc.fine_tuning.jobs.cancel(lj.id)
    time.sleep(1.0)
    check("azure: cancel -> cancelled, training stops", cj_.status == "cancelled" and oc.fine_tuning.jobs.retrieve(lj.id).vyomiTraining["epoch"] < 50 if hasattr(oc.fine_tuning.jobs.retrieve(lj.id), "vyomiTraining") else cj_.status == "cancelled")
    bf = oc.files.create(file=("big.jsonl", jl(rows(n_each=501))), purpose="fine-tune")
    try:
        oc.fine_tuning.jobs.create(model="all-minilm-l6-v2", training_file=bf.id); ok = False
    except BadRequestError as e:
        ok = "2000" in str(e)
    check("azure: caps rejection -> 400 BadRequestError", ok)
    try:
        oc.fine_tuning.jobs.create(model="gpt-4o-mini", training_file=f.id); ok = False
    except BadRequestError as e:
        ok = "cannot be fine-tuned by Vyomi" in str(e)
    check("azure: non-trainable base -> clear 400 (not a fake job)", ok)

print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
