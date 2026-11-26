import json
import os

import boto3

# Your RAG design (chapter 14) reaches this tool as function configuration: deploy_kb_search.py copies it into these variables.
TOP_K = int(os.environ.get("RAG_TOP_K", "3"))
SEARCH_TYPE = os.environ.get("RAG_SEARCH_TYPE", "vector")
RERANK_TOP_N = int(os.environ.get("RAG_RERANK_TOP_N", "0"))      # 0 = no rerank


def handler(event, context):
    proxy = "httpMethod" in event or "requestContext" in event      # invoked by API Gateway (Lambda proxy integration)
    if proxy:
        claims = ((event.get("requestContext") or {}).get("authorizer") or {}).get("claims") or {}
        event = json.loads(event.get("body") or "{}")
    r = boto3.client("bedrock-agent-runtime").retrieve(
        knowledgeBaseId=os.environ["KB_ID"], retrievalQuery={"text": event.get("query", "")},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": int(event.get("top_k", TOP_K)),
                                                                   **({"overrideSearchType": "HYBRID"} if SEARCH_TYPE != "vector" else {})}})
    hits = r.get("retrievalResults", [])
    if RERANK_TOP_N and len(hits) > 1:         # your design: rerank, keep the best few
        ranked = boto3.client("bedrock-agent-runtime").rerank(
            queries=[{"type": "TEXT", "textQuery": {"text": event.get("query", "")}}],
            sources=[{"type": "INLINE", "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": h["content"]["text"]}}} for h in hits],
            rerankingConfiguration={"type": "BEDROCK_RERANKING_MODEL", "bedrockRerankingConfiguration": {
                "numberOfResults": min(RERANK_TOP_N, len(hits)),
                "modelConfiguration": {"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.rerank-v1:0"}}})
        hits = [hits[x["index"]] for x in ranked["results"]]
    out = {"results": [{"text": x["content"]["text"], "score": x.get("score"),
                        "source": (x.get("location") or {}).get("s3Location", {}).get("uri", "")} for x in hits]}
    if proxy:
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"},
                "body": json.dumps(dict(out, caller=claims.get("email", "anonymous")))}
    return out
