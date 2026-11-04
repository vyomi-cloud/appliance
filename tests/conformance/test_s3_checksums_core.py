"""S3 additional checksums (x-amz-checksum-*): CRC32 / CRC32C / CRC64NVME / SHA1 / SHA256 are
computed against the standard check values, VERIFIED on upload (BadDigest on mismatch, header or
aws-chunked trailer), stored with the object version and returned on Put/Copy and on Head/Get
when x-amz-checksum-mode: ENABLED.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_s3_checksums_core.py
Run in Pyodide: loaded by wasm/ harness (same file).
"""
import base64
import hashlib

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


def _b64(hexstr):
    return base64.b64encode(bytes.fromhex(hexstr)).decode()


def run() -> int:
    # standard "123456789" check values
    d = b"123456789"
    _check("CRC32 check value", s3._checksum_value("CRC32", d) == _b64("cbf43926"))
    _check("CRC32C check value", s3._checksum_value("CRC32C", d) == _b64("e3069283"))
    _check("CRC64NVME check value", s3._checksum_value("CRC64NVME", d) == _b64("ae8b14860a799888"))
    _check("SHA1", s3._checksum_value("SHA1", d) == base64.b64encode(hashlib.sha1(d).digest()).decode())
    _check("SHA256", s3._checksum_value("SHA256", d) == base64.b64encode(hashlib.sha256(d).digest()).decode())

    st = InMemoryObjectStore()
    st.create_bucket("b")
    good = s3._checksum_value("CRC32", b"hello")
    r = s3.put_object(st, "b", "k", b"hello", {"x-amz-checksum-crc32": good})
    _check("PutObject echoes the verified checksum", r.status == 200 and r.headers.get("x-amz-checksum-crc32") == good)
    r = s3.put_object(st, "b", "bad", b"hello", {"x-amz-checksum-crc32": s3._checksum_value("CRC32", b"other")})
    _check("mismatched checksum -> 400 BadDigest", r.status == 400 and b"BadDigest" in r.body)
    _check("rejected object is not stored", s3.head_object(st, "b", "bad", {}, {}).status == 404)
    h = s3.head_object(st, "b", "k", {}, {})
    _check("HeadObject hides the checksum without checksum-mode", "x-amz-checksum-crc32" not in h.headers)
    h = s3.head_object(st, "b", "k", {}, {"X-Amz-Checksum-Mode": "ENABLED"})
    _check("HeadObject returns it with checksum-mode ENABLED", h.headers.get("x-amz-checksum-crc32") == good)
    g = s3.get_object(st, "b", "k", {}, {"x-amz-checksum-mode": "ENABLED"})
    _check("GetObject returns it with checksum-mode ENABLED", g.headers.get("x-amz-checksum-crc32") == good)

    # the server computes the checksum when only the algorithm is requested
    r = s3.put_object(st, "b", "calc", b"hello", {"x-amz-sdk-checksum-algorithm": "SHA256"})
    _check("algorithm-only request computes SHA256", r.headers.get("x-amz-checksum-sha256") == s3._checksum_value("SHA256", b"hello"))
    r = s3.put_object(st, "b", "x", b"hello", {"x-amz-sdk-checksum-algorithm": "MD5"})
    _check("unsupported algorithm is rejected", r.status == 400)

    # aws-chunked body with the checksum as a TRAILER (what current SDKs send)
    body = b"5\r\nhello\r\n0\r\nx-amz-checksum-crc32:" + good.encode() + b"\r\n\r\n"
    r = s3.put_object(st, "b", "chunked", body, {"content-encoding": "aws-chunked", "x-amz-trailer": "x-amz-checksum-crc32"})
    _check("aws-chunked trailer checksum verified + body decoded", r.status == 200
           and s3.get_object(st, "b", "chunked", {}, {}).body == b"hello")
    bad = b"5\r\nhello\r\n0\r\nx-amz-checksum-crc32:" + s3._checksum_value("CRC32", b"nope").encode() + b"\r\n\r\n"
    _check("aws-chunked trailer mismatch -> BadDigest",
           s3.put_object(st, "b", "chunked2", bad, {"content-encoding": "aws-chunked"}).status == 400)

    # CopyObject carries the checksum
    s3.copy_object(st, "b", "k2", {"x-amz-copy-source": "/b/k"})
    h = s3.head_object(st, "b", "k2", {}, {"x-amz-checksum-mode": "ENABLED"})
    _check("CopyObject keeps the source checksum", h.headers.get("x-amz-checksum-crc32") == good)
    print("\nRESULT: PASS — S3 additional checksums hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
