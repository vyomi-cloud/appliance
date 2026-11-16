"""vyomi-endurance stage 6 (AI) regressions found by the Terraform estate. Host + Pyodide.

    PYTHONPATH=. python3 tests/conformance/test_endurance_ai_core.py
"""
import json

from core import ai_models_core as am
from core import bedrock_guardrails_core as g


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  [PASS] {name}")


def run():
    class S:  # minimal account bag
        pass
    body = {"name": "gr1", "blockedInputMessaging": "x", "blockedOutputsMessaging": "y",
            "contentPolicyConfig": {"filtersConfig": [{"type": "HATE", "inputStrength": "HIGH", "outputStrength": "HIGH"}]},
            "tags": [{"key": "Estate", "value": "e"}]}
    r = am.bedrock_dispatch("POST", "/guardrails", {}, {}, json.dumps(body).encode())
    d = json.loads(r["body"])
    _check("F37 CreateGuardrail createdAt is an ISO string (Go SDK rejects a JSON number)", isinstance(d["createdAt"], str) and d["createdAt"].endswith("Z"))
    _check("F38 guardrail ARN uses the appliance account 123456789012", ":123456789012:guardrail/" in d["guardrailArn"])
    arn = d["guardrailArn"]
    lt = json.loads(am.bedrock_dispatch("POST", "/listTagsForResource", {}, {}, json.dumps({"resourceARN": arn}).encode())["body"])
    _check("F39 ListTagsForResource returns the create-time tags", lt["tags"] == [{"key": "Estate", "value": "e"}])
    am.bedrock_dispatch("POST", "/tagResource", {}, {}, json.dumps({"resourceARN": arn, "tags": [{"key": "A", "value": "b"}]}).encode())
    am.bedrock_dispatch("POST", "/untagResource", {}, {}, json.dumps({"resourceARN": arn, "tagKeys": ["Estate"]}).encode())
    lt = json.loads(am.bedrock_dispatch("POST", "/listTagsForResource", {}, {}, json.dumps({"resourceARN": arn}).encode())["body"])
    _check("F39 Tag/UntagResource round-trip", lt["tags"] == [{"key": "A", "value": "b"}])
    from core import bedrock_agents_core as ag
    v = ag._agent_view({"agentId": "A1", "agentName": "x"})
    cfgs = v["promptOverrideConfiguration"]["promptConfigurations"]
    _check("F40 an agent always carries its DEFAULT prompt configurations (the Terraform provider panics on nil)",
           {c["promptType"] for c in cfgs} >= {"PRE_PROCESSING", "ORCHESTRATION"} and all(c["promptCreationMode"] == "DEFAULT" for c in cfgs))
    _check("F40 an agent that sets its own override keeps it", ag._agent_view({"promptOverrideConfiguration": {"promptConfigurations": [{"promptType": "ORCHESTRATION", "promptCreationMode": "OVERRIDDEN"}]}})
           ["promptOverrideConfiguration"]["promptConfigurations"][0]["promptCreationMode"] == "OVERRIDDEN")
    _check("F42 an unset agent description is omitted", "description" not in ag._agent_view({"description": ""}))
    gid = arn.split("/")[-1]
    r = json.loads(am.bedrock_dispatch("POST", f"/guardrails/{arn}", {}, {}, json.dumps({"description": "v1"}).encode())["body"])
    _check("F41 CreateGuardrailVersion accepts the guardrail ARN as identifier", r["guardrailId"] == gid and r["version"] == "1")
    v1 = json.loads(am.bedrock_dispatch("GET", f"/guardrails/{arn}", {"guardrailVersion": "1"}, {}, b"")["body"])
    _check("F43 a guardrail version carries its own description", v1["description"] == "v1")
    class _Acct:
        account = {}
    ra = ag.dispatch(_Acct, "PUT", "/agents/", {}, {}, json.dumps({"agentName": "ag1", "agentResourceRoleArn": "arn:aws:iam::123456789012:role/r",
                     "foundationModel": "vyomi.qwen2.5-3b", "instruction": "x" * 40, "tags": {"Estate": "e"}}).encode())
    aarn = json.loads(ra["body"])["agent"]["agentArn"]
    lt = json.loads(ag.dispatch(_Acct, "GET", "/tags/" + aarn, {}, {}, b"")["body"])
    _check("F44 Bedrock Agents ListTagsForResource returns create-time tags", lt["tags"] == {"Estate": "e"})
    print("Endurance AI regressions: ALL GREEN")


if __name__ == "__main__":
    run()
