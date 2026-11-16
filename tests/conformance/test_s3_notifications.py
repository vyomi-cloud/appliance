"""S3 bucket notifications -> Lambda / SQS / SNS / EventBridge, through the real boto3 client against the in-process
wire router (= Nano / offline ingress).

Run: PYTHONPATH=. VYOMI_REPO=$PWD python3 tests/conformance/test_s3_notifications.py   (needs boto3)
"""
import io, json, os, sys, tempfile, time, zipfile
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test"); os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("CLOUDLEARN_STATE_FILE", os.path.join(tempfile.mkdtemp(), "s.sqlite3"))
os.environ["VYOMI_REPO"] = os.environ.get("VYOMI_REPO") or os.getcwd()
sys.path.insert(0, os.path.join(os.environ["VYOMI_REPO"], "examples", "enterprise-facilities-agent"))
import boto3
from facilities.server import start_in_process

PASS = FAIL = 0


def check(name, cond, extra=""):
    extra = str(extra) if True else extra
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"  FAIL {name} {str(extra)[:900]}")


def wait(fn, n=30):
    for _ in range(n):
        v = fn()
        if v: return v
        time.sleep(0.3)
    return None


ep = start_in_process()
mk = lambda s: boto3.client(s, endpoint_url=ep, region_name="us-east-1")
s3, lam, sqs, sns = mk("s3"), mk("lambda"), mk("sqs"), mk("sns")

# a Lambda that stores the S3 event it receives in a second bucket
CODE = '''
import os, boto3
def handler(event, context):
    r = event["Records"][0]
    boto3.client("s3").put_object(Bucket="s3n-docs", Key="seen/" + r["s3"]["object"]["key"].replace("/", "_") + "." + r["eventName"].replace(":", "_"), Body=b"x")
    return {}
'''
z = io.BytesIO()
with zipfile.ZipFile(z, "w") as f: f.writestr("h.py", CODE)
s3.create_bucket(Bucket="s3n-docs")   # free tier: 1 bucket per space, so everything shares it
lam.create_function(FunctionName="ingest", Runtime="python3.12", Role="arn:aws:iam::123456789012:role/r", Handler="h.handler",
                    Code={"ZipFile": z.getvalue()}, Environment={"Variables": {"AWS_ENDPOINT_URL": ep}})
lam.add_permission(FunctionName="ingest", StatementId="s3", Action="lambda:InvokeFunction", Principal="s3.amazonaws.com",
                      SourceArn="arn:aws:s3:::s3n-docs", SourceAccount="123456789012")
q = sqs.create_queue(QueueName="s3q")["QueueUrl"]
qarn = sqs.get_queue_attributes(QueueUrl=q, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
tarn = sns.create_topic(Name="s3t")["TopicArn"]
q2 = sqs.create_queue(QueueName="subq")["QueueUrl"]
sns.subscribe(TopicArn=tarn, Protocol="sqs", Endpoint=sqs.get_queue_attributes(QueueUrl=q2, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"])

cfg = {
    "LambdaFunctionConfigurations": [{"Id": "L", "LambdaFunctionArn": "arn:aws:lambda:us-east-1:123456789012:function:ingest",
        "Events": ["s3:ObjectCreated:*"], "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": "docs/"}, {"Name": "suffix", "Value": ".md"}]}}}],
    "QueueConfigurations": [{"Id": "Q", "QueueArn": qarn, "Events": ["s3:ObjectRemoved:*"]}],
    "TopicConfigurations": [{"Id": "T", "TopicArn": tarn, "Events": ["s3:ObjectCreated:Put"], "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": "t/"}]}}}],
}
s3.put_bucket_notification_configuration(Bucket="s3n-docs", NotificationConfiguration=cfg)
got = s3.get_bucket_notification_configuration(Bucket="s3n-docs")
check("Get returns Lambda config with filter", got["LambdaFunctionConfigurations"][0]["Filter"]["Key"]["FilterRules"][0]["Value"] == "docs/", got)
check("Get returns Queue + Topic configs", len(got["QueueConfigurations"]) == 1 and len(got["TopicConfigurations"]) == 1, got)

seen = lambda: [o["Key"] for o in s3.list_objects_v2(Bucket="s3n-docs", Prefix="seen/").get("Contents", [])]
s3.put_object(Bucket="s3n-docs", Key="docs/a.md", Body=b"hi")
check("upload invokes Lambda (matching prefix+suffix)", wait(lambda: any(k.startswith("seen/docs_a.md") and "ObjectCreated" in k for k in seen())), seen())
s3.put_object(Bucket="s3n-docs", Key="docs/b.txt", Body=b"hi"); s3.put_object(Bucket="s3n-docs", Key="other/c.md", Body=b"hi")
time.sleep(1.5)
check("suffix/prefix filters exclude non-matching keys", not any(k.startswith(("seen/docs_b", "seen/other_c")) for k in seen()), seen())

