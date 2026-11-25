"""Azure PIM-style eligible / time-bound role assignments (pure Python, Pyodide-safe), stored as ARM records of the space so they persist
and sync with the rest of ARM on Mesh and on Nano.

REAL (modelled on the Microsoft.Authorization 2020-10-01 / 2022-04-01-preview schedule APIs):
  PUT  {scope}/providers/Microsoft.Authorization/roleEligibilityScheduleRequests/{guid}   AdminAssign | AdminRemove | AdminUpdate | AdminExtend | AdminRenew
  PUT  {scope}/providers/Microsoft.Authorization/roleAssignmentScheduleRequests/{guid}    AdminAssign (time-bound) | AdminRemove | SelfActivate | SelfDeactivate | SelfExtend | SelfRenew
  GET  ...Requests[/{guid}], ...roleEligibilitySchedules[/{guid}], ...roleEligibilityScheduleInstances, ...roleAssignmentSchedules, ...roleAssignmentScheduleInstances
  an ACTIVATION creates an active schedule (assignmentType Activated) that grants the role for its window; the engine (azure_eval._active) honours
  startDateTime / endDateTime, so access appears at activation and disappears at expiry with no sweeper. Eligible schedules grant NOTHING by themselves.
  SelfActivate requires: the caller is the principal, an eligibility covering the scope + role that is inside its window, and a duration within the role
  setting's maximum (8 hours, the PIM default) and within the eligibility's remaining time.

APPROXIMATED: no approval workflow, MFA / justification / ticket enforcement, notification, access reviews or per-role policy rules (the max
activation duration is fixed at 8 h unless the request body carries `maxActivationHours` in the role-setting store key `pimSettings`); error
codes other than RoleAssignmentRequestPolicyValidationFailed are best-effort names."""
from __future__ import annotations

import calendar
import re
import time
import uuid

NS = "Microsoft.Authorization"
MAX_ACTIVATION_SECONDS = 8 * 3600
ELIG_REQ, ACT_REQ = "roleEligibilityScheduleRequests", "roleAssignmentScheduleRequests"
ELIG, ELIG_INST = "roleEligibilitySchedules", "roleEligibilityScheduleInstances"
ACT, ACT_INST = "roleAssignmentSchedules", "roleAssignmentScheduleInstances"
TYPES = {k.lower(): f"{NS}/{k}" for k in (ELIG_REQ, ACT_REQ, ELIG, ACT)}
_KIND = {k.lower(): k for k in (ELIG_REQ, ACT_REQ, ELIG, ELIG_INST, ACT, ACT_INST)}


class PimError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ------------------------------------------------------------------ time
def now_ts():
    return time.time()


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + ".0000000Z"


def parse_ts(s):
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)", str(s or ""))
    if not m:
        return None
    return float(calendar.timegm(tuple(int(x) for x in m.groups()) + (0, 0, 0)))


