"""S3 DEPTH pass, third iteration (v4 WAVE 5 — push config_only/limited sub-sections
further toward real enforcement).

Proves: Lifecycle NoncurrentVersionExpiration + Transition + AbortIncompleteMultipartUpload
(previously stored but not enforced), Object Lock bucket-level DefaultRetention (stamped
onto new object versions at upload time), Server access logging (PutBucketLogging now
writes real log-line objects into the target bucket instead of only storing the config),
and Replication DeleteMarkerReplication (a plain DELETE's delete marker is propagated to
the destination bucket synchronously, same as every other replicated write).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_s3_depth3_core.py
Run in Pyodide: loaded by wasm/ harness (same file).
"""
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


NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'


def _lifecycle_transition():
    st = InMemoryObjectStore()
    st.create_bucket("lct-bkt")
    lc = (f'<LifecycleConfiguration {NS}><Rule><ID>r1</ID><Status>Enabled</Status>'
          '<Filter><Prefix>a/</Prefix></Filter><Transition><Days>0</Days><StorageClass>GLACIER</StorageClass>'
          '</Transition></Rule></LifecycleConfiguration>').encode()
    s3.dispatch(st, "PUT", "/lct-bkt", {"lifecycle": ""}, body=lc)
    s3.dispatch(st, "PUT", "/lct-bkt/a/x.txt", body=b"hi")
    h = s3.dispatch(st, "HEAD", "/lct-bkt/a/x.txt")
    _check("Transition flips the current version's storage class once Days elapses", h.headers.get("x-amz-storage-class") == "GLACIER")

    s3.dispatch(st, "PUT", "/lct-bkt/b/y.txt", body=b"hi")
    h2 = s3.dispatch(st, "HEAD", "/lct-bkt/b/y.txt")
    _check("a key outside the rule's prefix is not transitioned", h2.headers.get("x-amz-storage-class") != "GLACIER")


def _lifecycle_noncurrent_expiration():
    st = InMemoryObjectStore()
    st.create_bucket("ncv-bkt", versioning="Enabled")
    lc = (f'<LifecycleConfiguration {NS}><Rule><ID>r1</ID><Status>Enabled</Status>'
          '<Filter><Prefix></Prefix></Filter><NoncurrentVersionExpiration><NoncurrentDays>30</NoncurrentDays>'
          '</NoncurrentVersionExpiration></Rule></LifecycleConfiguration>').encode()
    s3.dispatch(st, "PUT", "/ncv-bkt", {"lifecycle": ""}, body=lc)
    v1 = s3.dispatch(st, "PUT", "/ncv-bkt/o.txt", body=b"v1").headers["x-amz-version-id"]
    v2 = s3.dispatch(st, "PUT", "/ncv-bkt/o.txt", body=b"v2").headers["x-amz-version-id"]
    fresh = s3.dispatch(st, "GET", "/ncv-bkt", {"versions": ""}).body
    _check("a noncurrent version younger than NoncurrentDays survives the sweep", v1.encode() in fresh)

    for v in st.objects["ncv-bkt"]["o.txt"]["versions"]:
        if v["version_id"] == v1:
            v["last_modified"] = "2000-01-01T00:00:00.000Z"
    swept = s3.dispatch(st, "GET", "/ncv-bkt", {"versions": ""}).body
    _check("a noncurrent version older than NoncurrentDays is removed", v1.encode() not in swept)
    _check("the current version is untouched", v2.encode() in swept)


