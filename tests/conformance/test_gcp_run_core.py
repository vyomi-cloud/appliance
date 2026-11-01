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
st2 = rn.RunStore()
call(st2, "POST", L + "/services", svc_body, {"serviceId": "rv"})
cur = call(st2, "GET", L + "/services/rv")[1]
rname = cur["latestReadyRevision"].rsplit("/", 1)[-1]
same = dict(cur["template"], revision=rname)
check("re-sending the current revision name is a no-op (gcloud update-traffic)", call(st2, "PATCH", L + "/services/rv", {"template": same, "traffic": cur["traffic"]})[0] == 200
      and len(call(st2, "GET", L + "/services/rv/revisions")[1]["revisions"]) == 1)
diff = dict(same, timeout="60s")
check("same revision name with a different template -> 409", call(st2, "PATCH", L + "/services/rv", {"template": diff})[0] == 409)
kn = "/apis/serving.knative.dev/v1/namespaces/p1/services"
r = rn.dispatch(st2, "GET", kn + "/rv", {}, {"Host": "us-central1-run.googleapis.com"}, b"")
k = json.loads(r.body)
check("Knative view of the same service (gcloud run)", r.status == 200 and k["kind"] == "Service" and k["status"]["latestReadyRevisionName"] == rname
      and k["spec"]["template"]["spec"]["containers"][0]["image"] == "gcr.io/x/app:1" and k["status"]["conditions"][0]["status"] == "True", k)
k["spec"]["template"]["spec"]["containers"][0]["image"] = "gcr.io/x/app:3"
k["spec"]["template"]["metadata"]["name"] = ""
r = rn.dispatch(st2, "PUT", kn + "/rv", {}, {"Host": "us-central1-run.googleapis.com"}, json.dumps(k).encode())
check("Knative PUT creates a new revision", r.status == 200 and len(call(st2, "GET", L + "/services/rv/revisions")[1]["revisions"]) == 2, r.body)

# worker pools
st3 = rn.RunStore()
wp_body = {"template": {"containers": [{"image": "gcr.io/x/worker:1"}]}}
s, op = call(st3, "POST", L + "/workerPools", wp_body, {"workerPoolId": "wp1"})
check("create worker pool (LRO)", s == 200 and op["done"] and op["response"]["@type"].endswith("v2.WorkerPool"), op)
s, v = call(st3, "GET", L + "/workerPools/wp1")
check("worker pool defaults (template normalised)", s == 200 and v["template"]["containers"][0]["resources"]["limits"]["memory"] == "512Mi"
      and v["template"]["scaling"]["maxInstanceCount"] == 100, v)
check("duplicate worker pool -> 409", call(st3, "POST", L + "/workerPools", wp_body, {"workerPoolId": "wp1"})[0] == 409)
check("list worker pools", [x["name"].rsplit("/", 1)[-1] for x in call(st3, "GET", L + "/workerPools")[1]["workerPools"]] == ["wp1"])
check("console view for worker pools", rn.list_worker_pools(st3)[0]["image"] == "gcr.io/x/worker:1")
s, op = call(st3, "DELETE", L + "/workerPools/wp1")
check("delete worker pool", s == 200 and call(st3, "GET", L + "/workerPools/wp1")[0] == 404)

# domain mappings (Knative-style facade: gcloud run domain-mappings)
st4 = rn.RunStore()
call(st4, "POST", L + "/services", svc_body, {"serviceId": "web"})
kn_dm = "/apis/domains.cloudrun.com/v1/namespaces/p1/domainmappings"
host = {"Host": "us-central1-run.googleapis.com"}
r = rn.dispatch(st4, "POST", kn_dm, {}, host, json.dumps({"metadata": {"name": "www.example.com"}, "spec": {"routeName": "web"}}).encode())
op = json.loads(r.body)
check("create domain mapping (LRO) with DNS records", r.status == 200 and op["done"]
      and op["response"]["status"]["resourceRecords"][0]["type"] == "CNAME", op)
r = rn.dispatch(st4, "GET", kn_dm + "/www.example.com", {}, host, b"")
check("get domain mapping", r.status == 200 and json.loads(r.body)["spec"]["routeName"] == "web")
r = rn.dispatch(st4, "GET", kn_dm, {}, host, b"")
check("list domain mappings", r.status == 200 and len(json.loads(r.body)["items"]) == 1)
check("console view for domain mappings", rn.list_domain_mappings(st4)[0]["route"] == "web")
r = rn.dispatch(st4, "POST", kn_dm, {}, host, json.dumps({"metadata": {"name": "apex.com"}, "spec": {"routeName": "nope"}}).encode())
check("domain mapping to a missing service -> 400", r.status == 400 and json.loads(r.body)["error"]["status"] == "INVALID_ARGUMENT")
r = rn.dispatch(st4, "POST", kn_dm, {}, host, json.dumps({"metadata": {"name": "apex.com"}, "spec": {"routeName": "web"}}).encode())
check("apex domain gets A records, not CNAME", json.loads(r.body)["response"]["status"]["resourceRecords"][0]["type"] == "A")
r = rn.dispatch(st4, "DELETE", kn_dm + "/www.example.com", {}, host, b"")
check("delete domain mapping", r.status == 200 and rn.dispatch(st4, "GET", kn_dm + "/www.example.com", {}, host, b"").status == 404)

