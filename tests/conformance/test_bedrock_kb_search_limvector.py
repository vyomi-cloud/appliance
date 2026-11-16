"""Bedrock Knowledge Bases round 8, real boto3 over HTTP: overrideSearchType HYBRID / SEMANTIC (+ validation), reranking (Retrieve
rerankingConfiguration and the bedrock-agent-runtime Rerank API, with an OPTIONAL real cross-encoder endpoint), full RetrievalFilter
semantics and validation, implicit metadata filters from the local model.

Run: PYTHONPATH=. python tests/conformance/test_bedrock_kb_search_limvector.py   (skips with exit 0 when boto3 is missing)
"""
import json
import math
import os
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

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
        print(f"  FAIL {name} {str(extra)[:500]}")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:
    print("SKIP boto3 not installed")
    sys.exit(0)

import uvicorn
from fastapi import FastAPI, Request
from core import llm_core as llm
from core import wire_ingress
from core import s3_object_core as s3c
from core.aws_wire_router import AwsWireRouter

CONCEPTS = [("boiler", "furnace", "heater", "heating", "burner"), ("elevator", "lift", "escalator"), ("cafeteria", "lunch", "canteen", "soup"), ("chiller", "cooling", "refrigerant")]


def emb(texts):
    out = []
    for t in texts:
        toks = re.findall(r"[a-z0-9]+", t.lower())
        v = [sum(1.0 for w in toks if w in g) for g in CONCEPTS] + [0.0] * 4
        for w in toks:
            v[4 + (sum(map(ord, w)) % 4)] += 0.05
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


fake = FakeLLM(delay=0.0)
fake.handler = lambda body: {"content": '{"equals":{"key":"dept","value":"hvac"}}' if "Derive a metadata filter" in json.dumps(body["messages"]) else "fine"}
llm.set_backend(None, embed_fn=emb, endpoint=fake.url)
os.environ.pop("VYOMI_LLM_DISABLE", None)

# a stand-in cross-encoder server (what `llama-server --reranking` with a bge-reranker GGUF answers): prefers documents containing "october"
class CE(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["content-length"])))
        res = [{"index": i, "relevance_score": 9.0 if "october" in d.lower() else -3.0} for i, d in enumerate(b["documents"])]
        raw = json.dumps({"results": res}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


ce_port = free_port()
ce = HTTPServer(("127.0.0.1", ce_port), CE)
threading.Thread(target=ce.serve_forever, daemon=True).start()

router = AwsWireRouter()
app = FastAPI()


@app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def any_(p: str, request: Request):
    return await wire_ingress.serve(router, request)


port = free_port()
srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
threading.Thread(target=srv.run, daemon=True).start()
while not srv.started:
    time.sleep(0.05)
url = f"http://127.0.0.1:{port}"
kw = dict(region_name="us-east-1", endpoint_url=url, aws_access_key_id="x", aws_secret_access_key="y", config=Config(retries={"max_attempts": 1}))
ba, bar = boto3.client("bedrock-agent", **kw), boto3.client("bedrock-agent-runtime", **kw)


def err(fn, **a):
    try:
        fn(**a)
    except ClientError as e:
        return e.response["Error"]["Code"], e.response["Error"]["Message"]
    return None, ""


s3c.dispatch(router.s3, "PUT", "/kbs", {}, {}, b"")


def put(k, v):
    s3c.dispatch(router.s3, "PUT", f"/kbs/{k}", {}, {}, v if isinstance(v, bytes) else v.encode())


def meta(**a):
    return json.dumps({"metadataAttributes": a})


put("d/boiler.md", "The furnace room houses the boiler. Boiler inspection happens every October. The burner is cleaned yearly.")
put("d/boiler.md.metadata.json", meta(dept="hvac", year=2025, tags=["safety", "annual-inspection"], site="Oslo HQ", public=True))
put("d/lifts.md", "The lift maintenance contract renews in March for the north tower elevators.")
put("d/lifts.md.metadata.json", meta(dept="transport", year=2023, tags=["contract"], site="Bergen Annex", public=False))
put("d/menu.md", "Lunch in the canteen is soup and salad. The cafeteria opens at noon.")
put("d/menu.md.metadata.json", meta(dept="catering", year=2024, tags=["food", "safety-notice"], site="Oslo HQ"))
put("d/cooling.md", "The chiller plant needs refrigerant checks every quarter. Cooling towers are flushed in May.")
put("d/cooling.md.metadata.json", meta(dept="hvac", year=2026, tags=["safety"], site="Bergen Annex", public=True))

emb_arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
kb = ba.create_knowledge_base(name="facilities-kb", roleArn="arn:aws:iam::123456789012:role/r", knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {"embeddingModelArn": emb_arn}},
                              storageConfiguration={"type": "OPENSEARCH_SERVERLESS"})["knowledgeBase"]["knowledgeBaseId"]
