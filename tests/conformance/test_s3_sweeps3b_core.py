"""S3 sweep S3-2 — Multi-Region Access Points, Access Grants (with enforced GetDataAccess
credentials) and Batch Operations (jobs really executed against the store).

Run: PYTHONPATH=. python3 tests/conformance/test_s3_sweeps3b_core.py
"""
import json
import re

from core.aws_wire_router import AwsWireRouter

S3 = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0"
H = {"x-amz-account-id": "123456789012"}
CTL = 'xmlns="http://awss3control.amazonaws.com/doc/2016-08-20/"'
ROLE = "arn:aws:iam::123456789012:role/batch-role"
P = "/v20180820"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def s3(r, method, path, query=None, body=b"", headers=None, auth=S3):
    if isinstance(body, str):
        body = body.encode()
    return r.handle(method, path, query or {}, {"authorization": auth, **(headers or {})}, body)


def ctl(r, method, path, query=None, body=b"", headers=None):
    return s3(r, method, P + path, query, body, {**H, **(headers or {})})


def tag(text, name):
    m = re.search(rf"<{name}>([^<]*)</{name}>", text)
    return m.group(1) if m else ""


def mk_bucket(r, name, region="us-east-1"):
    body = "" if region == "us-east-1" else f"<CreateBucketConfiguration><LocationConstraint>{region}</LocationConstraint></CreateBucketConfiguration>"
    assert s3(r, "PUT", f"/{name}", body=body)["status"] == 200


# ── Multi-Region Access Points ────────────────────────────────────────────────────────
def _mrap_create(r, name, buckets):
    regs = "".join(f"<Region><Bucket>{b}</Bucket></Region>" for b in buckets)
    return ctl(r, "POST", "/async-requests/mrap/create",
               body=f"<CreateMultiRegionAccessPointInput {CTL}><ClientToken>t{name}</ClientToken><Details><Name>{name}</Name><Regions>{regs}</Regions></Details></CreateMultiRegionAccessPointInput>")


