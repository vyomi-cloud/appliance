from azdata import call_function, FUNCTION_APP

out = call_function(FUNCTION_APP, "asset-status", {"asset_id": "B-12"})
print("found:", out["found"], "| status:", out["asset"]["status"], "| work orders:", len(out["work_orders"]))
