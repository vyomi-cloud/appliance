from azlab import aoai, CHAT
from kb import kb_search

SYSTEM = "Answer using only the context. Cite sources like [1]. If the context does not contain the answer, say you do not know."


def answer(question, mode="hybrid", top=3):
    hits = kb_search(question, mode, top)
    citations = [{"n": i + 1, "source": h["source"], "text": h["text"][:160]} for i, h in enumerate(hits)]
    context = "\n".join(f"[{c['n']}] {h['text']}" for c, h in zip(citations, hits))
    r = aoai().chat.completions.create(model=CHAT, max_tokens=300, temperature=0, messages=[
        {"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}])
    return {"answer": r.choices[0].message.content, "citations": citations}
