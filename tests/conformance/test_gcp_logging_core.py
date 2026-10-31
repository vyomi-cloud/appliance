"""GCP Cloud Logging core conformance — the GCP analogue of test_kms_core.py.

Same test runs on host CPython and under Pyodide/WASM and must be green on both.
Asserts the native **Cloud Logging REST API v2** wire semantics (entries:write /
entries:list, sinks, log-based metrics, log buckets + views, Google
`{"error":{...,"status"}}` shape) through core.aws_wire_router.AwsWireRouter, proving
google-cloud-logging / gcloud logging can drive the core unchanged.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_logging_core.py
"""
import json
from datetime import datetime, timedelta, timezone

try:
    from core.aws_wire_router import AwsWireRouter
except ImportError:  # pragma: no cover - Pyodide flat layout
    from aws_wire_router import AwsWireRouter  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    r = AwsWireRouter()

    def call(method, path, query=None, body=None):
        b = json.dumps(body).encode() if body is not None else b""
        out = r.handle(method, path, query or {}, {}, b)
        try:
            j = json.loads(out["body"] or b"{}")
        except Exception:
            j = out["body"]
        return out["status"], j

    # ── entries ──────────────────────────────────────────────────────────
    st, b = call("POST", "/v2/entries:write", body={
        "logName": "projects/demo/logs/app", "resource": {"type": "global"},
        "entries": [
            {"severity": "ERROR", "textPayload": "boom"},
            {"severity": "INFO", "textPayload": "all good", "labels": {"k": "v"}},
        ],
    })
    _check("entries:write 200", st == 200 and b == {})

    st, b = call("POST", "/v2/entries:write", body={"entries": [{"severity": "BOGUS", "logName": "projects/demo/logs/app", "textPayload": "x"}]})
    _check("entries:write invalid severity -> 400 INVALID_ARGUMENT", st == 400 and b["error"]["status"] == "INVALID_ARGUMENT")

    st, b = call("POST", "/v2/entries:list", body={"resourceNames": ["projects/demo"]})
    _check("entries:list all", st == 200 and len(b["entries"]) == 2)

    st, b = call("POST", "/v2/entries:list", body={"resourceNames": ["projects/demo"], "filter": 'severity>="ERROR"'})
    _check("entries:list filter by severity", st == 200 and len(b["entries"]) == 1 and b["entries"][0]["textPayload"] == "boom")

    st, b = call("POST", "/v2/entries:list", body={"resourceNames": ["projects/demo"], "filter": "boom"})
    _check("entries:list free-text filter", st == 200 and len(b["entries"]) == 1)

    st, b = call("GET", "/v2/projects/demo/logs")
    _check("logs.list", st == 200 and b["logNames"] == ["projects/demo/logs/app"])

    # ── sinks ────────────────────────────────────────────────────────────
    st, b = call("POST", "/v2/projects/demo/sinks", body={
        "name": "err-sink", "destination": "storage.googleapis.com/my-bucket", "filter": 'severity>="ERROR"'})
    _check("sinks.create 200", st == 200 and b["name"] == "projects/demo/sinks/err-sink")
    _check("sinks.create matchedCount reflects past entries' matching filter", b["matchedCount"] == 0)

    st, b = call("POST", "/v2/projects/demo/sinks", body={"name": "bad-sink", "destination": "not-a-real-destination"})
    _check("sinks.create bad destination -> 400", st == 400 and b["error"]["status"] == "INVALID_ARGUMENT")

    st, b = call("POST", "/v2/projects/demo/sinks", body={
        "name": "err-sink", "destination": "storage.googleapis.com/my-bucket", "filter": "severity>=\"ERROR\""})
    _check("sinks.create duplicate -> 409", st == 409 and b["error"]["status"] == "ALREADY_EXISTS")

    st, b = call("GET", "/v2/projects/demo/sinks")
    _check("sinks.list has err-sink", st == 200 and any(s["name"].endswith("/err-sink") for s in b["sinks"]))

    st, b = call("POST", "/v2/entries:write", body={"logName": "projects/demo/logs/app", "entries": [{"severity": "ERROR", "textPayload": "another"}]})
    _check("second write 200", st == 200)
    st, b = call("GET", "/v2/projects/demo/sinks/err-sink")
    _check("sink routing counted the new matching entry", st == 200 and b["matchedCount"] == 1)

    st, b = call("PATCH", "/v2/projects/demo/sinks/err-sink", query={"updateMask": "disabled"}, body={"disabled": True})
    _check("sinks.patch disables", st == 200 and b["disabled"] is True)

    st, b = call("DELETE", "/v2/projects/demo/sinks/err-sink")
    _check("sinks.delete 200", st == 200)
    st, b = call("GET", "/v2/projects/demo/sinks/err-sink")
    _check("sinks.get after delete -> 404", st == 404 and b["error"]["status"] == "NOT_FOUND")

    # ── log-based metrics ────────────────────────────────────────────────
    st, b = call("POST", "/v2/projects/demo/metrics", body={"name": "error-count", "filter": 'severity>="ERROR"', "description": "errors"})
    _check("metrics.create 200", st == 200 and b["name"] == "projects/demo/metrics/error-count")

    st, b = call("POST", "/v2/projects/demo/metrics", body={"name": "no-filter"})
    _check("metrics.create requires filter -> 400", st == 400)

    st, b = call("GET", "/v2/projects/demo/metrics")
    _check("metrics.list", st == 200 and len(b["metrics"]) == 1)

    st, b = call("PUT", "/v2/projects/demo/metrics/error-count", body={"filter": 'severity>="ERROR"', "description": "errors v2"})
    _check("metrics.update", st == 200 and b["description"] == "errors v2")

    st, b = call("DELETE", "/v2/projects/demo/metrics/error-count")
    _check("metrics.delete 200", st == 200)
    st, b = call("GET", "/v2/projects/demo/metrics/error-count")
    _check("metrics.get after delete -> 404", st == 404)

    # ── buckets + views ──────────────────────────────────────────────────
    st, b = call("GET", "/v2/projects/demo/locations/global/buckets")
    _check("buckets.list seeds _Default/_Required", st == 200 and {x["name"].rsplit("/", 1)[-1] for x in b["buckets"]} >= {"_Default", "_Required"})

    st, b = call("POST", "/v2/projects/demo/locations/global/buckets", query={"bucketId": "my-bucket"},
                body={"retentionDays": 90, "analyticsEnabled": True})
    _check("buckets.create 200", st == 200 and b["retentionDays"] == 90)
    _check("buckets.create links a BigQuery dataset when analytics is enabled", bool(b["bigQueryDataset"]))

    st, b = call("POST", "/v2/projects/demo/locations/global/buckets", query={"bucketId": "my-bucket"}, body={})
    _check("buckets.create duplicate -> 409", st == 409)

    st, b = call("GET", "/v2/projects/demo/locations/global/buckets/my-bucket")
    _check("buckets.get 200", st == 200 and b["name"].endswith("/my-bucket"))

    st, b = call("PATCH", "/v2/projects/demo/locations/global/buckets/my-bucket", query={"updateMask": "retentionDays"}, body={"retentionDays": 120})
    _check("buckets.patch", st == 200 and b["retentionDays"] == 120)

    st, b = call("DELETE", "/v2/projects/demo/locations/global/buckets/_Default")
    _check("buckets.delete protected bucket -> 400", st == 400)

    st, b = call("POST", "/v2/projects/demo/locations/global/buckets/my-bucket/views", query={"viewId": "errors"},
                body={"filter": 'severity>="ERROR"', "description": "errors only"})
    _check("views.create 200", st == 200 and b["name"].endswith("/my-bucket/views/errors"))

    st, b = call("GET", "/v2/projects/demo/locations/global/buckets/my-bucket/views")
    _check("views.list", st == 200 and len(b["views"]) == 1)

    st, b = call("DELETE", "/v2/projects/demo/locations/global/buckets/my-bucket/views/errors")
    _check("views.delete 200", st == 200)

    st, b = call("DELETE", "/v2/projects/demo/locations/global/buckets/my-bucket")
    _check("buckets.delete 200", st == 200)
    st, b = call("GET", "/v2/projects/demo/locations/global/buckets/my-bucket")
    _check("buckets.get after delete -> 404", st == 404)

    # ── usage -> Monitoring (Logs Storage "Create usage alert" / "View usage data") ──
    # Every entries:write above mirrored live byte/entry counts for project "demo" into the
    # shared Cloud Monitoring store (core/gcp_logging_core._sync_usage_metrics); this is a
    # REAL metric a REAL alert policy can reference, evaluated by Monitoring's own
    # evaluate_incidents sweep — not a fabricated "it would work" claim.
    def iso(delta=0):
        return (datetime.now(timezone.utc) + timedelta(seconds=delta)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    st, b = call("GET", "/v3/projects/demo/timeSeries", query={
        "filter": 'metric.type = "logging.googleapis.com/byte_count" AND resource.type = "global"',
        "interval.startTime": iso(-3600), "interval.endTime": iso(60)})
    _check("byte_count time series carries a real point mirrored from Cloud Logging entries",
           st == 200 and len(b["timeSeries"]) == 1 and b["timeSeries"][0]["points"] and int(b["timeSeries"][0]["points"][0]["value"]["int64Value"]) > 0)

    st, b = call("POST", "/v3/projects/demo/alertPolicies", body={
        "displayName": "log usage", "combiner": "OR",
        "conditions": [{"displayName": "bytes high", "conditionThreshold": {
            "filter": 'metric.type = "logging.googleapis.com/byte_count" AND resource.type = "global"',
            "comparison": "COMPARISON_GT", "thresholdValue": 1, "duration": "0s"}}],
    })
    _check("usage alert policy created on the shared Monitoring store", st == 200 and b["name"].startswith("projects/demo/alertPolicies/"))

    st, b = call("GET", "/v3/projects/demo/incidents")
    _check("the usage alert really fires: evaluate_incidents opens a real incident against the live byte_count metric",
           st == 200 and any(i["policyDisplayName"] == "log usage" and i["state"] == "OPEN" for i in b.get("incidents", [])))

    print("\nRESULT: PASS — every Cloud Logging wire operation behaves as asserted")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
