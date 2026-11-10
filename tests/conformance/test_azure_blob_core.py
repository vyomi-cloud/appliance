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
    # 0. blob_content_headers helper unit tests (BL1, R1, R2)
    empty_h = az.blob_content_headers({})
    _check("default octet-stream", empty_h.get("content_type") == "application/octet-stream")
    ct_h = az.blob_content_headers({"content-type": "text/plain"})
    _check("content-type fallback", ct_h.get("content_type") == "text/plain")
    prec_h = az.blob_content_headers({"content-type": "application/octet-stream", "x-ms-blob-content-type": "image/png"})
    _check("x-ms-blob-content-type precedence", prec_h.get("content_type") == "image/png")
    all_props = az.blob_content_headers({
        "x-ms-blob-content-type": "text/markdown; charset=utf-8",
        "x-ms-blob-cache-control": "no-cache",
        "x-ms-blob-content-disposition": "attachment; filename=\"doc.md\"",
        "x-ms-blob-content-encoding": "gzip",
        "x-ms-blob-content-language": "en",
    })
    _check("all props extracted", all_props.get("content_type") == "text/markdown; charset=utf-8" and
           all_props.get("cache_control") == "no-cache" and
           all_props.get("content_disposition") == "attachment; filename=\"doc.md\"" and
           all_props.get("content_encoding") == "gzip" and
           all_props.get("content_language") == "en")

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

    # 1c. container with public_access (BL3, R3)
    pub = az.dispatch(st, "PUT", "/public-photos", {"restype": "container"},
                      {"x-ms-blob-public-access": "blob"}, b"")
    _check("create container public-access 201", pub.status == 201)
    pub_get = az.dispatch(st, "GET", "/public-photos", {"restype": "container"}, {}, b"")
    _check("get container public-access header", pub_get.headers.get("x-ms-blob-public-access") == "blob")
    pub_head = az.dispatch(st, "HEAD", "/public-photos", {"restype": "container"}, {}, b"")
    _check("head container public-access header", pub_head.headers.get("x-ms-blob-public-access") == "blob")

    # 2. put block blob -> 201 + ETag + Last-Modified + Content-MD5
    body = b"hello from the Azure Blob core"
    up = az.dispatch(st, "PUT", "/photos/a/hello.txt", {},
                     {"x-ms-blob-type": "BlockBlob", "content-type": "text/plain"}, body)
    _check("put blob 201", up.status == 201)
    _check("put blob ETag", up.headers.get("etag", "").startswith('"'))
    _check("put blob Last-Modified", "last-modified" in up.headers)
    _check("put blob Content-MD5", up.headers.get("content-md5") ==
           base64.b64encode(hashlib.md5(body).digest()).decode())

    # 2b. put blob to missing container -> 404 ContainerNotFound + error XML (BL4, R4)
    miss_c = az.dispatch(st, "PUT", "/nope/x.txt", {},
                         {"x-ms-blob-type": "BlockBlob"}, b"x")
    _check("put blob missing container 404", miss_c.status == 404 and
           miss_c.headers.get("x-ms-error-code") == "ContainerNotFound")
    _check("put blob missing container error xml", "<Code>ContainerNotFound</Code>" in _text(miss_c))

    # 2c. put blob with x-ms-blob-content-type precedence (BL1, R1) & props (BL2, R2)
    png_body = b"\x89PNG\r\n\x1a\nfake-png-data"
    up_png = az.dispatch(st, "PUT", "/photos/org/42/logo.png", {},
                         {"x-ms-blob-type": "BlockBlob",
                          "content-type": "application/octet-stream",
                          "x-ms-blob-content-type": "image/png",
                          "x-ms-blob-cache-control": "public, max-age=3600",
                          "x-ms-blob-content-disposition": "inline; filename=\"logo.png\"",
                          "x-ms-blob-content-encoding": "gzip",
                          "x-ms-blob-content-language": "en-US"}, png_body)
    _check("put blob with props 201", up_png.status == 201)

    # 3. get blob -> 200 bytes round-trip + Content-Type + x-ms-blob-type + Content-Length
    g = az.dispatch(st, "GET", "/photos/a/hello.txt", {}, {}, b"")
    _check("get blob 200", g.status == 200)
    _check("get blob body round-trips", g.body == body)
    _check("get blob content-type", g.headers.get("content-type") == "text/plain")
    _check("get blob x-ms-blob-type", g.headers.get("x-ms-blob-type") == "BlockBlob")
    _check("get blob content-length", g.headers.get("content-length") == str(len(body)))

    # 3b. get blob props round-trip (BL1, BL2, R1, R2)
    g_png = az.dispatch(st, "GET", "/photos/org/42/logo.png", {}, {}, b"")
    _check("get blob precedence image/png", g_png.headers.get("content-type") == "image/png")
    _check("get blob cache-control", g_png.headers.get("cache-control") == "public, max-age=3600")
    _check("get blob content-disposition", g_png.headers.get("content-disposition") == "inline; filename=\"logo.png\"")
    _check("get blob content-encoding", g_png.headers.get("content-encoding") == "gzip")
    _check("get blob content-language", g_png.headers.get("content-language") == "en-US")

    # 4. HEAD blob props -> 200, no body
    h = az.dispatch(st, "HEAD", "/photos/a/hello.txt", {}, {}, b"")
    _check("head blob 200", h.status == 200)
    _check("head blob no body", h.body == b"")
    _check("head blob content-length", h.headers.get("content-length") == str(len(body)))
    _check("head blob etag", "etag" in h.headers)

    # 4b. HEAD blob props round-trip (BL2, R2)
    h_png = az.dispatch(st, "HEAD", "/photos/org/42/logo.png", {}, {}, b"")
    _check("head blob precedence image/png", h_png.headers.get("content-type") == "image/png")
    _check("head blob cache-control", h_png.headers.get("cache-control") == "public, max-age=3600")
    _check("head blob content-disposition", h_png.headers.get("content-disposition") == "inline; filename=\"logo.png\"")
    _check("head blob content-encoding", h_png.headers.get("content-encoding") == "gzip")
    _check("head blob content-language", h_png.headers.get("content-language") == "en-US")

    # 5. list blobs -> XML with the name & properties (BL2)
    lb = az.dispatch(st, "GET", "/photos", {"restype": "container", "comp": "list"}, {}, b"")
    _check("list blobs 200", lb.status == 200)
    _check("list blobs EnumerationResults", "<EnumerationResults" in _text(lb))
    _check("list blobs has Name", "<Name>a/hello.txt</Name>" in _text(lb))
    _check("list blobs Blob element", "<Blob>" in _text(lb))
    _check("list blobs xml content-type", "<Content-Type>image/png</Content-Type>" in _text(lb))
    _check("list blobs xml cache-control", "<Cache-Control>public, max-age=3600</Cache-Control>" in _text(lb))

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
    _check("deleted container error xml", "<Code>ContainerNotFound</Code>" in _text(gone))

    print("\nAzure Blob storage-core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
