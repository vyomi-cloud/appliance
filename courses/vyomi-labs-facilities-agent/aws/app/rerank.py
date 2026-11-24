import boto3

from search import search

QUERY = "elevator door fault"
hits = search(QUERY, 4)
# Rerank takes a reranking-model ARN; the simulator scores with its own hosted embedding model
out = boto3.client("bedrock-agent-runtime").rerank(
    queries=[{"type": "TEXT", "textQuery": {"text": QUERY}}],
    sources=[{"type": "INLINE", "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": h["content"]["text"]}}} for h in hits],
    rerankingConfiguration={"type": "BEDROCK_RERANKING_MODEL", "bedrockRerankingConfiguration": {
        "numberOfResults": 2, "modelConfiguration": {"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.rerank-v1:0"}}})
print("rerank returned", len(out["results"]), "results; best index", out["results"][0]["index"])
