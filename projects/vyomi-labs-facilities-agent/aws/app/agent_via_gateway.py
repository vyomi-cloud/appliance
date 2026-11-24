from ask_agent import ask

res = ask("facilities-session-" + "d" * 20)
print("tool calls:", [(t["tool"], t["via"]) for t in res["tools"] if t["tool"] != "create_work_order"])
print("cited sources:", sorted({c["source"] for c in res["citations"]}))
print("tools reached through the gateway:", all(t["via"] == "agentcore-gateway" for t in res["tools"] if t["tool"] in ("kb_search", "asset_status")))
