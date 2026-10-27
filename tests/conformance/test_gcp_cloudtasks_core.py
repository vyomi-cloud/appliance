"""Unit tests for core/gcp_cloudtasks_core.py (Cloud Tasks v2 engine)."""
import base64
import json

from core import gcp_cloudtasks_core as ct

P = "/v2/projects/p1/locations/us-central1"


def call(store, method, path, body=None, query=None):
    r = ct.dispatch(store, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


def mkq(store, qid="q1", **extra):
    return call(store, "POST", f"{P}/queues", {"name": f"projects/p1/locations/us-central1/queues/{qid}", **extra})


def test_queue_lifecycle_and_defaults():
    s = ct.CloudTasksStore()
    st, q = mkq(s)
    assert st == 200 and q["state"] == "RUNNING"
    assert q["rateLimits"]["maxDispatchesPerSecond"] == 500.0 and q["retryConfig"]["maxAttempts"] == 100
    assert mkq(s)[0] == 409
    assert call(s, "GET", f"{P}/queues/q1")[1]["name"].endswith("/queues/q1")
    assert call(s, "GET", f"{P}/queues")[1]["queues"][0]["name"].endswith("/q1")
    st, q = call(s, "PATCH", f"{P}/queues/q1", {"rateLimits": {"maxDispatchesPerSecond": 10}},
                 {"updateMask": "rateLimits.maxDispatchesPerSecond"})
    assert st == 200 and q["rateLimits"]["maxDispatchesPerSecond"] == 10.0
    assert call(s, "POST", f"{P}/queues/q1:pause", {})[1]["state"] == "PAUSED"
    assert call(s, "POST", f"{P}/queues/q1:resume", {})[1]["state"] == "RUNNING"
    assert call(s, "DELETE", f"{P}/queues/q1")[0] == 200
    st, e = call(s, "GET", f"{P}/queues/q1")
    assert st == 404 and e["error"]["status"] == "NOT_FOUND"


def test_validation():
    s = ct.CloudTasksStore()
    assert mkq(s, "bad_name")[0] == 400
    assert mkq(s, "ok", retryConfig={"minBackoff": "10s", "maxBackoff": "1s"})[0] == 400
    assert call(s, "POST", f"{P}/queues", {"name": "projects/p1/locations/europe-west1/queues/x"})[0] == 400


def test_tasks_and_run():
    s = ct.CloudTasksStore()
    mkq(s)
    body = base64.b64encode(b"hello").decode()
    st, t = call(s, "POST", f"{P}/queues/q1/tasks",
                 {"task": {"httpRequest": {"url": "https://example.com/h", "body": body}}})
    assert st == 200 and "body" not in t["httpRequest"] and t["view"] == "BASIC"
    assert t["httpRequest"]["httpMethod"] == "POST" and t["dispatchCount"] == 0
    name = t["name"].rsplit("/", 1)[-1]
    st, full = call(s, "GET", f"{P}/queues/q1/tasks/{name}", query={"responseView": "FULL"})
    assert full["httpRequest"]["body"] == body
    assert call(s, "POST", f"{P}/queues/q1/tasks", {"task": {"name": t["name"], "httpRequest": {"url": "http://x.io"}}})[0] == 409
    assert call(s, "POST", f"{P}/queues/q1/tasks", {"task": {"httpRequest": {"url": "ftp://x"}}})[0] == 400
    assert len(call(s, "GET", f"{P}/queues/q1/tasks")[1]["tasks"]) == 1
    st, ran = call(s, "POST", f"{P}/queues/q1/tasks/{name}:run", {})
    assert st == 200 and ran["dispatchCount"] == 1 and ran["lastAttempt"]["responseStatus"]["code"] == 0
    assert call(s, "GET", f"{P}/queues/q1/tasks/{name}")[0] == 404


def test_failed_delivery_keeps_task_and_purge():
    s = ct.CloudTasksStore()
    mkq(s)
    call(s, "POST", f"{P}/queues/q1/tasks", {"task": {"name": f"{P[4:]}/queues/q1/tasks/t1", "httpRequest": {"url": "http://x.io"}}})
    ct.set_deliverer(lambda t: (503, "unavailable"))
    try:
        st, ran = call(s, "POST", f"{P}/queues/q1/tasks/t1:run", {})
        assert ran["dispatchCount"] == 1 and ran["lastAttempt"]["responseStatus"]["code"] != 0
        assert call(s, "GET", f"{P}/queues/q1/tasks/t1")[0] == 200
    finally:
        ct.set_deliverer(None)
    assert "purgeTime" in call(s, "POST", f"{P}/queues/q1:purge", {})[1]
    assert call(s, "GET", f"{P}/queues/q1/tasks")[1] == {"tasks": []}


def test_iam_locations_and_pagination():
    s = ct.CloudTasksStore()
    for i in range(3):
        mkq(s, f"q{i}")
    st, page = call(s, "GET", f"{P}/queues", query={"pageSize": "2"})
    assert len(page["queues"]) == 2 and page["nextPageToken"]
    st, rest = call(s, "GET", f"{P}/queues", query={"pageSize": "2", "pageToken": page["nextPageToken"]})
    assert len(rest["queues"]) == 1 and "nextPageToken" not in rest
    pol = {"policy": {"bindings": [{"role": "roles/cloudtasks.enqueuer", "members": ["user:a@b.c"]}]}}
    assert call(s, "POST", f"{P}/queues/q0:setIamPolicy", pol)[1]["bindings"]
    assert call(s, "POST", f"{P}/queues/q0:getIamPolicy", {})[1]["bindings"][0]["role"].endswith("enqueuer")
    assert call(s, "POST", f"{P}/queues/q0:testIamPermissions", {"permissions": ["cloudtasks.tasks.run", "x.y"]})[1] == {"permissions": ["cloudtasks.tasks.run"]}
    assert call(s, "GET", "/v2/projects/p1/locations")[1]["locations"]
    assert call(s, "GET", P)[1]["locationId"] == "us-central1"


def test_update_creates_missing_and_console_view():
    s = ct.CloudTasksStore()
    st, q = call(s, "PATCH", f"{P}/queues/new", {"rateLimits": {"maxConcurrentDispatches": 5}})
    assert st == 200 and q["rateLimits"]["maxConcurrentDispatches"] == 5
    v = ct.console_list(s)[0]
    assert all(x not in ("", None) for x in v.values())
