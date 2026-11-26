import json
import time

import gateway

url = gateway.api("GET", gateway.BASE + f"/agentGateways/{gateway.GATEWAY}")["mcpEndpoint"]
names = set()
for _ in range(20):
    names = {t["name"] for t in gateway.mcp(url, "tools/list")["tools"]}
    if names:
        break
    time.sleep(0.5)
print("catalogue:", sorted(names))
status_tool = next(n for n in names if n.endswith("asset_status"))
res = gateway.mcp(url, "tools/call", {"name": status_tool, "arguments": {"asset_id": "B-12"}})
assert not res.get("isError"), res
out = json.loads(res["content"][0]["text"])
print("asset_status via gateway:", out["asset"]["asset_id"], out["asset"]["status"])
