import math

from vymodels import BUDGET, chat, chat_with_tools, embed

reply = chat("Reply with the single word OK.")
assert reply.strip(), "the model returned no text"
print("chat:", reply)

TOOL = {"toolSpec": {"name": "asset_status", "description": "status of an asset by id",
                     "inputSchema": {"json": {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}}}}
r = chat_with_tools("What is the status of asset B-12?", [TOOL])
# The point of tool use: the model asked for the tool and named the right argument. A model that answers in prose instead has failed the lesson.
assert r["stop_reason"] == "tool_use" and r["tool_use"], "the model did not ask for the tool (stop_reason=%s)" % r["stop_reason"]
assert r["tool_use"]["name"] == "asset_status" and r["tool_use"]["input"].get("asset_id") == "B-12", "wrong tool call: %s" % r["tool_use"]
print("tools: stop_reason =", r["stop_reason"], "| asked for", r["tool_use"]["name"], r["tool_use"]["input"])


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b)) / math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))


v = embed("boiler pressure limit")
near, far = cosine(v, embed("maximum steam pressure for the boiler")), cosine(v, embed("cafeteria lunch menu"))
# Embeddings are only useful if related text lands closer than unrelated text.
assert near > far, "embeddings do not separate related from unrelated text (%.2f vs %.2f)" % (near, far)
print("embed: vector of", len(v), "numbers | related %.2f > unrelated %.2f" % (near, far))
print("notional cost so far: $%.5f over %d calls" % (BUDGET.spent, BUDGET.calls))
