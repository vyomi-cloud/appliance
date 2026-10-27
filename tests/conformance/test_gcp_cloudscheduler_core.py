"""Unit tests for core/gcp_cloudscheduler_core.py (run: python3 tests/conformance/test_gcp_cloudscheduler_core.py)."""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_cloudscheduler_core as cs  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


P = "/v1/projects/p1/locations/us-central1/jobs"


def call(st, method, path, body=None, query=None, invoker=None):
    r = cs.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"", invoker=invoker)
    return r.status, json.loads(r.body or b"{}")


def job(name, **kw):
    j = {"name": f"projects/p1/locations/us-central1/jobs/{name}", "schedule": "*/5 * * * *",
         "httpTarget": {"uri": "https://example.com/hook", "httpMethod": "POST"}}
    j.update(kw)
    return j


def main():
    st = cs.CloudSchedulerStore()
    s, b = call(st, "POST", P, job("j1", description="d"))
    check("create job", s == 200 and b["state"] == "ENABLED" and b["timeZone"] == "Etc/UTC" and b["scheduleTime"], b)
    s, b = call(st, "POST", P, job("j1"))
    check("duplicate → 409 ALREADY_EXISTS", s == 409 and b["error"]["status"] == "ALREADY_EXISTS", b)
    s, b = call(st, "POST", P, job("j2", schedule="bad cron"))
    check("bad cron → 400 INVALID_ARGUMENT", s == 400 and b["error"]["status"] == "INVALID_ARGUMENT", b)
    s, b = call(st, "POST", P, {"name": job("j3")["name"], "schedule": "* * * * *"})
    check("no target → 400", s == 400, b)
    s, b = call(st, "POST", P, job("j4", pubsubTarget={"topicName": "projects/p1/topics/t"}))
    check("two targets → 400", s == 400, b)
    s, b = call(st, "POST", P, job("j5", timeZone="Mars/Olympus"))
    check("unknown time zone → 400", s == 400, b)
    s, b = call(st, "GET", P + "/j1")
    check("get job", s == 200 and b["description"] == "d", b)
    s, b = call(st, "GET", P + "/nope")
    check("get missing → 404 NOT_FOUND", s == 404 and b["error"]["status"] == "NOT_FOUND", b)
    for i in range(3):
        call(st, "POST", P, job(f"p{i}"))
    s, b = call(st, "GET", P, query={"pageSize": "2"})
    check("list paginates", s == 200 and len(b["jobs"]) == 2 and b["nextPageToken"], b)
    s, b2 = call(st, "GET", P, query={"pageSize": "10", "pageToken": b["nextPageToken"]})
    check("list next page", s == 200 and len(b2["jobs"]) == 2 and "nextPageToken" not in b2, b2)
    s, b = call(st, "PATCH", P + "/j1", {"schedule": "0 9 * * 1-5", "timeZone": "America/New_York"}, {"updateMask": "schedule,timeZone"})
    check("patch schedule + timeZone", s == 200 and b["schedule"] == "0 9 * * 1-5" and b["timeZone"] == "America/New_York", b)
    s, b = call(st, "POST", P + "/j1:pause")
    check("pause", s == 200 and b["state"] == "PAUSED" and "scheduleTime" not in b, b)
    s, b = call(st, "POST", P + "/j1:run")
    check("run paused job → 400 FAILED_PRECONDITION", s == 400 and b["error"]["status"] == "FAILED_PRECONDITION", b)
    s, b = call(st, "POST", P + "/j1:resume")
    check("resume", s == 200 and b["state"] == "ENABLED" and b["scheduleTime"], b)
    s, b = call(st, "POST", P + "/j1:run")
    check("run stamps lastAttemptTime", s == 200 and b.get("lastAttemptTime") and b["status"] == {}, b)
    seen = []
    call(st, "POST", P, job("ps", pubsubTarget={"topicName": "projects/p1/topics/t", "data": "aGk="}, httpTarget=None))
    s, b = call(st, "POST", P + "/ps:run", invoker=lambda kind, d: seen.append((kind, d)) or True)
    check("pubsub target delivered via invoker", s == 200 and seen and seen[0][1]["topicName"] == "projects/p1/topics/t", (b, seen))
    s, b = call(st, "POST", P + "/ps:run", invoker=lambda kind, d: "topic not found")
    check("invoker failure recorded in status", s == 200 and b["status"].get("code") == 5, b)
    # lazy scheduler: a job whose scheduleTime passed fires once on next read
    st.jobs["projects/p1/locations/us-central1/jobs/p0"]["scheduleTime"] = "2020-01-01T00:00:00.000000Z"
    s, b = call(st, "GET", P + "/p0")
    check("due job fires lazily and reschedules", b.get("lastAttemptTime") and b["scheduleTime"] > "2021", b)
    s, b = call(st, "DELETE", P + "/j1")
    check("delete → {}", s == 200 and b == {}, b)
    s, b = call(st, "DELETE", P + "/j1")
    check("delete again → 404", s == 404, b)
    s, b = call(st, "GET", "/v1/projects/p1/locations")
    check("locations.list", s == 200 and any(l["locationId"] == "us-central1" for l in b["locations"]), b)
    s, b = call(st, "POST", "/v1/projects/p1/locations/mars-1/jobs", job("x"))
    check("invalid location → 404", s == 404, b)
    # wire encodings used by the Java/.NET REST clients
    s, b = call(st, "POST", P, {**job("e1"), "httpTarget": {"uri": "https://example.com/", "httpMethod": 6}}, query={"$alt": "json;enum-encoding=int"})
    check("integer enums accepted in and returned (enum-encoding=int)", s == 200 and b["state"] == 1 and b["httpTarget"]["httpMethod"] == 6, b)
    r = cs.dispatch(st, "POST", P + "/e1", {}, {"X-HTTP-Method-Override": "PATCH"}, json.dumps({"description": "via override"}).encode())
    check("POST + X-HTTP-Method-Override: PATCH", r.status == 200 and json.loads(r.body)["description"] == "via override", r.body)
    # cron semantics
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    check("cron */15", cs.next_run("*/15 * * * *", "UTC", t0).minute == 15)
    n = cs.next_run("0 9 * * 1-5", "America/New_York", t0)
    check("cron weekday 9am New York = 14:00Z in January", n.hour == 14 and n.weekday() < 5, n)
    check("cron dom OR dow", cs.next_run("0 0 13 * 5", "UTC", t0).day in (2, 9, 13))
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
