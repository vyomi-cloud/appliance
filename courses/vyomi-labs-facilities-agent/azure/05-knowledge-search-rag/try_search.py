from kb import kb_search

for mode, q in (("text", "boiler pressure exceeds 30 psi"), ("text", "AHU-7 supply air temperature drift chilled water valve"),
                ("vector", "what to do when boiler pressure is too high"), ("hybrid", "fire alarm evacuation procedure"),
                ("semantic", "who signs off on boiler work")):
    hits = kb_search(q, mode)
    extra = f" reranker={hits[0]['reranker']}" if mode == "semantic" else ""
    print(f"{mode:8} {q[:44]:44} -> {hits[0]['source']}{extra}")
print("every hit has a source:", all(h["source"] for h in kb_search("fire alarm evacuation")))
