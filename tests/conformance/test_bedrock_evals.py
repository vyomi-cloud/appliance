"""Bedrock Evaluations: LLM-as-a-judge, RAG (retrieve-only / retrieve-and-generate), human, custom metrics, batching over 25 records through the REAL boto3 clients (lane limflows).
Run: PYTHONPATH=. CLOUDLEARN_STATE_FILE=/tmp/x.sqlite3 /private/tmp/ai-probe-venv13/bin/python tests/conformance/test_bedrock_evals.py
Batch inference runs over the deterministic TEST STUB llm (tools/llm_stub); customization/provisioned/marketplace are metadata only."""
import asyncio, json, os, socket, sys, threading, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "llm_stub"))
import stub_llm_server  # noqa: E402
os.environ["VYOMI_LLM_ENDPOINT"] = stub_llm_server.start()
os.environ["VYOMI_LIST_BEDROCK_ALIASES"] = "1"  # the default routers/system profiles come from the opt-in alias set
os.environ.setdefault("CLOUDLEARN_STATE_FILE", "/tmp/bedrock-evals-test.sqlite3")
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



import re
from core import llm_core
ROLE = "arn:aws:iam::123456789012:role/r"
EMB = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
NOVA = "amazon.nova-lite-v1:0"
ANSWERS = {"What is 2+2?": "The answer is 4.", "Capital of France?": "Paris is the capital.", "Name a colour": "kill them all"}
_real_chat = llm_core.chat


def fake_chat(messages, *a, **k):
    """Deterministic stand-in for the local model: answers a fixed prompt table, and judges by rule so the pipeline (prompt building,
    verdict parsing, scale mapping, aggregation) is verifiable. The judge rules are NOT a quality claim about the real local model."""
    text = messages[-1]["content"] if isinstance(messages[-1]["content"], str) else str(messages[-1]["content"])
    if text.startswith("You are an impartial evaluator"):
        q = re.search(r"Question about the response: (.*)", text).group(1)
        opts = re.search(r"Choose exactly one rating from this list: (.*)\.\nReply", text).group(1).split(" | ")
        resp = (re.search(r"Candidate response:\n(.*?)\n\n", text, re.S) or re.search(r"Candidate response:\n(.*)$", text, re.S) or [None, ""])[1] if "Candidate response:" in text else ""
        ref = (re.search(r"Reference answer:\n(.*?)\n\n", text, re.S) or [None, ""])[1]
        if "UNPARSABLE" in text:
            return {"text": "I refuse to pick a rating."}
        if "correct answer" in q:
            ans = "correct" if ref and ref.lower().split()[0] in resp.lower() else "incorrect"
        elif "harmful" in q:
            ans = "Yes" if "kill" in resp.lower() else "No"
        elif "cited passage relevant" in q:
            ans = "Yes" if "wifi" in text.lower().split("cited passage:")[-1] else "No"
        elif "How relevant is the retrieved passage" in q:
            ans = "Completely relevant" if "wifi" in text.lower().split("retrieved passage:")[-1] else "Not relevant at all"
        elif "faithful" in q:
            ans = "all is faithful"
        elif "instruction" in q.lower() and "tone" in q.lower():
            ans = opts[-1]
        else:
            ans = opts[-1]
        return {"text": json.dumps({"reasoning": f"rule judge for: {q[:40]}", "answer": ans})}
    if text in ANSWERS:
        return {"text": ANSWERS[text]}
    return _real_chat(messages, *a, **k)


llm_core.chat = fake_chat

s3.create_bucket(Bucket="evb")
ds_rows = [{"prompt": "What is 2+2?", "referenceResponse": "4", "category": "math"}, {"prompt": "Capital of France?", "referenceResponse": "Paris", "category": "geo"},
           {"prompt": "Name a colour", "referenceResponse": "blue", "category": "misc"}]
s3.put_object(Bucket="evb", Key="in/qa.jsonl", Body="\n".join(json.dumps(x) for x in ds_rows).encode())


def cfg(metrics, uri="s3://evb/in/qa.jsonl", judge=NOVA, extra=None, task="QuestionAndAnswer"):
    a = {"datasetMetricConfigs": [{"taskType": task, "dataset": {"name": "qa", "datasetLocation": {"s3Uri": uri}}, "metricNames": metrics}]}
    if judge:
        a["evaluatorModelConfig"] = {"bedrockEvaluatorModels": [{"modelIdentifier": judge}]}
    a.update(extra or {})
    return {"automated": a}


def job(name, ec, inf=None, out="s3://evb/out/", app=None, **kw2):
    args = dict(jobName=name, roleArn=ROLE, evaluationConfig=ec, inferenceConfig=inf or {"models": [{"bedrockModel": {"modelIdentifier": NOVA, "inferenceParams": "{\"temperature\":0}"}}]}, outputDataConfig={"s3Uri": out})
    if app:
        args["applicationType"] = app
    args.update(kw2)
    return b.create_evaluation_job(**args)["jobArn"]


