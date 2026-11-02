"""Compute resource policies (snapshot schedules + instance schedules) are ENFORCED.
Run: PYTHONPATH=. python3 tests/conformance/test_gcp_compute_resource_policies.py"""
import json
import time

try:
    from core import gcp_compute_instances_core as gce
except ImportError:  # pragma: no cover
    import gcp_compute_instances_core as gce  # type: ignore

P, Z, R = "demo-proj", "us-central1-a", "us-central1"
BASE = "/compute/v1/projects/%s" % P


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print("  ok  " + name)


def call(st, method, path, body=None):
    r = gce.dispatch(st, method, BASE + path, {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


def run():
    st = gce.ComputeStore()
    t0 = 1_800_000_000 - (1_800_000_000 % 86400)       # a midnight UTC
    gce._CLOCK_OVERRIDE = t0 + 3600 * 6                 # 06:00
    try:
        s, _ = call(st, "POST", "/zones/%s/disks" % Z, {"name": "d1", "sizeGb": "20"})
        _check("disk created", s == 200)
        s, e = call(st, "POST", "/regions/%s/resourcePolicies" % R, {"name": "bad"})
        _check("policy needs exactly one kind", s == 400)
        s, e = call(st, "POST", "/regions/%s/resourcePolicies" % R, {"name": "bad", "groupPlacementPolicy": {}})
        _check("unmodelled policy kind -> UNIMPLEMENTED", s == 501)
        s, e = call(st, "POST", "/regions/%s/resourcePolicies" % R, {"name": "bad", "snapshotSchedulePolicy": {"schedule": {"hourlySchedule": {"hoursInCycle": 0, "startTime": "00:00"}}}})
        _check("bad hoursInCycle rejected", s == 400)
        s, e = call(st, "POST", "/regions/%s/resourcePolicies" % R, {"name": "daily", "snapshotSchedulePolicy": {
            "schedule": {"dailySchedule": {"daysInCycle": 1, "startTime": "08:00"}},
            "retentionPolicy": {"maxRetentionDays": 2},
            "snapshotProperties": {"labels": {"auto": "yes"}}}})
        _check("snapshot schedule created", s == 200)
        s, e = call(st, "POST", "/zones/%s/disks/d1/addResourcePolicies" % Z, {"resourcePolicies": ["projects/%s/regions/%s/resourcePolicies/daily" % (P, R)]})
        _check("attached to disk", s == 200)
        s, v = call(st, "GET", "/zones/%s/disks/d1" % Z)
        _check("disk shows resourcePolicies", len(v["resourcePolicies"]) == 1)
        s, e = call(st, "DELETE", "/regions/%s/resourcePolicies/daily" % R)
        _check("attached policy cannot be deleted", s == 400)
        _check("no snapshot before the first tick", call(st, "GET", "/global/snapshots")[1]["items"] == [])
        gce._CLOCK_OVERRIDE = t0 + 3600 * 9                 # 09:00 — the 08:00 tick fell due
        items = call(st, "GET", "/global/snapshots")[1]["items"]
        _check("a snapshot was really taken at the 08:00 tick", len(items) == 1 and items[0]["creationTimestamp"].startswith(gce._iso(t0 + 8 * 3600)[:16]))
        _check("auto snapshot carries schedule labels", items[0]["labels"].get("auto") == "yes" and items[0]["autoCreated"])
        gce._CLOCK_OVERRIDE = t0 + 86400 * 1 + 3600 * 9
        _check("next day's tick takes a second snapshot", len(call(st, "GET", "/global/snapshots")[1]["items"]) == 2)
        gce._CLOCK_OVERRIDE = t0 + 86400 * 3 + 3600 * 9
        names = [x["creationTimestamp"] for x in call(st, "GET", "/global/snapshots")[1]["items"]]
        _check("retention expired snapshots older than 2 days", len(names) >= 1 and all(
            (gce._clock() - time.mktime(time.strptime(n[:19], "%Y-%m-%dT%H:%M:%S")) + time.timezone) <= 2 * 86400 for n in names))
        s, e = call(st, "POST", "/zones/%s/disks/d1/removeResourcePolicies" % Z, {"resourcePolicies": ["daily"]})
        _check("detach", s == 200)
        s, e = call(st, "DELETE", "/regions/%s/resourcePolicies/daily" % R)
        _check("detached policy deletes", s == 200)

        # instance schedule
        gce._CLOCK_OVERRIDE = t0 + 3600 * 6
        s, e = call(st, "POST", "/zones/%s/instances" % Z, {"name": "vm1", "machineType": "e2-medium", "disks": [{"boot": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12", "diskSizeGb": 10}}]})
        _check("instance created", s == 200)
        s, e = call(st, "POST", "/regions/%s/resourcePolicies" % R, {"name": "office", "instanceSchedulePolicy": {
            "vmStartSchedule": {"schedule": "0 9 * * *"}, "vmStopSchedule": {"schedule": "0 18 * * *"}, "timeZone": "UTC"}})
        _check("instance schedule created", s == 200)
        s, e = call(st, "POST", "/regions/%s/resourcePolicies" % R, {"name": "badcron", "instanceSchedulePolicy": {"vmStartSchedule": {"schedule": "nope"}}})
        _check("bad cron rejected", s == 400)
        s, e = call(st, "POST", "/zones/%s/instances/vm1/addResourcePolicies" % Z, {"resourcePolicies": ["office"]})
        _check("attached to instance", s == 200)
        s, e = call(st, "POST", "/zones/%s/disks/d1/addResourcePolicies" % Z, {"resourcePolicies": ["office"]})
        _check("instance schedule cannot attach to a disk", s == 400)
        gce._CLOCK_OVERRIDE = t0 + 3600 * 19                # past 18:00 stop
        status = call(st, "GET", "/zones/%s/instances/vm1" % Z)[1]["status"]
        _check("VM was really stopped by the 18:00 tick", status == "TERMINATED")
        gce._CLOCK_OVERRIDE = t0 + 86400 + 3600 * 10        # next morning, past 09:00 start
        status = call(st, "GET", "/zones/%s/instances/vm1" % Z)[1]["status"]
        _check("VM was really started by the next 09:00 tick", status == "RUNNING")
    finally:
        gce._CLOCK_OVERRIDE = None
    print("RESULT ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
