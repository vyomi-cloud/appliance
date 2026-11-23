"""Host adapters: build the faithful-IAM engine `state` dict and resolve the calling principal from the Mesh stores / request.

The engine (core/iam_engine) never imports a store (contract); everything store-shaped lives here. Functions take the stores
explicitly so they are unit-testable; the `*_from_host()` helpers bind them to the live appliance stores."""
from __future__ import annotations

import base64
import json
import re
from urllib.parse import parse_qs, unquote

# ----------------------------------------------------------------------------- request -> plain dict


def http_request_from(request, body: bytes = b"", principal=None) -> dict:
    """Starlette Request -> the plain http_request dict the gate and the op-maps consume."""
    return {"method": request.method, "path": request.scope.get("path", ""),
            "query": request.scope.get("query_string", b"").decode("latin-1"),
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "host": request.headers.get("host", ""), "body": body, "principal": principal}


def _h(headers, name):
    for k, v in (headers or {}).items():
        if str(k).lower() == name:
            return v
    return ""


def _jwt_claims(headers) -> dict:
    auth = _h(headers, "authorization")
    if not auth.lower().startswith("bearer "):
        return {}
    parts = auth.split(None, 1)[1].strip().split(".")
    if len(parts) != 3:
        return {}
    try:
        pad = "=" * (-len(parts[1]) % 4)
        c = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


# ----------------------------------------------------------------------------- AWS
_CRED_RE = re.compile(r"Credential=([^/,\s]+)/")


def aws_access_key_id(headers, query="") -> str:
    auth = _h(headers, "authorization")
    m = _CRED_RE.search(auth)
    if m:
        return m.group(1)
    if auth.startswith("AWS ") and ":" in auth:            # SigV2
        return auth[4:].split(":", 1)[0].strip()
    q = parse_qs(query or "")
    for key in ("X-Amz-Credential", "AWSAccessKeyId"):
        if q.get(key):
            return unquote(q[key][0]).split("/", 1)[0]
    return ""


def aws_principal(headers, query, store) -> dict:
    """Access key id -> IAM user, or an assumed-role session (store.extras["sts_sessions"][akid], if the host records them)."""
    acct = getattr(store, "account_id", "") or "000000000000"
    override = _h(headers, "x-cloudlearn-principal")
    if override.startswith("arn:"):
        return {"arn": override, "type": "user" if ":user/" in override else "role", "account": acct}
    akid = aws_access_key_id(headers, query)
    key = (getattr(store, "access_keys", {}) or {}).get(akid)
    if key:
        u = (store.users or {}).get(key.get("user_name"))
        if u:
            # policies / boundary / groups come from aws_state()["principals"][arn] (documents, not ARNs): do not shadow them here
            return {"arn": u["arn"], "type": "user", "account": acct, "tags": u.get("tags") or {}, "access_key_id": akid}
    sess = ((getattr(store, "extras", {}) or {}).get("sts_sessions") or {}).get(akid)
    if sess:
        role = (store.roles or {}).get(sess.get("role_name") or "") or {}
        arn = f"arn:aws:sts::{acct}:assumed-role/{sess.get('role_name')}/{sess.get('session_name', 'session')}"
        return {"arn": arn, "type": "role", "account": acct, "role_arn": role.get("arn"),
                "session_policy": sess.get("session_policy"), "access_key_id": akid}
    return {"arn": "", "type": "unknown", "account": acct, "access_key_id": akid}


def _policy_doc(store, arn):
    """Default-version document of a managed policy (AWS-managed ones are materialised on first use by iam_core)."""
    p = (store.policies or {}).get(arn)
    if p is None:
        try:
            from core import iam_core
            p = iam_core._aws_managed_policy(store, arn)
        except Exception:
            p = None
    if not p:
        return None
    v = (p.get("versions") or {}).get(p.get("default_version_id") or "v1") or {}
    return v.get("document") or p.get("document")


def _entity_policies(store, ent):
    """Identity policies of a user/group/role record: inline documents + attached managed policy documents."""
    out = [{"id": f"inline:{n}", "document": d} for n, d in sorted((ent.get("inline_policies") or {}).items())]
    for arn in ent.get("attached_policies") or []:
        d = _policy_doc(store, arn)
        if d:
            out.append({"id": arn, "document": d})
    return out


