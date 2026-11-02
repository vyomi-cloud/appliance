"""S3 sweep S3-1 — account Block Public Access (enforced), directory buckets (S3 Express One
Zone), Object Lambda Access Points (control plane + GetObject through a real Lambda).

Run: PYTHONPATH=. python3 tests/conformance/test_s3_sweeps3_core.py
"""
import base64
import json

from core.aws_wire_router import AwsWireRouter

S3 = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0"
EXPRESS = S3.replace("/s3/", "/s3express/")
H = {"x-amz-account-id": "123456789012"}
CTL = 'xmlns="http://awss3control.amazonaws.com/doc/2016-08-20/"'


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def s3(r, method, path, query=None, body=b"", headers=None, auth=S3):
    return r.handle(method, path, query or {}, {"authorization": auth, **(headers or {})}, body)


PAB = lambda **kw: ("<PublicAccessBlockConfiguration %s>" % CTL + "".join(f"<{k}>{str(v).lower()}</{k}>" for k, v in kw.items()) + "</PublicAccessBlockConfiguration>").encode()


def account_pab():
    r = AwsWireRouter()
    p = "/v20180820/configuration/publicAccessBlock"
    _check("no account PAB -> NoSuchPublicAccessBlockConfiguration", s3(r, "GET", p, headers=H)["status"] == 404)
    _check("empty PUT rejected", s3(r, "PUT", p, body=PAB(), headers=H)["status"] == 400)
    _check("non-boolean rejected", s3(r, "PUT", p, body=b"<PublicAccessBlockConfiguration><BlockPublicAcls>maybe</BlockPublicAcls></PublicAccessBlockConfiguration>", headers=H)["status"] == 400)
    _check("wrong account id", s3(r, "GET", p, headers={"x-amz-account-id": "111111111111"})["status"] == 403)
    s3(r, "PUT", "/pab-b")
    pol = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::pab-b/*"}]}).encode()
    _check("public ACL allowed before account BPA", s3(r, "PUT", "/pab-b", {"acl": ""}, headers={"x-amz-acl": "public-read"})["status"] == 200)
    _check("PutAccountPAB", s3(r, "PUT", p, body=PAB(BlockPublicAcls=True, BlockPublicPolicy=True), headers=H)["status"] == 200)
    got = s3(r, "GET", p, headers=H)["body"]
    _check("GetAccountPAB round-trips (unset toggles false)", b"<BlockPublicAcls>true</BlockPublicAcls>" in got and b"<IgnorePublicAcls>false</IgnorePublicAcls>" in got)
    denied = s3(r, "PUT", "/pab-b", {"acl": ""}, headers={"x-amz-acl": "public-read"})
    _check("account BPA overrides: public ACL denied", denied["status"] == 403 and b"account owner enforced" in denied["body"])
    _check("account BPA overrides: public bucket policy denied", s3(r, "PUT", "/pab-b", {"policy": ""}, body=pol)["status"] in (403, 400))
    s3(r, "PUT", "/pab-c")
    _check("upload-time public ACL denied by account BPA", s3(r, "PUT", "/pab-c/o", headers={"x-amz-acl": "public-read"}, body=b"x")["status"] == 403)
    _check("bucket without BPA still blocked (effective = bucket OR account)", s3(r, "GET", "/pab-c", {"publicAccessBlock": ""})["status"] == 404)
    _check("DeleteAccountPAB", s3(r, "DELETE", p, headers=H)["status"] == 204)
    _check("deleted -> 404 again", s3(r, "GET", p, headers=H)["status"] == 404)
    _check("public ACL allowed again after delete", s3(r, "PUT", "/pab-b", {"acl": ""}, headers={"x-amz-acl": "public-read"})["status"] == 200)
    _check("state is a public attr (Nano snapshot) ", "account" in vars(r.s3))


def _dir_body(zone="usw2-az1", typ="Directory"):
    return (f"<CreateBucketConfiguration><Location><Name>{zone}</Name><Type>AvailabilityZone</Type></Location>"
            f"<Bucket><DataRedundancy>SingleAvailabilityZone</DataRedundancy><Type>{typ}</Type></Bucket></CreateBucketConfiguration>").encode()


def directory_buckets():
    r = AwsWireRouter()
    n = "exp-data--usw2-az1--x-s3"
    _check("directory name without configuration rejected", s3(r, "PUT", f"/{n}")["status"] == 400)
    _check("bad directory name rejected", s3(r, "PUT", "/bad--name--x-s3", body=_dir_body())["status"] == 400 and b"InvalidBucketName" in s3(r, "PUT", "/bad--name--x-s3", body=_dir_body())["body"])
    _check("Location.Name must match the zone in the name", s3(r, "PUT", f"/{n}", body=_dir_body("usw2-az2"))["status"] == 400)
    _check("Directory type on a general-purpose name rejected", s3(r, "PUT", "/plain-bucket", body=_dir_body())["status"] == 400)
    _check("CreateBucket directory", s3(r, "PUT", f"/{n}", body=_dir_body())["status"] == 200)
    _check("duplicate -> BucketAlreadyOwnedByYou", s3(r, "PUT", f"/{n}", body=_dir_body())["status"] == 409)
    s3(r, "PUT", "/general-one")
    lb = s3(r, "GET", "/")["body"]
    _check("ListBuckets excludes directory buckets", b"general-one" in lb and n.encode() not in lb)
    ld = s3(r, "GET", "/", auth=EXPRESS)["body"]
    _check("ListDirectoryBuckets lists only directory buckets", n.encode() in ld and b"general-one" not in ld and b"<BucketRegion>us-west-2" in ld)
    s3(r, "PUT", "/zzz-more--use1-az4--x-s3", body=_dir_body("use1-az4"))
    pg = s3(r, "GET", "/", {"max-directory-buckets": "1"}, auth=EXPRESS)["body"]
    _check("ListDirectoryBuckets paginates", b"ContinuationToken" in pg)
    nxt = s3(r, "GET", "/", {"max-directory-buckets": "1", "continuation-token": "exp-data--usw2-az1--x-s3"}, auth=EXPRESS)["body"]
    _check("page 2 returns the rest", b"zzz-more" in nxt and b"ContinuationToken" not in nxt)
    cs = s3(r, "GET", f"/{n}", {"session": ""}, headers={"x-amz-create-session-mode": "ReadWrite"})
    _check("CreateSession returns credentials", cs["status"] == 200 and b"<SessionToken>" in cs["body"] and b"<AccessKeyId>ASIA" in cs["body"])
    _check("CreateSession on a general bucket rejected", s3(r, "GET", "/general-one", {"session": ""})["status"] == 400)
    _check("CreateSession on missing bucket", s3(r, "GET", "/nope--use1-az4--x-s3", {"session": ""})["status"] == 404)
    _check("object PUT", s3(r, "PUT", f"/{n}/dir/a.txt", body=b"express")["status"] == 200)
    g = s3(r, "GET", f"/{n}/dir/a.txt")
    _check("object GET round-trips", g["status"] == 200 and g["body"] == b"express")
    _check("storage class is EXPRESS_ONEZONE", s3(r, "HEAD", f"/{n}/dir/a.txt")["headers"].get("x-amz-storage-class") == "EXPRESS_ONEZONE")
    _check("other storage class rejected", s3(r, "PUT", f"/{n}/b", headers={"x-amz-storage-class": "STANDARD_IA"}, body=b"x")["status"] == 400)
    _check("ACLs rejected on directory buckets", s3(r, "PUT", f"/{n}/b", headers={"x-amz-acl": "private"}, body=b"x")["status"] == 501)
    _check("versioning rejected", s3(r, "PUT", f"/{n}", {"versioning": ""}, body=b"<VersioningConfiguration><Status>Enabled</Status></VersioningConfiguration>")["status"] == 501)
    _check("ListObjectsV1 rejected", s3(r, "GET", f"/{n}")["status"] == 400)
    _check("non-slash delimiter rejected", s3(r, "GET", f"/{n}", {"list-type": "2", "delimiter": "-"})["status"] == 400)
    lo = s3(r, "GET", f"/{n}", {"list-type": "2", "prefix": "dir/"})["body"]
    _check("ListObjectsV2", b"dir/a.txt" in lo)
    _check("delete non-empty -> BucketNotEmpty", s3(r, "DELETE", f"/{n}")["status"] == 409)
    s3(r, "DELETE", f"/{n}/dir/a.txt")
    _check("delete object then bucket", s3(r, "DELETE", f"/{n}")["status"] == 204)
    _check("gone from ListDirectoryBuckets", n.encode() not in s3(r, "GET", "/", auth=EXPRESS)["body"])


def _lambda(r, name, src):
    out = r.handle("POST", "/2015-03-31/functions", {}, {"authorization": S3.replace("/s3/", "/lambda/")},
                   json.dumps({"FunctionName": name, "Code": {"Source": src}}).encode())
    assert out["status"] in (200, 201), out


def _olap_body(sup, fn, actions=("GetObject",), features=()):
    acts = "".join(f"<Action>{a}</Action>" for a in actions)
    feats = "".join(f"<AllowedFeature>{f}</AllowedFeature>" for f in features)
    return (f'<CreateAccessPointForObjectLambdaRequest {CTL}><Configuration><SupportingAccessPoint>{sup}</SupportingAccessPoint>'
            f"<CloudWatchMetricsEnabled>true</CloudWatchMetricsEnabled><AllowedFeatures>{feats}</AllowedFeatures>"
            f"<TransformationConfigurations><TransformationConfiguration><Actions>{acts}</Actions><ContentTransformation><AwsLambda>"
            f"<FunctionArn>{fn}</FunctionArn><FunctionPayload>hello</FunctionPayload></AwsLambda></ContentTransformation>"
            f"</TransformationConfiguration></TransformationConfigurations></Configuration></CreateAccessPointForObjectLambdaRequest>").encode()


def object_lambda_access_points():
    r = AwsWireRouter()
    P = "/v20180820/accesspointforobjectlambda"
    SUP = "arn:aws:s3:us-east-1:123456789012:accesspoint/sup-ap"
    FN = "arn:aws:lambda:us-east-1:123456789012:function:upper-fn"
    s3(r, "PUT", "/olap-bkt")
    s3(r, "PUT", "/olap-bkt/doc.txt", body=b"hello world")
    ni = s3(r, "PUT", f"{P}/my-olap", body=_olap_body(SUP, FN), headers=H)
    _check("supporting access point must exist", ni["status"] == 400)
    s3(r, "PUT", "/v20180820/accesspoint/sup-ap", body=f'<CreateAccessPointRequest {CTL}><Bucket>olap-bkt</Bucket></CreateAccessPointRequest>'.encode(), headers=H)
    _check("bad Lambda ARN rejected", s3(r, "PUT", f"{P}/my-olap", body=_olap_body(SUP, "not-an-arn"), headers=H)["status"] == 400)
    _check("bad action rejected", s3(r, "PUT", f"{P}/my-olap", body=_olap_body(SUP, FN, ("PutObject",)), headers=H)["status"] == 400)
    c = s3(r, "PUT", f"{P}/my-olap", body=_olap_body(SUP, FN, features=("GetObject-Range",)), headers=H)
    _check("CreateAccessPointForObjectLambda", c["status"] == 200 and b"s3-object-lambda" in c["body"] and b"--ol-s3" in c["body"])
    alias = c["body"].decode().split("<Value>")[1].split("</Value>")[0]
    _check("duplicate name rejected", s3(r, "PUT", f"{P}/my-olap", body=_olap_body(SUP, FN), headers=H)["status"] == 409)
    _check("name clash with a standard access point rejected", s3(r, "PUT", f"{P}/sup-ap", body=_olap_body(SUP, FN), headers=H)["status"] == 409)
    _check("List", b"my-olap" in s3(r, "GET", P, headers=H)["body"])
    _check("Get", b"<Name>my-olap</Name>" in s3(r, "GET", f"{P}/my-olap", headers=H)["body"])
    cfg = s3(r, "GET", f"{P}/my-olap/configuration", headers=H)["body"]
    _check("GetConfiguration round-trips", FN.encode() in cfg and b"GetObject-Range" in cfg and SUP.encode() in cfg)
    _check("PutConfiguration", s3(r, "PUT", f"{P}/my-olap/configuration", body=_olap_body(SUP, FN, features=("GetObject-Range", "GetObject-PartNumber")), headers=H)["status"] == 200)
    _check("policy 404 before set", s3(r, "GET", f"{P}/my-olap/policy", headers=H)["status"] == 404)
    pol = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::123456789012:root"}, "Action": "s3-object-lambda:GetObject", "Resource": "*"}]})
    _check("PutPolicy", s3(r, "PUT", f"{P}/my-olap/policy", body=f'<PutAccessPointPolicyForObjectLambdaRequest {CTL}><Policy>{pol}</Policy></PutAccessPointPolicyForObjectLambdaRequest>'.replace("<Policy>{", "<Policy>{").encode(), headers=H)["status"] == 200)
    _check("PolicyStatus not public", b"<IsPublic>false</IsPublic>" in s3(r, "GET", f"{P}/my-olap/policyStatus", headers=H)["body"])
    # data path: no Lambda yet
    miss = s3(r, "GET", f"/{alias}/doc.txt")
    _check("missing Lambda -> 500 InternalError", miss["status"] == 500)
    _lambda(r, "upper-fn", "def handler(event, ctx):\n"
            "    import base64\n"
            "    src = base64.b64decode(event['getObjectContext']['vyomiInputBase64']).decode()\n"
            "    return {'statusCode': 200, 'body': src.upper() + '|' + event['configuration']['payload'], 'headers': {'content-type': 'text/shouty'}}\n")
    g = s3(r, "GET", f"/{alias}/doc.txt")
    _check("GetObject via OLAP alias runs the Lambda", g["status"] == 200 and g["body"] == b"HELLO WORLD|hello")
    arn = "arn:aws:s3-object-lambda:us-east-1:123456789012:accesspoint/my-olap"
    _check("GetObject via OLAP ARN", s3(r, "GET", f"/{arn}/doc.txt")["body"] == b"HELLO WORLD|hello")
    _check("bucket itself untouched", s3(r, "GET", "/olap-bkt/doc.txt")["body"] == b"hello world")
    _check("missing key -> NoSuchKey (no Lambda call)", s3(r, "GET", f"/{alias}/nope.txt")["status"] == 404)
    _check("PUT through OLAP unsupported", s3(r, "PUT", f"/{alias}/x", body=b"1")["status"] == 400)
    _check("Range allowed when enabled", s3(r, "GET", f"/{alias}/doc.txt", headers={"range": "bytes=0-3"})["status"] in (200, 206))
    s3(r, "PUT", f"{P}/my-olap/configuration", body=_olap_body(SUP, FN), headers=H)
    _check("Range rejected when feature not allowed", s3(r, "GET", f"/{alias}/doc.txt", headers={"range": "bytes=0-3"})["status"] == 400)
    _lambda(r, "bad-fn", "def handler(event, ctx):\n    raise ValueError('boom')\n")
    s3(r, "PUT", f"{P}/bad-olap", body=_olap_body(SUP, "arn:aws:lambda:us-east-1:123456789012:function:bad-fn"), headers=H)
    ba = s3(r, "GET", f"{P}/bad-olap", headers=H)["body"].decode().split("<Value>")[1].split("</Value>")[0]
    bad = s3(r, "GET", f"/{ba}/doc.txt")
    _check("Lambda error surfaces as 500 with the message", bad["status"] == 500 and b"boom" in bad["body"])
    s3(r, "PUT", f"{P}/head-olap", body=_olap_body(SUP, FN, ("HeadObject",)), headers=H)
    ha = s3(r, "GET", f"{P}/head-olap", headers=H)["body"].decode().split("<Value>")[1].split("</Value>")[0]
    _check("HeadObject-only OLAP: GET has no transformation -> 400", s3(r, "GET", f"/{ha}/doc.txt")["status"] == 400)
    _check("HEAD transformation honestly NotImplemented", s3(r, "HEAD", f"/{ha}/doc.txt")["status"] == 501)
    _check("Delete", s3(r, "DELETE", f"{P}/my-olap", headers=H)["status"] == 204)
    _check("deleted -> 404", s3(r, "GET", f"{P}/my-olap", headers=H)["status"] == 404)
    _check("deleted alias no longer transforms (plain NoSuchBucket)", s3(r, "GET", f"/{alias}/doc.txt")["status"] == 404)


def run():
    account_pab()
    directory_buckets()
    object_lambda_access_points()
    print("\nRESULT: PASS - S3 sweep S3-1")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
