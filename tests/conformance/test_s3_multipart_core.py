"""S3 multipart upload conformance (v2.6.0) — host + Pyodide.

CreateMultipartUpload → UploadPart(×N) → ListParts → CompleteMultipartUpload
(assembles the parts, canonical `md5(concat part-md5s)-N` ETag) and Abort.
"""
import re

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


def run(store=None):
    store = store or InMemoryObjectStore()

    def call(m, p, q=None, h=None, b=b""):
        return s3.dispatch(store, m, p, q or {}, h or {}, b)

    call("PUT", "/mybucket")
    uid = re.search(r"<UploadId>(.*?)</UploadId>",
                    call("POST", "/mybucket/big.bin", {"uploads": ""},
                         {"content-type": "application/octet-stream"}).body.decode()).group(1)
    _check("initiate returns an UploadId", len(uid) > 16)

    p1, p2, p3 = b"A" * 100, b"B" * 200, b"C" * 50
    e1 = call("PUT", "/mybucket/big.bin", {"uploadId": uid, "partNumber": "1"}, {}, p1).headers["ETag"]
    e2 = call("PUT", "/mybucket/big.bin", {"uploadId": uid, "partNumber": "2"}, {}, p2).headers["ETag"]
    e3 = call("PUT", "/mybucket/big.bin", {"uploadId": uid, "partNumber": "3"}, {}, p3).headers["ETag"]

    lp = call("GET", "/mybucket/big.bin", {"uploadId": uid}).body.decode()
    _check("ListParts shows all 3 parts", lp.count("<Part>") == 3)

    body = ("<CompleteMultipartUpload>" + "".join(
        f"<Part><PartNumber>{n}</PartNumber><ETag>{e}</ETag></Part>"
        for n, e in [(1, e1), (2, e2), (3, e3)]) + "</CompleteMultipartUpload>").encode()
    r = call("POST", "/mybucket/big.bin", {"uploadId": uid}, {}, body)
    final_etag = re.search(r"<ETag>(.*?)</ETag>", r.body.decode()).group(1)
    _check("complete → multipart ETag (-N suffix)", final_etag.endswith('-3"'))

    g = call("GET", "/mybucket/big.bin")
    _check("assembled object == concatenated parts", g.body == p1 + p2 + p3)

    uid2 = re.search(r"<UploadId>(.*?)</UploadId>",
                     call("POST", "/mybucket/x", {"uploads": ""}).body.decode()).group(1)
    _check("abort returns 204", call("DELETE", "/mybucket/x", {"uploadId": uid2}).status == 204)
    _check("aborted upload is gone (404)", call("GET", "/mybucket/x", {"uploadId": uid2}).status == 404)

    print("\nS3 multipart upload conformance: ALL GREEN")
    return store


if __name__ == "__main__":
    run()
