import time

import boto3

ag = boto3.client("bedrock-agent")
kb = next(k for k in ag.list_knowledge_bases()["knowledgeBaseSummaries"] if k["name"] == "facilities-kb")["knowledgeBaseId"]
ds = ag.list_data_sources(knowledgeBaseId=kb)["dataSourceSummaries"][0]["dataSourceId"]

job = ag.start_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds)["ingestionJob"]
for _ in range(60):
    job = ag.get_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds, ingestionJobId=job["ingestionJobId"])["ingestionJob"]
    if job["status"] in ("COMPLETE", "FAILED"):
        break
    time.sleep(1)
print("ingestion", job["status"], "| documents scanned:", job.get("statistics", {}).get("numberOfDocumentsScanned"))
