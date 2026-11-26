import boto3

import rag_design
from search import search

QUERY = "elevator door fault"
hits = search(QUERY, 4)
# Rerank takes a reranking-model ARN; the simulator scores with its own hosted embedding model
out = boto3.client("bedrock-agent-runtime").rerank(
    queries=[{"type": "TEXT", "textQuery": {"text": QUERY}}],
    sources=[{"type": "INLINE", "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": h["content"]["text"]}}} for h in hits],
    rerankingConfiguration={"type": "BEDROCK_RERANKING_MODEL", "bedrockRerankingConfiguration": {
        "numberOfResults": rag_design.rerank()["topN"], "modelConfiguration": {"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.rerank-v1:0"}}})
best = hits[out["results"][0]["index"]]["content"]["text"]
assert len(out["results"]) == rag_design.rerank()["topN"], "rerank must return the requested number of results"
assert "elevator" in best.lower(), "the best reranked passage must be about the elevator, got: " + best[:60]
assert all(out["results"][i]["relevanceScore"] >= out["results"][i + 1]["relevanceScore"] for i in range(len(out["results"]) - 1)), "results must be ordered best first"
print("rerank returned", len(out["results"]), "results; best index", out["results"][0]["index"], "-> the elevator SOP")