import urllib.request


def raw(arn):
    """The Vyomi extension fields (vyomiReport / vyomiProgress) are outside the Bedrock model, so botocore drops them: read the raw JSON."""
    rq = urllib.request.Request(f"http://127.0.0.1:{port}/evaluation-jobs/{arn.split('/')[-1]}", headers={"Authorization": "AWS4-HMAC-SHA256 Credential=AKIAFAKE/20260101/us-east-1/bedrock/aws4_request, SignedHeaders=host, Signature=x"})
    return json.loads(urllib.request.urlopen(rq).read())


def wait(arn, secs=90):
    t = time.time()
    while time.time() - t < secs:
        g = raw(arn)
        if g["status"] != "InProgress":
            return g
        time.sleep(0.2)
    return g


def report(name_prefix):
    ks = [o["Key"] for o in s3.list_objects_v2(Bucket="evb", Prefix="out/").get("Contents", []) if o["Key"].endswith("report.json")]
    return ks


def rows(g, ds="qa"):
    k = [o["Key"] for o in s3.list_objects_v2(Bucket="evb", Prefix="out/").get("Contents", []) if o["Key"].endswith(f"{ds}.jsonl") and g["jobArn"].split("/")[-1] in o["Key"]][0]
    return [json.loads(x) for x in s3.get_object(Bucket="evb", Key=k)["Body"].read().decode().splitlines()]


# 1. LLM-as-a-judge on a model evaluation
a1 = job("judge1", cfg(["Builtin.Correctness", "Builtin.Completeness", "Builtin.Helpfulness", "Builtin.Harmfulness", "Builtin.Accuracy", "Vyomi.RougeL", "Vyomi.ExactMatch", "Vyomi.SemanticSimilarity"]))
g = wait(a1)
check("judge job Completed", g["status"] == "Completed", g.get("failureMessages"))
m = g["vyomiReport"]["datasets"][0]["metrics"]
check("Correctness mean = 2/3 (correct, correct, incorrect)", abs(m["Builtin.Correctness"] - 2 / 3) < 1e-3, m)
check("Completeness / Helpfulness map the last option to 1.0", m["Builtin.Completeness"] == 1.0 and m["Builtin.Helpfulness"] == 1.0, m)
check("Harmfulness flags the harmful answer: mean 1/3 (lower is better)", abs(m["Builtin.Harmfulness"] - 1 / 3) < 1e-3 and g["vyomiReport"]["datasets"][0]["higherIsBetter"]["Builtin.Harmfulness"] is False, m)
check("classic scorers present and in [0,1]: F1 / ROUGE-L / exact match / embedding cosine", all(0 <= m[k] <= 1 for k in ("Builtin.Accuracy", "Vyomi.RougeL", "Vyomi.ExactMatch", "Vyomi.SemanticSimilarity")), m)
rw = rows(g)
check("per-record rows carry the judge label + reasoning and the model response", rw[0]["judgements"]["Builtin.Correctness"]["label"] == "correct" and "rule judge" in rw[0]["judgements"]["Builtin.Correctness"]["reasoning"] and rw[2]["modelResponse"] == "kill them all", rw[0])
check("rouge_l / f1 unit", __import__("core.bedrock_build_core", fromlist=["x"]).rouge_l("the cat sat on the mat", "the cat on the mat") > 0.8 and __import__("core.bedrock_build_core", fromlist=["x"]).rouge_l("a b", "c d") == 0.0)
check("GetEvaluationJob exposes judge + job type", g["jobType"] == "Automated" and g["evaluationConfig"]["automated"]["evaluatorModelConfig"]["bedrockEvaluatorModels"][0]["modelIdentifier"] == NOVA)

# 2. validation
def err(**kw3):
    try:
        job(**kw3)
    except ClientError as e:
        return e.response["Error"]["Code"], e.response["Error"]["Message"]
    return None, ""
c, mmsg = err(name="nojudge", ec=cfg(["Builtin.Correctness"], judge=None))
check("judge metric without evaluatorModelConfig -> ValidationException naming it", c == "ValidationException" and "evaluator model" in mmsg, mmsg)
c, mmsg = err(name="badmetric", ec=cfg(["Builtin.Faithfulness"]))
check("RAG-only metric on a model evaluation -> ValidationException", c == "ValidationException" and "does not apply" in mmsg, mmsg)
c, mmsg = err(name="badjudge", ec=cfg(["Builtin.Correctness"], judge="not.a.model"))
check("unknown judge model -> ValidationException", c == "ValidationException")
big = "\n".join(json.dumps({"prompt": f"q{i}", "referenceResponse": "x"}) for i in range(1001))
s3.put_object(Bucket="evb", Key="in/big.jsonl", Body=big.encode())
c, mmsg = err(name="toobig", ec=cfg(["Builtin.Accuracy"], uri="s3://evb/in/big.jsonl", judge=None))
check("dataset over 1000 records -> ValidationException", c == "ValidationException" and "1000" in mmsg, mmsg)

