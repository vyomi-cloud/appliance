"""Nano embeddings: web catalogue has an embedding model; Titan/Cohere/vyomi ids create a KB; ingest+retrieve work with the
labelled hash fallback AND through the async in-browser embedder path (fake MiniLM stand-in; the real transformers.js model
runs only in a browser).  Run: VYOMI_CATALOG=web PYTHONPATH=. python3 tests/conformance/test_nano_embed.py"""
import asyncio
import os
import sys
os.environ["VYOMI_CATALOG"] = "web"
os.environ.setdefault("VYOMI_LLM_DISABLE", "1")
import tempfile
os.environ["CLOUDLEARN_STATE_FILE"] = os.path.join(tempfile.mkdtemp(), "s.sqlite3")
import boto3
from botocore.config import Config
from core import llm_core as llm, ai_model_catalog as C

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {str(extra)[:300]}")


check("web catalogue lists an embedding model", C.BY_ID.get("all-minilm-l6-v2", {}).get("kind") == "embed" and C.DEFAULT_EMBED == "all-minilm-l6-v2")
check("titan/cohere/gemini/openai embed ids alias to it", all(C.resolve(c, i) == "all-minilm-l6-v2" for c, i in
      [("aws", "amazon.titan-embed-text-v2:0"), ("aws", "cohere.embed-english-v3"), ("gcp", "text-embedding-004"), ("azure", "text-embedding-3-small")]))

def start_server():
    import socket, threading, time
    import uvicorn
    from fastapi import FastAPI, Request
    from core import wire_ingress
    app = FastAPI()
    router = wire_ingress.appliance_router()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)
    sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}"


url = start_server()
kw = dict(endpoint_url=url, region_name="us-east-1", aws_access_key_id="AKIAFAKE", aws_secret_access_key="x", config=Config(retries={"max_attempts": 1}))
s3, bra, brt = (boto3.client(n, **kw) for n in ("s3", "bedrock-agent", "bedrock-agent-runtime"))
s3.create_bucket(Bucket="fac-docs")
s3.put_object(Bucket="fac-docs", Key="hvac.md", Body=b"# HVAC\n\nReplace the chiller air filters every 90 days and log a work order.")
s3.put_object(Bucket="fac-docs", Key="fire.md", Body=b"# Fire alarm\n\nTest the fire alarm panel monthly and notify the monitoring company.")
for i, arn in enumerate(["amazon.titan-embed-text-v2:0", "cohere.embed-english-v3", "vyomi.all-minilm-l6-v2"]):
    try:
        kb = bra.create_knowledge_base(name=f"facilities-kb{'' if i == 0 else i}", roleArn="arn:aws:iam::123456789012:role/kb",
            knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {"embeddingModelArn": f"arn:aws:bedrock:us-east-1::foundation-model/{arn}"}},
            storageConfiguration={"type": "OPENSEARCH_SERVERLESS", "opensearchServerlessConfiguration": {"collectionArn": "arn:aws:aoss:us-east-1:123456789012:collection/x", "vectorIndexName": "i",
                                  "fieldMapping": {"vectorField": "e", "textField": "t", "metadataField": "m"}}})["knowledgeBase"]
        ok = True
    except Exception as e:
        ok, kb = False, str(e)
    check(f"CreateKnowledgeBase accepts {arn} on Nano", ok, kb)
kid = bra.list_knowledge_bases()["knowledgeBaseSummaries"][0]["knowledgeBaseId"]
ds = bra.create_data_source(knowledgeBaseId=kid, name="d", dataSourceConfiguration={"type": "S3", "s3Configuration": {"bucketArn": "arn:aws:s3:::fac-docs"}})["dataSource"]
j = bra.start_ingestion_job(knowledgeBaseId=kid, dataSourceId=ds["dataSourceId"])["ingestionJob"]
j = bra.get_ingestion_job(knowledgeBaseId=kid, dataSourceId=ds["dataSourceId"], ingestionJobId=j["ingestionJobId"])["ingestionJob"]
check("ingest COMPLETE with hash fallback", j["status"] == "COMPLETE" and j["statistics"]["numberOfDocumentsFailed"] == 0, j)
r = brt.retrieve(knowledgeBaseId=kid, retrievalQuery={"text": "how often replace chiller air filter"})["retrievalResults"]
check("retrieve top hit = HVAC doc", r and "hvac" in r[0]["location"]["s3Location"]["uri"], r)
e = llm.embed("x")
check("fallback is labelled", e["backend"] == "vyomi-hash-embed" and e["model"] == "vyomi-hash-embed", e)

# async in-browser embedder (stand-in for transformers.js MiniLM): 384-d, picked up through arun, labelled transformers.js
async def fake_minilm(texts):
    return [llm._renorm(([float(len(t))] + llm.hash_embed(t, 383))) for t in texts]
llm.set_async_embed(fake_minilm, model="all-minilm-l6-v2")
out = asyncio.run(llm.arun(lambda: llm.embed(["a b", "c"])))
check("async embedder used via arun (384-d, transformers.js)", out["backend"] == "transformers.js" and out["dimensions"] == 384 and out["model"] == "all-minilm-l6-v2", out)

async def broken(texts):
    raise RuntimeError("model fetch blocked")
llm.set_async_embed(broken, model="all-minilm-l6-v2")
out = asyncio.run(llm.arun(lambda: llm.embed("x")))
check("failed engine degrades to labelled hash-embed", out["backend"] == "vyomi-hash-embed", out)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
