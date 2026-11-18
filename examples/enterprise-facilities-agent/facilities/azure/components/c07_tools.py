"""C7: tools as Function App functions over Azure Table storage: seed, deploy (ARM + zip deploy), list via ARM, invoke over HTTPS.
kb-search (AI Search), asset-status (Table), approval-decision + create-work-order (the write tool, behind the approval)."""
from ..runtime import NAMES, LANE, RG, Blocked
from .. import deploy, search

FUNCS = {"kb-search": "kb_search", "asset-status": "asset_status", "approval-decision": "decide_approval", "create-work-order": "create_work_order"}


def run(ctx):
    def seed():
        deploy.seed_table(ctx, NAMES["assets"], deploy.fixture("assets.json"), "asset", "asset_id")
        deploy.seed_table(ctx, NAMES["work_orders"], deploy.fixture("work_orders.json"), "wo", "work_order_id")
        ctx.table(NAMES["ledger"])
        n = len(list(ctx.table(NAMES["assets"]).list_entities()))
        assert n == 3, n
        return "3 assets, 3 work orders in Azure Table storage (azure-data-tables); empty approvalledger table"
    ctx.step("table storage: seed fixture assets + work orders (azure-data-tables)", seed, lane=LANE["data"])

    def dep():
        search.ensure_search(ctx)
        deploy.create_function_app(ctx, NAMES["functions"], FUNCS)
        ctx.state["funcs_deployed"] = True
        return f"function app {NAMES['functions']} with {sorted(FUNCS)} created through ARM and zip-deployed"
    ctx.step("function app: ARM plan + site + zip deploy of four functions (azure-mgmt-web)", dep, lane=LANE["runtime"])

    def listed():
        from azure.mgmt.web import WebSiteManagementClient
        names = sorted(f.name.split("/")[-1] for f in ctx.arm(WebSiteManagementClient).web_apps.list_functions(RG, NAMES["functions"]))
        if not names:
            raise Blocked(LANE["runtime"], "ARM list_functions shows no functions after the zip deploy")
        assert set(FUNCS) <= set(names), f"ARM list_functions shows {names}"
        return names
    if ctx.state.get("funcs_deployed"):
        ctx.step("function app: ARM list_functions shows the deployed functions", listed, lane=LANE["runtime"])

        def keys():
            from azure.mgmt.web import WebSiteManagementClient
            w = ctx.arm(WebSiteManagementClient)
            try:
                k = w.web_apps.list_host_keys(RG, NAMES["functions"])
                val = (k.function_keys or {}).get("default") or k.master_key
            except Exception:
                k = w.web_apps.list_function_keys(RG, NAMES["functions"], "kb-search")
                val = (k.additional_properties or {}).get("default")
            if not val:
                raise Blocked(LANE["runtime"], "ARM returned no function / host key for the function app")
            ctx.state["func_key"] = val
            return "host key listed through ARM (sent as x-functions-key)"
        ctx.step("function app: ARM list_host_keys gives the key that authorises function calls", keys, lane=LANE["runtime"])

    def kb_tool():
        out = deploy.call_function(ctx, NAMES["functions"], "kb-search", {"query": "boiler pressure limit"})
        assert out["results"] and "boiler" in out["results"][0]["text"].lower(), out
        return f"read-only knowledge tool returned {len(out['results'])} cited results (AI Search client inside the function)"
    if ctx.state.get("funcs_deployed"):
        ctx.step("function: kb-search tool (Azure AI Search from inside the function)", kb_tool, lane=LANE["runtime"])

        def asset_tool():
            out = deploy.call_function(ctx, NAMES["functions"], "asset-status", {"asset_id": "B-12"})
            assert out["found"] and out["asset"]["asset_id"] == "B-12" and len(out["work_orders"]) == 1, out
            return f"B-12 status={out['asset']['status']}, open work orders={len(out['work_orders'])}"
        ctx.step("function: asset-status tool (Azure Table read from inside the function)", asset_tool, lane=LANE["runtime"])
