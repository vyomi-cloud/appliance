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
_F_ASTARGET = re.compile(r"^\s*asTarget\(\s*\)\s*$", re.I)


def parse_filter(flt):
    """-> (kind, principal) with kind in {None, "atScope", "principalId", "assignedTo"}; raises AzError on anything else."""
    if not flt:
        return None, None
    if _F_ATSCOPE.match(flt):
        return "atScope", None
    if _F_ASTARGET.match(flt):
        return "asTarget", None
    m = _F_PRINCIPAL.match(flt)
    if m:
        return "principalId", m.group(1)
    m = _F_ASSIGNED.match(flt)
    if m:
        return "assignedTo", m.group(1)
    raise AzError(400, "InvalidFilter", "The filter is not supported. Use atScope(), asTarget(), principalId eq '{id}' or assignedTo('{id}').")


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


def schedules(kind, scope, flt, state, principal=None):
    """Eligible schedules come from `state["eligibility"]` (ARM `roleEligibilitySchedules` records, when a store holds them) and from
    role assignments flagged assignment_type=eligible; active schedules / instances are the role assignments themselves
    (permanent, memberType Direct, status Provisioned). Filters: atScope() / principalId eq '..' / assignedTo('..')."""
    state = state or {}
    name, typ, instance = _KINDS[str(kind).lower()]
    f_kind, who = parse_filter(flt.replace("$filter=", "") if flt else flt)
    if f_kind == "asTarget":                         # the caller's own schedules (az pim / the portal's "My roles")
        f_kind, who = "principalId", str((principal or {}).get("object_id") or "")
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
        if not ok or (ra.get("pim") and not E._active(dict(ra, assignment_type="active"))):
            continue
        f = _ra_flat(ra)
        gid = f["id"].rsplit("/", 1)[-1]
        props = {"scope": f["scope"], "roleDefinitionId": f["roleDefinitionId"], "principalId": f["principalId"], "principalType": f["principalType"],
                 "status": "Provisioned", "memberType": "Direct", "createdOn": ra.get("created_on") or "2026-01-01T00:00:00.0000000Z",
                 "startDateTime": ra.get("start_date_time") or ra.get("created_on") or "2026-01-01T00:00:00.0000000Z"}
        if ra.get("end_date_time"):
            props["endDateTime"] = ra["end_date_time"]
        if typ == "eligible":
            props["roleEligibilityScheduleId"] = f"{scope if scope != '/' else ''}/providers/{NS}/roleEligibilitySchedules/{gid}"
        else:
            props["roleAssignmentScheduleId"] = f"{scope if scope != '/' else ''}/providers/{NS}/roleAssignmentSchedules/{gid}"
            props["assignmentType"] = ra.get("assignment_kind") or ("Activated" if instance else "Assigned")
            if ra.get("linked_eligibility"):
                props["linkedRoleEligibilityScheduleId"] = ra["linked_eligibility"]
        if instance:
            props["originRoleAssignmentId"] = f["id"]
        out.append({"id": f"{f['scope'] if f['scope'] != '/' else ''}/providers/{NS}/{name}/{gid}", "name": gid, "type": f"{NS}/{name}", "properties": props})
    return {"value": out}


# ------------------------------------------------------------------ custom role checks (Vyomi extension)
def _az_catalog(provider):
    """The provider's operation catalog (core/iam_catalog/azure/<Provider>.json) or None when this bundle has none (unverifiable, not wrong)."""
    from . import catalog_loader
    try:
        return catalog_loader.load("azure", provider)
    except (catalog_loader.CatalogUnavailable, ValueError):
        pass
    try:
        import json, os
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iam_catalog", "azure", provider + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _provider_names():
    import os
    try:
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iam_catalog", "azure")
        return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json") and not f.startswith("_"))
    except Exception:
        return []


def _role_perms(rd):
    p = (rd.get("properties") or rd)
    return [{k: list(x.get(k) or []) for k in ("actions", "notActions", "dataActions", "notDataActions")} for x in (p.get("permissions") or [])], \
        list(p.get("assignableScopes") or [])


