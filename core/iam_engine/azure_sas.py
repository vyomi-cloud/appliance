"""Azure Storage data-plane authorization that is NOT Azure RBAC: SAS tokens and Shared Key.

Pure Python (stdlib, Pyodide-safe). Called from azure_eval.evaluate when the principal type is "sas" or "sharedkey".

  Shared Key   the account key authorises EVERYTHING on its own storage account (blob / queue / table data plane) and nothing else:
               no control plane, no other account, and nothing at all when the account has allowSharedKeyAccess=false.
  SAS          authorization is the token's own claims: signed permissions `sp`, expiry `se` / start `st`, service/resource scope
               (`sr` for blob service SAS, `ss` + `srt` for account SAS), `spr` protocol is not enforced (the simulator speaks http).
               A user-delegation SAS (`skoid`) is the intersection of the token and the delegating identity's RBAC (evaluated by the caller via `rbac`).
               The signature is NOT cryptographically verified here (the data-plane handlers do not hold the key either) and a stored access policy
               (`si`) cannot be resolved to permissions: such a token with no `sp` is treated as granting the request (documented limit).

principal = {"type": "sas"|"sharedkey", "object_id": "sas:<acct>", "account": "<acct>", "sas": {query params of the token}}
request   = azure_eval request: resource "/<account>/<container>/<blob>" | "/<account>/<queue>/messages" | "/<account>/<table>(...)",
            action = the dataAction, context["hint"] in ("list", "update") when the action alone cannot tell the SAS permission.
Denial decisions carry `storageError` = {"code", "status", "message"} (the real Storage error the data plane answers with)."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .types import decision

_BLOB = "microsoft.storage/storageaccounts/blobservices/containers"
_QUEUE = "microsoft.storage/storageaccounts/queueservices/queues"
_TABLE = "microsoft.storage/storageaccounts/tableservices/tables"

# (service letter in `ss`, level of the target: s service-level, c container/queue/table, o object/message/entity, SAS permission letters (any one suffices))


def classify(action, hint=None):
    """dataAction (+ hint) -> (service 'b'|'q'|'t', level 's'|'c'|'o', frozenset of permission letters of which ANY authorises), or None."""
    a = str(action or "").lower()
    if a.startswith(_BLOB):
        rest = a[len(_BLOB):]
        if rest.startswith("/blobs"):
            r = rest[len("/blobs"):]
            if r in ("/read",):
                return "b", ("c" if hint == "list" else "o"), frozenset("l" if hint == "list" else "r")
            if r == "/write":
                return "b", "o", frozenset("wc")
            if r == "/add/action":
                return "b", "o", frozenset("aw")
            if r == "/delete":
                return "b", "o", frozenset("d")
            if r.startswith("/tags/"):
                return "b", "o", frozenset("t")
            return "b", "o", frozenset("w")
        return "b", "c", {"/read": frozenset("rl"), "/write": frozenset("cw"), "/delete": frozenset("d")}.get(rest, frozenset("r"))
    if a.startswith(_QUEUE):
        rest = a[len(_QUEUE):]
        if rest.startswith("/messages"):
            r = rest[len("/messages"):]
            return "q", "o", {"/read": frozenset("r"), "/add/action": frozenset("a"), "/delete": frozenset("p"),
                              "/process/action": frozenset("u" if hint == "update" else "p")}.get(r, frozenset("p"))
        return "q", "c", {"/read": frozenset("rl"), "/write": frozenset("cw"), "/delete": frozenset("d")}.get(rest, frozenset("r"))
    if a.startswith(_TABLE):
        rest = a[len(_TABLE):]
        if rest.startswith("/entities"):
            r = rest[len("/entities"):]
            return "t", "o", {"/read": frozenset("r"), "/add/action": frozenset("a"), "/update/action": frozenset("u"),
                              "/delete": frozenset("d"), "/write": frozenset("au")}.get(r, frozenset("au"))
        return "t", "c", {"/read": frozenset("rl"), "/write": frozenset("cau"), "/delete": frozenset("d")}.get(rest, frozenset("r"))
    return None


def _err(code, message, status=403):
    return {"code": code, "status": status, "message": message}


def _deny(code, message, reason="implicit_deny", **extra):
    return decision(False, reason, [], storageError=_err(code, message), **extra)


def _parse_time(v):
    v = str(v or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(v, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _account_of(resource):
    p = str(resource or "").strip("/").split("/", 1)[0]
    return p.lower()


def _acct_props(state, account):
    return ((state or {}).get("storage_accounts") or {}).get(str(account).lower()) or {}


def evaluate(req, state, rbac=None, now=None):
    """-> decision. `rbac(req, state)` evaluates Azure RBAC (used for user-delegation SAS)."""
    pr = req.get("principal") or {}
    kind = pr.get("type")
    account = str(pr.get("account") or "").lower()
    target = _account_of(req.get("resource"))
    if not req.get("data"):
        return _deny("AuthenticationFailed", "Shared Key / SAS credentials authorise the storage data plane only, not Azure Resource Manager.")
    cls = classify(req.get("action"), (req.get("context") or {}).get("hint"))
    if cls is None:
        return _deny("AuthorizationFailure", "This request is not authorized to perform this operation: Shared Key / SAS credentials cover Blob, Queue and Table data only.")
    if target and account and account != target:
        return _deny("AuthenticationFailed", "Server failed to authenticate the request. Make sure the value of Authorization header is formed correctly including the signature.")
    props = _acct_props(state, target or account)
    if props.get("allowSharedKeyAccess") is False and not (kind == "sas" and (pr.get("sas") or {}).get("skoid")):
        return _deny("KeyBasedAuthenticationNotPermitted", "Key based authentication is not permitted on this storage account.")
    if kind == "sharedkey":
        return decision(True, "allow", [{"source": "shared_key", "id": "account:" + (target or account), "effect": "Allow",
                                         "statement": {"note": "the account key grants full access to its own data plane"}}])
    sas = {str(k).lower(): str(v) for k, v in (pr.get("sas") or {}).items()}
    now = now or datetime.now(timezone.utc)
    se, st = _parse_time(sas.get("se")), _parse_time(sas.get("st"))
    if sas.get("se") and (se is None or now > se):
        return _deny("AuthenticationFailed", "Server failed to authenticate the request. Make sure the value of Authorization header is formed correctly including the signature.",
                     failedLayer="expired")
    if st is not None and now < st:
        return _deny("AuthenticationFailed", "Server failed to authenticate the request. Make sure the value of Authorization header is formed correctly including the signature.",
                     failedLayer="not_yet_valid")
    svc, level, letters = cls
    segs = [x for x in str(req.get("resource") or "").strip("/").split("/") if x]
    if len(segs) <= 1 or (svc == "t" and len(segs) == 2 and segs[1].lower() == "tables"):
        level = "s"                                         # account-level: list containers / queues / tables, service properties
    sp = set(sas.get("sp", "").lower())
    if "ss" in sas or "srt" in sas:                         # account SAS: services + resource types + permissions
        if svc not in sas.get("ss", "").lower() or level not in sas.get("srt", "").lower():
            return _deny("AuthorizationResourceTypeMismatch", "This request is not authorized to perform this operation using this resource type.", failedLayer="sas_scope")
    elif svc == "b":                                       # blob service SAS: sr = b blob | c container (| bs snapshot | bv version)
        sr = sas.get("sr", "").lower()
        if sr == "c" and level == "s":
            return _deny("AuthorizationResourceTypeMismatch", "This request is not authorized to perform this operation using this resource type.", failedLayer="sas_scope")
        if sr in ("b", "bs", "bv") and level != "o":
            return _deny("AuthorizationResourceTypeMismatch", "This request is not authorized to perform this operation using this resource type.", failedLayer="sas_scope")
    if not sp and sas.get("si"):                            # stored access policy: permissions live in the container/queue/table ACL (not resolved)
        ok = True
    else:
        ok = bool(sp & letters)
    if ok and sas.get("skoid") and rbac is not None:        # user delegation SAS: the delegating identity's RBAC must also allow it
        d = rbac(dict(req, principal={"object_id": sas["skoid"], "type": "user"}), state)
        if not d.get("allowed"):
            return _deny("AuthorizationPermissionMismatch", "This request is not authorized to perform this operation using this permission.", failedLayer="delegator")
    if not ok:
        return _deny("AuthorizationPermissionMismatch", "This request is not authorized to perform this operation using this permission.", failedLayer="sas_permission")
    return decision(True, "allow", [{"source": "sas", "id": "sp=" + sas.get("sp", ""), "effect": "Allow",
                                     "statement": {"sp": sas.get("sp", ""), "required_any_of": "".join(sorted(letters)), "se": sas.get("se")}}])


def parse_shared_key(authorization):
    """'SharedKey <acct>:<sig>' | 'SharedKeyLite <acct>:<sig>' -> account name, else ''."""
    m = re.match(r"^\s*SharedKey(?:Lite)?\s+([^:\s]+):", str(authorization or ""), re.I)
    return m.group(1).lower() if m else ""


def is_sas(query):
    """query: dict[str, str] (lower-case keys)"""
    return bool(query.get("sig")) and bool(query.get("sv") or query.get("sp") or query.get("se") or query.get("si"))
