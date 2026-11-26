import time

import boto3

ac = boto3.client("bedrock-agentcore-control")
dp = boto3.client("bedrock-agentcore")
mid = next(m["id"] for m in ac.list_memories()["memories"] if m["id"].startswith("facilities_memory") or m.get("name") == "facilities_memory")

for actor, session, role, text in (
        ("maria", "s1", "USER", "I am the duty engineer for site HQ-1. I prefer P1 work orders for any boiler pressure fault."),
        ("maria", "s1", "ASSISTANT", "Noted, I will raise boiler pressure faults as P1 for you."),
        ("joe", "s9", "USER", "I work nights at HQ-2 and I always want elevator faults escalated to the vendor.")):
    dp.create_event(memoryId=mid, actorId=actor, sessionId=session, eventTimestamp=time.time(),
                    payload=[{"conversational": {"content": {"text": text}, "role": role}}])
print("2 conversational events written for maria, 1 for joe")

events = dp.list_events(memoryId=mid, actorId="maria", sessionId="s1", includePayloads=True)["events"]
print("replayed", len(events), "events for session s1")
assert len(events) == 2, "session s1 must replay exactly maria's two turns, not joe's"
