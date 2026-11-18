"""One Azure Table scenario driven with the REAL azure-data-tables SDK (12.x). Used against the simulator's own core
(test_azure_table_wire_sdk.py) and against the real Azurite behind the simulator (test_azure_real_backends.py), so the
two implementations are held to the same behaviour."""
import datetime
import uuid

from _az_inproc import ok


def run(ts, label=""):
    from azure.core import MatchConditions
    from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
    from azure.data.tables import TableTransactionError, UpdateMode

    name = "ledger" + uuid.uuid4().hex[:8]
    t = ts.create_table_if_not_exists(name)
    ok(f"{label}create table + list", name in [x.name for x in ts.list_tables()])
    e = t.create_entity({"PartitionKey": "req", "RowKey": "r1", "status": "pending", "amount": 900, "who": "ann"})
    ok(f"{label}create_entity returns etag", bool(e.get("etag")), str(e))
    try:
        t.create_entity({"PartitionKey": "req", "RowKey": "r1"})
        ok(f"{label}duplicate create -> ResourceExistsError", False)
    except ResourceExistsError:
        ok(f"{label}duplicate create -> ResourceExistsError", True)

    # PATCH/MERGE and PUT/REPLACE verbs, both upsert modes
    t.update_entity({"PartitionKey": "req", "RowKey": "r1", "status": "approved"}, mode=UpdateMode.MERGE)
    g = t.get_entity("req", "r1")
    ok(f"{label}update_entity MERGE keeps other props", g["status"] == "approved" and g["amount"] == 900 and g["who"] == "ann", dict(g))
    t.update_entity({"PartitionKey": "req", "RowKey": "r1", "status": "closed"}, mode=UpdateMode.REPLACE)
    g = t.get_entity("req", "r1")
    ok(f"{label}update_entity REPLACE drops other props", g["status"] == "closed" and "amount" not in g, dict(g))
    t.upsert_entity({"PartitionKey": "req", "RowKey": "r2", "status": "pending", "amount": 50}, mode=UpdateMode.MERGE)
    t.upsert_entity({"PartitionKey": "req", "RowKey": "r2", "note": "x"}, mode=UpdateMode.MERGE)
    ok(f"{label}upsert MERGE inserts then merges", dict(t.get_entity("req", "r2")).get("amount") == 50 and t.get_entity("req", "r2")["note"] == "x")
    t.upsert_entity({"PartitionKey": "req", "RowKey": "r3", "status": "pending", "amount": 700, "ok": True}, mode=UpdateMode.REPLACE)
    t.upsert_entity({"PartitionKey": "req", "RowKey": "r3", "status": "approved"}, mode=UpdateMode.REPLACE)
    ok(f"{label}upsert REPLACE replaces", "amount" not in t.get_entity("req", "r3"))
    try:
        t.update_entity({"PartitionKey": "req", "RowKey": "nope", "a": 1}, mode=UpdateMode.MERGE)
        ok(f"{label}update_entity on a missing entity -> 404", False)
    except ResourceNotFoundError:
        ok(f"{label}update_entity on a missing entity -> 404", True)

    # more rows for queries / paging
    for i in range(4, 10):
        t.create_entity({"PartitionKey": "req", "RowKey": f"r{i}", "status": "pending" if i % 2 else "approved", "amount": i * 100, "big": i > 6})
    t.update_entity({"PartitionKey": "req", "RowKey": "r5", "when": datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)}, mode=UpdateMode.MERGE)
    t.create_entity({"PartitionKey": "other", "RowKey": "o1", "status": "approved", "amount": 5})

    # OData $filter
    def keys(flt, **kw):
        return sorted(x["RowKey"] for x in t.query_entities(flt, **kw))
    ok(f"{label}$filter eq string", keys("status eq 'approved' and PartitionKey eq 'req'") == ["r3", "r4", "r6", "r8"], keys("status eq 'approved' and PartitionKey eq 'req'"))
    ok(f"{label}$filter numeric gt / le", keys("PartitionKey eq 'req' and amount gt 500 and amount le 800") == ["r6", "r7", "r8"], keys("PartitionKey eq 'req' and amount gt 500 and amount le 800"))
    ok(f"{label}$filter or + not + parens", keys("PartitionKey eq 'other' or (PartitionKey eq 'req' and not (status eq 'pending') and RowKey ge 'r8')") == ["o1", "r8"])
    ok(f"{label}$filter bool", keys("big eq true") == ["r7", "r8", "r9"])
    ok(f"{label}$filter ne", "r1" not in keys("status ne 'closed' and PartitionKey eq 'req'"))
    ok(f"{label}query parameters (@param)", keys("amount ge @lo and PartitionKey eq @pk", parameters={"lo": 800, "pk": "req"}) == ["r8", "r9"])
    ok(f"{label}$filter datetime", keys("when ge @d", parameters={"d": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)}) == ["r5"], keys("when ge @d", parameters={"d": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)}))
    sel = list(t.query_entities("PartitionKey eq 'req' and RowKey eq 'r4'", select=["status"]))
    ok(f"{label}$select projects", len(sel) == 1 and set(k for k in sel[0].keys()) == {"status"}, str([dict(x) for x in sel]))
    allrows = list(t.list_entities())
    ok(f"{label}list_entities all", len(allrows) == 10, len(allrows))
    pages = list(t.list_entities(results_per_page=4).by_page())
    sizes = [len(list(p)) for p in pages]
    ok(f"{label}paging via continuation (results_per_page=4)", sizes == [4, 4, 2], str(sizes))

    # ETag optimistic concurrency
    cur = t.get_entity("req", "r9")
    etag = cur.metadata["etag"]
    t.update_entity({"PartitionKey": "req", "RowKey": "r9", "status": "done"}, mode=UpdateMode.MERGE, etag=etag, match_condition=MatchConditions.IfNotModified)
    ok(f"{label}If-Match with current etag succeeds", t.get_entity("req", "r9")["status"] == "done")
    try:
        t.update_entity({"PartitionKey": "req", "RowKey": "r9", "status": "late"}, mode=UpdateMode.MERGE, etag=etag, match_condition=MatchConditions.IfNotModified)
        ok(f"{label}stale etag -> 412 ResourceModifiedError", False)
    except ResourceModifiedError as ex:
        ok(f"{label}stale etag -> 412 ResourceModifiedError", getattr(ex, "status_code", None) == 412, str(getattr(ex, "status_code", None)))
    try:
        t.delete_entity("req", "r9", etag=etag, match_condition=MatchConditions.IfNotModified)
        ok(f"{label}delete with stale etag -> 412", False)
    except ResourceModifiedError:
        ok(f"{label}delete with stale etag -> 412", True)
    ok(f"{label}stale write did not apply", t.get_entity("req", "r9")["status"] == "done")

    # transactions
    ops = [("create", {"PartitionKey": "tx", "RowKey": "a", "v": 1}), ("create", {"PartitionKey": "tx", "RowKey": "b", "v": 2}),
           ("upsert", {"PartitionKey": "tx", "RowKey": "c", "v": 3}, {"mode": "replace"})]
    res = t.submit_transaction(ops)
    ok(f"{label}submit_transaction commits", len(res) == 3 and sorted(x["RowKey"] for x in t.query_entities("PartitionKey eq 'tx'")) == ["a", "b", "c"], str(res)[:120])
    try:
        t.submit_transaction([("create", {"PartitionKey": "tx", "RowKey": "d", "v": 4}), ("create", {"PartitionKey": "tx", "RowKey": "a", "v": 9})])
        ok(f"{label}failing transaction raises", False)
    except TableTransactionError as ex:
        ok(f"{label}failing transaction raises TableTransactionError (index 1)", getattr(ex, "index", None) == 1, str(getattr(ex, "index", None)))
    ok(f"{label}failing transaction is atomic", "d" not in keys("PartitionKey eq 'tx'"), keys("PartitionKey eq 'tx'"))
    t.submit_transaction([("update", {"PartitionKey": "tx", "RowKey": "a", "v": 11}, {"mode": "merge"}), ("delete", {"PartitionKey": "tx", "RowKey": "b"})])
    ok(f"{label}transaction update + delete", t.get_entity("tx", "a")["v"] == 11 and "b" not in keys("PartitionKey eq 'tx'"))

    t.delete_entity("req", "r2")
    ok(f"{label}delete_entity", "r2" not in keys("PartitionKey eq 'req'"))
    ts.delete_table(name)
    ok(f"{label}delete_table", name not in [x.name for x in ts.list_tables()])
    return name
