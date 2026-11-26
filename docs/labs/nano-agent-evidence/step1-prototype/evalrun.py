"""Run the fixed question set against the agent and score it. Usage: python evalrun.py"""
import json
import os
import sys
import time

from aws import ddb
from data import RECORDS
import evalset
from evalset import EVAL


def tickets():
    items = ddb.scan(TableName=RECORDS, FilterExpression="kind = :k", ExpressionAttributeValues={":k": {"S": "ticket"}}).get("Items", [])
    return {i["id"]["S"]: (i["asset_id"]["S"], i["priority"]["S"]) for i in items}


def grade(turn, res, new):
    why = []
    if res["type"] != turn["kind"]:
        why.append("ended with %s, wanted %s" % (res["type"], turn["kind"]))
    text = res["text"].lower()
    if turn.get("say") and not any(w in text for w in turn["say"]):
        why.append("reply lacks %s" % turn["say"])
    if turn.get("src") and turn["src"] not in res["sources"]:
        why.append("did not cite %s" % turn["src"])
    used = [s.get("action") for s in res["steps"]]
    for t in turn.get("tools", []):
        if t not in used:
            why.append("did not use %s" % t)
    want = turn["ticket"]
    if want == "none":
        if new:
            why.append("filed a ticket %s" % list(new.values()))
    elif list(new.values()) != [want]:
        why.append("tickets %s, wanted %s" % (list(new.values()), want))
    return why


def main(items=None):
    import agent
    results, t0 = [], time.time()
    for item in (items or EVAL):
        sess = "e-" + item["id"]
        ok, notes, calls, retries = True, [], 0, 0
        for i, turn in enumerate(item["turns"]):
            if turn.get("new_session"):
                sess += "-b"
            before = tickets()
            res = agent.run_turn(turn["q"], session_id=sess, user_id=item.get("user", "u-" + item["id"]))
            new = {k: v for k, v in tickets().items() if k not in before}
            why = grade(turn, res, new)
            calls += res["model_calls"]
            retries += res["retries"]
            if why:
                ok = False
                notes.append({"turn": i + 1, "why": why, "type": res["type"], "text": res["text"][:200], "steps": res["steps"]})
        results.append({"id": item["id"], "cat": item["cat"], "pass": ok, "calls": calls, "retries": retries, "notes": notes})
        print(("PASS " if ok else "FAIL ") + item["id"], "calls=%d retries=%d" % (calls, retries), json.dumps(notes)[:700] if notes else "", flush=True)
    by = {}
    for r in results:
        by.setdefault(r["cat"], []).append(r["pass"])
    print("SUMMARY", json.dumps({"pass": sum(r["pass"] for r in results), "total": len(results), "retries": sum(r["retries"] for r in results),
                                 "calls": sum(r["calls"] for r in results), "seconds": round(time.time() - t0),
                                 "by_cat": {c: "%d/%d" % (sum(v), len(v)) for c, v in by.items()}}))


if __name__ == "__main__":
    main()
