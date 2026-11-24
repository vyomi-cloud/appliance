import functions

out = functions.call("facilities-asset-status", {"asset_id": "B-12"})
open_orders = [w for w in out["work_orders"] if w["status"] == "OPEN"]
print("found:", out["found"], "| status:", out["asset"]["status"], "| open work orders:", len(open_orders))
