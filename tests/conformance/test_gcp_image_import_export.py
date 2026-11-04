"""Compute Engine image import (rawDisk from GCS), export to GCS, import/export history
(run: PYTHONPATH=. python3 tests/conformance/test_gcp_image_import_export.py)."""
import gzip
import io
import json
import os
import sys
import tarfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False   # engine test: ad-hoc project ids
R = AwsWireRouter()
PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(method, path, body=None, query=None):
    out = R.handle(method, path, query or {}, {"content-type": "application/json"}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {"raw": out["body"]}


C = "/compute/v1/projects/imp1"
call("POST", "/storage/v1/b", {"name": "vm-import-src"}, {"project": "imp1"})
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w:gz") as tf:
    raw = b"\0" * 4096
    ti = tarfile.TarInfo("disk.raw"); ti.size = len(raw); tf.addfile(ti, io.BytesIO(raw))
R.handle("POST", "/upload/storage/v1/b/vm-import-src/o", {"uploadType": "media", "name": "disk.tar.gz"}, {"content-type": "application/gzip"}, buf.getvalue())
R.handle("POST", "/upload/storage/v1/b/vm-import-src/o", {"uploadType": "media", "name": "notes.txt"}, {"content-type": "text/plain"}, b"x")

s, r = call("POST", C + "/global/images", {"name": "imported-1", "rawDisk": {"source": "gs://vm-import-src/disk.tar.gz"}})
check("images.insert with rawDisk from GCS", s == 200, r)
s, img = call("GET", C + "/global/images/imported-1")
check("image is RAW sourceType with the rawDisk source and archive size", img.get("sourceType") == "RAW" and img["rawDisk"]["source"] == "gs://vm-import-src/disk.tar.gz" and int(img["archiveSizeBytes"]) > 0, img)
check("https storage URL accepted", call("POST", C + "/global/images", {"name": "imported-2", "rawDisk": {"source": "https://storage.googleapis.com/vm-import-src/disk.tar.gz"}})[0] == 200)
check("missing object -> 404", call("POST", C + "/global/images", {"name": "imported-3", "rawDisk": {"source": "gs://vm-import-src/nope.tar.gz"}})[0] == 404)
check("missing bucket -> 404", call("POST", C + "/global/images", {"name": "imported-4", "rawDisk": {"source": "gs://ghost/disk.tar.gz"}})[0] == 404)
check("non-tar.gz source -> 400", call("POST", C + "/global/images", {"name": "imported-5", "rawDisk": {"source": "gs://vm-import-src/notes.txt"}})[0] == 400)
check("not a Cloud Storage URL -> 400", call("POST", C + "/global/images", {"name": "imported-6", "rawDisk": {"source": "/tmp/disk.tar.gz"}})[0] == 400)
check("rawDisk + sourceDisk -> 400", call("POST", C + "/global/images", {"name": "imported-7", "rawDisk": {"source": "gs://vm-import-src/disk.tar.gz"}, "sourceDisk": "d"})[0] == 400)
check("duplicate image name -> 409", call("POST", C + "/global/images", {"name": "imported-1", "rawDisk": {"source": "gs://vm-import-src/disk.tar.gz"}})[0] == 409)

call("POST", "/storage/v1/b", {"name": "vm-export-dst"}, {"project": "imp1"})
s, op = call("POST", C + "/global/images/imported-1:export", {"destinationUri": "gs://vm-export-dst/out/imported-1.tar.gz", "format": "vmdk"})
check("export image to GCS", s == 200, op)
st = R.handle("GET", "/storage/v1/b/vm-export-dst/o/out%2Fimported-1.tar.gz", {"alt": "media"}, {}, b"")
tf = tarfile.open(fileobj=io.BytesIO(st["body"]), mode="r:gz") if st["status"] == 200 else None
check("exported object is a real tar.gz in the destination bucket", tf is not None and "image.json" in tf.getnames())
check("export to a missing bucket -> 404", call("POST", C + "/global/images/imported-1:export", {"destinationUri": "gs://ghost/x.tar.gz"})[0] == 404)
check("export unknown format -> 400", call("POST", C + "/global/images/imported-1:export", {"destinationUri": "gs://vm-export-dst/x.tar.gz", "format": "iso"})[0] == 400)
check("export of a missing image -> 404", call("POST", C + "/global/images/zzz:export", {"destinationUri": "gs://vm-export-dst/x.tar.gz"})[0] == 404)

check("instance from a missing custom image -> 404", call("POST", C + "/zones/us-central1-a/instances", {"name": "vm-x", "machineType": "e2-medium", "disks": [{"boot": True, "initializeParams": {"sourceImage": "global/images/ghost"}}]})[0] == 404)
check("instance from the imported image", call("POST", C + "/zones/us-central1-a/instances", {"name": "vm-y", "machineType": "e2-medium", "disks": [{"boot": True, "initializeParams": {"sourceImage": "global/images/imported-1"}}]})[0] == 200)
s, jobs = call("GET", C + "/global/imageJobs")
items = jobs.get("items", [])
kinds = [(j["kind"], j["status"]) for j in items]
check("history records successful and failed imports and exports", ("import", "DONE") in kinds and ("import", "FAILED") in kinds and ("export", "DONE") in kinds and ("export", "FAILED") in kinds, kinds)
check("history rows carry image, uri and times", all(j["image"] and j["uri"] and j["startTime"] for j in items))
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
