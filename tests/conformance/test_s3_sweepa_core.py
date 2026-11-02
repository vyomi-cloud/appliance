"""S3 sweep A — EventBridge notifications, CloudWatch storage + replication metrics,
S3 Access Points (s3control), upload-time ACLs.

Run: PYTHONPATH=. python3 tests/conformance/test_s3_sweepa_core.py
"""
import json
import time

from core.aws_wire_router import AwsWireRouter

NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'
S3 = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def s3(r, method, path, query=None, body=b"", headers=None):
    h = {"authorization": S3, **(headers or {})}
    return r.handle(method, path, query or {}, h, body)


def aws_json(r, svc, target, payload, ver="1.1"):
    h = {"authorization": S3.replace("/s3/", f"/{svc}/"), "x-amz-target": target,
         "content-type": f"application/x-amz-json-{ver}"}
    out = r.handle("POST", "/", {}, h, json.dumps(payload).encode())
    b = out.get("body") or b""
    return out["status"], json.loads(b or b"{}")


def eventbridge_notifications():
    r = AwsWireRouter()
    s3(r, "PUT", "/eb-bkt")
    st, _ = aws_json(r, "events", "AWSEvents.PutRule", {"Name": "s3-rule", "EventPattern": json.dumps(
        {"source": ["aws.s3"], "detail-type": ["Object Created"], "detail": {"bucket": {"name": ["eb-bkt"]}}})}, "1.1")
    _check("PutRule", st == 200)
    s3(r, "PUT", "/eb-bkt", {"notification": ""}, f'<NotificationConfiguration {NS}><EventBridgeConfiguration/></NotificationConfiguration>'.encode())
    got = s3(r, "GET", "/eb-bkt", {"notification": ""})
    _check("EventBridgeConfiguration round-trips", b"EventBridgeConfiguration" in got["body"])
    s3(r, "PUT", "/eb-bkt/a.txt", body=b"hi")
    log = r.events._buses_default if False else None
    from core import eventbridge_core as eb
    events = eb._buses(r.events)["default"]["event_log"]
    ev = [e for e in events if e["source"] == "aws.s3"]
    _check("PutObject publishes an Object Created event on the default bus", len(ev) == 1 and ev[0]["detail-type"] == "Object Created")
    _check("event detail carries bucket + object key", ev[0]["detail"]["bucket"]["name"] == "eb-bkt" and ev[0]["detail"]["object"]["key"] == "a.txt")
    s3(r, "DELETE", "/eb-bkt/a.txt")
    ev = [e for e in eb._buses(r.events)["default"]["event_log"] if e["source"] == "aws.s3"]
    _check("DeleteObject publishes Object Deleted", ev[-1]["detail-type"] == "Object Deleted")
    s3(r, "PUT", "/eb-bkt", {"notification": ""}, f'<NotificationConfiguration {NS}></NotificationConfiguration>'.encode())
    n = len(ev)
    s3(r, "PUT", "/eb-bkt/b.txt", body=b"x")
    _check("disabled -> no events", len([e for e in eb._buses(r.events)["default"]["event_log"] if e["source"] == "aws.s3"]) == n)


def _stat(r, ns, metric, dims, stat="Maximum"):
    st, out = aws_json(r, "monitoring", "GraniteServiceVersion20100801.GetMetricStatistics", {
        "Namespace": ns, "MetricName": metric, "Dimensions": dims, "StartTime": time.time() - 3600,
        "EndTime": time.time() + 60, "Period": 3600, "Statistics": [stat]}, "1.0")
    return st, out


def storage_metrics():
    r = AwsWireRouter()
    s3(r, "PUT", "/sm-bkt")
    s3(r, "PUT", "/sm-bkt/a", body=b"12345")
    s3(r, "PUT", "/sm-bkt/b", body=b"123")
    d = [{"Name": "BucketName", "Value": "sm-bkt"}, {"Name": "StorageType", "Value": "StandardStorage"}]
    st, out = _stat(r, "AWS/S3", "BucketSizeBytes", d)
    _check("BucketSizeBytes published", st == 200 and out["Datapoints"] and out["Datapoints"][-1]["Maximum"] == 8)
    st, out = _stat(r, "AWS/S3", "NumberOfObjects", [{"Name": "BucketName", "Value": "sm-bkt"}, {"Name": "StorageType", "Value": "AllStorageTypes"}])
    _check("NumberOfObjects published", out["Datapoints"][-1]["Maximum"] == 2)
    s3(r, "DELETE", "/sm-bkt/a")
    st, out = _stat(r, "AWS/S3", "NumberOfObjects", [{"Name": "BucketName", "Value": "sm-bkt"}, {"Name": "StorageType", "Value": "AllStorageTypes"}], "Minimum")
    _check("count follows deletes", out["Datapoints"][-1]["Minimum"] == 1)


