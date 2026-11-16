"""(3) Agent tool-choice reliability: 20 scripted prompts through bedrock-agent-runtime InvokeAgent (real boto3) against the REAL local model.

A prompt PASSES when the first action-group call is the expected function with the expected key argument (case-insensitive substring match on the
value), or, for the no-tool prompts, when NO action group was called. Reported: success rate, first-try rate, model invocations per prompt
(retries = model invocations beyond the tool call + final answer), failures with what was chosen instead.
"""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tools.mesh_verify import inproc
from tools.mesh_verify.common import save

# (prompt, expected function or None, expected arg name, expected arg substring)
CASES = [
    ("What is the status of room B2?", "get_room_status", "room", "B2"),
    ("Is conference room C14 currently occupied or free?", "get_room_status", "room", "C14"),
    ("Check the live status of room A-101 please.", "get_room_status", "room", "A-101"),
    ("Tell me whether room 3F-Lab is available right now.", "get_room_status", "room", "3F-Lab"),
    ("List the open work orders for building 7.", "list_open_work_orders", "building", "7"),
    ("Which maintenance tickets are still open in building North?", "list_open_work_orders", "building", "north"),
    ("Show me every unresolved work order for the Annex building.", "list_open_work_orders", "building", "annex"),
    ("Raise a work order: the chiller in plant room 2 is making a grinding noise.", "create_work_order", "description", "chiller"),
    ("Please open a maintenance ticket for a leaking tap in the level-3 kitchen.", "create_work_order", "description", "tap"),
    ("Create a high priority work order because the lobby lift is stuck between floors.", "create_work_order", "description", "lift"),
    ("File a work order for flickering lights in corridor D.", "create_work_order", "description", "light"),
    ("What is the current reading of sensor TEMP-42?", "get_sensor_reading", "sensor_id", "TEMP-42"),
    ("Read the humidity sensor HUM-7 for me.", "get_sensor_reading", "sensor_id", "HUM-7"),
    ("Give me the latest value from sensor CO2-12.", "get_sensor_reading", "sensor_id", "CO2-12"),
    ("I need a manager to approve replacing the cooling pump in plant room 2, ask for approval.", "request_approval", "summary", "pump"),
    ("Request sign-off from the approver for the 5,000 dollar generator repair.", "request_approval", "summary", "generator"),
    ("Hello, how are you today?", None, None, None),
    ("Thanks, that is all for now.", None, None, None),
    ("Write one sentence explaining what HVAC stands for.", None, None, None),
    ("What is 12 times 12?", None, None, None),
]
FN = lambda name, desc, params: {"name": name, "description": desc, "parameters": {k: {"type": "string", "description": d, "required": True} for k, d in params.items()}}
LAMBDA = """import json
def handler(e, c):
    return {'messageVersion': '1.0', 'response': {'actionGroup': e['actionGroup'], 'function': e['function'],
            'functionResponse': {'responseBody': {'TEXT': {'body': json.dumps({'ok': True, 'received': e['parameters']})}}}}}
"""


def main():
    url, kw, boto3 = inproc.start()
    ag, rt, lam = (boto3.client(n, **kw) for n in ("bedrock-agent", "bedrock-agent-runtime", "lambda"))
    arn = inproc.make_lambda(lam, "fac-tools", LAMBDA)
    a = ag.create_agent(agentName="mv-agent", foundationModel="amazon.nova-lite-v1:0", agentResourceRoleArn=inproc.ROLE,
                        instruction="You are the facilities assistant. Use the available functions to look up rooms, work orders and sensors, to raise work orders and to request approvals. "
                                    "Answer small talk and general questions directly without calling any function.")["agent"]
    aid = a["agentId"]
    ag.create_agent_action_group(agentId=aid, agentVersion="DRAFT", actionGroupName="facilities", actionGroupExecutor={"lambda": arn}, functionSchema={"functions": [
        FN("get_room_status", "Look up the live occupancy/status of one room", {"room": "room id"}),
        FN("list_open_work_orders", "List the open maintenance work orders of a building", {"building": "building name or number"}),
        FN("create_work_order", "Create a maintenance work order", {"description": "what is wrong"}),
        FN("get_sensor_reading", "Read the latest value of an IoT sensor", {"sensor_id": "sensor id"}),
        FN("request_approval", "Ask the human approver to sign off an action", {"summary": "what needs approval"})]})
    ag.prepare_agent(agentId=aid)
    al = ag.create_agent_alias(agentId=aid, agentAliasName="live")["agentAlias"]["agentAliasId"]
    rows = []
    for i, (prompt, fn, arg, sub) in enumerate(CASES):
        t = time.time()
        row = {"i": i, "prompt": prompt, "expect": fn, "error": None}
        try:
            r = rt.invoke_agent(agentId=aid, agentAliasId=al, sessionId=f"mv-{i}", inputText=prompt, enableTrace=True)
            evs = list(r["completion"])
            traces = [e["trace"]["trace"] for e in evs if "trace" in e]
            inv = [o["orchestrationTrace"]["invocationInput"] for o in traces if "orchestrationTrace" in o and "invocationInput" in o["orchestrationTrace"]]
            calls = [(x["actionGroupInvocationInput"].get("function"), {p["name"]: p["value"] for p in x["actionGroupInvocationInput"].get("parameters", [])})
                     for x in inv if x.get("invocationType") == "ACTION_GROUP"]
            row.update(calls=calls, model_invocations=sum(1 for o in traces if "orchestrationTrace" in o and "modelInvocationInput" in o["orchestrationTrace"]),
                       failures=[str(o.get("failureTrace"))[:120] for o in traces if "failureTrace" in o],
                       answer="".join(e["chunk"]["bytes"].decode() for e in evs if "chunk" in e)[:160])
            if fn is None:
                row["ok"] = not calls
            else:
                row["ok"] = bool(calls) and calls[0][0] == fn and sub.lower() in str(calls[0][1].get(arg, "")).lower()
                row["right_fn"] = bool(calls) and calls[0][0] == fn
        except Exception as e:     # noqa: BLE001
            row.update(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}")
        row["secs"] = round(time.time() - t, 1)
        rows.append(row)
        print(f"{'ok  ' if row['ok'] else 'FAIL'} {row['secs']:>5}s mi={row.get('model_invocations')} {prompt[:55]!r} -> {row.get('calls') or row.get('error') or 'no tool'}", flush=True)
    tool_rows = [r for r in rows if r["expect"]]
    none_rows = [r for r in rows if not r["expect"]]
    expected_mi = lambda r: 2 if r.get("calls") else 1
    summ = {"n": len(rows), "success": sum(r["ok"] for r in rows), "success_rate": round(sum(r["ok"] for r in rows) / len(rows), 3),
            "tool_prompts": len(tool_rows), "tool_success": sum(r["ok"] for r in tool_rows), "tool_right_function": sum(bool(r.get("right_fn")) for r in tool_rows),
            "no_tool_prompts": len(none_rows), "no_tool_success": sum(r["ok"] for r in none_rows),
            "prompts_with_retries": sum(1 for r in rows if r.get("model_invocations") and r["model_invocations"] > expected_mi(r)),
            "extra_model_invocations": sum(max(0, r.get("model_invocations", 0) - expected_mi(r)) for r in rows),
            "prompts_with_failure_trace": sum(1 for r in rows if r.get("failures")), "errors": sum(1 for r in rows if r["error"]),
            "mean_secs": round(sum(r["secs"] for r in rows) / len(rows), 1)}
    print(json.dumps(summ))
    save("agent_tools", {"summary": summ, "rows": rows})


main()
