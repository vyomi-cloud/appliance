"""Knowledge lane (C6+C12): Bedrock KB over OpenSearch Serverless, hybrid + filter + rerank, opensearch-py data plane, RAG Studio inspect API.
Real boto3 + opensearch-py against the in-process wire server.   Run: PYTHONPATH=.:<dir with opensearch-py> python3 tests/conformance/test_knowledge_rag.py
"""
import json
import sys
sys.path.insert(0, "tools/ai_probe")
import boto3
import requests
from botocore.config import Config
import gcp_probe

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {str(extra)[:400]}")


url = gcp_probe.start_server()
kw = dict(endpoint_url=url, region_name="us-east-1", aws_access_key_id="AKIAFAKE", aws_secret_access_key="x", config=Config(retries={"max_attempts": 1}))
s3 = boto3.client("s3", **kw)
bra = boto3.client("bedrock-agent", **kw)
brt = boto3.client("bedrock-agent-runtime", **kw)
aoss = boto3.client("opensearchserverless", **kw)
osm = boto3.client("opensearch", **kw)
bdr = boto3.client("bedrock", **kw)

# ── docs in S3 ──
B = "facilities-docs"
s3.create_bucket(Bucket=B)
DOCS = {
    "sop/hvac-filter.md": ("# HVAC filter replacement\n\nReplace the chiller room air filters every 90 days. Isolate the air handler, lock out the breaker, swap the MERV 13 filter and log the work order.\n\n# Chiller shutdown\n\nTo shut down the chiller close the supply valve first, then power off the compressor.", {"site": "hq", "type": "sop"}),
    "sop/fire-alarm.md": ("# Fire alarm testing\n\nTest the fire alarm panel monthly. Notify the monitoring company before the test and record every device that fails to sound.", {"site": "plant", "type": "sop"}),
    "manual/elevator.md": ("# Elevator manual\n\nElevator inspection must happen annually by a licensed inspector. Emergency phone numbers are posted inside the car.", {"site": "hq", "type": "manual"}),
    "sop/contact.md": ("# Escalation contacts\n\nCall facility lead Jane Roe at jane.roe@example.com if the generator fails.", {"site": "hq", "type": "sop"}),
}
for k, (t, m) in DOCS.items():
    s3.put_object(Bucket=B, Key=k, Body=t.encode())
    s3.put_object(Bucket=B, Key=k + ".metadata.json", Body=json.dumps({"metadataAttributes": m}).encode())

# ── guardrail with PII anonymise (C12 PII scan stage) ──
g = bdr.create_guardrail(name="facilities-guardrail", blockedInputMessaging="blocked", blockedOutputsMessaging="blocked",
                         sensitiveInformationPolicyConfig={"piiEntitiesConfig": [{"type": "EMAIL", "action": "ANONYMIZE"}]})
s3.put_object(Bucket=B, Key=".vyomi-pipeline.json", Body=json.dumps({"guardrailIdentifier": g["guardrailId"], "guardrailVersion": "DRAFT"}).encode())

# ── OpenSearch Serverless control plane ──
try:
    aoss.create_collection(name="facilities-vec", type="VECTORSEARCH")
    check("collection without encryption policy is rejected", False)
except Exception as e:
    check("collection without encryption policy is rejected", "encryption" in str(e), e)
aoss.create_security_policy(name="facilities-enc", type="encryption", policy=json.dumps({"Rules": [{"ResourceType": "collection", "Resource": ["collection/facilities-vec"]}], "AWSOwnedKey": True}))
aoss.create_security_policy(name="facilities-net", type="network", policy=json.dumps([{"Rules": [{"ResourceType": "collection", "Resource": ["collection/facilities-vec"]}], "AllowFromPublic": True}]))
aoss.create_access_policy(name="facilities-acc", type="data", policy=json.dumps([{"Rules": [{"ResourceType": "index", "Resource": ["index/facilities-vec/*"], "Permission": ["aoss:*"]}], "Principal": ["*"]}]))
c = aoss.create_collection(name="facilities-vec", type="VECTORSEARCH")["createCollectionDetail"]
check("create_collection ACTIVE", c["status"] == "ACTIVE" and c["id"])
bg = aoss.batch_get_collection(names=["facilities-vec"])["collectionDetails"][0]
check("batch_get_collection has endpoint", bg["collectionEndpoint"].startswith("https://"))
check("list_collections", any(x["name"] == "facilities-vec" for x in aoss.list_collections()["collectionSummaries"]))
check("list_security_policies", len(aoss.list_security_policies(type="encryption")["securityPolicySummaries"]) == 1)
d = osm.create_domain(DomainName="facilities-search", EngineVersion="OpenSearch_2.17")["DomainStatus"]
check("opensearch create_domain", d["DomainName"] == "facilities-search" and d["Endpoint"])
check("opensearch describe/list", osm.describe_domain(DomainName="facilities-search")["DomainStatus"]["ARN"] == d["ARN"] and osm.list_domain_names()["DomainNames"])

