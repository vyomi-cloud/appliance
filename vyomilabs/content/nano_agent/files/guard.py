"""Guardrails: plain code that sits between the model and the world. The model proposes; these checks decide."""
import re

MAX_STEPS = 6
SUPPORT_NOTE = "The handbook and records do not contain an answer to this question."
INJECTION = re.compile(r"ignore (all |any |your |the )?(previous|prior|above|earlier)|disregard (all |your |the )?(rules|instructions)|system prompt|reveal your|you are now|developer mode", re.I)
TICKET_INTENT = re.compile(r"\b(ticket|work order)\b", re.I)
ASK_TICKET = re.compile(r"\b(file|raise|open|create|log|submit)\b[^.?!]*\b(ticket|work order)\b|\b(ticket|work order)\b[^.?!]*\b(for it|too|as well)\b", re.I)
ID_IN_TEXT = re.compile(r"\b(?:B|AHU|EL|WO)-\d{1,6}\b")


def check_input(question):
    """Refuse a message that tries to rewrite the agent's rules, before any model call."""
    if INJECTION.search(question):
        return "That message tries to change my instructions, so I will not act on it."
    return None


def check_action(act, question, ev, allowed):
    """None if the action may run, otherwise the reason it was rejected (told to the model, which may try once more)."""
    name = act["action"]
    if name not in allowed:
        return "action %s is not on this agent's allow-list" % name
    if name == "file_ticket" and not TICKET_INTENT.search(question):
        return "the user did not ask for a ticket, so file_ticket is not allowed for this question"
    sig = repr(sorted((k, v) for k, v in act.items()))
    if sig in ev["seen"]:
        return "you already did exactly this; use its result and pick answer or refuse"
    ev["seen"].add(sig)
    return None


def check_answer(act, question, ev):
    """An answer must rest on something the tools returned: evidence exists, and every number in it appears in that evidence."""
    if not ev["docs"] and not ev["records"]:
        return "you have no evidence yet; call a tool, or refuse if the handbook cannot answer"
    known = ev["text"] + " " + question
    for num in re.findall(r"\d+(?:\.\d+)?", act["text"]):
        if num not in known:
            return "the number %s is not in the tool results; do not invent values" % num
    return None


def check_complete(question, ev, ticket, ctx=""):
    """Before an answer is accepted: did the agent do what the question asked? A requested ticket must be filed; a named asset must be looked up.
    The message ends with the exact reply to send: a small model follows a template far better than a description."""
    ids = ID_IN_TEXT.findall(question)
    if ASK_TICKET.search(question) and not ticket:
        asset = next((i for i in ids if not i.startswith("WO-")), None) or (ID_IN_TEXT.findall(ctx) or ["B-12"])[-1]
        return 'the user asked for a ticket and you have not filed one. Reply exactly: {"action":"file_ticket","asset_id":"%s","summary":"<one line>","priority":"P2"}' % asset
    for rid in ids:
        if rid not in ev["records"] and not (ticket and not rid.startswith("WO-")):
            return 'the question names %s and you have not looked it up. Reply exactly: {"action":"lookup_record","id":"%s"}' % (rid, rid)
    return None
