import os

from ask_agent import ask

a = ask("facilities-session-" + "a" * 20)
print("hosted in another process:", a["pid"] != os.getpid())
print("route:", a["route"])
print("spans:", ", ".join(s["name"] for s in a["spans"] if s["kind"] == "agent"))
print("tools:", [(t["tool"], t["via"]) for t in a["tools"]])
print("answer:", a["answer"][:160])

b = ask("facilities-session-" + "b" * 20)
a2 = ask("facilities-session-" + "a" * 20)
print("different sessions use different processes:", a["pid"] != b["pid"])
print("the same session reuses its process:", a["pid"] == a2["pid"])
