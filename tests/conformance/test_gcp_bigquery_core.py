"""GCP BigQuery core conformance — host + Pyodide. Datasets, tables, tabledata, SQL jobs
(query / DML / DDL / parameters), query results paging, routines, IAM and native errors."""
import json

try:
    from core import gcp_bigquery_core as bq
except ImportError:  # pragma: no cover - Pyodide flat layout
    import gcp_bigquery_core as bq  # type: ignore

P = "/bigquery/v2/projects/proj"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or bq.BigQueryStore()

    def call(m, path, body=None, q=None):
        r = bq.dispatch(s, m, P + path, q or {}, {}, json.dumps(body).encode() if body is not None else b"")
        return r.status, (json.loads(r.body) if r.body else None)

    def reason(st_b, status, why):
        return st_b[0] == status and st_b[1]["error"]["errors"][0]["reason"] == why

    st, b = call("POST", "/datasets", {"datasetReference": {"datasetId": "sales"}, "labels": {"env": "dev"}, "description": "d"})
    _check("datasets.insert", st == 200 and b["id"] == "proj:sales" and b["location"] == "US" and b["kind"] == "bigquery#dataset")
    _check("datasets.insert duplicate → 409 duplicate", reason(call("POST", "/datasets", {"datasetReference": {"datasetId": "sales"}}), 409, "duplicate"))
    _check("datasets.insert bad id → 400", call("POST", "/datasets", {"datasetReference": {"datasetId": "bad-id"}})[0] == 400)
    _check("datasets.get", call("GET", "/datasets/sales")[1]["labels"] == {"env": "dev"})
    _check("datasets.get unknown → 404 notFound", reason(call("GET", "/datasets/nope"), 404, "notFound"))
    _check("datasets.patch", call("PATCH", "/datasets/sales", {"description": "new"})[1]["description"] == "new")
    _check("datasets.list", [d["datasetReference"]["datasetId"] for d in call("GET", "/datasets")[1]["datasets"]] == ["sales"])

    schema = {"fields": [{"name": "id", "type": "INT64", "mode": "REQUIRED"}, {"name": "name", "type": "STRING"},
                         {"name": "amount", "type": "FLOAT64"}, {"name": "paid", "type": "BOOL"}, {"name": "at", "type": "TIMESTAMP"}]}
    st, b = call("POST", "/datasets/sales/tables", {"tableReference": {"tableId": "orders"}, "schema": schema, "description": "orders"})
    _check("tables.insert normalizes types", st == 200 and [f["type"] for f in b["schema"]["fields"]] == ["INTEGER", "STRING", "FLOAT", "BOOLEAN", "TIMESTAMP"] and b["numRows"] == "0")
    _check("tables.insert duplicate → 409", call("POST", "/datasets/sales/tables", {"tableReference": {"tableId": "orders"}, "schema": schema})[0] == 409)
    _check("tables.insert without schema → 400", call("POST", "/datasets/sales/tables", {"tableReference": {"tableId": "x"}})[0] == 400)
    st, b = call("POST", "/datasets/sales/tables/orders/insertAll", {"rows": [
        {"insertId": "a", "json": {"id": "1", "name": "ann", "amount": 10.5, "paid": True, "at": "2024-01-01T00:00:00Z"}},
        {"json": {"id": 2, "name": "bob", "amount": "20", "paid": False}}]})
    _check("tabledata.insertAll", st == 200 and "insertErrors" not in b)
    st, b = call("POST", "/datasets/sales/tables/orders/insertAll", {"rows": [{"json": {"id": 3, "bogus": 1}}]})
    _check("tabledata.insertAll unknown field → insertErrors", st == 200 and b["insertErrors"][0]["index"] == 0)
    st, b = call("GET", "/datasets/sales/tables/orders/data")
    _check("tabledata.list wire shape", b["totalRows"] == "2" and b["rows"][0]["f"][0] == {"v": "1"} and b["rows"][0]["f"][3] == {"v": "true"} and b["rows"][1]["f"][4] == {"v": None})
    _check("tabledata.list paging", call("GET", "/datasets/sales/tables/orders/data", q={"maxResults": "1"})[1]["pageToken"] == "1")
    st, b = call("GET", "/datasets/sales/tables/orders")
    _check("tables.get numRows/numBytes", b["numRows"] == "2" and int(b["numBytes"]) > 0)
    _check("tables.list", call("GET", "/datasets/sales/tables")[1]["tables"][0]["tableReference"]["tableId"] == "orders")
    _check("datasets.delete non-empty → 400 resourceInUse", reason(call("DELETE", "/datasets/sales"), 400, "resourceInUse"))

    def q(sql, **kw):
        return call("POST", "/queries", {"query": sql, "useLegacySql": False, "defaultDataset": {"datasetId": "sales"}, **kw})

    st, b = q("SELECT name, amount FROM `proj.sales.orders` WHERE paid ORDER BY id")
    _check("jobs.query SELECT", st == 200 and b["jobComplete"] and b["totalRows"] == "1" and b["rows"][0]["f"][0]["v"] == "ann"
           and [f["type"] for f in b["schema"]["fields"]] == ["STRING", "FLOAT"])
    st, b = q("SELECT COUNT(*) AS n, SUM(amount) AS total FROM orders")
    _check("aggregates + unqualified table", b["rows"][0]["f"][0]["v"] == "2" and float(b["rows"][0]["f"][1]["v"]) == 30.5)
    st, b = q("INSERT INTO sales.orders (id, name, amount, paid) VALUES (3, 'cy', @amt, true)",
              queryParameters=[{"name": "amt", "parameterType": {"type": "FLOAT64"}, "parameterValue": {"value": "5"}}], parameterMode="NAMED")
    _check("DML INSERT with named parameter", st == 200 and b["numDmlAffectedRows"] == "1")
    _check("UPDATE", q("UPDATE sales.orders SET paid = true WHERE id = 2")[1]["numDmlAffectedRows"] == "1")
    _check("DELETE", q("DELETE FROM sales.orders WHERE id = 3")[1]["numDmlAffectedRows"] == "1")
    _check("DML visible through tabledata.list", call("GET", "/datasets/sales/tables/orders/data")[1]["totalRows"] == "2")
    _check("CREATE TABLE AS SELECT", q("CREATE OR REPLACE TABLE sales.paid_orders AS SELECT id, name FROM sales.orders WHERE paid")[0] == 200
           and call("GET", "/datasets/sales/tables/paid_orders")[1]["numRows"] == "2")
    _check("CREATE TABLE with columns", q("CREATE TABLE sales.empty (a INT64, b STRING NOT NULL)")[0] == 200
           and call("GET", "/datasets/sales/tables/empty")[1]["schema"]["fields"][1]["mode"] == "REQUIRED")
    st, b = call("POST", "/datasets/sales/tables", {"tableReference": {"tableId": "v"}, "view": {"query": "SELECT id FROM `proj.sales.orders`"}})
    _check("view table", st == 200 and b["type"] == "VIEW" and q("SELECT COUNT(*) FROM sales.v")[1]["rows"][0]["f"][0]["v"] == "2")
    _check("query syntax error → 400 invalidQuery", reason(q("SELEC 1"), 400, "invalidQuery"))
    _check("query unknown table → 404 notFound", reason(q("SELECT * FROM sales.ghost"), 404, "notFound"))

    st, b = call("POST", "/jobs", {"jobReference": {"jobId": "j1"}, "configuration": {"query": {"query": "SELECT id FROM sales.orders ORDER BY id", "useLegacySql": False}}})
    _check("jobs.insert query → DONE", st == 200 and b["status"]["state"] == "DONE" and b["jobReference"]["jobId"] == "j1" and b["statistics"]["query"]["statementType"] == "SELECT")
    _check("jobs.get", call("GET", "/jobs/j1")[1]["id"] == "proj:US.j1")
    st, b = call("GET", "/queries/j1", q={"maxResults": "1"})
    _check("jobs.getQueryResults paged", b["kind"] == "bigquery#getQueryResultsResponse" and b["totalRows"] == "2" and len(b["rows"]) == 1 and b["pageToken"] == "1")
    _check("jobs.list", any(j["jobReference"]["jobId"] == "j1" for j in call("GET", "/jobs")[1]["jobs"]))
    st, b = call("POST", "/jobs", {"jobReference": {"jobId": "j2"}, "configuration": {"query": {"query": "SELECT * FROM sales.ghost"}}})
    _check("failed query job records errorResult", st == 200 and b["status"]["errorResult"]["reason"] == "notFound" and call("GET", "/queries/j2")[0] == 404)
    _check("jobs.insert duplicate id → 409", call("POST", "/jobs", {"jobReference": {"jobId": "j1"}, "configuration": {"query": {"query": "SELECT 1"}}})[0] == 409)
    njobs = len(s.jobs)
    st, b = call("POST", "/jobs", {"configuration": {"dryRun": True, "query": {"query": "SELECT * FROM sales.orders"}}})
    _check("dry run reports bytes, stores nothing", st == 200 and int(b["statistics"]["totalBytesProcessed"]) > 0 and len(s.jobs) == njobs)
    st, b = call("POST", "/jobs", {"configuration": {"query": {"query": "SELECT id, name FROM sales.orders", "destinationTable": {"projectId": "proj", "datasetId": "sales", "tableId": "snap"}}}})
    _check("query destinationTable materializes", call("GET", "/datasets/sales/tables/snap")[1]["numRows"] == "2")
    st, b = call("POST", "/jobs", {"configuration": {"copy": {"sourceTable": {"projectId": "proj", "datasetId": "sales", "tableId": "orders"}, "destinationTable": {"projectId": "proj", "datasetId": "sales", "tableId": "orders_copy"}}}})
    _check("copy job", b["status"]["state"] == "DONE" and call("GET", "/datasets/sales/tables/orders_copy")[1]["numRows"] == "2")
    _check("jobs.cancel", call("POST", "/jobs/j1/cancel")[1]["kind"] == "bigquery#jobCancelResponse")
    _check("jobs.delete", call("DELETE", "/jobs/j1/delete")[0] == 204 and call("GET", "/jobs/j1")[0] == 404)

    st, b = call("POST", "/datasets/sales/routines", {"routineReference": {"projectId": "proj", "datasetId": "sales", "routineId": "add1"},
                 "routineType": "SCALAR_FUNCTION", "language": "SQL", "definitionBody": "x + 1", "arguments": [{"name": "x", "dataType": {"typeKind": "INT64"}}]})
    _check("routines.insert", st == 200 and b["routineType"] == "SCALAR_FUNCTION")
    _check("routines.get/list", call("GET", "/datasets/sales/routines/add1")[0] == 200 and len(call("GET", "/datasets/sales/routines")[1]["routines"]) == 1)
    _check("routines.delete", call("DELETE", "/datasets/sales/routines/add1")[0] == 204)

    path = "/datasets/sales/tables/orders"
    r = bq.dispatch(s, "POST", P + path + ":setIamPolicy", {}, {}, json.dumps({"policy": {"bindings": [{"role": "roles/bigquery.dataViewer", "members": ["user:a@b.c"]}]}}).encode())
    _check("tables.setIamPolicy/getIamPolicy", r.status == 200 and json.loads(bq.dispatch(s, "POST", P + path + ":getIamPolicy").body)["bindings"][0]["role"] == "roles/bigquery.dataViewer")
    _check("projects.list + serviceAccount", bq.dispatch(s, "GET", "/bigquery/v2/projects").status == 200 and "email" in call("GET", "/serviceAccount")[1])

    _check("tables.patch labels", call("PATCH", path, {"labels": {"a": "b"}})[1]["labels"] == {"a": "b"})
    _check("tables.delete", call("DELETE", path)[0] == 204 and call("GET", path)[0] == 404)
    _check("datasets.delete deleteContents", call("DELETE", "/datasets/sales", q={"deleteContents": "true"})[0] == 204 and call("GET", "/datasets/sales")[0] == 404)

    # console facade
    c = bq.console_create(s, "proj", {"name": "web", "location": "EU"})
    _check("console_create", c["ok"] and c["location"] == "EU")
    bq.console_sample(s, "web", "createTable")
    bq.console_sample(s, "web", "runQuery")
    row = bq.console_list(s)[0]
    _check("console row: every column filled", all(row[k] not in (None, "", "-") for k in ("name", "location", "tables", "size", "expiration", "encryption", "created", "modified")) and row["tables"] == 1)
    for kind in ("tables", "jobs"):
        rows = bq.console_children(s, "web", kind)
        _check(f"console {kind} rows filled", rows and all(v not in (None, "", "-") for r_ in rows for v in r_.values()))
    _check("console_delete", bq.console_delete(s, "web")["ok"])
    return s


def test_bigquery_core():
    run()


if __name__ == "__main__":
    run()
    print("OK")
