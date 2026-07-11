"""GCS storage-core conformance — the GCP analogue of test_s3_core.py.

Same test runs on host CPython and under Pyodide/WASM and must be green on both.
It asserts the native **GCS JSON API** wire semantics (storage#bucket /
storage#object resources, media + multipart uploads, ?alt=media download,
base64 md5Hash + CRC32C integrity fields, 204 deletes, notFound errors),
proving google-cloud-storage / gsutil can drive the core unchanged.

Run on host:    python3 tests/conformance/test_gcp_storage_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import base64
import hashlib

try:
    from core.object_store import InMemoryObjectStore
    from core import gcp_storage_core as gcs
except ImportError:  # pragma: no cover - Pyodide flat layout
    from object_store import InMemoryObjectStore  # type: ignore
    import gcp_storage_core as gcs  # type: ignore

import json


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def run() -> int:
    st = InMemoryObjectStore()

    # 1. insert bucket -> 200 storage#bucket
    r = gcs.dispatch(st, "POST", "/storage/v1/b", {"project": "p"},
                     {"content-type": "application/json"},
                     json.dumps({"name": "demo"}).encode())
    _check("insert bucket 200", r.status == 200)
    _check("insert bucket kind", _jbody(r)["kind"] == "storage#bucket")
    _check("insert bucket name", _jbody(r)["name"] == "demo")

    # 1b. duplicate bucket -> 409
    dup = gcs.dispatch(st, "POST", "/storage/v1/b", {"project": "p"},
                       {"content-type": "application/json"},
                       json.dumps({"name": "demo"}).encode())
    _check("duplicate bucket 409", dup.status == 409)

    # 2. list buckets
    lb = gcs.dispatch(st, "GET", "/storage/v1/b", {"project": "p"}, {}, b"")
    _check("list buckets kind", _jbody(lb)["kind"] == "storage#buckets")
    _check("list buckets has demo", any(b["name"] == "demo" for b in _jbody(lb)["items"]))

    # 3. get bucket
    gb = gcs.dispatch(st, "GET", "/storage/v1/b/demo", {}, {}, b"")
    _check("get bucket 200", gb.status == 200 and _jbody(gb)["name"] == "demo")

    # 4. simple media upload -> correct md5Hash + crc32c + size
    body = b"hello from the GCS core"
    up = gcs.dispatch(st, "POST", "/upload/storage/v1/b/demo/o",
                      {"uploadType": "media", "name": "a/hello.txt"},
                      {"content-type": "text/plain"}, body)
    _check("media upload 200", up.status == 200)
    o = _jbody(up)
    _check("object kind", o["kind"] == "storage#object")
    _check("object name", o["name"] == "a/hello.txt")
    _check("object size", o["size"] == str(len(body)))
    _check("object md5 = base64(md5)", o["md5Hash"] == base64.b64encode(hashlib.md5(body).digest()).decode())
    _check("object contentType", o["contentType"] == "text/plain")
    _check("object generation set", int(o["generation"]) >= 1)

    # 5. multipart/related upload (what google-cloud-storage sends) -> name + metadata from JSON part
    media = b"multipart media payload"
    meta = {"name": "docs/report.txt", "contentType": "text/plain", "metadata": {"author": "vyomi"}}
    boundary = "===============boundary=="
    mp = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(meta)}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/plain\r\n\r\n"
    ).encode() + media + f"\r\n--{boundary}--".encode()
    mpr = gcs.dispatch(st, "POST", "/upload/storage/v1/b/demo/o",
                       {"uploadType": "multipart"},
                       {"content-type": f"multipart/related; boundary={boundary}"}, mp)
    _check("multipart upload 200", mpr.status == 200)
    mo = _jbody(mpr)
    _check("multipart name from JSON part", mo["name"] == "docs/report.txt")
    _check("multipart custom metadata echoed", mo.get("metadata", {}).get("author") == "vyomi")

    # 6. get object metadata
    gm = gcs.dispatch(st, "GET", "/storage/v1/b/demo/o/a%2Fhello.txt", {}, {}, b"")
    _check("get metadata 200", gm.status == 200 and _jbody(gm)["name"] == "a/hello.txt")

    # 7. download ?alt=media -> bytes round-trip + x-goog-hash
    dl = gcs.dispatch(st, "GET", "/storage/v1/b/demo/o/a%2Fhello.txt", {"alt": "media"}, {}, b"")
    _check("download 200", dl.status == 200)
    _check("download body round-trips", dl.body == body)
    _check("download content-type", dl.headers.get("content-type") == "text/plain")
    _check("download x-goog-hash present", "md5=" in dl.headers.get("x-goog-hash", ""))

    # 8. list objects + prefix filter
    lo = gcs.dispatch(st, "GET", "/storage/v1/b/demo/o", {}, {}, b"")
    names = [it["name"] for it in _jbody(lo).get("items", [])]
    _check("list objects has both", "a/hello.txt" in names and "docs/report.txt" in names)
    lp = gcs.dispatch(st, "GET", "/storage/v1/b/demo/o", {"prefix": "docs/"}, {}, b"")
    pnames = [it["name"] for it in _jbody(lp).get("items", [])]
    _check("prefix filter", pnames == ["docs/report.txt"])

    # 9. delete object -> 204, then 404 on re-get
    dele = gcs.dispatch(st, "DELETE", "/storage/v1/b/demo/o/a%2Fhello.txt", {}, {}, b"")
    _check("delete object 204", dele.status == 204)
    miss = gcs.dispatch(st, "GET", "/storage/v1/b/demo/o/a%2Fhello.txt", {}, {}, b"")
    _check("deleted object 404", miss.status == 404 and _jbody(miss)["error"]["errors"][0]["reason"] == "notFound")

    # 10. delete non-empty bucket -> 409; empty it, then 204
    ne = gcs.dispatch(st, "DELETE", "/storage/v1/b/demo", {}, {}, b"")
    _check("delete non-empty bucket 409", ne.status == 409)
    gcs.dispatch(st, "DELETE", "/storage/v1/b/demo/o/docs%2Freport.txt", {}, {}, b"")
    db = gcs.dispatch(st, "DELETE", "/storage/v1/b/demo", {}, {}, b"")
    _check("delete empty bucket 204", db.status == 204)

    # 11. missing bucket -> 404
    mb = gcs.dispatch(st, "GET", "/storage/v1/b/nope", {}, {}, b"")
    _check("missing bucket 404", mb.status == 404)

    print("\nGCS storage-core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
