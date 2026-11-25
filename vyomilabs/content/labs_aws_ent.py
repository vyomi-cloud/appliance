"""Enterprise additions to the AWS course: shared IAM Enforce helper, least-privilege policy per layer with an audit-log 'find what is missing' step,
failure labs and the Ship it capstone. Appended to LAB by labs_aws.extend(); every block here is verified by `python -m vyomilabs.labrun aws ...`
(blocks marked needs_appliance run against the full appliance: `--endpoint http://host:port`)."""

IAMKIT = r'''
"""Least-privilege helper for the IAM Enforce labs: make a principal with an inline policy, switch the simulator to Enforce, and read the audit log."""
import json
import os
import urllib.request

import boto3

EP = os.environ["AWS_ENDPOINT_URL"]
ACCOUNT = "123456789012"


def _admin(method, path, body=None):
    req = urllib.request.Request(EP + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read() or b"{}")


def enforce(mode="enforce"):
    """off | audit | enforce for the whole space. The root test credentials stay allowed; only the IAM users you create are judged."""
    return _admin("PUT", "/api/iam/aws/enforcement", {"space": mode})


def allow(actions, resources="*"):
    return {"Effect": "Allow", "Action": actions if isinstance(actions, list) else [actions], "Resource": resources}


def _put(p):
    boto3.client("iam").put_user_policy(UserName=p["name"], PolicyName=p["name"] + "-least-privilege",
                                        PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": p["statements"]}))


def principal(name, statements):
    """Create (or reset) IAM user `name` with ONE inline policy and return it with fresh access keys."""
    iam = boto3.client("iam")
    try:
        iam.create_user(UserName=name)
    except iam.exceptions.EntityAlreadyExistsException:
        pass
    for k in iam.list_access_keys(UserName=name)["AccessKeyMetadata"]:
        iam.delete_access_key(UserName=name, AccessKeyId=k["AccessKeyId"])
    p = {"name": name, "arn": "arn:aws:iam::%s:user/%s" % (ACCOUNT, name), "statements": list(statements)}
    _put(p)
    k = iam.create_access_key(UserName=name)["AccessKey"]
    p.update(key=k["AccessKeyId"], secret=k["SecretAccessKey"])
    return p


def grant(p, statements):
    """Add statements to the principal's policy."""
    p["statements"] = p["statements"] + list(statements)
    _put(p)


def client(service, p, **kw):
    """A boto3 client that signs as principal p."""
    return boto3.client(service, aws_access_key_id=p["key"], aws_secret_access_key=p["secret"], **kw)


def last_audit_id():
    recs = _admin("GET", "/api/iam/aws/audit?limit=1")["records"]
    return recs[0]["id"] if recs else 0


def audit(p, since=0):
    """Every authorization decision the simulator made for principal p after audit id `since`, oldest first."""
    recs = _admin("GET", "/api/iam/aws/audit?limit=500")["records"]
    return sorted([r for r in recs if r["principal"] == p["arn"] and r["id"] > since], key=lambda r: r["id"])


def denied(p, since=0):
    """(action, resource) pairs that were refused: this is what 'find what is missing' reads."""
    return sorted({(r["action"], r["resource"]) for r in audit(p, since) if r["decision"] == "deny"})


def missing_statements(p, since=0):
    """One Allow statement per refused (action, resource): the narrowest fix the audit log can justify."""
    return [allow(a, r) for a, r in denied(p, since)]


def settle(p, run, max_rounds=8):
    """Run `run()` as principal p. While it is refused, read the audit log, grant exactly what it names and run again.
    Returns the statements that had to be added: if you wrote the policy right this is empty."""
    added = []
    for _ in range(max_rounds):
        since = last_audit_id()
        try:
            run()
            return added
        except Exception as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
            if code not in ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "403") and "403" not in str(e):
                raise
            fix = missing_statements(p, since)
            assert fix, "refused but the audit log names nothing: %s" % e
            grant(p, fix)
            added += fix
    raise AssertionError("policy still incomplete after %d rounds: %s" % (max_rounds, added))
'''

