"""IAM Query actions the offline server's api_iam_query did not implement, on the SAME iam_state the console and
enforcement (server._iam_authorize) use: AttachUserPolicy / DetachUserPolicy / ListAttachedUserPolicies,
PutUserPolicy / GetUserPolicy / DeleteUserPolicy / ListUserPolicies, CreateAccessKey / ListAccessKeys /
DeleteAccessKey / UpdateAccessKey, SimulatePrincipalPolicy / SimulateCustomPolicy.

Response XML and the policy evaluator are core.iam_core / core.iam_store (the shared Nano code), so offline and Nano give the
same decisions. Inline policies and access keys are stored on the user record (`inline_policies`, `access_keys`) and inline
policies are read by server._iam_resolve_identity so they take part in enforcement.
"""
from __future__ import annotations

import json
import uuid

from core import iam_core as ic
from core.iam_store import NativeIamEvaluator

ACTIONS = {"AttachUserPolicy", "DetachUserPolicy", "ListAttachedUserPolicies", "PutUserPolicy", "GetUserPolicy",
           "DeleteUserPolicy", "ListUserPolicies", "CreateAccessKey", "ListAccessKeys", "DeleteAccessKey",
           "UpdateAccessKey", "SimulatePrincipalPolicy", "SimulateCustomPolicy"}
_ENGINE = NativeIamEvaluator()


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _s():
    import server
    return server


def _user(name):
    u = _s()._iam_find_user(str(name or "").strip())
    if not u:
        raise ic.IamError("NoSuchEntity", f"The user with name {name} cannot be found.", 404)
    return u


def _policy_by_arn(arn):
    name = str(arn or "").rsplit("/", 1)[-1]
    for pid, p in _s()._iam_state()["policies"].items():
        if p.get("policy_name") == name:
            return pid, p
    raise ic.IamError("NoSuchEntity", f"Policy {arn} does not exist or is not attachable.", 404)


def _doc(p):
    d = p.get("document", {})
    return json.loads(d) if isinstance(d, str) else (d or {})


def _identity_docs(source):
    s = _s()
    ident = s._iam_resolve_identity(source)
    if ident["type"] == "unknown":
        raise ic.IamError("NoSuchEntity", f"Entity {source} not found.", 404)
    return ident, [_doc(p) for p in ident.get("policies", [])]


def handle(action: str, params: dict):
    """Return an XML Response, or None when `action` is not one of ours. IamError -> error Response."""
    if action not in ACTIONS:
        return None
    s = _s()
    try:
        r = _run(s, action, params)
    except ic.IamError as e:
        return s._iam_query_error(e.code, e.message, e.status)
    return s._xml_response(r.body, r.status)


