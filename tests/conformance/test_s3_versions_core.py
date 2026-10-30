"""S3 ListObjectVersions conformance (v4 UI gap-fill) — host + Pyodide.

The object/version data model already keeps every PUT/DELETE as a version
record (see test_s3_core.py #9); this proves `GET /{bucket}?versions` walks
that chain correctly: Version/DeleteMarker entries, IsLatest, prefix filter,
and the native "not implemented" fallback stays gone (the op used to 501).

Run on host:    python3 tests/conformance/test_s3_versions_core.py
Run in Pyodide: loaded by wasm/ harness (same file).
"""
try:
    from core.object_store import InMemoryObjectStore
    from core import s3_object_core as s3
except ImportError:  # pragma: no cover - Pyodide flat layout
    from object_store import InMemoryObjectStore  # type: ignore
    import s3_object_core as s3  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    st = InMemoryObjectStore()
    st.create_bucket("vbkt", versioning="Enabled")

    p1 = s3.dispatch(st, "PUT", "/vbkt/a.txt", body=b"v1")
    p2 = s3.dispatch(st, "PUT", "/vbkt/a.txt", body=b"v2")
    s3.dispatch(st, "PUT", "/vbkt/b.txt", body=b"other")
    vid1, vid2 = p1.headers["x-amz-version-id"], p2.headers["x-amz-version-id"]

    lv = s3.dispatch(st, "GET", "/vbkt", {"versions": ""})
    xml = lv.body.decode()
    _check("list-versions 200", lv.status == 200)
    _check("list-versions is xml", "<ListVersionsResult" in xml and "</ListVersionsResult>" in xml)
    _check("both a.txt versions present", xml.count(f"<Key>a.txt</Key>") == 2)
    _check("newest version marked latest", f"<VersionId>{vid2}</VersionId><IsLatest>true</IsLatest>" in xml)
    _check("older version not latest", f"<VersionId>{vid1}</VersionId><IsLatest>false</IsLatest>" in xml)
    _check("other key present too", "<Key>b.txt</Key>" in xml)

    # Prefix filters to one key.
    lp = s3.dispatch(st, "GET", "/vbkt", {"versions": "", "prefix": "a."}).body.decode()
    _check("prefix filters out b.txt", "<Key>b.txt</Key>" not in lp and "<Key>a.txt</Key>" in lp)

    # Deleting (versioned) inserts a delete marker that shows up too.
    s3.dispatch(st, "DELETE", "/vbkt/a.txt")
    ld = s3.dispatch(st, "GET", "/vbkt", {"versions": ""}).body.decode()
    _check("delete marker listed", "<DeleteMarker>" in ld and ld.count("<Key>a.txt</Key>") == 3)

    # Unversioned bucket: still works (single current version per key, no 501).
    st.create_bucket("plain")
    s3.dispatch(st, "PUT", "/plain/x.txt", body=b"x")
    lu = s3.dispatch(st, "GET", "/plain", {"versions": ""})
    _check("unversioned bucket list-versions 200 (not 501)", lu.status == 200)
    _check("unversioned bucket shows the key", "<Key>x.txt</Key>" in lu.body.decode())

    print("\nRESULT: PASS — S3 ListObjectVersions conforms (native wire semantics) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