CHAOS = r'''
"""Failure injection for the failure labs: make the next N calls to an operation fail the way the real service does."""
import json

from botocore.awsrequest import AWSResponse


class _Raw:
    def __init__(self, body):
        self._b = body

    def stream(self, *a, **k):
        yield self._b

    def read(self, *a, **k):
        return self._b


def inject(client, operation, times, status=429, code="ThrottlingException", message="Too many requests"):
    """Fail the next `times` calls of `operation` (e.g. "Converse") on `client`. Returns a counter dict {'left','seen'}; call .remove() to stop."""
    service = client.meta.service_model.endpoint_prefix
    event = "before-send.%s.%s" % (client.meta.service_model.service_id.hyphenize(), operation)
    state = {"left": times, "seen": 0}

    def handler(request, **kw):
        state["seen"] += 1
        if state["left"] > 0:
            state["left"] -= 1
            body = json.dumps({"__type": code, "message": message}).encode()
            return AWSResponse(request.url, status, {"x-amzn-ErrorType": code, "content-type": "application/json"}, _Raw(body))

    client.meta.events.register(event, handler)
    state["remove"] = lambda: client.meta.events.unregister(event, handler)
    return state
'''


def extend(LAB, b):
    BOTH, MESH = ["nano", "mesh"], ["mesh"]
    N_IAM = "IAM Enforce and its audit log exist only on a Mesh (the Nano console has no enforcement engine); on Nano this step is read-only prose."

    # ───────────────────────── chapter 10: models ─────────────────────────
    LAB[10] += [
     b("Meter, retry and limit the model client", "The model client you wrote already retries throttling with backoff and meters notional cost against a budget. This block proves both behaviours instead of describing them: it makes the service throttle on purpose, shows the retry recovering, shows the retry giving up with a clear error (never an endless loop), and shows the budget refusing a call before it is made.",
       "chaos.py", CHAOS, kind="failure"),
     b("Failure lab: throttling and a spent budget", "Break it on purpose. Two throttles in a row: the third attempt must succeed. A model that throttles forever: the client must stop and say so. A spent budget: the call must be refused before it reaches the model. Every outcome is asserted, not printed and hoped for.",
       "fail_models.py", r'''
from botocore.exceptions import ClientError

import vymodels
from chaos import inject

rt = vymodels._rt

# 1. Transient throttling: two refusals, then success.
f = inject(rt, "Converse", times=2)
reply = vymodels.chat("Reply with the single word OK.")
f["remove"]()
assert reply.strip() and f["seen"] == 3, "expected 3 attempts (2 throttled + 1 ok), saw %d" % f["seen"]
print("transient throttling: recovered after", f["seen"], "attempts")

# 2. Permanent throttling: the client must give up after MAX_ATTEMPTS with a clear error.
f = inject(rt, "Converse", times=99)
try:
    vymodels.chat("Reply with the single word OK.")
    raise AssertionError("a model that always throttles must not return an answer")
except vymodels.ModelUnavailable as e:
    print("permanent throttling: gave up cleanly ->", e)
assert f["seen"] == vymodels.MAX_ATTEMPTS, "must stop after exactly MAX_ATTEMPTS attempts, saw %d" % f["seen"]
f["remove"]()

# 3. A non-retryable error must NOT be retried (retrying a bad request only burns budget).
f = inject(rt, "Converse", times=99, status=400, code="ValidationException", message="bad request")
try:
    vymodels.chat("hello")
    raise AssertionError("a ValidationException must surface")
except Exception as e:
    assert isinstance(e, ClientError) and f["seen"] == 1, "validation errors must fail on the first attempt"
f["remove"]()
print("validation error: failed fast after", 1, "attempt")

# 4. The budget refuses before the call is made.
old = vymodels.BUDGET
vymodels.BUDGET = vymodels.Budget(0.000001)
try:
    vymodels.chat("Reply with the single word OK.")        # first call is allowed and uses the budget up
    try:
        vymodels.chat("Reply with the single word OK.")
        raise AssertionError("second call must be refused: the budget is spent")
    except vymodels.BudgetExceeded as e:
        print("budget limit: refused ->", e)
finally:
    vymodels.BUDGET = old
print("failure lab passed: retries are bounded, validation fails fast, spend is capped")
''', run="python fail_models.py", expect="failure lab passed", kind="failure",
       nano_note="Runs on Nano too: the failures are injected in your own client, not in the service."),
     b("Give the model client its own identity", "Helper used by every later least-privilege step: it creates an IAM user with ONE inline policy, switches the simulator to Enforce, and reads the audit log. The root test credentials stay allowed, so only the principals you create are judged.",
       "iamkit.py", IAMKIT, kind="iam", edition=MESH, nano_note=N_IAM),
     b("Least privilege for the model caller, from the audit log", "Start with a policy that is too thin on purpose: the caller may invoke the two models and nothing else. Call the model as that identity, get refused, and read the audit log to find exactly which action and resource were missing. `settle()` grants only what the log names and re-runs, so the final policy is the narrowest that works. Note: the simulator's Converse check also asks for `bedrock:ApplyGuardrail` (the IAM catalog lists it as a related action); on real AWS it is only needed when a guardrail is attached, so check your account's behaviour before copying this policy.",
       "iam_models.py", r'''
import json

from botocore.exceptions import ClientError

import iamkit
import vymodels
from iamkit import allow

iamkit.enforce("enforce")
arn = lambda m: "arn:aws:bedrock:us-east-1::foundation-model/" + m
p = iamkit.principal("agent-model-caller", [allow("bedrock:InvokeModel", [arn(vymodels.CHAT_MODEL), arn(vymodels.EMBED_MODEL)])])
rt = iamkit.client("bedrock-runtime", p)
req = dict(modelId=vymodels.CHAT_MODEL, messages=[{"role": "user", "content": [{"text": "Reply with the single word OK."}]}])

since = iamkit.last_audit_id()
try:
    rt.converse(**req)
    first = "allowed"
except ClientError as e:
    first = e.response["Error"]["Code"]
missing = iamkit.denied(p, since)
print("first call:", first, "| the audit log says the policy is missing:", [a for a, _ in missing])
assert first != "allowed" and missing, "the deliberately thin policy must be refused and the audit log must say why"

added = iamkit.settle(p, lambda: rt.converse(**req))
print("settled by granting:", [(s["Action"][0]) for s in added])
assert rt.converse(**req)["stopReason"], "the model call must work with the settled policy"

# Least privilege means the policy is also NARROW: another model, and any control-plane action, stay refused.
since = iamkit.last_audit_id()
for label, call in (("other model", lambda: rt.invoke_model(modelId="vyomi.not-granted", body=json.dumps({"inputText": "x"}))),
                    ("create guardrail", lambda: iamkit.client("bedrock", p).create_guardrail(name="x", blockedInputMessaging="a", blockedOutputsMessaging="b"))):
    try:
        call()
        raise AssertionError(label + " must be refused")
    except ClientError as e:
        assert e.response["Error"]["Code"] in ("AccessDenied", "AccessDeniedException", "403"), e
        print("refused as intended:", label)
print("audit trail holds", len([r for r in iamkit.audit(p) if r["decision"] == "deny"]), "denials and",
      len([r for r in iamkit.audit(p) if r["decision"] == "allow"]), "allows for", p["name"])
print("least-privilege model caller verified")
''', run="python iam_models.py", expect="least-privilege model caller verified", needs_appliance=True, kind="iam", edition=MESH, nano_note=N_IAM),
    ]

    # ───────────────────────── chapter 7: tools ─────────────────────────
    LAB[7] += [
     b("Failure lab: hostile input and a replayed approval", "The tools are called with arguments a model wrote, so treat them as hostile. This block throws a SQL-injection string, a wrong type, a missing field and an oversized summary at the tools and asserts each is refused before any data is touched. Then it approves the same request twice and asserts exactly one work order exists: the conditional write makes the second call a harmless replay.",
       "tool_contract.py", r'''
import json

import boto3

lam, ddb = boto3.client("lambda"), boto3.client("dynamodb")


def call(fn, payload):
    r = lam.invoke(FunctionName=fn, Payload=json.dumps(payload).encode())
    return json.loads(r["Payload"].read())


# Read tool: bad input never reaches DynamoDB.
for bad in ("B-12'; DROP TABLE assets;--", "../../etc/passwd", "", None, 12, "b-12", "B-12 " + "x" * 400):
    out = call("facilities-asset-status", {"asset_id": bad})
    assert out.get("error") == "invalid_input", "hostile asset_id %r was not refused: %s" % (bad, out)
assert call("facilities-asset-status", {}).get("error") == "invalid_input"
print("read tool: 8 hostile or malformed inputs refused")
assert call("facilities-asset-status", {"asset_id": "B-12"})["found"] is True       # and the good one still works

# Write tool: schema is enforced too.
base = {"request_id": "req-contract01", "asset_id": "B-12", "summary": "Inspect the boiler PRV", "priority": "P2", "requester": "contract-test"}
for patch in ({"priority": "URGENT"}, {"summary": "x" * 500}, {"asset_id": "B-12; DELETE"}, {"summary": ""}):
    out = call("facilities-create-work-order", dict(base, **patch))
    assert out.get("error") == "invalid_input", "invalid request %r was not refused: %s" % (patch, out)
print("write tool: 4 invalid requests refused")

# Idempotency: the same approved request twice produces ONE work order.
first = call("facilities-create-work-order", base)
second = call("facilities-create-work-order", base)
rows = [i for i in ddb.scan(TableName="facilities-work-orders")["Items"] if i["requester"]["S"] == "contract-test"]
assert first["work_order_id"] == second["work_order_id"], "a replay must return the same work order"
assert first["replayed"] is False and second["replayed"] is True, (first, second)
assert len(rows) == 1, "expected exactly one work order, found %d" % len(rows)
print("idempotent: replay returned", second["work_order_id"], "(replayed=True) and the table holds", len(rows), "row")
print("tool contract verified")
''', run="python tool_contract.py", expect="tool contract verified", needs_runtime=True, kind="failure",
       nano_note="Needs the tools to execute as real Lambda functions; on Nano the Lambda sandbox cannot yet run these handlers."),
     b("Least privilege per tool, from the audit log", "Each tool gets its own identity with the smallest policy that works. The read tool starts with only GetItem on the assets table: run its real handler as that identity, get refused when it scans the work orders, and read the audit log to learn the missing action and resource. Then prove the boundaries: the read tool cannot write, the write tool cannot read assets, and nothing can touch the ledger except the write tool. The same policies are attached to IAM roles for the functions; on real AWS the role is what the function runs as (the simulator's Lambda runner uses the account root, so this proof runs the handler as an IAM user carrying the identical policy).",
       "iam_tools.py", r'''
import importlib
import os

import boto3
from botocore.exceptions import ClientError

import iamkit
from iamkit import allow

TABLES = {"ASSETS_TABLE": "facilities-assets", "WORK_ORDERS_TABLE": "facilities-work-orders", "LEDGER_TABLE": "approval-ledger"}
tbl = lambda name: "arn:aws:dynamodb:us-east-1:123456789012:table/" + name
iamkit.enforce("enforce")


def run_as(p, module, event):
    """Run the tool's real handler with this principal's credentials."""
    saved = {k: os.environ.get(k) for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", *TABLES)}
    os.environ.update(AWS_ACCESS_KEY_ID=p["key"], AWS_SECRET_ACCESS_KEY=p["secret"], **TABLES)
    boto3.setup_default_session()          # the default session caches credentials: start a fresh one for this identity
    try:
        return importlib.import_module(module).handler(event, None)
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        boto3.setup_default_session()


# 1. The read tool, starting too thin: GetItem on the assets table only.
reader = iamkit.principal("tool-asset-status", [allow("dynamodb:GetItem", tbl("facilities-assets"))])
added = iamkit.settle(reader, lambda: run_as(reader, "asset_status", {"asset_id": "B-12"}))
fix = sorted((s["Action"][0], s["Resource"].split("/")[-1]) for s in added)
print("the audit log said the read tool was missing:", fix)
assert fix == [("dynamodb:Scan", "facilities-work-orders")], "unexpected missing permissions: %s" % fix
assert run_as(reader, "asset_status", {"asset_id": "B-12"})["found"] is True

# 2. The write tool: put the work order, update the ledger, nothing else.
writer = iamkit.principal("tool-create-work-order", [allow("dynamodb:PutItem", tbl("facilities-work-orders"))])
req = {"request_id": "req-iam-0001", "asset_id": "B-12", "summary": "least privilege check", "priority": "P3", "requester": "iam-lab"}
added = iamkit.settle(writer, lambda: run_as(writer, "create_work_order", req))
fix = sorted((s["Action"][0], s["Resource"].split("/")[-1]) for s in added)
print("the audit log said the write tool was missing:", fix)
assert ("dynamodb:UpdateItem", "approval-ledger") in fix

# 3. The boundaries: each identity is refused everything outside its job.
def refused(label, call):
    try:
        call()
    except ClientError as e:
        assert e.response["Error"]["Code"] in ("AccessDenied", "AccessDeniedException"), e
        print("refused as intended:", label)
        return
    raise AssertionError(label + " should have been refused")


rd, wr = iamkit.client("dynamodb", reader), iamkit.client("dynamodb", writer)
refused("read tool writes a work order", lambda: rd.put_item(TableName="facilities-work-orders", Item={"work_order_id": {"S": "WO-EVIL"}}))
refused("read tool reads the approval ledger", lambda: rd.scan(TableName="approval-ledger"))
refused("write tool reads the assets", lambda: wr.get_item(TableName="facilities-assets", Key={"asset_id": {"S": "B-12"}}))
refused("write tool deletes a work order", lambda: wr.delete_item(TableName="facilities-work-orders", Key={"work_order_id": {"S": "WO-000101"}}))
assert "WO-EVIL" not in [i["work_order_id"]["S"] for i in boto3.client("dynamodb").scan(TableName="facilities-work-orders")["Items"]]

# 4. The same policies as roles the functions run as on real AWS.
iam = boto3.client("iam")
trust = '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
for role, p in (("facilities-asset-status-role", reader), ("facilities-create-work-order-role", writer)):
    try:
        iam.create_role(RoleName=role, AssumeRolePolicyDocument=trust)
    except iam.exceptions.EntityAlreadyExistsException:
        pass
    iam.put_role_policy(RoleName=role, PolicyName="least-privilege", PolicyDocument=__import__("json").dumps({"Version": "2012-10-17", "Statement": p["statements"]}))
print("roles created with the settled policies:", ", ".join(r["RoleName"] for r in iam.list_roles()["Roles"] if r["RoleName"].startswith("facilities-")))
print("least privilege per tool verified; denials in the audit log:", len([r for r in iamkit.audit(reader) + iamkit.audit(writer) if r["decision"] == "deny"]))
''', run="python iam_tools.py", expect="least privilege per tool verified", needs_appliance=True, kind="iam", edition=MESH, nano_note=N_IAM),
    ]

    # ───────────────────────── chapter 5: actions and approval ─────────────────────────
    LAB[5] += [
     b("Failure lab: nobody answers, then someone approves too late", "A request left unanswered must not wait forever and must not be approvable later. This block builds the same workflow with a two-second deadline, starts a request and walks away. It asserts the execution ends as `ApprovalExpired`, the ledger says EXPIRED (with the deadline it was given), no work order exists, and a late SendTaskSuccess with the old token is refused.",
       "expiry.py", r'''
import json
import time

import boto3
from botocore.exceptions import ClientError

from state_machine import ROLE, build_asl

sf, ddb = boto3.client("stepfunctions"), boto3.client("dynamodb")
arn = sf.create_state_machine(name="work-order-approval-2s", definition=json.dumps(build_asl(2)), roleArn=ROLE, type="STANDARD")["stateMachineArn"]
rid = "req-expire01"
ex = sf.start_execution(stateMachineArn=arn, name=rid, input=json.dumps(
    {"request_id": rid, "asset_id": "EL-3", "summary": "Replace the elevator 3 door sensor", "priority": "P3", "requester": "expiry-test"}))["executionArn"]

row = None
for _ in range(40):
    row = ddb.get_item(TableName="approval-ledger", Key={"request_id": {"S": rid}}).get("Item")
    if row:
        break
    time.sleep(0.25)
assert row and row["status"]["S"] == "PENDING" and int(row["expires_at"]["N"]) > int(row["ts"]["N"]), "the ledger must hold a PENDING row with a deadline"
token = row["task_token"]["S"]
print("pending with a deadline: expires_at - ts =", int(row["expires_at"]["N"]) - int(row["ts"]["N"]), "seconds (the lambda default; this run uses 2s in the workflow)")

time.sleep(3)                                             # nobody answers
for _ in range(40):
    d = sf.describe_execution(executionArn=ex)
    if d["status"] != "RUNNING":
        break
    time.sleep(0.5)
assert d["status"] == "FAILED" and d.get("error") == "ApprovalExpired", "execution must end as ApprovalExpired, got %s/%s" % (d["status"], d.get("error"))
status = ddb.get_item(TableName="approval-ledger", Key={"request_id": {"S": rid}})["Item"]["status"]["S"]
assert status == "EXPIRED", "ledger must say EXPIRED, got " + status
print("nobody answered: execution", d["status"], "/", d["error"], "| ledger", status)

try:
    sf.send_task_success(taskToken=token, output=json.dumps({"decision": "approved"}))
    raise AssertionError("a late approval must be refused")
except ClientError as e:
    print("late approval refused:", e.response["Error"]["Code"])
mine = [i for i in ddb.scan(TableName="facilities-work-orders")["Items"] if i["requester"]["S"] == "expiry-test"]
assert not mine, "an expired request must never create a work order"
print("expiry verified: no work order, request closed")
''', run="python expiry.py", expect="expiry verified", needs_runtime=True, kind="failure", edition=MESH,
       nano_note="Needs the Lambda tools to execute and a timer; on Nano the approval chain cannot run yet."),
     b("Real approver identity and no self-approval", "A string like `duty.manager@example.com` typed into the approval proves nothing. Here the identity is the credential. The smallest form of the callback pattern (publish a task token, wait) runs with two IAM identities: the agent that asks may start the workflow but may NOT call SendTaskSuccess; the duty manager may read the inbox and answer. The audit log records which principal made each decision: that record, not a typed name, is who approved. (The simulator's STS GetCallerIdentity currently returns the account root for any key, so the audit log is the reliable record here.)",
       "iam_approval.py", r'''
import json
import time

import boto3
from botocore.exceptions import ClientError

import iamkit
from iamkit import allow

sns, sqs, sf = boto3.client("sns"), boto3.client("sqs"), boto3.client("stepfunctions")
topic = sns.create_topic(Name="gate-topic")["TopicArn"]
qurl = sqs.create_queue(QueueName="gate-inbox")["QueueUrl"]
qarn = sqs.get_queue_attributes(QueueUrl=qurl, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=qarn)
ASL = {"StartAt": "Ask", "States": {
    "Ask": {"Type": "Task", "Resource": "arn:aws:states:::sns:publish.waitForTaskToken", "TimeoutSeconds": 120,
            "Parameters": {"TopicArn": topic, "Message": {"request_id.$": "$.request_id", "token.$": "$$.Task.Token"}},
            "Catch": [{"ErrorEquals": ["States.Timeout"], "Next": "Expired"}, {"ErrorEquals": ["States.ALL"], "Next": "Rejected"}], "Next": "Approved"},
    "Approved": {"Type": "Succeed"}, "Expired": {"Type": "Fail", "Error": "ApprovalExpired"}, "Rejected": {"Type": "Fail", "Error": "ApprovalRejected"}}}
sm = sf.create_state_machine(name="approval-gate", definition=json.dumps(ASL), roleArn="arn:aws:iam::123456789012:role/facilities-role")["stateMachineArn"]

iamkit.enforce("enforce")
agent = iamkit.principal("facilities-agent", [allow("states:StartExecution", sm), allow(["states:DescribeExecution"], "*")])
manager = iamkit.principal("duty-manager", [allow(["states:SendTaskSuccess", "states:SendTaskFailure"], "*"), allow(["sqs:ReceiveMessage", "sqs:DeleteMessage"], qarn)])

# The agent asks for approval.
ex = iamkit.client("stepfunctions", agent).start_execution(stateMachineArn=sm, name="gate-1", input=json.dumps({"request_id": "gate-1"}))["executionArn"]
msg = None
for _ in range(20):
    got = iamkit.client("sqs", manager).receive_message(QueueUrl=qurl, WaitTimeSeconds=1).get("Messages")
    if got:
        msg = json.loads(json.loads(got[0]["Body"])["Message"])
        break
assert msg and msg["request_id"] == "gate-1", "the approver must find the request in the inbox"

# 1. The agent cannot approve its own request.
since = iamkit.last_audit_id()
try:
    iamkit.client("stepfunctions", agent).send_task_success(taskToken=msg["token"], output="{}")
    raise AssertionError("self-approval must be refused")
except ClientError as e:
    assert e.response["Error"]["Code"] in ("AccessDenied", "AccessDeniedException"), e
print("agent tried to approve its own request: refused")
assert sf.describe_execution(executionArn=ex)["status"] == "RUNNING", "a refused approval must leave the request waiting"

# 2. The duty manager approves; the audit log names who.
iamkit.client("stepfunctions", manager).send_task_success(taskToken=msg["token"], output=json.dumps({"decision": "approved"}))
for _ in range(20):
    if sf.describe_execution(executionArn=ex)["status"] != "RUNNING":
        break
    time.sleep(0.25)
assert sf.describe_execution(executionArn=ex)["status"] == "SUCCEEDED"
decided = [r for r in iamkit.audit(manager, since) if r["action"] == "states:SendTaskSuccess"]
assert decided and decided[0]["decision"] == "allow", "the audit log must show who sent the approval"
refusals = [r for r in iamkit.audit(agent, since) if r["action"] == "states:SendTaskSuccess" and r["decision"] == "deny"]
assert refusals, "the audit log must also show the refused self-approval"
approver, requester = decided[0]["principal"], refusals[0]["principal"]
assert approver != requester, "separation of duties: approver and requester must differ"
print("approved by", approver, "| requested by", requester)
print("approver identity verified from the audit log")
''', run="python iam_approval.py", expect="approver identity verified", needs_appliance=True, kind="iam", edition=MESH, nano_note=N_IAM),
    ]

    # ───────────────────────── chapter 13: governance and security ─────────────────────────
    LAB[13] += [
     b("Rotate the key and prove old data still opens", "Rotation must never strand data. This block rotates the key on demand, checks the rotation was recorded, then asserts the record encrypted before the rotation still decrypts and a record encrypted after it does too. The policy lesson: rotate on a schedule, never delete old key material while ciphertext depends on it.",
       "key_rotation.py", r'''
import boto3

kms = boto3.client("kms")
key = kms.describe_key(KeyId="alias/facilities-ledger")["KeyMetadata"]["KeyId"]
ctx = {"table": "approval-ledger"}
before = kms.encrypt(KeyId=key, Plaintext=b"approved before rotation", EncryptionContext=ctx)["CiphertextBlob"]
n = len(kms.list_key_rotations(KeyId=key)["Rotations"])
kms.rotate_key_on_demand(KeyId=key)
rotations = kms.list_key_rotations(KeyId=key)["Rotations"]
assert len(rotations) == n + 1, "the rotation was not recorded"
after = kms.encrypt(KeyId=key, Plaintext=b"approved after rotation", EncryptionContext=ctx)["CiphertextBlob"]
assert kms.decrypt(CiphertextBlob=before, EncryptionContext=ctx)["Plaintext"] == b"approved before rotation", "pre-rotation data became unreadable"
assert kms.decrypt(CiphertextBlob=after, EncryptionContext=ctx)["Plaintext"] == b"approved after rotation"
assert kms.get_key_rotation_status(KeyId=key)["KeyRotationEnabled"], "automatic rotation must stay on"
print("rotations recorded:", len(rotations), "| old ciphertext still opens | new ciphertext opens | automatic rotation on")
print("key rotation verified")
''', run="python key_rotation.py", expect="key rotation verified", kind="harden", edition=MESH, nano_note="Not verified on Nano: needs the KMS engine to support RotateKeyOnDemand."),
     b("Make the audit trail tamper-evident", "A trail the writer can edit is not evidence. Every ledger decision is chained: each entry's hash covers the previous hash, so changing, removing or reordering any entry breaks every hash after it. The head hash is signed with a KMS HMAC key held by a different identity than the writer, so even rewriting the whole chain is detected. The block then attacks its own trail three ways (edit an entry, delete the last entry, rewrite the chain) and asserts each is caught and located.",
       "audit_chain.py", r'''
import hashlib
import json

import boto3

ddb, kms, s3 = boto3.client("dynamodb"), boto3.client("kms"), boto3.client("s3")
rows = [{k: list(v.values())[0] for k, v in i.items() if k != "task_token"} for i in ddb.scan(TableName="approval-ledger")["Items"]]
rows.sort(key=lambda r: (r.get("ts", "0"), r["request_id"]))
if len(rows) < 2:
    raise SystemExit("missing prerequisite: the ledger needs at least two decisions (run chapter 5: approve.py, reject.py)")


def chain(entries):
    out, prev = [], "0" * 64
    for e in entries:
        body = json.dumps(e, sort_keys=True)
        prev = hashlib.sha256((prev + body).encode()).hexdigest()
        out.append({"entry": e, "hash": prev})
    return out


def first_break(links):
    """Index of the first entry whose hash does not follow from the entries before it, or None."""
    prev = "0" * 64
    for i, l in enumerate(links):
        prev = hashlib.sha256((prev + json.dumps(l["entry"], sort_keys=True)).encode()).hexdigest()
        if prev != l["hash"]:
            return i
    return None


try:
    mac_key = kms.describe_key(KeyId="alias/audit-anchor")["KeyMetadata"]["KeyId"]
except kms.exceptions.NotFoundException:
    mac_key = kms.create_key(KeySpec="HMAC_256", KeyUsage="GENERATE_VERIFY_MAC", Description="signs the audit chain head")["KeyMetadata"]["KeyId"]
    kms.create_alias(AliasName="alias/audit-anchor", TargetKeyId=mac_key)


def anchor(links):
    return kms.generate_mac(KeyId=mac_key, Message=links[-1]["hash"].encode(), MacAlgorithm="HMAC_SHA_256")["Mac"]


def anchor_ok(links, mac):
    try:
        return kms.verify_mac(KeyId=mac_key, Message=links[-1]["hash"].encode(), MacAlgorithm="HMAC_SHA_256", Mac=mac)["MacValid"]
    except Exception:
        return False


links = chain(rows)
mac = anchor(links)
s3.put_object(Bucket="facilities-docs", Key="audit/chain.json", Body=json.dumps(links).encode())
assert first_break(links) is None and anchor_ok(links, mac)
print("chain of", len(links), "decisions written and signed; verifies clean")

# Attack 1: edit one entry in the middle.
t = json.loads(json.dumps(links))
t[0]["entry"]["status"] = "EXECUTED" if t[0]["entry"].get("status") != "EXECUTED" else "REJECTED"
assert first_break(t) == 0, "an edited entry must break the chain at that entry"
print("edit entry 0: chain breaks at index", first_break(t))

# Attack 2: delete the newest entry (the chain still looks internally valid, the signed head no longer matches).
t = json.loads(json.dumps(links))[:-1]
assert first_break(t) is None and not anchor_ok(t, mac), "a truncated chain must fail the signed anchor"
print("delete the last entry: hashes still chain, signed anchor rejects it")

# Attack 3: rewrite the whole chain after editing (the attacker can recompute hashes but cannot sign).
t = json.loads(json.dumps(links))
t[-1]["entry"]["status"] = "FORGED"
forged = chain([l["entry"] for l in t])
assert first_break(forged) is None and not anchor_ok(forged, mac), "a recomputed chain must fail the signed anchor"
print("rewrite the chain: hashes recompute, signed anchor rejects it")
print("tamper evidence verified")
''', run="python audit_chain.py", expect="tamper evidence verified", kind="harden", edition=MESH, needs_runtime=True,
       nano_note="Not verified on Nano: needs KMS GenerateMac/VerifyMac and the approval ledger populated by the Lambda-backed chapter 5."),
     b("Who did what: the identity behind each approval", "Joins the two audit sources that chapter 5 produced: the ledger (what was decided) and the IAM audit log (which principal was allowed or refused). It asserts the approver and the requester are different identities, that the refused self-approval is on record, and says plainly which prerequisite is missing if the Enforce step was skipped.",
       "audit_who.py", r'''
import iamkit

recs = iamkit._admin("GET", "/api/iam/aws/audit?limit=500")["records"]
sends = [r for r in recs if r["action"] == "states:SendTaskSuccess"]
allowed = [r for r in sends if r["decision"] == "allow" and "duty-manager" in r["principal"]]
refused = [r for r in sends if r["decision"] == "deny" and "facilities-agent" in r["principal"]]
if not allowed or not refused:
    raise SystemExit("missing prerequisite: run chapter 5 'Real approver identity and no self-approval' first "
                     "(found %d approvals by the duty manager and %d refused self-approvals)" % (len(allowed), len(refused)))
approver, requester = allowed[-1]["principal"], refused[-1]["principal"]
assert approver != requester, "approver and requester must be different identities"
print("approved by :", approver, "at", allowed[-1]["time"])
print("refused     :", requester, "tried to approve its own request at", refused[-1]["time"])
denials = [r for r in recs if r["decision"] == "deny"]
print("every denial in the trail names a principal and an action:", all(r["principal"] and r["action"] for r in denials), "(%d denials)" % len(denials))
print("identity audit verified")
''', run="python audit_who.py", expect="identity audit verified", needs_appliance=True, kind="iam", edition=MESH, nano_note=N_IAM),
    ]