def multi_region_access_points():
    r = AwsWireRouter()
    mk_bucket(r, "mr-use1")
    mk_bucket(r, "mr-euw1", "eu-west-1")
    mk_bucket(r, "mr-use1-b")
    _check("same-region buckets rejected", _mrap_create(r, "bad-mrap", ["mr-use1", "mr-use1-b"])["status"] == 400)
    _check("missing bucket rejected", _mrap_create(r, "bad-mrap", ["mr-use1", "nope-bkt"])["status"] == 404)
    _check("bad name rejected", _mrap_create(r, "X", ["mr-use1"])["status"] == 400)
    c = _mrap_create(r, "my-mrap", ["mr-use1", "mr-euw1"])
    ctext = c["body"].decode()
    tok = tag(ctext, "RequestTokenARN")
    _check("CreateMultiRegionAccessPoint returns a RequestTokenARN", c["status"] == 200 and "async-request/mrap/create/" in tok)
    d = ctl(r, "GET", f"/async-requests/mrap/{tok}")
    _check("DescribeMultiRegionAccessPointOperation reports SUCCEEDED with the create parameters",
           d["status"] == 200 and b"<RequestStatus>SUCCEEDED</RequestStatus>" in d["body"] and b"<Name>my-mrap</Name>" in d["body"] and b"eu-west-1" in d["body"])
    _check("unknown token 404", ctl(r, "GET", "/async-requests/mrap/arn:aws:s3:us-west-2:123456789012:async-request/mrap/create/zzz")["status"] == 404)
    _check("duplicate name rejected", _mrap_create(r, "my-mrap", ["mr-use1-b"])["status"] == 409)
    _check("bucket already in an MRAP rejected", _mrap_create(r, "other-mrap", ["mr-use1"])["status"] == 400)
    g = ctl(r, "GET", "/mrap/instances/my-mrap")["body"].decode()
    alias = tag(g, "Alias")
    _check("GetMultiRegionAccessPoint: alias xxxx.mrap, READY, regions", re.match(r"^[a-z]{13}\.mrap$", alias) and "<Status>READY</Status>" in g and "<Region>eu-west-1</Region>" in g)
    lst = ctl(r, "GET", "/mrap/instances")["body"].decode()
    _check("ListMultiRegionAccessPoints", "my-mrap" in lst and alias in lst)
    arn = f"arn:aws:s3::123456789012:accesspoint/{alias}"
    rt = ctl(r, "GET", f"/mrap/instances/{arn}/routes")["body"].decode()
    _check("GetMultiRegionAccessPointRoutes: default dial 100 for every member", rt.count("<TrafficDialPercentage>100</TrafficDialPercentage>") == 2 and arn in rt)

    # data path: alias + ARN, primary write mirrored to the other member
    _check("PUT via alias", s3(r, "PUT", f"/{alias}/a.txt", body=b"one")["status"] == 200)
    _check("object landed in the primary (first active) bucket", s3(r, "GET", "/mr-use1/a.txt")["body"] == b"one")
    _check("write mirrored to the other member bucket", s3(r, "GET", "/mr-euw1/a.txt")["body"] == b"one")
    _check("GET via ARN path", s3(r, "GET", f"/{arn}/a.txt")["body"] == b"one")
    _check("HEAD via alias", s3(r, "HEAD", f"/{alias}/a.txt")["status"] == 200)
    _check("list through an MRAP is refused (like real S3)", s3(r, "GET", f"/{alias}", {"list-type": "2"})["status"] == 400)

    # routes: dial the first bucket to 0 -> new writes go to the other region first, reads prefer it
    bad = ctl(r, "PATCH", f"/mrap/instances/{arn}/routes", body=f"<SubmitMultiRegionAccessPointRoutesRequest {CTL}><RouteUpdates>"
              "<Route><Bucket>mr-use1</Bucket><TrafficDialPercentage>0</TrafficDialPercentage></Route><Route><Bucket>mr-euw1</Bucket><TrafficDialPercentage>0</TrafficDialPercentage></Route></RouteUpdates></SubmitMultiRegionAccessPointRoutesRequest>")
    _check("all-zero dials rejected", bad["status"] == 400)
    _check("route for a foreign bucket rejected", ctl(r, "PATCH", f"/mrap/instances/{arn}/routes", body=f"<SubmitMultiRegionAccessPointRoutesRequest {CTL}><RouteUpdates><Route><Bucket>mr-use1-b</Bucket><TrafficDialPercentage>0</TrafficDialPercentage></Route></RouteUpdates></SubmitMultiRegionAccessPointRoutesRequest>")["status"] == 400)
    ok = ctl(r, "PATCH", f"/mrap/instances/{arn}/routes", body=f"<SubmitMultiRegionAccessPointRoutesRequest {CTL}><RouteUpdates><Route><Bucket>mr-use1</Bucket><Region>us-east-1</Region><TrafficDialPercentage>0</TrafficDialPercentage></Route></RouteUpdates></SubmitMultiRegionAccessPointRoutesRequest>")
    _check("SubmitMultiRegionAccessPointRoutes", ok["status"] == 200)
    rt = ctl(r, "GET", f"/mrap/instances/{arn}/routes")["body"].decode()
    _check("routes reflect the dial", re.search(r"<Bucket>mr-use1</Bucket><Region>us-east-1</Region><TrafficDialPercentage>0<", rt))
    s3(r, "PUT", f"/{alias}/b.txt", body=b"two")
    _check("write routes to the active region", s3(r, "GET", "/mr-euw1/b.txt")["body"] == b"two")
    _check("passive region still receives the mirrored copy", s3(r, "GET", "/mr-use1/b.txt")["body"] == b"two")
    s3(r, "PUT", "/mr-use1/only-passive.txt", body=b"p")
    _check("passive (dial 0) bucket is never read from", s3(r, "GET", f"/{alias}/only-passive.txt")["status"] == 404)
    _check("delete via alias mirrors", s3(r, "DELETE", f"/{alias}/b.txt")["status"] == 204 and s3(r, "GET", "/mr-use1/b.txt")["status"] == 404)

    # policy
    _check("no policy yet -> 404", ctl(r, "GET", "/mrap/instances/my-mrap/policy")["status"] == 404)
    pol = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": f"{arn}/object/*"}]})
    _check("malformed policy rejected", ctl(r, "POST", "/async-requests/mrap/put-policy", body=f"<PutMultiRegionAccessPointPolicyInput {CTL}><Details><Name>my-mrap</Name><Policy>nope</Policy></Details></PutMultiRegionAccessPointPolicyInput>")["status"] == 400)
    pp = ctl(r, "POST", "/async-requests/mrap/put-policy", body=f"<PutMultiRegionAccessPointPolicyInput {CTL}><ClientToken>x</ClientToken><Details><Name>my-mrap</Name><Policy>{pol}</Policy></Details></PutMultiRegionAccessPointPolicyInput>")
    _check("PutMultiRegionAccessPointPolicy returns a token", pp["status"] == 200 and "async-request/mrap/put-policy/" in tag(pp["body"].decode(), "RequestTokenARN"))
    gp = ctl(r, "GET", "/mrap/instances/my-mrap/policy")["body"].decode()
    _check("GetMultiRegionAccessPointPolicy (established)", "<Established>" in gp and "s3:GetObject" in gp)
    _check("GetMultiRegionAccessPointPolicyStatus detects public", b"<IsPublic>true</IsPublic>" in ctl(r, "GET", "/mrap/instances/my-mrap/policystatus")["body"])

    # delete
    dl = ctl(r, "POST", "/async-requests/mrap/delete", body=f"<DeleteMultiRegionAccessPointInput {CTL}><ClientToken>d</ClientToken><Details><Name>my-mrap</Name></Details></DeleteMultiRegionAccessPointInput>")
    _check("DeleteMultiRegionAccessPoint", dl["status"] == 200 and ctl(r, "GET", "/mrap/instances/my-mrap")["status"] == 404)
    _check("alias no longer routes", s3(r, "GET", f"/{alias}/a.txt")["status"] == 404)
    _check("member buckets and data survive", s3(r, "GET", "/mr-use1/a.txt")["body"] == b"one")
    _check("delete unknown -> 404", ctl(r, "POST", "/async-requests/mrap/delete", body=f"<DeleteMultiRegionAccessPointInput {CTL}><Details><Name>my-mrap</Name></Details></DeleteMultiRegionAccessPointInput>")["status"] == 404)
    _check("state is a public attr (Nano snapshot)", "account" in vars(r.s3))


# ── Access Grants ─────────────────────────────────────────────────────────────────────
def _grant(r, loc, grantee, perm, sub="", gtype="IAM", ptype=""):
    return ctl(r, "POST", "/accessgrantsinstance/grant",
               body=f"<CreateAccessGrantRequest {CTL}><AccessGrantsLocationId>{loc}</AccessGrantsLocationId><AccessGrantsLocationConfiguration><S3SubPrefix>{sub}</S3SubPrefix></AccessGrantsLocationConfiguration>"
                    f"<Grantee><GranteeType>{gtype}</GranteeType><GranteeIdentifier>{grantee}</GranteeIdentifier></Grantee><Permission>{perm}</Permission>"
                    + (f"<S3PrefixType>{ptype}</S3PrefixType>" if ptype else "") + "</CreateAccessGrantRequest>")


def access_grants():
    r = AwsWireRouter()
    mk_bucket(r, "ag-data")
    s3(r, "PUT", "/ag-data/reports/q1.csv", body=b"q1")
    s3(r, "PUT", "/ag-data/reports/q2.csv", body=b"q2")
    s3(r, "PUT", "/ag-data/private/secret.txt", body=b"s")
    _check("no instance yet -> 404", ctl(r, "GET", "/accessgrantsinstance")["status"] == 404)
    _check("location needs an instance", ctl(r, "POST", "/accessgrantsinstance/location", body=f"<CreateAccessGrantsLocationRequest {CTL}><LocationScope>s3://</LocationScope><IAMRoleArn>{ROLE}</IAMRoleArn></CreateAccessGrantsLocationRequest>")["status"] == 404)
    ci = ctl(r, "POST", "/accessgrantsinstance", body=f"<CreateAccessGrantsInstanceRequest {CTL}></CreateAccessGrantsInstanceRequest>")
    _check("CreateAccessGrantsInstance", ci["status"] == 200 and b"access-grants/default" in ci["body"])
    _check("second instance rejected", ctl(r, "POST", "/accessgrantsinstance", body=f"<CreateAccessGrantsInstanceRequest {CTL}></CreateAccessGrantsInstanceRequest>")["status"] == 409)
    _check("GetAccessGrantsInstance / List", ctl(r, "GET", "/accessgrantsinstance")["status"] == 200 and b"access-grants/default" in ctl(r, "GET", "/accessgrantsinstances")["body"])
    _check("associate Identity Center validates the ARN", ctl(r, "POST", "/accessgrantsinstance/identitycenter", body=f"<AssociateAccessGrantsIdentityCenterRequest {CTL}><IdentityCenterArn>bogus</IdentityCenterArn></AssociateAccessGrantsIdentityCenterRequest>")["status"] == 400)

    def loc(scope, role=ROLE):
        return ctl(r, "POST", "/accessgrantsinstance/location", body=f"<CreateAccessGrantsLocationRequest {CTL}><LocationScope>{scope}</LocationScope><IAMRoleArn>{role}</IAMRoleArn></CreateAccessGrantsLocationRequest>")
    _check("bad scope rejected", loc("http://x")["status"] == 400)
    _check("bad role rejected", loc("s3://ag-data", "nope")["status"] == 400)
    _check("missing bucket rejected", loc("s3://no-such-bkt")["status"] == 404)
    lc = loc("s3://ag-data")
    lid = tag(lc["body"].decode(), "AccessGrantsLocationId")
    _check("CreateAccessGrantsLocation", lc["status"] == 200 and lid)
    _check("duplicate location scope rejected", loc("s3://ag-data")["status"] == 409)
    _check("Get/List locations", lid.encode() in ctl(r, "GET", f"/accessgrantsinstance/location/{lid}")["body"] and lid.encode() in ctl(r, "GET", "/accessgrantsinstance/locations")["body"])
    ul = ctl(r, "PUT", f"/accessgrantsinstance/location/{lid}", body=f"<UpdateAccessGrantsLocationRequest {CTL}><IAMRoleArn>arn:aws:iam::123456789012:role/other</IAMRoleArn></UpdateAccessGrantsLocationRequest>")
    _check("UpdateAccessGrantsLocation", ul["status"] == 200 and b"role/other" in ul["body"])

    _check("bad permission rejected", _grant(r, lid, "arn:aws:iam::123456789012:role/app", "ADMIN")["status"] == 400)
    _check("directory grantee needs Identity Center", _grant(r, lid, "user-1", "READ", gtype="DIRECTORY_USER")["status"] == 400)
    _check("unknown location rejected", _grant(r, "nope", "arn:aws:iam::123456789012:role/app", "READ")["status"] == 404)
    APP = "arn:aws:iam::123456789012:role/app"
    g1 = _grant(r, lid, APP, "READ", "reports/*")
    g1id = tag(g1["body"].decode(), "AccessGrantId")
    _check("CreateAccessGrant: scope = location + sub-prefix", g1["status"] == 200 and "<GrantScope>s3://ag-data/reports/*</GrantScope>" in g1["body"].decode())
    g2 = _grant(r, lid, APP, "READWRITE", "uploads/*")
    _check("Get/List grants (+ filters)", g1id.encode() in ctl(r, "GET", f"/accessgrantsinstance/grant/{g1id}")["body"]
           and ctl(r, "GET", "/accessgrantsinstance/grants")["body"].count(b"<AccessGrant>") == 2
           and ctl(r, "GET", "/accessgrantsinstance/grants", {"permission": "READ"})["body"].count(b"<AccessGrant>") == 1)
    _check("object grant (S3PrefixType Object) is an exact key", "<GrantScope>s3://ag-data/private/secret.txt</GrantScope>" in _grant(r, lid, APP, "READ", "private/secret.txt", ptype="Object")["body"].decode())

    # resource policy
    _check("no resource policy -> 404", ctl(r, "GET", "/accessgrantsinstance/resourcepolicy")["status"] == 404)
    rp = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::111122223333:root"}, "Action": ["s3:GetDataAccess"], "Resource": "*"}]}
    _check("malformed resource policy", ctl(r, "PUT", "/accessgrantsinstance/resourcepolicy", body=f"<PutAccessGrantsInstanceResourcePolicyRequest {CTL}><Policy>x</Policy></PutAccessGrantsInstanceResourcePolicyRequest>")["status"] == 400)
    _check("Put/Get resource policy", ctl(r, "PUT", "/accessgrantsinstance/resourcepolicy", body=f"<PutAccessGrantsInstanceResourcePolicyRequest {CTL}><Policy>{json.dumps(rp)}</Policy></PutAccessGrantsInstanceResourcePolicyRequest>")["status"] == 200
           and b"s3:GetDataAccess" in ctl(r, "GET", "/accessgrantsinstance/resourcepolicy")["body"])
    _check("Delete resource policy", ctl(r, "DELETE", "/accessgrantsinstance/resourcepolicy")["status"] == 204 and ctl(r, "GET", "/accessgrantsinstance/resourcepolicy")["status"] == 404)

    # GetDataAccess -> scoped, ENFORCED credentials
    _check("no grant covers target -> 403", ctl(r, "GET", "/accessgrantsinstance/dataaccess", {"target": "s3://ag-data/other/*", "permission": "READ"})["status"] == 403)
    _check("READ grant cannot mint WRITE creds", ctl(r, "GET", "/accessgrantsinstance/dataaccess", {"target": "s3://ag-data/reports/*", "permission": "WRITE"})["status"] == 403)
    _check("short duration rejected", ctl(r, "GET", "/accessgrantsinstance/dataaccess", {"target": "s3://ag-data/reports/*", "permission": "READ", "durationSeconds": "60"})["status"] == 400)
    da = ctl(r, "GET", "/accessgrantsinstance/dataaccess", {"target": "s3://ag-data/reports/q1.csv", "permission": "READ"})
    dt = da["body"].decode()
    akid, tok = tag(dt, "AccessKeyId"), tag(dt, "SessionToken")
    _check("GetDataAccess returns temporary credentials + matched grant", da["status"] == 200 and akid.startswith("ASIA") and tok and "<MatchedGrantTarget>s3://ag-data/reports/</MatchedGrantTarget>" in dt)
    cred = f"AWS4-HMAC-SHA256 Credential={akid}/20261030/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0"
    T = {"x-amz-security-token": tok}
    _check("scoped creds can READ inside the grant", s3(r, "GET", "/ag-data/reports/q2.csv", headers=T, auth=cred)["body"] == b"q2")
    _check("scoped creds cannot read outside the prefix", s3(r, "GET", "/ag-data/private/secret.txt", headers=T, auth=cred)["status"] == 403)
    _check("READ-only creds cannot write", s3(r, "PUT", "/ag-data/reports/new.csv", body=b"x", headers=T, auth=cred)["status"] == 403)
    _check("cannot list the bucket root without a prefix", s3(r, "GET", "/ag-data", {"list-type": "2"}, headers=T, auth=cred)["status"] == 403)
    _check("can list within the prefix", s3(r, "GET", "/ag-data", {"list-type": "2", "prefix": "reports/"}, headers=T, auth=cred)["status"] == 200)
    _check("cannot list all buckets", s3(r, "GET", "/", headers=T, auth=cred)["status"] == 403)
    _check("wrong session token rejected", s3(r, "GET", "/ag-data/reports/q1.csv", headers={"x-amz-security-token": "bad"}, auth=cred)["status"] == 400)
    wr = ctl(r, "GET", "/accessgrantsinstance/dataaccess", {"target": "s3://ag-data/uploads/*", "permission": "WRITE"})["body"].decode()
    wcred = f"AWS4-HMAC-SHA256 Credential={tag(wr, 'AccessKeyId')}/20261030/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0"
    _check("WRITE creds (narrowed from READWRITE) can PUT in scope", s3(r, "PUT", "/ag-data/uploads/a.bin", body=b"w", auth=wcred)["status"] == 200)
    _check("WRITE creds cannot READ (narrowed)", s3(r, "GET", "/ag-data/uploads/a.bin", auth=wcred)["status"] == 403)
    _check("WRITE creds cannot PUT outside scope", s3(r, "PUT", "/ag-data/reports/z", body=b"w", auth=wcred)["status"] == 403)
    _check("unrestricted callers unaffected", s3(r, "GET", "/ag-data/private/secret.txt")["body"] == b"s")
    # expiry
    for c in r.s3.account["grants"]["creds"].values():
        c["expires"] = 1
    _check("expired creds refused", s3(r, "GET", "/ag-data/reports/q1.csv", headers=T, auth=cred)["status"] == 400)

    # delete order
    _check("delete location with grants rejected", ctl(r, "DELETE", f"/accessgrantsinstance/location/{lid}")["status"] == 409)
    _check("delete instance with locations rejected", ctl(r, "DELETE", "/accessgrantsinstance")["status"] == 409)
    for gid in re.findall(r"<AccessGrantId>([^<]+)</AccessGrantId>", ctl(r, "GET", "/accessgrantsinstance/grants")["body"].decode()):
        assert ctl(r, "DELETE", f"/accessgrantsinstance/grant/{gid}")["status"] == 204
    _check("grants deleted", ctl(r, "GET", f"/accessgrantsinstance/grant/{g1id}")["status"] == 404)
    _check("DeleteAccessGrantsLocation", ctl(r, "DELETE", f"/accessgrantsinstance/location/{lid}")["status"] == 204)
    _check("DeleteAccessGrantsInstance", ctl(r, "DELETE", "/accessgrantsinstance")["status"] == 204 and ctl(r, "GET", "/accessgrantsinstance")["status"] == 404)


# ── Batch Operations ──────────────────────────────────────────────────────────────────
def _lambda(r, name, src):
    out = r.handle("POST", "/2015-03-31/functions", {}, {"authorization": S3.replace("/s3/", "/lambda/")},
                   json.dumps({"FunctionName": name, "Code": {"Source": src}}).encode())
    assert out["status"] in (200, 201), out


def _job(r, op_xml, manifest_key="manifest.csv", confirm=False, report=True, prio=10, role=ROLE, fields=("Bucket", "Key"), fmt="S3BatchOperations_CSV_20180820", token=None, mb="jb-src"):
    et = s3(r, "HEAD", f"/{mb}/{manifest_key}")["headers"].get("ETag", "")
    f = "".join(f"<member>{x}</member>" for x in fields)
    rep = ('<Report><Bucket>arn:aws:s3:::jb-report</Bucket><Format>Report_CSV_20180820</Format><Enabled>true</Enabled><Prefix>rpt</Prefix><ReportScope>AllTasks</ReportScope></Report>'
           if report else "<Report><Enabled>false</Enabled></Report>")
    return ctl(r, "POST", "/jobs", body=f"<CreateJobRequest {CTL}><ConfirmationRequired>{str(confirm).lower()}</ConfirmationRequired><ClientRequestToken>{token or manifest_key + str(abs(hash(op_xml + str(confirm)+role)))}</ClientRequestToken>"
               f"<Description>test job</Description><Priority>{prio}</Priority><RoleArn>{role}</RoleArn><Operation>{op_xml}</Operation>"
               f"<Manifest><Spec><Format>{fmt}</Format><Fields>{f}</Fields></Spec><Location><ObjectArn>arn:aws:s3:::{mb}/{manifest_key}</ObjectArn><ETag>{et}</ETag></Location></Manifest>{rep}</CreateJobRequest>")


def _run(r, jid, want=("Complete", "Failed", "Cancelled")):
    seen = []
    for _ in range(8):
        d = ctl(r, "GET", f"/jobs/{jid}")["body"].decode()
        st = tag(d, "Status")
        seen.append(st)
        if st in want:
            return d, seen
    raise AssertionError(f"job stuck: {seen}")


def batch_operations():
    r = AwsWireRouter()
    for b in ("jb-src", "jb-dst", "jb-report"):
        mk_bucket(r, b)
    for i in range(3):
        s3(r, "PUT", f"/jb-src/data/f{i}.txt", body=f"file{i}".encode())
    s3(r, "PUT", "/jb-src/cold.bin", body=b"c", headers={"x-amz-storage-class": "GLACIER"})
    s3(r, "PUT", "/jb-src/manifest.csv", body=b"jb-src,data/f0.txt\njb-src,data/f1.txt\njb-src,data/f2.txt\njb-src,data/missing.txt\n")
    s3(r, "PUT", "/jb-src/ok.csv", body=b"jb-src,data/f0.txt\njb-src,data/f1.txt\njb-src,data/f2.txt\n")
    s3(r, "PUT", "/jb-src/cold.csv", body=b"jb-src,cold.bin\njb-src,data/f0.txt\n")
    TAG = "<S3PutObjectTagging><TagSet><member><Key>env</Key><Value>prod</Value></member></TagSet></S3PutObjectTagging>"

    _check("bad role rejected", _job(r, TAG, "ok.csv", role="nope")["status"] == 400)
    _check("foreign-account role rejected", _job(r, TAG, "ok.csv", role="arn:aws:iam::999999999999:role/x")["status"] == 400)
    _check("two operations rejected", _job(r, TAG + "<S3DeleteObjectTagging/>", "ok.csv")["status"] == 400)
    _check("unimplemented op honest 501", _job(r, "<S3ComputeObjectChecksum><ChecksumAlgorithm>CRC32</ChecksumAlgorithm><ChecksumType>FULL_OBJECT</ChecksumType></S3ComputeObjectChecksum>", "ok.csv")["status"] == 501)
    _check("report bucket must exist", ctl(r, "POST", "/jobs", body=f"<CreateJobRequest {CTL}><Priority>1</Priority><RoleArn>{ROLE}</RoleArn><Operation>{TAG}</Operation><Manifest><Spec><Format>S3BatchOperations_CSV_20180820</Format><Fields><member>Bucket</member><member>Key</member></Fields></Spec><Location><ObjectArn>arn:aws:s3:::jb-src/ok.csv</ObjectArn></Location></Manifest><Report><Bucket>arn:aws:s3:::nope</Bucket><Format>Report_CSV_20180820</Format><Enabled>true</Enabled><ReportScope>AllTasks</ReportScope></Report></CreateJobRequest>")["status"] == 400)

    # confirmation flow + tagging operation
    c = _job(r, TAG, "ok.csv", confirm=True)
    jid = tag(c["body"].decode(), "JobId")
    d = ctl(r, "GET", f"/jobs/{jid}")["body"].decode()
    _check("ConfirmationRequired job waits (Suspended) with task total", tag(d, "Status") == "Suspended" and tag(d, "TotalNumberOfTasks") == "3")
    _check("idempotent ClientRequestToken", tag(_job(r, TAG, "ok.csv", confirm=True)["body"].decode(), "JobId") == jid)
    _check("not executed while suspended", s3(r, "GET", "/jb-src/data/f0.txt", {"tagging": ""})["body"].count(b"<Tag>") == 0)
    _check("priority update", ctl(r, "POST", f"/jobs/{jid}/priority", {"priority": "50"})["status"] == 200 and tag(ctl(r, "GET", f"/jobs/{jid}")["body"].decode(), "Priority") == "50")
    _check("invalid transition rejected", ctl(r, "POST", f"/jobs/{jid}/status", {"requestedJobStatus": "Complete"})["status"] == 400)
    u = ctl(r, "POST", f"/jobs/{jid}/status", {"requestedJobStatus": "Ready"})
    _check("UpdateJobStatus Ready (confirm)", u["status"] == 200 and tag(u["body"].decode(), "Status") == "Ready")
    d, seen = _run(r, jid)
    _check("lifecycle goes Active before Complete", "Active" in seen and seen[-1] == "Complete")
    _check("progress summary", tag(d, "NumberOfTasksSucceeded") == "3" and tag(d, "NumberOfTasksFailed") == "0" and tag(d, "TotalNumberOfTasks") == "3")
    _check("S3PutObjectTagging EXECUTED against the store", all(b"<Key>env</Key><Value>prod</Value>" in s3(r, "GET", f"/jb-src/data/f{i}.txt", {"tagging": ""})["body"] for i in range(3)))
    keys = [k for k in re.findall(r"<Key>([^<]+)</Key>", s3(r, "GET", "/jb-report", {"list-type": "2", "prefix": "rpt/"})["body"].decode())]
    _check("completion report + manifest written to the report bucket/prefix", any(k.startswith(f"rpt/job-{jid}/results/") for k in keys) and f"rpt/job-{jid}/manifest.json" in keys)
    rep = s3(r, "GET", f"/jb-report/{[k for k in keys if '/results/' in k][0]}")["body"].decode()
    _check("report rows carry bucket,key,status", '"jb-src","data/f0.txt"' in rep and '"succeeded"' in rep)
    _check("cancel of a completed job rejected", ctl(r, "POST", f"/jobs/{jid}/status", {"requestedJobStatus": "Cancelled"})["status"] == 409)
    _check("priority of a completed job rejected", ctl(r, "POST", f"/jobs/{jid}/priority", {"priority": "1"})["status"] == 409)

    # failures are per-task, job still completes; FailedTasksOnly scope
    f = _job(r, "<S3DeleteObjectTagging/>", "manifest.csv")
    d, _ = _run(r, tag(f["body"].decode(), "JobId"))
    _check("one missing key -> 1 failed task, job Complete", tag(d, "NumberOfTasksFailed") == "1" and tag(d, "NumberOfTasksSucceeded") == "3" and tag(d, "Status") == "Complete")
    _check("S3DeleteObjectTagging EXECUTED", b"<Tag>" not in s3(r, "GET", "/jb-src/data/f1.txt", {"tagging": ""})["body"])
    _check("failed task reported with its error code", any(b"NoSuchKey" in s3(r, "GET", f"/jb-report/{k}")["body"] for k in re.findall(r"<Key>(rpt/[^<]*results/[^<]+)</Key>", s3(r, "GET", "/jb-report", {"list-type": "2", "prefix": "rpt/"})["body"].decode())))

    # copy
    cp = _job(r, "<S3PutObjectCopy><TargetResource>arn:aws:s3:::jb-dst</TargetResource><TargetKeyPrefix>copied/</TargetKeyPrefix><StorageClass>STANDARD_IA</StorageClass>"
                 "<NewObjectTagging><member><Key>k</Key><Value>v</Value></member></NewObjectTagging><CannedAccessControlList>private</CannedAccessControlList></S3PutObjectCopy>", "ok.csv")
    d, _ = _run(r, tag(cp["body"].decode(), "JobId"))
    _check("S3PutObjectCopy EXECUTED (prefix, storage class, new tags)", s3(r, "GET", "/jb-dst/copied/data/f2.txt")["body"] == b"file2"
           and s3(r, "HEAD", "/jb-dst/copied/data/f2.txt")["headers"].get("x-amz-storage-class") == "STANDARD_IA"
           and b"<Key>k</Key><Value>v</Value>" in s3(r, "GET", "/jb-dst/copied/data/f2.txt", {"tagging": ""})["body"])
    # acl
    acl = _job(r, "<S3PutObjectAcl><AccessControlPolicy><CannedAccessControlList>public-read</CannedAccessControlList></AccessControlPolicy></S3PutObjectAcl>", "ok.csv")
    d, _ = _run(r, tag(acl["body"].decode(), "JobId"))
    _check("S3PutObjectAcl EXECUTED (public-read grant present)", tag(d, "NumberOfTasksSucceeded") == "3" and b"AllUsers" in s3(r, "GET", "/jb-src/data/f0.txt", {"acl": ""})["body"])
    # restore
    rs = _job(r, "<S3InitiateRestoreObject><ExpirationInDays>3</ExpirationInDays><GlacierJobTier>STANDARD</GlacierJobTier></S3InitiateRestoreObject>", "cold.csv")
    d, _ = _run(r, tag(rs["body"].decode(), "JobId"))
    _check("S3InitiateRestoreObject: archived object restored, standard object fails InvalidObjectState",
           tag(d, "NumberOfTasksSucceeded") == "1" and tag(d, "NumberOfTasksFailed") == "1" and b"ongoing-request=\"false\"" in (s3(r, "HEAD", "/jb-src/cold.bin")["headers"].get("x-amz-restore", "").encode() or b""))
    # replicate (no rule -> per-task failure; with rule -> replicated)
    rp = _job(r, "<S3ReplicateObject/>", "ok.csv")
    d, _ = _run(r, tag(rp["body"].decode(), "JobId"))
    _check("S3ReplicateObject without a rule fails per task", tag(d, "NumberOfTasksFailed") == "3")
    for b in ("jb-src", "jb-dst"):
        s3(r, "PUT", f"/{b}", {"versioning": ""}, body=b"<VersioningConfiguration><Status>Enabled</Status></VersioningConfiguration>")
    s3(r, "PUT", "/jb-src", {"replication": ""}, body=b"<ReplicationConfiguration><Role>arn:aws:iam::123456789012:role/r</Role><Rule><ID>r1</ID><Status>Enabled</Status><Filter><Prefix></Prefix></Filter><Destination><Bucket>arn:aws:s3:::jb-dst</Bucket></Destination></Rule></ReplicationConfiguration>")
    s3(r, "PUT", "/jb-src/data/f0.txt", body=b"file0")
    s3(r, "DELETE", "/jb-dst/data/f0.txt")
    rp = _job(r, "<S3ReplicateObject/>", "ok.csv", token="rep2")
    d, _ = _run(r, tag(rp["body"].decode(), "JobId"))
    _check("S3ReplicateObject with a rule replicates", tag(d, "NumberOfTasksSucceeded") == "3" and s3(r, "GET", "/jb-dst/data/f2.txt")["body"] == b"file2")

    # object lock ops
    s3(r, "PUT", "/jb-lock", headers={"x-amz-bucket-object-lock-enabled": "true"})
    s3(r, "PUT", "/jb-lock/a", body=b"a")
    s3(r, "PUT", "/jb-src/lock.csv", body=b"jb-lock,a\n")
    rt = _job(r, "<S3PutObjectRetention><Retention><Mode>GOVERNANCE</Mode><RetainUntilDate>2099-01-01T00:00:00Z</RetainUntilDate></Retention></S3PutObjectRetention>", "lock.csv", token="rt")
    _run(r, tag(rt["body"].decode(), "JobId"))
    _check("S3PutObjectRetention EXECUTED", b"GOVERNANCE" in s3(r, "GET", "/jb-lock/a", {"retention": ""})["body"])

    lh = _job(r, "<S3PutObjectLegalHold><LegalHold><Status>ON</Status></LegalHold></S3PutObjectLegalHold>", "lock.csv", token="lh")
    _run(r, tag(lh["body"].decode(), "JobId"))
    _check("S3PutObjectLegalHold EXECUTED", b"<Status>ON</Status>" in s3(r, "GET", "/jb-lock/a", {"legal-hold": ""})["body"])
    # lambda
    _lambda(r, "mark-fn", "def handler(event, ctx):\n"
                          "    t = event['tasks'][0]\n"
                          "    return {'invocationSchemaVersion': '1.0', 'treatMissingKeysAs': 'PermanentFailure', 'invocationId': event['invocationId'],\n"
                          "            'results': [{'taskId': t['taskId'], 'resultCode': 'Succeeded' if not t['s3Key'].endswith('f1.txt') else 'PermanentFailure', 'resultString': 'seen ' + t['s3Key'] + ' ' + event['job']['id'][:4]}]}\n")
    lj = _job(r, "<LambdaInvoke><FunctionArn>arn:aws:lambda:us-east-1:123456789012:function:mark-fn</FunctionArn></LambdaInvoke>", "ok.csv")
    ljid = tag(lj["body"].decode(), "JobId")
    d, _ = _run(r, ljid)
    _check("LambdaInvoke EXECUTED through the Lambda core (per-task Succeeded/PermanentFailure)", tag(d, "NumberOfTasksSucceeded") == "2" and tag(d, "NumberOfTasksFailed") == "1")
    rk = [k for k in re.findall(r"<Key>([^<]+)</Key>", s3(r, "GET", "/jb-report", {"list-type": "2", "prefix": f"rpt/job-{ljid}/results/"})["body"].decode())][0]
    _check("Lambda resultString lands in the report", "seen data/f0.txt" in s3(r, "GET", f"/jb-report/{rk}")["body"].decode())
    nf = _job(r, "<LambdaInvoke><FunctionArn>arn:aws:lambda:us-east-1:123456789012:function:ghost</FunctionArn></LambdaInvoke>", "ok.csv", token="ghost")
    d, _ = _run(r, tag(nf["body"].decode(), "JobId"))
    _check("missing Lambda fails every task", tag(d, "NumberOfTasksFailed") == "3")

    # manifest problems -> Failed job; inventory-style manifest; cancel
    s3(r, "PUT", "/jb-src/inv.csv", body=b'"jb-src","data%2Ff0.txt","1024","2026-01-01"\n')
    iv = _job(r, TAG, "inv.csv", fields=("Bucket", "Key", "Size", "LastModifiedDate"), fmt="S3InventoryReport_CSV_20161130", token="inv")
    d, _ = _run(r, tag(iv["body"].decode(), "JobId"))
    _check("inventory CSV manifest (url-decoded keys, custom fields)", tag(d, "NumberOfTasksSucceeded") == "1")
    bad = ctl(r, "POST", "/jobs", body=f"<CreateJobRequest {CTL}><Priority>1</Priority><RoleArn>{ROLE}</RoleArn><Operation>{TAG}</Operation><Manifest><Spec><Format>S3BatchOperations_CSV_20180820</Format><Fields><member>Bucket</member><member>Key</member></Fields></Spec><Location><ObjectArn>arn:aws:s3:::jb-src/no-manifest.csv</ObjectArn></Location></Manifest><Report><Enabled>false</Enabled></Report></CreateJobRequest>")
    bd = ctl(r, "GET", f"/jobs/{tag(bad['body'].decode(), 'JobId')}")["body"].decode()
    _check("missing manifest -> Failed job with FailureReasons", tag(bd, "Status") == "Failed" and "no-manifest.csv" in bd)
    wrong = _job(r, TAG, "ok.csv", token="etag")
    cn = _job(r, TAG, "ok.csv", confirm=True, token="cancelme")
    cid = tag(cn["body"].decode(), "JobId")
    cu = ctl(r, "POST", f"/jobs/{cid}/status", {"requestedJobStatus": "Cancelled", "statusUpdateReason": "no thanks"})
    _check("Cancel a suspended job", tag(cu["body"].decode(), "Status") == "Cancelled" and tag(ctl(r, "GET", f"/jobs/{cid}")["body"].decode(), "StatusUpdateReason") == "no thanks")
    _check("cancelled job never runs", tag(ctl(r, "GET", f"/jobs/{cid}")["body"].decode(), "NumberOfTasksSucceeded") == "0")

    # tagging + list
    _check("PutJobTagging", ctl(r, "PUT", f"/jobs/{jid}/tagging", body=f"<PutJobTaggingRequest {CTL}><Tags><member><Key>team</Key><Value>data</Value></member></Tags></PutJobTaggingRequest>")["status"] == 204)
    _check("GetJobTagging", b"<Key>team</Key><Value>data</Value>" in ctl(r, "GET", f"/jobs/{jid}/tagging")["body"])
    _check("duplicate tag keys rejected", ctl(r, "PUT", f"/jobs/{jid}/tagging", body=f"<PutJobTaggingRequest {CTL}><Tags><member><Key>a</Key><Value>1</Value></member><member><Key>a</Key><Value>2</Value></member></Tags></PutJobTaggingRequest>")["status"] == 400)
    _check("DeleteJobTagging", ctl(r, "DELETE", f"/jobs/{jid}/tagging")["status"] == 204 and b"<Key>" not in ctl(r, "GET", f"/jobs/{jid}/tagging")["body"])
    all_ = ctl(r, "GET", "/jobs")["body"].decode()
    _check("ListJobs", all_.count("<JobId>") >= 10 and "<Operation>S3PutObjectTagging</Operation>" in all_)
    cancelled = ctl(r, "GET", "/jobs", {"jobStatuses": "Cancelled"})["body"].decode()
    _check("ListJobs status filter", cancelled.count("<JobId>") == 1 and cid in cancelled)
    pg = ctl(r, "GET", "/jobs", {"maxResults": "2"})["body"].decode()
    _check("ListJobs pagination", pg.count("<JobId>") == 2 and "<NextToken>2</NextToken>" in pg)
    _check("unknown job 404", ctl(r, "GET", "/jobs/nope")["status"] == 404)
    _check("state is a public attr (Nano snapshot)", "jobs" in r.s3.account)


def run():
    multi_region_access_points()
    access_grants()
    batch_operations()
    print("\nRESULT: PASS - S3 sweep S3-2")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
