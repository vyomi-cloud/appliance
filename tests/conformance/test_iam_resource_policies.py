"""Resource-based policies + SCP/RCP fed to the AWS engine (core/iam_resource_policies.py): unit (fake stores, real engine) and end-to-end
through the real appliance app (bucket-policy explicit Deny, SQS queue-policy allow, enforce on/off)."""
import json, os, re, sys, types, uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")

from core import iam_resource_policies as rp
from core import iam_state_adapters as ad
from core.iam_engine import aws_eval

ACCT = "123456789012"
USER = f"arn:aws:iam::{ACCT}:user/alice"
OTHER = "arn:aws:iam::999999999999:user/mallory"


def allow_all(actions="*"):
    return [{"id": "p", "document": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": actions, "Resource": "*"}]}}]


def ev(action, resource, state, principal=None, **kw):
    p = principal or {"arn": USER, "type": "user", "account": ACCT, "policies": allow_all()}
    return aws_eval.evaluate({"action": action, "resource": resource, "principal": p, **kw}, state)


def fake_stores():
    pol = lambda **st: json.dumps({"Version": "2012-10-17", "Statement": [dict(Principal="*", Resource="*", **st)]})  # noqa: E731
    s3 = types.SimpleNamespace(account_id=ACCT, buckets={"bk": {"cfg": {"policy": pol(Effect="Deny", Action="s3:*")}, "tags": {"env": "prod"}}, "plain": {}},
                               account={"ecr": {"regions": {"us-east-1": {"repo": {"policy": pol(Effect="Allow", Action="ecr:*")}}}}})
    msg = types.SimpleNamespace(account_id=ACCT,
                                queues={"q": {"queue_arn": f"arn:aws:sqs:us-east-1:{ACCT}:q", "attributes": {"Policy": pol(Effect="Allow", Action="sqs:*")}}},
                                topics={"t": {"topic_arn": f"arn:aws:sns:us-east-1:{ACCT}:t", "attributes": {"Policy": pol(Effect="Deny", Action="sns:*")}}})
    root = {"Sid": "e", "Effect": "Allow", "Principal": {"AWS": f"arn:aws:iam::{ACCT}:root"}, "Action": "kms:*", "Resource": "*"}
    kms = types.SimpleNamespace(account_id=ACCT, aliases={"alias/open": "k-open"},
                                keys={"k-open": {"Policy": json.dumps({"Version": "2012-10-17", "Statement": [root]})},
                                      "k-closed": {"Policy": json.dumps({"Version": "2012-10-17", "Statement": [
                                          {"Effect": "Allow", "Principal": {"AWS": USER}, "Action": "kms:Encrypt", "Resource": "*"}]})}})
    sec = types.SimpleNamespace(account_id=ACCT, secrets={"s": {"arn": f"arn:aws:secretsmanager:us-east-1:{ACCT}:secret:s-AbCdEf", "resource_policy": pol(Effect="Deny", Action="secretsmanager:*")}})
    lam = types.SimpleNamespace(account_id=ACCT, _lambda_functions={"fn": {"arn": f"arn:aws:lambda:us-east-1:{ACCT}:function:fn", "policy_statements": {
        "x": {"Sid": "x", "Effect": "Allow", "Principal": {"AWS": OTHER}, "Action": "lambda:InvokeFunction", "Resource": f"arn:aws:lambda:us-east-1:{ACCT}:function:fn"}}}},
        _apigateway_apis={"abc": {"policy": pol(Effect="Deny", Action="execute-api:Invoke")}})
    return {"s3": s3, "msg": msg, "kms": kms, "sec": sec, "lam": lam}


def test_feed_keys_exact_arns_per_service():
    p = rp.aws_resource_policies(fake_stores())
    for arn in ("arn:aws:s3:::bk", f"arn:aws:ecr:us-east-1:{ACCT}:repository/repo", f"arn:aws:sqs:us-east-1:{ACCT}:q", f"arn:aws:sns:us-east-1:{ACCT}:t",
                f"arn:aws:kms:us-east-1:{ACCT}:key/k-open", f"arn:aws:kms:us-east-1:{ACCT}:alias/open",
                f"arn:aws:secretsmanager:us-east-1:{ACCT}:secret:s-AbCdEf", f"arn:aws:secretsmanager:us-east-1:{ACCT}:secret:s",
                f"arn:aws:lambda:us-east-1:{ACCT}:function:fn", f"arn:aws:execute-api:us-east-1:{ACCT}:abc"):
        assert arn in dict(p), arn
    assert "arn:aws:s3:::plain" not in dict(p)
    assert rp.aws_resource_tags(fake_stores())["arn:aws:s3:::bk"] == {"env": "prod"}


def test_lookup_widens_to_owner_but_stays_a_dict():
    p = rp.aws_resource_policies(fake_stores())
    assert p.get("arn:aws:s3:::bk/deep/key.txt") is p["arn:aws:s3:::bk"]
    assert p.get(f"arn:aws:lambda:us-east-1:{ACCT}:function:fn:live") is p[f"arn:aws:lambda:us-east-1:{ACCT}:function:fn"]
    assert p.get(f"arn:aws:execute-api:us-east-1:{ACCT}:abc/prod/GET/x") is p[f"arn:aws:execute-api:us-east-1:{ACCT}:abc"]
    assert p.get("arn:aws:s3:::nope/k") is None and p.get("*") is None


def test_bucket_policy_explicit_deny_beats_identity_allow_on_object_arn():
    st = {"account": ACCT, "resource_policies": rp.aws_resource_policies(fake_stores())}
    assert ev("s3:GetObject", "arn:aws:s3:::bk/k", st)["reason"] == "explicit_deny"
    assert ev("s3:GetObject", "arn:aws:s3:::plain/k", st)["allowed"] is True


def test_cross_account_needs_resource_policy_allow():
    st = {"account": ACCT, "resource_policies": rp.aws_resource_policies(fake_stores())}
    mal = {"arn": OTHER, "type": "user", "account": "999999999999", "policies": allow_all()}
    assert ev("lambda:InvokeFunction", f"arn:aws:lambda:us-east-1:{ACCT}:function:fn", st, mal, resource_account=ACCT)["allowed"] is True
    assert ev("lambda:InvokeFunction", f"arn:aws:lambda:us-east-1:{ACCT}:function:other", st, mal, resource_account=ACCT)["allowed"] is False


def test_sqs_queue_policy_grants_principal_without_identity_policy():
    st = {"account": ACCT, "resource_policies": {}}
    bare = {"arn": USER, "type": "user", "account": ACCT, "policies": []}
    q = f"arn:aws:sqs:us-east-1:{ACCT}:q"
    assert ev("sqs:SendMessage", q, st, bare)["allowed"] is False
    st["resource_policies"] = {q: {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": USER}, "Action": "sqs:SendMessage", "Resource": q}]}}
    assert ev("sqs:SendMessage", q, st, bare)["allowed"] is True
    assert ev("sqs:DeleteQueue", q, st, bare)["allowed"] is False


def test_kms_key_policy_must_enable_iam():
    stores = fake_stores()
    st = {"account": ACCT, **rp.aws_resource_state(stores)}
    open_k, closed_k = f"arn:aws:kms:us-east-1:{ACCT}:key/k-open", f"arn:aws:kms:us-east-1:{ACCT}:key/k-closed"
    assert ev("kms:Decrypt", open_k, st)["allowed"] is True                     # root statement enables IAM identity policies
    assert ev("kms:Decrypt", closed_k, st)["allowed"] is False                  # identity allow alone is not enough
    assert ev("kms:Encrypt", closed_k, st)["allowed"] is True                   # the key policy names the user directly
    assert ev("kms:Decrypt", f"arn:aws:kms:us-east-1:{ACCT}:alias/open", st)["allowed"] is True
    assert rp.kms_key_policy_enables_iam(None, ACCT) is False


def _org(store_account=ACCT, master=ACCT):
    ous = {"ou-1": {"id": "ou-1", "parent": "r-1"}}
    o = {"id": "o-x", "master_account_id": master, "roots": {"r-1": {"id": "r-1"}}, "ous": ous,
         "accounts": {master: {"id": master, "parent": "r-1"}, store_account: {"id": store_account, "parent": "ou-1"}},
         "attachments": {"r-1": ["p-full"], "ou-1": ["p-deny-s3"]}}
    pols = {"p-full": {"type": "SERVICE_CONTROL_POLICY", "content": json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]})},
            "p-deny-s3": {"type": "SERVICE_CONTROL_POLICY", "content": json.dumps({"Version": "2012-10-17", "Statement": [
                {"Effect": "Allow", "Action": "*", "Resource": "*"}, {"Effect": "Deny", "Action": "s3:Delete*", "Resource": "*"}]})}}
    return types.SimpleNamespace(account_id=store_account, extras={"org": o}, org_policies=pols)


def test_scp_levels_root_to_account_and_management_exemption():
    member = _org(store_account="222233334444")
    lv = rp.org_levels(member)
    assert len(lv["scps"]) == 2 and lv["rcps"] == []
    st = {"account": "222233334444", "scps": lv["scps"]}
    pr = {"arn": "arn:aws:iam::222233334444:user/m", "type": "user", "account": "222233334444", "policies": allow_all()}
    assert ev("s3:DeleteObject", "arn:aws:s3:::b/k", st, pr)["reason"] == "explicit_deny"
    assert ev("s3:GetObject", "arn:aws:s3:::b/k", st, pr)["allowed"] is True
    mgmt = _org(store_account=ACCT, master=ACCT)                              # same account as management: exempt
    assert rp.org_levels(mgmt) == {"scps": [], "rcps": []}
    mgmt.extras["org"]["scp_apply_to_management"] = True
    mgmt.extras["org"]["accounts"][ACCT]["parent"] = "ou-1"
    assert len(rp.org_levels(mgmt)["scps"]) == 2
    assert rp.org_levels(types.SimpleNamespace(account_id=ACCT, extras={}, org_policies={})) == {"scps": [], "rcps": []}


def test_aws_state_hook_merges_extras_and_survives_failures():
    from core.iam_store import InMemoryIamStore
    s = InMemoryIamStore()
    rp.set_host_stores(lambda: fake_stores())
    try:
        st = ad.aws_state(s)
        assert "arn:aws:s3:::bk" in st["resource_policies"] and st["resource_policy_requires_grant"]
        rp.set_host_stores(lambda: 1 / 0)
        assert ad.aws_state(s)["resource_policies"] == {}                       # hook failure -> identity-only, never an exception
    finally:
        rp.set_host_stores(None)


# ----------------------------------------------------------------------------- end to end through the real app
@pytest.fixture(scope="module")
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    yield c
    c.put("/api/iam/aws/enforcement", json={"space": "off"})


def _sig(akid, svc):
    return f"AWS4-HMAC-SHA256 Credential={akid}/20261123/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=00"


def _q(c, akid, svc, form):
    return c.post("/", data=form, headers={"Authorization": _sig(akid, svc), "X-Amz-Date": "20261123T000000Z",
                                          "Content-Type": "application/x-www-form-urlencoded"})


def _s3(c, akid, method, path, **kw):
    return c.request(method, path, headers={"Authorization": _sig(akid, "s3"), "X-Amz-Date": "20261123T000000Z"}, **kw)


def test_e2e_bucket_policy_deny_and_sqs_queue_policy_allow(client):
    c = client
    tag = uuid.uuid4().hex[:8]
    uname, uname2, bucket, queue = "rp-a-" + tag, "rp-b-" + tag, "rp-bkt-" + tag, "rp-q-" + tag
    made = []

    def mkuser(name, statements):
        assert _q(c, "test", "iam", {"Action": "CreateUser", "UserName": name, "Version": "2010-05-08"}).status_code == 200
        made.append(name)
        k = _q(c, "test", "iam", {"Action": "CreateAccessKey", "UserName": name, "Version": "2010-05-08"})
        akid = re.search(r"<AccessKeyId>(.*?)</AccessKeyId>", k.text).group(1)
        arn = re.search(r"<Arn>(.*?)</Arn>", _q(c, "test", "iam", {"Action": "GetUser", "UserName": name, "Version": "2010-05-08"}).text).group(1)
        if statements:
            _q(c, "test", "iam", {"Action": "PutUserPolicy", "UserName": name, "PolicyName": "p", "Version": "2010-05-08",
                                  "PolicyDocument": json.dumps({"Version": "2012-10-17", "Statement": statements})})
        return akid, arn
    try:
        a_key, a_arn = mkuser(uname, [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}])
        b_key, b_arn = mkuser(uname2, [{"Effect": "Allow", "Action": "iam:GetUser", "Resource": "*"}])      # nothing on SQS
        assert _s3(c, "test", "PUT", f"/{bucket}").status_code == 200
        assert _s3(c, "test", "PUT", f"/{bucket}/k.txt", content=b"hello").status_code == 200
        q = _q(c, "test", "sqs", {"Action": "CreateQueue", "QueueName": queue, "Version": "2012-11-05"})
        assert q.status_code == 200
        qurl = re.search(r"<QueueUrl>(.*?)</QueueUrl>", q.text).group(1)
        qarn = f"arn:aws:sqs:us-east-1:{ACCT}:{queue}"
        send = {"Action": "SendMessage", "QueueUrl": qurl, "MessageBody": "hi", "Version": "2012-11-05"}

        assert c.put("/api/iam/aws/enforcement", json={"space": "enforce"}).status_code == 200
        assert _s3(c, a_key, "GET", f"/{bucket}/k.txt").status_code == 200                                # identity s3:* allows
        deny = {"Version": "2012-10-17", "Statement": [{"Sid": "NoAlice", "Effect": "Deny", "Principal": {"AWS": a_arn},
                                                         "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/*"}]}
        assert _s3(c, "test", "PUT", f"/{bucket}?policy", content=json.dumps(deny)).status_code in (200, 204)
        den = _s3(c, a_key, "GET", f"/{bucket}/k.txt")
        assert den.status_code == 403 and "AccessDenied" in den.text, den.text                           # explicit Deny in the bucket policy
        assert _s3(c, "test", "GET", f"/{bucket}/k.txt").status_code == 200                              # root (unregistered key) unaffected
        assert _s3(c, a_key, "PUT", f"/{bucket}/other.txt", content=b"x").status_code == 200              # only GetObject is denied

        assert _q(c, b_key, "sqs", send).status_code == 403                                               # no identity grant, no queue policy
        pol = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": b_arn}, "Action": "sqs:SendMessage", "Resource": qarn}]}
        assert _q(c, "test", "sqs", {"Action": "SetQueueAttributes", "QueueUrl": qurl, "Attribute.1.Name": "Policy",
                                     "Attribute.1.Value": json.dumps(pol), "Version": "2012-11-05"}).status_code == 200
        assert _q(c, b_key, "sqs", send).status_code == 200                                               # queue policy grants the principal
        assert _q(c, b_key, "sqs", {"Action": "PurgeQueue", "QueueUrl": qurl, "Version": "2012-11-05"}).status_code == 403
        assert c.put("/api/iam/aws/enforcement", json={"space": "off"}).status_code == 200
        assert _s3(c, a_key, "GET", f"/{bucket}/k.txt").status_code == 200                                # enforcement off: nothing changes
    finally:
        c.put("/api/iam/aws/enforcement", json={"space": "off"})
        _s3(c, "test", "DELETE", f"/{bucket}/k.txt"); _s3(c, "test", "DELETE", f"/{bucket}/other.txt"); _s3(c, "test", "DELETE", f"/{bucket}?policy"); _s3(c, "test", "DELETE", f"/{bucket}")
        _q(c, "test", "sqs", {"Action": "DeleteQueue", "QueueUrl": locals().get("qurl", ""), "Version": "2012-11-05"})
        for n in made:
            r = _q(c, "test", "iam", {"Action": "ListAccessKeys", "UserName": n, "Version": "2010-05-08"})
            for kid in re.findall(r"<AccessKeyId>(.*?)</AccessKeyId>", r.text):
                _q(c, "test", "iam", {"Action": "DeleteAccessKey", "UserName": n, "AccessKeyId": kid, "Version": "2010-05-08"})
            _q(c, "test", "iam", {"Action": "DeleteUserPolicy", "UserName": n, "PolicyName": "p", "Version": "2010-05-08"})
            _q(c, "test", "iam", {"Action": "DeleteUser", "UserName": n, "Version": "2010-05-08"})


