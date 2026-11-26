"""CLI side for validate-aws-v4-roundtrip.mjs (SDKPY=this file): the REAL `aws` CLI, endpoint only changed, same
interface as _aws_roundtrip_sdk.py: <svc> <create|describe|delete|prep> <name> -> one JSON line.
Covers the core services; any other svc exits 3 so the caller reports it as not driven."""
import json, os, subprocess, sys

EP = os.environ["VYOMI_BASE_URL"].rstrip("/")
ENV = {**os.environ, "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1", "AWS_PAGER": "", "AWS_EC2_METADATA_DISABLED": "true"}
svc, op, name = sys.argv[1:4]


def aws(*a, check=True):
    p = subprocess.run(["aws", "--endpoint-url", EP, "--output", "json", "--no-cli-pager", *a], capture_output=True, text=True, env=ENV)
    if check and p.returncode:
        raise SystemExit("aws %s: %s" % (" ".join(a[:2]), (p.stderr.strip().splitlines() or ["failed"])[-1][:200]))
    try:
        return json.loads(p.stdout) if p.stdout.strip() else {}
    except ValueError:
        return {}


def _simple(create, exists, delete):
    if op == "create": create(); return {}
    ex = bool(exists())
    if op == "describe": return {"exists": ex}
    if ex: delete()
    return {"deleted": ex}


def s3():
    return _simple(lambda: aws("s3api", "create-bucket", "--bucket", name), lambda: name in [b["Name"] for b in aws("s3api", "list-buckets").get("Buckets", [])], lambda: aws("s3api", "delete-bucket", "--bucket", name))


def sqs():
    url = lambda: next((u for u in aws("sqs", "list-queues", "--queue-name-prefix", name).get("QueueUrls", []) if u.rsplit("/", 1)[-1] == name), None)
    return _simple(lambda: aws("sqs", "create-queue", "--queue-name", name), url, lambda: aws("sqs", "delete-queue", "--queue-url", url()))


def sns():
    arn = lambda: next((t["TopicArn"] for t in aws("sns", "list-topics").get("Topics", []) if t["TopicArn"].endswith(":" + name)), None)
    return _simple(lambda: aws("sns", "create-topic", "--name", name), arn, lambda: aws("sns", "delete-topic", "--topic-arn", arn()))


def dynamodb():
    return _simple(lambda: aws("dynamodb", "create-table", "--table-name", name, "--attribute-definitions", "AttributeName=id,AttributeType=S", "--key-schema", "AttributeName=id,KeyType=HASH", "--billing-mode", "PAY_PER_REQUEST"),
                   lambda: name in aws("dynamodb", "list-tables").get("TableNames", []), lambda: aws("dynamodb", "delete-table", "--table-name", name))


def secretsmanager():
    return _simple(lambda: aws("secretsmanager", "create-secret", "--name", name, "--secret-string", "v"), lambda: name in [s["Name"] for s in aws("secretsmanager", "list-secrets").get("SecretList", [])],
                   lambda: aws("secretsmanager", "delete-secret", "--secret-id", name, "--force-delete-without-recovery"))


def iam():
    return _simple(lambda: aws("iam", "create-user", "--user-name", name), lambda: name in [u["UserName"] for u in aws("iam", "list-users").get("Users", [])], lambda: aws("iam", "delete-user", "--user-name", name))


def ssm():
    return _simple(lambda: aws("ssm", "put-parameter", "--name", "/" + name, "--value", "v", "--type", "String"), lambda: any(p["Name"] in (name, "/" + name) for p in aws("ssm", "describe-parameters").get("Parameters", [])),
                   lambda: aws("ssm", "delete-parameter", "--name", "/" + name))


def kinesis():
    return _simple(lambda: aws("kinesis", "create-stream", "--stream-name", name, "--shard-count", "1"), lambda: name in aws("kinesis", "list-streams").get("StreamNames", []), lambda: aws("kinesis", "delete-stream", "--stream-name", name))


def cloudwatch():
    return _simple(lambda: aws("logs", "create-log-group", "--log-group-name", name), lambda: name in [g["logGroupName"] for g in aws("logs", "describe-log-groups", "--log-group-name-prefix", name).get("logGroups", [])],
                   lambda: aws("logs", "delete-log-group", "--log-group-name", name))


def eventbridge():
    return _simple(lambda: aws("events", "create-event-bus", "--name", name), lambda: name in [b["Name"] for b in aws("events", "list-event-buses").get("EventBuses", [])], lambda: aws("events", "delete-event-bus", "--name", name))


if op == "prep":
    print("{}"); sys.exit(0)
if svc not in globals() or svc.startswith("_"):
    sys.stderr.write("CLI leg not implemented for %s\n" % svc); sys.exit(3)
print(json.dumps(globals()[svc]()))