def aws_state(store) -> dict:
    """Engine `state` (core/iam_engine/aws_eval.py): principals{arn: {policies, boundary, groups, tags}}, groups{name: {policies}},
    scps/rcps (org policies, one level per org unit - flat here), resource_policies (fed by the host per service; empty = identity-only)."""
    principals, groups = {}, {}
    for name, g in (store.groups or {}).items():
        groups[name] = {"policies": _entity_policies(store, g)}
    for name, u in (store.users or {}).items():
        b = _policy_doc(store, u.get("permissions_boundary")) if u.get("permissions_boundary") else None
        principals[u["arn"]] = {"policies": _entity_policies(store, u), "boundary": [b] if b else [],
                                "groups": [g for g in (u.get("groups") or []) if g in groups], "tags": u.get("tags") or {}}
    for name, r in (store.roles or {}).items():
        b = _policy_doc(store, r.get("permissions_boundary")) if r.get("permissions_boundary") else None
        rec = {"policies": _entity_policies(store, r), "boundary": [b] if b else [], "tags": r.get("tags") or {}}
        principals[r["arn"]] = rec
        principals[r["arn"].replace(":role/", ":assumed-role/", 1) if ":role/" in r["arn"] else r["arn"]] = rec
    scps = []   # an SCP restricts only once attached to a target; the store does not model attachment yet, so none are applied (open issue)
    for o in (getattr(store, "org_policies", {}) or {}).values():
        if isinstance(o, dict) and o.get("type") == "SERVICE_CONTROL_POLICY" and o.get("targets"):
            try:
                scps.append([json.loads(o.get("content") or "{}")])
            except Exception:
                pass
    return {"cloud": "aws", "account": getattr(store, "account_id", ""), "principals": principals, "groups": groups,
            "scps": scps, "rcps": [], "resource_policies": {}, "resource_tags": {}}


# ----------------------------------------------------------------------------- GCP

def gcp_member(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw or raw == "root":
        return {"member": "root", "type": "root"}
    if ":" in raw:
        return {"member": raw, "type": raw.split(":", 1)[0]}
    if raw.endswith("gserviceaccount.com"):
        return {"member": "serviceAccount:" + raw, "type": "serviceAccount"}
    return {"member": "user:" + raw, "type": "user"}


def gcp_principal(headers, space) -> dict:
    raw = _h(headers, "x-cloudlearn-principal")
    if not raw:
        c = _jwt_claims(headers)
        raw = c.get("email") or ""
    return gcp_member(raw or str((space or {}).get("active_principal") or "root"))


def gcp_state(iam_state) -> dict:
    st = iam_state if isinstance(iam_state, dict) else {}
    policies = st.get("policies") if isinstance(st.get("policies"), dict) else {}
    bindings = list(st.get("bindings") or [])
    for p in policies.values():
        if isinstance(p, dict) and isinstance(p.get("bindings"), list):
            bindings.extend(p["bindings"])
    return {"cloud": "gcp", "policies": policies, "bindings": bindings, "service_accounts": st.get("service_accounts") or {}}


# ----------------------------------------------------------------------------- Azure
_AZ = {"microsoft.authorization/roleassignments": "role_assignments",
       "microsoft.authorization/roledefinitions": "role_definitions",
       "microsoft.authorization/denyassignments": "deny_assignments"}


def azure_principal(headers, space) -> dict:
    raw = _h(headers, "x-cloudlearn-principal")
    if not raw:
        c = _jwt_claims(headers)
        raw = c.get("oid") or c.get("appid") or c.get("sub") or ""
    raw = raw or str((space or {}).get("active_principal") or "root")
    return {"object_id": raw, "type": "root" if raw == "root" else "user", "groups": []}


def azure_state(arm_resources) -> dict:
    out = {"cloud": "azure", "role_assignments": [], "role_definitions": [], "deny_assignments": []}
    for rec in (arm_resources or {}).values():
        if isinstance(rec, dict):
            t = str(rec.get("_type") or rec.get("type") or "").lower()
            if t in _AZ:
                out[_AZ[t]].append(rec)
    return out


# ----------------------------------------------------------------------------- live host binding

def state_and_principal(cloud, headers, query="", space=None):
    """(state, principal) from the live appliance stores."""
    if cloud == "aws":
        from core.appliance_stores import iam_store
        s = iam_store()
        return aws_state(s), aws_principal(headers, query, s)
    if cloud == "gcp":
        from core.app_context import gcp_iam_state
        return gcp_state(gcp_iam_state), gcp_principal(headers, space)
    from core.app_context import azure_state_dict
    return azure_state(azure_state_dict()), azure_principal(headers, space)
