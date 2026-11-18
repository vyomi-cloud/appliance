"""C7: tools as Cloud Run functions over Firestore: deploy, seed, invoke over HTTPS. kb-search (RAG), asset-status (Firestore), MCP tool server,
approval decision + create-work-order (the write tool, behind the approval)."""
from ..runtime import NAMES, LANE, need_grpc
from .. import deploy


def run(ctx):
    def seed():
        need_grpc(ctx, "firestore")
        deploy.seed(ctx, NAMES["assets"], deploy.fixture("assets.json"), "asset_id")
        deploy.seed(ctx, NAMES["work_orders"], deploy.fixture("work_orders.json"), "work_order_id")
        return "3 assets, 3 work orders in Firestore (SDK default gRPC)"
    ctx.step("firestore: seed fixture assets + work orders (firestore.Client)", seed)

    def dep():
        ctx.state["kb_uri"] = deploy.deploy_function(ctx, "facilities-kb-search", "kb_search")
        ctx.state["asset_uri"] = deploy.deploy_function(ctx, "facilities-asset-status", "asset_status")
        ctx.state["mcp_uri"] = deploy.deploy_function(ctx, "facilities-tools-mcp", "mcp_server")
        ctx.state["decide_uri"] = deploy.deploy_function(ctx, "facilities-approval-decision", "decide_approval")
        ctx.state["wo_uri"] = deploy.deploy_function(ctx, "facilities-create-work-order", "create_work_order")
        return "5 functions deployed (kb-search, asset-status, tools-mcp, approval-decision, create-work-order)"
    ctx.step("cloud functions gen2: generateUploadUrl + PUT zip + CreateFunction x5", dep)

    def kb_tool():
        out = deploy.call_function(ctx, ctx.state["kb_uri"], {"query": "boiler pressure limit"})
        assert out["results"] and "boiler" in out["results"][0]["text"].lower(), out
        return f"read-only knowledge tool returned {len(out['results'])} cited results (RAG client inside the function)"
    if ctx.state.get("kb_uri") and ctx.state.get("rag_corpus"):
        ctx.step("cloud run function: kb-search tool (Vertex RAG retrieveContexts from inside the function)", kb_tool, lane=LANE["sandbox"])

    def asset_tool():
        out = deploy.call_function(ctx, ctx.state["asset_uri"], {"asset_id": "B-12"})
        assert out["found"] and out["asset"]["asset_id"] == "B-12" and len(out["work_orders"]) == 1, out
        return f"B-12 status={out['asset']['status']}, open work orders={len(out['work_orders'])}"
    if ctx.state.get("asset_uri"):
        ctx.step("cloud run function: asset-status tool (Firestore read from inside the function)", asset_tool, lane=LANE["sandbox"])
