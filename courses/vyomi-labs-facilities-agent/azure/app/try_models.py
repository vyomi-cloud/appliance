from models import chat, chat_with_tools, embed

print("chat:", chat("Reply with the single word OK."))

TOOL = {"type": "function", "function": {"name": "asset_status", "description": "Look up an asset by id",
        "parameters": {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}}}
r = chat_with_tools("What is the status of asset B-12?", [TOOL])
print("tools: finish_reason =", r["finish_reason"], "| tool =", r["tool_use"])

print("embed: vector of", len(embed("boiler pressure limit")), "numbers")
