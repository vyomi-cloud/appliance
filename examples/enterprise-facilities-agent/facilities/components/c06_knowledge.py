"""C6: knowledge search layer: Bedrock KB Retrieve (vector), metadata/semantic ranking, rerank."""
from ..runtime import Blocked


def run(ctx):
    rt = ctx.client("bedrock-agent-runtime")
    kid = ctx.state.get("kb_id")
    if not kid:
        ctx.step("retrieve", lambda: (_ for _ in ()).throw(Blocked("knowledge", "no knowledge base was created")))
        return

    def search(q, k=3):
        r = rt.retrieve(knowledgeBaseId=kid, retrievalQuery={"text": q},
                        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": k}})["retrievalResults"]
        return r

    def boiler():
        r = search("What should I do when boiler pressure exceeds 30 psi?")
        assert r, "no results"
        top = r[0]
        uri = top.get("location", {}).get("s3Location", {}).get("uri", "")
        assert "boiler-sop" in uri, f"top hit was {uri or top['content']['text'][:60]}"
        ctx.state["citations"] = [(x.get("location", {}).get("s3Location", {}).get("uri", ""), x["content"]["text"]) for x in r]
        return f"top hit {uri} score={top.get('score')}"
    ctx.step("bedrock-agent-runtime: Retrieve ranks the boiler SOP first", boiler)

    def hvac():
        r = search("AHU-7 supply air temperature drift chilled water valve")
        uri = r[0].get("location", {}).get("s3Location", {}).get("uri", "") if r else ""
        assert "hvac" in uri, f"top hit {uri}"
        return f"top hit {uri}"
    ctx.step("bedrock-agent-runtime: Retrieve ranks the HVAC manual first for an AHU question", hvac)

    def cited():
        r = search("fire alarm evacuation")
        assert all(x["content"]["text"] and x.get("location") for x in r), "result without text or source location"
        return f"{len(r)} results each with text + S3 source"
    ctx.step("retrieve results carry source locations (needed for citations)", cited)

    def rerank():
        r = search("elevator door fault", 4)
        out = rt.rerank(queries=[{"type": "TEXT", "textQuery": {"text": "elevator door fault"}}],
                        sources=[{"type": "INLINE", "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": x["content"]["text"]}}} for x in r],
                        rerankingConfiguration={"type": "BEDROCK_RERANKING_MODEL", "bedrockRerankingConfiguration": {
                            "numberOfResults": 2, "modelConfiguration": {"modelArn": f"arn:aws:bedrock:{ctx.region}::foundation-model/amazon.rerank-v1:0"}}})
        assert out["results"], "no rerank results"
        return f"rerank returned {len(out['results'])} results"
    ctx.step("bedrock-agent-runtime: Rerank", rerank, lane="knowledge")
