import boto3

ac = boto3.client("bedrock-agentcore-control")
dp = boto3.client("bedrock-agentcore")
mid = next(m["id"] for m in ac.list_memories()["memories"] if m["id"].startswith("facilities_memory") or m.get("name") == "facilities_memory")

r = dp.retrieve_memory_records(memoryId=mid, namespace="/facts/maria/", searchCriteria={"searchQuery": "boiler", "topK": 3})
print("long-term records for maria:", len(r.get("memoryRecordSummaries", [])))
