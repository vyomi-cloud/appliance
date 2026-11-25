"""Least-privilege helper for the IAM Enforce labs: make a principal with an inline policy, switch the simulator to Enforce, and read the audit log."""
import atexit
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
    """off | audit | enforce for the whole space. The root test credentials stay allowed for every service the simulator can map to an IAM action;
    only the IAM users you create are judged. Enforce is switched back off when your script ends, so the other chapters keep working
    (a production account would leave it on and map every service)."""
    if mode != "off":
        atexit.register(lambda: _admin("PUT", "/api/iam/aws/enforcement", {"space": "off"}))
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