# ── Bedrock KB over OpenSearch Serverless ──
kb = bra.create_knowledge_base(
    name="facilities-kb", roleArn="arn:aws:iam::123456789012:role/kb",
    knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {"embeddingModelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"}},
    storageConfiguration={"type": "OPENSEARCH_SERVERLESS", "opensearchServerlessConfiguration": {
        "collectionArn": c["arn"], "vectorIndexName": "facilities-index",
        "fieldMapping": {"vectorField": "embedding", "textField": "text", "metadataField": "metadata"}}})["knowledgeBase"]
kid = kb["knowledgeBaseId"]
ds = bra.create_data_source(knowledgeBaseId=kid, name="sop-docs",
                            dataSourceConfiguration={"type": "S3", "s3Configuration": {"bucketArn": f"arn:aws:s3:::{B}"}},
                            vectorIngestionConfiguration={"chunkingConfiguration": {"chunkingStrategy": "SEMANTIC", "semanticChunkingConfiguration": {"maxTokens": 60, "bufferSize": 0, "breakpointPercentileThreshold": 95}}})["dataSource"]
job = bra.start_ingestion_job(knowledgeBaseId=kid, dataSourceId=ds["dataSourceId"])["ingestionJob"]
st = bra.get_ingestion_job(knowledgeBaseId=kid, dataSourceId=ds["dataSourceId"], ingestionJobId=job["ingestionJobId"])["ingestionJob"]
check("ingestion COMPLETE, 4 docs", st["status"] == "COMPLETE" and st["statistics"]["numberOfDocumentsScanned"] == 4 and st["statistics"]["numberOfDocumentsFailed"] == 0, st)

# ── Retrieve ──
r = brt.retrieve(knowledgeBaseId=kid, retrievalQuery={"text": "how often do I replace the chiller air filter"},
                 retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3, "overrideSearchType": "HYBRID"}})["retrievalResults"]
check("hybrid retrieve top hit is the HVAC SOP", r and "hvac-filter" in r[0]["location"]["s3Location"]["uri"], [x["location"] for x in r])
check("result has score + metadata + chunk id", "score" in r[0] and r[0]["metadata"].get("site") == "hq" and r[0]["metadata"].get("x-amz-bedrock-kb-chunk-id"))
rf = brt.retrieve(knowledgeBaseId=kid, retrievalQuery={"text": "testing procedure"},
                  retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 5, "filter": {"equals": {"key": "site", "value": "plant"}}}})["retrievalResults"]
check("metadata filter (access-aware) only returns site=plant", rf and all(x["metadata"]["site"] == "plant" for x in rf), rf)
rr = brt.retrieve(knowledgeBaseId=kid, retrievalQuery={"text": "elevator inspection"},
                  retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 2, "rerankingConfiguration": {"type": "BEDROCK_RERANKING_MODEL", "bedrockRerankingConfiguration": {
                      "modelConfiguration": {"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.rerank-v1:0"}, "numberOfRerankedResults": 2}}}})["retrievalResults"]
check("rerank retrieve: elevator doc first", rr and "elevator" in rr[0]["location"]["s3Location"]["uri"], rr)
rk = brt.rerank(queries=[{"type": "TEXT", "textQuery": {"text": "fire alarm test"}}],
                sources=[{"type": "INLINE", "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": t}}} for t in ["elevator inspection yearly", "monthly fire alarm panel test", "pizza"]],
                rerankingConfiguration={"type": "BEDROCK_RERANKING_MODEL", "bedrockRerankingConfiguration": {"modelConfiguration": {"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.rerank-v1:0"}, "numberOfResults": 2}})["results"]
check("Rerank API orders passages", rk[0]["index"] == 1 and len(rk) == 2, rk)