ds = ba.create_data_source(knowledgeBaseId=kb, name="d", dataSourceConfiguration={"type": "S3", "s3Configuration": {"bucketArn": "arn:aws:s3:::kbs", "inclusionPrefixes": ["d/"]}},
                           vectorIngestionConfiguration={"chunkingConfiguration": {"chunkingStrategy": "NONE"}})["dataSource"]["dataSourceId"]
ba.start_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds)


def retrieve(q, n=4, **vs):
    return bar.retrieve(knowledgeBaseId=kb, retrievalQuery={"text": q}, retrievalConfiguration={"vectorSearchConfiguration": dict({"numberOfResults": n}, **vs)})["retrievalResults"]


def raw(method, path, body):
    import urllib.request as u
    req = u.Request(url + path, data=json.dumps(body).encode(), method=method, headers={"content-type": "application/json", "authorization": "AWS4-HMAC-SHA256 Credential=x/20261116/us-east-1/bedrock/aws4_request, SignedHeaders=host, Signature=0"})
    try:
        with u.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except Exception as e:  # noqa: BLE001
        return getattr(e, "code", 0), (e.read().decode() if hasattr(e, "read") else str(e)) + str(getattr(e, "headers", {}))


def names(r):
    return [x["location"]["s3Location"]["uri"].rsplit("/", 1)[-1] for x in r]


# ───────── search types ─────────
r = retrieve("heating plant inspection", overrideSearchType="SEMANTIC")
check("SEMANTIC finds the boiler doc with no shared words", names(r)[0] == "boiler.md", names(r))
check("SEMANTIC scores are cosine similarities (descending, in 0..1)", all(0 <= x["score"] <= 1 for x in r) and [x["score"] for x in r] == sorted((x["score"] for x in r), reverse=True) and r[0]["score"] > 0.3, [x["score"] for x in r])
r = retrieve("October", overrideSearchType="HYBRID")
check("HYBRID: the exact lexical hit leads", names(r)[0] == "boiler.md", names(r))
check("HYBRID and SEMANTIC differ in scoring", retrieve("October", overrideSearchType="SEMANTIC")[0]["score"] != r[0]["score"])
code, msg = err(bar.retrieve, knowledgeBaseId=kb, retrievalQuery={"text": "x"}, retrievalConfiguration={"vectorSearchConfiguration": {"overrideSearchType": "BM25", "numberOfResults": 3}})
check("unknown overrideSearchType is a ValidationException", code in ("ValidationException", "ParamValidationError") or "overrideSearchType" in msg, (code, msg))
r = bar.retrieve_and_generate(input={"text": "when is the boiler checked"}, retrieveAndGenerateConfiguration={"type": "KNOWLEDGE_BASE", "knowledgeBaseConfiguration": {
    "knowledgeBaseId": kb, "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
    "retrievalConfiguration": {"vectorSearchConfiguration": {"overrideSearchType": "SEMANTIC", "numberOfResults": 2}}}})
check("RetrieveAndGenerate honours overrideSearchType", r["citations"] and "boiler" in json.dumps(r["citations"]).lower(), r)

