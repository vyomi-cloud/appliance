from google.genai import types

from vymodels import chat, chat_with_tools, embed

print("chat:", chat("Reply with the single word OK."))

ASSET_STATUS = types.FunctionDeclaration(
    name="asset_status", description="status of an asset by id",
    parameters=types.Schema(type="OBJECT", properties={"asset_id": types.Schema(type="STRING")}, required=["asset_id"]))
r = chat_with_tools("What is the status of asset B-12?", [ASSET_STATUS])
print("tools: the model asked for", r["calls"])

v = embed(["boiler pressure limit", "boiler pressure maximum", "elevator contract renewal"])
cos = lambda a, b: sum(x * y for x, y in zip(a, b)) / ((sum(x * x for x in a) ** .5) * (sum(y * y for y in b) ** .5))
print("embed: vectors of", len(v[0]), "numbers; paraphrase %.2f, unrelated %.2f" % (cos(v[0], v[1]), cos(v[0], v[2])))
