"""v4 C0 — MinioBackedObjectStore keeps ALL bucket state across a restart.

Before C0 a fresh MinioBackedObjectStore rebuilt its buckets from MinIO and lost
everything in store.buckets[name] (versioning, cfg sub-resources, object lock,
tags, GCS labels/retention). Now the cores call persist() and the store keeps a
SQLite sidecar. Also proves build_object_store() falls back to a SQLite-only
persistent store when MinIO is unreachable.

Host-only (boto3). Needs a MinIO: VYOMI_MINIO_ENDPOINT (default http://127.0.0.1:9190)
with the appliance dev credentials; without one only the fallback half runs.
Run:  PYTHONPATH=. python3 tests/conformance/test_minio_sidecar_store.py
"""
import json
import os
import tempfile

from core import gcp_storage_core as gcs
from core import s3_object_core as s3
from core.minio_backed_store import build_object_store, minio_reachable
from core.persistent_store import PersistentObjectStore

EP = os.environ.get("VYOMI_MINIO_ENDPOINT", "http://127.0.0.1:9190")
AK = os.environ.get("VYOMI_MINIO_ACCESS_KEY", "cloudlearn")
SK = os.environ.get("VYOMI_MINIO_SECRET_KEY", "cloudlearn-dev-secret-key")
NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def _exercise(new):
    a = new()
    c = lambda m, p, q=None, h=None, b=b"": s3.dispatch(a, m, p, q or {}, h or {}, b)
    c("PUT", "/sc-bkt", None, {"x-amz-bucket-object-lock-enabled": "true"})
    c("PUT", "/sc-bkt", {"encryption": ""}, {}, f"<ServerSideEncryptionConfiguration {NS}/>".encode())
    c("PUT", "/sc-bkt", {"tagging": ""}, {},
      f"<Tagging {NS}><TagSet><Tag><Key>k</Key><Value>v</Value></Tag></TagSet></Tagging>".encode())
    c("PUT", "/sc-bkt/f.txt", None, None, b"one")
    c("PUT", "/sc-bkt/f.txt", None, None, b"two")
    c("DELETE", "/sc-bkt/f.txt")                                  # delete marker (versioned via object lock)
    gcs.dispatch(a, "POST", "/storage/v1/b", {}, {}, json.dumps(
        {"name": "sc-gb", "labels": {"env": "t"}, "retentionPolicy": {"retentionPeriod": 9}}).encode())
    b = new()                                                      # restart
    meta = b.buckets.get("sc-bkt", {})
    _check("versioning + object lock survive", meta.get("versioning") == "Enabled" and meta.get("object_lock"))
    _check("cfg sub-resources survive", "encryption" in meta.get("cfg", {}) and "tagging" in meta.get("cfg", {}))
    vers = s3.dispatch(b, "GET", "/sc-bkt", {"versions": ""}, {}, b"").body.decode()
    _check("version chain + delete marker survive", vers.count("<Version>") == 2 and "<DeleteMarker>" in vers, vers)
    _check("older version bytes readable", s3.dispatch(
        b, "GET", "/sc-bkt/f.txt", {"versionId": vers.split("<Version><Key>f.txt</Key><VersionId>")[1].split("<")[0]},
        {}, b"").status == 200)
    g = b.buckets.get("sc-gb", {})
    _check("GCS labels + retention survive", g.get("labels") == {"env": "t"} and g.get("retentionPolicy"))
    return b


def run() -> int:
    tmp = tempfile.mkdtemp(prefix="vyomi-sidecar-")
    if minio_reachable(EP, AK, SK):
        print(f"[MinIO at {EP}]")
        side = os.path.join(tmp, "minio-meta.sqlite")
        b = _exercise(lambda: build_object_store("c0sidecar-", EP, AK, SK, sidecar_path=side))
        _check("MinIO-backed store selected", type(b).__name__ == "MinioBackedObjectStore")
        for name in list(b.buckets):                               # clean the real buckets
            real = b._mb(name)
            for o in b._s3.list_objects_v2(Bucket=real).get("Contents", []):
                b._s3.delete_object(Bucket=real, Key=o["Key"])
            b._s3.delete_bucket(Bucket=real)
    else:
        print(f"[no MinIO at {EP} — MinIO half skipped]")
    print("[MinIO unreachable → SQLite fallback]")
    side = os.path.join(tmp, "fallback.sqlite")
    b = _exercise(lambda: build_object_store("c0fb-", "http://127.0.0.1:1", AK, SK, sidecar_path=side))
    _check("fallback is a SQLite-persistent store", isinstance(b, PersistentObjectStore))
    print("\nRESULT: PASS — object-store state is durable with and without MinIO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
