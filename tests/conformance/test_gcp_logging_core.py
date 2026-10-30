"""GCP Cloud Logging core conformance — the GCP analogue of test_kms_core.py.

Same test runs on host CPython and under Pyodide/WASM and must be green on both.
Asserts the native **Cloud Logging REST API v2** wire semantics (entries:write /
entries:list, sinks, log-based metrics, log buckets + views, Google
`{"error":{...,"status"}}` shape) through core.aws_wire_router.AwsWireRouter, proving
google-cloud-logging / gcloud logging can drive the core unchanged.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_logging_core.py
"""
import json

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

    print("\nRESULT: PASS — every Cloud Logging wire operation behaves as asserted")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
