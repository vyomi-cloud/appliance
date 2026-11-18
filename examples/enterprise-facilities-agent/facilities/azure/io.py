"""Azure adapter for the cloud-neutral LangGraph agents (facilities/agents.py): Azure OpenAI for the model, the APIM gateway (REST operations or MCP) or the
Function App tool functions for tools, Service Bus + the Azure Table ledger for the human-approval write path, Azure Table storage for statistics."""
import json, time
from .runtime import NAMES
from . import deploy


class AzureIO:
    def __init__(self, ctx):
        self.ctx = ctx

    def converse(self, system, text, max_tokens=300):
        """Returns the model text or None when no model is reachable."""
        ctx = self.ctx
        try:
            r = ctx.aoai().chat.completions.create(model=NAMES["chat"], max_tokens=max_tokens, temperature=0,
                                                   messages=[{"role": "system", "content": system}, {"role": "user", "content": text}])
            return r.choices[0].message.content
        except Exception as e:
            ctx.state["llm_error"] = f"{type(e).__name__}: {str(e)[:120]}"
            return None

    def call_tool(self, tool, args):
        """Through the APIM gateway (MCP tools/call, else the tool's REST operation) when it serves the tool, otherwise a direct call to the Function App."""
        ctx = self.ctx
        if ctx.state.get("gateway_tools_ok"):
            if ctx.state.get("apim_mcp_ok"):
                name = [n for n in ctx.state["mcp_tools"] if n.replace("-", "_").endswith(tool)][0]
                res = apim_mcp(ctx, "tools/call", {"name": name, "arguments": args})
                return (json.loads(res["content"][0]["text"]) if res.get("content") else res), "apim-mcp"
            import requests
            r = requests.post(ctx.apim_url(f"tools/{tool.replace('_', '-')}"), json=args, headers=apim_headers(ctx), timeout=60)
            r.raise_for_status()
            return r.json(), "apim-gateway"
        return deploy.call_function(ctx, NAMES["functions"], tool.replace("_", "-"), args), "function-direct"

    def start_approval(self, rid, payload):
        """Write path: ledger row PENDING + a message on the approval topic. Nothing is written to workorders until an approver decides."""
        from azure.servicebus import ServiceBusMessage
        ctx = self.ctx
        ctx.table(NAMES["ledger"]).upsert_entity(dict(PartitionKey="req", RowKey=rid, status="PENDING", ts=int(time.time()), **payload))
        with ctx.servicebus() as c, c.get_topic_sender(NAMES["topic"]) as s:
            s.send_messages(ServiceBusMessage(json.dumps(payload), subject="work-order", application_properties={"requester": payload.get("requester", ""), "kind": "work-order"}))
        return {"request_id": rid, "status": "PENDING_APPROVAL"}, "servicebus-approval"

    def work_orders(self):
        rows = [{k: v for k, v in dict(e).items() if k not in ("PartitionKey", "RowKey")} for e in self.ctx.table(NAMES["work_orders"]).list_entities()]
        return rows, "azure-table"


def apim_headers(ctx):
    h = {"Ocp-Apim-Subscription-Key": ctx.state.get("apim_key", ""), "Content-Type": "application/json"}
    if ctx.state.get("access_token"):
        h["Authorization"] = "Bearer " + ctx.state["access_token"]
    return h


def apim_mcp(ctx, method, params=None):
    """MCP over streamable HTTP (JSON-RPC 2.0) to the APIM MCP server."""
    import requests
    r = requests.post(ctx.apim_url("mcp"), json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, headers=apim_headers(ctx), timeout=60)
    r.raise_for_status()
    out = r.json()
    if "error" in out:
        raise RuntimeError(f"MCP error: {out['error']}")
    return out["result"]
