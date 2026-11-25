import time

import boto3

from ask_agent import ARN, ask

ac = boto3.client("bedrock-agentcore-control")
rid = ARN.split("/")[-1]
rt = ac.get_agent_runtime(agentRuntimeId=rid)


def set_limit(n):
    ac.update_agent_runtime(agentRuntimeId=rid, agentRuntimeArtifact=rt["agentRuntimeArtifact"], roleArn=rt["roleArn"],
                            networkConfiguration=rt["networkConfiguration"],
                            environmentVariables=dict(rt.get("environmentVariables") or {}, AGENT_MAX_STEPS=str(n)))
    for _ in range(60):                                  # an update takes the runtime through UPDATING: wait for READY before the next call
        if ac.get_agent_runtime(agentRuntimeId=rid)["status"] == "READY":
            return
        time.sleep(0.5)
    raise AssertionError("runtime did not return to READY")


try:
    set_limit(2)
    r = ask("facilities-session-" + "r" * 20)
    assert r["stopped"] == "step_budget" and r["steps"] == 3, "the run must stop at the budget, got stopped=%s steps=%s" % (r["stopped"], r["steps"])
    assert "stopped" in r["answer"].lower() and not r["approval"], "a stopped run must say so and must not start an approval"
    assert not [t for t in r["tools"] if t["tool"] == "create_work_order"], "a stopped run must not reach the write tool"
    print("budget of 2 steps: stopped after", r["steps"] - 1, "steps ->", r["answer"])
finally:
    set_limit(12)
ok = ask("facilities-session-" + "s" * 20)
assert not ok["stopped"] and ok["steps"] >= 4 and ok["answer"].strip(), "with the normal budget the same question must complete"
print("normal budget: completed in", ok["steps"], "steps without stopping")
print("runaway protection verified")
