import os

from ask_agent import ask

a = ask("facilities-session-" + "a" * 20)
print("hosted in another process:", a["pid"] != os.getpid())
assert a["pid"] != os.getpid(), "the agent must run inside the runtime, not in this script"
assert a["route"] and a["answer"].strip() and a["spans"], "the agent must route, answer and emit spans"
print("route:", a["route"])
print("spans:", ", ".join(s["name"] for s in a["spans"] if s["kind"] == "agent"))
print("tools:", [(t["tool"], t["via"]) for t in a["tools"]])
print("answer:", a["answer"][:160])

b = ask("facilities-session-" + "b" * 20)
a2 = ask("facilities-session-" + "a" * 20)
print("different sessions use different processes:", a["pid"] != b["pid"])
print("the same session reuses its process:", a["pid"] == a2["pid"])
assert a["pid"] != b["pid"], "two sessions must not share a process (isolation)"
assert a["pid"] == a2["pid"], "one session must keep its process (state)"
