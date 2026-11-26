"""The first agent: the model picks, the tools act. Two questions, one tool each."""
import agent

r = agent.run_turn("What is the status of AHU-7?", session_id="ch3-a")
print("steps:", [s["action"] for s in r["steps"]])
print("reply:", r["text"])
assert r["steps"][0]["action"] == "lookup_record", "the first action should be lookup_record"
assert r["type"] == "answer" and "degraded" in r["text"].lower(), r

r = agent.run_turn("How often should the AHU-7 filter be replaced?", session_id="ch3-b")
print("steps:", [s["action"] for s in r["steps"]])
print("reply:", r["text"])
assert r["steps"][0]["action"] == "search_docs", "the first action should be search_docs"
assert r["type"] == "answer" and "60" in r["text"], r
print("first agent ok")
