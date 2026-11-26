import boto3

ac = boto3.client("bedrock-agentcore-control")
dp = boto3.client("bedrock-agentcore")
mid = next(m["id"] for m in ac.list_memories()["memories"] if m["id"].startswith("facilities_memory") or m.get("name") == "facilities_memory")

import time
time.sleep(1)                       # extraction is asynchronous on real AWS; the simulator finishes within a moment


def recall(actor, query="boiler work order preference"):
    r = dp.retrieve_memory_records(memoryId=mid, namespace="/facts/%s/" % actor, searchCriteria={"searchQuery": query, "topK": 5})
    return [x["content"]["text"] for x in r.get("memoryRecordSummaries", [])]


maria, joe, stranger = recall("maria"), recall("joe"), recall("nobody")
print("long-term records for maria:", len(maria), "->", maria[:2])
assert maria and any("P1" in t for t in maria), "maria told the agent she prefers P1 work orders; that fact must be recalled"
assert joe and not any("P1" in t or "HQ-1" in t for t in joe), "joe's namespace must hold joe's facts only"
assert stranger == [], "an actor who never spoke must have no memory"
print("isolation holds: joe sees", len(joe), "of his own record(s), none of maria's; an unknown actor sees", len(stranger))
mem = ac.get_memory(memoryId=mid)["memory"]
assert mem.get("eventExpiryDuration") == 30, "events must expire (retention is a requirement, not a default)"
print("retention: events expire after", mem["eventExpiryDuration"], "days")
