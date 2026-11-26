"""Chapter 7: Lambda here loads ONE module, so the agent's modules are joined into a single file. The imports between them are dropped (the names are now
in the same file); everything else is byte for byte what you ran in chapters 2 to 6, plus a six-line handler."""
import re

ORDER = ["data", "aws", "llmx", "rag", "tools", "memory", "guard", "agent"]
HANDLER = '''
def handler(event, context):
    """event: {"question": ..., "session_id": ..., "user_id": ...}"""
    r = run_turn(event["question"], session_id=event.get("session_id", "s"), user_id=event.get("user_id", "u"))
    return {"type": r["type"], "text": r["text"], "sources": r["sources"], "steps": r["steps"], "ticket": r["ticket"], "model_calls": r["model_calls"], "retries": r["retries"]}
'''


def build():
    own = re.compile(r"^(from|import) (%s)\b" % "|".join(ORDER))
    parts = []
    for name in ORDER:
        lines = [l for l in open(name + ".py").read().splitlines() if not own.match(l)]
        parts.append("# ---- %s.py ----\n" % name + "\n".join(lines))
    return "\n\n".join(parts) + "\n" + HANDLER


if __name__ == "__main__":
    src = build()
    open("handler.py", "w").write(src)
    compile(src, "handler.py", "exec")
    print("handler.py:", len(src.splitlines()), "lines from", len(ORDER), "modules")
