"""AWS faithful-IAM gaps: execute-api API id, S3 DeleteObjects per key, CloudWatch CBOR, SNS default / access point / ECR registry / Lambda alias
and layer policies, and anonymous (unsigned) S3 through the real appliance app (presigned URLs keep resolving their signer)."""
import json, os, re, struct, sys, types, uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")

from core import iam_resource_policies as rp
from core import iam_state_adapters as ad
from core.iam_engine import aws_eval, gate, map_aws

ACCT = "123456789012"
USER = f"arn:aws:iam::{ACCT}:user/alice"
OTHER = "arn:aws:iam::999999999999:user/mallory"


def sig(svc, akid="AK"):
    return {"authorization": f"AWS4-HMAC-SHA256 Credential={akid}/20261123/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"}


def pairs(entries):
    return {(e["action"], e["resource"]) for e in entries}


def ev(action, resource, state, principal=None, **kw):
    p = principal or {"arn": USER, "type": "user", "account": ACCT, "policies": []}
    return aws_eval.evaluate({"action": action, "resource": resource, "principal": p, **kw}, state)


# ------------------------------------------------------------------------------------------------ request map
@pytest.mark.parametrize("path,host", [
    ("/prod/items/1", "abcde12345.execute-api.us-east-1.amazonaws.com"),
    ("/prod/items/1", "abcde12345.execute-api.localhost"),
    ("/restapis/abcde12345/prod/_user_request_/items/1", "localhost"),
    ("/apigw/abcde12345/prod/items/1", "localhost:8099"),
    ("/abcde12345/prod/items/1", "localhost"),
])
def test_execute_api_resolves_the_api_id(path, host):
    got = map_aws.required({"method": "GET", "path": path, "headers": dict(sig("execute-api"), host=host)})
    assert pairs(got) == {("execute-api:Invoke", f"arn:aws:execute-api:us-east-1:{ACCT}:abcde12345/prod/GET/items/1")}


def test_rest_api_resource_policy_now_matches_the_invoke_arn():
    api = f"arn:aws:execute-api:us-east-1:{ACCT}:abcde12345"
    pol = {"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Principal": "*", "Action": "execute-api:Invoke", "Resource": "*"}]}
    stores = {"lam": types.SimpleNamespace(account_id=ACCT, _apigateway_apis={"abcde12345": {"policy": json.dumps(pol)}})}
    st = {"account": ACCT, **rp.aws_resource_state(stores)}
    ident = [{"id": "p", "document": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}}]
    req = map_aws.required({"method": "GET", "path": "/restapis/abcde12345/prod/_user_request_/x", "headers": dict(sig("execute-api"), host="localhost")})[0]
    assert req["resource"].startswith(api + "/prod/GET")
    d = ev(req["action"], req["resource"], st, {"arn": USER, "type": "user", "account": ACCT, "policies": ident})
    assert d["allowed"] is False and d["reason"] == "explicit_deny"


