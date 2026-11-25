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
