"""Cosmos DB SQL-API wire in the simulator's OWN core, driven by the unmodified azure-cosmos SDK (4.x):
ETag / If-Match -> 412 on replace / patch / delete, replace_item through the returned `_self` link, patch_item (set /
replace / add / remove / incr / move + filter predicate), read_all_items + max_item_count paging with continuation tokens,
query paging, execute_item_batch (atomic transactional batch).
There is no open-source Cosmos engine we can run cheaply, so this is Vyomi's own core (never claimed to be a real engine).
Tier note: Cosmos is Max-tier on a licensed appliance; the harness sets CLOUDLEARN_TIER_ENFORCE=0 (the gate has its own tests).
Run: PYTHONPATH=. python3 tests/conformance/test_azure_cosmos_wire_sdk.py   (skips when azure-cosmos is absent)"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from azure.cosmos import CosmosClient, PartitionKey
except ImportError:
    print("[SKIP] azure-cosmos not installed")
    sys.exit(0)
import _az_inproc as h


def run(base):
    from azure.core import MatchConditions
    from azure.cosmos import exceptions as cx
    c = CosmosClient(base, credential=h.KEY, connection_verify=False)
    db = c.create_database_if_not_exists("ops" + uuid.uuid4().hex[:6])
    ct = db.create_container_if_not_exists("ledger", partition_key=PartitionKey(path="/id"))
    ct.upsert_item({"id": "r1", "status": "pending", "tags": ["a"], "n": 1})
    it = ct.read_item("r1", partition_key="r1")

    # ETag / If-Match
    it["status"] = "approved"
    ok1 = ct.replace_item("r1", it, etag=it["_etag"], match_condition=MatchConditions.IfNotModified)
    h.ok("replace_item with the current etag succeeds", ok1["status"] == "approved" and ok1["_etag"] != it["_etag"])
    try:
        ct.replace_item("r1", it, etag=it["_etag"], match_condition=MatchConditions.IfNotModified)
        h.ok("replace_item with a stale etag -> 412", False)
    except cx.CosmosAccessConditionFailedError as ex:
        h.ok("replace_item with a stale etag -> 412", ex.status_code == 412, str(ex.status_code))
    h.ok("stale replace did not apply", ct.read_item("r1", partition_key="r1")["status"] == "approved")
    try:
        ct.delete_item("r1", partition_key="r1", etag=it["_etag"], match_condition=MatchConditions.IfNotModified)
        h.ok("delete_item with a stale etag -> 412", False)
    except cx.CosmosAccessConditionFailedError:
        h.ok("delete_item with a stale etag -> 412", True)

    # replace through the returned _self link (the SDK resolves dbs/{rid}/colls/{rid}/docs/{rid})
    cur = ct.read_item("r1", partition_key="r1")
    cur["status"] = "closed"
    ct.replace_item(cur, cur)
    h.ok("replace_item(item dict) via _self", ct.read_item("r1", partition_key="r1")["status"] == "closed")

    # patch_item
    ct.patch_item("r1", partition_key="r1", patch_operations=[
        {"op": "set", "path": "/approver", "value": "mgr"}, {"op": "add", "path": "/tags/-", "value": "b"},
        {"op": "incr", "path": "/n", "value": 4}, {"op": "replace", "path": "/status", "value": "done"}])
    g = ct.read_item("r1", partition_key="r1")
    h.ok("patch_item set/add/incr/replace", g["approver"] == "mgr" and g["tags"] == ["a", "b"] and g["n"] == 5 and g["status"] == "done", str({k: v for k, v in g.items() if not k.startswith("_")}))
    ct.patch_item("r1", partition_key="r1", patch_operations=[{"op": "remove", "path": "/approver"}, {"op": "move", "from": "/n", "path": "/count"}])
    g = ct.read_item("r1", partition_key="r1")
    h.ok("patch_item remove + move", "approver" not in g and g.get("count") == 5 and "n" not in g)
    try:
        ct.patch_item("r1", partition_key="r1", patch_operations=[{"op": "replace", "path": "/nope", "value": 1}])
        h.ok("patch_item replace of a missing path -> 400", False)
    except cx.CosmosHttpResponseError as ex:
        h.ok("patch_item replace of a missing path -> 400", ex.status_code == 400, str(ex.status_code))
    try:
        ct.patch_item("r1", partition_key="r1", patch_operations=[{"op": "set", "path": "/x", "value": 1}], filter_predicate="FROM c WHERE c.status = 'pending'")
        h.ok("patch_item filter predicate not met -> 412", False)
    except cx.CosmosHttpResponseError as ex:
        h.ok("patch_item filter predicate not met -> 412", ex.status_code == 412, str(ex.status_code))
    cur = ct.read_item("r1", partition_key="r1")
    try:
        ct.patch_item("r1", partition_key="r1", patch_operations=[{"op": "set", "path": "/x", "value": 1}], etag='"stale"', match_condition=MatchConditions.IfNotModified)
        h.ok("patch_item with a stale etag -> 412", False)
    except cx.CosmosAccessConditionFailedError:
        h.ok("patch_item with a stale etag -> 412", True)

    # read_all_items + paging
    for i in range(2, 9):
        ct.upsert_item({"id": f"r{i}", "status": "pending" if i % 2 else "approved", "amount": i * 10})
    allitems = list(ct.read_all_items())
    h.ok("read_all_items", len(allitems) == 8, str(len(allitems)))
    pages = [len(list(p)) for p in ct.read_all_items(max_item_count=3).by_page()]
    h.ok("read_all_items paged by continuation (max_item_count=3)", pages == [3, 3, 2], str(pages))
    q = "SELECT * FROM c WHERE c.status = 'approved'"
    qp = [len(list(p)) for p in ct.query_items(q, enable_cross_partition_query=True, max_item_count=2).by_page()]
    h.ok("query_items paged by continuation", sum(qp) == 4 and qp[0] == 2 and len(qp) == 2, str(qp))
    tok = ct.read_all_items(max_item_count=3).by_page()
    first = list(next(tok))
    rest = sum(len(list(p)) for p in ct.read_all_items(max_item_count=3).by_page(tok.continuation_token))
    h.ok("resume from a continuation token", len(first) == 3 and rest == 5, f"{len(first)}+{rest}")

    # transactional batch (one partition key)
    bc = db.create_container_if_not_exists("batch", partition_key=PartitionKey(path="/pk"))
    bc.upsert_item({"id": "seed", "pk": "p", "v": 0})
    res = bc.execute_item_batch([("create", ({"id": "b1", "pk": "p", "v": 1},)), ("upsert", ({"id": "b2", "pk": "p", "v": 2},)),
                                 ("patch", ("seed", [{"op": "incr", "path": "/v", "value": 7}])), ("read", ("b1",))], partition_key="p")
    h.ok("execute_item_batch commits", len(res) == 4 and bc.read_item("seed", partition_key="p")["v"] == 7 and bc.read_item("b2", partition_key="p")["v"] == 2, str(res)[:100])
    try:
        bc.execute_item_batch([("create", ({"id": "b3", "pk": "p"},)), ("create", ({"id": "b1", "pk": "p"},))], partition_key="p")
        h.ok("failing batch raises CosmosBatchOperationError", False)
    except cx.CosmosBatchOperationError as ex:
        h.ok("failing batch raises CosmosBatchOperationError (409 on op 1)", True, str(ex)[:80])
    try:
        bc.read_item("b3", partition_key="p")
        h.ok("failing batch is atomic", False)
    except cx.CosmosResourceNotFoundError:
        h.ok("failing batch is atomic", True)
    return ct, c


if __name__ == "__main__":
    os.environ.pop("VYOMI_AZURE_REAL_BACKENDS", None)
    base = h.start_sim()
    run(base)
    print(f"\n{len(h.FAILS)} failure(s)" if h.FAILS else "\nAll PASS")
    sys.exit(1 if h.FAILS else 0)
