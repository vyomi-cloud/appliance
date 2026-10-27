"""Unit tests for core/gcp_workflows_core.py (run: python3 tests/conformance/test_gcp_workflows_core.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_workflows_core as wc  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


L = "/v1/projects/p1/locations/us-central1"


def call(st, method, path, body=None, query=None):
    r = wc.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


st = wc.WorkflowsStore()
s, op = call(st, "POST", L + "/workflows", {"sourceContents": wc.DEFAULT_SOURCE, "description": "d"}, {"workflowId": "w1"})
check("create returns a done LRO with the Workflow", s == 200 and op["done"] and op["response"]["name"].endswith("/workflows/w1")
      and op["metadata"]["verb"] == "create" and op["response"]["state"] == "ACTIVE", op)
s, w = call(st, "GET", L + "/workflows/w1")
check("get: ACTIVE, revision 000001-xxx, service account", s == 200 and w["revisionId"].startswith("000001-") and "@developer.gserviceaccount.com" in w["serviceAccount"], w)
check("duplicate -> 409 ALREADY_EXISTS", call(st, "POST", L + "/workflows", {"sourceContents": wc.DEFAULT_SOURCE}, {"workflowId": "w1"})[1]["error"]["status"] == "ALREADY_EXISTS")
check("bad id -> 400", call(st, "POST", L + "/workflows", {"sourceContents": wc.DEFAULT_SOURCE}, {"workflowId": "1bad"})[0] == 400)
check("missing source -> 400", call(st, "POST", L + "/workflows", {}, {"workflowId": "x"})[0] == 400)
check("source without main -> 400", call(st, "POST", L + "/workflows", {"sourceContents": "foo:\n  steps: []\n"}, {"workflowId": "x"})[0] == 400)
check("bad region -> 404", call(st, "POST", "/v1/projects/p1/locations/mars-1/workflows", {"sourceContents": wc.DEFAULT_SOURCE}, {"workflowId": "x"})[0] == 404)
check("bad label -> 400", call(st, "POST", L + "/workflows", {"sourceContents": wc.DEFAULT_SOURCE, "labels": {"Bad": "v"}}, {"workflowId": "x"})[0] == 400)
check("get missing -> 404 NOT_FOUND", call(st, "GET", L + "/workflows/nope")[1]["error"]["status"] == "NOT_FOUND")

s, op = call(st, "PATCH", L + "/workflows/w1", {"description": "new", "labels": {"env": "dev"}}, {"updateMask": "description,labels"})
w = call(st, "GET", L + "/workflows/w1")[1]
check("patch metadata keeps revision", s == 200 and w["description"] == "new" and w["labels"] == {"env": "dev"} and w["revisionId"].startswith("000001-"), w)
src2 = 'main:\n  steps:\n    - done:\n        return: "v2"\n'
call(st, "PATCH", L + "/workflows/w1", {"sourceContents": src2}, {"updateMask": "sourceContents"})
w = call(st, "GET", L + "/workflows/w1")[1]
check("patch source bumps revision", w["revisionId"].startswith("000002-"), w)
s, revs = call(st, "GET", L + "/workflows/w1:listRevisions")
check("listRevisions newest first", s == 200 and len(revs["workflows"]) == 2 and revs["workflows"][0]["revisionId"].startswith("000002-"), revs)
check("patch bad mask -> 400", call(st, "PATCH", L + "/workflows/w1", {"description": "x"}, {"updateMask": "state"})[0] == 400)

for i in range(3):
    call(st, "POST", L + "/workflows", {"sourceContents": wc.DEFAULT_SOURCE}, {"workflowId": "pg%d" % i})
s, page = call(st, "GET", L + "/workflows", query={"pageSize": "2"})
check("list paginates", s == 200 and len(page["workflows"]) == 2 and page.get("nextPageToken"), page)
s, page2 = call(st, "GET", L + "/workflows", query={"pageSize": "2", "pageToken": page["nextPageToken"]})
check("list page 2", len(page2["workflows"]) == 2 and "nextPageToken" not in page2, page2)

s, ex = call(st, "POST", L + "/workflows/w1/executions", {"argument": "{\"a\":1}"})
check("execution runs to SUCCEEDED with literal result", s == 200 and ex["state"] == "SUCCEEDED" and ex["result"] == '"v2"' and ex["workflowRevisionId"].startswith("000002-"), ex)
s, ex0 = call(st, "POST", L + "/workflows/pg0/executions", {})
check("execution resolves ${var} of an assign", ex0["result"] == '"Hello from Vyomi"', ex0)
eid = ex["name"].rsplit("/", 1)[1]
check("get execution", call(st, "GET", L + "/workflows/w1/executions/" + eid)[1]["name"] == ex["name"])
check("list executions", len(call(st, "GET", L + "/workflows/w1/executions")[1]["executions"]) == 1)
check("cancel finished execution -> 400", call(st, "POST", L + "/workflows/w1/executions/%s:cancel" % eid, {})[0] == 400)
check("bad argument -> 400", call(st, "POST", L + "/workflows/w1/executions", {"argument": "{nope"})[0] == 400)
check("execute missing workflow -> 404", call(st, "POST", L + "/workflows/zzz/executions", {})[0] == 404)

s, ops = call(st, "GET", L + "/operations")
check("operations list", s == 200 and len(ops["operations"]) >= 5)
opn = ops["operations"][0]["name"]
check("operation get", call(st, "GET", "/v1/" + opn)[1]["done"] is True)
check("operation delete", call(st, "DELETE", "/v1/" + opn)[0] == 200 and call(st, "GET", "/v1/" + opn)[0] == 404)

s, w = call(st, "GET", L + "/workflows/w1", query={"$alt": "json;enum-encoding=int"})
check("enum-encoding=int", w["state"] == 1, w)
s, op = call(st, "DELETE", L + "/workflows/w1")
check("delete -> LRO Empty, then 404 and executions gone", s == 200 and op["response"]["@type"].endswith("google.protobuf.Empty")
      and call(st, "GET", L + "/workflows/w1")[0] == 404 and not any("/w1/" in n for n in st.executions))
check("locations list", len(call(st, "GET", "/v1/projects/p1/locations")[1]["locations"]) > 5)
v = wc.list_all(st)[0]
check("console view has every column", all(v.get(k) not in (None, "") for k in ("id", "region", "state", "revision", "service_account", "updated", "last_execution")), v)

print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