# inline function source (Cloud Run functions "Save and redeploy"): a real redeploy — a new
# revision — and a build-style rejection of broken Python source (consoles/gcp/functions)
st5 = rn.RunStore()
fn_ann = {"vyomi.dev/function-runtime": "Python 3.13", "vyomi.dev/function-entry-point": "handler",
          "vyomi.dev/function-source": "def handler(event):\n    return event\n"}
fn_body = {"template": {"containers": [{"image": "vyomi.dev/function-source/python-3-13:aaaa"}]}, "annotations": dict(fn_ann)}
s, op = call(st5, "POST", L + "/services", fn_body, {"serviceId": "fn1"})
check("create function service", s == 200 and op["response"]["annotations"]["vyomi.dev/function-runtime"] == "Python 3.13", op)
check("deploy rejects a missing entry point", call(st5, "POST", L + "/services",
      {**fn_body, "annotations": {**fn_ann, "vyomi.dev/function-entry-point": "missing"}}, {"serviceId": "fnbad"})[1]["error"]["status"] == "INVALID_ARGUMENT")
check("deploy rejects a syntax error", call(st5, "POST", L + "/services",
      {**fn_body, "annotations": {**fn_ann, "vyomi.dev/function-source": "def ("}}, {"serviceId": "fnbad2"})[1]["error"]["status"] == "INVALID_ARGUMENT")
check("non-python runtime source is stored unparsed", call(st5, "POST", L + "/services",
      {**fn_body, "annotations": {**fn_ann, "vyomi.dev/function-runtime": "Node.js 22", "vyomi.dev/function-source": "not valid js((("}},
      {"serviceId": "fnnode"})[0] == 200)
s, op = call(st5, "PATCH", L + "/services/fn1", {
    "annotations": {**fn_ann, "vyomi.dev/function-source": "def handler(event):\n    return {'ok': True}\n"},
    "template": {"containers": [{"image": "vyomi.dev/function-source/python-3-13:bbbb"}]},
}, {"updateMask": "annotations,template"})
check("saving a source edit redeploys: a real new revision", s == 200
      and len(call(st5, "GET", L + "/services/fn1/revisions")[1]["revisions"]) == 2
      and call(st5, "GET", L + "/services/fn1")[1]["template"]["containers"][0]["image"].endswith(":bbbb"))
check("patch rejects an entry point the saved source doesn't define", call(st5, "PATCH", L + "/services/fn1",
      {"annotations": {**fn_ann, "vyomi.dev/function-entry-point": "nope"}}, {"updateMask": "annotations"})[1]["error"]["status"] == "INVALID_ARGUMENT")
check("rejected patch left the service and its revisions untouched", len(call(st5, "GET", L + "/services/fn1/revisions")[1]["revisions"]) == 2
      and call(st5, "GET", L + "/services/fn1")[1]["annotations"]["vyomi.dev/function-entry-point"] == "handler")


# Eventarc-style triggers (services/{s}/eventarcTriggers) + delivery + Cloud Logging hooks —
# wave 5b gap sweep (gcp.run.services.triggers / observability, gcp.run.jobs.observability):
# real IAM-enforced invoke, real delivery on a real Pub/Sub publish, real log entries, never
# synthetic data.
import base64 as _b64

logged = []


def _log_fn(kind, project, location, rid, message, severity="INFO"):
    logged.append((kind, project, location, rid, message, severity))


st6 = rn.RunStore()


def d(method, path, body=None, query=None, **kw):
    return rn.dispatch(st6, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"", **kw)


s, _op = call(st6, "POST", L + "/services", {"template": {"containers": [{"image": "gcr.io/x/app:1"}]}}, {"serviceId": "api"})
check("create service (setup)", s == 200)

# create/update/delete/setIamPolicy each log a real entry through the dispatch() entry point
logged.clear()
r = d("POST", L + "/services", {"template": {"containers": [{"image": "gcr.io/x/app:1"}]}}, {"serviceId": "lg"}, log_fn=_log_fn)
check("create logs a real 'Service created' entry", r.status == 200 and len(logged) == 1
      and logged[0][:2] == ("service", "p1") and "created" in logged[0][4], logged)
