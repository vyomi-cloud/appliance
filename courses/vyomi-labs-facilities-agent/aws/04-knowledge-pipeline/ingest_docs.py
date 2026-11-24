import os

import boto3


def handler(event, context):
    r = boto3.client("bedrock-agent").start_ingestion_job(knowledgeBaseId=os.environ["KB_ID"], dataSourceId=os.environ["DS_ID"])
    return {"ingestionJobId": r["ingestionJob"]["ingestionJobId"], "records": len(event.get("Records", []))}
