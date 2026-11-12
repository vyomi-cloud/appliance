"""GCS hierarchical namespace (HNS) Folders (v4 gap-sweep wave 5b): a bucket created with
hierarchicalNamespace.enabled=true (requires uniform bucket-level access, same as the
real API) gets a REAL Folders sub-resource — create/get/list/delete, and an atomic
rename that moves every object and subfolder beneath the source folder in ONE operation,
unlike the flat-namespace console's copy-then-delete-each-object dance. See
core/capabilities/gcp/storage.json: hierarchical-namespace = limited.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_storage_hns_core.py
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


def run() -> int:
    st = InMemoryObjectStore()

    bad = _call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "hnsbad", "hierarchicalNamespace": {"enabled": True}})
    _check("HNS without uniform bucket-level access is rejected", bad.status == 400)

    b = _j(_call(st, "POST", "/storage/v1/b", {"project": "p"}, {
        "name": "hns1", "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True}},
        "hierarchicalNamespace": {"enabled": True}}))
    _check("HNS bucket created with UBLA", b["hierarchicalNamespace"]["enabled"] is True)

    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "plain"})
    plain_folders = _call(st, "POST", "/storage/v1/b/plain/folders", body={"name": "a/"})
    _check("folders API rejected on a non-HNS bucket", plain_folders.status == 400)

    f1 = _j(_call(st, "POST", "/storage/v1/b/hns1/folders", body={"name": "a/"}))
    _check("create top-level folder", f1["name"] == "a/")
    f2 = _j(_call(st, "POST", "/storage/v1/b/hns1/folders", body={"name": "a/b/"}))
    _check("create nested folder under an existing parent", f2["name"] == "a/b/")
    dupe = _call(st, "POST", "/storage/v1/b/hns1/folders", body={"name": "a/"})
    _check("duplicate folder rejected", dupe.status == 409)
    no_parent = _call(st, "POST", "/storage/v1/b/hns1/folders", body={"name": "x/y/"})
    _check("nested folder without its parent rejected", no_parent.status == 404)
    rec = _j(_call(st, "POST", "/storage/v1/b/hns1/folders", {"recursive": "true"}, {"name": "x/y/"}))
    _check("recursive=true creates missing parents", rec["name"] == "x/y/")

    _call(st, "POST", "/upload/storage/v1/b/hns1/o", {"uploadType": "media", "name": "a/b/keep.txt"}, b"hi", "text/plain")
    lst = _j(_call(st, "GET", "/storage/v1/b/hns1/folders"))
    names = sorted(i["name"] for i in lst.get("items", []))
    _check("list shows every folder", names == ["a/", "a/b/", "x/", "x/y/"])

    ren = _j(_call(st, "POST", "/storage/v1/b/hns1/folders/a%2F:renameTo", body={"destinationFolderId": "z/"}))
    _check("rename returns the destination folder", ren["name"] == "z/")
    after = _j(_call(st, "GET", "/storage/v1/b/hns1/folders"))
    after_names = sorted(i["name"] for i in after.get("items", []))
    _check("rename moves the subfolder too (atomic)", "z/" in after_names and "z/b/" in after_names and "a/" not in after_names)
    objs = _j(_call(st, "GET", "/storage/v1/b/hns1/o"))
    obj_names = [i["name"] for i in objs.get("items", [])]
    _check("rename moves every object under the folder in the SAME operation", obj_names == ["z/b/keep.txt"])

    non_empty_del = _call(st, "DELETE", "/storage/v1/b/hns1/folders/z%2F")
    _check("deleting a non-empty folder is rejected", non_empty_del.status == 409)
    empty_del = _call(st, "DELETE", "/storage/v1/b/hns1/folders/x%2Fy%2F")
    _check("deleting an empty folder succeeds", empty_del.status == 204)
    gone = _call(st, "GET", "/storage/v1/b/hns1/folders/x%2Fy%2F")
    _check("deleted folder is gone", gone.status == 404)

    immutable = _call(st, "PATCH", "/storage/v1/b/hns1", body={"hierarchicalNamespace": {"enabled": False}})
    _check("hierarchicalNamespace is immutable after creation", immutable.status == 400)

    print("\nGCS hierarchical namespace (Folders) conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
