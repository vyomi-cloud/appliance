import gcp
import memory

client = gcp.vertex_client("v1beta1")
engine = memory.engine_name()
client.agent_engines.memories.create(name=engine, fact="Maria Ops prefers the boiler B-12 report on Mondays", scope={"user_id": "maria"})
found = list(client.agent_engines.memories.retrieve(name=engine, scope={"user_id": "maria"}, similarity_search_params={"search_query": "boiler", "top_k": 3}))
print("retrieved:", found[0].memory.fact)
assert "boiler" in found[0].memory.fact.lower()
other = list(client.agent_engines.memories.retrieve(name=engine, scope={"user_id": "someone-else"}, similarity_search_params={"search_query": "boiler", "top_k": 3}))
print("another user's memories:", len(other))
