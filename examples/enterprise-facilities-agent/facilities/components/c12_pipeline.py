"""C12: knowledge processing pipeline. Documents -> S3 -> embeddings -> Bedrock KB ingestion; a new upload re-triggers ingestion through S3 events + Lambda."""
import json, os, time
from ..runtime import NAMES, Blocked
from .. import deploy


def run(ctx):
    s3, ag, rt = ctx.client("s3"), ctx.client("bedrock-agent"), ctx.client("bedrock-runtime")
    bucket = NAMES["bucket"]
    docs_dir = os.path.join(deploy.FIX, "docs")

    def upload():
        s3.create_bucket(Bucket=bucket)
        n = 0
        for f in sorted(os.listdir(docs_dir)):
            with open(os.path.join(docs_dir, f), "rb") as fh:
                s3.put_object(Bucket=bucket, Key="docs/" + f, Body=fh.read(), ContentType="text/markdown")
            n += 1
        return f"{n} documents uploaded to s3://{bucket}/docs/"
    ctx.step("s3: upload SOP and manual documents", upload)

    def embed():
        v = json.loads(rt.invoke_model(modelId="amazon.titan-embed-text-v2:0", body=json.dumps({"inputText": "boiler pressure"}))["body"].read())["embedding"]
        assert len(v) > 0
        if not any(abs(x) > 1e-9 for x in v):
            raise Blocked("local model", "embedding endpoint returned an all-zero vector (no embedding model reachable)")
        return f"embedding dim {len(v)}"
    ctx.step("bedrock-runtime: InvokeModel titan-embed-text-v2", embed)

    def collection():
        oss = ctx.client("opensearchserverless")
        oss.create_security_policy(name="facilities-enc", type="encryption", policy=json.dumps({"Rules": [{"ResourceType": "collection", "Resource": ["collection/facilities-kb"]}], "AWSOwnedKey": True}))
        c = oss.create_collection(name="facilities-kb", type="VECTORSEARCH")["createCollectionDetail"]
        ctx.state["collection_arn"] = c["arn"]
        return c["arn"]
    ctx.step("opensearchserverless: CreateCollection (vector store)", collection, lane="knowledge")
    coll = ctx.state.get("collection_arn", f"arn:aws:aoss:{ctx.region}:123456789012:collection/facilities-kb")

    def kb():
        r = ag.create_knowledge_base(
            name=NAMES["kb"], roleArn=NAMES["role"],
            knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": f"arn:aws:bedrock:{ctx.region}::foundation-model/amazon.titan-embed-text-v2:0"}},
            storageConfiguration={"type": "OPENSEARCH_SERVERLESS", "opensearchServerlessConfiguration": {
                "collectionArn": coll, "vectorIndexName": "facilities-index",
                "fieldMapping": {"vectorField": "embedding", "textField": "text", "metadataField": "metadata"}}})["knowledgeBase"]
        ctx.state["kb_id"] = r["knowledgeBaseId"]
        return f"KB {r['knowledgeBaseId']}"
    ctx.step("bedrock-agent: CreateKnowledgeBase facilities-kb", kb)
    if "kb_id" not in ctx.state:
        return
    kid = ctx.state["kb_id"]

    def ds():
        r = ag.create_data_source(knowledgeBaseId=kid, name="facilities-docs",
                                  dataSourceConfiguration={"type": "S3", "s3Configuration": {"bucketArn": f"arn:aws:s3:::{bucket}", "inclusionPrefixes": ["docs/"]}},
                                  vectorIngestionConfiguration={"chunkingConfiguration": {"chunkingStrategy": "FIXED_SIZE", "fixedSizeChunkingConfiguration": {"maxTokens": 200, "overlapPercentage": 10}}})["dataSource"]
        ctx.state["ds_id"] = r["dataSourceId"]
        return r["dataSourceId"]
    ctx.step("bedrock-agent: CreateDataSource (S3, fixed-size chunking)", ds)
    if "ds_id" not in ctx.state:
        return

    def ingest():
        j = ag.start_ingestion_job(knowledgeBaseId=kid, dataSourceId=ctx.state["ds_id"])["ingestionJob"]
        for _ in range(60):
            j = ag.get_ingestion_job(knowledgeBaseId=kid, dataSourceId=ctx.state["ds_id"], ingestionJobId=j["ingestionJobId"])["ingestionJob"]
            if j["status"] in ("COMPLETE", "FAILED"):
                break
            time.sleep(1)
        assert j["status"] == "COMPLETE", f"ingestion {j['status']}"
        st = j.get("statistics", {})
        return f"ingestion COMPLETE, scanned={st.get('numberOfDocumentsScanned', '?')} indexed={st.get('numberOfNewDocumentsIndexed', '?')}"
    ctx.step("bedrock-agent: StartIngestionJob + poll to COMPLETE", ingest)

    def event_driven():
        arn = deploy.deploy_lambda(ctx, "facilities-ingest-docs", "ingest_docs", dict(KB_ID=kid, DS_ID=ctx.state["ds_id"]))
        before = len(ag.list_ingestion_jobs(knowledgeBaseId=kid, dataSourceId=ctx.state["ds_id"])["ingestionJobSummaries"])
        s3.put_bucket_notification_configuration(Bucket=bucket, NotificationConfiguration={"LambdaFunctionConfigurations": [
            {"LambdaFunctionArn": arn, "Events": ["s3:ObjectCreated:*"], "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": "docs/"}]}}}]})
        s3.put_object(Bucket=bucket, Key="docs/safety-bulletin-2026-11.md", Body=b"# Bulletin 2026-11\nChilled water loop flush is scheduled for Saturday. Notify tenants on floors 3 to 5.")
        for _ in range(20):
            after = len(ag.list_ingestion_jobs(knowledgeBaseId=kid, dataSourceId=ctx.state["ds_id"])["ingestionJobSummaries"])
            if after > before:
                return f"new upload triggered ingestion job #{after} via S3 event -> Lambda"
            time.sleep(0.5)
        raise Blocked("knowledge", "S3 ObjectCreated did not invoke the ingest Lambda (no event delivery to Lambda observed)")
    ctx.step("s3 event -> Lambda -> StartIngestionJob (event-driven re-index)", event_driven)