def replication_metrics():
    r = AwsWireRouter()
    for b in ("rm-src", "rm-dst"):
        s3(r, "PUT", f"/{b}")
        s3(r, "PUT", f"/{b}", {"versioning": ""}, f'<VersioningConfiguration {NS}><Status>Enabled</Status></VersioningConfiguration>'.encode())
    doc = (f'<ReplicationConfiguration {NS}><Role>arn:aws:iam::123456789012:role/r</Role><Rule><ID>rule1</ID><Status>Enabled</Status>'
           '<Filter><Prefix></Prefix></Filter><DeleteMarkerReplication><Status>Disabled</Status></DeleteMarkerReplication>'
           '<Destination><Bucket>arn:aws:s3:::rm-dst</Bucket><Metrics><Status>Enabled</Status></Metrics></Destination></Rule></ReplicationConfiguration>')
    s3(r, "PUT", "/rm-src", {"replication": ""}, doc.encode())
    s3(r, "PUT", "/rm-src/o", body=b"data")
    d = [{"Name": "SourceBucket", "Value": "rm-src"}, {"Name": "DestinationBucket", "Value": "rm-dst"}, {"Name": "RuleId", "Value": "rule1"}]
    st, out = _stat(r, "AWS/S3", "ReplicationLatency", d)
    _check("ReplicationLatency published for a metrics-enabled rule", st == 200 and len(out["Datapoints"]) >= 1)
    _check("object really replicated", s3(r, "GET", "/rm-dst/o")["body"] == b"data")


def upload_acl():
    r = AwsWireRouter()
    s3(r, "PUT", "/acl-bkt")
    s3(r, "PUT", "/acl-bkt/pub.txt", body=b"x", headers={"x-amz-acl": "public-read"})
    acl = s3(r, "GET", "/acl-bkt/pub.txt", {"acl": ""})["body"]
    _check("PutObject x-amz-acl public-read stored as the object ACL", b"AllUsers" in acl and b"READ" in acl)
    s3(r, "PUT", "/acl-bkt/plain.txt", body=b"x")
    _check("no ACL header -> default owner-only ACL", b"AllUsers" not in s3(r, "GET", "/acl-bkt/plain.txt", {"acl": ""})["body"])
    s3(r, "PUT", "/acl-bkt/grant.txt", body=b"x", headers={"x-amz-grant-read": 'uri="http://acs.amazonaws.com/groups/global/AuthenticatedUsers"'})
    g = s3(r, "GET", "/acl-bkt/grant.txt", {"acl": ""})["body"]
    _check("x-amz-grant-read header builds a READ grant", b"AuthenticatedUsers" in g and b"READ" in g)
    bad = s3(r, "PUT", "/acl-bkt/bad.txt", body=b"x", headers={"x-amz-acl": "no-such-acl"})
    _check("unknown canned ACL rejected", bad["status"] == 400 and b"InvalidArgument" in bad["body"])
    both = s3(r, "PUT", "/acl-bkt/both.txt", body=b"x", headers={"x-amz-acl": "private", "x-amz-grant-read": 'id="a"'})
    _check("canned ACL + header grants rejected", both["status"] == 400)
    s3(r, "PUT", "/acl-bkt", {"ownershipControls": ""}, f'<OwnershipControls {NS}><Rule><ObjectOwnership>BucketOwnerEnforced</ObjectOwnership></Rule></OwnershipControls>'.encode())
    enf = s3(r, "PUT", "/acl-bkt/e.txt", body=b"x", headers={"x-amz-acl": "public-read"})
    _check("BucketOwnerEnforced rejects ACL headers", enf["status"] == 400 and b"AccessControlListNotSupported" in enf["body"])
    ok = s3(r, "PUT", "/acl-bkt/e2.txt", body=b"x", headers={"x-amz-acl": "bucket-owner-full-control"})
    _check("BucketOwnerEnforced accepts bucket-owner-full-control", ok["status"] == 200)
    s3(r, "PUT", "/acl-b2")
    s3(r, "PUT", "/acl-b2", {"publicAccessBlock": ""}, f'<PublicAccessBlockConfiguration {NS}><BlockPublicAcls>true</BlockPublicAcls></PublicAccessBlockConfiguration>'.encode())
    pab = s3(r, "PUT", "/acl-b2/p.txt", body=b"x", headers={"x-amz-acl": "public-read"})
    _check("Block Public Access refuses a public upload ACL", pab["status"] == 403)
    s3(r, "PUT", "/acl-b3")
    u = s3(r, "POST", "/acl-b3/m.bin", {"uploads": ""}, headers={"x-amz-acl": "authenticated-read"})
    import re
    uid = re.search(rb"<UploadId>(\w+)</UploadId>", u["body"]).group(1).decode()
    s3(r, "PUT", "/acl-b3/m.bin", {"partNumber": "1", "uploadId": uid}, b"abc")
    s3(r, "POST", "/acl-b3/m.bin", {"uploadId": uid}, b"<CompleteMultipartUpload><Part><PartNumber>1</PartNumber></Part></CompleteMultipartUpload>")
    _check("multipart upload keeps the creation ACL", b"AuthenticatedUsers" in s3(r, "GET", "/acl-b3/m.bin", {"acl": ""})["body"])


