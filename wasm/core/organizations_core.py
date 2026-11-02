# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AWS Organizations core — the management-account control plane (JSON 1.1,
X-Amz-Target: AWSOrganizationsV20161128.<Action>, signing name `organizations`).

Real and enforced here: the organization object model (organization, root, OU tree, member
accounts, handshakes), the policy model for every policy type (SCP / RCP / tag / backup /
AI-services opt-out / ...) with attach / detach / list-targets / list-policies-for-target, the
root's enabled-policy-type state machine (a policy of a disabled type cannot be attached; the
last SCP on a target cannot be detached; a policy in use cannot be deleted; an OU / organization
that is not empty cannot be deleted), AWS service access (trusted access) and delegated
administrators, tags on every taggable resource, and the CreateAccount / Invite / Accept /
Move / Remove / Close account lifecycle. AWS completes CreateAccount asynchronously; here the
create-account status is SUCCEEDED the moment it is requested.

What is NOT modeled (registered in core/capabilities/aws/iam.json): Vyomi is one account, so a
member account has no resources, principals or traffic of its own and an SCP/RCP is stored,
validated and attached but never evaluated against a request (the management account is exempt
from SCPs in real AWS too). `effective_scp_decision` evaluates the attached SCP chain for a
caller that asks (the policy-simulator seam), nothing else calls it.

