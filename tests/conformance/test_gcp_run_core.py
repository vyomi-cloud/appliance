"""Unit tests for core/gcp_run_core.py (run: python3 tests/conformance/test_gcp_run_core.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_run_core as rn  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


L = "/v2/projects/p1/locations/us-central1"


def call(st, method, path, body=None, query=None):
    r = rn.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


st = rn.RunStore()
svc_body = {"template": {"containers": [{"image": "gcr.io/x/app:1"}]}, "labels": {"env": "dev"}}
s, op = call(st, "POST", L + "/services", svc_body, {"serviceId": "web"})
check("create returns a done Operation carrying the Service", s == 200 and op["done"] and op["response"]["name"].endswith("/services/web")
      and op["response"]["@type"].endswith("google.cloud.run.v2.Service"), op)
s, v = call(st, "GET", L + "/services/web")
check("get: defaults, uri, Ready, traffic, revision", s == 200 and v["generation"] == "1" and v["uri"].startswith("https://web-")
      and v["uri"].endswith(".us-central1.run.app") and v["terminalCondition"]["state"] == "CONDITION_SUCCEEDED"
      and v["traffic"] == [{"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 100}]
      and v["template"]["timeout"] == "300s" and v["template"]["containers"][0]["resources"]["limits"]["memory"] == "512Mi"
      and v["template"]["maxInstanceRequestConcurrency"] == 80 and v["latestReadyRevision"].endswith(v["trafficStatuses"][0]["revision"]), v)
check("duplicate -> 409 ALREADY_EXISTS", call(st, "POST", L + "/services", svc_body, {"serviceId": "web"})[0] == 409)
check("bad id -> 400", call(st, "POST", L + "/services", svc_body, {"serviceId": "Bad_Id"})[0] == 400)
check("missing image -> 400", call(st, "POST", L + "/services", {"template": {"containers": [{}]}}, {"serviceId": "x"})[0] == 400)
check("missing serviceId -> 400", call(st, "POST", L + "/services", svc_body)[0] == 400)
check("bad location -> 400", call(st, "POST", "/v2/projects/p1/locations/mars-1/services", svc_body, {"serviceId": "x"})[0] == 400)
check("get missing -> 404 NOT_FOUND", call(st, "GET", L + "/services/nope")[1]["error"]["status"] == "NOT_FOUND")
check("list", [x["name"].rsplit("/", 1)[-1] for x in call(st, "GET", L + "/services")[1]["services"]] == ["web"])
s, revs = call(st, "GET", L + "/services/web/revisions")
check("one revision with the service backref", s == 200 and len(revs["revisions"]) == 1 and revs["revisions"][0]["service"].endswith("/services/web"))
s, op = call(st, "PATCH", L + "/services/web", {"template": {"containers": [{"image": "gcr.io/x/app:2"}]}})
v = call(st, "GET", L + "/services/web")[1]
check("patch template -> generation 2, new revision", s == 200 and v["generation"] == "2" and len(call(st, "GET", L + "/services/web/revisions")[1]["revisions"]) == 2
      and v["template"]["containers"][0]["image"].endswith(":2"), v)
call(st, "PATCH", L + "/services/web", {"labels": {"a": "b"}}, {"updateMask": "labels"})
check("patch labels (mask) keeps template/revisions", call(st, "GET", L + "/services/web")[1]["labels"] == {"a": "b"}
      and len(call(st, "GET", L + "/services/web/revisions")[1]["revisions"]) == 2)
check("traffic must sum to 100", call(st, "PATCH", L + "/services/web", {"traffic": [{"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 50}]})[0] == 400)
first = sorted(r["name"].rsplit("/", 1)[-1] for r in call(st, "GET", L + "/services/web/revisions")[1]["revisions"])[0]
check("PATCH with integer enums", call(st, "PATCH", L + "/services/web", {"ingress": 2}, {"updateMask": "ingress"})[0] == 200
      and call(st, "GET", L + "/services/web")[1]["ingress"] == "INGRESS_TRAFFIC_INTERNAL_ONLY")
s, _ = call(st, "PATCH", L + "/services/web", {"traffic": [{"type": 2, "revision": first, "percent": 100}]}, {"updateMask": "traffic"})
check("traffic pinned to a revision", s == 200 and call(st, "GET", L + "/services/web")[1]["trafficStatuses"][0]["revision"] == first)
check("serving revision cannot be deleted", call(st, "DELETE", L + "/services/web/revisions/" + first)[0] == 400)
latest = call(st, "GET", L + "/services/web")[1]["latestReadyRevision"].rsplit("/", 1)[-1]
check("non-serving revision deletes", call(st, "DELETE", L + "/services/web/revisions/" + latest)[0] == 200
      and call(st, "GET", L + "/services/web/revisions/" + latest)[0] == 404)
fullname = "projects/p1/locations/us-central1/services/web"
check("auth text is private by default", rn.list_all(st)[0]["authentication"] == "Require authentication")
pol = {"policy": {"bindings": [{"role": "roles/run.invoker", "members": ["allUsers"]}]}}
s, p = call(st, "POST", L + "/services/web:setIamPolicy", pol)
check("setIamPolicy/getIamPolicy round-trip", s == 200 and call(st, "GET", L + "/services/web:getIamPolicy")[1]["bindings"] == pol["policy"]["bindings"])
check("console view reflects allUsers invoker", rn.list_all(st)[0]["authentication"] == "Allow unauthenticated")
check("testIamPermissions", call(st, "POST", L + "/services/web:testIamPermissions", {"permissions": ["run.services.get", "x.y.z"]})[1]["permissions"] == ["run.services.get"])
check("validateOnly create persists nothing", call(st, "POST", L + "/services", svc_body, {"serviceId": "dry", "validateOnly": "true"})[0] == 200
      and call(st, "GET", L + "/services/dry")[0] == 404)
s, op = call(st, "DELETE", L + "/services/web")
check("delete returns the deleted service; revisions and policy gone", s == 200 and op["done"] and "deleteTime" in op["response"]
      and call(st, "GET", L + "/services/web")[0] == 404 and not st.revisions and fullname not in st.policies)
# jobs
job = {"template": {"taskCount": 2, "template": {"containers": [{"image": "gcr.io/x/job:1", "args": ["a"]}]}}}
s, op = call(st, "POST", L + "/jobs", job, {"jobId": "etl"})
check("create job (LRO)", s == 200 and op["done"] and op["response"]["@type"].endswith("v2.Job"), op)
j = call(st, "GET", L + "/jobs/etl")[1]
check("job defaults", j["template"]["taskCount"] == 2 and j["template"]["template"]["maxRetries"] == 3
      and j["template"]["template"]["timeout"] == "600s" and j["executionCount"] == 0, j)
check("job without task template -> 400", call(st, "POST", L + "/jobs", {"template": {}}, {"jobId": "bad"})[0] == 400)
check("duplicate job -> 409", call(st, "POST", L + "/jobs", job, {"jobId": "etl"})[0] == 409)
s, op = call(st, "POST", L + "/jobs/etl:run", {})
ex = op["response"]
check("run -> Execution with counts", s == 200 and ex["taskCount"] == 2 and ex["succeededCount"] == 2 and ex["job"] == "etl", op)
eid = ex["name"].rsplit("/", 1)[-1]
check("job.latestCreatedExecution + executionCount", call(st, "GET", L + "/jobs/etl")[1]["latestCreatedExecution"]["name"] == ex["name"]
      and call(st, "GET", L + "/jobs/etl")[1]["executionCount"] == 1)
check("get/list execution", call(st, "GET", L + "/jobs/etl/executions/" + eid)[0] == 200
      and len(call(st, "GET", L + "/jobs/etl/executions")[1]["executions"]) == 1)
tasks = call(st, "GET", L + "/jobs/etl/executions/%s/tasks" % eid)[1]["tasks"]
check("tasks listed with index/exit code", [t["index"] for t in tasks] == [0, 1] and tasks[0]["lastAttemptResult"]["exitCode"] == 0)
check("get task", call(st, "GET", tasks[0]["name"].replace("projects", "/v2/projects", 1))[0] == 200)
check("run override taskCount", call(st, "POST", L + "/jobs/etl:run", {"overrides": {"taskCount": 3}})[1]["response"]["taskCount"] == 3)
check("cancel a completed execution -> 400 FAILED_PRECONDITION", call(st, "POST", L + "/jobs/etl/executions/%s:cancel" % eid)[1]["error"]["status"] == "FAILED_PRECONDITION")
call(st, "PATCH", L + "/jobs/etl", {"labels": {"x": "y"}}, {"updateMask": "labels"})
check("patch job", call(st, "GET", L + "/jobs/etl")[1]["labels"] == {"x": "y"} and call(st, "GET", L + "/jobs/etl")[1]["generation"] == "2")
check("delete execution", call(st, "DELETE", L + "/jobs/etl/executions/" + eid)[0] == 200 and call(st, "GET", L + "/jobs/etl/executions/" + eid)[0] == 404)
# operations
s, ops = call(st, "GET", L + "/operations")
check("operations list + get + wait", s == 200 and len(ops["operations"]) >= 6
      and call(st, "GET", "/v2/" + ops["operations"][0]["name"])[0] == 200
      and call(st, "POST", "/v2/" + ops["operations"][0]["name"] + ":wait", {})[1]["done"])
check("delete operation", call(st, "DELETE", "/v2/" + ops["operations"][0]["name"])[0] == 200 and call(st, "GET", "/v2/" + ops["operations"][0]["name"])[0] == 404)
for i in range(3):
    call(st, "POST", L + "/services", svc_body, {"serviceId": "pg%d" % i})
s, pg = call(st, "GET", L + "/services", None, {"pageSize": "2"})
check("pagination", len(pg["services"]) == 2 and pg["nextPageToken"] and len(call(st, "GET", L + "/services", None, {"pageSize": "2", "pageToken": pg["nextPageToken"]})[1]["services"]) == 1)
f = rn.job_from_form({"name": "svc9", "region": "europe-west1", "image": "gcr.io/x/y", "allowUnauthenticated": "true"})
check("form -> request", f["serviceId"] == "svc9" and f["parent"].endswith("europe-west1") and f["service"]["template"]["containers"][0]["image"] == "gcr.io/x/y" and f["allowUnauthenticated"])
print(f"RESULT pass={PASS} fail={FAIL}")
sys.exit(1 if FAIL else 0)
