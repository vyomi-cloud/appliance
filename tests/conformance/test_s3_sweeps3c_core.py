"""S3 sweep S3-3 — Table buckets (S3 Tables), IAM Access Analyzer for S3 findings, Storage Lens
dashboards + groups. Everything goes through AwsWireRouter (the Nano / unified-ingress entry).

Run: PYTHONPATH=. python3 tests/conformance/test_s3_sweeps3c_core.py
"""
import json
import re

from core.aws_wire_router import AwsWireRouter

S3 = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0"
TB = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/s3tables/aws4_request, SignedHeaders=host, Signature=0"
H = {"x-amz-account-id": "123456789012"}
CTL = 'xmlns="http://awss3control.amazonaws.com/doc/2016-08-20/"'
P = "/v20180820"
ACCT = "123456789012"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def s3(r, method, path, query=None, body=b"", headers=None):
    if isinstance(body, str):
        body = body.encode()
    return r.handle(method, path, query or {}, {"authorization": S3, **(headers or {})}, body)


def ctl(r, method, path, query=None, body=b""):
    return s3(r, method, P + path, query, body, H)


def tb(r, method, path, body=None, query=None):
    out = r.handle(method, path, query or {}, {"authorization": TB}, json.dumps(body).encode() if body is not None else b"")
    out["json"] = json.loads(out["body"]) if out["body"] else {}
    return out


def vy(r, method, path, query=None):
    out = ctl(r, method, path, query)
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def mk_bucket(r, name):
    assert s3(r, "PUT", f"/{name}")["status"] == 200


