import time

import boto3

ac = boto3.client("bedrock-agentcore-control")
dp = boto3.client("bedrock-agentcore")
mid = next(m["id"] for m in ac.list_memories()["memories"] if m["id"].startswith("facilities_memory") or m.get("name") == "facilities_memory")

for role, text in (("USER", "Boiler B-12 is at 34 psi. What does the SOP say?"),
                   ("ASSISTANT", "Close the main steam valve, notify the duty engineer and raise a P1 work order [1].")):
    dp.create_event(memoryId=mid, actorId="maria", sessionId="s1", eventTimestamp=time.time(),
                    payload=[{"conversational": {"content": {"text": text}, "role": role}}])
print("2 conversational events written")

events = dp.list_events(memoryId=mid, actorId="maria", sessionId="s1", includePayloads=True)["events"]
print("replayed", len(events), "events for session s1")
