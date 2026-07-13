"""Phase 5 — IAM decision unification: AWS + GCP policy DECISIONS on one durable seam.

Both IAM cores route decisions through the shared IamStore/AuthzEngine seam, and a
single PersistentIamStore holds BOTH AWS identity (users/policies) and GCP policy
(gcp_iam_policies) state. So one backed seam serves both clouds' authorization
decisions, and they survive a FRESH store — proving the identity plane unifies on
a real backend. AWS uses SimulatePrincipalPolicy (IAM-JSON eval); GCP uses
testIamPermissions (binding eval). Different models, one seam.

Run:  PYTHONPATH=. python3 tests/conformance/test_iam_unification.py
"""
import json
import re

try:
    from core.persistent_store import SqliteStateBackend, PersistentIamStore
    from core import iam_core as aws_iam
    from core import gcp_iam_core as gcp_iam
except ImportError:  # pragma: no cover - Pyodide flat layout
    from persistent_store import SqliteStateBackend, PersistentIamStore  # type: ignore
    import iam_core as aws_iam  # type: ignore
    import gcp_iam_core as gcp_iam  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _policy(stmt):
    return json.dumps({"Version": "2012-10-17", "Statement": [stmt]})


def _decisions(xml):
    return {m.group(1): m.group(2) for m in re.finditer(
        r"<EvalActionName>(.*?)</EvalActionName>.*?<EvalDecision>(.*?)</EvalDecision>", xml, re.S)}


def _gjson(r):
    return json.loads(r.body.decode("utf-8")) if r.body else {}


def run() -> int:
    be = SqliteStateBackend(":memory:")

    # ── set up BOTH clouds' identity + policy on store A (one shared seam) ──
    a = PersistentIamStore(be)
    # AWS: user alice + a managed S3-read policy, attached
    aws_iam.dispatch(a, {"Action": "CreateUser", "UserName": "alice"})
    aws_iam.dispatch(a, {"Action": "CreatePolicy", "PolicyName": "S3ReadOnly",
                         "PolicyDocument": _policy({"Effect": "Allow", "Action": "s3:Get*",
                                                    "Resource": "arn:aws:s3:::data/*"})})
    aws_iam.dispatch(a, {"Action": "AttachUserPolicy", "UserName": "alice",
                         "PolicyArn": "arn:aws:iam::123456789012:policy/S3ReadOnly"})
    # GCP: a binding granting alice the objectViewer role on a resource
    gcp_iam.dispatch(a, "POST", "/v1/projects/demo:setIamPolicy", {}, {},
                     json.dumps({"policy": {"bindings": [
                         {"role": "roles/storage.objectViewer",
                          "members": ["user:alice@example.com"]}]}}).encode())

    # ── decide on a FRESH backed store B (durable identity, both clouds) ────
    b = PersistentIamStore(be)

    sim = aws_iam.dispatch(b, {"Action": "SimulatePrincipalPolicy", "PolicySourceArn": "alice",
                               "ActionNames.member.1": "s3:GetObject",
                               "ActionNames.member.2": "s3:DeleteObject",
                               "ResourceArns.member.1": "arn:aws:s3:::data/report.csv"})
    dec = _decisions(sim.body)
    _check("AWS decision durable: s3:GetObject ALLOWED (matches s3:Get* on data/*)",
           dec.get("s3:GetObject") == "allowed")
    _check("AWS decision durable: s3:DeleteObject implicitDeny",
           dec.get("s3:DeleteObject") == "implicitDeny")

    tp = _gjson(gcp_iam.dispatch(b, "POST", "/v1/projects/demo:testIamPermissions", {}, {},
                json.dumps({"member": "user:alice@example.com",
                            "permissions": ["storage.objects.get", "storage.objects.list",
                                            "storage.objects.delete"]}).encode()))
    granted = set(tp.get("permissions", []))
    _check("GCP decision durable: viewer grants get+list", {"storage.objects.get", "storage.objects.list"} <= granted)
    _check("GCP decision durable: viewer does NOT grant delete (evaluated, not echoed)",
           "storage.objects.delete" not in granted)

    _check("one PersistentIamStore seam holds BOTH clouds' IAM state",
           b.users and getattr(b, "gcp_iam_policies", None))

    print("\nPHASE 5: ALL GREEN — AWS + GCP IAM authorization decisions unify on one durable "
          "IamStore seam (SimulatePrincipalPolicy + testIamPermissions, fresh-store durable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
