"""(7) KB retrieval quality, REAL boto3 (bedrock-agent + bedrock-agent-runtime + s3): the same corpus and queries through two knowledge bases,
one embedded by the REAL nomic-embed-text model (llama.cpp), one by the labelled hash fallback (vyomi-hash-embed). recall@1, recall@3, MRR."""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tools.mesh_verify import inproc
from tools.mesh_verify.common import save
from tools.mesh_verify.kb_data import DOCS, QUERIES


def build(boto3, kw, llm, name, real):
    s3, ag, rt, oss = (boto3.client(n, **kw) for n in ("s3", "bedrock-agent", "bedrock-agent-runtime", "opensearchserverless"))
    llm._state["embed_fn"] = None if real else (lambda texts: [llm.hash_embed(t) for t in texts])
    bucket = f"mv-{name}"
    s3.create_bucket(Bucket=bucket)
    for k, v in DOCS.items():
        s3.put_object(Bucket=bucket, Key=f"docs/{k}.md", Body=v.encode())
    oss.create_security_policy(name=f"{name}-enc", type="encryption", policy=json.dumps({"Rules": [{"ResourceType": "collection", "Resource": [f"collection/{name}"]}], "AWSOwnedKey": True}))
    coll = oss.create_collection(name=name, type="VECTORSEARCH")["createCollectionDetail"]["arn"]
    kb = ag.create_knowledge_base(name=name, roleArn=inproc.ROLE, knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {
        "embeddingModelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"}},
        storageConfiguration={"type": "OPENSEARCH_SERVERLESS", "opensearchServerlessConfiguration": {"collectionArn": coll, "vectorIndexName": "i",
                              "fieldMapping": {"vectorField": "embedding", "textField": "text", "metadataField": "metadata"}}})["knowledgeBase"]["knowledgeBaseId"]
    ds = ag.create_data_source(knowledgeBaseId=kb, name="d", dataSourceConfiguration={"type": "S3", "s3Configuration": {"bucketArn": f"arn:aws:s3:::{bucket}", "inclusionPrefixes": ["docs/"]}},
                               vectorIngestionConfiguration={"chunkingConfiguration": {"chunkingStrategy": "FIXED_SIZE", "fixedSizeChunkingConfiguration": {"maxTokens": 200, "overlapPercentage": 10}}})["dataSource"]["dataSourceId"]
    j = ag.start_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds)["ingestionJob"]
    for _ in range(300):
        j = ag.get_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds, ingestionJobId=j["ingestionJobId"])["ingestionJob"]
        if j["status"] in ("COMPLETE", "FAILED"):
            break
        time.sleep(1)
    assert j["status"] == "COMPLETE", j
    ranks = []
    for q, want in QUERIES:
        res = rt.retrieve(knowledgeBaseId=kb, retrievalQuery={"text": q}, retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 5}})["retrievalResults"]
        ids = [r["location"]["s3Location"]["uri"].rsplit("/", 1)[-1][:-3] for r in res]
        ranks.append(ids.index(want) + 1 if want in ids else None)
    n = len(ranks)
    return {"n_queries": n, "recall@1": round(sum(r == 1 for r in ranks) / n, 3), "recall@3": round(sum(bool(r) and r <= 3 for r in ranks) / n, 3),
            "recall@5": round(sum(r is not None for r in ranks) / n, 3), "mrr": round(sum(1 / r for r in ranks if r) / n, 3), "ranks": ranks}


def main():
    url, kw, boto3 = inproc.start()
    from core import llm_core as llm
    e = llm.embed(["probe"]); assert e.get("backend") != "vyomi-hash-embed", "real embedder not reachable"
    out = {"real": dict(embed_backend=e.get("backend"), embed_model=e.get("model"), **build(boto3, kw, llm, "mvreal", True))}
    out["hash"] = dict(embed_backend="vyomi-hash-embed", **build(boto3, kw, llm, "mvhash", False))
    for k in ("real", "hash"):
        print(k, {a: b for a, b in out[k].items() if a != "ranks"})
    save("kb_quality", out)


main()
