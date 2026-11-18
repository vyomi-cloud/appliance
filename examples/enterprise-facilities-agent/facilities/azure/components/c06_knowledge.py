"""C6: knowledge search: Azure AI Search over the facilities-kb index: BM25, vector, hybrid (text + vector) and the semantic ranker; results carry the source for citations."""
from ..runtime import NAMES, LANE
from .. import search


def embed(ctx, texts):
    return [d.embedding for d in ctx.aoai().embeddings.create(model=NAMES["embed"], input=texts).data]


def run(ctx):
    search.ensure_search(ctx)

    def index():
        ic = search.index_client(ctx)
        ic.create_or_update_index(search.kb_index())
        got = ic.get_index(NAMES["index"])
        assert [f.name for f in got.fields] == ["id", "source", "title", "content", "content_vector"], [f.name for f in got.fields]
        return f"index {got.name} with vector field ({search.DIMS} dims) and semantic configuration"
    ctx.step("ai search: SearchIndexClient.create_or_update_index (text + vector + semantic)", index, lane=LANE["ai"])

    def vectors():
        sc = search.search_client(ctx)
        rows = list(sc.search(search_text="*", select=["id", "source", "content"], top=50))
        assert rows, "the index is empty: the knowledge pipeline (component 12) has not filled it"
        vecs = embed(ctx, [r["content"] for r in rows])
        res = sc.merge_documents([{"id": r["id"], "content_vector": v} for r, v in zip(rows, vecs)])
        assert all(r.succeeded for r in res), res
        ctx.state["kb_docs"] = {r["id"]: r["source"] for r in rows}
        return f"{len(rows)} documents embedded with the {NAMES['embed']} deployment and merged into content_vector"
    ctx.step("ai search: embed the indexed documents (azure openai embeddings) and merge_documents the vectors", vectors, lane=LANE["ai"])
    if not ctx.state.get("kb_docs"):
        return
    sc = search.search_client(ctx)

    def q(text=None, vec=None, **kw):
        from azure.search.documents.models import VectorizedQuery
        vq = [VectorizedQuery(vector=embed(ctx, [vec])[0], k_nearest_neighbors=3, fields="content_vector")] if vec else None
        return list(sc.search(search_text=text, vector_queries=vq, select=["id", "source", "title", "content"], top=3, **kw))

    def bm25():
        r = q("boiler pressure exceeds 30 psi")
        assert r and "boiler" in r[0]["source"].lower(), [(x["source"], x["@search.score"]) for x in r]
        ctx.state["citations"] = [(x["source"], x["content"]) for x in r]
        return f"top hit {r[0]['source']} score={r[0]['@search.score']}"
    ctx.step("ai search: SearchClient.search BM25 ranks the boiler SOP first", bm25, lane=LANE["ai"])

    def hvac():
        r = q("AHU-7 supply air temperature drift chilled water valve")
        assert r and "hvac" in r[0]["source"].lower(), [x["source"] for x in r]
        return f"top hit {r[0]['source']}"
    ctx.step("ai search: BM25 ranks the HVAC manual first for an AHU question", hvac, lane=LANE["ai"])

    def vector():
        r = q(None, vec="what to do when boiler pressure is too high")
        assert r and "boiler" in r[0]["source"].lower(), [(x["source"], x["@search.score"]) for x in r]
        return f"vector top hit {r[0]['source']}"
    ctx.step("ai search: vector query (VectorizedQuery on content_vector)", vector, lane=LANE["ai"])

    def hybrid():
        r = q("evacuation alarm", vec="fire alarm evacuation procedure")
        assert r and "fire" in r[0]["source"].lower(), [(x["source"], x["@search.score"]) for x in r]
        return f"hybrid (text + vector) top hit {r[0]['source']}"
    ctx.step("ai search: hybrid query (text + vector, RRF)", hybrid, lane=LANE["ai"])

    def semantic():
        r = q("who signs off on boiler work", query_type="semantic", semantic_configuration_name="sem")
        assert r and r[0].get("@search.reranker_score") is not None, [(x["source"], x.get("@search.reranker_score")) for x in r]
        return f"semantic ranker top hit {r[0]['source']} reranker={r[0]['@search.reranker_score']}"
    ctx.step("ai search: semantic ranker returns a reranker score", semantic, lane=LANE["ai"])

    def cited():
        r = q("fire alarm evacuation")
        assert r and all(x["content"] and x["source"] for x in r), "result without content or source"
        return f"{len(r)} results each with content + source blob name"
    ctx.step("ai search: results carry source names (needed for citations)", cited, lane=LANE["ai"])
