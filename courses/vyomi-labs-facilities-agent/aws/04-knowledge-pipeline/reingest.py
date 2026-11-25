import time

import boto3

ag, rt, s3 = boto3.client("bedrock-agent"), boto3.client("bedrock-agent-runtime"), boto3.client("s3")
kb = next(k for k in ag.list_knowledge_bases()["knowledgeBaseSummaries"] if k["name"] == "facilities-kb")["knowledgeBaseId"]
ds = ag.list_data_sources(knowledgeBaseId=kb)["dataSourceSummaries"][0]["dataSourceId"]


def ingest():
    job = ag.start_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds)["ingestionJob"]
    for _ in range(60):
        job = ag.get_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds, ingestionJobId=job["ingestionJobId"])["ingestionJob"]
        if job["status"] in ("COMPLETE", "FAILED"):
            break
        time.sleep(0.5)
    assert job["status"] == "COMPLETE", job
    return job


def chunks(query="boiler pressure"):
    r = rt.retrieve(knowledgeBaseId=kb, retrievalQuery={"text": query}, retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 25}})
    return [x["content"]["text"] for x in r["retrievalResults"]]


before = chunks()
ingest()
ingest()
after = chunks()
assert len(after) == len(set(after)), "re-ingestion duplicated chunks: %d results, %d unique" % (len(after), len(set(after)))
assert len(after) == len(before), "re-ingesting unchanged documents changed the index size (%d -> %d)" % (len(before), len(after))
print("ingested twice more: the index still holds", len(after), "chunks, each once")

key = "docs/boiler-sop.md"
old = s3.get_object(Bucket="facilities-docs", Key=key)["Body"].read().decode()
assert "30 psi" in old
s3.put_object(Bucket="facilities-docs", Key=key, Body=old.replace("30 psi", "25 psi").encode(), ContentType="text/markdown")
try:
    ingest()
    fresh = chunks("What boiler pressure triggers the valve closure?")
    assert any("25 psi" in c for c in fresh), "the edited limit (25 psi) is not retrievable"
    assert not any("30 psi" in c for c in fresh), "the superseded limit (30 psi) is still served"
    print("edited SOP: retrieval serves 25 psi and no longer serves 30 psi")
finally:
    s3.put_object(Bucket="facilities-docs", Key=key, Body=old.encode(), ContentType="text/markdown")     # restore the original for the later chapters
    ingest()
print("idempotent ingestion verified")