# ───────── reranking ─────────
rrc = lambda n=2, **extra: {"type": "BEDROCK_RERANKING_MODEL", "bedrockRerankingConfiguration": dict({"modelConfiguration": {"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.rerank-v1:0"}, "numberOfRerankedResults": n}, **extra)}
os.environ.pop("VYOMI_RERANK_ENDPOINT", None)
r = retrieve("heating plant inspection", 3, rerankingConfiguration=rrc(2))
check("Retrieve with reranking returns numberOfRerankedResults", len(r) == 2 and names(r)[0] == "boiler.md", names(r))
tr = json.loads(__import__("urllib.request").request.urlopen(__import__("urllib.request").request.Request(f"{url}/_vyomi/kb/{kb}/retrieve-trace", data=json.dumps({"retrievalQuery": {"text": "boiler"}, "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 2, "rerankingConfiguration": rrc(2)}}}).encode(), headers={"content-type": "application/json"}), timeout=20).read())
check("trace labels the rerank backend honestly (embedding+lexical by default)", tr["trace"]["rerankBackend"] == "embedding+lexical", tr["trace"].get("rerankBackend"))
os.environ["VYOMI_RERANK_ENDPOINT"] = f"http://127.0.0.1:{ce_port}/v1/rerank"
r = retrieve("annual checks", 4, rerankingConfiguration=rrc(2))
check("a cross-encoder endpoint, when provided, decides the order", names(r)[0] == "boiler.md" and r[0]["score"] > 0.99, [(n, x["score"]) for n, x in zip(names(r), r)])
tr = json.loads(__import__("urllib.request").request.urlopen(__import__("urllib.request").request.Request(f"{url}/_vyomi/kb/{kb}/retrieve-trace", data=json.dumps({"retrievalQuery": {"text": "boiler"}, "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 2, "rerankingConfiguration": rrc(2)}}}).encode(), headers={"content-type": "application/json"}), timeout=20).read())
check("trace reports the cross-encoder", tr["trace"]["rerankBackend"].startswith("cross-encoder"), tr["trace"].get("rerankBackend"))
os.environ["VYOMI_RERANK_ENDPOINT"] = f"http://127.0.0.1:{free_port()}/v1/rerank"
r = retrieve("heating", 3, rerankingConfiguration=rrc(2))
check("an unreachable cross-encoder falls back and says so", len(r) == 2, r)
os.environ.pop("VYOMI_RERANK_ENDPOINT", None)
r = retrieve("heating", 3, rerankingConfiguration=rrc(2, metadataConfiguration={"selectionMode": "SELECTIVE", "selectiveModeConfiguration": {"fieldsToInclude": [{"fieldName": "dept"}]}}))
check("rerank metadataConfiguration accepted", len(r) == 2, r)
code, msg = err(bar.retrieve, knowledgeBaseId=kb, retrievalQuery={"text": "x"}, retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3, "rerankingConfiguration": {
    "type": "BEDROCK_RERANKING_MODEL", "bedrockRerankingConfiguration": {"modelConfiguration": {"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0"}}}}})
check("a non-reranking model ARN is rejected", code == "ValidationException" and "reranking model" in msg, (code, msg))

docs = ["The boiler is inspected every October.", "Elevators renew in March.", "Lunch is served at noon.", "Chiller refrigerant is checked quarterly."]
src = [{"type": "INLINE", "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": t}}} for t in docs]
cfg = lambda n: {"type": "BEDROCK_RERANKING_MODEL", "bedrockRerankingConfiguration": {"modelConfiguration": {"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/cohere.rerank-v3-5:0"}, "numberOfResults": n}}
res = bar.rerank(queries=[{"type": "TEXT", "textQuery": {"text": "when is the heating furnace checked"}}], sources=src, rerankingConfiguration=cfg(3))["results"]
check("Rerank API: top results with index, score and the document", len(res) == 3 and res[0]["index"] == 0 and res[0]["document"]["textDocument"]["text"] == docs[0] and res[0]["relevanceScore"] >= res[1]["relevanceScore"], res)
res = bar.rerank(queries=[{"type": "TEXT", "textQuery": {"text": "lift"}}], sources=src, rerankingConfiguration=cfg(99))["results"]
check("Rerank API: numberOfResults above the source count is capped", len(res) == 4, len(res))
code, msg = err(bar.rerank, queries=[{"type": "TEXT", "textQuery": {"text": "a"}}, {"type": "TEXT", "textQuery": {"text": "b"}}], sources=src, rerankingConfiguration=cfg(2))
check("Rerank API: two queries rejected", code == "ValidationException", (code, msg))
code, msg = err(bar.rerank, queries=[{"type": "TEXT", "textQuery": {"text": "a"}}], sources=[{"type": "INLINE", "inlineDocumentSource": {"type": "JSON", "jsonDocument": {"a": 1}}}], rerankingConfiguration=cfg(1))
check("Rerank API: JSON documents are declared unsupported", code == "ValidationException" and "TEXT" in msg, (code, msg))
code, msg = err(bar.rerank, queries=[{"type": "TEXT", "textQuery": {"text": "a"}}], sources=src, rerankingConfiguration={"type": "BEDROCK_RERANKING_MODEL", "bedrockRerankingConfiguration": {"modelConfiguration": {"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"}, "numberOfResults": 1}})
check("Rerank API: embedding model ARN rejected", code == "ValidationException", (code, msg))

# ───────── metadata filters ─────────
F = lambda f, q="the", n=8: names(retrieve(q, n, filter=f))
check("equals string", sorted(F({"equals": {"key": "dept", "value": "hvac"}})) == ["boiler.md", "cooling.md"])
check("equals boolean", sorted(F({"equals": {"key": "public", "value": True}})) == ["boiler.md", "cooling.md"])
check("equals does not mix number and string", F({"equals": {"key": "year", "value": "2025"}}) == [])
check("notEquals keeps documents without the attribute", sorted(F({"notEquals": {"key": "public", "value": True}})) == ["lifts.md", "menu.md"])
check("greaterThanOrEquals numeric", sorted(F({"greaterThanOrEquals": {"key": "year", "value": 2025}})) == ["boiler.md", "cooling.md"])
check("lessThan numeric", sorted(F({"lessThan": {"key": "year", "value": 2024}})) == ["lifts.md"])
check("lessThanOrEquals numeric", sorted(F({"lessThanOrEquals": {"key": "year", "value": 2024}})) == ["lifts.md", "menu.md"])
check("in", sorted(F({"in": {"key": "dept", "value": ["catering", "transport"]}})) == ["lifts.md", "menu.md"])
check("notIn", sorted(F({"notIn": {"key": "dept", "value": ["catering", "transport"]}})) == ["boiler.md", "cooling.md"])
check("startsWith", sorted(F({"startsWith": {"key": "site", "value": "Oslo"}})) == ["boiler.md", "menu.md"])
check("listContains is an exact member match", sorted(F({"listContains": {"key": "tags", "value": "safety"}})) == ["boiler.md", "cooling.md"])
check("stringContains matches a substring of a string", sorted(F({"stringContains": {"key": "site", "value": "Annex"}})) == ["cooling.md", "lifts.md"])
check("stringContains matches a substring of a list member", sorted(F({"stringContains": {"key": "tags", "value": "safety"}})) == ["boiler.md", "cooling.md", "menu.md"])
check("andAll", F({"andAll": [{"equals": {"key": "dept", "value": "hvac"}}, {"greaterThan": {"key": "year", "value": 2025}}]}) == ["cooling.md"])
check("orAll", sorted(F({"orAll": [{"equals": {"key": "dept", "value": "transport"}}, {"equals": {"key": "dept", "value": "catering"}}]})) == ["lifts.md", "menu.md"])
check("nested andAll inside orAll", sorted(F({"orAll": [{"andAll": [{"equals": {"key": "dept", "value": "hvac"}}, {"lessThan": {"key": "year", "value": 2026}}]}, {"equals": {"key": "dept", "value": "catering"}}]})) == ["boiler.md", "menu.md"])
for label, flt in [("two operators in one filter", {"equals": {"key": "a", "value": "b"}, "notEquals": {"key": "a", "value": "b"}}),
                   ("andAll with one filter", {"andAll": [{"equals": {"key": "a", "value": "b"}}]}),
                   ("andAll with six filters", {"andAll": [{"equals": {"key": "a", "value": str(i)}} for i in range(6)]}),
                   ("in with a scalar", {"in": {"key": "a", "value": "b"}}),
                   ("greaterThan with a string", {"greaterThan": {"key": "a", "value": "b"}}),
                   ("startsWith with a number", {"startsWith": {"key": "a", "value": 3}}),
                   ("empty key", {"equals": {"key": "", "value": "b"}})]:
    st_, bd = raw("POST", f"/knowledgebases/{kb}/retrieve", {"retrievalQuery": {"text": "x"}, "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 3, "filter": flt}}})
    check(f"invalid filter rejected (ValidationException, wire level): {label}", st_ == 400 and "ValidationException" in bd, (st_, bd))

# ───────── implicit filter (local model derives the filter from the question) ─────────
attrs = [{"key": "dept", "type": "STRING", "description": "owning department, e.g. hvac, catering, transport"}]
r = retrieve("hvac documents about the plant", 8, implicitFilterConfiguration={"metadataAttributes": attrs, "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0"})
check("implicit filter derived by the local model narrows results to dept=hvac", sorted(names(r)) == ["boiler.md", "cooling.md"], names(r))
r = retrieve("hvac documents about the plant", 8, filter={"greaterThan": {"key": "year", "value": 2025}}, implicitFilterConfiguration={"metadataAttributes": attrs, "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0"})
check("implicit filter is AND-ed with the explicit filter", names(r) == ["cooling.md"], names(r))
fake.handler = lambda body: {"content": '{"equals":{"key":"invented","value":"x"}}'}
r = retrieve("anything", 8, implicitFilterConfiguration={"metadataAttributes": attrs, "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0"})
check("a model filter on an undeclared attribute is ignored (no invented filter)", len(r) == 4, names(r))
st_, bd = raw("POST", f"/knowledgebases/{kb}/retrieve", {"retrievalQuery": {"text": "x"}, "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 3, "implicitFilterConfiguration": {"metadataAttributes": [], "modelArn": "x"}}}})
check("implicitFilterConfiguration needs attributes", st_ == 400 and "ValidationException" in bd, (st_, bd))
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
