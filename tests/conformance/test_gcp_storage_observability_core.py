"""GCS request-count metering (v4 gap-sweep wave 5b): every real request against a
bucket records a REAL point on storage.googleapis.com/api/request_count (Cloud
Monitoring's own pre-existing builtin metric, resource type gcs_bucket) — derived from
actual API activity in the core, never synthetic/random data. See
core/capabilities/gcp/storage.json: observability = limited.

Must run through AwsWireRouter (not a bare gcp_storage_core.dispatch call against an
InMemoryObjectStore) — the router is what links store.mon_store to the shared Cloud
Monitoring store, the same way it already does for Cloud Logging's usage-alert counters.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_storage_observability_core.py
"""
import datetime
import json

try:
    from core.aws_wire_router import AwsWireRouter
except ImportError:  # pragma: no cover - Pyodide flat layout
    from aws_wire_router import AwsWireRouter  # type: ignore

AUTH = {"authorization": "AWS4-HMAC-SHA256 Credential=CAP/20261101/us-east-1/s3/aws4_request"}


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _call(router, m, p, q=None, body=None, ct="application/json"):
    raw = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else b"")
    out = router.handle(m, p, q or {}, {"content-type": ct, **AUTH}, raw)
    b = out.get("body") or b""
    return int(out.get("status", 200)), (json.loads(b) if b else {})


def run() -> int:
    router = AwsWireRouter()
    s, _ = _call(router, "POST", "/storage/v1/b", {"project": "obs-proj"}, {"name": "obs-bkt"})
    _check("bucket created", s == 200)

    for _ in range(5):
        _call(router, "GET", "/storage/v1/b/obs-bkt/o")

    now = datetime.datetime.now(datetime.timezone.utc)
    start = (now - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end = (now + datetime.timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    s, ts = _call(router, "GET", "/v3/projects/obs-proj/timeSeries", {
        "filter": 'metric.type="storage.googleapis.com/api/request_count" AND resource.label.bucket_name="obs-bkt"',
        "interval.startTime": start, "interval.endTime": end})
    _check("timeSeries.list 200", s == 200)
    series = ts.get("timeSeries") or []
    _check("a real series exists for this bucket", len(series) == 1)
    points = series[0]["points"]
    _check("every one of the 5 real requests got its own point (no silent drops)", len(points) == 5)
    _check("resource carries the real bucket name", series[0]["resource"]["labels"]["bucket_name"] == "obs-bkt")
    _check("points carry a real delta count of 1 each", all(p["value"]["int64Value"] == "1" for p in points))

    s2, _ = _call(router, "POST", "/storage/v1/b", {"project": "obs-proj"}, {"name": "other-bkt"})
    _call(router, "GET", "/storage/v1/b/other-bkt/o")
    s3, ts2 = _call(router, "GET", "/v3/projects/obs-proj/timeSeries", {
        "filter": 'metric.type="storage.googleapis.com/api/request_count" AND resource.label.bucket_name="obs-bkt"',
        "interval.startTime": start, "interval.endTime": end})
    _check("a different bucket's requests don't pollute this bucket's series", len(ts2["timeSeries"][0]["points"]) == 5)

    print("\nGCS observability (request-count metering) conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
