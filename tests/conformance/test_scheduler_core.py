"""EventBridge Scheduler conformance — schedule + schedule-group CRUD on the
native REST wire, and the lazy-advance firing mechanism (a schedule whose
computed next occurrence has passed fires the next time the API is polled,
delivering to its SQS/SNS/Lambda target via core/eventbridge_core.deliver).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_scheduler_core.py
"""
import json
from datetime import datetime, timedelta, timezone

try:
    from core.messaging_store import InMemoryMessagingStore
    from core import sqs_core as sqs, scheduler_core as sch
except ImportError:  # pragma: no cover - Pyodide flat layout
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import sqs_core as sqs  # type: ignore
    import scheduler_core as sch  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    msg = InMemoryMessagingStore()
    qurl = sqs.dispatch(msg, "AmazonSQS.CreateQueue", {"QueueName": "sched-q"}).body["QueueUrl"]
    qarn = sqs.dispatch(msg, "AmazonSQS.GetQueueAttributes", {"QueueUrl": qurl}).body["Attributes"]["QueueArn"]
    store = sch.SchedulerStore()

    def call(method, path, query=None, body=None):
        b = json.dumps(body).encode() if body is not None else b""
        r = sch.dispatch(store, method, path, query or {}, {}, b, msg_store=msg, lam_store=None)
        r.json = json.loads(r.body) if r.body else {}
        return r

    # 1. Default schedule group exists; custom groups are real resources.
    _check("default group exists", any(g["Name"] == "default" for g in call("GET", "/schedule-groups").json["ScheduleGroups"]))
    created = call("POST", "/schedule-groups/batch-jobs")
    _check("CreateScheduleGroup 200", created.status == 200)
    dup = call("POST", "/schedule-groups/batch-jobs")
    _check("duplicate group rejected", dup.status == 409)

    # 2. A one-time "at()" schedule in the past fires on the very next poll (the
    #    lazy-advance mechanism, since Vyomi has no background timer).
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).strftime("at(%Y-%m-%dT%H:%M:%S)")
    r = call("POST", "/schedules/one-shot", body={
        "GroupName": "batch-jobs", "ScheduleExpression": past,
        "Target": {"Arn": qarn, "Input": json.dumps({"job": "cleanup"})}})
    _check("CreateSchedule 200", r.status == 200)
    got = call("GET", "/schedules/one-shot", query={"GroupName": "batch-jobs"}).json
    _check("polling advances and fires the due one-shot", got["LastInvocationTime"] is not None)
    delivered = sqs.dispatch(msg, "AmazonSQS.ReceiveMessage", {"QueueUrl": qurl, "MaxNumberOfMessages": 10}).body.get("Messages", [])
    _check("fired schedule delivers its Input to the target", len(delivered) == 1 and
           json.loads(delivered[0]["Body"]) == {"job": "cleanup"})
    _check("one-shot does not re-arm (no NextInvocationTime)", got["NextInvocationTime"] is None)

    # 3. A rate() schedule recurs: each poll past the next occurrence fires once
    #    and recomputes the next occurrence (never goes stale).
    near = (datetime.now(timezone.utc) - timedelta(seconds=1))
    call("POST", "/schedules/heartbeat", body={
        "GroupName": "batch-jobs", "ScheduleExpression": "rate(1 minute)",
        "Target": {"Arn": qarn, "Input": json.dumps({"tick": 1})}})
    # Force the first occurrence into the past by polling right after creation won't
    # fire yet (next run is ~1 minute out) — simulate time having passed instead.
    sched_key = "batch-jobs/heartbeat"
    store.schedules[sched_key]["next_run_dt"] = near.timestamp()   # epoch seconds (JSON-safe state)
    call("GET", "/schedules", query={"GroupName": "batch-jobs"})
    after_first = store.schedules[sched_key]
    _check("rate() schedule fired once it was due", after_first["last_run"] is not None)
    _check("rate() schedule re-armed with a NEW future occurrence", after_first["next_run_dt"] > near.timestamp())
    _check("schedule state is JSON-serializable (persists on every substrate)", bool(json.dumps(store.schedules)))

    # 4. List / delete.
    names = [s["Name"] for s in call("GET", "/schedules", query={"GroupName": "batch-jobs"}).json["Schedules"]]
    _check("ListSchedules sees both", set(names) == {"one-shot", "heartbeat"})
    d = call("DELETE", "/schedules/heartbeat", query={"GroupName": "batch-jobs"})
    _check("DeleteSchedule 200", d.status == 200)
    nf = call("GET", "/schedules/heartbeat", query={"GroupName": "batch-jobs"})
    _check("deleted schedule is gone", nf.status == 404)

    # 5. Deleting a group deletes its schedules; the default group can't be deleted.
    call("DELETE", "/schedule-groups/batch-jobs")
    _check("deleting a group removes its schedules",
           call("GET", "/schedules").json["Schedules"] == [])
    cantdelete = call("DELETE", "/schedule-groups/default")
    _check("the default group cannot be deleted", cantdelete.status == 400)

    print("\nRESULT: PASS — EventBridge Scheduler conforms (native wire semantics) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
