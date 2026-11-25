import vymodels as models
from search import search

SYSTEM = "Answer using only the context. Cite sources like [1]. If the context does not contain the answer, say so."


def grounded_answer(question, top_k=3):
    passages = search(question, top_k)
    context = "\n".join(f"[{i + 1}] {p['text']}" for i, p in enumerate(passages))
    answer = models.chat(f"Context:\n{context}\n\nQuestion: {question}", system=SYSTEM)
    citations = [{"n": i + 1, "source": p["source"]} for i, p in enumerate(passages)]
    return {"answer": answer, "citations": citations}
