"""Azure RBAC analysis answered by `azure_eval` over the ARM state (pure Python, Pyodide-safe: no fastapi / socket).

  check_access(body, state)                      POST {scope}/providers/Microsoft.Authorization/checkAccess  (native array response)
  effective_permissions(scope, principal, state) GET  {scope}/providers/Microsoft.Authorization/permissions   -> {"value": [Permission]}
  role_assignments(scope, filter, principal, state)  GET {scope}/providers/Microsoft.Authorization/roleAssignments?$filter=atScope() |
                                                 principalId eq '..' | assignedTo('..')
  schedules(kind, scope, filter, principal, state)   roleEligibilitySchedules / roleEligibilityScheduleInstances /
                                                 roleAssignmentSchedules / roleAssignmentScheduleInstances

`state` is the engine's Azure state (iam_state_adapters.azure_state / iam_state_nano.azure_state): role_assignments (flat), role_definitions,
deny_assignments, groups, management_groups, subscriptions, eligibility (PIM schedules, optional)."""
from __future__ import annotations

import re

from . import azure_eval as E

NS = "Microsoft.Authorization"


class AzError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code


def _ci(d, *names):
    """Case-insensitive dict lookup (portal bodies are PascalCase, SDK bodies camelCase)."""
    if not isinstance(d, dict):
        return None
    low = {str(k).lower(): v for k, v in d.items()}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


def _sub_of(scope):
    m = re.match(r"^/subscriptions/([^/]+)", scope or "", re.I)
    return m.group(1) if m else ""


def _role_id(ref, scope):
    guid = str(ref or "").rsplit("/", 1)[-1]
    sub = _sub_of(scope)
    return (f"/subscriptions/{sub}" if sub else "") + f"/providers/{NS}/roleDefinitions/{guid}"


def _ra_flat(ra, role_id_hint=None):
    sc = ra.get("scope") or "/"
    d = {"id": ra.get("id", ""), "roleDefinitionId": _role_id(ra.get("role_definition_id") or role_id_hint, sc),
         "principalId": ra.get("principal_id", ""), "principalType": ra.get("principal_type") or "User", "scope": sc, "canDelegate": False}
    if ra.get("condition"):
        d["condition"], d["conditionVersion"] = ra["condition"], ra.get("condition_version") or "2.0"
    return d


def _find_ra(state, rid):
    return next((r for r in state.get("role_assignments") or [] if r.get("id") == rid), None)


def check_access(body, state, default_principal=None):
    """-> list of AccessDecision (the portal / REST response is a bare JSON array)."""
    state = state or {}
    subject = _ci(body, "Subject", "subject") or {}
    attrs = _ci(subject, "Attributes", "attributes") or {}
    oid = _ci(attrs, "ObjectId") or _ci(subject, "principalId") or _ci(body, "principalId")
    if not oid and default_principal and default_principal.get("object_id"):
        oid = default_principal["object_id"]
    scope = _ci(_ci(body, "Resource", "resource") or {}, "Id") or _ci(body, "scope") or "/"
    acts = _ci(body, "Actions", "actions")
    if acts is None and _ci(body, "action"):
        acts = [{"Id": _ci(body, "action")}]
    if not oid or not acts:
        raise AzError(400, "InvalidRequestContent", "Subject.Attributes.ObjectId, Actions and Resource.Id are required.")
    groups = sorted(E.expand_groups(state, str(oid)))      # group memberships always resolved (the portal's xms-pasrp-retrievegroupmemberships)
    out = []
    for a in acts:
        aid = a if isinstance(a, str) else _ci(a, "Id", "id")
        data = bool(_ci(a, "IsDataAction", "isDataAction")) if isinstance(a, dict) else False
        r = E.check_access(state, str(oid), str(aid), scope, data=data, groups=groups)
        ra, da = r.get("roleAssignment"), r.get("denyAssignment")
        out.append({"actionId": aid, "accessDecision": r["accessDecision"], "isDataAction": data,
                    "roleAssignment": _ra_flat(_find_ra(state, ra["id"]) or {"id": ra["id"], "scope": ra.get("scope"), "principal_id": ra.get("principalId"),
                                                                              "role_definition_id": ra.get("roleDefinitionId")}) if ra else None,
                    "denyAssignment": ({"id": da["id"], "scope": da.get("scope"), "isSystemProtected": bool(da.get("isSystemProtected"))} if da else None),
                    "timeToLiveInMs": 300000})
    return out


