# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AWS RAM (Resource Access Manager) core — scoped to the two resource types the VPC
console's sharing pages need: subnets and security groups (gap-sweep queue items
aws.vpc.resource-sharing / aws.vpc.security-group-sharing).

Real AWS RAM lets you share a resource with ANOTHER account; the invited account's
Describe calls then show the resource too. Vyomi is a single-account simulator — there
is no second account anywhere in the system to observe that half of the effect from, and
inventing one (principals/orgs/cross-account auth) is a cross-cutting change this service
isn't scoped to make. What IS real and enforced here, confined to vpc_core.py's own
resources: the full RAM object model — resource shares, principal/resource associations,
their state machine (ASSOCIATING → ASSOCIATED, idempotent re-association, disassociation),
validation (only subnet/security-group ARNs, must actually exist), and the owner-side
consequence AWS itself enforces — a subnet or security group with an ACTIVE external
association cannot be deleted until the association (or the whole share) is removed first
(see vpc_core._delete_subnet / _delete_security_group's `ram_store` check). That is a real
behaviour change driven by share state, not stored-and-ignored config.

Speaks the native RAM JSON1.1 protocol (X-Amz-Target: AWSRAMFrontendService.<Action>), the
same dispatch shape as core/kms_core.py.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

OWNER_ID = "123456789012"
_SHARABLE_TYPES = {"subnet": "ec2:Subnet", "security-group": "ec2:SecurityGroup"}


@dataclass
class RamResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class RamError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status = code, message, status


def _model(store) -> dict:
    m = getattr(store, "_ram_model", None)
    if m is None:
        m = {"shares": {}, "resource_assocs": {}, "principal_assocs": {}}
        store._ram_model = m
    return m


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def resource_kind(arn: str) -> str | None:
    for kind in _SHARABLE_TYPES:
        if f":{kind}/" in arn:
            return kind
    return None


def resource_id(arn: str) -> str:
    return arn.rsplit("/", 1)[-1]


def _validate_resource(vpc_store, arn: str) -> None:
    kind = resource_kind(arn)
    if kind is None:
        raise RamError("UnknownResourceException", f"Resource type for '{arn}' is not supported by this resource share.")
    rid = resource_id(arn)
    vm = getattr(vpc_store, "_vpc_model", None) or {}
    coll = {"subnet": "subnets", "security-group": "sgs"}[kind]
    if rid not in vm.get(coll, {}):
        raise RamError("UnknownResourceException", f"The resource {arn} does not exist.")


def has_active_share(ram_store, arn: str) -> bool:
    """Used by vpc_core before DeleteSubnet/DeleteSecurityGroup: True if `arn` has an
    ASSOCIATED resource association in any non-deleted resource share."""
    if ram_store is None:
        return False
    m = _model(ram_store)
    return any(a["resource_arn"] == arn and a["status"] == "ASSOCIATED" for a in m["resource_assocs"].values())


def _share_dict(s: dict) -> dict:
    return {"resourceShareArn": s["arn"], "name": s["name"], "owningAccountId": OWNER_ID,
           "allowExternalPrincipals": s["allow_external_principals"], "status": s["status"],
           "statusMessage": "", "tags": [{"key": k, "value": v} for k, v in s.get("tags", {}).items()],
           "creationTime": s["created"], "lastUpdatedTime": s["created"], "featureSet": "STANDARD"}


def _create_resource_share(store, body, vpc_store=None):
    name = str(body.get("name") or "")
    if not name:
        raise RamError("MissingRequiredParameterException", "name is required.")
    share_id = "rs-" + uuid.uuid4().hex[:17]
    arn = f"arn:aws:ram:us-east-1:{OWNER_ID}:resource-share/{share_id}"
    m = _model(store)
    s = {"id": share_id, "arn": arn, "name": name, "status": "ACTIVE", "created": _now(),
        "allow_external_principals": bool(body.get("allowExternalPrincipals", True)),
        "tags": {t["key"]: t.get("value", "") for t in body.get("tags", []) if t.get("key")}}
    m["shares"][arn] = s
    assocs = []
    for res_arn in body.get("resourceArns") or []:
        assocs.append(_associate_one(store, vpc_store, arn, "RESOURCE", res_arn))
    for principal in body.get("principals") or []:
        assocs.append(_associate_one(store, vpc_store, arn, "PRINCIPAL", principal))
    return {"resourceShare": _share_dict(s), "clientToken": str(body.get("clientToken") or "")}


def _get_resource_shares(store, body):
    m = _model(store)
    arns = body.get("resourceShareArns") or []
    name = body.get("name")
    rows = list(m["shares"].values())
    if arns:
        rows = [s for s in rows if s["arn"] in arns]
    if name:
        rows = [s for s in rows if s["name"] == name]
    status = body.get("resourceShareStatus")
    if status:
        rows = [s for s in rows if s["status"] == status]
    return {"resourceShares": [_share_dict(s) for s in rows]}


def _update_resource_share(store, body):
    m = _model(store)
    arn = str(body.get("resourceShareArn", ""))
    s = m["shares"].get(arn)
    if s is None:
        raise RamError("UnknownResourceException", f"Resource share {arn} does not exist.")
    if "name" in body:
        s["name"] = str(body["name"])
    if "allowExternalPrincipals" in body:
        s["allow_external_principals"] = bool(body["allowExternalPrincipals"])
    return {"resourceShare": _share_dict(s)}


def _delete_resource_share(store, body):
    m = _model(store)
    arn = str(body.get("resourceShareArn", ""))
    s = m["shares"].get(arn)
    if s is None:
        raise RamError("UnknownResourceException", f"Resource share {arn} does not exist.")
    s["status"] = "DELETED"
    for aid in [k for k, a in m["resource_assocs"].items() if a["share_arn"] == arn]:
        m["resource_assocs"].pop(aid)
    for aid in [k for k, a in m["principal_assocs"].items() if a["share_arn"] == arn]:
        m["principal_assocs"].pop(aid)
    m["shares"].pop(arn)
    return {"returnValue": True}


def _assoc_dict(a: dict) -> dict:
    key = "resourceArn" if a["kind"] == "RESOURCE" else "principal"
    return {"resourceShareArn": a["share_arn"], key: a["target"], "associationType": a["kind"],
           "status": a["status"], "statusMessage": a.get("status_message", ""),
           "creationTime": a["created"], "lastUpdatedTime": a["created"], "external": a.get("external", False)}


def _associate_one(store, vpc_store, share_arn: str, kind: str, target: str) -> dict:
    m = _model(store)
    coll = m["resource_assocs"] if kind == "RESOURCE" else m["principal_assocs"]
    if kind == "RESOURCE":
        _validate_resource(vpc_store, target)
        key_field = "resource_arn"
    else:
        key_field = "principal"
    existing = next((a for a in coll.values() if a["share_arn"] == share_arn and a[key_field] == target), None)
    if existing:
        existing["status"] = "ASSOCIATED"
        return _assoc_dict(existing)
    aid = str(uuid.uuid4())
    rec = {"id": aid, "share_arn": share_arn, "kind": kind, "target": target, "status": "ASSOCIATED",
          "created": _now(), "external": kind == "PRINCIPAL" and not target.startswith(OWNER_ID)}
    rec[key_field] = target
    coll[aid] = rec
    return _assoc_dict(rec)


def _associate_resource_share(store, body, vpc_store=None):
    arn = str(body.get("resourceShareArn", ""))
    m = _model(store)
    if arn not in m["shares"]:
        raise RamError("UnknownResourceException", f"Resource share {arn} does not exist.")
    assocs = [_associate_one(store, vpc_store, arn, "RESOURCE", r) for r in body.get("resourceArns") or []]
    assocs += [_associate_one(store, vpc_store, arn, "PRINCIPAL", p) for p in body.get("principals") or []]
    return {"resourceShareAssociations": assocs}


def _disassociate_resource_share(store, body):
    arn = str(body.get("resourceShareArn", ""))
    m = _model(store)
    if arn not in m["shares"]:
        raise RamError("UnknownResourceException", f"Resource share {arn} does not exist.")
    out = []
    for r in body.get("resourceArns") or []:
        a = next((x for x in m["resource_assocs"].values() if x["share_arn"] == arn and x["resource_arn"] == r), None)
        if a:
            a["status"] = "DISASSOCIATED"
            out.append(_assoc_dict(a))
            m["resource_assocs"].pop(a["id"])
    for p in body.get("principals") or []:
        a = next((x for x in m["principal_assocs"].values() if x["share_arn"] == arn and x["principal"] == p), None)
        if a:
            a["status"] = "DISASSOCIATED"
            out.append(_assoc_dict(a))
            m["principal_assocs"].pop(a["id"])
    return {"resourceShareAssociations": out}


def _get_resource_share_associations(store, body):
    m = _model(store)
    atype = str(body.get("associationType") or "RESOURCE")
    coll = m["resource_assocs"] if atype == "RESOURCE" else m["principal_assocs"]
    rows = list(coll.values())
    arns = body.get("resourceShareArns") or []
    if arns:
        rows = [a for a in rows if a["share_arn"] in arns]
    if body.get("resourceArn"):
        rows = [a for a in rows if a.get("resource_arn") == body["resourceArn"]]
    if body.get("principal"):
        rows = [a for a in rows if a.get("principal") == body["principal"]]
    return {"resourceShareAssociations": [_assoc_dict(a) for a in rows]}


def _list_principals(store, body):
    m = _model(store)
    arns = body.get("resourceShareArns") or []
    rows = [a for a in m["principal_assocs"].values() if not arns or a["share_arn"] in arns]
    return {"principals": [{"id": a["principal"], "resourceShareArn": a["share_arn"], "creationTime": a["created"],
                            "lastUpdatedTime": a["created"], "external": a.get("external", False)} for a in rows]}


def _list_resources(store, body, vpc_store=None):
    m = _model(store)
    owner = str(body.get("resourceOwner") or "SELF")
    rows = [a for a in m["resource_assocs"].values() if a["status"] == "ASSOCIATED"]
    arns = body.get("resourceShareArns") or []
    if arns:
        rows = [a for a in rows if a["share_arn"] in arns]
    return {"resources": [{"arn": a["resource_arn"], "type": _SHARABLE_TYPES.get(resource_kind(a["resource_arn"]), ""),
                           "resourceShareArn": a["share_arn"], "status": "AVAILABLE", "creationTime": a["created"],
                           "lastUpdatedTime": a["created"]} for a in rows]}


_OPS = {
    "CreateResourceShare": lambda s, b, v: _create_resource_share(s, b, v),
    "GetResourceShares": lambda s, b, v: _get_resource_shares(s, b),
    "UpdateResourceShare": lambda s, b, v: _update_resource_share(s, b),
    "DeleteResourceShare": lambda s, b, v: _delete_resource_share(s, b),
    "AssociateResourceShare": lambda s, b, v: _associate_resource_share(s, b, v),
    "DisassociateResourceShare": lambda s, b, v: _disassociate_resource_share(s, b),
    "GetResourceShareAssociations": lambda s, b, v: _get_resource_share_associations(s, b),
    "ListPrincipals": lambda s, b, v: _list_principals(s, b),
    "ListResources": lambda s, b, v: _list_resources(s, b, v),
}


def dispatch(store, target: str, payload: dict | None = None, vpc_store=None) -> RamResponse:
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    op = _OPS.get(action)
    if op is None:
        return RamResponse(status=400, body={"__type": "UnknownOperationException",
                                             "message": f"The action {action} is not implemented."})
    try:
        return RamResponse(status=200, body=op(store, body, vpc_store), headers={"x-amzn-requestid": str(uuid.uuid4())})
    except RamError as e:
        return RamResponse(status=e.status, body={"__type": e.code, "message": e.message},
                           headers={"x-amzn-requestid": str(uuid.uuid4())})