def _run(s, action, params):
    st = s._iam_state()
    el = ic._el
    if action == "AttachUserPolicy":
        u = _user(params.get("UserName"))
        pid, _p = _policy_by_arn(params.get("PolicyArn"))
        if pid not in u.get("policies", []):
            s.provider_aws_iam.api_iam_attach_policy({"target_type": "user", "target_id": u["user_id"], "policy_id": pid})
        return ic._envelope(action)
    if action == "DetachUserPolicy":
        u = _user(params.get("UserName"))
        pid, _p = _policy_by_arn(params.get("PolicyArn"))
        if pid not in u.get("policies", []):
            raise ic.IamError("NoSuchEntity", f"Policy {params.get('PolicyArn')} was not found.", 404)
        s._iam_detach_policy_records("user", u["user_id"], pid)
        return ic._envelope(action)
    if action == "ListAttachedUserPolicies":
        u = _user(params.get("UserName"))
        items = []
        for pid in u.get("policies", []):
            p = st["policies"].get(pid)
            if p:
                items.append("<member>" + el("PolicyName", p["policy_name"]) + el("PolicyArn", s._iam_policy_arn(p["policy_name"])) + "</member>")
        return ic._envelope(action, f"<AttachedPolicies>{''.join(items)}</AttachedPolicies><IsTruncated>false</IsTruncated>")
    if action == "PutUserPolicy":
        u = _user(params.get("UserName"))
        pname = str(params.get("PolicyName", "")).strip()
        if not pname:
            raise ic.IamError("ValidationError", "PolicyName is required.", 400)
        u.setdefault("inline_policies", {})[pname] = ic._json_param(params, "PolicyDocument")
        return ic._envelope(action)
    if action in ("GetUserPolicy", "DeleteUserPolicy"):
        u = _user(params.get("UserName"))
        pname = str(params.get("PolicyName", "")).strip()
        inl = u.setdefault("inline_policies", {})
        if pname not in inl:
            raise ic.IamError("NoSuchEntity", f"The user policy with name {pname} cannot be found.", 404)
        if action == "DeleteUserPolicy":
            del inl[pname]
            return ic._envelope(action)
        inner = el("UserName", u["user_name"]) + el("PolicyName", pname) + \
            f"<PolicyDocument>{ic._xml_escape(json.dumps(inl[pname]))}</PolicyDocument>"
        return ic._envelope(action, inner)
    if action == "ListUserPolicies":
        u = _user(params.get("UserName"))
        names = "".join(f"<member>{ic._xml_escape(n)}</member>" for n in sorted(u.get("inline_policies", {})))
        return ic._envelope(action, f"<PolicyNames>{names}</PolicyNames><IsTruncated>false</IsTruncated>")
    if action == "CreateAccessKey":
        u = _user(params.get("UserName") or "")
        keys = u.setdefault("access_keys", [])
        if len(keys) >= 2:
            raise ic.IamError("LimitExceeded", "Cannot exceed quota for AccessKeysPerUser: 2", 409)
        k = {"access_key_id": "AKIA" + uuid.uuid4().hex[:16].upper(), "secret_access_key": uuid.uuid4().hex + uuid.uuid4().hex[:8],
             "status": "Active", "created": _now()}
        keys.append(k)
        return ic._envelope(action, "<AccessKey>" + el("UserName", u["user_name"]) + el("AccessKeyId", k["access_key_id"])
                            + el("Status", "Active") + el("SecretAccessKey", k["secret_access_key"]) + el("CreateDate", k["created"]) + "</AccessKey>")
    if action == "ListAccessKeys":
        u = _user(params.get("UserName"))
        items = "".join("<member>" + el("UserName", u["user_name"]) + el("AccessKeyId", k["access_key_id"]) + el("Status", k["status"])
                        + el("CreateDate", k["created"]) + "</member>" for k in u.get("access_keys", []))
        return ic._envelope(action, f"<AccessKeyMetadata>{items}</AccessKeyMetadata><IsTruncated>false</IsTruncated>")
    if action in ("DeleteAccessKey", "UpdateAccessKey"):
        akid = str(params.get("AccessKeyId", "")).strip()
        owner = next((u for u in st["users"].values() if any(k["access_key_id"] == akid for k in u.get("access_keys", []))), None)
        if owner is None or (params.get("UserName") and owner["user_name"] != params["UserName"]):
            raise ic.IamError("NoSuchEntity", f"The Access Key with id {akid} cannot be found.", 404)
        if action == "DeleteAccessKey":
            owner["access_keys"] = [k for k in owner["access_keys"] if k["access_key_id"] != akid]
        else:
            if params.get("Status") not in ("Active", "Inactive"):
                raise ic.IamError("ValidationError", "Status must be Active or Inactive.", 400)
            next(k for k in owner["access_keys"] if k["access_key_id"] == akid)["status"] = params["Status"]
        return ic._envelope(action)
    # simulate
    actions, resources = ic._members(params, "ActionNames"), ic._members(params, "ResourceArns") or ["*"]
    extra = [ic._json_param({"p": x}, "p") for x in ic._members(params, "PolicyInputList")]
    if action == "SimulateCustomPolicy":
        if not extra:
            raise ic.IamError("ValidationError", "PolicyInputList is required.", 400)
        return ic.simulate_xml(_ENGINE, action, extra, actions, resources, {"aws:RequestedRegion": "us-east-1"})
    source = str(params.get("PolicySourceArn", "")).strip()
    if not source:
        raise ic.IamError("ValidationError", "PolicySourceArn is required.", 400)
    ident, docs = _identity_docs(source)
    ctx = {"aws:PrincipalArn": ident["arn"], "aws:PrincipalType": ident["type"], "aws:username": ident["name"], "aws:RequestedRegion": "us-east-1"}
    return ic.simulate_xml(_ENGINE, action, docs + extra, actions, resources, ctx)