# ── PII scan stage: email anonymised in chunks ──
ch = requests.get(f"{url}/_vyomi/kb/{kid}/chunks").json()
txt = " ".join(x["text"] for x in ch["chunks"])
check("PII: email redacted before indexing", "jane.roe@example.com" not in txt and "{EMAIL}" in txt)
check("inspect chunks: tokens, metadata, 2-D projection", ch["count"] >= 4 and all(len(x["projection2d"]) == 2 and x["tokenCount"] > 0 for x in ch["chunks"]))
tr = requests.post(f"{url}/_vyomi/kb/{kid}/retrieve-trace", json={"retrievalQuery": {"text": "fire alarm"}, "hybridWeight": 0.5,
                   "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 2, "filter": {"equals": {"key": "site", "value": "plant"}}}}}).json()
cand = tr["trace"]["candidates"]
check("retrieve-trace: per-candidate scores + filtered reason + stage latency",
      all(k in cand[0] for k in ("vector_score", "bm25_score", "fused_rank", "rerank_score", "filtered_out_reason")) and any(x["filtered_out_reason"] == "metadata filter" for x in cand)
      and "search" in tr["trace"]["latencyMs"], tr["trace"])
# chunking params honoured: FIXED_SIZE tiny chunks -> more chunks
ds2 = bra.create_data_source(knowledgeBaseId=kid, name="tiny", dataSourceConfiguration={"type": "S3", "s3Configuration": {"bucketArn": f"arn:aws:s3:::{B}", "inclusionPrefixes": ["sop/"]}},
                             vectorIngestionConfiguration={"chunkingConfiguration": {"chunkingStrategy": "FIXED_SIZE", "fixedSizeChunkingConfiguration": {"maxTokens": 8, "overlapPercentage": 1}}})["dataSource"]
bra.start_ingestion_job(knowledgeBaseId=kid, dataSourceId=ds2["dataSourceId"])
n2 = requests.get(f"{url}/_vyomi/kb/{kid}/chunks").json()["count"]
check("chunking parameters honoured (size 8 -> many more chunks)", n2 > ch["count"] + 10, (ch["count"], n2))

# ── opensearch-py on the same index (KB mirrored it) ──
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
creds = boto3.Session(aws_access_key_id="AKIAFAKE", aws_secret_access_key="x").get_credentials()
os_ = OpenSearch(hosts=[url], http_auth=AWSV4SignerAuth(creds, "us-east-1", "aoss"), use_ssl=False, verify_certs=False, connection_class=RequestsHttpConnection)
check("opensearch-py info", os_.info()["version"]["distribution"] == "opensearch")
m = os_.search(index="facilities-index", body={"query": {"match": {"text": "fire alarm"}}})
check("BM25 match on KB index", m["hits"]["total"]["value"] >= 1 and "fire" in m["hits"]["hits"][0]["_source"]["text"].lower(), m["hits"])
vec = m["hits"]["hits"][0]["_source"]["embedding"]
k = os_.search(index="facilities-index", body={"size": 2, "query": {"knn": {"embedding": {"vector": vec, "k": 2}}}})
check("knn query returns nearest first", k["hits"]["hits"][0]["_id"] == m["hits"]["hits"][0]["_id"])
hy = os_.search(index="facilities-index", body={"size": 3, "query": {"hybrid": {"queries": [{"match": {"text": "chiller"}}, {"knn": {"embedding": {"vector": vec, "k": 3}}}]}}})
check("hybrid query", hy["hits"]["hits"], hy)
f = os_.search(index="facilities-index", body={"query": {"bool": {"must": [{"match": {"text": "inspection"}}], "filter": [{"term": {"metadata.site": "hq"}}]}}})
check("bool + term filter on metadata", f["hits"]["total"]["value"] >= 1 and all(h["_source"]["metadata"]["site"] == "hq" for h in f["hits"]["hits"]), f["hits"])
# generic index CRUD + bulk
os_.indices.create(index="tickets", body={"mappings": {"properties": {"v": {"type": "knn_vector", "dimension": 2}}}})
from opensearchpy import helpers
helpers.bulk(os_, [{"_index": "tickets", "_id": str(i), "title": f"leak {i}", "prio": i, "v": [1.0, float(i)]} for i in range(5)], refresh=True)
check("bulk + count", os_.count(index="tickets")["count"] == 5)
rg = os_.search(index="tickets", body={"query": {"range": {"prio": {"gte": 3}}}, "sort": [{"prio": "desc"}]})
check("range + sort", [h["_id"] for h in rg["hits"]["hits"]] == ["4", "3"])
os_.update(index="tickets", id="1", body={"doc": {"title": "burst"}})
check("update + get + delete", os_.get(index="tickets", id="1")["_source"]["title"] == "burst" and os_.delete(index="tickets", id="1")["result"] == "deleted")
try:
    os_.search(index="nope", body={"query": {"match_all": {}}})
    check("missing index -> index_not_found", False)
except Exception as e:
    check("missing index -> index_not_found", "index_not_found" in str(e), e)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
