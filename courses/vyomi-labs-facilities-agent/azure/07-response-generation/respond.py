from azlab import aoai, CHAT
from kb import kb_search
import rag_design

SYSTEM = "Answer using only the context. Cite sources like [1]. If the context does not contain the answer, say you do not know."


def answer(question, mode=None, top=None):
    hits = kb_search(question, mode or rag_design.search_type(), top)      # your design: search type and how many passages
    best = max([h.get("score") or 0 for h in hits] or [0])
    if rag_design.grounding_threshold() > 0 and best < rag_design.grounding_threshold():       # your design: refuse when nothing retrieved is relevant enough
        return {"answer": "I do not know: nothing in the approved documents is relevant enough.", "citations": []}
    citations = [{"n": i + 1, "source": h["source"], "text": h["text"][:160]} for i, h in enumerate(hits)]
    context = "\n".join(f"[{c['n']}] {h['text']}" for c, h in zip(citations, hits))
    r = aoai().chat.completions.create(model=CHAT, max_tokens=300, temperature=0, messages=[
        {"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}])
    return {"answer": r.choices[0].message.content, "citations": citations}
