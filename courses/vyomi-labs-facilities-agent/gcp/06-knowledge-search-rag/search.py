import gcp
import rag
import rag_design

CORPUS = rag.corpus_name()


def search(question, top_k=None):
    cfg = {"top_k": top_k or rag_design.top_k()}                  # your design: how many passages (the v1 client has no hybrid setting, so searchType is not applied here)
    r = rag.search_client().retrieve_contexts(request={
        "parent": gcp.PARENT, "query": {"text": question, "rag_retrieval_config": cfg},
        "vertex_rag_store": {"rag_resources": [{"rag_corpus": CORPUS}]}})
    return [{"source": c.source_uri, "score": round(c.score, 3), "text": c.text} for c in r.contexts.contexts]


if __name__ == "__main__":
    for q in ("What should I do when boiler pressure exceeds 30 psi?", "AHU-7 supply air temperature drift chilled water valve"):
        hits = search(q)
        print(q[:40], "->", hits[0]["source"], hits[0]["score"])
        assert all(h["text"] and h["source"] for h in hits), "every passage must carry its source"
    print("every passage carries text and a gs:// source")
