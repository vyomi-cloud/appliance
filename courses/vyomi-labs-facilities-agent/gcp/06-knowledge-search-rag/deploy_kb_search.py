import functions
import rag
import rag_design

uri = functions.deploy("facilities-kb-search", "kb_search_fn.py", env={"RAG_CORPUS": rag.corpus_name(), "RAG_TOP_K": str(rag_design.top_k())})
out = functions.call(uri, {"query": "boiler pressure limit"})
print("deployed facilities-kb-search; first source:", out["results"][0]["source"])
assert "boiler" in out["results"][0]["text"].lower()
print("kb-search returned", len(out["results"]), "cited results")