# ------------------------------------------------------------------ effective permissions
def _ids(principal, state):
    oid = str((principal or {}).get("object_id") or "")
    return {oid.lower()} | E.expand_groups(state, oid, (principal or {}).get("groups"))


def effective_permissions(scope, principal, state):
    state = state or {}
    scope = scope or "/"
    pr = principal or {}
    if pr.get("type") == "root" or not pr.get("object_id"):
        role = E.resolve_role(state, "Owner")           # the simulator's unidentified caller is the subscription owner
        perms = role["permissions"] if role else [{"actions": ["*"], "notActions": [], "dataActions": [], "notDataActions": []}]
        return {"value": [dict(p) for p in perms]}
    ids = _ids(pr, state)
    seen, out = set(), []
    for ra in state.get("role_assignments") or []:
        if (ra.get("principal_id") or "").lower() not in ids or not E._active(ra):
            continue
        if not E.scope_covers(ra.get("scope"), scope, state):
            continue
        role = E.resolve_role(state, ra.get("role_definition_id"))
        if not role or role["id"] in seen:
            continue
        seen.add(role["id"])
        out.extend({k: list(p.get(k) or []) for k in ("actions", "notActions", "dataActions", "notDataActions")} for p in role["permissions"])
    return {"value": out}


# ------------------------------------------------------------------ role assignments (list with $filter)
_F_PRINCIPAL = re.compile(r"^\s*principalId\s+eq\s+'([^']+)'\s*$", re.I)
_F_ASSIGNED = re.compile(r"^\s*assignedTo\(\s*'([^']+)'\s*\)\s*$", re.I)
_F_ATSCOPE = re.compile(r"^\s*atScope\(\s*\)\s*$", re.I)


def parse_filter(flt):
    """-> (kind, principal) with kind in {None, "atScope", "principalId", "assignedTo"}; raises AzError on anything else."""
    if not flt:
        return None, None
    if _F_ATSCOPE.match(flt):
        return "atScope", None
    m = _F_PRINCIPAL.match(flt)
    if m:
        return "principalId", m.group(1)
    m = _F_ASSIGNED.match(flt)
    if m:
        return "assignedTo", m.group(1)
    raise AzError(400, "InvalidFilter", "The filter is not supported. Use atScope(), principalId eq '{id}' or assignedTo('{id}').")


def _arm_ra(ra):
    f = _ra_flat(ra)
    name = f["id"].rsplit("/", 1)[-1]
    props = {"roleDefinitionId": f["roleDefinitionId"], "principalId": f["principalId"], "principalType": f["principalType"], "scope": f["scope"],
             "createdOn": ra.get("created_on") or "2026-01-01T00:00:00.0000000Z", "updatedOn": ra.get("created_on") or "2026-01-01T00:00:00.0000000Z"}
    for k in ("condition", "conditionVersion"):
        if f.get(k):
            props[k] = f[k]
    return {"id": f["id"], "name": name, "type": f"{NS}/roleAssignments", "properties": props}