State lives in `store.extras["org"]` of the IAM store (and the policies in `store.org_policies`,
shared with IAM's Vyomi-only CreateOrgPolicy actions), so it persists on every substrate.
Pure stdlib — loads under Pyodide.
"""
from __future__ import annotations

import json
import random
import string
import time
import uuid
from dataclasses import dataclass, field

MGMT_EMAIL = "management@vyomi.local"
SCP, RCP = "SERVICE_CONTROL_POLICY", "RESOURCE_CONTROL_POLICY"
POLICY_TYPES = {SCP, RCP, "TAG_POLICY", "BACKUP_POLICY", "AISERVICES_OPT_OUT_POLICY",
                "CHATBOT_POLICY", "DECLARATIVE_POLICY_EC2", "SECURITYHUB_POLICY", "INSPECTOR_POLICY",
                "UPGRADE_ROLLOUT_POLICY", "BEDROCK_POLICY", "S3_POLICY", "NETWORK_SECURITY_DIRECTOR_POLICY"}
FULL_ACCESS_ID = "p-FullAWSAccess"
FULL_ACCESS = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]})
FULL_ACCESS_RCP_ID = "p-RCPFullAWSAccess"


@dataclass
class OrgResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class OrgError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status = code, message, status


def _ts() -> float:
    return round(time.time(), 3)


def _rid(n: int) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _org(store, required: bool = True) -> dict | None:
    o = store.extras.get("org")
    if not o and required:
        raise OrgError("AWSOrganizationsNotInUseException", "Your account is not a member of an organization.")
    return o


def _persist(store) -> None:
    p = getattr(store, "persist", None)
    if callable(p):
        p()


def _arn(store, o: dict, kind: str, ident: str = "") -> str:
    base = f"arn:aws:organizations::{o['master_account_id']}"
    if kind == "organization":
        return f"{base}:organization/{o['id']}"
    if kind == "root":
        return f"{base}:root/{o['id']}/{ident}"
    return f"{base}:{kind}/{o['id']}/{ident}"


# ── object shapes ──────────────────────────────────────────────────────────
def _s_org(o: dict) -> dict:
    return {"Id": o["id"], "Arn": o["arn"], "FeatureSet": o["feature_set"],
            "MasterAccountArn": o["master_account_arn"], "MasterAccountId": o["master_account_id"],
            "MasterAccountEmail": o["master_account_email"],
            "AvailablePolicyTypes": [{"Type": "SERVICE_CONTROL_POLICY", "Status": "ENABLED"}] if o["feature_set"] == "ALL" else []}


def _s_root(r: dict) -> dict:
    return {"Id": r["id"], "Arn": r["arn"], "Name": r["name"],
            "PolicyTypes": [{"Type": t, "Status": "ENABLED"} for t in sorted(r["policy_types"])]}


def _s_ou(u: dict) -> dict:
    return {"Id": u["id"], "Arn": u["arn"], "Name": u["name"]}


def _s_acct(a: dict) -> dict:
    return {"Id": a["id"], "Arn": a["arn"], "Email": a["email"], "Name": a["name"], "Status": a["status"],
            "State": a["state"], "JoinedMethod": a["joined_method"], "JoinedTimestamp": a["joined"]}


def _s_policy_summary(o: dict, p: dict) -> dict:
    return {"Id": p["id"], "Arn": p["arn"], "Name": p["name"], "Description": p.get("description", ""),
            "Type": p["type"], "AwsManaged": bool(p.get("aws_managed"))}


def _s_policy(o: dict, p: dict) -> dict:
    return {"PolicySummary": _s_policy_summary(o, p), "Content": p["content"]}


def _s_status(s: dict) -> dict:
    out = {"Id": s["id"], "AccountName": s["account_name"], "State": s["state"],
           "RequestedTimestamp": s["requested"], "CompletedTimestamp": s["completed"]}
    if s.get("account_id"):
        out["AccountId"] = s["account_id"]
    return out


def _s_handshake(h: dict) -> dict:
    return {"Id": h["id"], "Arn": h["arn"], "Parties": h["parties"], "State": h["state"],
            "RequestedTimestamp": h["requested"], "ExpirationTimestamp": h["expires"], "Action": h["action"],
            "Resources": h["resources"]}


# ── model helpers ──────────────────────────────────────────────────────────
def _root(o: dict) -> dict:
    return next(iter(o["roots"].values()))


def _node(o: dict, ident: str):
    """(kind, record) for a root / OU / account id."""
    if ident in o["roots"]:
        return "ROOT", o["roots"][ident]
    if ident in o["ous"]:
        return "ORGANIZATIONAL_UNIT", o["ous"][ident]
    if ident in o["accounts"]:
        return "ACCOUNT", o["accounts"][ident]
    return None, None


def _need_parent(o: dict, pid: str):
    kind, rec = _node(o, pid)
    if kind not in ("ROOT", "ORGANIZATIONAL_UNIT"):
        raise OrgError("ParentNotFoundException", f"You specified a parent that doesn't exist: {pid}.")
    return kind, rec


def _need_account(o: dict, aid: str) -> dict:
    a = o["accounts"].get(aid)
    if not a:
        raise OrgError("AccountNotFoundException", "You specified an account that doesn't exist.")
    return a


def _need_policy(store, pid: str) -> dict:
    p = store.org_policies.get(pid)
    if not p:
        raise OrgError("PolicyNotFoundException", "You specified a policy that doesn't exist.")
    return p


def _attached(o: dict, policy_id: str) -> list[str]:
    return [t for t, pids in o["attachments"].items() if policy_id in pids]


def _children_of(o: dict, parent: str):
    ous = [u for u in o["ous"].values() if u["parent"] == parent]
    accts = [a for a in o["accounts"].values() if a["parent"] == parent]
    return ous, accts


def _ensure_managed(store, o: dict) -> None:
    for pid, ptype, name, desc in ((FULL_ACCESS_ID, SCP, "FullAWSAccess", "Allows access to every operation"),
                                   (FULL_ACCESS_RCP_ID, RCP, "RCPFullAWSAccess", "Allows access to every operation")):
        if pid not in store.org_policies:
            store.org_policies[pid] = {"id": pid, "arn": f"arn:aws:organizations::aws:policy/{ptype.lower()}/{pid}",
                                       "name": name, "description": desc, "type": ptype, "content": FULL_ACCESS,
                                       "created": _iso(), "aws_managed": True}


def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fix_policy_arn(o: dict, p: dict) -> None:
    """Policies made by IAM's older Vyomi-only CreateOrgPolicy carry a placeholder org id."""
    if not p.get("aws_managed") and "/o-vyomi/" in p.get("arn", ""):
        p["arn"] = p["arn"].replace("/o-vyomi/", f"/{o['id']}/")


# ── organization ───────────────────────────────────────────────────────────
def _create_organization(store, b):
    if _org(store, required=False):
        raise OrgError("AlreadyInOrganizationException", "The account is already a member of an organization.")
    fs = b.get("FeatureSet") or "ALL"
    if fs not in ("ALL", "CONSOLIDATED_BILLING"):
        raise OrgError("InvalidInputException", "You specified an invalid value for FeatureSet.")
    mgmt = store.account_id
    oid = "o-" + _rid(10)
    rid = "r-" + _rid(4)
    o = {"id": oid, "feature_set": fs, "master_account_id": mgmt, "master_account_email": MGMT_EMAIL,
         "arn": f"arn:aws:organizations::{mgmt}:organization/{oid}",
         "master_account_arn": f"arn:aws:organizations::{mgmt}:account/{oid}/{mgmt}",
         "roots": {}, "ous": {}, "accounts": {}, "attachments": {}, "service_access": {}, "delegated": {},
         "tags": {}, "handshakes": {}, "create_status": {}}
    o["roots"][rid] = {"id": rid, "arn": f"arn:aws:organizations::{mgmt}:root/{oid}/{rid}", "name": "Root",
                       "policy_types": {SCP} if fs == "ALL" else set()}
    o["roots"][rid]["policy_types"] = sorted(o["roots"][rid]["policy_types"])
    o["accounts"][mgmt] = {"id": mgmt, "arn": o["master_account_arn"], "email": MGMT_EMAIL, "name": "Management account",
                           "status": "ACTIVE", "state": "ACTIVE", "joined_method": "INVITED", "joined": _ts(), "parent": rid}
    store.extras["org"] = o
    _ensure_managed(store, o)
    if fs == "ALL":
        o["attachments"][rid] = [FULL_ACCESS_ID]
    _persist(store)
    return {"Organization": _s_org(o)}


def _describe_organization(store, b):
    return {"Organization": _s_org(_org(store))}


def _delete_organization(store, b):
    o = _org(store)
    if len(o["accounts"]) > 1 or o["ous"]:
        raise OrgError("OrganizationNotEmptyException", "To delete an organization you must first remove all member accounts (except the master).")
    store.org_policies.clear()
    del store.extras["org"]
    _persist(store)
    return {}


def _list_roots(store, b):
    o = _org(store)
    return {"Roots": [_s_root(r) for r in o["roots"].values()]}


def _enable_all_features(store, b):
    o = _org(store)
    o["feature_set"] = "ALL"
    r = _root(o)
    if SCP not in r["policy_types"]:
        r["policy_types"] = sorted(set(r["policy_types"]) | {SCP})
        o["attachments"].setdefault(r["id"], [])
        if FULL_ACCESS_ID not in o["attachments"][r["id"]]:
            o["attachments"][r["id"]].append(FULL_ACCESS_ID)
    _persist(store)
    return {"Handshake": _make_handshake(store, o, "ENABLE_ALL_FEATURES", [{"Id": o["master_account_id"], "Type": "ACCOUNT"}], state="ACCEPTED")}


def _enable_policy_type(store, b):
    o = _org(store)
    r = o["roots"].get(b.get("RootId"))
    t = b.get("PolicyType")
    if not r:
        raise OrgError("RootNotFoundException", "You specified a root that doesn't exist.")
    if t not in POLICY_TYPES:
        raise OrgError("InvalidInputException", "You specified an invalid value for PolicyType.")
    if o["feature_set"] != "ALL":
        raise OrgError("AccessDeniedForDependencyException", "All features must be enabled in the organization.")
    if t in r["policy_types"]:
        raise OrgError("PolicyTypeAlreadyEnabledException", "The specified policy type is already enabled.")
    r["policy_types"] = sorted(set(r["policy_types"]) | {t})
    if t in (SCP, RCP):
        pid = FULL_ACCESS_ID if t == SCP else FULL_ACCESS_RCP_ID
        _ensure_managed(store, o)
        o["attachments"].setdefault(r["id"], [])
        if pid not in o["attachments"][r["id"]]:
            o["attachments"][r["id"]].append(pid)
    _persist(store)
    return {"Root": _s_root(r)}


def _disable_policy_type(store, b):
    o = _org(store)
    r = o["roots"].get(b.get("RootId"))
    t = b.get("PolicyType")
    if not r:
        raise OrgError("RootNotFoundException", "You specified a root that doesn't exist.")
    if t not in r["policy_types"]:
        raise OrgError("PolicyTypeNotEnabledException", "The specified policy type isn't currently enabled in this root.")
    r["policy_types"] = [x for x in r["policy_types"] if x != t]
    for target, pids in o["attachments"].items():   # disabling a type detaches every policy of that type
        o["attachments"][target] = [p for p in pids if store.org_policies.get(p, {}).get("type") != t]
    _persist(store)
    return {"Root": _s_root(r)}


# ── OUs ────────────────────────────────────────────────────────────────────
def _create_ou(store, b):
    o = _org(store)
    parent, name = b.get("ParentId"), (b.get("Name") or "").strip()
    _need_parent(o, parent)
    if not name:
        raise OrgError("InvalidInputException", "You specified an invalid value for Name.")
    if any(u["name"] == name and u["parent"] == parent for u in o["ous"].values()):
        raise OrgError("DuplicateOrganizationalUnitException", "An OU with the same name already exists.")
    rootid = _root(o)["id"]
    uid = "ou-" + rootid[2:] + "-" + _rid(8)
    u = {"id": uid, "arn": _arn(store, o, "ou", uid), "name": name, "parent": parent}
    o["ous"][uid] = u
    _tag_into(o, uid, b.get("Tags"))
    _persist(store)
    return {"OrganizationalUnit": _s_ou(u)}


def _need_ou(o, ouid):
    u = o["ous"].get(ouid)
    if not u:
        raise OrgError("OrganizationalUnitNotFoundException", "You specified an organizational unit that doesn't exist.")
    return u


def _describe_ou(store, b):
    o = _org(store)
    return {"OrganizationalUnit": _s_ou(_need_ou(o, b.get("OrganizationalUnitId")))}


def _update_ou(store, b):
    o = _org(store)
    u = _need_ou(o, b.get("OrganizationalUnitId"))
    name = (b.get("Name") or "").strip()
    if name:
        if any(x["name"] == name and x["parent"] == u["parent"] and x["id"] != u["id"] for x in o["ous"].values()):
            raise OrgError("DuplicateOrganizationalUnitException", "An OU with the same name already exists.")
        u["name"] = name
    _persist(store)
    return {"OrganizationalUnit": _s_ou(u)}


def _delete_ou(store, b):
    o = _org(store)
    u = _need_ou(o, b.get("OrganizationalUnitId"))
    ous, accts = _children_of(o, u["id"])
    if ous or accts:
        raise OrgError("OrganizationalUnitNotEmptyException", "You can't delete an OU that contains accounts or other OUs.")
    del o["ous"][u["id"]]
    o["attachments"].pop(u["id"], None)
    o["tags"].pop(u["id"], None)
    _persist(store)
    return {}


def _list_ous_for_parent(store, b):
    o = _org(store)
    _need_parent(o, b.get("ParentId"))
    return {"OrganizationalUnits": [_s_ou(u) for u in _children_of(o, b.get("ParentId"))[0]]}


def _list_children(store, b):
    o = _org(store)
    _need_parent(o, b.get("ParentId"))
    ct = b.get("ChildType")
    if ct not in ("ACCOUNT", "ORGANIZATIONAL_UNIT"):
        raise OrgError("InvalidInputException", "You specified an invalid value for ChildType.")
    ous, accts = _children_of(o, b.get("ParentId"))
    return {"Children": [{"Id": x["id"], "Type": ct} for x in (accts if ct == "ACCOUNT" else ous)]}


def _list_parents(store, b):
    o = _org(store)
    cid = b.get("ChildId")
    kind, rec = _node(o, cid)
    if kind not in ("ACCOUNT", "ORGANIZATIONAL_UNIT"):
        raise OrgError("ChildNotFoundException", "You specified a child that doesn't exist.")
    pk, _ = _node(o, rec["parent"])
    return {"Parents": [{"Id": rec["parent"], "Type": pk}]}


# ── accounts ───────────────────────────────────────────────────────────────
def _new_account_id(o: dict) -> str:
    while True:
        a = "".join(random.choices(string.digits, k=12))
        if a not in o["accounts"] and a[0] != "0":
            return a


def _create_account(store, b):
    o = _org(store)
    email, name = (b.get("Email") or "").strip(), (b.get("AccountName") or "").strip()
    if "@" not in email or not name:
        raise OrgError("ConstraintViolationException", "Email and AccountName are required (email must be a valid address).")
    if any(a["email"].lower() == email.lower() for a in o["accounts"].values()):
        st = _status_rec(o, name, "FAILED", None, "EMAIL_ALREADY_EXISTS")
        return {"CreateAccountStatus": _s_status(st)}
    aid = _new_account_id(o)
    o["accounts"][aid] = {"id": aid, "arn": _arn(store, o, "account", aid), "email": email, "name": name,
                          "status": "ACTIVE", "state": "ACTIVE", "joined_method": "CREATED", "joined": _ts(),
                          "parent": _root(o)["id"], "role_name": b.get("RoleName") or "OrganizationAccountAccessRole"}
    _tag_into(o, aid, b.get("Tags"))
    st = _status_rec(o, name, "SUCCEEDED", aid)
    _persist(store)
    return {"CreateAccountStatus": _s_status(st)}


def _status_rec(o, name, state, aid, reason=None) -> dict:
    sid = "car-" + uuid.uuid4().hex
    st = {"id": sid, "account_name": name, "state": state, "requested": _ts(), "completed": _ts(), "account_id": aid}
    if reason:
        st["failure_reason"] = reason
    o["create_status"][sid] = st
    return st


def _describe_create_status(store, b):
    o = _org(store)
    st = o["create_status"].get(b.get("CreateAccountRequestId"))
    if not st:
        raise OrgError("CreateAccountStatusNotFoundException", "We can't find an create account request with the CreateAccountRequestId that you specified.")
    return {"CreateAccountStatus": _s_status(st)}


def _list_create_status(store, b):
    o = _org(store)
    states = b.get("States") or []
    return {"CreateAccountStatuses": [_s_status(s) for s in o["create_status"].values() if not states or s["state"] in states]}


def _describe_account(store, b):
    o = _org(store)
    return {"Account": _s_acct(_need_account(o, b.get("AccountId")))}


def _list_accounts(store, b):
    o = _org(store)
    return {"Accounts": [_s_acct(a) for a in o["accounts"].values()]}


def _list_accounts_for_parent(store, b):
    o = _org(store)
    _need_parent(o, b.get("ParentId"))
    return {"Accounts": [_s_acct(a) for a in _children_of(o, b.get("ParentId"))[1]]}


def _move_account(store, b):
    o = _org(store)
    a = _need_account(o, b.get("AccountId"))
    src, dst = b.get("SourceParentId"), b.get("DestinationParentId")
    _need_parent(o, src)
    _need_parent(o, dst)
    if a["parent"] != src:
        raise OrgError("SourceParentNotFoundException", "We can't find a source root or OU with the ParentId that you specified.")
    a["parent"] = dst
    _persist(store)
    return {}


def _remove_account(store, b):
    o = _org(store)
    a = _need_account(o, b.get("AccountId"))
    if a["id"] == o["master_account_id"]:
        raise OrgError("MasterCannotLeaveOrganizationException", "You can't remove the management account from the organization.")
    del o["accounts"][a["id"]]
    o["attachments"].pop(a["id"], None)
    o["tags"].pop(a["id"], None)
    for acct in list(o["delegated"]):
        if acct == a["id"]:
            del o["delegated"][acct]
    _persist(store)
    return {}


def _close_account(store, b):
    o = _org(store)
    a = _need_account(o, b.get("AccountId"))
    if a["id"] == o["master_account_id"]:
        raise OrgError("ConstraintViolationException", "You can't close the management account.")
    if a["status"] == "SUSPENDED" or a["state"] == "PENDING_CLOSURE":
        raise OrgError("AccountAlreadyClosedException", "The specified account is already closed.")
    a["state"], a["status"] = "PENDING_CLOSURE", "SUSPENDED"
    _persist(store)
    return {}


# ── handshakes (invite-lite) ───────────────────────────────────────────────
def _make_handshake(store, o, action, resources, state="OPEN", target=None) -> dict:
    hid = "h-" + _rid(8) + _rid(8)
    h = {"id": hid, "arn": f"arn:aws:organizations::{o['master_account_id']}:handshake/{o['id']}/{action.lower()}/{hid}",
         "parties": [{"Id": o["master_account_id"], "Type": "ACCOUNT"}] + ([target] if target else []),
         "state": state, "requested": _ts(), "expires": _ts() + 15 * 86400, "action": action,
         "resources": [{"Type": "ORGANIZATION", "Value": o["id"]}] + ([{"Type": "ACCOUNT", "Value": target["Id"]}] if target else [])}
    o["handshakes"][hid] = h
    _persist(store)
    return _s_handshake(h)


def _invite(store, b):
    o = _org(store)
    t = b.get("Target") or {}
    tid, ttype = (t.get("Id") or "").strip(), t.get("Type")
    if ttype not in ("ACCOUNT", "EMAIL") or not tid:
        raise OrgError("InvalidInputException", "You specified an invalid Target.")
    if ttype == "ACCOUNT" and (len(tid) != 12 or not tid.isdigit()):
        raise OrgError("InvalidInputException", "You specified an invalid account ID.")
    if any((a["id"] == tid or a["email"].lower() == tid.lower()) for a in o["accounts"].values()):
        raise OrgError("DuplicateAccountException", "That account is already present in the specified destination.")
    if any(h["state"] == "OPEN" and h["action"] == "INVITE" and any(p["Id"] == tid for p in h["parties"]) for h in o["handshakes"].values()):
        raise OrgError("DuplicateHandshakeException", "A handshake for this target is already pending.")
    h = _make_handshake(store, o, "INVITE", [], target={"Id": tid, "Type": ttype})
    _tag_into(o, h["Id"], b.get("Tags"))
    return {"Handshake": h}


def _need_handshake(o, hid):
    h = o["handshakes"].get(hid)
    if not h:
        raise OrgError("HandshakeNotFoundException", "We can't find a handshake with the HandshakeId that you specified.")
    return h


def _handshake_transition(store, b, new_state):
    o = _org(store)
    h = _need_handshake(o, b.get("HandshakeId"))
    if h["state"] != "OPEN":
        raise OrgError("InvalidHandshakeTransitionException", f"You can't {new_state.lower()} a handshake that is {h['state']}.")
    h["state"] = new_state
    if new_state == "ACCEPTED" and h["action"] == "INVITE":
        tgt = h["parties"][1]
        aid = tgt["Id"] if tgt["Type"] == "ACCOUNT" else _new_account_id(o)
        email = tgt["Id"] if tgt["Type"] == "EMAIL" else f"account-{aid}@vyomi.local"
        o["accounts"][aid] = {"id": aid, "arn": _arn(store, o, "account", aid), "email": email, "name": f"Account {aid}",
                              "status": "ACTIVE", "state": "ACTIVE", "joined_method": "INVITED", "joined": _ts(), "parent": _root(o)["id"]}
    _persist(store)
    return {"Handshake": _s_handshake(h)}


def _list_handshakes(store, b):
    o = _org(store)
    return {"Handshakes": [_s_handshake(h) for h in o["handshakes"].values()]}


# ── policies ───────────────────────────────────────────────────────────────
def _create_policy(store, b):
    o = _org(store)
    name, ptype = (b.get("Name") or "").strip(), b.get("Type")
    if not name:
        raise OrgError("InvalidInputException", "You specified an invalid value for Name.")
    if ptype not in POLICY_TYPES:
        raise OrgError("InvalidInputException", "You specified an invalid value for Type.")
    content = b.get("Content") or ""
    try:
        doc = json.loads(content)
        if not isinstance(doc, dict):
            raise ValueError
    except Exception:
        raise OrgError("MalformedPolicyDocumentException", "The provided policy document does not meet the requirements of the specified policy type.")
    if ptype in (SCP, RCP) and not isinstance(doc.get("Statement"), (list, dict)):
        raise OrgError("MalformedPolicyDocumentException", "The provided policy document does not meet the requirements of the specified policy type.")
    if any(p["name"] == name and p["type"] == ptype for p in store.org_policies.values()):
        raise OrgError("DuplicatePolicyException", "A policy with the same name already exists.")
    pid = "p-" + _rid(8)
    p = {"id": pid, "arn": _arn(store, o, f"policy", f"{ptype.lower()}/{pid}"), "name": name,
         "description": b.get("Description", ""), "type": ptype, "content": content, "created": _iso()}
    p["arn"] = f"arn:aws:organizations::{o['master_account_id']}:policy/{o['id']}/{ptype.lower()}/{pid}"
    store.org_policies[pid] = p
    _tag_into(o, pid, b.get("Tags"))
    _persist(store)
    return {"Policy": _s_policy(o, p)}


def _describe_policy(store, b):
    o = _org(store)
    p = _need_policy(store, b.get("PolicyId"))
    _fix_policy_arn(o, p)
    return {"Policy": _s_policy(o, p)}


def _update_policy(store, b):
    o = _org(store)
    p = _need_policy(store, b.get("PolicyId"))
    if p.get("aws_managed"):
        raise OrgError("PolicyChangesInProgressException", "You can't modify an AWS managed policy.")
    if b.get("Name"):
        p["name"] = b["Name"].strip()
    if b.get("Description") is not None:
        p["description"] = b["Description"]
    if b.get("Content"):
        try:
            json.loads(b["Content"])
        except Exception:
            raise OrgError("MalformedPolicyDocumentException", "The provided policy document does not meet the requirements of the specified policy type.")
        p["content"] = b["Content"]
    _persist(store)
    return {"Policy": _s_policy(o, p)}


def _delete_policy(store, b):
    o = _org(store)
    p = _need_policy(store, b.get("PolicyId"))
    if p.get("aws_managed"):
        raise OrgError("InvalidInputException", "You can't delete an AWS managed policy.")
    if _attached(o, p["id"]):
        raise OrgError("PolicyInUseException", "The policy is attached to one or more entities. You must detach it from all roots, OUs, and accounts before performing this operation.")
    del store.org_policies[p["id"]]
    o["tags"].pop(p["id"], None)
    _persist(store)
    return {}


def _list_policies(store, b):
    o = _org(store)
    f = b.get("Filter")
    if f not in POLICY_TYPES:
        raise OrgError("InvalidInputException", "You specified an invalid value for Filter.")
    return {"Policies": [_s_policy_summary(o, p) for p in store.org_policies.values() if p["type"] == f]}


def _target(o, tid):
    kind, rec = _node(o, tid)
    if not kind:
        raise OrgError("TargetNotFoundException", "We can't find a root, OU, or account with the TargetId that you specified.")
    return kind, rec


def _attach_policy(store, b):
    o = _org(store)
    p = _need_policy(store, b.get("PolicyId"))
    tid = b.get("TargetId")
    _target(o, tid)
    if p["type"] not in _root(o)["policy_types"]:
        raise OrgError("PolicyTypeNotEnabledException", "The specified policy type isn't currently enabled in this root.")
    cur = o["attachments"].setdefault(tid, [])
    if p["id"] in cur:
        raise OrgError("DuplicatePolicyAttachmentException", "The selected policy is already attached to the specified target.")
    cur.append(p["id"])
    _persist(store)
    return {}


def _detach_policy(store, b):
    o = _org(store)
    p = _need_policy(store, b.get("PolicyId"))
    tid = b.get("TargetId")
    _target(o, tid)
    cur = o["attachments"].get(tid, [])
    if p["id"] not in cur:
        raise OrgError("PolicyNotAttachedException", "The policy isn't attached to the specified target.")
    if p["type"] in (SCP, RCP) and sum(1 for x in cur if store.org_policies.get(x, {}).get("type") == p["type"]) <= 1:
        raise OrgError("ConstraintViolationException", "You can't detach the last policy of this type from a target — attach another first (a target must keep at least one SCP/RCP).")
    cur.remove(p["id"])
    _persist(store)
    return {}


def _list_targets_for_policy(store, b):
    o = _org(store)
    p = _need_policy(store, b.get("PolicyId"))
    out = []
    for t in _attached(o, p["id"]):
        kind, rec = _node(o, t)
        if kind:
            out.append({"TargetId": t, "Arn": rec["arn"], "Name": rec["name"], "Type": kind})
    return {"Targets": out}


def _list_policies_for_target(store, b):
    o = _org(store)
    tid, f = b.get("TargetId"), b.get("Filter")
    _target(o, tid)
    if f not in POLICY_TYPES:
        raise OrgError("InvalidInputException", "You specified an invalid value for Filter.")
    return {"Policies": [_s_policy_summary(o, store.org_policies[p]) for p in o["attachments"].get(tid, [])
                         if p in store.org_policies and store.org_policies[p]["type"] == f]}


# ── service access + delegated administrators ──────────────────────────────
def _need_all_features(o):
    if o["feature_set"] != "ALL":
        raise OrgError("ConstraintViolationException", "All features must be enabled in the organization.")


def _enable_service_access(store, b):
    o = _org(store)
    _need_all_features(o)
    sp = (b.get("ServicePrincipal") or "").strip()
    if not sp or "." not in sp:
        raise OrgError("InvalidInputException", "You specified an invalid value for ServicePrincipal.")
    o["service_access"].setdefault(sp, _ts())
    _persist(store)
    return {}


def _disable_service_access(store, b):
    o = _org(store)
    sp = b.get("ServicePrincipal")
    if sp not in o["service_access"]:
        return {}
    if any(sp in d["services"] for d in o["delegated"].values()):
        raise OrgError("ConstraintViolationException", "Remove the delegated administrators for this service first.")
    del o["service_access"][sp]
    if sp == "iam.amazonaws.com":
        o.pop("iam_features", None)
    _persist(store)
    return {}


def _list_service_access(store, b):
    o = _org(store)
    return {"EnabledServicePrincipals": [{"ServicePrincipal": sp, "DateEnabled": d} for sp, d in sorted(o["service_access"].items())]}


def _register_delegated(store, b):
    o = _org(store)
    a = _need_account(o, b.get("AccountId"))
    sp = b.get("ServicePrincipal")
    if a["id"] == o["master_account_id"]:
        raise OrgError("ConstraintViolationException", "You can't register the management account as a delegated administrator.")
    if sp not in o["service_access"]:
        raise OrgError("ConstraintViolationException", "The service principal must have trusted access enabled (EnableAWSServiceAccess) first.")
    d = o["delegated"].setdefault(a["id"], {"services": {}, "enabled": _ts()})
    if sp in d["services"]:
        raise OrgError("AccountAlreadyRegisteredException", "The provided account is already a delegated administrator for your organization.")
    d["services"][sp] = _ts()
    _persist(store)
    return {}


def _deregister_delegated(store, b):
    o = _org(store)
    a = _need_account(o, b.get("AccountId"))
    d, sp = o["delegated"].get(a["id"]), b.get("ServicePrincipal")
    if not d or sp not in d["services"]:
        raise OrgError("AccountNotRegisteredException", "The specified account is not a delegated administrator for this organization.")
    del d["services"][sp]
    if not d["services"]:
        del o["delegated"][a["id"]]
    _persist(store)
    return {}


def _list_delegated(store, b):
    o = _org(store)
    sp = b.get("ServicePrincipal")
    out = []
    for aid, d in o["delegated"].items():
        if sp and sp not in d["services"]:
            continue
        a = o["accounts"].get(aid)
        if a:
            out.append({**_s_acct(a), "DelegationEnabledDate": d["enabled"]})
    return {"DelegatedAdministrators": out}


def _list_delegated_services(store, b):
    o = _org(store)
    a = _need_account(o, b.get("AccountId"))
    d = o["delegated"].get(a["id"])
    if not d:
        raise OrgError("AccountNotRegisteredException", "The specified account is not a delegated administrator for this organization.")
    return {"DelegatedServices": [{"ServicePrincipal": sp, "DelegationEnabledDate": t} for sp, t in d["services"].items()]}


# ── tags ───────────────────────────────────────────────────────────────────
def _tag_into(o, rid, tags):
    if tags:
        cur = o["tags"].setdefault(rid, {})
        for t in tags:
            cur[t.get("Key")] = t.get("Value", "")


def _tag_target(o, rid):
    kind, _ = _node(o, rid)
    if kind or rid in o["handshakes"]:
        return
    raise OrgError("TargetNotFoundException", "We can't find a root, OU, account or policy with the ResourceId that you specified.")


def _need_taggable(store, o, rid):
    if rid in store.org_policies or rid in o["handshakes"]:
        return
    _tag_target(o, rid)


def _tag_resource(store, b):
    o = _org(store)
    rid = b.get("ResourceId")
    _need_taggable(store, o, rid)
    if not b.get("Tags"):
        raise OrgError("InvalidInputException", "Tags are required.")
    _tag_into(o, rid, b["Tags"])
    _persist(store)
    return {}


def _untag_resource(store, b):
    o = _org(store)
    rid = b.get("ResourceId")
    _need_taggable(store, o, rid)
    for k in b.get("TagKeys") or []:
        o["tags"].get(rid, {}).pop(k, None)
    _persist(store)
    return {}


def _list_tags(store, b):
    o = _org(store)
    rid = b.get("ResourceId")
    _need_taggable(store, o, rid)
    return {"Tags": [{"Key": k, "Value": v} for k, v in o["tags"].get(rid, {}).items()]}


# ── SCP chain evaluation (policy-simulator seam; not applied to live traffic) ──
def effective_scp_decision(store, account_id: str, action: str, resource: str = "*", context: dict | None = None):
    """(decision, reason) for the attached-SCP chain root -> OUs -> account, AWS semantics: at EVERY
    level the union of that level's SCPs must allow the action and no SCP anywhere may deny it.
    The management account is not restricted by SCPs. No organization / SCPs disabled -> allowed."""
    o = (getattr(store, "extras", None) or {}).get("org")
    if not o or SCP not in _root(o)["policy_types"]:
        return "allowed", "no service control policies in effect"
    if account_id == o["master_account_id"]:
        return "allowed", "SCPs do not restrict the management account"
    if account_id not in o["accounts"]:
        return "allowed", "account is not a member of the organization"
    engine = getattr(store, "engine", None)
    chain, cur = [], o["accounts"][account_id]["parent"]
    while cur:
        chain.append(cur)
        kind, rec = _node(o, cur)
        cur = rec.get("parent") if kind == "ORGANIZATIONAL_UNIT" else None
    chain = [account_id] + chain
    for level in chain:
        docs = []
        for pid in o["attachments"].get(level, []):
            p = store.org_policies.get(pid)
            if p and p["type"] == SCP:
                try:
                    docs.append(json.loads(p["content"]))
                except Exception:
                    pass
        if level == account_id and not docs:
            continue
        if not docs:
            return "implicitDeny", f"no SCP attached at {level} allows {action}"
        d, _ = engine.evaluate(docs, action, resource, context or {})
        if d != "allowed":
            return d, f"service control policies at {level} do not allow {action}"
    return "allowed", "allowed by the SCP chain"


# ── dispatch ───────────────────────────────────────────────────────────────
_OPS = {
    "CreateOrganization": _create_organization, "DescribeOrganization": _describe_organization,
    "DeleteOrganization": _delete_organization, "ListRoots": _list_roots, "EnableAllFeatures": _enable_all_features,
    "EnablePolicyType": _enable_policy_type, "DisablePolicyType": _disable_policy_type,
    "CreateOrganizationalUnit": _create_ou, "DescribeOrganizationalUnit": _describe_ou,
    "UpdateOrganizationalUnit": _update_ou, "DeleteOrganizationalUnit": _delete_ou,
    "ListOrganizationalUnitsForParent": _list_ous_for_parent, "ListChildren": _list_children, "ListParents": _list_parents,
    "CreateAccount": _create_account, "DescribeCreateAccountStatus": _describe_create_status,
    "ListCreateAccountStatus": _list_create_status, "DescribeAccount": _describe_account,
    "ListAccounts": _list_accounts, "ListAccountsForParent": _list_accounts_for_parent,
    "MoveAccount": _move_account, "RemoveAccountFromOrganization": _remove_account, "CloseAccount": _close_account,
    "InviteAccountToOrganization": _invite,
    "DescribeHandshake": lambda s, b: {"Handshake": _s_handshake(_need_handshake(_org(s), b.get("HandshakeId")))},
    "AcceptHandshake": lambda s, b: _handshake_transition(s, b, "ACCEPTED"),
    "DeclineHandshake": lambda s, b: _handshake_transition(s, b, "DECLINED"),
    "CancelHandshake": lambda s, b: _handshake_transition(s, b, "CANCELED"),
    "ListHandshakesForOrganization": _list_handshakes, "ListHandshakesForAccount": _list_handshakes,
    "CreatePolicy": _create_policy, "DescribePolicy": _describe_policy, "UpdatePolicy": _update_policy,
    "DeletePolicy": _delete_policy, "ListPolicies": _list_policies, "AttachPolicy": _attach_policy,
    "DetachPolicy": _detach_policy, "ListTargetsForPolicy": _list_targets_for_policy,
    "ListPoliciesForTarget": _list_policies_for_target,
    "EnableAWSServiceAccess": _enable_service_access, "DisableAWSServiceAccess": _disable_service_access,
    "ListAWSServiceAccessForOrganization": _list_service_access,
    "RegisterDelegatedAdministrator": _register_delegated, "DeregisterDelegatedAdministrator": _deregister_delegated,
    "ListDelegatedAdministrators": _list_delegated, "ListDelegatedServicesForAccount": _list_delegated_services,
    "TagResource": _tag_resource, "UntagResource": _untag_resource, "ListTagsForResource": _list_tags,
}


def dispatch(store, target: str, payload: dict | None = None) -> OrgResponse:
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    op = _OPS.get(action)
    hdrs = {"x-amzn-requestid": str(uuid.uuid4())}
    if op is None:
        return OrgResponse(400, {"__type": "UnknownOperationException", "Message": f"The action {action} is not implemented."}, hdrs)
    if getattr(store, "extras", None) is None:
        store.extras = {}
    try:
        res = op(store, body)
        # older Vyomi-only policies may carry a placeholder org id: normalise lazily
        o = store.extras.get("org")
        if o:
            for p in store.org_policies.values():
                _fix_policy_arn(o, p)
        return OrgResponse(200, res, hdrs)
    except OrgError as e:
        return OrgResponse(e.status, {"__type": e.code, "Message": e.message}, hdrs)
