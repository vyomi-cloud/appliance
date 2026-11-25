import time
from azure.core import MatchConditions
from azure.core.exceptions import ResourceModifiedError
from azure.data.tables import UpdateMode
from azdata import table

ledger = table("approvalledger")
now = int(time.time())
ledger.upsert_entity({"PartitionKey": "req", "RowKey": "req-exp-stale", "status": "PENDING", "expires_at": now - 5, "asset_id": "B-12"})
ledger.upsert_entity({"PartitionKey": "req", "RowKey": "req-exp-done", "status": "APPROVED", "expires_at": now - 5, "asset_id": "B-12"})
ledger.upsert_entity({"PartitionKey": "req", "RowKey": "req-exp-fresh", "status": "PENDING", "expires_at": now + 3600, "asset_id": "B-12"})


def sweep():
    expired = []
    for row in ledger.query_entities("status eq 'PENDING'"):
        if int(row.get("expires_at", 1 << 60)) < int(time.time()):
            try:
                ledger.update_entity({"PartitionKey": "req", "RowKey": row["RowKey"], "status": "EXPIRED"}, mode=UpdateMode.MERGE,
                                     etag=row.metadata["etag"], match_condition=MatchConditions.IfNotModified)
                expired.append(row["RowKey"])
            except ResourceModifiedError:
                pass          # decided in the meantime: leave it alone
    return expired


assert sweep() == ["req-exp-stale"], "only the overdue PENDING request may expire"
status = lambda r: ledger.get_entity("req", r)["status"]
assert status("req-exp-stale") == "EXPIRED" and status("req-exp-done") == "APPROVED" and status("req-exp-fresh") == "PENDING"
print("expired:", "req-exp-stale", "| approved row untouched | fresh row still waiting")

# a decision that raced the sweeper: it holds an old ETag, so the condition refuses it
stale = ledger.get_entity("req", "req-exp-stale")
try:
    ledger.update_entity({"PartitionKey": "req", "RowKey": "req-exp-stale", "status": "APPROVED"}, mode=UpdateMode.MERGE,
                         etag="W/\"stale\"", match_condition=MatchConditions.IfNotModified)
    raise SystemExit("an old ETag must not be able to approve an expired request")
except ResourceModifiedError:
    pass
assert status("req-exp-stale") == "EXPIRED"
print("approval expiry verified")