def _lifecycle_abort_incomplete_mpu():
    st = InMemoryObjectStore()
    st.create_bucket("mpu-bkt")
    lc = (f'<LifecycleConfiguration {NS}><Rule><ID>r1</ID><Status>Enabled</Status>'
          '<Filter><Prefix></Prefix></Filter><AbortIncompleteMultipartUpload><DaysAfterInitiation>7</DaysAfterInitiation>'
          '</AbortIncompleteMultipartUpload></Rule></LifecycleConfiguration>').encode()
    s3.dispatch(st, "PUT", "/mpu-bkt", {"lifecycle": ""}, body=lc)
    import re
    r = s3.dispatch(st, "POST", "/mpu-bkt/big.bin", {"uploads": ""})
    uid = re.search(rb"<UploadId>(.*?)</UploadId>", r.body).group(1).decode()
    fresh = s3.dispatch(st, "GET", "/mpu-bkt", {"uploads": ""}).body
    _check("a fresh incomplete upload survives the sweep", uid.encode() in fresh)

    for up in s3._mpu(st).values():
        up["initiated"] = "2000-01-01T00:00:00.000Z"
    swept = s3.dispatch(st, "GET", "/mpu-bkt", {"uploads": ""}).body
    _check("a stale incomplete upload is aborted past DaysAfterInitiation", uid.encode() not in swept)


def _object_lock_default_retention():
    st = InMemoryObjectStore()
    st.create_bucket("dr-bkt", versioning="Enabled")
    st.buckets["dr-bkt"]["object_lock"] = True
    doc = (f'<ObjectLockConfiguration {NS}><ObjectLockEnabled>Enabled</ObjectLockEnabled>'
           '<Rule><DefaultRetention><Mode>GOVERNANCE</Mode><Days>10</Days></DefaultRetention></Rule>'
           '</ObjectLockConfiguration>').encode()
    put = s3.dispatch(st, "PUT", "/dr-bkt", {"object-lock": ""}, body=doc)
    _check("PutObjectLockConfiguration with a DefaultRetention rule accepted", put.status == 200)
    got = s3.dispatch(st, "GET", "/dr-bkt", {"object-lock": ""})
    _check("GetObjectLockConfiguration round-trips the DefaultRetention rule", b"<Mode>GOVERNANCE</Mode>" in got.body and b"<Days>10</Days>" in got.body)

    vid = s3.dispatch(st, "PUT", "/dr-bkt/f.txt", body=b"hi").headers["x-amz-version-id"]
    ret = s3.dispatch(st, "GET", "/dr-bkt/f.txt", {"retention": ""})
    _check("a newly uploaded object inherits the bucket's DefaultRetention without an explicit request", b"<Mode>GOVERNANCE</Mode>" in ret.body)
    blocked = s3.dispatch(st, "DELETE", "/dr-bkt/f.txt", {"versionId": vid})
    _check("the inherited default retention is actually enforced on delete", blocked.status == 403)
    bypassed = s3.dispatch(st, "DELETE", "/dr-bkt/f.txt", {"versionId": vid}, {"x-amz-bypass-governance-retention": "true"})
    _check("GOVERNANCE default retention can still be bypassed like an explicit one", bypassed.status == 204)


def _logging_writes_objects():
    st = InMemoryObjectStore()
    st.create_bucket("src-bkt")
    st.create_bucket("log-dest")
    doc = (f'<BucketLoggingStatus {NS}><LoggingEnabled><TargetBucket>log-dest</TargetBucket>'
           '<TargetPrefix>logs/</TargetPrefix></LoggingEnabled></BucketLoggingStatus>').encode()
    s3.dispatch(st, "PUT", "/src-bkt", {"logging": ""}, body=doc)

    s3.dispatch(st, "PUT", "/src-bkt/a.txt", body=b"hello world")
    s3.dispatch(st, "GET", "/src-bkt/a.txt")
    listing = s3.dispatch(st, "GET", "/log-dest", {"list-type": "2", "prefix": "logs/"}).body
    _check("PutObject + GetObject each write a real log object into the target bucket", listing.count(b"<Contents>") == 2)
    _check("the log key uses TargetPrefix + source bucket name", b"<Key>logs/src-bkt-" in listing)

    log_obj = s3.dispatch(st, "GET", "/log-dest", {"list-type": "2", "prefix": "logs/", "max-keys": "1"})
    import re
    key = re.search(rb"<Key>(logs/[^<]+)</Key>", log_obj.body).group(1).decode()
    body = s3.dispatch(st, "GET", f"/log-dest/{key}").body
    _check("the log line names the source bucket and the REST operation", b"src-bkt" in body and b"REST." in body)

    # A bucket with no logging configured never writes anything.
    st.create_bucket("plain-bkt")
    s3.dispatch(st, "PUT", "/plain-bkt/x.txt", body=b"x")
    _check("a bucket without PutBucketLogging writes nothing anywhere",
          not any(k.startswith("logs/plain-bkt") for k in st.objects.get("log-dest", {})))


