"""GCS resumable upload conformance (v2.6.0) — host + Pyodide.

Initiate (uploadType=resumable → session URI in Location) then finalize the
session with a PUT of the media, and confirm the object + metadata land and the
session is single-use.
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


def run(store=None):
    store = store or InMemoryObjectStore()

    def call(m, p, q=None, h=None, b=b""):
        return gcs.dispatch(store, m, p, q or {}, h or {}, b)

    call("POST", "/storage/v1/b", {}, {"content-type": "application/json"},
         json.dumps({"name": "mybucket"}).encode())

    r = call("POST", "/upload/storage/v1/b/mybucket/o", {"uploadType": "resumable"},
             {"content-type": "application/json"},
             json.dumps({"name": "big.dat", "contentType": "text/plain",
                         "metadata": {"team": "blue"}}).encode())
    _check("initiate → Location session URI", r.status == 200 and "Location" in r.headers)
    sid = r.headers["Location"].split("upload_id=")[1]

    r = call("PUT", "/upload/storage/v1/b/mybucket/o", {"upload_id": sid}, {}, b"hello resumable world")
    obj = json.loads(r.body.decode())
    _check("finalize → object created with size/type/metadata",
           obj["name"] == "big.dat" and obj["size"] == "21" and
           obj["contentType"] == "text/plain" and obj["metadata"] == {"team": "blue"})

    g = call("GET", "/storage/v1/b/mybucket/o/big.dat", {"alt": "media"})
    _check("download → bytes match", g.body == b"hello resumable world")
    _check("session single-use (404 after finalize)",
           call("PUT", "/upload/storage/v1/b/mybucket/o", {"upload_id": sid}, {}, b"x").status == 404)

    print("\nGCS resumable upload conformance: ALL GREEN")
    return store


if __name__ == "__main__":
    run()
