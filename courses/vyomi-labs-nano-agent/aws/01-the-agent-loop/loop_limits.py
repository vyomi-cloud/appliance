"""Two things every loop needs: a way to say "I cannot", and a limit that stops it when the brain never decides."""
from loop import rules, run


def never_decides(question, history):
    return {"action": "lookup", "id": "B-12"}               # keeps asking for the same record forever


r = run("What is the status of B-12?", never_decides, max_steps=3)
assert r["kind"] == "stopped" and r["steps"] == 3, r
print("the step limit stopped a loop that never answers")

r = run("Is the cafeteria open?", rules)
assert r["kind"] == "refuse", r
print("the loop refused a question it cannot support")
print("loop limits ok")
