"""GCS object versioning + soft delete (v4 gap-sweep wave 5b): a bucket with
versioning.enabled or a softDeletePolicy keeps a REAL noncurrent-version archive —
overwrites and deletes snapshot the prior generation instead of discarding it, so it
stays listable (?versions=true), fetchable by generation, and (soft delete) restorable
within its retention window. A bucket with neither flag behaves exactly as before (hard
delete, single generation) — see core/capabilities/gcp/storage.json: versioning /
soft-delete = limited.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_storage_versioning_core.py
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


def _upload(st, bucket, name, data, ct="text/plain"):
    return gcs.dispatch(st, "POST", f"/upload/storage/v1/b/{bucket}/o", {"uploadType": "media", "name": name},
                        {"content-type": ct}, data)


def run() -> int:
    st = InMemoryObjectStore()

    # ── versioning: overwrite keeps the old generation around ──────────────────────────
    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "v1", "versioning": {"enabled": True}})
    v1 = _j(_upload(st, "v1", "o.txt", b"one"))
    _check("first generation created", v1["generation"] == "1")
    v2 = _j(_upload(st, "v1", "o.txt", b"two"))
    _check("overwrite bumps generation", v2["generation"] == "2")
    cur = _j(_call(st, "GET", "/storage/v1/b/v1/o/o.txt"))
    _check("current generation serves latest bytes", cur["generation"] == "2")
    old = _j(_call(st, "GET", "/storage/v1/b/v1/o/o.txt", {"generation": "1"}))
    _check("old generation still fetchable by number", old["generation"] == "1")
    old_media = gcs.dispatch(st, "GET", "/storage/v1/b/v1/o/o.txt", {"generation": "1", "alt": "media"}, {}, b"")
    _check("old generation bytes are the ORIGINAL write", old_media.body == b"one")
    missing_gen = gcs.dispatch(st, "GET", "/storage/v1/b/v1/o/o.txt", {"generation": "99"}, {}, b"")
    _check("unknown generation 404s", missing_gen.status == 404)

    lst = _j(_call(st, "GET", "/storage/v1/b/v1/o", {"versions": "true"}))
    gens = sorted(int(i["generation"]) for i in lst.get("items", []) if i["name"] == "o.txt")
    _check("versions=true lists both generations", gens == [1, 2])
    plain = _j(_call(st, "GET", "/storage/v1/b/v1/o"))
    _check("plain list shows only the current generation", [i["generation"] for i in plain["items"]] == ["2"])

    # delete on a versioned bucket archives (noncurrent), it does not hard-delete
    _call(st, "DELETE", "/storage/v1/b/v1/o/o.txt")
    gone = _call(st, "GET", "/storage/v1/b/v1/o/o.txt")
    _check("deleted object is gone from the live namespace", gone.status == 404)
    after_del = _j(_call(st, "GET", "/storage/v1/b/v1/o", {"versions": "true"}))
    gens2 = sorted(int(i["generation"]) for i in after_del.get("items", []) if i["name"] == "o.txt")
    _check("delete on a versioned bucket preserves history (generation 2 becomes noncurrent, not a new one)", gens2 == [1, 2])
    deleted_gen = next(i for i in after_del["items"] if i["name"] == "o.txt" and i["generation"] == "2")
    _check("the removed generation carries timeDeleted", "timeDeleted" in deleted_gen)

    # generation-specific delete permanently removes exactly that version
    _call(st, "DELETE", "/storage/v1/b/v1/o/o.txt", {"generation": "1"})
    after_purge = _j(_call(st, "GET", "/storage/v1/b/v1/o", {"versions": "true"}))
    gens3 = sorted(int(i["generation"]) for i in after_purge.get("items", []) if i["name"] == "o.txt")
    _check("generation-targeted delete permanently removes just that version", gens3 == [2])

    # ── soft delete: independent of versioning, restorable within the retention window ─
    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {
        "name": "sd1", "softDeletePolicy": {"retentionDurationSeconds": "604800"}})
    _upload(st, "sd1", "keep.txt", b"hello")
    before = _j(_call(st, "GET", "/storage/v1/b/sd1/o/keep.txt"))
    _call(st, "DELETE", "/storage/v1/b/sd1/o/keep.txt")
    soft = _j(_call(st, "GET", "/storage/v1/b/sd1/o", {"softDeleted": "true"}))
    _check("soft-deleted listing shows the removed object", len(soft.get("items", [])) == 1)
    restore = _j(_call(st, "POST", f"/storage/v1/b/sd1/o/keep.txt/restore", {"generation": before["generation"]}))
    _check("restore brings the object back as a NEW current generation", restore["generation"] != before["generation"])
    back = gcs.dispatch(st, "GET", "/storage/v1/b/sd1/o/keep.txt", {"alt": "media"}, {}, b"")
    _check("restored object bytes match the original", back.body == b"hello")
    missing_restore = _call(st, "POST", "/storage/v1/b/sd1/o/keep.txt/restore", {"generation": "999999"})
    _check("restoring an unknown generation 404s", missing_restore.status == 404)

    # ── soft delete retention sweep: an expired soft-deleted version is purged for real ─
    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {
        "name": "sd2", "softDeletePolicy": {"retentionDurationSeconds": "1"}})
    _upload(st, "sd2", "temp.txt", b"bye")
    _call(st, "DELETE", "/storage/v1/b/sd2/o/temp.txt")
    import time
    time.sleep(1.2)
    swept = _j(_call(st, "GET", "/storage/v1/b/sd2/o", {"softDeleted": "true"}))
    _check("expired soft-deleted version is swept for real", swept.get("items", []) == [])

    # ── a plain bucket (neither flag) is completely unaffected: hard delete as before ──
    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "plain1"})
    _upload(st, "plain1", "a.txt", b"x")
    _call(st, "DELETE", "/storage/v1/b/plain1/o/a.txt")
    plain_versions = _j(_call(st, "GET", "/storage/v1/b/plain1/o", {"versions": "true"}))
    _check("a plain bucket keeps no noncurrent history at all", plain_versions.get("items", []) is None or plain_versions.get("items") in (None, []))

    # ── lifecycle numNewerVersions now evaluates for real against the archive ──────────
    _call(st, "POST", "/storage/v1/b", {"project": "p"}, {
        "name": "lcv", "versioning": {"enabled": True},
        "lifecycle": {"rule": [{"action": {"type": "Delete"}, "condition": {"numNewerVersions": 1}}]}})
    _upload(st, "lcv", "n.txt", b"g1")
    _upload(st, "lcv", "n.txt", b"g2")
    _upload(st, "lcv", "n.txt", b"g3")   # sweeping happens lazily on the next /o request
    lcv_versions = _j(_call(st, "GET", "/storage/v1/b/lcv/o", {"versions": "true"}))
    lcv_gens = sorted(int(i["generation"]) for i in lcv_versions.get("items", []) if i["name"] == "n.txt")
    _check("numNewerVersions=1 lifecycle rule prunes all but the newest noncurrent version", lcv_gens == [3])

    print("\nGCS versioning + soft delete conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
