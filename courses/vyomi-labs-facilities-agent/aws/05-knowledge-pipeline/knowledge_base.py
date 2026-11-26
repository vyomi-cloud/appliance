import boto3

from vymodels import EMBED_MODEL
from rag_design import chunk_cfg

REGION = "us-east-1"
ag = boto3.client("bedrock-agent")
coll = boto3.client("opensearchserverless").batch_get_collection(names=["facilities-kb"])["collectionDetails"][0]["arn"]

kb = ag.create_knowledge_base(
    name="facilities-kb", roleArn="arn:aws:iam::123456789012:role/facilities-role",
    knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {
        "embeddingModelArn": "arn:aws:bedrock:%s::foundation-model/%s" % (REGION, EMBED_MODEL)}},
    storageConfiguration={"type": "OPENSEARCH_SERVERLESS", "opensearchServerlessConfiguration": {
        "collectionArn": coll, "vectorIndexName": "facilities-index",
        "fieldMapping": {"vectorField": "embedding", "textField": "text", "metadataField": "metadata"}}})["knowledgeBase"]
print("knowledge base", kb["knowledgeBaseId"])

ds = ag.create_data_source(
    knowledgeBaseId=kb["knowledgeBaseId"], name="facilities-docs",
    dataSourceConfiguration={"type": "S3", "s3Configuration": {"bucketArn": "arn:aws:s3:::facilities-docs", "inclusionPrefixes": ["docs/"]}},
    vectorIngestionConfiguration={"chunkingConfiguration": {"chunkingStrategy": "FIXED_SIZE",       # your design: chunking
                                                            "fixedSizeChunkingConfiguration": {"maxTokens": chunk_cfg()["maxTokens"],
                                                                                                "overlapPercentage": chunk_cfg()["overlapPct"]}}})["dataSource"]
print("data source", ds["dataSourceId"])