def test_s3_delete_objects_authorises_each_key():
    body = (b'<Delete xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Object><Key>a/b.txt</Key></Object>'
            b'<Object><Key>c.txt</Key><VersionId>v1</VersionId></Object></Delete>')
    got = map_aws.required({"method": "POST", "path": "/bk", "query": "delete", "headers": dict(sig("s3"), host="localhost"), "body": body})
    assert pairs(got) == {("s3:DeleteObject", "arn:aws:s3:::bk/a/b.txt"), ("s3:DeleteObjectVersion", "arn:aws:s3:::bk/c.txt")}
    # a policy on one prefix now bites: the other key is denied
    ident = [{"id": "p", "document": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:DeleteObject", "Resource": "arn:aws:s3:::bk/a/*"}]}}]
    p = {"arn": USER, "type": "user", "account": ACCT, "policies": ident}
    res = [ev(e["action"], e["resource"], {"account": ACCT}, p)["allowed"] for e in got]
    assert res == [True, False]
    no_body = map_aws.required({"method": "POST", "path": "/bk", "query": "delete", "headers": dict(sig("s3"), host="localhost"), "body": b""})
    assert pairs(no_body) and all(e["service"] == "s3" for e in no_body)       # unparseable body: the old bucket-wide fallback


def _cbor(o):
    if o is None:
        return b"\xf6"
    if isinstance(o, bool):
        return b"\xf5" if o else b"\xf4"
    if isinstance(o, int):
        if o < 0:
            return bytes([0x20 + (-1 - o)])                                     # only small negatives are needed here
        return bytes([o]) if o < 24 else b"\x18" + bytes([o]) if o < 256 else b"\x19" + struct.pack(">H", o)
    if isinstance(o, float):
        return b"\xfb" + struct.pack(">d", o)
    if isinstance(o, str):
        b = o.encode()
        return (bytes([0x60 + len(b)]) if len(b) < 24 else b"\x78" + bytes([len(b)])) + b
    if isinstance(o, list):
        return bytes([0x80 + len(o)]) + b"".join(_cbor(x) for x in o)
    return bytes([0xa0 + len(o)]) + b"".join(_cbor(k) + _cbor(v) for k, v in o.items())


def test_cbor_decoder_roundtrip():
    doc = {"AlarmName": "a1", "Threshold": 2.5, "Period": 300, "Dims": [{"Name": "n", "Value": "v"}], "On": True, "Nil": None, "Neg": -1}
    got = map_aws._cbor_loads(_cbor(doc))
    assert got["AlarmName"] == "a1" and got["Threshold"] == 2.5 and got["Period"] == 300 and got["Dims"] == [{"Name": "n", "Value": "v"}] \
        and got["On"] is True and got["Nil"] is None
    assert map_aws._cbor_loads(b"\xa1\x61a\x9f\x01\x02\xff") == {"a": [1, 2]}           # indefinite array
    with pytest.raises(Exception):
        map_aws._cbor_loads(b"\xa1\x61")


def test_cloudwatch_cbor_resources_bind_like_json():
    h = dict(sig("monitoring"), host="localhost")
    cbor = map_aws.required({"method": "POST", "path": "/service/GraniteServiceVersion20100801/operation/PutMetricAlarm",
                             "headers": dict(h, **{"content-type": "application/cbor", "smithy-protocol": "rpc-v2-cbor"}), "body": _cbor({"AlarmName": "cpu-high"})})
    js = map_aws.required({"method": "POST", "path": "/", "headers": dict(h, **{"x-amz-target": "GraniteServiceVersion20100801.PutMetricAlarm",
                                                                                   "content-type": "application/x-amz-json-1.0"}), "body": json.dumps({"AlarmName": "cpu-high"})})
    assert pairs(cbor) == pairs(js) == {("cloudwatch:PutMetricAlarm", f"arn:aws:cloudwatch:us-east-1:{ACCT}:alarm:cpu-high")}


# ------------------------------------------------------------------------------------------------ resource policies
def test_sns_default_policy_grants_same_account_only():
    topic = f"arn:aws:sns:us-east-1:{ACCT}:t"
    msg = types.SimpleNamespace(account_id=ACCT, queues={}, topics={"t": {"topic_arn": topic, "attributes": {}}})
    st = {"account": ACCT, **rp.aws_resource_state({"msg": msg})}
    assert topic in st["resource_policies"]
    bare = {"arn": USER, "type": "user", "account": ACCT, "policies": []}
    assert ev("sns:Publish", topic, st, bare)["allowed"] is True                    # no identity policy: the default topic policy allows the account
    assert ev("sns:CreateTopic", topic, st, bare)["allowed"] is False               # not in the default policy's action list
    other = {"arn": OTHER, "type": "user", "account": "999999999999", "policies": [
        {"id": "p", "document": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "sns:*", "Resource": "*"}]}}]}
    assert ev("sns:Publish", topic, st, other, resource_account=ACCT)["allowed"] is False   # another account: identity allow is not enough
    msg.topics["t"]["attributes"]["Policy"] = json.dumps({"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": {"AWS": OTHER}, "Action": "sns:Publish", "Resource": topic}]})
    st = {"account": ACCT, **rp.aws_resource_state({"msg": msg})}
    assert ev("sns:Publish", topic, st, bare)["allowed"] is False                   # an explicit policy replaces the default


def test_s3_access_point_and_object_lambda_policies():
    ap = f"arn:aws:s3:us-east-1:{ACCT}:accesspoint/ap1"
    olap = f"arn:aws:s3-object-lambda:us-east-1:{ACCT}:accesspoint/ol1"
    doc = lambda r, a: json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": USER}, "Action": a, "Resource": r}]})  # noqa: E731
    s3 = types.SimpleNamespace(account_id=ACCT, account={"olaps": {"ol1": {"arn": olap, "policy": doc(olap, "s3-object-lambda:GetObject")}}},
                               buckets={"bk": {"access_points": {"ap1": {"arn": ap, "policy": doc(ap + "/object/*", "s3:GetObject")}}}})
    st = {"account": ACCT, **rp.aws_resource_state({"s3": s3})}
    bare = {"arn": USER, "type": "user", "account": ACCT, "policies": []}
    assert ev("s3:GetObject", ap + "/object/k", st, bare)["allowed"] is True        # object ARN resolves to the access point policy
    assert ev("s3:PutObject", ap + "/object/k", st, bare)["allowed"] is False
    assert ev("s3-object-lambda:GetObject", olap, st, bare)["allowed"] is True
    assert rp.ResourcePolicyMap.owner_of("arn:aws:s3:us-east-1:%s:accesspoint/ap1/object/a/b" % ACCT) == ap


def test_ecr_registry_policy_applies_to_every_repository_and_new_ones():
    pol = lambda a, r: json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": OTHER}, "Action": a, "Resource": r}]})  # noqa: E731
    repo = f"arn:aws:ecr:us-east-1:{ACCT}:repository/r1"
    s3 = types.SimpleNamespace(account_id=ACCT, buckets={}, account={"ecr": {"registryPolicy": pol("ecr:ReplicateImage", f"arn:aws:ecr:us-east-1:{ACCT}:repository/*"),
                                                                                  "regions": {"us-east-1": {"r1": {"policy": pol("ecr:BatchGetImage", repo)}}}}})
    st = {"account": ACCT, **rp.aws_resource_state({"s3": s3})}
    other = {"arn": OTHER, "type": "user", "account": "999999999999", "policies": [
        {"id": "p", "document": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "ecr:*", "Resource": "*"}]}}]}
    assert ev("ecr:BatchGetImage", repo, st, other, resource_account=ACCT)["allowed"] is True            # repository policy still applies
    assert ev("ecr:ReplicateImage", repo, st, other, resource_account=ACCT)["allowed"] is True           # merged registry policy
    assert ev("ecr:ReplicateImage", f"arn:aws:ecr:us-east-1:{ACCT}:repository/brand-new", st, other, resource_account=ACCT)["allowed"] is True
    assert ev("ecr:PutImage", repo, st, other, resource_account=ACCT)["allowed"] is False


def test_lambda_alias_and_layer_policies_have_their_own_arns():
    fn = f"arn:aws:lambda:us-east-1:{ACCT}:function:fn"
    st_ = lambda sid, res: {"Sid": sid, "Effect": "Allow", "Principal": {"AWS": OTHER}, "Action": "lambda:InvokeFunction", "Resource": res}  # noqa: E731
    lam = types.SimpleNamespace(account_id=ACCT, _lambda_functions={"fn": {"arn": fn, "policy_statements": {"a": st_("a", fn + ":live")}}},
                                _lambda_layers={"lay": {"versions": {1: {"policy_statements": {"x": {"Sid": "x", "Effect": "Allow", "Principal": {"AWS": OTHER},
                                                                                                      "Action": "lambda:GetLayerVersion", "Resource": f"arn:aws:lambda:us-east-1:{ACCT}:layer:lay:1"}}}}}})
    got = rp.aws_resource_policies({"lam": lam})
    assert fn + ":live" in got and fn not in dict.keys(got)                          # alias statement lives on the alias ARN only
    assert f"arn:aws:lambda:us-east-1:{ACCT}:layer:lay:1" in got
    st = {"account": ACCT, "resource_policies": got}
    other = {"arn": OTHER, "type": "user", "account": "999999999999", "policies": [
        {"id": "p", "document": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "lambda:*", "Resource": "*"}]}}]}
    assert ev("lambda:InvokeFunction", fn + ":live", st, other, resource_account=ACCT)["allowed"] is True
    assert ev("lambda:GetLayerVersion", f"arn:aws:lambda:us-east-1:{ACCT}:layer:lay:1", st, other, resource_account=ACCT)["allowed"] is True


# ------------------------------------------------------------------------------------------------ anonymous S3 (unit)
def test_unsigned_request_resolution():
    buckets = {"pub", "my.dotted.bucket"}
    store = types.SimpleNamespace(account_id=ACCT, users={}, groups={}, roles={}, policies={}, org_policies={}, extras={})
    mk = lambda path, host="localhost", method="GET": {"method": method, "path": path, "headers": {"host": host}, "query": ""}   # noqa: E731
    r = mk("/pub/k.txt")
    state, principal = ad.aws_anonymous(r, store, buckets)
    assert principal["type"] == "anonymous" and principal["arn"] == "" and r["service_hint"] == "s3"
    assert ad.aws_anonymous(mk("/", method="GET"), store, buckets) is None                 # the console root
    assert ad.aws_anonymous(mk("/aws-console.html"), store, buckets) is None              # console assets are not buckets
    assert ad.aws_anonymous(mk("/nobucket/k"), store, buckets) is None                     # real S3: NoSuchBucket (404), not an IAM decision
    assert ad.aws_anonymous(mk("/pub/k", method="OPTIONS"), store, buckets) is None        # CORS preflight is not IAM
    assert ad.aws_anonymous(mk("/k", host="pub.s3.us-east-1.amazonaws.com"), store, buckets)[1]["type"] == "anonymous"   # virtual-host style
    assert ad.aws_anonymous(mk("/k", host="my.dotted.bucket.s3.localhost"), store, buckets)[1]["type"] == "anonymous"


def test_browser_form_post_is_signed_not_anonymous():
    body = (b'--B\r\nContent-Disposition: form-data; name="key"\r\n\r\nk\r\n--B\r\nContent-Disposition: form-data; name="x-amz-credential"\r\n\r\n'
            b'AKIA123/20261123/us-east-1/s3/aws4_request\r\n--B--\r\n')
    assert ad._form_post_akid({"content-type": "multipart/form-data; boundary=B"}, body) == "AKIA123"
    assert ad._form_post_akid({"content-type": "multipart/form-data; boundary=B"}, b"nothing") == ""
    assert ad._form_post_akid({"content-type": "text/plain"}, body) == ""


def test_anonymous_denial_shape_and_gate():
    pub = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::pub/*"}]}
    st = {"account": ACCT, "principals": {}, "groups": {}, "resource_policies": rp.ResourcePolicyMap({"arn:aws:s3:::pub": pub})}
    anon = {"arn": "", "type": "anonymous", "account": ACCT}
    settings = {"space": "enforce"}
    mk = lambda method, path: {"method": method, "path": path, "headers": {"host": "localhost"}, "query": "", "principal": anon, "service_hint": "s3"}  # noqa: E731
    assert gate.check("aws", mk("GET", "/pub/k"), st, settings) is None
    spec = gate.check("aws", mk("PUT", "/pub/k"), st, settings)
    assert spec["status"] == 403 and "<Code>AccessDenied</Code>" in spec["body"] and "<Message>Access Denied</Message>" in spec["body"]
    assert gate.check("aws", mk("GET", "/private/k"), st, settings)["status"] == 403
    assert gate.check("aws", mk("GET", "/private/k"), st, {"space": "audit"}) is None


# ------------------------------------------------------------------------------------------------ anonymous S3 through the real app
@pytest.fixture(scope="module")
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    yield c
    c.put("/api/iam/aws/enforcement", json={"space": "off"})


def _hdr(akid, svc):
    return f"AWS4-HMAC-SHA256 Credential={akid}/20261123/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=00"


def _q(c, akid, svc, form):
    return c.post("/", data=form, headers={"Authorization": _hdr(akid, svc), "X-Amz-Date": "20261123T000000Z", "Content-Type": "application/x-www-form-urlencoded"})


def _s3(c, akid, method, path, **kw):
    return c.request(method, path, headers={"Authorization": _hdr(akid, "s3"), "X-Amz-Date": "20261123T000000Z"}, **kw)


def test_e2e_anonymous_s3_public_bucket_policy_presigned_and_console(client):
    c, tag = client, uuid.uuid4().hex[:8]
    bucket, uname, uname2 = "an-bkt-" + tag, "an-a-" + tag, "an-b-" + tag
    made = []

    def mkuser(name, statements):
        assert _q(c, "test", "iam", {"Action": "CreateUser", "UserName": name, "Version": "2010-05-08"}).status_code == 200
        made.append(name)
        k = _q(c, "test", "iam", {"Action": "CreateAccessKey", "UserName": name, "Version": "2010-05-08"})
        akid = re.search(r"<AccessKeyId>(.*?)</AccessKeyId>", k.text).group(1)
        if statements:
            _q(c, "test", "iam", {"Action": "PutUserPolicy", "UserName": name, "PolicyName": "p", "Version": "2010-05-08",
                                  "PolicyDocument": json.dumps({"Version": "2012-10-17", "Statement": statements})})
        return akid

    def presigned(akid, path):
        return f"{path}?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential={akid}%2F20261123%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20261123T000000Z&X-Amz-Expires=300&X-Amz-SignedHeaders=host&X-Amz-Signature=00"
    try:
        reader = mkuser(uname, [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}])
        nobody = mkuser(uname2, [{"Effect": "Allow", "Action": "iam:GetUser", "Resource": "*"}])
        assert _s3(c, "test", "PUT", f"/{bucket}").status_code == 200
        assert _s3(c, "test", "PUT", f"/{bucket}/secret.txt", content=b"s").status_code == 200
        assert _s3(c, "test", "PUT", f"/{bucket}/pub/open.txt", content=b"o").status_code == 200
        assert c.get(f"/{bucket}/secret.txt").status_code == 200                                      # off: unsigned works as before

        assert c.put("/api/iam/aws/enforcement", json={"space": "enforce"}).status_code == 200
        den = c.get(f"/{bucket}/secret.txt")
        assert den.status_code == 403 and "AccessDenied" in den.text and "Access Denied" in den.text, den.text   # anonymous, no policy: denied
        pol = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/pub/*"}]}
        assert _s3(c, "test", "PUT", f"/{bucket}?policy", content=json.dumps(pol)).status_code in (200, 204)
        assert c.get(f"/{bucket}/pub/open.txt").status_code == 200                                    # public-read policy allows anonymous
        assert c.get(f"/{bucket}/secret.txt").status_code == 403                                      # ... only that prefix
        assert c.put(f"/{bucket}/pub/evil.txt", content=b"x").status_code == 403                      # ... and only GetObject
        assert c.delete(f"/{bucket}/pub/open.txt").status_code == 403
        assert c.get(f"/{bucket}?list-type=2").status_code == 403                                     # ListBucket not granted

        # presigned URLs resolve their signer, they are not anonymous
        assert c.get(presigned(reader, f"/{bucket}/secret.txt")).status_code == 200                   # signer has s3:GetObject
        nb = c.get(presigned(nobody, f"/{bucket}/secret.txt"))
        assert nb.status_code == 403 and uname2 in nb.text, nb.text                                   # signer named, so it was not treated as anonymous
        assert c.get(presigned(reader, f"/{bucket}/pub/open.txt")).status_code == 200

        # console / assets / unknown buckets are never gated
        for path in ("/", "/healthz", "/aws-console.html", "/static/x.js"):
            assert c.get(path).status_code != 403, path
        nb404 = c.get(f"/no-such-bucket-{tag}/k")
        assert nb404.status_code != 403 or "NoSuchBucket" in nb404.text

        # explicit Deny for everybody beats the public Allow
        pol["Statement"].append({"Effect": "Deny", "Principal": "*", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/pub/open.txt"})
        assert _s3(c, "test", "PUT", f"/{bucket}?policy", content=json.dumps(pol)).status_code in (200, 204)
        assert c.get(f"/{bucket}/pub/open.txt").status_code == 403
        assert c.put("/api/iam/aws/enforcement", json={"space": "enforce", "anonymousS3": "allow"}).status_code == 200
        assert c.get(f"/{bucket}/secret.txt").status_code == 200                                      # opt-out restores the old behaviour
        assert c.put("/api/iam/aws/enforcement", json={"space": "audit"}).status_code == 200
        assert c.get(f"/{bucket}/secret.txt").status_code == 200                                      # audit never blocks
        recs = c.get("/api/iam/aws/audit?limit=50").json()["records"]
        assert any(r["mode"] == "audit" and r["principal"] == "anonymous" and r["action"] == "s3:GetObject" for r in recs)
        assert c.put("/api/iam/aws/enforcement", json={"space": "off"}).status_code == 200
        assert c.get(f"/{bucket}/secret.txt").status_code == 200
    finally:
        c.put("/api/iam/aws/enforcement", json={"space": "off"})
        for k in ("secret.txt", "pub/open.txt", "pub/evil.txt"):
            _s3(c, "test", "DELETE", f"/{bucket}/{k}")
        _s3(c, "test", "DELETE", f"/{bucket}?policy"); _s3(c, "test", "DELETE", f"/{bucket}")
        for n in made:
            r = _q(c, "test", "iam", {"Action": "ListAccessKeys", "UserName": n, "Version": "2010-05-08"})
            for kid in re.findall(r"<AccessKeyId>(.*?)</AccessKeyId>", r.text):
                _q(c, "test", "iam", {"Action": "DeleteAccessKey", "UserName": n, "AccessKeyId": kid, "Version": "2010-05-08"})
            _q(c, "test", "iam", {"Action": "DeleteUserPolicy", "UserName": n, "PolicyName": "p", "Version": "2010-05-08"})
            _q(c, "test", "iam", {"Action": "DeleteUser", "UserName": n, "Version": "2010-05-08"})