# ── Table buckets ─────────────────────────────────────────────────────────────────────
def table_buckets():
    r = AwsWireRouter()
    bad = [("Ab", "short/uppercase"), ("UPPER-case", "uppercase"), ("-lead", "leading hyphen"), ("trail-", "trailing hyphen"),
           ("under_score", "underscore"), ("x" * 64, "too long"), ("amzn-s3-demo-foo", "reserved prefix"), ("foo--table-s3", "reserved suffix")]
    for n, why in bad:
        _check(f"name rule rejected: {why}", tb(r, "PUT", "/buckets", {"name": n})["status"] == 400)
    c = tb(r, "PUT", "/buckets", {"name": "lake-bucket", "tags": {"env": "dev"}})
    arn = c["json"]["arn"]
    _check("CreateTableBucket returns an s3tables ARN", c["status"] == 200 and arn == "arn:aws:s3tables:us-east-1:123456789012:bucket/lake-bucket")
    _check("duplicate name is a ConflictException", tb(r, "PUT", "/buckets", {"name": "lake-bucket"})["status"] == 409
           and tb(r, "PUT", "/buckets", {"name": "lake-bucket"})["headers"].get("x-amzn-errortype") == "ConflictException")
    g = tb(r, "GET", f"/buckets/{arn}")
    _check("GetTableBucket", g["status"] == 200 and g["json"]["name"] == "lake-bucket" and g["json"]["ownerAccountId"] == ACCT and g["json"]["tableBucketId"])
    _check("GetTableBucket on unknown -> NotFoundException", tb(r, "GET", "/buckets/arn:aws:s3tables:us-east-1:123456789012:bucket/nope")["status"] == 404)
    _check("malformed ARN -> BadRequest", tb(r, "GET", "/buckets/not-an-arn")["status"] == 400)
    tb(r, "PUT", "/buckets", {"name": "other-bucket"})
    lst = tb(r, "GET", "/buckets", query={"prefix": "lake"})["json"]["tableBuckets"]
    _check("ListTableBuckets honours prefix", [b["name"] for b in lst] == ["lake-bucket"])
    pg = tb(r, "GET", "/buckets", query={"maxBuckets": "1"})["json"]
    _check("ListTableBuckets paginates", len(pg["tableBuckets"]) == 1 and pg.get("continuationToken"))
    # policy
    _check("no policy -> NotFound", tb(r, "GET", f"/buckets/{arn}/policy")["status"] == 404)
    pol = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::123456789012:root"}, "Action": "s3tables:*", "Resource": "*"}]})
    _check("PutTableBucketPolicy rejects non-JSON", tb(r, "PUT", f"/buckets/{arn}/policy", {"resourcePolicy": "{nope"})["status"] == 400)
    _check("PutTableBucketPolicy", tb(r, "PUT", f"/buckets/{arn}/policy", {"resourcePolicy": pol})["status"] == 200)
    _check("GetTableBucketPolicy round-trips", tb(r, "GET", f"/buckets/{arn}/policy")["json"]["resourcePolicy"] == pol)
    _check("DeleteTableBucketPolicy", tb(r, "DELETE", f"/buckets/{arn}/policy")["status"] == 204 and tb(r, "GET", f"/buckets/{arn}/policy")["status"] == 404)
    # encryption
    _check("default encryption is AES256", tb(r, "GET", f"/buckets/{arn}/encryption")["json"]["encryptionConfiguration"]["sseAlgorithm"] == "AES256")
    _check("kms encryption needs a key", tb(r, "PUT", f"/buckets/{arn}/encryption", {"encryptionConfiguration": {"sseAlgorithm": "aws:kms"}})["status"] == 400)
    kms = {"sseAlgorithm": "aws:kms", "kmsKeyArn": "arn:aws:kms:us-east-1:123456789012:key/abc"}
    tb(r, "PUT", f"/buckets/{arn}/encryption", {"encryptionConfiguration": kms})
    _check("PutTableBucketEncryption round-trips", tb(r, "GET", f"/buckets/{arn}/encryption")["json"]["encryptionConfiguration"] == kms)
    tb(r, "DELETE", f"/buckets/{arn}/encryption")
    _check("DeleteTableBucketEncryption resets to AES256", tb(r, "GET", f"/buckets/{arn}/encryption")["json"]["encryptionConfiguration"]["sseAlgorithm"] == "AES256")
    # maintenance
    mc = tb(r, "GET", f"/buckets/{arn}/maintenance")["json"]["configuration"]
    _check("default bucket maintenance: unreferenced file removal enabled", mc["icebergUnreferencedFileRemoval"]["status"] == "enabled")
    _check("maintenance type validated", tb(r, "PUT", f"/buckets/{arn}/maintenance/icebergCompaction", {"value": {"status": "enabled"}})["status"] == 400)
    _check("maintenance setting range validated", tb(r, "PUT", f"/buckets/{arn}/maintenance/icebergUnreferencedFileRemoval",
                                                   {"value": {"status": "enabled", "settings": {"icebergUnreferencedFileRemoval": {"unreferencedDays": 0}}}})["status"] == 400)
    val = {"status": "enabled", "settings": {"icebergUnreferencedFileRemoval": {"unreferencedDays": 5, "nonCurrentDays": 20}}}
    _check("PutTableBucketMaintenanceConfiguration", tb(r, "PUT", f"/buckets/{arn}/maintenance/icebergUnreferencedFileRemoval", {"value": val})["status"] == 204)
    _check("GetTableBucketMaintenanceConfiguration round-trips", tb(r, "GET", f"/buckets/{arn}/maintenance")["json"]["configuration"]["icebergUnreferencedFileRemoval"] == val)
    # namespaces
    for bad_ns in (["Sales"], ["a-b"], ["_x"], ["aws_internal"], ["a", "b"], "sales"):
        _check(f"namespace rejected: {bad_ns}", tb(r, "PUT", f"/namespaces/{arn}", {"namespace": bad_ns})["status"] == 400)
    _check("CreateNamespace", tb(r, "PUT", f"/namespaces/{arn}", {"namespace": ["sales"]})["json"]["namespace"] == ["sales"])
    _check("duplicate namespace -> Conflict", tb(r, "PUT", f"/namespaces/{arn}", {"namespace": ["sales"]})["status"] == 409)
    tb(r, "PUT", f"/namespaces/{arn}", {"namespace": ["hr"]})
    _check("ListNamespaces", [n["namespace"] for n in tb(r, "GET", f"/namespaces/{arn}")["json"]["namespaces"]] == [["hr"], ["sales"]])
    _check("GetNamespace", tb(r, "GET", f"/namespaces/{arn}/sales")["json"]["namespaceId"])
    _check("GetNamespace unknown -> 404", tb(r, "GET", f"/namespaces/{arn}/zzz")["status"] == 404)
    # tables
    schema = {"iceberg": {"schema": {"fields": [{"name": "id", "type": "long", "required": True}, {"name": "amount", "type": "double"}]}}}
    _check("CreateTable needs an existing namespace", tb(r, "PUT", f"/tables/{arn}/zzz", {"name": "t", "format": "ICEBERG"})["status"] == 404)
    _check("CreateTable format must be ICEBERG", tb(r, "PUT", f"/tables/{arn}/sales", {"name": "t", "format": "DELTA"})["status"] == 400)
    _check("CreateTable table name rule", tb(r, "PUT", f"/tables/{arn}/sales", {"name": "Bad-Name", "format": "ICEBERG"})["status"] == 400)
    _check("CreateTable duplicate schema field rejected", tb(r, "PUT", f"/tables/{arn}/sales", {"name": "t", "format": "ICEBERG", "metadata": {
        "iceberg": {"schema": {"fields": [{"name": "a", "type": "int"}, {"name": "a", "type": "int"}]}}}})["status"] == 400)
    t = tb(r, "PUT", f"/tables/{arn}/sales", {"name": "orders", "format": "ICEBERG", "metadata": schema, "tags": {"t": "1"}})
    tarn, vt = t["json"]["tableARN"], t["json"]["versionToken"]
    _check("CreateTable returns tableARN + versionToken", t["status"] == 200 and re.match(rf"^{re.escape(arn)}/table/[0-9a-f-]{{36}}$", tarn) and vt)
    _check("duplicate table -> Conflict", tb(r, "PUT", f"/tables/{arn}/sales", {"name": "orders", "format": "ICEBERG"})["status"] == 409)
    gt = tb(r, "GET", "/get-table", query={"tableBucketARN": arn, "namespace": "sales", "name": "orders"})["json"]
    wh = gt["warehouseLocation"]
    wb = wh[len("s3://"):]
    _check("GetTable: warehouse s3://<uuid>--table-s3 + metadataLocation inside it", re.match(r"^s3://[0-9a-f-]{36}--table-s3$", wh) and gt["metadataLocation"].startswith(wh + "/metadata/00000-")
           and gt["format"] == "ICEBERG" and gt["namespace"] == ["sales"] and gt["versionToken"] == vt)
    _check("GetTable by tableArn", tb(r, "GET", "/get-table", query={"tableArn": tarn})["json"]["name"] == "orders")
    mkey = gt["metadataLocation"][len(wh) + 1:]
    meta = s3(r, "GET", f"/{wb}/{mkey}")
    mj = json.loads(meta["body"]) if meta["status"] == 200 else {}
    _check("initial Iceberg metadata JSON lives in the object store with the schema", mj.get("format-version") == 2 and [f["name"] for f in mj["schemas"][0]["fields"]] == ["id", "amount"]
           and mj["schemas"][0]["fields"][0]["required"] is True and mj["table-uuid"] == tarn.rsplit("/", 1)[-1])
    _check("warehouse bucket is hidden from ListBuckets", wb not in s3(r, "GET", "/")["body"].decode())
    _check("uploading a data file through S3 is visible", s3(r, "PUT", f"/{wb}/data/part-0.parquet", body=b"PAR1....")["status"] == 200
           and "data/part-0.parquet" in s3(r, "GET", f"/{wb}", {"list-type": "2", "prefix": "data/"})["body"].decode())
    _check("ListTables (namespace filter + prefix)", [x["name"] for x in tb(r, "GET", f"/tables/{arn}", query={"namespace": "sales", "prefix": "ord"})["json"]["tables"]] == ["orders"]
           and tb(r, "GET", f"/tables/{arn}", query={"namespace": "hr"})["json"]["tables"] == [])
    # metadata location CAS
    ml = tb(r, "GET", f"/tables/{arn}/sales/orders/metadata-location")["json"]
    _check("GetTableMetadataLocation", ml["versionToken"] == vt and ml["metadataLocation"] == gt["metadataLocation"] and ml["warehouseLocation"] == wh)
    new_loc = f"{wh}/metadata/00001-abc.metadata.json"
    _check("Update with a stale versionToken -> Conflict", tb(r, "PUT", f"/tables/{arn}/sales/orders/metadata-location", {"versionToken": "stale", "metadataLocation": new_loc})["status"] == 409)
    _check("Update to a location outside the warehouse -> BadRequest", tb(r, "PUT", f"/tables/{arn}/sales/orders/metadata-location", {"versionToken": vt, "metadataLocation": "s3://elsewhere/metadata/x.metadata.json"})["status"] == 400)
    _check("Update to a metadata file that does not exist -> BadRequest", tb(r, "PUT", f"/tables/{arn}/sales/orders/metadata-location", {"versionToken": vt, "metadataLocation": new_loc})["status"] == 400)
    s3(r, "PUT", f"/{wb}/metadata/00001-abc.metadata.json", body=b"{}")
    up = tb(r, "PUT", f"/tables/{arn}/sales/orders/metadata-location", {"versionToken": vt, "metadataLocation": new_loc})
    _check("UpdateTableMetadataLocation swaps the pointer and rotates the versionToken", up["status"] == 200 and up["json"]["metadataLocation"] == new_loc and up["json"]["versionToken"] != vt)
    vt = up["json"]["versionToken"]
    # table policy / maintenance
    _check("table policy lifecycle", tb(r, "GET", f"/tables/{arn}/sales/orders/policy")["status"] == 404
           and tb(r, "PUT", f"/tables/{arn}/sales/orders/policy", {"resourcePolicy": pol})["status"] == 200
           and tb(r, "GET", f"/tables/{arn}/sales/orders/policy")["json"]["resourcePolicy"] == pol
           and tb(r, "DELETE", f"/tables/{arn}/sales/orders/policy")["status"] == 204)
    tmc = tb(r, "GET", f"/tables/{arn}/sales/orders/maintenance")["json"]["configuration"]
    _check("default table maintenance has compaction + snapshot management", set(tmc) == {"icebergCompaction", "icebergSnapshotManagement"})
    comp = {"status": "enabled", "settings": {"icebergCompaction": {"targetFileSizeMB": 256, "strategy": "binpack"}}}
    _check("strategy validated", tb(r, "PUT", f"/tables/{arn}/sales/orders/maintenance/icebergCompaction", {"value": {"status": "enabled", "settings": {"icebergCompaction": {"strategy": "x"}}}})["status"] == 400)
    tb(r, "PUT", f"/tables/{arn}/sales/orders/maintenance/icebergCompaction", {"value": comp})
    tb(r, "PUT", f"/tables/{arn}/sales/orders/maintenance/icebergSnapshotManagement", {"value": {"status": "disabled"}})
    _check("table maintenance round-trips", tb(r, "GET", f"/tables/{arn}/sales/orders/maintenance")["json"]["configuration"]["icebergCompaction"] == comp)
    js = tb(r, "GET", f"/tables/{arn}/sales/orders/maintenance-job-status")["json"]["status"]
    _check("job status is honest: nothing ever ran; disabled types report Disabled", js["icebergCompaction"]["status"] == "Not_Yet_Run" and js["icebergSnapshotManagement"]["status"] == "Disabled")
    # tags
    tb(r, "POST", f"/tag/{tarn}", {"tags": {"a": "b"}})
    _check("tags on a table (create + TagResource)", tb(r, "GET", f"/tag/{tarn}")["json"]["tags"] == {"t": "1", "a": "b"})
    tb(r, "POST", f"/tag/{arn}", {"tags": {"x": "y"}})
    _check("tags on a table bucket", tb(r, "GET", f"/tag/{arn}")["json"]["tags"] == {"env": "dev", "x": "y"})
    tb(r, "DELETE", f"/tag/{tarn}", query={"tagKeys": "a"})
    _check("UntagResource", tb(r, "GET", f"/tag/{tarn}")["json"]["tags"] == {"t": "1"})
    # rename
    _check("RenameTable to an existing name -> Conflict", (tb(r, "PUT", f"/tables/{arn}/sales/orders", {"name": "x", "format": "ICEBERG"}), tb(r, "PUT", f"/tables/{arn}/sales", {"name": "orders_b", "format": "ICEBERG"}),
                                                          tb(r, "PUT", f"/tables/{arn}/sales/orders_b/rename", {"newName": "orders"}))[2]["status"] == 409)
    _check("RenameTable with a stale versionToken -> Conflict", tb(r, "PUT", f"/tables/{arn}/sales/orders/rename", {"newName": "orders2", "versionToken": "stale"})["status"] == 409)
    _check("RenameTable across namespaces", tb(r, "PUT", f"/tables/{arn}/sales/orders/rename", {"newNamespaceName": "hr", "newName": "orders2"})["status"] == 204
           and tb(r, "GET", "/get-table", query={"tableBucketARN": arn, "namespace": "hr", "name": "orders2"})["status"] == 200
           and tb(r, "GET", "/get-table", query={"tableBucketARN": arn, "namespace": "sales", "name": "orders"})["status"] == 404)
    _check("renamed table keeps its ARN and warehouse", tb(r, "GET", "/get-table", query={"tableArn": tarn})["json"]["warehouseLocation"] == wh)
    # not-empty deletes
    _check("DeleteNamespace with tables -> Conflict", tb(r, "DELETE", f"/namespaces/{arn}/hr")["status"] == 409)
    _check("DeleteTableBucket with namespaces -> Conflict", tb(r, "DELETE", f"/buckets/{arn}")["status"] == 409)
    _check("DeleteTable with a stale versionToken -> Conflict", tb(r, "DELETE", f"/tables/{arn}/hr/orders2", query={"versionToken": "stale"})["status"] == 409)
    _check("DeleteTable", tb(r, "DELETE", f"/tables/{arn}/hr/orders2")["status"] == 204 and tb(r, "GET", "/get-table", query={"tableArn": tarn})["status"] == 404)
    _check("DeleteTable removes the warehouse bucket and its files", s3(r, "GET", f"/{wb}", {"list-type": "2"})["status"] == 404)
    tb(r, "DELETE", f"/tables/{arn}/sales/orders_b")
    for ns in ("hr", "sales"):
        _check(f"DeleteNamespace {ns}", tb(r, "DELETE", f"/namespaces/{arn}/{ns}")["status"] == 204)
    _check("DeleteTableBucket", tb(r, "DELETE", f"/buckets/{arn}")["status"] == 204 and tb(r, "GET", f"/buckets/{arn}")["status"] == 404)
    _check("replication is honestly NotImplemented", tb(r, "GET", "/table-bucket-replication", query={"tableBucketARN": arn})["status"] == 501)
    _check("an unsigned/ordinary S3 bucket called 'buckets' is untouched", s3(r, "PUT", "/buckets")["status"] == 200)