def test_e2e_every_service_policy_reaches_the_feed_from_the_live_stores(client):
    c, tag = client, uuid.uuid4().hex[:8]
    H = lambda svc, **h: {"Authorization": _sig("test", svc), **h}                      # noqa: E731
    pol = lambda a: json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": f"arn:aws:iam::{ACCT}:root"}, "Action": a, "Resource": "*"}]})  # noqa: E731
    j = lambda svc, t, d: c.post("/", content=json.dumps(d), headers=H(svc, **{"X-Amz-Target": t, "Content-Type": "application/x-amz-json-1.1"}))  # noqa: E731
    sec, topic, fn, repo = "rp-s-" + tag, "rp-t-" + tag, "rp-f-" + tag, "rp-r-" + tag
    kid = None
    try:
        kid = json.loads(j("kms", "TrentService.CreateKey", {"Policy": pol("kms:Encrypt")}).text)["KeyMetadata"]["KeyId"]
        j("secretsmanager", "secretsmanager.CreateSecret", {"Name": sec, "SecretString": "x"})
        j("secretsmanager", "secretsmanager.PutResourcePolicy", {"SecretId": sec, "ResourcePolicy": pol("secretsmanager:GetSecretValue")})
        c.post("/", data={"Action": "CreateTopic", "Name": topic, "Attributes.entry.1.key": "Policy", "Attributes.entry.1.value": pol("sns:Publish"), "Version": "2010-03-31"},
               headers=H("sns", **{"Content-Type": "application/x-www-form-urlencoded"}))
        c.post("/2015-03-31/functions", content=json.dumps({"FunctionName": fn, "Runtime": "python3.12", "Role": f"arn:aws:iam::{ACCT}:role/x", "Handler": "a.b",
                                                            "Code": {"ZipFile": "UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA=="}}), headers=H("lambda", **{"Content-Type": "application/json"}))
        c.post(f"/2015-03-31/functions/{fn}/policy", content=json.dumps({"StatementId": "s1", "Action": "lambda:InvokeFunction", "Principal": "arn:aws:iam::999999999999:root"}),
               headers=H("lambda", **{"Content-Type": "application/json"}))
        j("ecr", "AmazonEC2ContainerRegistry_V20150921.CreateRepository", {"repositoryName": repo})
        j("ecr", "AmazonEC2ContainerRegistry_V20150921.SetRepositoryPolicy", {"repositoryName": repo, "policyText": pol("ecr:*")})
        api = json.loads(c.post("/restapis", content=json.dumps({"name": "rp-api-" + tag, "policy": pol("execute-api:Invoke")}),
                                headers=H("apigateway", **{"Content-Type": "application/json"})).text)["id"]
        got = rp.aws_state_extras(types.SimpleNamespace(account_id=ACCT, extras={}, org_policies={}))["resource_policies"]
        for arn in (f"arn:aws:kms:us-east-1:{ACCT}:key/{kid}", f"arn:aws:secretsmanager:us-east-1:{ACCT}:secret:{sec}", f"arn:aws:sns:us-east-1:{ACCT}:{topic}",
                    f"arn:aws:lambda:us-east-1:{ACCT}:function:{fn}", f"arn:aws:ecr:us-east-1:{ACCT}:repository/{repo}", f"arn:aws:execute-api:us-east-1:{ACCT}:{api}"):
            assert arn in got, arn
    finally:
        j("ecr", "AmazonEC2ContainerRegistry_V20150921.DeleteRepository", {"repositoryName": repo, "force": True})
        c.delete(f"/2015-03-31/functions/{fn}", headers=H("lambda"))
        c.post("/", data={"Action": "DeleteTopic", "TopicArn": f"arn:aws:sns:us-east-1:{ACCT}:{topic}", "Version": "2010-03-31"}, headers=H("sns", **{"Content-Type": "application/x-www-form-urlencoded"}))
        j("secretsmanager", "secretsmanager.DeleteSecret", {"SecretId": sec, "ForceDeleteWithoutRecovery": True})
        if kid:
            j("kms", "TrentService.ScheduleKeyDeletion", {"KeyId": kid, "PendingWindowInDays": 7})
        if "api" in locals():
            c.delete(f"/restapis/{api}", headers=H("apigateway"))