def check_custom_role(body, state):
    """POST {scope}/providers/Microsoft.Authorization/customRoleChecks  (VYOMI EXTENSION: Azure has no native 'custom policy check' API, this is the
    Access-Analyzer-style validation for role definitions). Body {properties|roleName/permissions/assignableScopes, reference?: roleDefinitionId or a role
    body}. Findings (ERROR | WARNING | SECURITY_WARNING | SUGGESTION): INVALID_ACTION (provider catalog proves the operation does not exist), ACTION_IN_
    DATA_ACTIONS / DATA_ACTION_IN_ACTIONS, NOT_ACTION_NO_EFFECT, REDUNDANT_ACTION, MISSING_ASSIGNABLE_SCOPES, WILDCARD_OWNER_EQUIVALENT,
    PRIVILEGE_ESCALATION (Microsoft.Authorization/roleAssignments/write reachable), and, with `reference`, NO_NEW_ACCESS PASS/FAIL (every action the new role grants
    that the reference does not). Only claims INVALID_ACTION for providers whose catalog is in the bundle."""
    perms, scopes = _role_perms(body or {})
    findings = []

    def add(sev, code, msg, path):
        findings.append({"findingType": sev, "issueCode": code, "findingDetails": msg, "path": path})

    if not scopes:
        add("ERROR", "MISSING_ASSIGNABLE_SCOPES", "assignableScopes is empty: a custom role must be assignable at one or more scopes.", ["assignableScopes"])
    if not perms:
        add("ERROR", "MISSING_PERMISSIONS", "permissions is empty.", ["permissions"])
    known = set(_provider_names())
    for i, pm in enumerate(perms):
        for kind, other in (("actions", "dataActions"), ("dataActions", "actions")):
            for j, a in enumerate(pm[kind]):
                prov = a.split("/", 1)[0]
                cat = _az_catalog(prov) if prov in known else None
                if cat is not None and "*" not in a:
                    own, oth = cat.get(kind, {}) or {}, cat.get(other, {}) or {}
                    if not any(k.lower() == a.lower() for k in own):
                        if any(k.lower() == a.lower() for k in oth):
                            add("ERROR", "DATA_ACTION_IN_ACTIONS" if kind == "actions" else "ACTION_IN_DATA_ACTIONS",
                                f"{a} is a {'data' if kind == 'actions' else 'management'} operation: list it under {other}.", ["permissions", i, kind, j])
                        else:
                            add("ERROR", "INVALID_ACTION", f"The operation {a} does not exist in provider {prov}. Verify that the operation name is correct.", ["permissions", i, kind, j])
        for kind, ex in (("actions", "notActions"), ("dataActions", "notDataActions")):
            for j, n in enumerate(pm[ex]):
                if not any(E.action_matches(a, n) or E.action_matches(n, a) for a in pm[kind]):
                    add("WARNING", "NOT_ACTION_NO_EFFECT", f"{ex} entry {n} subtracts nothing: no entry of {kind} overlaps it.", ["permissions", i, ex, j])
            seen = []
            for j, a in enumerate(pm[kind]):
                cover = next((b for b in pm[kind] if b != a and "*" in b and E.action_matches(b, a)), None)
                if a.lower() in [x.lower() for x in seen] or cover:
                    add("SUGGESTION", "REDUNDANT_ACTION", f"{a} is {'listed more than once' if not cover else 'already covered by ' + cover}.", ["permissions", i, kind, j])
                seen.append(a)
        if any(a == "*" for a in pm["actions"]) and not pm["notActions"]:
            add("SECURITY_WARNING", "WILDCARD_OWNER_EQUIVALENT", "actions contains * with no notActions: this role grants every management operation (Owner-equivalent).", ["permissions", i, "actions"])
        elif any(E.action_matches(a, "Microsoft.Authorization/roleAssignments/write") for a in pm["actions"]) and \
                not any(E.action_matches(n, "Microsoft.Authorization/roleAssignments/write") for n in pm["notActions"]):
            add("SECURITY_WARNING", "PRIVILEGE_ESCALATION", "This role can create role assignments (Microsoft.Authorization/roleAssignments/write): holders can grant themselves any role. Add it to notActions.", ["permissions", i, "actions"])
    out = {"findings": findings}
    ref = (body or {}).get("reference")
    if ref:
        if isinstance(ref, str):
            rr = E.resolve_role(state or {}, ref)
            rperms = rr["permissions"] if rr else None
        else:
            rperms, _ = _role_perms(ref)
        if rperms is None:
            raise AzError(404, "RoleDefinitionDoesNotExist", f"The reference role definition {ref} was not found.")
        new = []
        for pm in perms:
            for kind, ex in (("actions", "notActions"), ("dataActions", "notDataActions")):
                for a in pm[kind]:
                    if E.action_matches("*", a) and a == "*" or True:
                        covered = any(any(E.action_matches(r, a) for r in rp.get(kind) or []) and not any(E.action_matches(n, a) for n in rp.get(ex) or []) for rp in rperms)
                        if not covered and not any(E.action_matches(n, a) for n in pm[ex]) and a not in new:
                            new.append(a)
        out["noNewAccess"] = {"result": "FAIL" if new else "PASS", "newAccess": new}
    out["result"] = "FAIL" if any(f["findingType"] == "ERROR" for f in findings) or out.get("noNewAccess", {}).get("result") == "FAIL" else "PASS"
    return out
