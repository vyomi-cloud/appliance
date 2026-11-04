"""GCS Storage-Intelligence sub-resources (v4 DEPTH pass): batchOperations jobs and
insightsDatasets configs, modeled on /storage/v1 since no google-cloud-storage client
calls them directly (the real products live on separate services — see the module
docstrings on _run_batch_job / _insights_datasets in core/gcp_storage_core.py).

  - a batch job with action Delete really deletes every matching object under
    bucket+prefix, synchronously, and reports counts
  - a batch job with action SetStorageClass really rewrites storageClass
  - a batch job honors retention/holds the same as a direct delete (failed count)
  - insightsDatasets create/list/get/delete round-trip (config_only: no export runs)

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_storage_intelligence_core.py
"""
import json

try:
    from core.object_store import InMemoryObjectStore
    from core import gcp_storage_core as gcs
except ImportError:  # pragma: no cover - Pyodide flat layout
    from object_store import InMemoryObjectStore  # type: ignore
    import gcp_storage_core as gcs  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _j(r):
    return json.loads(r.body.decode("utf-8")) if r.body else {}


def _call(st, m, p, q=None, body=None, ct="application/json"):
    raw = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else b"")
    return gcs.dispatch(st, m, p, q or {}, {"content-type": ct}, raw)


def _upload(st, bucket, name, data=b"x"):
    return _call(st, "POST", f"/upload/storage/v1/b/{bucket}/o", {"uploadType": "media", "name": name}, data, "text/plain")


def run() -> int:
    st = InMemoryObjectStore()
    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "bo"})
    for n in ("logs/a.log", "logs/b.log", "data.csv"):
        _upload(st, "bo", n)

    # 1. batch Delete job really deletes matching objects
    j = _j(_call(st, "POST", "/storage/v1/batchOperations", body={"bucket": "bo", "prefix": "logs/", "action": {"type": "Delete"}}))
    _check("job reports state SUCCEEDED", j["state"] == "SUCCEEDED")
    _check("job matched+deleted the 2 logs/ objects", j["counts"] == {"matched": 2, "succeeded": 2, "failed": 0})
    remaining = sorted(i["name"] for i in _j(_call(st, "GET", "/storage/v1/b/bo/o")).get("items", []))
    _check("objects really gone from the bucket", remaining == ["data.csv"])

    # 2. batch SetStorageClass job really rewrites storageClass
    j2 = _j(_call(st, "POST", "/storage/v1/batchOperations", body={"bucket": "bo", "prefix": "data", "action": {"type": "SetStorageClass", "storageClass": "ARCHIVE"}}))
    _check("SetStorageClass job succeeds", j2["counts"]["succeeded"] == 1)
    _check("object storageClass really changed", _j(_call(st, "GET", "/storage/v1/b/bo/o/data.csv"))["storageClass"] == "ARCHIVE")

    # 3. a held object fails rather than silently succeeding
    _upload(st, "bo", "held.txt")
    _call(st, "PATCH", "/storage/v1/b/bo/o/held.txt", body={"temporaryHold": True})
    j3 = _j(_call(st, "POST", "/storage/v1/batchOperations", body={"bucket": "bo", "prefix": "held", "action": {"type": "Delete"}}))
    _check("held object counted as failed, not deleted", j3["counts"] == {"matched": 1, "succeeded": 0, "failed": 1})
    _check("held object still present", _call(st, "GET", "/storage/v1/b/bo/o/held.txt").status == 200)

    # 4. job list/get/delete
    jobs = _j(_call(st, "GET", "/storage/v1/batchOperations"))
    _check("job list has all 3 jobs", len(jobs["jobs"]) == 3)
    job_id = jobs["jobs"][0]["name"].split("/")[-1]
    _check("job get 200", _call(st, "GET", f"/storage/v1/batchOperations/{job_id}").status == 200)
    _check("job delete 204", _call(st, "DELETE", f"/storage/v1/batchOperations/{job_id}").status == 204)
    _check("job gone after delete", _call(st, "GET", f"/storage/v1/batchOperations/{job_id}").status == 404)
    _check("unknown bucket -> 404", _call(st, "POST", "/storage/v1/batchOperations", body={"bucket": "nope", "action": {"type": "Delete"}}).status == 404)

    # 5. insightsDatasets config CRUD (config_only)
    d = _j(_call(st, "POST", "/storage/v1/insightsDatasets", body={"displayName": "My inventory", "sourceBucketPrefix": "bo"}))
    _check("dataset config created", d["displayName"] == "My inventory" and d["state"] == "ACTIVE")
    ds_id = d["name"].split("/")[-1]
    lst = _j(_call(st, "GET", "/storage/v1/insightsDatasets"))
    _check("dataset listed", any(x["name"] == d["name"] for x in lst["datasets"]))
    _check("dataset get 200", _call(st, "GET", f"/storage/v1/insightsDatasets/{ds_id}").status == 200)
    _check("dataset delete 204", _call(st, "DELETE", f"/storage/v1/insightsDatasets/{ds_id}").status == 204)
    _check("dataset gone after delete", _call(st, "GET", f"/storage/v1/insightsDatasets/{ds_id}").status == 404)
    _check("missing displayName rejected", _call(st, "POST", "/storage/v1/insightsDatasets", body={}).status == 400)

    print("\nGCS Storage Intelligence (batch operations / insights datasets) conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
