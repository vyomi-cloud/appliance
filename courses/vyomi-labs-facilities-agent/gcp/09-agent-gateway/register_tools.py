import functions
import gateway
import rag
import rag_design

uri = functions.deploy("facilities-tools-mcp", "mcp_server_fn.py", env={"RAG_CORPUS": rag.corpus_name(), "RAG_TOP_K": str(rag_design.top_k())})
print("deployed facilities-tools-mcp")
direct = functions.call(uri, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
print("server publishes:", sorted(t["name"] for t in direct["result"]["tools"]))

registered = gateway.api("POST", gateway.BASE + f"/mcpServers?mcpServerId={gateway.MCP_SERVER}", {
    "endpoint": uri, "displayName": "Facilities tools (MCP)", "description": "kb_search, asset_status",
    "authentication": {"apiKey": {"value": "Bearer vyomi-local"}}})        # the credential the gateway presents to the tool server
print("registered:", registered["name"])
