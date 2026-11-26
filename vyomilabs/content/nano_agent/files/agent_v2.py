"""Chapter 4: the same loop, now with memory. Before the first model call the agent loads what it knows about the user and the session; after the
turn it saves a conversation note. A message that starts "remember that ..." is handled by the runtime itself, with no model call."""
from llmx import BadAction, ask
from memory import load_context, remember, save_turn
from tools import REGISTRY, TOOLS

ALLOWED = TOOLS + ("answer", "refuse")
MAX_STEPS = 6


def nudge(out, ev):
    """What the model sees after a tool result: the state of the turn, and the exact shape of the reply that fits it."""
    answer = ' Reply {"action":"answer","text":"..."} with one or two sentences that use only the text above, unless the question asks for something you have not done yet.'
    if out["ticket"]:
        return "The ticket is filed. If the user also asked what a document says, call search_docs next; otherwise reply with an answer action." + answer
    if ev["docs"] or ev["records"]:
        return "You now have evidence." + answer
    return 'Nothing useful was found yet. If the question names an id call lookup_record, otherwise reply {"action":"refuse","reason":"not in the handbook"}.'


def run_turn(question, session_id="s1", user_id="u1", allowed=ALLOWED, max_steps=MAX_STEPS):
    out = {"type": "refuse", "text": "", "sources": [], "steps": [], "ticket": None, "model_calls": 0, "retries": 0}
    stats = {}
    ctx, n_turns = load_context(session_id, user_id)

    def finish(kind, text, sources=()):
        out.update(type=kind, text=text, sources=list(sources), model_calls=stats.get("model_calls", 0), retries=stats.get("retries", 0))
        save_turn(session_id, n_turns, question, text)
        return out

    note = remember(user_id, question)
    if note:
        return finish("answer", "Noted. I will remember: %s" % note)
    ev = {"docs": set(), "records": set()}
    messages = [{"role": "user", "content": ((ctx + "\n") if ctx else "") + "Question: " + question}]
    for step in range(max_steps):
        have = bool(ev["docs"] or ev["records"])
        menu = tuple(x for x in allowed if not (x == "refuse" and have) and not (x == "answer" and not have and not out["ticket"]))
        try:
            act, raw, _ = ask(messages, menu, stats)
        except BadAction as e:
            stats["model_calls"] = stats.get("model_calls", 0) + 2
            out["steps"].append({"invalid": str(e)[:120]})
            return finish("refuse", "I could not turn that into a safe action, so I will not guess.")
        out["steps"].append({"action": act["action"], **{k: v for k, v in act.items() if k not in ("action", "text")}})
        name = act["action"]
        if name == "answer":
            srcs = [s for s in act["sources"] if s in ev["docs"] or s in ev["records"]] or sorted(ev["docs"] | ev["records"])
            return finish("answer", act["text"], srcs)
        if name == "refuse":
            return finish("refuse", act["reason"][:300])
        observation, got = REGISTRY[name](session_id=session_id, **{k: v for k, v in act.items() if k != "action"})
        ev["docs"].update(got.get("docs", []))
        ev["records"].update(got.get("records", []))
        if got.get("ticket"):
            out["ticket"], out["ticket_text"] = got["ticket"], got["ticket_text"]
        messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": "Result:\n%s\n%s" % (observation, nudge(out, ev))}]
    return finish("refuse", "I reached my step limit without an answer.")
