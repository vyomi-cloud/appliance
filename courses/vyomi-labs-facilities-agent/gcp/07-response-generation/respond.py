import models
import rag_design
from search import search

SYSTEM = "Answer using only the context. Cite sources like [1]. If the context does not contain the answer, say so."


def grounded_answer(question, top_k=None):
    passages = search(question, top_k)
    best = max([p.get("score") or 0 for p in passages] or [0])
    if rag_design.grounding_threshold() > 0 and best < rag_design.grounding_threshold():       # your design: refuse when nothing retrieved is relevant enough
        return {"answer": "I can't answer that from the approved documents.", "citations": []}
    context = "\n".join(f"[{i + 1}] {p['text']}" for i, p in enumerate(passages))
    answer = models.chat(f"Context:\n{context}\n\nQuestion: {question}", system=SYSTEM)
    citations = [{"n": i + 1, "source": p["source"]} for i, p in enumerate(passages)]
    return {"answer": answer, "citations": citations}
