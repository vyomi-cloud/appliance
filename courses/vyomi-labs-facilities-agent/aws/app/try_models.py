from models import chat, chat_with_tools, embed

print("chat:", chat("Reply with the single word OK."))

TOOL = {"toolSpec": {"name": "asset_status", "description": "status of an asset by id",
                     "inputSchema": {"json": {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}}}}
r = chat_with_tools("What is the status of asset B-12?", [TOOL])
print("tools: stop_reason =", r["stop_reason"])

v = embed("boiler pressure limit")
print("embed: vector of", len(v), "numbers")
