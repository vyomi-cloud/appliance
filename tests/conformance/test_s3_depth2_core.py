"""S3 DEPTH pass, second iteration (v4 — raise the remaining not_simulated/config_only
sub-sections). Proves: website/logging/requester-pays config storage+return,
id-keyed configurations (Intelligent-Tiering / Inventory / Metrics) storage+return,
and synchronous same-appliance replication enforcement.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_s3_depth2_core.py
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


def _website():
    st = InMemoryObjectStore()
    st.create_bucket("web-bkt")
    absent = s3.dispatch(st, "GET", "/web-bkt", {"website": ""})
    _check("GetBucketWebsite 404 when unconfigured", absent.status == 404 and b"NoSuchWebsiteConfiguration" in absent.body)

    doc = f'<WebsiteConfiguration {NS}><IndexDocument><Suffix>index.html</Suffix></IndexDocument><ErrorDocument><Key>error.html</Key></ErrorDocument></WebsiteConfiguration>'.encode()
    put = s3.dispatch(st, "PUT", "/web-bkt", {"website": ""}, body=doc)
    _check("PutBucketWebsite accepted", put.status == 200)
    got = s3.dispatch(st, "GET", "/web-bkt", {"website": ""})
    _check("GetBucketWebsite round-trips the index document", b"<Suffix>index.html</Suffix>" in got.body)

    bad = s3.dispatch(st, "PUT", "/web-bkt", {"website": ""}, body=b"not xml")
    _check("malformed website XML rejected (400)", bad.status == 400)

    deleted = s3.dispatch(st, "DELETE", "/web-bkt", {"website": ""})
    _check("DeleteBucketWebsite 204", deleted.status == 204)
    after = s3.dispatch(st, "GET", "/web-bkt", {"website": ""})
    _check("website configuration gone after delete", after.status == 404)


def _logging():
    st = InMemoryObjectStore()
    st.create_bucket("log-bkt")
    default = s3.dispatch(st, "GET", "/log-bkt", {"logging": ""})
    _check("GetBucketLogging 200 (never 404) when disabled", default.status == 200 and b"<BucketLoggingStatus" in default.body)

    doc = f'<BucketLoggingStatus {NS}><LoggingEnabled><TargetBucket>log-dest</TargetBucket><TargetPrefix>logs/</TargetPrefix></LoggingEnabled></BucketLoggingStatus>'.encode()
    put = s3.dispatch(st, "PUT", "/log-bkt", {"logging": ""}, body=doc)
    _check("PutBucketLogging accepted", put.status == 200)
    got = s3.dispatch(st, "GET", "/log-bkt", {"logging": ""})
    _check("GetBucketLogging round-trips the target bucket", b"<TargetBucket>log-dest</TargetBucket>" in got.body)

    cleared = s3.dispatch(st, "PUT", "/log-bkt", {"logging": ""}, body=f"<BucketLoggingStatus {NS}/>".encode())
    _check("empty BucketLoggingStatus disables logging", cleared.status == 200)
    after = s3.dispatch(st, "GET", "/log-bkt", {"logging": ""})
    _check("GetBucketLogging back to the empty default", b"LoggingEnabled" not in after.body)


def _request_payment():
    st = InMemoryObjectStore()
    st.create_bucket("pay-bkt")
    default = s3.dispatch(st, "GET", "/pay-bkt", {"requestPayment": ""})
    _check("GetBucketRequestPayment defaults to BucketOwner", b"<Payer>BucketOwner</Payer>" in default.body)

    put = s3.dispatch(st, "PUT", "/pay-bkt", {"requestPayment": ""},
                      body=f"<RequestPaymentConfiguration {NS}><Payer>Requester</Payer></RequestPaymentConfiguration>".encode())
    _check("PutBucketRequestPayment accepted", put.status == 200)
    got = s3.dispatch(st, "GET", "/pay-bkt", {"requestPayment": ""})
    _check("GetBucketRequestPayment reflects Requester", b"<Payer>Requester</Payer>" in got.body)

    bad = s3.dispatch(st, "PUT", "/pay-bkt", {"requestPayment": ""}, body=b"<RequestPaymentConfiguration/>")
    _check("missing Payer element rejected (400)", bad.status == 400)


def _id_keyed_configs():
    for sub, tag, list_tag in (
        ("intelligent-tiering", "IntelligentTieringConfiguration", "ListBucketIntelligentTieringConfigurationsOutput"),
        ("inventory", "InventoryConfiguration", "ListInventoryConfigurationsResult"),
        ("metrics", "MetricsConfiguration", "ListBucketMetricsConfigurationsResult"),
    ):
        st = InMemoryObjectStore()
        st.create_bucket("cfg-bkt")
        no_id = s3.dispatch(st, "PUT", f"/cfg-bkt", {sub: ""}, body=f"<{tag} {NS}><Id>x</Id></{tag}>".encode())
        _check(f"{sub}: PUT without id rejected (400)", no_id.status == 400)

        missing = s3.dispatch(st, "GET", "/cfg-bkt", {sub: "", "id": "cfg1"})
        _check(f"{sub}: GET of an unknown id is 404", missing.status == 404)

        doc = f"<{tag} {NS}><Id>cfg1</Id></{tag}>".encode()
        put = s3.dispatch(st, "PUT", "/cfg-bkt", {sub: "", "id": "cfg1"}, body=doc)
        _check(f"{sub}: PUT with id accepted", put.status == 200)

        got = s3.dispatch(st, "GET", "/cfg-bkt", {sub: "", "id": "cfg1"})
        _check(f"{sub}: GET by id round-trips the stored document", b"<Id>cfg1</Id>" in got.body)

        put2 = s3.dispatch(st, "PUT", "/cfg-bkt", {sub: "", "id": "cfg2"}, body=f"<{tag} {NS}><Id>cfg2</Id></{tag}>".encode())
        _check(f"{sub}: a second configuration can coexist", put2.status == 200)
        listing = s3.dispatch(st, "GET", "/cfg-bkt", {sub: ""})
        _check(f"{sub}: List wraps both configurations in {list_tag}", listing.body.count(f"<{tag}".encode()) == 2 and list_tag.encode() in listing.body)

        deleted = s3.dispatch(st, "DELETE", "/cfg-bkt", {sub: "", "id": "cfg1"})
        _check(f"{sub}: DELETE by id is 204", deleted.status == 204)
        after = s3.dispatch(st, "GET", "/cfg-bkt", {sub: "", "id": "cfg1"})
        _check(f"{sub}: deleted id now 404", after.status == 404)


def _replication_requires_versioning():
    st = InMemoryObjectStore()
    st.create_bucket("src-bkt")       # versioning NOT enabled
    st.create_bucket("dst-bkt", versioning="Enabled")
    rep = (f'<ReplicationConfiguration {NS}><Role>arn:aws:iam::123456789012:role/repl</Role>'
           '<Rule><ID>r1</ID><Status>Enabled</Status><Filter><Prefix>logs/</Prefix></Filter>'
           '<Destination><Bucket>arn:aws:s3:::dst-bkt</Bucket></Destination></Rule>'
           '</ReplicationConfiguration>').encode()
    blocked = s3.dispatch(st, "PUT", "/src-bkt", {"replication": ""}, body=rep)
    _check("PutBucketReplication rejected without source versioning (400)", blocked.status == 400 and b"InvalidRequest" in blocked.body)

    missing = s3.dispatch(st, "GET", "/src-bkt", {"replication": ""})
    _check("GetBucketReplication 404 when unconfigured", missing.status == 404 and b"ReplicationConfigurationNotFoundError" in missing.body)

    st.buckets["src-bkt"]["versioning"] = "Enabled"
    ok = s3.dispatch(st, "PUT", "/src-bkt", {"replication": ""}, body=rep)
    _check("PutBucketReplication accepted once source versioning is Enabled", ok.status == 200)
    got = s3.dispatch(st, "GET", "/src-bkt", {"replication": ""})
    _check("GetBucketReplication round-trips the rule", b"<Bucket>arn:aws:s3:::dst-bkt</Bucket>" in got.body)


def _replication_enforced_on_write():
    st = InMemoryObjectStore()
    st.create_bucket("rsrc-bkt", versioning="Enabled")
    st.create_bucket("rdst-bkt", versioning="Enabled")
    rep = (f'<ReplicationConfiguration {NS}><Role>arn:aws:iam::123456789012:role/repl</Role>'
           '<Rule><ID>r1</ID><Status>Enabled</Status><Filter><Prefix>logs/</Prefix></Filter>'
           '<Destination><Bucket>arn:aws:s3:::rdst-bkt</Bucket></Destination></Rule>'
           '</ReplicationConfiguration>').encode()
    s3.dispatch(st, "PUT", "/rsrc-bkt", {"replication": ""}, body=rep)

    s3.dispatch(st, "PUT", "/rsrc-bkt/logs/a.txt", body=b"replicate me")
    s3.dispatch(st, "PUT", "/rsrc-bkt/keep/b.txt", body=b"stay put")

    replicated = s3.dispatch(st, "GET", "/rdst-bkt/logs/a.txt")
    _check("a matching key is synchronously copied to the destination bucket", replicated.status == 200 and replicated.body == b"replicate me")
    not_replicated = s3.dispatch(st, "GET", "/rdst-bkt/keep/b.txt")
    _check("a key outside the rule's prefix is NOT replicated", not_replicated.status == 404)

    h = s3.dispatch(st, "HEAD", "/rsrc-bkt/logs/a.txt")
    _check("source object reports x-amz-replication-status: COMPLETED", h.headers.get("x-amz-replication-status") == "COMPLETED")
    h2 = s3.dispatch(st, "HEAD", "/rsrc-bkt/keep/b.txt")
    _check("non-matching key carries no replication-status header", "x-amz-replication-status" not in h2.headers)

    # CopyObject also replicates (server-side copy produces a new current version too).
    s3.dispatch(st, "PUT", "/rsrc-bkt/logs/c.txt", {},
               {"x-amz-copy-source": "/rsrc-bkt/logs/a.txt"}, b"")
    copied = s3.dispatch(st, "GET", "/rdst-bkt/logs/c.txt")
    _check("CopyObject onto a matching key also replicates", copied.status == 200)

    # A destination that doesn't exist in this appliance is simply unreachable (no crash,
    # replication-status stays absent — same as real S3 cross-account/region destinations
    # Vyomi has no network path to).
    st2 = InMemoryObjectStore()
    st2.create_bucket("lonely-bkt", versioning="Enabled")
    rep2 = (f'<ReplicationConfiguration {NS}><Role>arn:aws:iam::123456789012:role/repl</Role>'
           '<Rule><ID>r1</ID><Status>Enabled</Status><Filter><Prefix></Prefix></Filter>'
           '<Destination><Bucket>arn:aws:s3:::ghost-bkt</Bucket></Destination></Rule>'
           '</ReplicationConfiguration>').encode()
    s3.dispatch(st2, "PUT", "/lonely-bkt", {"replication": ""}, body=rep2)
    s3.dispatch(st2, "PUT", "/lonely-bkt/x.txt", body=b"x")
    h3 = s3.dispatch(st2, "HEAD", "/lonely-bkt/x.txt")
    _check("an unreachable destination bucket leaves no replication-status claim", "x-amz-replication-status" not in h3.headers)


def run() -> int:
    _website()
    _logging()
    _request_payment()
    _id_keyed_configs()
    _replication_requires_versioning()
    _replication_enforced_on_write()
    print("\nRESULT: PASS — S3 DEPTH-pass-2 (website/logging/requester-pays/id-keyed configs/replication) holds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
