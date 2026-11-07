"""Storage Insights datasets really populate a BigQuery dataset (bucket/object/project_attributes_view), queryable with SQL
through the native BigQuery v2 wire. Run: PYTHONPATH=. python tests/conformance/test_gcp_bigquery_insights.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False
R = AwsWireRouter()
PASS = FAIL = 0
P = "vyomi-project"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:500] if detail and not ok else ''}")


def call(method, path, body=None, query=None, raw=None):
    out = R.handle(method, path, query or {}, {"content-type": "application/json"}, raw if raw is not None else (json.dumps(body).encode() if body is not None else b""))
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {}


for b in ("data-a", "data-b", "other"):
    check("bucket " + b, call("POST", "/storage/v1/b", {"name": b}, {"project": P})[0] == 200)
for b, n, body in (("data-a", "x.txt", b"hello"), ("data-a", "dir/y.csv", b"a,b\n1,2\n"), ("data-b", "z.bin", b"0123456789"), ("other", "skip.txt", b"nope")):
    st, _ = call("POST", f"/upload/storage/v1/b/{b}/o", None, {"uploadType": "media", "name": n}, raw=body)
    check(f"upload {b}/{n}", st == 200)

st, ds = call("POST", "/storage/v1/insightsDatasets", {"displayName": "inv", "sourceBucketPrefix": "data-", "datasetConfigId": "inv1"})
check("insights dataset created, linked to a BigQuery dataset", st == 200 and ds["link"]["dataset"] == f"projects/{P}/datasets/storage_insights_inv1" and ds["tableRowCounts"]["object_attributes_view"] == 3, ds)
st, l = call("GET", f"/bigquery/v2/projects/{P}/datasets")
check("BigQuery datasets.list shows the linked dataset", st == 200 and any(d["datasetReference"]["datasetId"] == "storage_insights_inv1" for d in l.get("datasets", [])), l)
st, t = call("GET", f"/bigquery/v2/projects/{P}/datasets/storage_insights_inv1/tables")
check("three insights tables", st == 200 and {x["tableReference"]["tableId"] for x in t["tables"]} == {"bucket_attributes_view", "object_attributes_view", "project_attributes_view"}, t)
st, q = call("POST", f"/bigquery/v2/projects/{P}/queries", {"query": f"SELECT bucket, COUNT(*) AS n, SUM(size) AS bytes FROM `{P}.storage_insights_inv1.object_attributes_view` GROUP BY bucket ORDER BY bucket", "useLegacySql": False})
rows = [[c["v"] for c in r["f"]] for r in q.get("rows", [])]
check("SQL aggregate over the exported inventory", st == 200 and rows == [["data-a", "2", "13"], ["data-b", "1", "10"]], q)
check("schema types in the response", [f["type"] for f in q["schema"]["fields"]] == ["STRING", "INTEGER", "INTEGER"], q.get("schema"))
st, q = call("POST", f"/bigquery/v2/projects/{P}/queries", {"query": "SELECT name FROM object_attributes_view WHERE size > 5 ORDER BY name", "defaultDataset": {"datasetId": "storage_insights_inv1"}})
check("defaultDataset + WHERE", st == 200 and [r["f"][0]["v"] for r in q["rows"]] == ["dir/y.csv", "z.bin"], q)
st, q = call("POST", f"/bigquery/v2/projects/{P}/queries", {"query": f"SELECT totalBytes, objectCount FROM `storage_insights_inv1.project_attributes_view`"})
check("project_attributes_view totals", st == 200 and [c["v"] for c in q["rows"][0]["f"]] == ["23", "3"], q)
check("non-prefixed bucket excluded", "skip.txt" not in json.dumps(call("GET", f"/bigquery/v2/projects/{P}/datasets/storage_insights_inv1/tables/object_attributes_view/data")[1]))

# the export reflects new objects after :refresh
call("POST", "/upload/storage/v1/b/data-b/o", None, {"uploadType": "media", "name": "late.txt"}, raw=b"12345")
st, r = call("POST", "/storage/v1/insightsDatasets/inv1:refresh")
check(":refresh re-exports", st == 200 and r["tableRowCounts"]["object_attributes_view"] == 4, r)

# BigQuery basics
check("DML refused", call("POST", f"/bigquery/v2/projects/{P}/queries", {"query": "DELETE FROM x"})[0] == 400)
check("missing table 404", call("POST", f"/bigquery/v2/projects/{P}/queries", {"query": f"SELECT * FROM `{P}.nope.t`"})[0] == 404)
check("bad dataset id", call("POST", f"/bigquery/v2/projects/{P}/datasets", {"datasetReference": {"datasetId": "bad-id"}})[0] == 400)
check("create dataset", call("POST", f"/bigquery/v2/projects/{P}/datasets", {"datasetReference": {"datasetId": "mine"}})[0] == 200)
check("dup dataset 409", call("POST", f"/bigquery/v2/projects/{P}/datasets", {"datasetReference": {"datasetId": "mine"}})[0] == 409)
check("create table", call("POST", f"/bigquery/v2/projects/{P}/datasets/mine/tables", {"tableReference": {"tableId": "t"}, "schema": {"fields": [{"name": "a", "type": "INTEGER"}, {"name": "b", "type": "STRING"}]}})[0] == 200)
st, r = call("POST", f"/bigquery/v2/projects/{P}/datasets/mine/tables/t/insertAll", {"rows": [{"json": {"a": 1, "b": "x"}}, {"json": {"a": 2, "b": "y"}}, {"json": {"zz": 1}}]})
check("insertAll reports bad rows", st == 200 and r["insertErrors"][0]["index"] == 2, r)
st, q = call("POST", f"/bigquery/v2/projects/{P}/queries", {"query": "SELECT SUM(a) FROM mine.t"})
check("user table query", st == 200 and q["rows"][0]["f"][0]["v"] == "3", q)
st, j = call("POST", f"/bigquery/v2/projects/{P}/jobs", {"configuration": {"query": {"query": "SELECT b FROM mine.t ORDER BY a"}}})
st2, gq = call("GET", f"/bigquery/v2/projects/{P}/queries/{j['jobReference']['jobId']}")
check("jobs.insert + getQueryResults", st == 200 and st2 == 200 and [r["f"][0]["v"] for r in gq["rows"]] == ["x", "y"], gq)
check("delete non-empty dataset refused", call("DELETE", f"/bigquery/v2/projects/{P}/datasets/mine")[0] == 400)
check("delete config removes the linked dataset", call("DELETE", "/storage/v1/insightsDatasets/inv1")[0] == 204 and call("GET", f"/bigquery/v2/projects/{P}/datasets/storage_insights_inv1")[0] == 404)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
