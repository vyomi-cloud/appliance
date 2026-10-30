"""S3 DEPTH pass conformance (v4 — sub-sections/config sections → real enforcement).

Proves the backend enforcement added on top of the previously config_only sub-resources:
default encryption headers, Block Public Access (ACL + policy write rejection), Object
Ownership (BucketOwnerEnforced disables ACLs), canned-ACL grants actually reflected by
GET, CORS preflight + response headers, lifecycle Expiration (Date-based, enforced lazily
on list/get/head), and Object Lock (legal hold + retention WORM enforcement).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_s3_depth_core.py
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


def _encryption():
    st = InMemoryObjectStore()
    st.create_bucket("enc-bkt")
    p = s3.dispatch(st, "PUT", "/enc-bkt/a.txt", body=b"x")
    _check("default SSE header without any PutBucketEncryption call", p.headers.get("x-amz-server-side-encryption") == "AES256")
    g = s3.dispatch(st, "GET", "/enc-bkt/a.txt")
    _check("GetObject carries SSE header", g.headers.get("x-amz-server-side-encryption") == "AES256")
    h = s3.dispatch(st, "HEAD", "/enc-bkt/a.txt")
    _check("HeadObject carries SSE header", h.headers.get("x-amz-server-side-encryption") == "AES256")

    doc = (f'<ServerSideEncryptionConfiguration {NS}><Rule><ApplyServerSideEncryptionByDefault>'
           '<SSEAlgorithm>aws:kms</SSEAlgorithm><KMSMasterKeyID>key-1</KMSMasterKeyID>'
           '</ApplyServerSideEncryptionByDefault><BucketKeyEnabled>true</BucketKeyEnabled></Rule>'
           '</ServerSideEncryptionConfiguration>').encode()
    s3.dispatch(st, "PUT", "/enc-bkt", {"encryption": ""}, body=doc)
    p2 = s3.dispatch(st, "PUT", "/enc-bkt/b.txt", body=b"y")
    _check("configured SSE-KMS algorithm reflected", p2.headers.get("x-amz-server-side-encryption") == "aws:kms")
    _check("KMS key id reflected", p2.headers.get("x-amz-server-side-encryption-aws-kms-key-id") == "key-1")
    _check("bucket-key-enabled reflected", p2.headers.get("x-amz-server-side-encryption-bucket-key-enabled") == "true")


def _public_access_block():
    st = InMemoryObjectStore()
    st.create_bucket("pab-bkt")
    pab = (f'<PublicAccessBlockConfiguration {NS}><BlockPublicAcls>true</BlockPublicAcls>'
           '<IgnorePublicAcls>false</IgnorePublicAcls><BlockPublicPolicy>true</BlockPublicPolicy>'
           '<RestrictPublicBuckets>false</RestrictPublicBuckets></PublicAccessBlockConfiguration>').encode()
    s3.dispatch(st, "PUT", "/pab-bkt", {"publicAccessBlock": ""}, body=pab)

    r = s3.dispatch(st, "PUT", "/pab-bkt", {"acl": ""}, {"x-amz-acl": "public-read"}, b"")
    _check("public-read canned ACL blocked (403)", r.status == 403 and b"AccessDenied" in r.body)
    priv = s3.dispatch(st, "PUT", "/pab-bkt", {"acl": ""}, {"x-amz-acl": "private"}, b"")
    _check("private canned ACL still allowed", priv.status == 200)

    policy = b'{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":"*","Action":"s3:GetObject","Resource":"*"}]}'
    rp = s3.dispatch(st, "PUT", "/pab-bkt", {"policy": ""}, body=policy)
    _check("public bucket policy blocked (403)", rp.status == 403 and b"AccessDenied" in rp.body)
    deny_policy = b'{"Version":"2012-10-17","Statement":[{"Effect":"Deny","Principal":"*","Action":"s3:DeleteBucket","Resource":"*"}]}'
    rd = s3.dispatch(st, "PUT", "/pab-bkt", {"policy": ""}, body=deny_policy)
    _check("a Deny-everyone policy is not treated as public", rd.status == 204)
    bad_json = s3.dispatch(st, "PUT", "/pab-bkt", {"policy": ""}, body=b"not json")
    _check("malformed policy JSON rejected (400)", bad_json.status == 400)


def _object_ownership():
    st = InMemoryObjectStore()
    st.create_bucket("own-bkt")
    s3.dispatch(st, "PUT", "/own-bkt", {"ownershipControls": ""},
               body=(f'<OwnershipControls {NS}><Rule><ObjectOwnership>BucketOwnerEnforced</ObjectOwnership>'
                     '</Rule></OwnershipControls>').encode())
    r = s3.dispatch(st, "PUT", "/own-bkt", {"acl": ""}, {"x-amz-acl": "private"}, b"")
    _check("BucketOwnerEnforced rejects any ACL write (400)", r.status == 400 and b"InvalidBucketAclWithObjectOwnership" in r.body)

    # Buckets WITHOUT an explicit ownership setting keep allowing ACL writes (no behaviour change / no regression).
    st2 = InMemoryObjectStore()
    st2.create_bucket("plain-bkt")
    r2 = s3.dispatch(st2, "PUT", "/plain-bkt", {"acl": ""}, {}, b'<AccessControlPolicy><Owner><ID>me</ID></Owner><AccessControlList/></AccessControlPolicy>')
    _check("bucket without ownershipControls still accepts ACL writes", r2.status == 200)


def _canned_acl_reflected():
    st = InMemoryObjectStore()
    st.create_bucket("acl-bkt")
    s3.dispatch(st, "PUT", "/acl-bkt", {"acl": ""}, {"x-amz-acl": "public-read"}, b"")
    g = s3.dispatch(st, "GET", "/acl-bkt", {"acl": ""}).body
    _check("canned public-read ACL grant now shows up on GetBucketAcl", b"AllUsers" in g and b"READ" in g)

    s3.dispatch(st, "PUT", "/acl-bkt/o.txt", body=b"x")
    s3.dispatch(st, "PUT", "/acl-bkt/o.txt", {"acl": ""}, {"x-amz-acl": "public-read"}, b"")
    go = s3.dispatch(st, "GET", "/acl-bkt/o.txt", {"acl": ""}).body
    _check("canned public-read object ACL grant reflected too", b"AllUsers" in go)


def _cors():
    st = InMemoryObjectStore()
    st.create_bucket("cors-bkt")
    cors = (f'<CORSConfiguration {NS}><CORSRule><AllowedOrigin>https://app.example.com</AllowedOrigin>'
            '<AllowedMethod>GET</AllowedMethod><AllowedMethod>PUT</AllowedMethod>'
            '<ExposeHeader>ETag</ExposeHeader></CORSRule></CORSConfiguration>').encode()
    s3.dispatch(st, "PUT", "/cors-bkt", {"cors": ""}, body=cors)
    s3.dispatch(st, "PUT", "/cors-bkt/x.txt", body=b"x")

    pre = s3.dispatch(st, "OPTIONS", "/cors-bkt/x.txt", {}, {"origin": "https://app.example.com", "access-control-request-method": "GET"})
    _check("preflight for an allowed origin+method succeeds", pre.status == 200)
    _check("preflight echoes the allowed origin", pre.headers.get("Access-Control-Allow-Origin") == "https://app.example.com")

    bad_pre = s3.dispatch(st, "OPTIONS", "/cors-bkt/x.txt", {}, {"origin": "https://evil.example.com", "access-control-request-method": "GET"})
    _check("preflight for a disallowed origin is forbidden", bad_pre.status == 403)

    get = s3.dispatch(st, "GET", "/cors-bkt/x.txt", {}, {"origin": "https://app.example.com"})
    _check("actual GET carries Access-Control-Allow-Origin when Origin matches a rule", get.headers.get("Access-Control-Allow-Origin") == "https://app.example.com")
    _check("actual GET carries the rule's Expose-Headers", get.headers.get("Access-Control-Expose-Headers") == "ETag")

    get_plain = s3.dispatch(st, "GET", "/cors-bkt/x.txt")
    _check("no Origin header → no CORS headers added", "Access-Control-Allow-Origin" not in get_plain.headers)


def _lifecycle_expiration():
    st = InMemoryObjectStore()
    st.create_bucket("lc-bkt")
    lc = (f'<LifecycleConfiguration {NS}><Rule><ID>r1</ID><Status>Enabled</Status>'
          '<Filter><Prefix>logs/</Prefix></Filter><Expiration><Date>2020-01-01T00:00:00.000Z</Date>'
          '</Expiration></Rule></LifecycleConfiguration>').encode()
    s3.dispatch(st, "PUT", "/lc-bkt", {"lifecycle": ""}, body=lc)
    s3.dispatch(st, "PUT", "/lc-bkt/logs/a.txt", body=b"log line")
    s3.dispatch(st, "PUT", "/lc-bkt/keep/b.txt", body=b"keep me")

    listing = s3.dispatch(st, "GET", "/lc-bkt", {"list-type": "2"}).body
    _check("past-Date Expiration removes the matching (prefixed) key", b"<Key>logs/a.txt</Key>" not in listing)
    _check("a key outside the rule's prefix survives", b"<Key>keep/b.txt</Key>" in listing)
    got = s3.dispatch(st, "GET", "/lc-bkt/logs/a.txt")
    _check("expired key reads as gone (404)", got.status == 404)

    # Versioned bucket: Expiration inserts a delete marker rather than destroying history.
    st2 = InMemoryObjectStore()
    st2.create_bucket("lcv-bkt", versioning="Enabled")
    s3.dispatch(st2, "PUT", "/lcv-bkt", {"lifecycle": ""}, body=lc)
    s3.dispatch(st2, "PUT", "/lcv-bkt/logs/a.txt", body=b"v1")
    s3.dispatch(st2, "GET", "/lcv-bkt", {"list-type": "2"})  # triggers the lazy sweep
    versions = s3.dispatch(st2, "GET", "/lcv-bkt", {"versions": "", "prefix": "logs/"}).body
    _check("versioned bucket: expiration adds a delete marker, keeps the version", b"<DeleteMarker>" in versions and b"<Version>" in versions)


def _object_lock():
    st = InMemoryObjectStore()
    st.create_bucket("lock-bkt")  # created WITHOUT object-lock
    nolock = s3.dispatch(st, "GET", "/lock-bkt", {"object-lock": ""})
    _check("GetObjectLockConfiguration 404 when the bucket wasn't created with it enabled", nolock.status == 404)
    cant_enable = s3.dispatch(st, "PUT", "/lock-bkt", {"object-lock": ""}, body=b"<x/>")
    _check("can't retroactively enable Object Lock (409)", cant_enable.status == 409)

    st2 = InMemoryObjectStore()
    st2.create_bucket("lockon-bkt", versioning="Enabled")
    st2.buckets["lockon-bkt"]["object_lock"] = True
    vid = s3.dispatch(st2, "PUT", "/lockon-bkt/secret.txt", body=b"v1").headers["x-amz-version-id"]
    enabled = s3.dispatch(st2, "GET", "/lockon-bkt", {"object-lock": ""})
    _check("GetObjectLockConfiguration 200 Enabled when set at creation", enabled.status == 200 and b"<ObjectLockEnabled>Enabled</ObjectLockEnabled>" in enabled.body)

    s3.dispatch(st2, "PUT", "/lockon-bkt/secret.txt", {"legal-hold": ""}, body=f'<LegalHold {NS}><Status>ON</Status></LegalHold>'.encode())
    lh = s3.dispatch(st2, "GET", "/lockon-bkt/secret.txt", {"legal-hold": ""})
    _check("legal hold round-trips ON", b"<Status>ON</Status>" in lh.body)
    del_blocked = s3.dispatch(st2, "DELETE", "/lockon-bkt/secret.txt", {"versionId": vid})
    _check("DELETE of a specific version under legal hold is rejected (403)", del_blocked.status == 403)
    s3.dispatch(st2, "PUT", "/lockon-bkt/secret.txt", {"legal-hold": ""}, body=f'<LegalHold {NS}><Status>OFF</Status></LegalHold>'.encode())

    far_future = "2099-01-01T00:00:00.000Z"
    s3.dispatch(st2, "PUT", "/lockon-bkt/secret.txt", {"retention": ""},
               body=f'<Retention {NS}><Mode>GOVERNANCE</Mode><RetainUntilDate>{far_future}</RetainUntilDate></Retention>'.encode())
    blocked = s3.dispatch(st2, "DELETE", "/lockon-bkt/secret.txt", {"versionId": vid})
    _check("GOVERNANCE retention blocks delete without a bypass header", blocked.status == 403)
    bypassed = s3.dispatch(st2, "DELETE", "/lockon-bkt/secret.txt", {"versionId": vid}, {"x-amz-bypass-governance-retention": "true"})
    _check("GOVERNANCE retention delete succeeds with the bypass header", bypassed.status == 204)

    vid2 = s3.dispatch(st2, "PUT", "/lockon-bkt/compliant.txt", body=b"v1").headers["x-amz-version-id"]
    s3.dispatch(st2, "PUT", "/lockon-bkt/compliant.txt", {"retention": ""},
               body=f'<Retention {NS}><Mode>COMPLIANCE</Mode><RetainUntilDate>{far_future}</RetainUntilDate></Retention>'.encode())
    never = s3.dispatch(st2, "DELETE", "/lockon-bkt/compliant.txt", {"versionId": vid2}, {"x-amz-bypass-governance-retention": "true"})
    _check("COMPLIANCE retention blocks delete even with the bypass header", never.status == 403)


def run() -> int:
    _encryption()
    _public_access_block()
    _object_ownership()
    _canned_acl_reflected()
    _cors()
    _lifecycle_expiration()
    _object_lock()
    print("\nRESULT: PASS — S3 DEPTH-pass enforcement (encryption/PAB/ownership/ACL/CORS/lifecycle/object-lock) holds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
