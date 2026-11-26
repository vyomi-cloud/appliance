import time

import boto3

ac = boto3.client("bedrock-agentcore-control")
m = ac.create_memory(name="facilities_memory", eventExpiryDuration=30,
                     memoryStrategies=[{"semanticMemoryStrategy": {"name": "facts", "namespaces": ["/facts/{actorId}/"]}}])["memory"]
for _ in range(30):
    status = ac.get_memory(memoryId=m["id"])["memory"]["status"]
    if status != "CREATING":
        break
    time.sleep(0.5)
print("memory", m["id"], status)
