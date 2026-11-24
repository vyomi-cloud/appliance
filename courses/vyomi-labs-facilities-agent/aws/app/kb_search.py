import json
import os

import boto3


def handler(event, context):
    proxy = "httpMethod" in event or "requestContext" in event      # invoked by API Gateway (Lambda proxy integration)
    if proxy:
        claims = ((event.get("requestContext") or {}).get("authorizer") or {}).get("claims") or {}
        event = json.loads(event.get("body") or "{}")
    r = boto3.client("bedrock-agent-runtime").retrieve(
        knowledgeBaseId=os.environ["KB_ID"], retrievalQuery={"text": event.get("query", "")},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": int(event.get("top_k", 3))}})
    out = {"results": [{"text": x["content"]["text"], "score": x.get("score"),
                        "source": (x.get("location") or {}).get("s3Location", {}).get("uri", "")} for x in r.get("retrievalResults", [])]}
    if proxy:
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"},
                "body": json.dumps(dict(out, caller=claims.get("email", "anonymous")))}
    return out