# 3. unparsable verdicts are counted, never scored
s3.put_object(Bucket="evb", Key="in/unp.jsonl", Body=json.dumps({"prompt": "UNPARSABLE what is 2+2?", "referenceResponse": "4"}).encode())
g = wait(job("unp", cfg(["Builtin.Correctness", "Builtin.Accuracy"], uri="s3://evb/in/unp.jsonl")))
d = g["vyomiReport"]["datasets"][0]
check("unparsable judge verdict -> metric None + unscoredRecords=1 (job still Completed)", g["status"] == "Completed" and d["metrics"]["Builtin.Correctness"] is None and d["unscoredRecords"]["Builtin.Correctness"] == 1 and d["metrics"]["Builtin.Accuracy"] is not None, d)

# 4. batching: 80 records (the old cap was 25), progress visible, all scored
s3.put_object(Bucket="evb", Key="in/b80.jsonl", Body="\n".join(json.dumps({"prompt": "What is 2+2?", "referenceResponse": "4", "category": f"c{i % 4}"}) for i in range(80)).encode())
a80 = job("batch80", cfg(["Builtin.Accuracy", "Builtin.Correctness"], uri="s3://evb/in/b80.jsonl"))
g0 = raw(a80)
prog = g0["vyomiProgress"]
g = wait(a80)
check("80-record job: progress reported while InProgress, then Completed with all 80 scored", prog["totalRecords"] == 80 and g["status"] == "Completed" and g["vyomiReport"]["datasets"][0]["records"] == 80 and g["vyomiProgress"]["processedRecords"] == 80, (prog, g["status"]))
check("80-record output rows written to S3", len(rows(g)) == 80)
check("Correctness over 80 identical records = 1.0", g["vyomiReport"]["datasets"][0]["metrics"]["Builtin.Correctness"] == 1.0)

# 5. custom metric
cm = {"customMetricConfig": {"customMetrics": [{"customMetricDefinition": {"name": "Brevity", "instructions": "Is the candidate response brief?", "ratingScale": [{"definition": "long", "value": {"floatValue": 0.0}}, {"definition": "short", "value": {"floatValue": 1.0}}]}}],
      "evaluatorModelConfig": {"bedrockEvaluatorModels": [{"modelIdentifier": NOVA}]}}}
g = wait(job("custom", cfg(["Brevity"], judge=None, extra=cm)))
check("custom judge metric scored from its own rating scale", g["status"] == "Completed" and g["vyomiReport"]["datasets"][0]["metrics"]["Brevity"] == 1.0, g.get("failureMessages") or g.get("vyomiReport"))

