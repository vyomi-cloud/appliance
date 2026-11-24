import io
import os
import time
import zipfile

import boto3

lam, s3, ag = boto3.client("lambda"), boto3.client("s3"), boto3.client("bedrock-agent")
kb = next(k for k in ag.list_knowledge_bases()["knowledgeBaseSummaries"] if k["name"] == "facilities-kb")["knowledgeBaseId"]
ds = ag.list_data_sources(knowledgeBaseId=kb)["dataSourceSummaries"][0]["dataSourceId"]

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    z.write("ingest_docs.py")
arn = lam.create_function(
    FunctionName="facilities-ingest-docs", Runtime="python3.12", Role="arn:aws:iam::123456789012:role/facilities-role", Handler="ingest_docs.handler",
    Code={"ZipFile": buf.getvalue()}, Timeout=30,
    Environment={"Variables": {"KB_ID": kb, "DS_ID": ds, "AWS_ENDPOINT_URL": os.environ["AWS_ENDPOINT_URL"],
                               "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION", "us-east-1")}})["FunctionArn"]
lam.add_permission(FunctionName="facilities-ingest-docs", StatementId="s3-invoke", Action="lambda:InvokeFunction",
                   Principal="s3.amazonaws.com", SourceArn="arn:aws:s3:::facilities-docs", SourceAccount="123456789012")
s3.put_bucket_notification_configuration(Bucket="facilities-docs", NotificationConfiguration={"LambdaFunctionConfigurations": [
    {"LambdaFunctionArn": arn, "Events": ["s3:ObjectCreated:*"], "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": "docs/"}]}}}]})

before = len(ag.list_ingestion_jobs(knowledgeBaseId=kb, dataSourceId=ds)["ingestionJobSummaries"])
s3.put_object(Bucket="facilities-docs", Key="docs/safety-bulletin-2026-11.md",
              Body=b"# Bulletin 2026-11\nChilled water loop flush is scheduled for Saturday. Notify tenants on floors 3 to 5.")
for _ in range(20):
    after = len(ag.list_ingestion_jobs(knowledgeBaseId=kb, dataSourceId=ds)["ingestionJobSummaries"])
    if after > before:
        break
    time.sleep(0.5)
print("new upload started ingestion job #%d through S3 event -> Lambda" % after if after > before else "no new ingestion job appeared")