def access_points():
    import re
    r = AwsWireRouter()
    s3(r, "PUT", "/ap-bkt")
    H = {"x-amz-account-id": "123456789012"}
    body = f'<CreateAccessPointRequest xmlns="http://awss3control.amazonaws.com/doc/2016-08-20/"><Bucket>ap-bkt</Bucket></CreateAccessPointRequest>'.encode()
    c = s3(r, "PUT", "/v20180820/accesspoint/my-ap", body=body, headers=H)
    _check("CreateAccessPoint", c["status"] == 200 and b"accesspoint/my-ap" in c["body"])
    alias = re.search(rb"<Alias>([^<]+)</Alias>", c["body"]).group(1).decode()
    _check("alias ends with -s3alias", alias.endswith("-s3alias"))
    dup = s3(r, "PUT", "/v20180820/accesspoint/my-ap", body=body, headers=H)
    _check("duplicate -> AccessPointAlreadyOwnedByYou 409", dup["status"] == 409 and b"AccessPointAlreadyOwnedByYou" in dup["body"])
    miss = s3(r, "PUT", "/v20180820/accesspoint/other-ap", body=body.replace(b"ap-bkt", b"nope-bkt"), headers=H)
    _check("unknown bucket -> NoSuchBucket", miss["status"] == 404)
    g = s3(r, "GET", "/v20180820/accesspoint/my-ap", headers=H)
    _check("GetAccessPoint returns bucket/network origin", b"<Bucket>ap-bkt</Bucket>" in g["body"] and b"<NetworkOrigin>Internet</NetworkOrigin>" in g["body"])
    lst = s3(r, "GET", "/v20180820/accesspoint", {"bucket": "ap-bkt"}, headers=H)
    _check("ListAccessPoints filters by bucket", b"<Name>my-ap</Name>" in lst["body"])
    _check("ListAccessPoints other bucket empty", b"my-ap" not in s3(r, "GET", "/v20180820/accesspoint", {"bucket": "zzz-bkt"}, headers=H)["body"])
    s3(r, "PUT", "/ap-bkt/k.txt", body=b"via bucket")
    via = s3(r, "GET", f"/{alias}/k.txt")
    _check("object readable through the access point alias", via["status"] == 200 and via["body"] == b"via bucket")
    s3(r, "PUT", f"/{alias}/w.txt", body=b"via alias")
    _check("object written through the alias lands in the bucket", s3(r, "GET", "/ap-bkt/w.txt")["body"] == b"via alias")
    pol = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::123456789012:root"}, "Action": "s3:GetObject", "Resource": "arn:aws:s3:us-east-1:123456789012:accesspoint/my-ap/object/*"}]})
    nop = s3(r, "GET", "/v20180820/accesspoint/my-ap/policy", headers=H)
    _check("no policy -> NoSuchAccessPointPolicy", nop["status"] == 404)
    pp = s3(r, "PUT", "/v20180820/accesspoint/my-ap/policy", body=f'<PutAccessPointPolicyRequest xmlns="http://awss3control.amazonaws.com/doc/2016-08-20/"><Policy>{pol.replace("<","&lt;")}</Policy></PutAccessPointPolicyRequest>'.encode(), headers=H)
    _check("PutAccessPointPolicy", pp["status"] == 200)
    _check("GetAccessPointPolicy round-trips", b"s3:GetObject" in s3(r, "GET", "/v20180820/accesspoint/my-ap/policy", headers=H)["body"])
    _check("PolicyStatus not public", b"<IsPublic>false</IsPublic>" in s3(r, "GET", "/v20180820/accesspoint/my-ap/policyStatus", headers=H)["body"])
    ni = s3(r, "GET", "/v20180820/bucket", headers=H)     # ListRegionalBuckets (S3 on Outposts): never modelled
    _check("unmodelled s3control op -> NotImplemented 501", ni["status"] == 501 and b"NotImplemented" in ni["body"])
    d = s3(r, "DELETE", "/v20180820/accesspoint/my-ap", headers=H)
    _check("DeleteAccessPoint", d["status"] == 204)
    _check("deleted access point gone", s3(r, "GET", "/v20180820/accesspoint/my-ap", headers=H)["status"] == 404)
    _check("deleted alias no longer resolves", s3(r, "GET", f"/{alias}/k.txt")["status"] == 404)


def run():
    access_points()
    upload_acl()
    eventbridge_notifications()
    storage_metrics()
    replication_metrics()
    print("\nRESULT: PASS - S3 sweep A")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
