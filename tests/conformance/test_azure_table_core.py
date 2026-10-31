"""Azure Table Storage data-plane core conformance — the OData/JSON analogue of
test_azure_queue_core.py.

Asserts the native **Azure Table REST API** wire semantics (Tables collection create/
list/delete, entity insert/get/replace/merge/delete/query, PartitionKey/RowKey entity
keys, $filter, ETag round-trip, TableNotFound / EntityAlreadyExists errors), proving
azure-data-tables can drive the core unchanged.

Run on host:    python3 tests/conformance/test_azure_table_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core import azure_table_core as at
except ImportError:  # pragma: no cover - Pyodide flat layout
    import azure_table_core as at  # type: ignore

ACCT = "/devstoreaccount1"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    st = at.AzureTableStore()
    T = "orders"

    # 1. create table -> 201
    r = at.dispatch(st, "POST", f"{ACCT}/Tables", {}, {}, json.dumps({"TableName": T}).encode())
    _check("create table 201", r.status == 201)
    _check("table exists in store", st.table_exists(T))

    # 1b. duplicate create -> 409 TableAlreadyExists
    dup = at.dispatch(st, "POST", f"{ACCT}/Tables", {}, {}, json.dumps({"TableName": T}).encode())
    _check("duplicate table 409", dup.status == 409)
    _check("duplicate error code", dup.headers.get("x-ms-error-code") == "TableAlreadyExists")

    # 2. list tables -> 200, value includes T
    lst = at.dispatch(st, "GET", f"{ACCT}/Tables", {}, {}, b"")
    names = [t["TableName"] for t in json.loads(lst.body)["value"]]
    _check("list tables includes T", T in names)

    # 3. insert entity -> 201, echoes PartitionKey/RowKey/Timestamp/odata.etag
    entity = {"PartitionKey": "customers", "RowKey": "c1", "Name": "Ada", "Age": 30}
    ins = at.dispatch(st, "POST", f"{ACCT}/{T}", {}, {}, json.dumps(entity).encode())
    _check("insert entity 201", ins.status == 201)
    body = json.loads(ins.body)
    _check("insert echoes Name", body["Name"] == "Ada")
    _check("insert has odata.etag", "odata.etag" in body)
    _check("insert has Timestamp", "Timestamp" in body)
    _check("insert sets etag header", bool(ins.headers.get("etag")))

    # 3b. duplicate insert -> 409 EntityAlreadyExists
    dupe = at.dispatch(st, "POST", f"{ACCT}/{T}", {}, {}, json.dumps(entity).encode())
    _check("duplicate entity 409", dupe.status == 409)

    # 4. get entity by key -> 200
    get = at.dispatch(st, "GET", f"{ACCT}/{T}(PartitionKey='customers',RowKey='c1')", {}, {}, b"")
    _check("get entity 200", get.status == 200)
    _check("get entity returns Age", json.loads(get.body)["Age"] == 30)

    # 4b. get missing entity -> 404
    miss = at.dispatch(st, "GET", f"{ACCT}/{T}(PartitionKey='customers',RowKey='ghost')", {}, {}, b"")
    _check("get missing entity 404", miss.status == 404)

    # 5. query entities with $filter -> only the matching row
    e2 = {"PartitionKey": "customers", "RowKey": "c2", "Name": "Grace"}
    at.dispatch(st, "POST", f"{ACCT}/{T}", {}, {}, json.dumps(e2).encode())
    q = at.dispatch(st, "GET", f"{ACCT}/{T}", {"$filter": "RowKey eq 'c2'"}, {}, b"")
    rows = json.loads(q.body)["value"]
    _check("filtered query returns one row", len(rows) == 1 and rows[0]["Name"] == "Grace")

    # 6. replace entity (PUT) -> 204, overwrites fields not resent
    repl = at.dispatch(st, "PUT", f"{ACCT}/{T}(PartitionKey='customers',RowKey='c1')", {}, {},
                       json.dumps({"PartitionKey": "customers", "RowKey": "c1", "Name": "Ada Lovelace"}).encode())
    _check("replace entity 204", repl.status == 204)
    after = json.loads(at.dispatch(st, "GET", f"{ACCT}/{T}(PartitionKey='customers',RowKey='c1')", {}, {}, b"").body)
    _check("replace dropped Age", "Age" not in after)
    _check("replace updated Name", after["Name"] == "Ada Lovelace")

    # 7. merge entity (MERGE) -> 204, keeps unresent fields
    merge = at.dispatch(st, "MERGE", f"{ACCT}/{T}(PartitionKey='customers',RowKey='c1')", {}, {},
                        json.dumps({"City": "London"}).encode())
    _check("merge entity 204", merge.status == 204)
    merged = json.loads(at.dispatch(st, "GET", f"{ACCT}/{T}(PartitionKey='customers',RowKey='c1')", {}, {}, b"").body)
    _check("merge kept Name", merged["Name"] == "Ada Lovelace")
    _check("merge added City", merged["City"] == "London")

    # 7b. X-HTTP-Method: MERGE override on POST (the SDK's fallback for proxies that drop verbs)
    ov = at.dispatch(st, "POST", f"{ACCT}/{T}(PartitionKey='customers',RowKey='c1')",
                     {}, {"x-http-method": "MERGE"}, json.dumps({"Country": "UK"}).encode())
    _check("MERGE-via-POST 204", ov.status == 204)

    # 8. delete entity -> 204, then 404
    de = at.dispatch(st, "DELETE", f"{ACCT}/{T}(PartitionKey='customers',RowKey='c2')", {}, {}, b"")
    _check("delete entity 204", de.status == 204)
    de2 = at.dispatch(st, "DELETE", f"{ACCT}/{T}(PartitionKey='customers',RowKey='c2')", {}, {}, b"")
    _check("delete missing entity 404", de2.status == 404)

    # 9. operation on a missing table -> 404 TableNotFound
    nt = at.dispatch(st, "GET", f"{ACCT}/ghosttable", {}, {}, b"")
    _check("missing table 404", nt.status == 404)
    _check("missing table error code", nt.headers.get("x-ms-error-code") == "TableNotFound")

    # 10. delete table -> 204, then operations 404
    dt = at.dispatch(st, "DELETE", f"{ACCT}/Tables('{T}')", {}, {}, b"")
    _check("delete table 204", dt.status == 204)
    _check("table gone from store", not st.table_exists(T))
    dt2 = at.dispatch(st, "DELETE", f"{ACCT}/Tables('{T}')", {}, {}, b"")
    _check("delete missing table 404", dt2.status == 404)

    # 11. works WITHOUT the optional account prefix too
    at.dispatch(st, "POST", "/Tables", {}, {}, json.dumps({"TableName": "bare"}).encode())
    _check("create table no-account prefix", st.table_exists("bare"))

    print("\nAzure Table Storage data-plane core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
