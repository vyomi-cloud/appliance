import gcp
import memory

client = gcp.vertex_client("v1beta1")
client.agent_engines.memories.generate(
    name=memory.engine_name(), scope={"user_id": "maria"},
    direct_contents_source={"events": [{"content": {"role": "user", "parts": [{"text": "I always want the level 3 chiller report on Mondays."}]}}]})
print("memories generated from the conversation")
