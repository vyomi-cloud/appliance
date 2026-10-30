"""GCS lifecycle-rule ENFORCEMENT conformance (v4 DEPTH pass): real GCS evaluates a
bucket's lifecycle rules roughly once a day; Vyomi evaluates them lazily on every
request against the bucket's objects (core/gcp_storage_core.py:_apply_lifecycle) —
observably stricter timing, but a rule that matches is always honored, never ignored.

  - Delete action removes a matched object
  - SetStorageClass action changes the object's storageClass in place
  - age / createdBefore / matchesPrefix / matchesSuffix / matchesStorageClass /
    daysSinceCustomTime / customTimeBefore conditions are evaluated against real
    object fields
  - conditions Vyomi cannot evaluate (numNewerVersions, daysSinceNoncurrentTime,
    noncurrentTimeBefore — no version history is kept) never match, so a rule that
    relies solely on them never fires
  - a rule with no matching objects leaves the bucket untouched

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_storage_lifecycle_core.py
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


def _backdate(st, bucket, name, days):
    entry = st.bucket_objects(bucket)[name]
    import datetime
    entry["timeCreated"] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def run() -> int:
    st = InMemoryObjectStore()
    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "lc"})

    # 1. Delete action, age condition
    _upload(st, "lc", "old.txt")
    _upload(st, "lc", "new.txt")
    _backdate(st, "lc", "old.txt", 40)
    _call(st, "PATCH", "/storage/v1/b/lc", body={"lifecycle": {"rule": [
        {"action": {"type": "Delete"}, "condition": {"age": 30}},
    ]}})
    listed = _j(_call(st, "GET", "/storage/v1/b/lc/o"))
    names = sorted(i["name"] for i in listed.get("items", []))
    _check("age-based Delete sweeps the old object on next read", names == ["new.txt"])
    _check("younger object untouched", _call(st, "GET", "/storage/v1/b/lc/o/new.txt").status == 200)
    _check("swept object is really gone (404)", _call(st, "GET", "/storage/v1/b/lc/o/old.txt").status == 404)

    # 2. SetStorageClass action, prefix/suffix condition
    st2 = InMemoryObjectStore()
    _call(st2, "POST", "/storage/v1/b", {"project": "p"}, {"name": "sc", "storageClass": "STANDARD"})
    _upload(st2, "sc", "logs/app.log")
    _upload(st2, "sc", "data.csv")
    _backdate(st2, "sc", "logs/app.log", 10)
    _backdate(st2, "sc", "data.csv", 10)
    _call(st2, "PATCH", "/storage/v1/b/sc", body={"lifecycle": {"rule": [
        {"action": {"type": "SetStorageClass", "storageClass": "NEARLINE"}, "condition": {"age": 7, "matchesPrefix": ["logs/"]}},
    ]}})
    log_obj = _j(_call(st2, "GET", "/storage/v1/b/sc/o/logs%2Fapp.log"))
    csv_obj = _j(_call(st2, "GET", "/storage/v1/b/sc/o/data.csv"))
    _check("prefix-matched object transitions to Nearline", log_obj["storageClass"] == "NEARLINE")
    _check("non-matching object keeps its class", csv_obj["storageClass"] == "STANDARD")

    # 3. createdBefore + matchesSuffix
    st3 = InMemoryObjectStore()
    _call(st3, "POST", "/storage/v1/b", {"project": "p"}, {"name": "cb"})
    _upload(st3, "cb", "a.tmp")
    _upload(st3, "cb", "b.tmp")
    _backdate(st3, "cb", "a.tmp", 100)
    _call(st3, "PATCH", "/storage/v1/b/cb", body={"lifecycle": {"rule": [
        {"action": {"type": "Delete"}, "condition": {"createdBefore": "2020-01-01", "matchesSuffix": [".tmp"]}},
    ]}})
    remaining = sorted(i["name"] for i in _j(_call(st3, "GET", "/storage/v1/b/cb/o")).get("items", []))
    _check("createdBefore uses real timestamps (nothing older than year 2020 here)", remaining == ["a.tmp", "b.tmp"])

    # 4. version-dependent conditions never fire (no version history kept)
    st4 = InMemoryObjectStore()
    _call(st4, "POST", "/storage/v1/b", {"project": "p"}, {"name": "nv"})
    _upload(st4, "nv", "f.txt")
    _backdate(st4, "nv", "f.txt", 40)
    _call(st4, "PATCH", "/storage/v1/b/nv", body={"lifecycle": {"rule": [
        {"action": {"type": "Delete"}, "condition": {"numNewerVersions": 1}},
    ]}})
    _check("a rule that only checks noncurrent-version state never matches (honest: Vyomi keeps no versions)",
           _call(st4, "GET", "/storage/v1/b/nv/o/f.txt").status == 200)

    # 5. empty / no-rule bucket is untouched
    st5 = InMemoryObjectStore()
    _call(st5, "POST", "/storage/v1/b", {"project": "p"}, {"name": "nr"})
    _upload(st5, "nr", "keep.txt")
    _backdate(st5, "nr", "keep.txt", 365)
    _check("no lifecycle rules -> object never swept", _call(st5, "GET", "/storage/v1/b/nr/o/keep.txt").status == 200)

    print("\nGCS lifecycle enforcement conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
