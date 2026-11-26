"""Chapter 1: the agent loop, with no model yet.

An agent is a loop. Look at what you know, pick ONE action, run it, add the result to what you know, and repeat until you answer or run out of steps.
Here the "brain" is a few rules, so you can watch the loop on its own. In chapter 2 a language model takes the brain's place; the loop does not change."""

NOTES = {"B-12": "Boiler B-12 is RUNNING at 34 psi.", "AHU-7": "Air handling unit 7 is DEGRADED."}


def lookup(id):
    return NOTES.get(id, "There is no record " + id + ".")


TOOLS = {"lookup": lookup}          # the only things the agent can do besides answering


def rules(question, history):
    """A stand-in for the model. It sees the question and everything done so far, and returns the next action."""
    ids = [w.strip("?.,") for w in question.split() if "-" in w]
    if not history and ids:
        return {"action": "lookup", "id": ids[0]}
    if history:
        return {"action": "answer", "text": history[-1]["result"]}
    return {"action": "refuse", "reason": "I do not see an asset id in that question."}


def run(question, brain, max_steps=4):
    history = []
    for step in range(1, max_steps + 1):
        act = brain(question, history)
        print("step", step, "->", act)
        if act["action"] in ("answer", "refuse"):
            return {"kind": act["action"], "text": act.get("text") or act.get("reason"), "steps": step}
        result = TOOLS[act["action"]](act["id"])          # run the tool, then show the result to the brain on the next step
        history.append({"act": act, "result": result})
    return {"kind": "stopped", "text": "step limit reached", "steps": max_steps}


if __name__ == "__main__":
    r = run("What is the status of AHU-7?", rules)
    print("finished:", r["kind"], "after", r["steps"], "steps:", r["text"])