s3.put_object(Bucket="s3n-docs", Key="t/x", Body=b"hi")
msgs = wait(lambda: sqs.receive_message(QueueUrl=q2, MaxNumberOfMessages=10, WaitTimeSeconds=1).get("Messages"))
body = json.loads(msgs[0]["Body"]) if msgs else {}
body = json.loads(body["Message"]) if "Message" in body else body   # SNS envelope or raw delivery
rec = (body.get("Records") or [{}])[0]
check("SNS topic fan-out delivers real S3 event shape",
      rec.get("eventSource") == "aws:s3" and rec.get("eventName") == "ObjectCreated:Put" and rec["s3"]["bucket"]["name"] == "s3n-docs" and rec["s3"]["configurationId"] == "T" and not rec["s3"]["object"]["eTag"].startswith('"') and rec["s3"]["object"]["key"] == "t/x" and rec["s3"]["object"]["size"] == 2, rec)

s3.delete_object(Bucket="s3n-docs", Key="docs/a.md")
m = wait(lambda: [x for x in sqs.receive_message(QueueUrl=q, MaxNumberOfMessages=10, WaitTimeSeconds=1).get("Messages", [])
                  if "ObjectRemoved" in x["Body"]])
check("ObjectRemoved delivered to SQS", bool(m), m)

# EventBridge
eb = mk("events")
eb.put_rule(Name="s3r", EventPattern=json.dumps({"source": ["aws.s3"], "detail-type": ["Object Created"]}))
eb.put_targets(Rule="s3r", Targets=[{"Id": "1", "Arn": qarn}])
s3.put_bucket_notification_configuration(Bucket="s3n-docs", NotificationConfiguration={"EventBridgeConfiguration": {}})
check("EventBridgeConfiguration round-trips", "EventBridgeConfiguration" in s3.get_bucket_notification_configuration(Bucket="s3n-docs"))
s3.put_object(Bucket="s3n-docs", Key="k", Body=b"1")
m = wait(lambda: [x for x in sqs.receive_message(QueueUrl=q, MaxNumberOfMessages=10, WaitTimeSeconds=1).get("Messages", []) if "Object Created" in x["Body"]])
check("EventBridge rule receives 'Object Created'", bool(m), m)

# --- Nano substrate: the shared core router (InMemoryObjectStore + the msg/lam cross-wiring), no HTTP ------------------
from core.aws_wire_router import AwsWireRouter
nr = AwsWireRouter()
check("Nano router: S3 store is the in-memory substrate wired to msg/lam", nr.s3.msg_store is nr.msg and nr.s3.lam_store is nr.lam)
from core import sqs_core
nr.s3.buckets.setdefault("nb", {}) if hasattr(nr.s3, "buckets") else None
hdr = {"host": "s3.amazonaws.com"}
nr.handle("PUT", "/nb", {}, hdr, b"")
nr.msg.__class__  # noqa
sqs_core.dispatch(nr.msg, "AmazonSQS.CreateQueue", {"QueueName": "nq"})
nq = nr.msg.get_queue("nq")
xml = ('<NotificationConfiguration><QueueConfiguration><Id>NQ</Id><Queue>%s</Queue><Event>s3:ObjectCreated:*</Event>'
       '<Filter><S3Key><FilterRule><Name>suffix</Name><Value>.pdf</Value></FilterRule></S3Key></Filter></QueueConfiguration></NotificationConfiguration>' % "arn:aws:sqs:us-east-1:123456789012:nq").encode()
nr.handle("PUT", "/nb", {"notification": ""}, hdr, xml)
nr.handle("PUT", "/nb/a.pdf", {}, hdr, b"pdf"); nr.handle("PUT", "/nb/a.txt", {}, hdr, b"txt")
msgs = [m for m in list(nq.get("messages", [])) if "a.pdf" in json.dumps(m, default=str) and "ObjectCreated" in json.dumps(m, default=str)]
check("Nano router: ObjectCreated delivered to SQS, suffix filter applied", len(msgs) == 1 and "a.txt" not in json.dumps(list(nq.get("messages", [])), default=str), list(nq.get("messages", []))[:2])

print(f"\n{PASS} passed, {FAIL} failed"); sys.exit(1 if FAIL else 0)
