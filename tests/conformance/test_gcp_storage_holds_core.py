"""GCS object holds + per-object retention ENFORCEMENT conformance (v4 DEPTH pass):

  - temporaryHold / eventBasedHold block delete AND overwrite with the native 403
    conditionNotMet, same shape as bucket retentionPolicy's retentionPolicyNotMet
  - clearing a hold (objects.patch with the field set to false) un-blocks it
  - object retention (retention.retainUntilTime) requires objectRetention.mode =
    Enabled on the bucket first (buckets.insert/patch), then blocks delete/overwrite
    until the retain-until time has passed
  - metadata-only objects.patch is NOT blocked by a hold (only delete/overwrite are) —
    matches real GCS, where you can still read/patch metadata under a hold

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_storage_holds_core.py
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
    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "hold"})

    # 1. temporaryHold blocks delete and overwrite
    _upload(st, "hold", "a.txt")
    _call(st, "PATCH", "/storage/v1/b/hold/o/a.txt", body={"temporaryHold": True})
    d = _call(st, "DELETE", "/storage/v1/b/hold/o/a.txt")
    _check("delete under temporary hold -> 403 conditionNotMet", d.status == 403 and _j(d)["error"]["errors"][0]["reason"] == "conditionNotMet")
    ow = _upload(st, "hold", "a.txt", b"new")
    _check("overwrite under temporary hold -> 403", ow.status == 403)
    _check("metadata patch is NOT blocked by a hold", _call(st, "PATCH", "/storage/v1/b/hold/o/a.txt", body={"contentType": "text/csv"}).status == 200)
    _call(st, "PATCH", "/storage/v1/b/hold/o/a.txt", body={"temporaryHold": False})
    _check("clearing hold -> delete allowed", _call(st, "DELETE", "/storage/v1/b/hold/o/a.txt").status == 204)

    # 2. eventBasedHold blocks delete
    _upload(st, "hold", "b.txt")
    _call(st, "PATCH", "/storage/v1/b/hold/o/b.txt", body={"eventBasedHold": True})
    _check("delete under event-based hold -> 403", _call(st, "DELETE", "/storage/v1/b/hold/o/b.txt").status == 403)
    _call(st, "PATCH", "/storage/v1/b/hold/o/b.txt", body={"eventBasedHold": False})
    _check("clearing event-based hold -> delete allowed", _call(st, "DELETE", "/storage/v1/b/hold/o/b.txt").status == 204)

    # 3. object retention requires bucket objectRetention.mode = Enabled
    _upload(st, "hold", "c.txt")
    rej = _call(st, "PATCH", "/storage/v1/b/hold/o/c.txt", body={"retention": {"mode": "Unlocked", "retainUntilTime": "2099-01-01T00:00:00.000Z"}})
    _check("object retention rejected when bucket hasn't enabled it", rej.status == 400)
    _call(st, "PATCH", "/storage/v1/b/hold", body={"objectRetention": {"mode": "Enabled"}})
    ok = _call(st, "PATCH", "/storage/v1/b/hold/o/c.txt", body={"retention": {"mode": "Unlocked", "retainUntilTime": "2099-01-01T00:00:00.000Z"}})
    _check("object retention accepted once bucket enables it", ok.status == 200 and _j(ok)["retention"]["retainUntilTime"] == "2099-01-01T00:00:00.000Z")
    _check("delete before retainUntilTime -> 403", _call(st, "DELETE", "/storage/v1/b/hold/o/c.txt").status == 403)

    # 4. a retention time in the past does not block
    _upload(st, "hold", "d.txt")
    _call(st, "PATCH", "/storage/v1/b/hold/o/d.txt", body={"retention": {"mode": "Unlocked", "retainUntilTime": "2020-01-01T00:00:00.000Z"}})
    _check("delete after retainUntilTime has passed -> allowed", _call(st, "DELETE", "/storage/v1/b/hold/o/d.txt").status == 204)

    # 5. bucket view reflects objectRetention
    bv = _j(_call(st, "GET", "/storage/v1/b/hold"))
    _check("bucket view reports objectRetention enabled", bv.get("objectRetention", {}).get("mode") == "Enabled")

    print("\nGCS holds + object retention enforcement conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
