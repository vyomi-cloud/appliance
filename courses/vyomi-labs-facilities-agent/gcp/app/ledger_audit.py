import gcp

rows = [d.to_dict() for d in gcp.firestore_client().collection("approval-ledger").stream()]
print("ledger rows:", len(rows), sorted({r["status"] for r in rows}))
done = [r for r in rows if r["status"] == "EXECUTED"]
assert done, "no executed request"
print("executed:", done[0]["request_id"], "approved by", done[0]["approver"], "-> work order", done[0]["work_order_id"])