def role_assignments(scope, flt, state):
    """List semantics of the ARM API: no filter = at the scope and BELOW; atScope() = at or ABOVE; principalId eq = that principal at,
    above or below; assignedTo = the principal's own plus those of its groups, at or above."""
    state = state or {}
    kind, who = parse_filter(flt)
    out = []
    ids = None
    if kind == "assignedTo":
        ids = {who.lower()} | E.expand_groups(state, who)
    for ra in state.get("role_assignments") or []:
        if not E._active(ra):
            continue
        sc = ra.get("scope") or "/"
        above = E.scope_covers(sc, scope, state)                   # sc is the scope itself or an ancestor
        below = E.scope_covers(scope, sc, state) if scope != "/" else True
        if kind == "atScope":
            ok = above
        elif kind == "principalId":
            ok = (ra.get("principal_id") or "").lower() == who.lower() and (above or below)
        elif kind == "assignedTo":
            ok = (ra.get("principal_id") or "").lower() in ids and above
        else:
            ok = above or below
        if ok:
            out.append(_arm_ra(ra))
    return {"value": out}


# ------------------------------------------------------------------ PIM schedules (as far as the store supports)
_KINDS = {"roleeligibilityschedules": ("roleEligibilitySchedules", "eligible", False),
          "roleeligibilityscheduleinstances": ("roleEligibilityScheduleInstances", "eligible", True),
          "roleassignmentschedules": ("roleAssignmentSchedules", "active", False),
          "roleassignmentscheduleinstances": ("roleAssignmentScheduleInstances", "active", True)}


def schedule_kind(seg):
    return _KINDS.get(str(seg).lower())


def schedules(kind, scope, flt, state):
    """Eligible schedules come from `state["eligibility"]` (ARM `roleEligibilitySchedules` records, when a store holds them) and from
    role assignments flagged assignment_type=eligible; active schedules / instances are the role assignments themselves
    (permanent, memberType Direct, status Provisioned). Filters: atScope() / principalId eq '..' / assignedTo('..')."""
    state = state or {}
    name, typ, instance = _KINDS[str(kind).lower()]
    f_kind, who = parse_filter(flt.replace("$filter=", "") if flt else flt)
    pool = []
    for ra in state.get("role_assignments") or []:
        is_elig = str(ra.get("assignment_type") or "active").lower() == "eligible"
        if (typ == "eligible") == is_elig:
            pool.append(ra)
    if typ == "eligible":
        pool += [r for r in state.get("eligibility") or []]
    ids = ({who.lower()} | E.expand_groups(state, who)) if f_kind == "assignedTo" else None
    out = []
    for ra in pool:
        sc = ra.get("scope") or "/"
        above, below = E.scope_covers(sc, scope, state), (E.scope_covers(scope, sc, state) if scope != "/" else True)
        if f_kind == "atScope":
            ok = above
        elif f_kind == "principalId":
            ok = (ra.get("principal_id") or "").lower() == who.lower() and (above or below)
        elif f_kind == "assignedTo":
            ok = (ra.get("principal_id") or "").lower() in ids and above
        else:
            ok = above or below
        if not ok:
            continue
        f = _ra_flat(ra)
        gid = f["id"].rsplit("/", 1)[-1]
        props = {"scope": f["scope"], "roleDefinitionId": f["roleDefinitionId"], "principalId": f["principalId"], "principalType": f["principalType"],
                 "status": "Provisioned", "memberType": "Direct", "createdOn": ra.get("created_on") or "2026-01-01T00:00:00.0000000Z",
                 "startDateTime": ra.get("created_on") or "2026-01-01T00:00:00.0000000Z"}
        if typ == "eligible":
            props["roleEligibilityScheduleId"] = f"{scope if scope != '/' else ''}/providers/{NS}/roleEligibilitySchedules/{gid}"
        else:
            props["roleAssignmentScheduleId"] = f"{scope if scope != '/' else ''}/providers/{NS}/roleAssignmentSchedules/{gid}"
            props["assignmentType"] = "Activated" if instance else "Assigned"
        if instance:
            props["originRoleAssignmentId"] = f["id"]
        out.append({"id": f"{f['scope'] if f['scope'] != '/' else ''}/providers/{NS}/{name}/{gid}", "name": gid, "type": f"{NS}/{name}", "properties": props})
    return {"value": out}
