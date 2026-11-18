"""MCP server (streamable HTTP, JSON-RPC 2.0) exposing the two read-only tools. This is what the agent gateway registers (mcpServers) and fronts.
Write actions are deliberately NOT exposed: they go through the approval flow (components 5 and 7)."""
from tools import kb_search, asset_status
import json

TOOLS = [
    {"name": "kb_search", "description": "Search the facilities knowledge base (read-only).",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "asset_status", "description": "Look up an asset and its work orders (read-only).",
     "inputSchema": {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}},
]
IMPL = {"kb_search": kb_search, "asset_status": asset_status}


def _reply(rid, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": rid}
    out.update({"error": error} if error else {"result": result})
    return out


def handler(request):
    msg = request.get_json(silent=True) or {}
    rid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return _reply(rid, {"protocolVersion": params.get("protocolVersion", "2025-03-26"), "capabilities": {"tools": {}},
                            "serverInfo": {"name": "facilities-tools", "version": "1.0.0"}})
    if method and method.startswith("notifications/"):
        return {}
    if method == "tools/list":
        return _reply(rid, {"tools": TOOLS})
    if method == "tools/call":
        fn = IMPL.get(params.get("name"))
        if not fn:
            return _reply(rid, error={"code": -32602, "message": f"unknown tool {params.get('name')}"})
        try:
            return _reply(rid, {"content": [{"type": "text", "text": json.dumps(fn(params.get("arguments") or {}))}], "isError": False})
        except Exception as e:
            return _reply(rid, {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True})
    return _reply(rid, error={"code": -32601, "message": f"method not found: {method}"})
