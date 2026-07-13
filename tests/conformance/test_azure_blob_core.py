"""Azure Blob Storage object-CRUD conformance — the Azure analogue of
test_gcp_storage_core.py.

Same test runs on host CPython and under Pyodide/WASM and must be green on both.
It asserts native **Azure Blob REST API** wire semantics (restype=container /
comp=list, x-ms-blob-type block blobs, ETag + Content-MD5, XML
EnumerationResults, 201/202 status codes, x-ms-error-code + <Error><Code>
errors), proving azure-storage-blob / az storage blob can drive the core
unchanged.

Run on host:    python3 tests/conformance/test_azure_blob_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import base64
import hashlib

try:
    from core import azure_blob_core as az
except ImportError:  # pragma: no cover - Pyodide flat layout
    import azure_blob_core as az  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _text(r):
    return r.body.decode("utf-8")


def run() -> int:
    st = az.AzureBlobStore()

    # 1. create container -> 201
    r = az.dispatch(st, "PUT", "/photos", {"restype": "container"}, {}, b"")
    _check("create container 201", r.status == 201)
    _check("create container etag header", "etag" in r.headers)
    _check("create container x-ms-version", r.headers.get("x-ms-version"))

    # 1b. duplicate container -> 409 ContainerAlreadyExists
    dup = az.dispatch(st, "PUT", "/photos", {"restype": "container"}, {}, b"")
    _check("duplicate container 409", dup.status == 409)
    _check("duplicate x-ms-error-code", dup.headers.get("x-ms-error-code") == "ContainerAlreadyExists")
    _check("duplicate error xml", "<Code>ContainerAlreadyExists</Code>" in _text(dup))

    # 2. put block blob -> 201 + ETag + Last-Modified + Content-MD5
    body = b"hello from the Azure Blob core"
    up = az.dispatch(st, "PUT", "/photos/a/hello.txt", {},
                     {"x-ms-blob-type": "BlockBlob", "content-type": "text/plain"}, body)
    _check("put blob 201", up.status == 201)
    _check("put blob ETag", up.headers.get("etag", "").startswith('"'))
    _check("put blob Last-Modified", "last-modified" in up.headers)
    _check("put blob Content-MD5", up.headers.get("content-md5") ==
           base64.b64encode(hashlib.md5(body).digest()).decode())

    # 2b. put blob to missing container -> 404 ContainerNotFound
    miss_c = az.dispatch(st, "PUT", "/nope/x.txt", {},
                         {"x-ms-blob-type": "BlockBlob"}, b"x")
    _check("put blob missing container 404", miss_c.status == 404 and
           miss_c.headers.get("x-ms-error-code") == "ContainerNotFound")

    # 3. get blob -> 200 bytes round-trip + Content-Type + x-ms-blob-type + Content-Length
    g = az.dispatch(st, "GET", "/photos/a/hello.txt", {}, {}, b"")
    _check("get blob 200", g.status == 200)
    _check("get blob body round-trips", g.body == body)
    _check("get blob content-type", g.headers.get("content-type") == "text/plain")
    _check("get blob x-ms-blob-type", g.headers.get("x-ms-blob-type") == "BlockBlob")
    _check("get blob content-length", g.headers.get("content-length") == str(len(body)))

    # 4. HEAD blob props -> 200, no body
    h = az.dispatch(st, "HEAD", "/photos/a/hello.txt", {}, {}, b"")
    _check("head blob 200", h.status == 200)
    _check("head blob no body", h.body == b"")
    _check("head blob content-length", h.headers.get("content-length") == str(len(body)))
    _check("head blob etag", "etag" in h.headers)

    # 5. list blobs -> XML with the name
    lb = az.dispatch(st, "GET", "/photos", {"restype": "container", "comp": "list"}, {}, b"")
    _check("list blobs 200", lb.status == 200)
    _check("list blobs EnumerationResults", "<EnumerationResults" in _text(lb))
    _check("list blobs has Name", "<Name>a/hello.txt</Name>" in _text(lb))
    _check("list blobs Blob element", "<Blob>" in _text(lb))

    # 5b. list blobs prefix filter
    az.dispatch(st, "PUT", "/photos/docs/report.txt", {},
                {"x-ms-blob-type": "BlockBlob"}, b"report")
    lp = az.dispatch(st, "GET", "/photos",
                     {"restype": "container", "comp": "list", "prefix": "docs/"}, {}, b"")
    _check("list blobs prefix filter", "<Name>docs/report.txt</Name>" in _text(lp)
           and "<Name>a/hello.txt</Name>" not in _text(lp))

    # 6. delete blob -> 202, then get -> 404 BlobNotFound
    d = az.dispatch(st, "DELETE", "/photos/a/hello.txt", {}, {}, b"")
    _check("delete blob 202", d.status == 202)
    miss = az.dispatch(st, "GET", "/photos/a/hello.txt", {}, {}, b"")
    _check("deleted blob 404", miss.status == 404)
    _check("deleted blob BlobNotFound", miss.headers.get("x-ms-error-code") == "BlobNotFound")
    _check("deleted blob error xml", "<Code>BlobNotFound</Code>" in _text(miss))

    # 7. Azurite-style /{account} prefix tolerated
    acc = az.dispatch(st, "GET", "/devstoreaccount1/photos/docs/report.txt", {}, {}, b"")
    _check("account-prefixed get 200", acc.status == 200 and acc.body == b"report")

    # 8. list containers -> XML with the name
    az.dispatch(st, "PUT", "/thumbnails", {"restype": "container"}, {}, b"")
    lc = az.dispatch(st, "GET", "/", {"comp": "list"}, {}, b"")
    _check("list containers 200", lc.status == 200)
    _check("list containers Containers", "<Containers>" in _text(lc))
    _check("list containers has photos", "<Name>photos</Name>" in _text(lc))
    _check("list containers has thumbnails", "<Name>thumbnails</Name>" in _text(lc))

    # 9. delete container -> 202, then list blobs -> 404 ContainerNotFound
    dc = az.dispatch(st, "DELETE", "/photos", {"restype": "container"}, {}, b"")
    _check("delete container 202", dc.status == 202)
    gone = az.dispatch(st, "GET", "/photos", {"restype": "container", "comp": "list"}, {}, b"")
    _check("deleted container 404", gone.status == 404 and
           gone.headers.get("x-ms-error-code") == "ContainerNotFound")

    print("\nAzure Blob storage-core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