def _replication_delete_marker():
    st = InMemoryObjectStore()
    st.create_bucket("rsrc-bkt", versioning="Enabled")
    st.create_bucket("rdst-bkt", versioning="Enabled")
    rep = (f'<ReplicationConfiguration {NS}><Role>arn:aws:iam::123456789012:role/repl</Role>'
           '<Rule><ID>r1</ID><Status>Enabled</Status><Filter><Prefix></Prefix></Filter>'
           '<DeleteMarkerReplication><Status>Enabled</Status></DeleteMarkerReplication>'
           '<Destination><Bucket>arn:aws:s3:::rdst-bkt</Bucket></Destination></Rule>'
           '</ReplicationConfiguration>').encode()
    s3.dispatch(st, "PUT", "/rsrc-bkt", {"replication": ""}, body=rep)
    s3.dispatch(st, "PUT", "/rsrc-bkt/a.txt", body=b"hi")
    _check("the object replicates before the delete", s3.dispatch(st, "GET", "/rdst-bkt/a.txt").status == 200)

    s3.dispatch(st, "DELETE", "/rsrc-bkt/a.txt")
    _check("a plain DELETE's delete marker is replicated (dest GET now 404)", s3.dispatch(st, "GET", "/rdst-bkt/a.txt").status == 404)
    versions = s3.dispatch(st, "GET", "/rdst-bkt", {"versions": ""}).body
    _check("the destination carries an actual DeleteMarker entry, not just a missing key", b"<DeleteMarker>" in versions)

    # Without DeleteMarkerReplication enabled, the marker stays source-only.
    st2 = InMemoryObjectStore()
    st2.create_bucket("nodmr-src", versioning="Enabled")
    st2.create_bucket("nodmr-dst", versioning="Enabled")
    rep2 = (f'<ReplicationConfiguration {NS}><Role>arn:aws:iam::123456789012:role/repl</Role>'
            '<Rule><ID>r1</ID><Status>Enabled</Status><Filter><Prefix></Prefix></Filter>'
            '<Destination><Bucket>arn:aws:s3:::nodmr-dst</Bucket></Destination></Rule>'
            '</ReplicationConfiguration>').encode()
    s3.dispatch(st2, "PUT", "/nodmr-src", {"replication": ""}, body=rep2)
    s3.dispatch(st2, "PUT", "/nodmr-src/a.txt", body=b"hi")
    s3.dispatch(st2, "DELETE", "/nodmr-src/a.txt")
    _check("DeleteMarkerReplication is opt-in: disabled by default, the destination keeps the stale object",
          s3.dispatch(st2, "GET", "/nodmr-dst/a.txt").status == 200)


def run() -> int:
    _lifecycle_transition()
    _lifecycle_noncurrent_expiration()
    _lifecycle_abort_incomplete_mpu()
    _object_lock_default_retention()
    _logging_writes_objects()
    _replication_delete_marker()
    print("\nRESULT: PASS — S3 DEPTH-pass-3 (lifecycle Transition/NoncurrentVersionExpiration/"
          "AbortIncompleteMultipartUpload, Object Lock DefaultRetention, enforced logging, "
          "DeleteMarkerReplication) holds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
