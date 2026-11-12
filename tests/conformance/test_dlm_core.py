"""Data Lifecycle Manager core (wave 5b gap sweep, ec2.lifecycle-manager) — a policy
really creates (and prunes) snapshots/AMIs for tagged resources through the SAME
vpc_core CreateSnapshot/CreateImage path the console's manual actions use.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_dlm_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json
import re

try:
    from core import dlm_core as dlm
    from core import vpc_core as vpc
    from core.aws_wire_router import AwsWireRouter
except ImportError:  # pragma: no cover - Pyodide flat layout
    import dlm_core as dlm  # type: ignore
    import vpc_core as vpc  # type: ignore
    from aws_wire_router import AwsWireRouter  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    r = AwsWireRouter()

    def call(method, path, body=None, query=None):
        raw = json.dumps(body).encode() if body is not None else b""
        resp = dlm.dispatch(r.dlm, method, path, query or {}, {}, raw)
        return resp.status, json.loads(resp.body or b"{}")

    vol = vpc.dispatch(r.vpc, {"Action": "CreateVolume", "AvailabilityZone": "us-east-1a", "Size": "8",
                              "TagSpecification.1.ResourceType": "volume",
                              "TagSpecification.1.Tag.1.Key": "Backup", "TagSpecification.1.Tag.1.Value": "daily"}).body
    vol_id = re.search(r"<volumeId>(.*?)</volumeId>", vol).group(1)

    status, body = call("POST", "/policies", {
        "Description": "daily volume backups", "State": "ENABLED",
        "PolicyDetails": {"ResourceTypes": ["VOLUME"], "TargetTags": [{"Key": "Backup", "Value": "daily"}],
                          "Schedules": [{"Name": "daily", "CreateRule": {"Interval": 24, "IntervalUnit": "HOURS"},
                                        "RetainRule": {"Count": 2}}]}})
    _check("CreateLifecyclePolicy succeeds", status == 200 and body.get("PolicyId"))
    policy_id = body["PolicyId"]

    status, body = call("GET", f"/policies/{policy_id}")
    _check("GetLifecyclePolicy round-trips", status == 200 and body["Policy"]["State"] == "ENABLED")

    snaps = vpc.dispatch(r.vpc, {"Action": "DescribeSnapshots"}).body
    _check("evaluating the policy really created a snapshot for the tagged volume",
           snaps.count(f"<volumeId>{vol_id}</volumeId>") == 1)

    status, body = call("GET", f"/policies/{policy_id}")
    _check("LastRunStatus now reports success", body["Policy"]["LastRunStatus"] == "SUCCESS")

    untagged = vpc.dispatch(r.vpc, {"Action": "CreateVolume", "AvailabilityZone": "us-east-1a", "Size": "8"}).body
    untagged_id = re.search(r"<volumeId>(.*?)</volumeId>", untagged).group(1)
    snaps2 = vpc.dispatch(r.vpc, {"Action": "DescribeSnapshots"}).body
    _check("an untagged volume is never touched by the policy", f"<volumeId>{untagged_id}</volumeId>" not in snaps2)

    # force the schedule due again and re-evaluate — RetainRule.Count=2 prunes the oldest
    r.dlm.policies[policy_id]["_schedule_state"]["daily"]["next_due"] = 0
    call("GET", "/policies")
    r.dlm.policies[policy_id]["_schedule_state"]["daily"]["next_due"] = 0
    call("GET", "/policies")
    snaps3 = vpc.dispatch(r.vpc, {"Action": "DescribeSnapshots"}).body
    _check("RetainRule.Count=2 is really enforced (only 2 of this volume's snapshots survive)",
           snaps3.count(f"<volumeId>{vol_id}</volumeId>") == 2)

    status, body = call("PATCH", f"/policies/{policy_id}", {"State": "DISABLED"})
    _check("UpdateLifecyclePolicy succeeds", status == 200)
    _check("disabled policy state round-trips", call("GET", f"/policies/{policy_id}")[1]["Policy"]["State"] == "DISABLED")

    bad_status, bad_body = call("POST", "/policies", {"State": "ENABLED", "PolicyDetails": {
        "ResourceTypes": ["VOLUME"], "TargetTags": [{"Key": "x", "Value": "y"}],
        "Schedules": [{"Name": "bad", "CreateRule": {}, "RetainRule": {"Count": 1}}]}})
    _check("a schedule with no real Interval is rejected", bad_status == 400)

    status, _ = call("DELETE", f"/policies/{policy_id}")
    _check("DeleteLifecyclePolicy succeeds", status == 200)
    _check("deleted policy is gone", call("GET", f"/policies/{policy_id}")[0] == 404)

    print("RESULT: PASS — DLM core (real scheduled snapshot policies) conforms.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