def parse_duration(s):
    """ISO-8601 duration (P1DT2H30M) -> seconds, None when it is not one."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", str(s or ""))
    if not m or not any(m.groups()):
        return None
    d, h, mi, sec = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + sec


def _ci(d, *names):
    if not isinstance(d, dict):
        return None
    low = {str(k).lower(): v for k, v in d.items()}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


def kind_of(seg):
    return _KIND.get(str(seg).lower())


# ------------------------------------------------------------------ records
def _rec_id(scope, kind, name):
    return f"{'' if scope in ('', '/') else scope.rstrip('/')}/providers/{NS}/{kind}/{name}"


def _put(arm, scope, kind, name, props):
    rid = _rec_id(scope, kind, name)
    rec = {"id": rid, "name": name, "type": f"{NS}/{kind}", "_type": f"{NS}/{kind}", "_scope": scope, "properties": props}
    arm[rid.lower()] = rec
    return rec


def _all(arm, kind):
    t = f"{NS}/{kind}".lower()
    return [r for r in list(arm.values()) if isinstance(r, dict) and str(r.get("_type") or r.get("type") or "").lower() == t]


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _role_guid(ref):
    return str(ref or "").rsplit("/", 1)[-1].lower()


def _scope_covers(parent, child):
    p, c = (parent or "/").rstrip("/").lower(), (child or "/").rstrip("/").lower()
    return p in ("", "/") or c == p or c.startswith(p + "/")


def _window(info, now):
    """scheduleInfo -> (start, end|None); validates the expiration block."""
    info = info or {}
    start = parse_ts(_ci(info, "startDateTime")) if _ci(info, "startDateTime") else now
    if start is None:
        raise PimError(400, "InvalidRequestContent", "scheduleInfo.startDateTime is not a valid date-time.")
    exp = _ci(info, "expiration") or {}
    typ = str(_ci(exp, "type") or "NoExpiration")
    if typ == "NoExpiration":
        return start, None
    if typ == "AfterDateTime":
        end = parse_ts(_ci(exp, "endDateTime"))
        if end is None:
            raise PimError(400, "InvalidRequestContent", "scheduleInfo.expiration.endDateTime is required for AfterDateTime.")
    elif typ == "AfterDuration":
        dur = parse_duration(_ci(exp, "duration"))
        if dur is None:
            raise PimError(400, "InvalidRequestContent", "scheduleInfo.expiration.duration must be an ISO-8601 duration (for example PT8H).")
        end = start + dur
    else:
        raise PimError(400, "InvalidRequestContent", f"scheduleInfo.expiration.type '{typ}' is not one of AfterDateTime, AfterDuration, NoExpiration.")
    if end <= start:
        raise PimError(400, "InvalidRequestContent", "The schedule end must be after its start.")
    return start, end


def _live(rec, now):
    p = rec.get("properties") or {}
    s, e = parse_ts(p.get("startDateTime")), parse_ts(p.get("endDateTime"))
    return (s is None or s <= now) and (e is None or e > now) and p.get("status", "Provisioned") == "Provisioned"


# ------------------------------------------------------------------ requests
def put_request(arm, scope, kind, name, body, caller, max_activation=MAX_ACTIVATION_SECONDS, now=None):
    """-> (status, doc). `kind` is roleEligibilityScheduleRequests | roleAssignmentScheduleRequests; `caller` the engine principal
    ({"object_id","type"}); root (the unidentified simulator owner) may administer."""
    now = now or now_ts()
    props = _ci(body, "properties") or body or {}
    rtype = str(_ci(props, "requestType") or "")
    pid, rdef = _ci(props, "principalId"), _ci(props, "roleDefinitionId")
    is_elig = kind == ELIG_REQ
    admin = {"AdminAssign", "AdminRemove", "AdminUpdate", "AdminExtend", "AdminRenew"}
    allowed = admin | ({"SelfExtend", "SelfRenew"} if is_elig else {"SelfActivate", "SelfDeactivate", "SelfExtend", "SelfRenew"})
    if rtype not in allowed:
        raise PimError(400, "InvalidRequestContent", f"requestType '{rtype}' is not valid for {kind}; expected one of {sorted(allowed)}.")
    if not pid or not rdef:
        raise PimError(400, "InvalidRequestContent", "properties.principalId and properties.roleDefinitionId are required.")
    if not re.fullmatch(r"[0-9a-fA-F-]{8,}", str(name or "")):
        raise PimError(400, "InvalidRequestContent", "The request name must be a GUID.")
    cid = str((caller or {}).get("object_id") or "root")
    is_root = (caller or {}).get("type") == "root" or cid == "root"
    if rtype.startswith("Self") and not is_root and cid.lower() != str(pid).lower():
        raise PimError(403, "AuthorizationFailed", "The caller can only perform self-service requests for their own principalId.")
    rid = _rec_id(scope, kind, name)
    if rid.lower() in arm:
        raise PimError(409, "RoleAssignmentRequestExists", f"A request with name '{name}' already exists.")
    role_id = rdef if "/providers/" in str(rdef) else f"/providers/{NS}/roleDefinitions/{rdef}"
    base = {"scope": scope or "/", "roleDefinitionId": role_id, "principalId": pid, "principalType": _ci(props, "principalType") or "User",
            "requestType": rtype, "status": "Provisioned", "createdOn": iso(now), "requestorId": cid if not is_root else "root",
            "justification": _ci(props, "justification") or "", "ticketInfo": _ci(props, "ticketInfo") or {}, "scheduleInfo": _ci(props, "scheduleInfo") or {}}
    sched_kind = ELIG if is_elig else ACT
    if rtype in ("AdminAssign", "AdminUpdate", "AdminExtend", "AdminRenew", "SelfExtend", "SelfRenew") or (rtype == "SelfActivate"):
        start, end = _window(base["scheduleInfo"], now)
        if rtype == "SelfActivate":
            elig = _find_eligibility(arm, scope, pid, rdef, now)
            if elig is None:
                raise PimError(400, "RoleAssignmentRequestNoEligibility",
                               "The role assignment request is invalid: no active eligible assignment exists for this principal, role and scope.")
            ep = elig["properties"]
            if end is None:
                end = start + min(max_activation, (parse_ts(ep.get("endDateTime")) or 1e18) - start)
            if end - start > max_activation or (parse_ts(ep.get("endDateTime")) is not None and end > parse_ts(ep["endDateTime"])):
                raise PimError(400, "RoleAssignmentRequestPolicyValidationFailed", 'The following policy rules failed: ["ExpirationRule"]')
        sp = {"scope": scope or "/", "roleDefinitionId": role_id, "principalId": pid, "principalType": base["principalType"], "status": "Provisioned",
              "memberType": "Direct", "createdOn": iso(now), "startDateTime": iso(start), "endDateTime": iso(end) if end else None,
              f"{'roleEligibility' if is_elig else 'roleAssignment'}ScheduleRequestId": rid}
        if is_elig:
            sp["roleEligibilityScheduleId"] = _rec_id(scope, ELIG, name)
        else:
            sp["assignmentType"] = "Activated" if rtype == "SelfActivate" else "Assigned"
            sp["roleAssignmentScheduleId"] = _rec_id(scope, ACT, name)
            if rtype == "SelfActivate":
                sp["linkedRoleEligibilityScheduleId"] = elig["id"]
        _put(arm, scope, sched_kind, name, sp)
        base[("targetRoleEligibilityScheduleId" if is_elig else "targetRoleAssignmentScheduleId")] = _rec_id(scope, sched_kind, name)
    elif rtype in ("AdminRemove", "SelfDeactivate"):
        hit = [r for r in _all(arm, sched_kind) if _matches(r, scope, pid, rdef)]
        if not hit:
            raise PimError(404, "RoleAssignmentRequestNotFound" if not is_elig else "RoleEligibilityScheduleNotFound",
                           "No schedule matching the principal, role and scope exists to remove.")
        for r in hit:
            r["properties"]["status"] = "Revoked"
            r["properties"]["endDateTime"] = iso(now)
    rec = _put(arm, scope, kind, name, base)
    return 201, _view(rec)


def _matches(rec, scope, pid, rdef):
    p = rec.get("properties") or {}
    return (str(p.get("principalId")).lower() == str(pid).lower() and _role_guid(p.get("roleDefinitionId")) == _role_guid(rdef)
            and (p.get("scope") or "/").rstrip("/").lower() == (scope or "/").rstrip("/").lower() and p.get("status") == "Provisioned")


def _find_eligibility(arm, scope, pid, rdef, now):
    best = None
    for r in _all(arm, ELIG):
        p = r["properties"]
        if str(p.get("principalId")).lower() == str(pid).lower() and _role_guid(p.get("roleDefinitionId")) == _role_guid(rdef) \
                and _scope_covers(p.get("scope"), scope) and _live(r, now):
            best = r
    return best


# ------------------------------------------------------------------ reads
def get_record(arm, scope, kind, name):
    rec = arm.get(_rec_id(scope, kind, name).lower())
    if rec is None:
        raise PimError(404, "RoleAssignmentRequestNotFound" if kind.endswith("Requests") else "ResourceNotFound",
                       f"The {kind} '{name}' was not found at scope '{scope or '/'}'.")
    return _view(rec)


def list_records(arm, scope, kind, who=None, as_target=None, now=None):
    """Schedules / instances / requests at `scope` and below (above for atScope handled by the caller). `who` filters on principalId."""
    now = now or now_ts()
    base = ELIG if kind in (ELIG, ELIG_INST) else ACT if kind in (ACT, ACT_INST) else kind
    out = []
    for r in _all(arm, base):
        p = r["properties"]
        sc = p.get("scope") or "/"
        if not (_scope_covers(scope, sc) or _scope_covers(sc, scope)):
            continue
        if who and str(p.get("principalId")).lower() != str(who).lower():
            continue
        if kind in (ELIG, ELIG_INST, ACT, ACT_INST) and not _live(r, now):
            continue
        v = _view(r)
        if kind in (ELIG_INST, ACT_INST):
            v = dict(v, id=v["id"].replace(f"/{base}/", f"/{kind}/"), type=f"{NS}/{kind}",
                     properties=dict(v["properties"], originRoleAssignmentId=r["id"],
                                     **({"roleEligibilityScheduleId": r["id"]} if kind == ELIG_INST else {"roleAssignmentScheduleId": r["id"]})))
        out.append(v)
    return out


# ------------------------------------------------------------------ engine state
def fold_into_state(state, rec, now=None):
    """One ARM record -> the engine state. Eligible schedules go to state["eligibility"] (they grant nothing); a live active schedule becomes a
    role assignment with start/end so the evaluator enforces the window."""
    t = str(rec.get("_type") or rec.get("type") or "").lower()
    if t not in (f"{NS}/{ELIG}".lower(), f"{NS}/{ACT}".lower()):
        return False
    p = rec.get("properties") or {}
    if p.get("status", "Provisioned") != "Provisioned":
        return True
    flat = {"id": rec.get("id", ""), "principal_id": p.get("principalId", ""), "principal_type": p.get("principalType"),
            "scope": p.get("scope") or "/", "role_definition_id": p.get("roleDefinitionId", ""), "created_on": p.get("createdOn"),
            "start_date_time": p.get("startDateTime"), "end_date_time": p.get("endDateTime"), "pim": True}
    if t.endswith(ELIG.lower()):
        state.setdefault("eligibility", []).append(dict(flat, assignment_type="eligible"))
    else:
        state.setdefault("role_assignments", []).append(dict(flat, assignment_type="active", assignment_kind=p.get("assignmentType") or "Assigned",
                                                              linked_eligibility=p.get("linkedRoleEligibilityScheduleId")))
    return True