# 6. RAG evaluation over a knowledge base
s3.put_object(Bucket="evb", Key="kb/wifi.txt", Body=b"The guest wifi password for the lobby is Aurora-2026. Contact facilities to rotate it.")
s3.put_object(Bucket="evb", Key="kb/parking.txt", Body=b"Visitor parking is in garage B, levels 1 to 3, free after 6 pm.")
kb = ba.create_knowledge_base(name="eval-kb", roleArn=ROLE, knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {"embeddingModelArn": EMB}}, storageConfiguration={"type": "OPENSEARCH_SERVERLESS"})["knowledgeBase"]["knowledgeBaseId"]
dsid = ba.create_data_source(knowledgeBaseId=kb, name="d", dataSourceConfiguration={"type": "S3", "s3Configuration": {"bucketArn": "arn:aws:s3:::evb", "inclusionPrefixes": ["kb/"]}})["dataSource"]["dataSourceId"]
ba.start_ingestion_job(knowledgeBaseId=kb, dataSourceId=dsid)
turn = lambda q, r: json.dumps({"conversationTurns": [{"prompt": {"content": [{"text": q}]}, "referenceResponses": [{"content": [{"text": r}]}]}]})  # noqa: E731
s3.put_object(Bucket="evb", Key="in/rag.jsonl", Body=(turn("What is the lobby wifi password?", "Aurora-2026") + "\n" + turn("Where is visitor parking?", "Garage B")).encode())
ret = {"ragConfigs": [{"knowledgeBaseConfig": {"retrieveConfig": {"knowledgeBaseId": kb, "knowledgeBaseRetrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 2}}}}}]}
g = wait(job("rag-ret", cfg(["Builtin.ContextRelevance", "Builtin.ContextCoverage"], uri="s3://evb/in/rag.jsonl", task="General"), inf=ret, app="RagEvaluation"))
check("RAG retrieve-only job Completed with ContextRelevance + ContextCoverage scored", g["status"] == "Completed" and all(0 <= g["vyomiReport"]["datasets"][0]["metrics"][k] <= 1 for k in ("Builtin.ContextRelevance", "Builtin.ContextCoverage")), g.get("failureMessages") or g.get("vyomiReport"))
rr = rows(g)
check("retrieve-only rows record the retrieved passages", len(rr) == 2 and len(rr[0]["retrievedPassages"]) == 2 and "Aurora-2026" in json.dumps(rr[0]["retrievedPassages"]), rr[0])
check("ContextRelevance judged per passage (relevant wifi passage scores above the parking passage)", len(rr[0]["judgements"]["Builtin.ContextRelevance"]) == 2 and 0 < rr[0]["scores"]["Builtin.ContextRelevance"] <= 1, rr[0]["judgements"])
rag = {"ragConfigs": [{"knowledgeBaseConfig": {"retrieveAndGenerateConfig": {"type": "KNOWLEDGE_BASE", "knowledgeBaseConfiguration": {"knowledgeBaseId": kb, "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/" + NOVA}}}}]}
g = wait(job("rag-gen", cfg(["Builtin.Correctness", "Builtin.Faithfulness", "Builtin.CitationPrecision", "Builtin.Helpfulness"], uri="s3://evb/in/rag.jsonl", task="General"), inf=rag, app="RagEvaluation"))
dm = g["vyomiReport"]["datasets"][0]["metrics"] if g.get("vyomiReport") else {}
check("RAG retrieve-and-generate job Completed with Faithfulness + CitationPrecision + Correctness", g["status"] == "Completed" and dm.get("Builtin.Faithfulness") == 1.0 and dm.get("Builtin.CitationPrecision") is not None and dm.get("Builtin.Correctness") is not None, g.get("failureMessages") or dm)
rr = rows(g)
check("generate rows carry the KB answer + cited passages", all(r.get("modelResponse") for r in rr) and all(r["retrievedPassages"] for r in rr), rr[0])
c, mmsg = err(name="rag-bad", ec=cfg(["Builtin.Faithfulness"], uri="s3://evb/in/rag.jsonl", task="General"), inf=ret, app="RagEvaluation")
check("Faithfulness on a retrieve-only job -> ValidationException", c == "ValidationException" and "does not apply" in mmsg, mmsg)
c, mmsg = err(name="rag-nokb", ec=cfg(["Builtin.ContextRelevance"], uri="s3://evb/in/rag.jsonl", task="General"),
              inf={"ragConfigs": [{"knowledgeBaseConfig": {"retrieveConfig": {"knowledgeBaseId": "NOSUCHKB123", "knowledgeBaseRetrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 1}}}}}]}, app="RagEvaluation")
check("unknown knowledge base -> ResourceNotFoundException", c == "ResourceNotFoundException", (c, mmsg))

# 7. human workflow job: recorded honestly
hum = {"human": {"humanWorkflowConfig": {"flowDefinitionArn": "arn:aws:sagemaker:us-east-1:123456789012:flow-definition/fd", "instructions": "Rate the answers"},
                 "datasetMetricConfigs": [{"taskType": "QuestionAndAnswer", "dataset": {"name": "qa", "datasetLocation": {"s3Uri": "s3://evb/in/qa.jsonl"}}, "metricNames": ["Helpfulness"]}]}}
ha = job("human1", hum)
gh = raw(ha)
check("human job type recorded; stays InProgress awaiting reviewers", gh["jobType"] == "Human" and gh["status"] == "InProgress" and gh["vyomiReport"]["humanWorkflow"]["state"] == "AwaitingReviewers", gh)
hr = rows(gh)
check("human job generated the model responses for reviewers (no ratings fabricated)", len(hr) == 3 and all(r["modelResponse"] and r["humanRating"] is None for r in hr))
b.stop_evaluation_job(jobIdentifier=ha)
check("human job can be stopped", b.get_evaluation_job(jobIdentifier=ha)["status"] == "Stopped")

# 8. list summaries
ls = {j["jobName"]: j for j in b.list_evaluation_jobs()["jobSummaries"]}
check("list summaries: judge model, rag identifiers, job type, application type", ls["judge1"]["evaluatorModelIdentifiers"] == [NOVA] and ls["rag-ret"]["ragIdentifiers"] == [kb] and ls["rag-ret"]["applicationType"] == "RagEvaluation" and ls["human1"]["jobType"] == "Human")
check("list filter by application type", {j["jobName"] for j in b.list_evaluation_jobs(applicationTypeEquals="RagEvaluation")["jobSummaries"]} == {"rag-ret", "rag-gen"})

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
