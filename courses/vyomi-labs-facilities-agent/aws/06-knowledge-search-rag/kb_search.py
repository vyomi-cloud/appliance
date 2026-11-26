import json
import os

import boto3

import rag_design


def handler(event, context):
    proxy = "httpMethod" in event or "requestContext" in event      # invoked by API Gateway (Lambda proxy integration)
    if proxy:
        claims = ((event.get("requestContext") or {}).get("authorizer") or {}).get("claims") or {}
        event = json.loads(event.get("body") or "{}")
    r = boto3.client("bedrock-agent-runtime").retrieve(
        knowledgeBaseId=os.environ["KB_ID"], retrievalQuery={"text": event.get("query", "")},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": int(event.get("top_k", rag_design.top_k())),
                                                                   **({"overrideSearchType": "HYBRID"} if rag_design.search_type() != "vector" else {})}})
    hits = r.get("retrievalResults", [])
    rr = rag_design.rerank()
    if rr["enabled"] and len(hits) > 1:        # your design: rerank, keep the best topN
        ranked = boto3.client("bedrock-agent-runtime").rerank(
            queries=[{"type": "TEXT", "textQuery": {"text": event.get("query", "")}}],
            sources=[{"type": "INLINE", "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": h["content"]["text"]}}} for h in hits],
            rerankingConfiguration={"type": "BEDROCK_RERANKING_MODEL", "bedrockRerankingConfiguration": {
                "numberOfResults": min(rr["topN"], len(hits)),
                "modelConfiguration": {"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.rerank-v1:0"}}})
        hits = [hits[x["index"]] for x in ranked["results"]]
    out = {"results": [{"text": x["content"]["text"], "score": x.get("score"),
                        "source": (x.get("location") or {}).get("s3Location", {}).get("uri", "")} for x in hits]}
    if proxy:
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"},
                "body": json.dumps(dict(out, caller=claims.get("email", "anonymous")))}
    return out