# ── IAM Access Analyzer for S3 ────────────────────────────────────────────────────────
def put_policy(r, bucket, statements):
    assert s3(r, "PUT", f"/{bucket}", {"policy": ""}, json.dumps({"Version": "2012-10-17", "Statement": statements}))["status"] == 204


def findings(r, **flt):
    st, doc = vy(r, "GET", "/_vyomi/access-analysis")
    assert st == 200
    return [f for f in doc["findings"] if all(f.get(k) == v for k, v in flt.items())], doc


def access_analysis():
    r = AwsWireRouter()
    for b in ("aa-pub", "aa-x", "aa-org", "aa-vpc", "aa-self", "aa-priv"):
        mk_bucket(r, b)
    get = {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}
    put_policy(r, "aa-pub", [{**get, "Sid": "Open", "Principal": "*"}])
    put_policy(r, "aa-x", [{**get, "Principal": {"AWS": "arn:aws:iam::999999999999:role/r"}}, {**get, "Principal": {"AWS": f"arn:aws:iam::{ACCT}:root"}}])
    put_policy(r, "aa-org", [{**get, "Principal": "*", "Condition": {"StringEquals": {"aws:PrincipalOrgID": "o-abc123"}}}])
    put_policy(r, "aa-vpc", [{**get, "Principal": "*", "Condition": {"StringEquals": {"aws:SourceVpce": "vpce-1"}}}])
    put_policy(r, "aa-self", [{**get, "Principal": "*", "Condition": {"StringEquals": {"aws:SourceAccount": ACCT}}}])
    fs, doc = findings(r)
    by = {(f["resource"], f["kind"]): f for f in fs}
    _check("wildcard principal without conditions = Public (names the statement)", ("aa-pub", "Public") in by and "Sid Open" in by[("aa-pub", "Public")]["reasons"][0] and by[("aa-pub", "Public")]["via"] == "Bucket policy")
    _check("other-account principal = Shared with that account; own account is not a finding", by[("aa-x", "Shared")]["principal"] == "account:999999999999" and len([f for f in fs if f["resource"] == "aa-x"]) == 1)
    _check("aws:PrincipalOrgID narrows a wildcard to Shared with the organization", by[("aa-org", "Shared")]["principal"] == "org:o-abc123")
    _check("VPC-endpoint condition and own-account SourceAccount produce no finding", not any(f["resource"] in ("aa-vpc", "aa-self") for f in fs))
    _check("clean bucket has no finding; summary says so", not any(f["resource"] == "aa-priv" for f in fs)
           and [b for b in doc["buckets"] if b["name"] == "aa-priv"][0]["public"] is False)
    # ACL
    s3(r, "PUT", "/aa-priv", {"acl": ""}, headers={"x-amz-acl": "public-read"})
    f = findings(r, resource="aa-priv")[0]
    _check("public-read bucket ACL = Public via Bucket ACL (READ to AllUsers)", len(f) == 1 and f[0]["via"] == "Bucket ACL" and f[0]["kind"] == "Public" and "AllUsers" in f[0]["reasons"][0])
    acl = ('<AccessControlPolicy><Owner><ID>simulator</ID></Owner><AccessControlList><Grant><Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="CanonicalUser">'
           "<ID>abcdef0123</ID></Grantee><Permission>READ</Permission></Grant></AccessControlList></AccessControlPolicy>")
    s3(r, "PUT", "/aa-self", {"acl": ""}, body=acl)
    f = findings(r, resource="aa-self")[0]
    _check("ACL grant to another canonical user = Shared", len(f) == 1 and f[0]["kind"] == "Shared" and f[0]["principal"] == "canonical:abcdef0123")
    # BPA changes the result on the next read (no stale cache)
    s3(r, "PUT", "/aa-pub", {"publicAccessBlock": ""}, "<PublicAccessBlockConfiguration><RestrictPublicBuckets>true</RestrictPublicBuckets></PublicAccessBlockConfiguration>")
    fs, doc = findings(r, resource="aa-pub")
    _check("RestrictPublicBuckets removes the public policy finding and lists it as suppressed", not fs
           and "RestrictPublicBuckets" in [b for b in doc["buckets"] if b["name"] == "aa-pub"][0]["suppressed"][0])
    s3(r, "DELETE", "/aa-pub", {"publicAccessBlock": ""})
    _check("removing the BPA brings the finding back (recomputed on read)", len(findings(r, resource="aa-pub")[0]) == 1)
    s3(r, "PUT", "/aa-priv", {"publicAccessBlock": ""}, "<PublicAccessBlockConfiguration><IgnorePublicAcls>true</IgnorePublicAcls></PublicAccessBlockConfiguration>")
    _check("IgnorePublicAcls neutralises the public ACL finding", not findings(r, resource="aa-priv")[0])
    ctl(r, "PUT", "/configuration/publicAccessBlock", body=f"<PublicAccessBlockConfiguration {CTL}><RestrictPublicBuckets>true</RestrictPublicBuckets></PublicAccessBlockConfiguration>")
    _check("ACCOUNT-level Block Public Access also suppresses (shortcut target)", not findings(r, resource="aa-pub")[0] and findings(r, resource="aa-x")[0])
    ctl(r, "DELETE", "/configuration/publicAccessBlock")
    # archive / unarchive
    fid = findings(r, resource="aa-pub")[0][0]["id"]
    st, doc = vy(r, "PUT", f"/_vyomi/access-analysis/findings/{fid}/archive")
    _check("archive a finding", st == 200 and findings(r, resource="aa-pub")[0][0]["status"] == "Archived")
    st, _ = vy(r, "PUT", f"/_vyomi/access-analysis/findings/{fid}/unarchive")
    _check("unarchive a finding", st == 200 and findings(r, resource="aa-pub")[0][0]["status"] == "Active")
    vy(r, "PUT", f"/_vyomi/access-analysis/findings/{fid}/archive")
    put_policy(r, "aa-pub", [{**get, "Principal": "*"}, {**get, "Principal": {"AWS": "*"}, "Action": "s3:ListBucket"}])
    _check("a changed finding re-activates", findings(r, resource="aa-pub")[0][0]["status"] == "Active" and "s3:ListBucket" in findings(r, resource="aa-pub")[0][0]["actions"])
    vy(r, "PUT", f"/_vyomi/access-analysis/findings/{fid}/archive")
    s3(r, "DELETE", "/aa-pub", {"policy": ""})
    _check("deleting the policy resolves the finding (and its archive state)", not findings(r, resource="aa-pub")[0])
    _check("unknown finding -> 404", vy(r, "PUT", "/_vyomi/access-analysis/findings/deadbeef/archive")[0] == 404)
    # access points
    mk_bucket(r, "aa-ap")
    ctl(r, "PUT", "/accesspoint/ap-open", body=f"<CreateAccessPointRequest {CTL}><Bucket>aa-ap</Bucket><PublicAccessBlockConfiguration><RestrictPublicBuckets>false</RestrictPublicBuckets></PublicAccessBlockConfiguration></CreateAccessPointRequest>")
    pol = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": "*"}]})
    ctl(r, "PUT", "/accesspoint/ap-open/policy", body=f"<PutAccessPointPolicyRequest {CTL}><Policy>{pol.replace('&', '&amp;')}</Policy></PutAccessPointPolicyRequest>")
    f = findings(r, resource="ap-open")[0]
    _check("an internet access point with a public policy is a Public AWS::S3::AccessPoint finding", len(f) == 1 and f[0]["resourceType"] == "AWS::S3::AccessPoint" and f[0]["kind"] == "Public" and f[0]["bucket"] == "aa-ap")
    ctl(r, "PUT", "/accesspoint/ap-vpc", body=f"<CreateAccessPointRequest {CTL}><Bucket>aa-ap</Bucket><VpcConfiguration><VpcId>vpc-1</VpcId></VpcConfiguration></CreateAccessPointRequest>")
    ctl(r, "PUT", "/accesspoint/ap-vpc/policy", body=f"<PutAccessPointPolicyRequest {CTL}><Policy>{pol.replace('&', '&amp;')}</Policy></PutAccessPointPolicyRequest>")
    _check("a VPC-origin access point is not external access", not findings(r, resource="ap-vpc")[0])


