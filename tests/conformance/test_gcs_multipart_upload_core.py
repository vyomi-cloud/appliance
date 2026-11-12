"""GCS multipart/related uploads exactly as real clients send them.

gcloud (apitools / Python email generator) sends `boundary='…'` in SINGLE quotes and LF
line endings; the JSON client libraries send double quotes and CRLF. Both must store the
object under the metadata name with the media bytes byte-for-byte (a file ending in a
newline keeps it).

Run: PYTHONPATH=. python3 tests/conformance/test_gcs_multipart_upload_core.py
"""
import json
import sys

try:
    from core.object_store import InMemoryObjectStore
    from core import gcp_storage_core as gcs
except ImportError:  # vendored layout (wasm/core on sys.path)
    from object_store import InMemoryObjectStore  # type: ignore
    import gcp_storage_core as gcs  # type: ignore

FAILS = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)


def upload(st, bucket, name, media, *, quote, nl):
    b = "===============6384608772179982017=="
    meta = json.dumps({"name": name}).encode()
    body = (f"--{b}{nl}Content-Type: application/json{nl}{nl}").encode() + meta + nl.encode() + \
           (f"--{b}{nl}Content-Type: text/plain{nl}{nl}").encode() + media + nl.encode() + f"--{b}--{nl}".encode()
    ct = f"multipart/related; boundary={quote}{b}{quote}"
    return gcs.dispatch(st, "POST", f"/upload/storage/v1/b/{bucket}/o", {"uploadType": "multipart"},
                        {"content-type": ct}, body)


def read(st, bucket, name):
    r = gcs.dispatch(st, "GET", f"/storage/v1/b/{bucket}/o/{name}", {"alt": "media"}, {}, b"")
    return r.status, r.body if isinstance(r.body, bytes) else str(r.body).encode()


st = InMemoryObjectStore()
gcs.dispatch(st, "POST", "/storage/v1/b", {"project": "p"}, {"content-type": "application/json"}, json.dumps({"name": "mp"}).encode())
for label, quote, nl in [("gcloud: single quotes + LF", "'", "\n"), ("client libs: double quotes + CRLF", '"', "\r\n"), ("no quotes + CRLF", "", "\r\n")]:
    name = "f-" + label.split(":")[0].replace(" ", "-") + ".txt"
    r = upload(st, "mp", name, b"hello\n", quote=quote, nl=nl)
    check(f"{label}: upload 200", r.status == 200)
    status, data = read(st, "mp", name)
    check(f"{label}: stored under metadata name, bytes intact (trailing newline kept)", status == 200 and data == b"hello\n")

if FAILS:
    print("RESULT: FAIL —", ", ".join(FAILS))
    sys.exit(1)
print("GCS multipart upload conformance: ALL GREEN")
