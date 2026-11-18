"""GCP adapter for the cloud-neutral LangGraph agents (facilities/agents.py): Gemini on Vertex for the model, the agent gateway (MCP) or the tool
functions for tools, Pub/Sub + the Firestore ledger for the human-approval write path, Firestore for statistics."""
import json, time
from .runtime import NAMES, is_model_missing
from . import deploy

MODEL = "gemini-2.0-flash"


class GcpIO:
    def __init__(self, ctx):
        self.ctx = ctx

    def converse(self, system, text, max_tokens=300):
        """Returns the model text or None when no model is reachable."""
        ctx = self.ctx
        try:
            from google.genai import types
            r = ctx.genai().models.generate_content(model=MODEL, contents=text, config=types.GenerateContentConfig(
                system_instruction=system, max_output_tokens=max_tokens, temperature=0))
            return r.text
        except Exception as e:
            ctx.state["llm_error"] = f"{type(e).__name__}: {str(e)[:120]}"
            return None

    def call_tool(self, tool, args):
        """Through the agent gateway (MCP tools/call) when it serves the tool, otherwise a direct HTTPS call to the tool function."""
        ctx = self.ctx
        if ctx.state.get("gateway_tools_ok"):
            res = mcp_call(ctx, ctx.state["gateway_mcp_url"], "tools/call", {"name": [n for n in ctx.state["mcp_tools"] if n.endswith("___" + tool) or n == tool][0], "arguments": args})
            return (json.loads(res["content"][0]["text"]) if res.get("content") else res), "agent-gateway"
        return deploy.call_function(ctx, ctx.state[{"kb_search": "kb_uri", "asset_status": "asset_uri"}[tool]], args), "function-direct"

    def start_approval(self, rid, payload):
        """Write path: ledger row PENDING + a message on the approval topic. Nothing is written to work-orders until an approver decides."""
        ctx = self.ctx
        ctx.firestore().collection(NAMES["ledger"]).document(rid).set(dict(payload, status="PENDING", ts=int(time.time())))
        pub, _ = ctx.pubsub()
        pub.publish(f"projects/{ctx.project}/topics/{NAMES['topic']}", json.dumps(payload).encode(), requester=payload.get("requester", ""), kind="work-order").result(timeout=30)
        return {"request_id": rid, "status": "PENDING_APPROVAL"}, "pubsub-approval"

    def work_orders(self):
        return [d.to_dict() for d in self.ctx.firestore().collection(NAMES["work_orders"]).stream()], "firestore"


def mcp_call(ctx, url, method, params=None):
    """MCP over streamable HTTP (JSON-RPC 2.0) to the agent gateway's mcpEndpoint."""
    r = ctx.authed_session().post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, timeout=60)
    r.raise_for_status()
    out = r.json()
    if "error" in out:
        raise RuntimeError(f"MCP error: {out['error']}")
    return out["result"]