logged.clear()
d("PATCH", L + "/services/lg", {"template": {"containers": [{"image": "gcr.io/x/app:2"}]}}, log_fn=_log_fn)
check("new revision logs 'New revision deployed'", len(logged) == 1 and "New revision deployed" in logged[0][4], logged)
logged.clear()
d("PATCH", L + "/services/lg", {"labels": {"a": "b"}}, {"updateMask": "labels"}, log_fn=_log_fn)
check("config-only patch logs an 'updated' entry, not a new revision", len(logged) == 1
      and "New revision" not in logged[0][4] and "updated" in logged[0][4], logged)
logged.clear()
d("POST", L + "/services/lg:setIamPolicy", {"policy": {"bindings": [{"role": "roles/run.invoker", "members": ["allUsers"]}]}}, log_fn=_log_fn)
check("auth change logs 'Authentication changed'", len(logged) == 1 and "allow unauthenticated" in logged[0][4], logged)
logged.clear()
d("DELETE", L + "/services/lg", log_fn=_log_fn)
check("delete logs 'Service deleted'", len(logged) == 1 and "deleted" in logged[0][4], logged)

# Eventarc-style trigger: nested under the service, bound to a Pub/Sub topic
check("create trigger with an invalid topic resource name -> 400", d("POST", L + "/services/api/eventarcTriggers",
      {"transport": {"pubsub": {"topic": "not-a-resource-name"}}}, {"eventarcTriggerId": "tbad"}).status == 400)
r = d("POST", L + "/services/api/eventarcTriggers", {"transport": {"pubsub": {"topic": "projects/p1/topics/evt"}}}, {"eventarcTriggerId": "t1"})
trg = json.loads(r.body)
check("create trigger on a known topic", r.status == 200 and trg["name"].endswith("/services/api/eventarcTriggers/t1")
      and trg["transport"]["pubsub"]["topic"] == "projects/p1/topics/evt" and "_eventCount" not in trg, trg)
check("topic_exists is enforced when provided", d("POST", L + "/services/api/eventarcTriggers",
      {"transport": {"pubsub": {"topic": "projects/p1/topics/missing"}}}, {"eventarcTriggerId": "t2"},
      topic_exists=lambda t: t == "projects/p1/topics/evt").status == 400)
r = d("GET", L + "/services/api/eventarcTriggers")
check("list triggers for the service", r.status == 200 and len(json.loads(r.body)["triggers"]) == 1)
check("duplicate trigger id -> 409", d("POST", L + "/services/api/eventarcTriggers",
      {"transport": {"pubsub": {"topic": "projects/p1/topics/evt"}}}, {"eventarcTriggerId": "t1"}).status == 409)

# invoke_service: IAM invoker is enforced for a direct (non-internal) call, bypassed for
# internal (Eventarc) delivery — exactly like a real trigger's auto-granted service account.
try:
    rn.invoke_service(st6, "p1", "us-central1", "api", headers={})
    check("invoke without auth on a private service raises", False)
except rn._E as e:
    check("invoke without auth on a private service raises 403", e.status == 403)
check("invoke with a bearer token succeeds", bool(rn.invoke_service(st6, "p1", "us-central1", "api", headers={"authorization": "Bearer faketoken123"})))
check("internal invoke bypasses IAM", bool(rn.invoke_service(st6, "p1", "us-central1", "api", internal=True)))

# deliver_event: a real Pub/Sub publish on the bound topic delivers to the trigger and logs it
logged.clear()
msg = {"data": _b64.b64encode(b"hello").decode(), "attributes": {}}
rn.deliver_event(st6, "projects/p1/topics/evt", [msg], log_fn=_log_fn)
check("delivery logs an Eventarc delivery entry", len(logged) == 1 and "Eventarc trigger t1 delivered" in logged[0][4], logged)
logged.clear()
rn.deliver_event(st6, "projects/p1/topics/nope", [msg], log_fn=_log_fn)
check("delivery to an unbound topic is a no-op", logged == [])

# delete trigger
check("delete trigger", d("DELETE", L + "/services/api/eventarcTriggers/t1").status == 200
      and len(json.loads(d("GET", L + "/services/api/eventarcTriggers").body)["triggers"]) == 0)
check("get a deleted trigger -> 404", json.loads(d("GET", L + "/services/api/eventarcTriggers/t1").body)["error"]["status"] == "NOT_FOUND")

# jobs: run logs a real 'Execution started' entry
s, _op = call(st6, "POST", L + "/jobs", {"template": {"template": {"containers": [{"image": "gcr.io/x/batch:1"}]}}}, {"jobId": "batch"})
check("create job (setup)", s == 200)
logged.clear()
d("POST", L + "/jobs/batch:run", log_fn=_log_fn)
check("run_job logs a real 'Execution started' entry", len(logged) == 1 and logged[0][0] == "job"
      and "Execution" in logged[0][4] and "started" in logged[0][4], logged)

print(f"RESULT pass={PASS} fail={FAIL}")
sys.exit(1 if FAIL else 0)