# ── Storage Lens ──────────────────────────────────────────────────────────────────────
def cfg_xml(cid, extra="", enabled="true", prefix=True):
    pl = ("<PrefixLevel><StorageMetrics><IsEnabled>true</IsEnabled><SelectionCriteria><Delimiter>/</Delimiter><MaxDepth>3</MaxDepth>"
          "<MinStorageBytesPercentage>1.0</MinStorageBytesPercentage></SelectionCriteria></StorageMetrics></PrefixLevel>") if prefix else ""
    return (f"<PutStorageLensConfigurationRequest {CTL}><StorageLensConfiguration><Id>{cid}</Id><AccountLevel><BucketLevel>{pl}</BucketLevel>{extra}</AccountLevel>"
            f"<IsEnabled>{enabled}</IsEnabled></StorageLensConfiguration></PutStorageLensConfigurationRequest>")


def group_xml(name, flt, tag="CreateStorageLensGroupRequest"):
    return f"<{tag} {CTL}><StorageLensGroup><Name>{name}</Name><Filter>{flt}</Filter></StorageLensGroup></{tag}>"


def storage_lens():
    r = AwsWireRouter()
    lst = ctl(r, "GET", "/storagelens")["body"].decode()
    _check("default-account-dashboard is always listed", "<Id>default-account-dashboard</Id>" in lst and f"arn:aws:s3:us-east-1:{ACCT}:storage-lens/default-account-dashboard" in lst)
    g = ctl(r, "GET", "/storagelens/default-account-dashboard")
    _check("GetStorageLensConfiguration (default) is enabled", g["status"] == 200 and b"<IsEnabled>true</IsEnabled>" in g["body"])
    _check("default dashboard cannot be deleted", ctl(r, "DELETE", "/storagelens/default-account-dashboard")["status"] == 400)
    # fixtures
    for b in ("sl-a", "sl-b"):
        mk_bucket(r, b)
    s3(r, "PUT", "/sl-a", {"versioning": ""}, "<VersioningConfiguration><Status>Enabled</Status></VersioningConfiguration>")
    for k, n, tags in (("logs/2026/a.log", 100, "team=ops"), ("logs/2026/b.log", 300, "team=ops"), ("img/p.png", 1000, ""), ("root.txt", 10, "")):
        s3(r, "PUT", f"/sl-a/{k}", body=b"x" * n, headers={"x-amz-tagging": tags} if tags else {})
    s3(r, "PUT", "/sl-a/logs/2026/a.log", body=b"y" * 50, headers={"x-amz-tagging": "team=ops"})     # -> a 100-byte noncurrent version
    s3(r, "DELETE", "/sl-a/root.txt")                                                                   # -> delete marker + noncurrent 10
    s3(r, "PUT", "/sl-b/d/q.bin", body=b"q" * 500, headers={"x-amz-storage-class": "STANDARD_IA"})
    up = s3(r, "POST", "/sl-b/big", {"uploads": ""})["body"].decode()
    uid = re.search(r"<UploadId>([^<]+)", up).group(1)
    s3(r, "PUT", "/sl-b/big", {"uploadId": uid, "partNumber": "1"}, b"m" * 700)
    st, d = vy(r, "GET", "/_vyomi/storage-lens/default-account-dashboard")
    s = d["summary"]
    _check("dashboard totals come from the real store (current/noncurrent/markers/MPU)", st == 200 and s["currentObjects"] == 4 and s["currentBytes"] == 50 + 300 + 1000 + 500
           and s["noncurrentObjects"] == 2 and s["noncurrentBytes"] == 100 + 10 and s["deleteMarkers"] == 1 and s["incompleteMpuBytes"] == 700 and s["bucketCount"] == 2)
    _check("derived metrics: total, object count, avg size, % current", s["totalBytes"] == 1850 + 110 + 700 and s["objectCount"] == 6 and s["avgObjectBytes"] == (1850 + 110) // 6
           and abs(s["currentVersionPct"] - round(100 * 1850 / 1960, 2)) < 0.01)
    bb = {b["bucket"]: b for b in d["byBucket"]}
    _check("by bucket", bb["sl-a"]["currentBytes"] == 1350 and bb["sl-b"]["incompleteMpuBytes"] == 700 and bb["sl-b"]["bytes"] == 1200)
    sc = {c["storageClass"]: c for c in d["byStorageClass"]}
    _check("by storage class", sc["STANDARD_IA"]["bytes"] == 500 and sc["STANDARD"]["bytes"] == 1350 + 110)
    pre = {(p["bucket"], p["prefix"]): p for p in d["byPrefix"]}
    _check("by prefix (current versions, depth rollup)", pre[("sl-a", "img/")]["bytes"] == 1000 and pre[("sl-a", "logs/")]["bytes"] == 350 and pre[("sl-a", "logs/2026/")]["objects"] == 2)
    _check("activity metrics are reported as not modelled (never faked)", d["activityMetrics"]["modelled"] is False)
    _check("first read records a snapshot", len(d["trend"]) == 1 and d["trend"][0]["totalBytes"] == s["totalBytes"])
    s3(r, "PUT", "/sl-a/new.bin", body=b"n" * 1000)
    st, d2 = vy(r, "GET", "/_vyomi/storage-lens/default-account-dashboard")
    _check("same-day re-read refreshes today's snapshot (still one row, new total)", len(d2["trend"]) == 1 and d2["trend"][0]["totalBytes"] == s["totalBytes"] + 1000)
    r_state = r.s3.account["lens"]["snapshots"]["default-account-dashboard"]
    r_state[0]["date"] = "2026-01-01"
    st, d3 = vy(r, "GET", "/_vyomi/storage-lens/default-account-dashboard")
    _check("a new day appends a snapshot", len(d3["trend"]) == 2 and d3["trend"][0]["date"] == "2026-01-01")
    for i in range(40):
        r_state.insert(0, {**r_state[0], "date": f"2025-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}"})
    st, d4 = vy(r, "GET", "/_vyomi/storage-lens/default-account-dashboard")
    _check("snapshots are capped at 30", len(d4["trend"]) == 30)
    # custom config
    inc = "<Include><Buckets><Arn>arn:aws:s3:::sl-a</Arn></Buckets></Include>"
    x = cfg_xml("my-dash").replace("</StorageLensConfiguration>", f"{inc}</StorageLensConfiguration>")
    _check("id mismatch rejected", ctl(r, "PUT", "/storagelens/other-id", body=x)["status"] == 400)
    bad = cfg_xml("my-dash").replace("<MaxDepth>3", "<MaxDepth>99")
    _check("MaxDepth validated", ctl(r, "PUT", "/storagelens/my-dash", body=bad)["status"] == 400)
    both = x.replace(inc, inc + "<Exclude><Buckets><Arn>arn:aws:s3:::sl-b</Arn></Buckets></Exclude>")
    _check("Include and Exclude together rejected", ctl(r, "PUT", "/storagelens/my-dash", body=both)["status"] == 400)
    exp = x.replace("</StorageLensConfiguration>", "<DataExport><S3BucketDestination><Format>CSV</Format><OutputSchemaVersion>V_1</OutputSchemaVersion>"
                    f"<AccountId>{ACCT}</AccountId><Arn>arn:aws:s3:::missing-dest</Arn></S3BucketDestination></DataExport></StorageLensConfiguration>")
    _check("export destination bucket must exist", ctl(r, "PUT", "/storagelens/my-dash", body=exp)["status"] == 400)
    put = ctl(r, "PUT", "/storagelens/my-dash", body=x.replace("</PutStorageLensConfigurationRequest>", "<Tags><Tag><Key>team</Key><Value>fin</Value></Tag></Tags></PutStorageLensConfigurationRequest>"))
    _check("PutStorageLensConfiguration", put["status"] == 200)
    got = ctl(r, "GET", "/storagelens/my-dash")["body"].decode()
    _check("Get returns the stored document + StorageLensArn", "<Include>" in got and "sl-a" in got and f"storage-lens/my-dash</StorageLensArn>" in got)
    _check("tags set on Put are returned", "<Tags><Tag><Key>team</Key><Value>fin</Value></Tag></Tags>" in ctl(r, "GET", "/storagelens/my-dash/tagging")["body"].decode())
    ctl(r, "PUT", "/storagelens/my-dash/tagging", body=f"<PutStorageLensConfigurationTaggingRequest {CTL}><Tags><Tag><Key>k</Key><Value>v</Value></Tag></Tags></PutStorageLensConfigurationTaggingRequest>")
    _check("PutStorageLensConfigurationTagging replaces the tag set", "<Key>k</Key>" in ctl(r, "GET", "/storagelens/my-dash/tagging")["body"].decode() and "team" not in ctl(r, "GET", "/storagelens/my-dash/tagging")["body"].decode())
    arn = f"arn:aws:s3:us-east-1:{ACCT}:storage-lens/my-dash"
    ctl(r, "POST", f"/tags/{arn}", body=f"<TagResourceRequest {CTL}><Tags><Tag><Key>z</Key><Value>1</Value></Tag></Tags></TagResourceRequest>")
    _check("TagResource / ListTagsForResource on a dashboard ARN", "<Key>z</Key>" in ctl(r, "GET", f"/tags/{arn}")["body"].decode())
    ctl(r, "DELETE", f"/tags/{arn}", {"tagKeys": "z"})
    _check("UntagResource", "<Key>z</Key>" not in ctl(r, "GET", f"/tags/{arn}")["body"].decode())
    _check("List includes the custom dashboard", "<Id>my-dash</Id>" in ctl(r, "GET", "/storagelens")["body"].decode())
    st, d5 = vy(r, "GET", "/_vyomi/storage-lens/my-dash")
    _check("Include filter scopes the data to sl-a", d5["scope"]["buckets"] == ["sl-a"] and d5["summary"]["bucketCount"] == 1 and d5["summary"]["incompleteMpuBytes"] == 0)
    # groups
    g1 = group_xml("ops-logs", "<And><MatchAnyPrefix><Prefix>logs/</Prefix></MatchAnyPrefix><MatchAnyTag><Tag><Key>team</Key><Value>ops</Value></Tag></MatchAnyTag></And>")
    _check("CreateStorageLensGroup", ctl(r, "POST", "/storagelensgroup", body=g1)["status"] == 204)
    _check("duplicate group -> 409", ctl(r, "POST", "/storagelensgroup", body=g1)["status"] == 409)
    _check("group name rule", ctl(r, "POST", "/storagelensgroup", body=group_xml("bad name!", "<MatchAnyPrefix><Prefix>a</Prefix></MatchAnyPrefix>"))["status"] == 400)
    _check("age bounds must be consistent", ctl(r, "POST", "/storagelensgroup", body=group_xml("g-age", "<MatchObjectAge><DaysGreaterThan>10</DaysGreaterThan><DaysLessThan>5</DaysLessThan></MatchObjectAge>"))["status"] == 400)
    _check("filter needs exactly one of single/And/Or", ctl(r, "POST", "/storagelensgroup", body=group_xml("g-two", "<MatchAnyPrefix><Prefix>a</Prefix></MatchAnyPrefix><MatchAnySuffix><Suffix>b</Suffix></MatchAnySuffix>"))["status"] == 400)
    ctl(r, "POST", "/storagelensgroup", body=group_xml("big-or-png", "<Or><MatchObjectSize><BytesGreaterThan>900</BytesGreaterThan></MatchObjectSize><MatchAnySuffix><Suffix>.bin</Suffix></MatchAnySuffix></Or>"))
    gg = ctl(r, "GET", "/storagelensgroup/ops-logs")["body"].decode()
    _check("GetStorageLensGroup returns the filter and the ARN", "<And>" in gg and "<Prefix>logs/</Prefix>" in gg and f"storage-lens-group/ops-logs" in gg)
    _check("ListStorageLensGroups", ctl(r, "GET", "/storagelensgroup")["body"].decode().count("<Name>") == 2)
    _check("UpdateStorageLensGroup", ctl(r, "PUT", "/storagelensgroup/big-or-png", body=group_xml("big-or-png", "<Or><MatchObjectSize><BytesGreaterThan>900</BytesGreaterThan></MatchObjectSize><MatchAnySuffix><Suffix>.bin</Suffix></MatchAnySuffix></Or>", "UpdateStorageLensGroupRequest"))["status"] == 204
           and ctl(r, "PUT", "/storagelensgroup/ghost", body=group_xml("ghost", "<MatchAnyPrefix><Prefix>a</Prefix></MatchAnyPrefix>", "UpdateStorageLensGroupRequest"))["status"] == 404)
    gl = ",".join(f"<Arn>arn:aws:s3:us-east-1:{ACCT}:storage-lens-group/{n}</Arn>" for n in ("ops-logs", "big-or-png"))
    gx = cfg_xml("grp-dash", extra=f"<StorageLensGroupLevel><SelectionCriteria><Include>{gl}</Include></SelectionCriteria></StorageLensGroupLevel>")
    _check("a dashboard may only select existing groups", ctl(r, "PUT", "/storagelens/grp-dash", body=gx.replace("ops-logs", "nope"))["status"] == 400)
    _check("PUT dashboard with group-level selection", ctl(r, "PUT", "/storagelens/grp-dash", body=gx)["status"] == 200)
    st, d6 = vy(r, "GET", "/_vyomi/storage-lens/grp-dash")
    bg = {g["group"]: g for g in d6["byGroup"]}
    _check("group filters applied to the data (And: prefix+tag; Or: size>900 | .bin)", bg["ops-logs"]["objects"] == 2 and bg["ops-logs"]["bytes"] == 50 + 300
           and bg["big-or-png"]["objects"] == 3 and bg["big-or-png"]["bytes"] == 1000 + 1000 + 500)
    st, d7 = vy(r, "GET", "/_vyomi/storage-lens/default-account-dashboard", {"group": "ops-logs"})
    pre = {(p["bucket"], p["prefix"]): p for p in d7["byPrefix"]}
    _check("a group applied as a filter narrows prefix-level aggregation", d7["summary"]["currentObjects"] == 2 and d7["summary"]["currentBytes"] == 350 and list(pre) == [("sl-a", "logs/"), ("sl-a", "logs/2026/")]
           or sorted(pre) == [("sl-a", "logs/"), ("sl-a", "logs/2026/")])
    _check("unknown group filter -> 404", vy(r, "GET", "/_vyomi/storage-lens/grp-dash", {"group": "zz"})[0] == 404)
    gtag = f"arn:aws:s3:us-east-1:{ACCT}:storage-lens-group/ops-logs"
    ctl(r, "POST", f"/tags/{gtag}", body=f"<TagResourceRequest {CTL}><Tags><Tag><Key>o</Key><Value>1</Value></Tag></Tags></TagResourceRequest>")
    _check("tags on a group ARN", "<Key>o</Key>" in ctl(r, "GET", f"/tags/{gtag}")["body"].decode())
    _check("DeleteStorageLensGroup", ctl(r, "DELETE", "/storagelensgroup/ops-logs")["status"] == 204 and ctl(r, "GET", "/storagelensgroup/ops-logs")["status"] == 404)
    _check("DeleteStorageLensConfiguration", ctl(r, "DELETE", "/storagelens/my-dash")["status"] == 204 and ctl(r, "GET", "/storagelens/my-dash")["status"] == 404
           and vy(r, "GET", "/_vyomi/storage-lens/my-dash")[0] == 404)
    # persistence round-trip: the state is plain data on the store
    json.dumps(r.s3.account, default=str)
    _check("Storage Lens state is plain JSON-able data on store.account (persists with the buckets)", "lens" in r.s3.account)


if __name__ == "__main__":
    for fn in (table_buckets, access_analysis, storage_lens):
        print(fn.__name__)
        fn()
    print("OK")
