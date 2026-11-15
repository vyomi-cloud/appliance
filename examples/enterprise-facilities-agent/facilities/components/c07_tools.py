"""C7: Lambda tools. Deploy the four functions, seed DynamoDB, call them through lambda:Invoke."""
import json
from ..runtime import NAMES, aws_json
from .. import deploy


def run(ctx):
    lam = ctx.client("lambda")
    ctx.step("dynamodb: create tables (assets, work orders, approval ledger)", lambda: [deploy.make_table(ctx, NAMES["assets"], "asset_id"),
             deploy.make_table(ctx, NAMES["work_orders"], "work_order_id"), deploy.make_table(ctx, NAMES["ledger"], "request_id")] and "3 tables")
    ctx.step("dynamodb: seed fixture assets + work orders", lambda: (deploy.seed(ctx, NAMES["assets"], deploy.fixture("assets.json")),
             deploy.seed(ctx, NAMES["work_orders"], deploy.fixture("work_orders.json"))) and "3 assets, 3 work orders")
    env = deploy.lambda_env(ctx)

    def dep():
        ctx.state["kb_lambda_arn"] = deploy.deploy_lambda(ctx, "facilities-kb-search", "kb_search", env)
        deploy.deploy_lambda(ctx, "facilities-asset-status", "asset_status", env)
        deploy.deploy_lambda(ctx, "facilities-request-approval", "request_approval", env)
        deploy.deploy_lambda(ctx, "facilities-create-work-order", "create_work_order", env)
        return "4 functions deployed"
    ctx.step("lambda: CreateFunction x4 (kb-search, asset-status, request-approval, create-work-order)", dep)

    def inv(fn, payload):
        r = lam.invoke(FunctionName=fn, Payload=json.dumps(payload).encode())
        body = json.loads(r["Payload"].read() or b"null")
        assert "FunctionError" not in r, f"function error: {body}"
        return body

    def kb_tool():
        out = inv("facilities-kb-search", {"query": "boiler pressure limit"})
        assert out["results"] and "boiler" in out["results"][0]["text"].lower(), out
        return f"read-only knowledge tool returned {len(out['results'])} cited results"
    if ctx.state.get("kb_id"):
        ctx.step("lambda: kb-search tool (Bedrock KB Retrieve from inside Lambda)", kb_tool)

    def asset_tool():
        out = inv("facilities-asset-status", {"asset_id": "B-12"})
        assert out["found"] and out["asset"]["asset_id"] == "B-12" and len(out["work_orders"]) == 1, out
        return f"B-12 status={out['asset']['status']}, open work orders={len(out['work_orders'])}"
    ctx.step("lambda: asset-status tool (DynamoDB read from inside Lambda)", asset_tool)
