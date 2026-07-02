"""AwsWireRouter conformance — the relay/bridge front door.

Proves that a request shaped EXACTLY as an unmodified SDK sends it (SigV4
credential scope + X-Amz-Target / Query Action) is routed to the correct proven
core and served in that core's native wire. This is the acceptance gate for the
external-app → in-browser-sim path (the relay's reason to exist).

Same file, two substrates, must be green on both:
  - host CPython (proxy for the Pro/Max front-end)
  - Pyodide / WASM (the Nano relay tab)

Run on host:    python3 tests/conformance/test_aws_wire_router.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core.aws_wire_router import AwsWireRouter
except ImportError:  # pragma: no cover - Pyodide flat layout
    from aws_wire_router import AwsWireRouter  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _sig(service):
    """A SigV4 Authorization header for `service` — the router reads the
    credential scope for routing but never verifies the signature."""
    return ("AWS4-HMAC-SHA256 "
            f"Credential=AKIAEXAMPLE/20260626/us-east-1/{service}/aws4_request, "
            "SignedHeaders=host;x-amz-date, Signature=deadbeef")


def _body(resp):
    b = resp["body"]
    return b.decode() if isinstance(b, (bytes, bytearray)) else b


def run() -> int:
    R = AwsWireRouter()

    # ── S3: native method+path wire, no X-Amz-Target (routes via s3 scope) ──
    h_s3 = {"Authorization": _sig("s3")}
    r = R.handle("PUT", "/photos", {}, h_s3, b"")
    _check("s3 create bucket 200", r["status"] == 200)
    put = R.handle("PUT", "/photos/cat.txt", {}, h_s3, b"meow")
    _check("s3 put object 200", put["status"] == 200)
    _check("s3 put returns ETag", "etag" in {k.lower() for k in put["headers"]})
    got = R.handle("GET", "/photos/cat.txt", {}, h_s3, b"")
    _check("s3 get round-trips body", got["body"] == b"meow")
    lst = R.handle("GET", "/photos", {}, h_s3, b"")
    _check("s3 list shows the key", "cat.txt" in _body(lst))

    # routing precedence: even unsigned, S3 is the path-style default
    anon = R.handle("GET", "/photos/cat.txt", {}, {}, b"")
    _check("s3 default route when unsigned", anon["body"] == b"meow")

    # ── DynamoDB: JSON wire via X-Amz-Target ──
    def ddb(action, payload):
        return R.handle("POST", "/", {},
                        {"Authorization": _sig("dynamodb"),
                         "X-Amz-Target": "DynamoDB_20120810." + action,
                         "Content-Type": "application/x-amz-json-1.0"},
                        json.dumps(payload).encode())
    ct = ddb("CreateTable", {"TableName": "users",
             "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
             "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
             "BillingMode": "PAY_PER_REQUEST"})
    _check("ddb create table 200", ct["status"] == 200)
    pi = ddb("PutItem", {"TableName": "users", "Item": {"id": {"S": "u1"}, "age": {"N": "30"}}})
    _check("ddb put item 200", pi["status"] == 200)
    gi = ddb("GetItem", {"TableName": "users", "Key": {"id": {"S": "u1"}}})
    item = json.loads(_body(gi))["Item"]
    _check("ddb get item types preserved", item["age"]["N"] == "30")
    _check("ddb json content-type", gi["headers"]["content-type"] == "application/x-amz-json-1.0")

    # ── KMS: JSON wire (TrentService.*) — encrypt/decrypt round-trip ──
    def kms(action, payload):
        return R.handle("POST", "/", {},
                        {"Authorization": _sig("kms"),
                         "X-Amz-Target": "TrentService." + action}, json.dumps(payload).encode())
    key = json.loads(_body(kms("CreateKey", {})))["KeyMetadata"]["KeyId"]
    enc = json.loads(_body(kms("Encrypt", {"KeyId": key, "Plaintext": "c2VjcmV0"})))  # "secret"
    dec = json.loads(_body(kms("Decrypt", {"CiphertextBlob": enc["CiphertextBlob"]})))
    _check("kms decrypt recovers plaintext", dec["Plaintext"] == "c2VjcmV0")
    _check("kms decrypt recovers key id", dec["KeyId"].endswith(key))
    _check("kms json-1.1 content-type",
           kms("ListKeys", {})["headers"]["content-type"] == "application/x-amz-json-1.1")

    # ── Secrets Manager: JSON wire (secretsmanager.*) ──
    def sec(action, payload):
        return R.handle("POST", "/", {},
                        {"Authorization": _sig("secretsmanager"),
                         "X-Amz-Target": "secretsmanager." + action}, json.dumps(payload).encode())
    sec("CreateSecret", {"Name": "db/pw", "SecretString": "hunter2"})
    gv = json.loads(_body(sec("GetSecretValue", {"SecretId": "db/pw"})))
    _check("secrets value round-trips", gv["SecretString"] == "hunter2")

    # ── SQS: JSON wire (AmazonSQS.*) ──
    def sqs(action, payload):
        return R.handle("POST", "/", {},
                        {"Authorization": _sig("sqs"),
                         "X-Amz-Target": "AmazonSQS." + action,
                         "Content-Type": "application/x-amz-json-1.0"}, json.dumps(payload).encode())
    qurl = json.loads(_body(sqs("CreateQueue", {"QueueName": "jobs"})))["QueueUrl"]
    sqs("SendMessage", {"QueueUrl": qurl, "MessageBody": "hello"})
    recv = json.loads(_body(sqs("ReceiveMessage", {"QueueUrl": qurl})))
    _check("sqs send/receive round-trips", recv["Messages"][0]["Body"] == "hello")

    # ── IAM: Query+XML wire (form body, signed iam scope) ──
    def query(service, params):
        body = "&".join(f"{k}={v}" for k, v in params.items())
        return R.handle("POST", "/", {},
                        {"Authorization": _sig(service),
                         "Content-Type": "application/x-www-form-urlencoded"}, body.encode())
    cu = query("iam", {"Action": "CreateUser", "UserName": "alice", "Version": "2010-05-08"})
    _check("iam create user 200 + XML", cu["status"] == 200 and "<UserName>alice</UserName>" in _body(cu))
    lu = query("iam", {"Action": "ListUsers", "Version": "2010-05-08"})
    _check("iam list shows alice", "alice" in _body(lu))
    _check("iam xml content-type", lu["headers"]["content-type"] == "text/xml")

    # ── RDS: Query+XML wire ──
    cdb = query("rds", {"Action": "CreateDBInstance", "DBInstanceIdentifier": "appdb",
                "Engine": "postgres", "DBInstanceClass": "db.t3.micro",
                "AllocatedStorage": "20", "Version": "2014-10-31"})
    _check("rds create db 200 + XML", cdb["status"] == 200 and "<DBInstanceIdentifier>appdb</DBInstanceIdentifier>" in _body(cdb))
    ddbs = query("rds", {"Action": "DescribeDBInstances", "Version": "2014-10-31"})
    _check("rds describe shows appdb", "appdb" in _body(ddbs))

    # ── SNS → SQS fan-out, ACROSS the router's shared MessagingStore ──
    topic = _xml(_body(query("sns", {"Action": "CreateTopic", "Name": "alerts", "Version": "2010-03-31"})), "TopicArn")
    evq = json.loads(_body(sqs("CreateQueue", {"QueueName": "alert-q"})))["QueueUrl"]
    # subscribe the SQS queue ARN (derive from url) to the topic
    arn = "arn:aws:sqs:us-east-1:123456789012:" + evq.rsplit("/", 1)[-1]
    query("sns", {"Action": "Subscribe", "TopicArn": topic, "Protocol": "sqs",
                  "Endpoint": arn, "Version": "2010-03-31"})
    query("sns", {"Action": "Publish", "TopicArn": topic, "Message": "disk-full", "Version": "2010-03-31"})
    fan = json.loads(_body(sqs("ReceiveMessage", {"QueueUrl": evq})))
    _check("sns publish fans out into the sqs queue (shared store)",
           "Messages" in fan and "disk-full" in fan["Messages"][0]["Body"])

    # ── routing: unsigned Query Publish still routes to SNS via the Action table ──
    body = "Action=ListTopics&Version=2010-03-31"
    unsigned = R.handle("POST", "/", {},
                        {"Content-Type": "application/x-www-form-urlencoded"}, body.encode())
    _check("unsigned query routes to sns by Action", "<ListTopicsResult>" in _body(unsigned))

    print("\nRESULT: PASS — AwsWireRouter routes all 7 services to the proven cores "
          "(native SDK wire) on this substrate.")
    return 0


def _xml(xml, tag):
    import re
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
    return m.group(1) if m else ""


if __name__ == "__main__":
    raise SystemExit(run())
