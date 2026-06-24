"""S3 object-core conformance — the acceptance gate for the WASM extraction.

This SAME test runs on two substrates and must be green on both:
  - host CPython (proxy for the Pro/Max appliance handler)
  - Pyodide / WASM (the Nano substrate)

It asserts the NATIVE AWS S3 wire semantics (quoted-MD5 ETag, x-amz-version-id,
NoSuchKey/NoSuchBucket XML, 204 deletes, byte-range 206, ListBucketResult,
versioning + delete markers) — proving the extracted core conforms regardless
of substrate. No network, no fastapi: pure functions over the ObjectStore seam.

Run on host:    python3 tests/conformance/test_s3_core.py
Run in Pyodide: loaded by wasm/ harness (same file).
"""
import hashlib

# Allow running both as a repo script (host) and from a flat FS (Pyodide).
try:
    from core.object_store import InMemoryObjectStore
    from core import s3_object_core as s3
except ImportError:  # pragma: no cover - Pyodide flat layout
    from object_store import InMemoryObjectStore  # type: ignore
    import s3_object_core as s3  # type: ignore


def _md5q(b: bytes) -> str:
    return f'"{hashlib.md5(b).hexdigest()}"'


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    st = InMemoryObjectStore()
    st.create_bucket("demo")

    # 1. PutObject -> 200 + quoted-MD5 ETag
    body = b"hello from the extracted S3 core"
    r = s3.put_object(st, "demo", "a/hello.txt", body,
                      {"content-type": "text/plain", "x-amz-meta-author": "vyomi"})
    _check("put 200", r.status == 200)
    _check("put etag = quoted md5", r.headers["ETag"] == _md5q(body))

    # 2. GetObject -> body + headers conform
    g = s3.get_object(st, "demo", "a/hello.txt", {}, {})
    _check("get 200", g.status == 200)
    _check("get body round-trips", g.body == body)
    _check("get etag matches", g.headers["ETag"] == _md5q(body))
    _check("get content-type", g.headers["Content-Type"] == "text/plain")
    _check("get user metadata echoed", g.headers.get("x-amz-meta-author") == "vyomi")

    # 3. HeadObject -> size + etag, no body
    h = s3.head_object(st, "demo", "a/hello.txt", {}, {})
    _check("head 200", h.status == 200)
    _check("head content-length", h.headers["Content-Length"] == str(len(body)))
    _check("head no body", h.body == b"")

    # 4. Range GET -> 206 + Content-Range
    rg = s3.get_object(st, "demo", "a/hello.txt", {}, {"range": "bytes=0-4"})
    _check("range 206", rg.status == 206)
    _check("range body slice", rg.body == body[:5])
    _check("range content-range", rg.headers["Content-Range"] == f"bytes 0-4/{len(body)}")

    # 5. ListObjectsV2 -> XML ListBucketResult with the key
    s3.put_object(st, "demo", "a/two.txt", b"two", {})
    s3.put_object(st, "demo", "b/three.txt", b"three", {})
    lst = s3.list_objects_v2(st, "demo", {})
    xml = lst.body.decode()
    _check("list is xml", "<ListBucketResult" in xml and "</ListBucketResult>" in xml)
    _check("list has key", "<Key>a/hello.txt</Key>" in xml)
    _check("list keycount 3", "<KeyCount>3</KeyCount>" in xml)

    # 6. List with prefix + delimiter -> CommonPrefixes
    lp = s3.list_objects_v2(st, "demo", {"prefix": "", "delimiter": "/"}).body.decode()
    _check("list delimiter -> common prefixes", "<Prefix>a/</Prefix>" in lp and "<Prefix>b/</Prefix>" in lp)

    # 7. DeleteObject (unversioned) -> 204, then GET -> 404 NoSuchKey
    d = s3.delete_object(st, "demo", "a/hello.txt", {}, {})
    _check("delete 204", d.status == 204)
    g404 = s3.get_object(st, "demo", "a/hello.txt", {}, {})
    _check("get after delete 404", g404.status == 404)
    _check("get after delete NoSuchKey", b"<Code>NoSuchKey</Code>" in g404.body)

    # 8. NoSuchBucket
    nb = s3.get_object(st, "ghost", "x", {}, {})
    _check("missing bucket 404", nb.status == 404)
    _check("missing bucket NoSuchBucket", b"<Code>NoSuchBucket</Code>" in nb.body)

    # 9. Versioning: enable -> two puts keep both versions; delete -> marker
    st.create_bucket("ver", versioning="Enabled")
    p1 = s3.put_object(st, "ver", "k", b"v1", {})
    p2 = s3.put_object(st, "ver", "k", b"v2", {})
    vid1 = p1.headers["x-amz-version-id"]
    vid2 = p2.headers["x-amz-version-id"]
    _check("versioning distinct version ids", vid1 != vid2 and vid1 != "null")
    cur = s3.get_object(st, "ver", "k", {}, {})
    _check("current version is latest put", cur.body == b"v2")
    old = s3.get_object(st, "ver", "k", {"versionId": vid1}, {})
    _check("old version still retrievable", old.body == b"v1")
    dm = s3.delete_object(st, "ver", "k", {}, {})
    _check("versioned delete -> delete marker", dm.headers.get("x-amz-delete-marker") == "true")
    after = s3.get_object(st, "ver", "k", {}, {})
    _check("get after delete-marker 404", after.status == 404)

    print("\nRESULT: PASS — S3 object core conforms (native wire semantics) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
