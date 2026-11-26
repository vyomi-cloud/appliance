import rag_design

d = rag_design.load()
print("design file:", rag_design.source() or "none found, using the built-in defaults")
print("name:", d["name"], "| cloud:", d["cloud"])
c = d["chunking"]
print("chunking:", c["strategy"], "| maxTokens", c["maxTokens"], "| overlap", c["overlapPct"], "%")
e = d["embedding"]
print("embedding:", e["model"] or "the model this simulator hosts", "| dimensions", e["dimensions"] or "model default")
r = d["retrieve"]
print("retrieve: topK", r["topK"], "|", r["searchType"], "search", "| hybridWeight", r["hybridWeight"], "| filter", r["filter"])
rr = d["rerank"]
print("rerank:", "on, keep the best %d" % rr["topN"] if rr["enabled"] else "off")
print("generate: refuse below a grounding score of", d["generate"]["groundingThreshold"])
print("sources:", len(d["sources"]), "| golden questions:", len(d["golden"]))
bad = rag_design.problems()
print("design OK" if not bad else "design has %d problem(s); the defaults are used for those fields" % len(bad))
for p in bad:
    print("  -", p)
