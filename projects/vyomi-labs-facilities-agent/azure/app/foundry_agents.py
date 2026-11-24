import time
from azure.ai.agents import AgentsClient
from azlab import ENDPOINT, DevToken, CHAT

client = AgentsClient(endpoint=f"{ENDPOINT}/api/projects/facilities-project", credential=DevToken())

TOOLS = [
    {"type": "function", "function": {"name": "kb_search", "description": "Search the facilities knowledge base (read-only).",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "asset_status", "description": "Look up an asset and its work orders (read-only).",
        "parameters": {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}}},
    {"type": "function", "function": {"name": "create_work_order", "description": "Request a work order (needs human approval).",
        "parameters": {"type": "object", "properties": {"asset_id": {"type": "string"}, "summary": {"type": "string"}}, "required": ["asset_id", "summary"]}}},
]
AGENTS = (("facilities_supervisor", "You route facilities requests to the Facilities, Maintenance and Analytics agents and combine their answers.", TOOLS),
          ("facilities_facilities", "Answer from the knowledge base only, with citations.", TOOLS[:1]),
          ("facilities_maintenance", "Look up assets and raise work orders (approval required).", TOOLS[1:]),
          ("facilities_analytics", "Count and summarise work orders.", []))
ids = {}
for name, instructions, tools in AGENTS:
    ids[name] = client.create_agent(model=CHAT, name=name, instructions=instructions, tools=tools).id
print("agents:", sorted(a.name for a in client.list_agents() if a.name in ids))

thread = client.threads.create()
client.messages.create(thread_id=thread.id, role="user", content="Boiler B-12 is at 34 psi. What does the SOP say?")
run = client.runs.create(thread_id=thread.id, agent_id=ids["facilities_supervisor"])
for _ in range(60):
    run = client.runs.get(thread_id=thread.id, run_id=run.id)
    if str(run.status).lower().split(".")[-1] not in ("queued", "in_progress"):
        break
    time.sleep(0.5)
print("supervisor run:", str(run.status).lower().split(".")[-1], "| messages on the thread:", len(list(client.messages.list(thread_id=thread.id))))
