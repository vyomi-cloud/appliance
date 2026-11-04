"""GCP VM Manager control plane — OS Config API (osconfig.googleapis.com v1) + Compute VM extension policies.

Substrate-independent (stdlib only; Pyodide-loadable). State lives on the Compute (VM) store's `ext` dict:
  ext["osc_patch_jobs"]          "projects/p/patchJobs/id"                 -> PatchJob (+ private _targets)
  ext["osc_patch_deployments"]   "projects/p/patchDeployments/id"          -> PatchDeployment
  ext["osc_policy_assignments"]  "projects/p/locations/z/osPolicyAssignments/id" -> assignment (+ revisions)
  ext["osc_vm_ext_policies"]     "projects/p/global/vmExtensionPolicies/n"  -> VM extension policy

Wire (what google-cloud-os-config / gcloud compute os-config / the console speak):
  POST   /v1/projects/{p}/patchJobs:execute  |  GET patchJobs[/{id}]  |  POST patchJobs/{id}:cancel
  GET    /v1/projects/{p}/patchJobs/{id}/instanceDetails
  POST   /v1/projects/{p}/patchDeployments?patchDeploymentId=  |  GET/PATCH/DELETE  |  :pause / :resume
  POST   /v1/projects/{p}/locations/{zone}/osPolicyAssignments?osPolicyAssignmentId=  (long-running op, done)
  GET/PATCH/DELETE osPolicyAssignments/{id}  |  GET .../{id}:listRevisions
  *      /compute/{v1,beta}/projects/{p}/global/vmExtensionPolicies   (Compute operations)

Honesty: targeting, validation, schedules, rollout and state machines are real and driven by the real
Compute instances. No guest agent runs inside a Vyomi VM, so no package is actually installed or
updated: a running VM with `enable-osconfig=TRUE` reports SUCCEEDED (nothing changed), a running VM
without it is NO_AGENT_DETECTED, a stopped VM is INACTIVE.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except Exception:                       # pragma: no cover
    ZoneInfo = None

ID_RE = re.compile(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$")
ZONE_RE = re.compile(r"^[a-z]+-[a-z]+[0-9]+-[a-z]$")
DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
ORDINALS = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "LAST": -1}
REBOOT = ("DEFAULT", "ALWAYS", "NEVER")
APT_TYPES = ("DIST", "UPGRADE")
YUM_UPDATE_KEYS = ("security", "minimal", "excludes", "exclusivePackages")
WIN_CLASSES = ("CRITICAL", "SECURITY", "DEFINITION", "DRIVER", "FEATURE_PACK", "SERVICE_PACK", "TOOL", "UPDATE_ROLLUP", "UPDATE")
PATCH_FINALIZE_SECONDS = 2.0            # a patch job is STARTED/PATCHING this long, then settles lazily
POLICY_MODES = ("VALIDATION", "ENFORCEMENT")
PKG_STATES = ("INSTALLED", "REMOVED")
PKG_SOURCES = ("apt", "deb", "yum", "zypper", "rpm", "googet", "msi")
FILE_STATES = ("PRESENT", "ABSENT", "CONTENTS_MATCH")
INTERPRETERS = ("SHELL", "POWERSHELL", "INTERPRETER_UNSPECIFIED")
EXT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
ROLLOUT_PLANS = ("FAST_ROLLOUT", "SLOW_ROLLOUT")
KNOWN_EXTENSIONS = ("ops-agent", "google-cloud-ops-agent", "google-cloud-ops-agent-v2", "sap-agent", "workloadmanager-agent")


class Resp:
    media_type = "application/json"

    def __init__(self, status, obj):
        self.status, self.headers = status, {}
        self.body = json.dumps(obj).encode()


class _E(Exception):
    def __init__(self, status, gcp_status, message):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _bad(msg):
    return _E(400, "INVALID_ARGUMENT", msg)


def _nf(full):
    return _E(404, "NOT_FOUND", "Requested entity was not found." if "/" in full else "Not found.")


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_ts(v, field):
    try:
        s = re.sub(r"(\.\d{6})\d+", r"\1", str(v).replace("Z", "+00:00"))
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        raise _bad("Invalid value for %s: %r is not an RFC 3339 timestamp." % (field, v))


def _x(store, coll):
    if getattr(store, "ext", None) is None:
        store.ext = {}
    return store.ext.setdefault(coll, {})


def _pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _dur(v, field, lo=1, hi=None):
    if v is None:
        return None
    m = re.match(r"^(\d+)(\.\d+)?s$", str(v))
    if not m:
        raise _bad("Invalid value for %s: %r (expected a duration such as \"3600s\")." % (field, v))
    n = int(m.group(1))
    if n < lo or (hi and n > hi):
        raise _bad("%s must be between %ds and %ds." % (field, lo, hi or n))
    return n


def _page(items, query, key):
    try:
        size = int(query.get("pageSize") or 500)
    except Exception:
        raise _bad("Invalid pageSize.")
    if size < 0:
        raise _bad("pageSize must not be negative.")
    size = min(size or 500, 1000)
    start = 0
    tok = query.get("pageToken")
    if tok:
        try:
            start = int(tok)
        except Exception:
            raise _bad("Invalid pageToken.")
    out = {key: items[start:start + size]}
    if start + size < len(items):
        out["nextPageToken"] = str(start + size)
    return out


# ── instance targeting (real Compute instances) ───────────────────────────────
def _instances(store, project):
    pre = "projects/%s/zones/" % project
    return [(k, v) for k, v in sorted((getattr(store, "instances", None) or {}).items()) if k.startswith(pre)]


def _zone_of(key):
    return key.split("/")[3]


def _meta(inst, key):
    for i in ((inst.get("metadata") or {}).get("items") or []):
        if i.get("key") == key:
            return str(i.get("value") or "")
    return None


def _agent_enabled(inst):
    return (_meta(inst, "enable-osconfig") or "").strip().upper() == "TRUE"


def _validate_filter(f, field):
    if f is None:
        raise _bad("%s is required." % field)
    if not isinstance(f, dict):
        raise _bad("%s must be an object." % field)
    known = ("all", "groupLabels", "zones", "instances", "instanceNamePrefixes")
    for k in f:
        if k not in known:
            raise _bad("Unknown field %r in %s." % (k, field))
    if not (f.get("all") or f.get("groupLabels") or f.get("zones") or f.get("instances") or f.get("instanceNamePrefixes")):
        raise _bad("%s must select at least one of all, groupLabels, zones, instances or instanceNamePrefixes." % field)
    for g in f.get("groupLabels") or []:
        if not isinstance(g, dict) or not g.get("labels"):
            raise _bad("Each %s.groupLabels entry needs non-empty labels." % field)
    for z in f.get("zones") or []:
        if not ZONE_RE.match(str(z)):
            raise _bad("Invalid zone %r in %s.zones." % (z, field))
    for i in f.get("instances") or []:
        if not re.match(r"^zones/[^/]+/instances/[^/]+$", str(i)):
            raise _bad("Invalid instance %r in %s.instances (expected zones/ZONE/instances/NAME)." % (i, field))


def match_patch_filter(store, project, f):
    out = []
    for key, inst in _instances(store, project):
        name, zone = key.split("/")[-1], _zone_of(key)
        labels = inst.get("labels") or {}
        ok = bool(f.get("all"))
        ok = ok or zone in (f.get("zones") or [])
        ok = ok or ("zones/%s/instances/%s" % (zone, name)) in (f.get("instances") or [])
        ok = ok or any(name.startswith(p) for p in (f.get("instanceNamePrefixes") or []))
        ok = ok or any(all(labels.get(k) == v for k, v in (g.get("labels") or {}).items()) for g in (f.get("groupLabels") or []))
        if ok:
            out.append((key, inst))
    return out


# ── patch config ──────────────────────────────────────────────────────────────
def _validate_patch_config(pc):
    if pc is None:
        return
    if not isinstance(pc, dict):
        raise _bad("patchConfig must be an object.")
    for k in pc:
        if k not in ("rebootConfig", "apt", "yum", "goo", "zypper", "windowsUpdate", "preStep", "postStep", "migInstancesAllowed"):
            raise _bad("Unknown field %r in patchConfig." % k)
    if pc.get("rebootConfig") not in (None,) + REBOOT:
        raise _bad("Invalid patchConfig.rebootConfig %r (one of %s)." % (pc.get("rebootConfig"), ", ".join(REBOOT)))
    apt = pc.get("apt")
    if apt:
        if apt.get("type") not in (None, "TYPE_UNSPECIFIED") + APT_TYPES:
            raise _bad("Invalid patchConfig.apt.type %r (DIST or UPGRADE)." % apt.get("type"))
        if apt.get("exclusivePackages") and apt.get("excludes"):
            raise _bad("patchConfig.apt.exclusivePackages cannot be combined with excludes.")
    yum = pc.get("yum")
    if yum and yum.get("exclusivePackages") and (yum.get("excludes") or yum.get("security") or yum.get("minimal")):
        raise _bad("patchConfig.yum.exclusivePackages cannot be combined with security, minimal or excludes.")
    win = pc.get("windowsUpdate")
    if win:
        if win.get("exclusivePatches") and (win.get("classifications") or win.get("excludes")):
            raise _bad("patchConfig.windowsUpdate.exclusivePatches cannot be combined with classifications or excludes.")
        for c in win.get("classifications") or []:
            if c not in WIN_CLASSES:
                raise _bad("Invalid patchConfig.windowsUpdate.classifications value %r." % c)
    for step in ("preStep", "postStep"):
        s = pc.get(step)
        if s:
            for plat in ("linuxExecStepConfig", "windowsExecStepConfig"):
                c = s.get(plat)
                if c and not (c.get("localPath") or c.get("gcsObject")):
                    raise _bad("patchConfig.%s.%s needs localPath or gcsObject." % (step, plat))


def _validate_rollout(r):
    if r is None:
        return
    if r.get("mode") not in (None, "ZONE_BY_ZONE", "CONCURRENT_ZONES", "MODE_UNSPECIFIED"):
        raise _bad("Invalid rollout.mode %r." % r.get("mode"))
    db = r.get("disruptionBudget") or {}
    if "fixed" in db and "percentage" in db:
        raise _bad("rollout.disruptionBudget accepts only one of fixed or percentage.")
    if "percentage" in db and not (0 <= int(db["percentage"]) <= 100):
        raise _bad("rollout.disruptionBudget.percentage must be between 0 and 100.")
    if "fixed" in db and int(db["fixed"]) < 0:
        raise _bad("rollout.disruptionBudget.fixed must not be negative.")


# ── patch jobs ────────────────────────────────────────────────────────────────
def _summary(details):
    s = {k: 0 for k in ("pendingInstanceCount", "inactiveInstanceCount", "notifiedInstanceCount", "startedInstanceCount",
                        "downloadingPatchesInstanceCount", "applyingPatchesInstanceCount", "rebootingInstanceCount",
                        "succeededInstanceCount", "succeededRebootRequiredInstanceCount", "failedInstanceCount",
                        "ackedInstanceCount", "timedOutInstanceCount", "prePatchStepInstanceCount",
                        "postPatchStepInstanceCount", "noAgentDetectedInstanceCount")}
    m = {"PENDING": "pendingInstanceCount", "INACTIVE": "inactiveInstanceCount", "NOTIFIED": "notifiedInstanceCount",
         "STARTED": "startedInstanceCount", "SUCCEEDED": "succeededInstanceCount", "FAILED": "failedInstanceCount",
         "TIMED_OUT": "timedOutInstanceCount", "NO_AGENT_DETECTED": "noAgentDetectedInstanceCount",
         "SUCCEEDED_REBOOT_REQUIRED": "succeededRebootRequiredInstanceCount"}
    for d in details:
        s[m.get(d["state"], "pendingInstanceCount")] += 1
    return s


def _settle(store, rec, now=None):
    """Lazy state machine: STARTED -> PATCHING -> final, driven by wall clock + the live instance set."""
    if rec["state"] in ("SUCCEEDED", "COMPLETED_WITH_ERRORS", "CANCELED", "TIMED_OUT", "NO_INSTANCES_FOUND"):
        return
    now = now or _now()
    age = (now - _parse_ts(rec["createTime"], "createTime")).total_seconds()
    details = rec["_details"]
    if age < PATCH_FINALIZE_SECONDS / 2:
        return
    if age < PATCH_FINALIZE_SECONDS:
        rec["state"] = "PATCHING"
        for d in details:
            if d["state"] == "PENDING":
                d["state"] = "STARTED"
        rec["instanceDetailsSummary"] = _summary(details)
        rec["percentComplete"] = 50.0
        return
    inst = getattr(store, "instances", None) or {}
    for d in details:
        i = inst.get(d["_key"])
        if i is None or i.get("status") in ("TERMINATED", "STOPPED", "SUSPENDED", "STOPPING"):
            d["state"], d["failureReason"] = "INACTIVE", "Instance was not running."
        elif not _agent_enabled(i):
            d["state"], d["failureReason"] = "NO_AGENT_DETECTED", "The OS Config agent was not detected; set metadata enable-osconfig=TRUE and install the agent."
        elif rec["dryRun"]:
            d["state"] = "SUCCEEDED"
        else:
            reboot = (rec.get("patchConfig") or {}).get("rebootConfig")
            d["state"] = "SUCCEEDED"
            if reboot == "NEVER":
                d["state"] = "SUCCEEDED"
        d.setdefault("attemptCount", 1)
    rec["instanceDetailsSummary"] = _summary(details)
    rec["percentComplete"] = 100.0
    if not details:
        rec["state"] = "NO_INSTANCES_FOUND"
    elif any(d["state"] in ("FAILED", "TIMED_OUT", "NO_AGENT_DETECTED") for d in details):
        rec["state"] = "COMPLETED_WITH_ERRORS"
    else:
        rec["state"] = "SUCCEEDED"
    rec["updateTime"] = _iso(now)


def _new_job(store, project, body, deployment=None):
    f = body.get("instanceFilter")
    _validate_filter(f, "instanceFilter")
    _validate_patch_config(body.get("patchConfig"))
    _validate_rollout(body.get("rollout"))
    dur = _dur(body.get("duration"), "duration", 1800, 86400 * 7)
    if len(str(body.get("description", ""))) > 1024:
        raise _bad("description must be at most 1024 characters.")
    if body.get("displayName") and len(body["displayName"]) > 63:
        raise _bad("displayName must be at most 63 characters.")
    matched = match_patch_filter(store, project, f)
    jid = str(uuid.uuid4())
    now = _now()
    details = [{"name": k, "_key": k, "instanceSystemId": hashlib.sha1(k.encode()).hexdigest()[:20], "state": "PENDING", "attemptCount": 0}
               for k, _ in matched]
    rec = {"name": "projects/%s/patchJobs/%s" % (project, jid), "displayName": body.get("displayName", ""),
           "description": body.get("description", ""), "createTime": _iso(now), "updateTime": _iso(now), "state": "STARTED",
           "instanceFilter": f, "patchConfig": body.get("patchConfig") or {}, "duration": ("%ds" % dur) if dur else "3600s",
           "instanceDetailsSummary": _summary(details), "dryRun": bool(body.get("dryRun")), "percentComplete": 0.0,
           "rollout": body.get("rollout") or {}, "_details": details}
    if deployment:
        rec["patchDeployment"] = deployment
    if not details:
        rec["state"] = "NO_INSTANCES_FOUND"
        rec["percentComplete"] = 100.0
    _x(store, "osc_patch_jobs")[rec["name"]] = rec
    return rec


def _job_view(store, rec):
    _settle(store, rec)
    out = _pub(rec)
    out["instanceDetailsSummary"] = _summary(rec["_details"])
    return out


def patch_jobs(store, method, project, rest, verb, payload, query):
    jobs = _x(store, "osc_patch_jobs")
    if not rest:
        if method == "POST" and verb == "execute":
            return _job_view(store, _new_job(store, project, payload))
        if method == "GET" and not verb:
            pre = "projects/%s/patchJobs/" % project
            items = [_job_view(store, v) for k, v in sorted(jobs.items(), key=lambda kv: kv[1]["createTime"], reverse=True) if k.startswith(pre)]
            flt = query.get("filter") or ""
            m = re.match(r'^\s*parent_patch_deployment\s*=\s*"?([^"\s]+)"?\s*$', flt)
            if m:
                items = [j for j in items if j.get("patchDeployment") == m.group(1)]
            elif flt:
                raise _bad("Unsupported filter %r (only parent_patch_deployment=... is supported)." % flt)
            return _page(items, query, "patchJobs")
        raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)
    full = "projects/%s/patchJobs/%s" % (project, rest[0])
    rec = jobs.get(full)
    if rec is None:
        raise _nf(full)
    if len(rest) == 2 and rest[1] == "instanceDetails" and method == "GET":
        _settle(store, rec)
        det = [{k: v for k, v in d.items() if not k.startswith("_")} for d in rec["_details"]]
        for d in det:
            d["name"] = d["name"]
        return _page(det, query, "patchJobInstanceDetails")
    if len(rest) == 1 and verb == "cancel" and method == "POST":
        _settle(store, rec)
        if rec["state"] in ("SUCCEEDED", "COMPLETED_WITH_ERRORS", "CANCELED", "TIMED_OUT", "NO_INSTANCES_FOUND"):
            raise _E(400, "FAILED_PRECONDITION", "Patch job %s is already in a terminal state (%s)." % (rest[0], rec["state"]))
        rec["state"] = "CANCELED"
        rec["updateTime"] = _iso(_now())
        for d in rec["_details"]:
            if d["state"] in ("PENDING", "STARTED", "NOTIFIED"):
                d["state"] = "INACTIVE"
                d["failureReason"] = "Patch job canceled."
        rec["instanceDetailsSummary"] = _summary(rec["_details"])
        return _job_view(store, rec)
    if len(rest) == 1 and method == "GET":
        return _job_view(store, rec)
    raise _E(404, "NOT_FOUND", "Unknown path.")


# ── patch deployments ─────────────────────────────────────────────────────────
def _tz(rs):
    name = ((rs.get("timeZone") or {}).get("id")) or "UTC"
    if name == "UTC" or ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        raise _bad("Invalid recurringSchedule.timeZone.id %r." % name)


def _tod(rs):
    t = rs.get("timeOfDay") or {}
    h, m = int(t.get("hours", 0)), int(t.get("minutes", 0))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise _bad("recurringSchedule.timeOfDay out of range.")
    return h, m


def _nth_weekday(year, month, dow, ordinal):
    d = datetime(year, month, 1)
    first = d + timedelta(days=(dow - d.weekday()) % 7)
    if ordinal > 0:
        return first + timedelta(days=7 * (ordinal - 1))
    nxt = datetime(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - dow) % 7)


def _month_days(year, month):
    return ((datetime(year + (month == 12), month % 12 + 1, 1)) - datetime(year, month, 1)).days


def _validate_recurring(rs):
    if rs.get("frequency") not in ("WEEKLY", "MONTHLY", "DAILY"):
        raise _bad("recurringSchedule.frequency must be WEEKLY, MONTHLY or DAILY.")
    _tz(rs)
    _tod(rs)
    if rs["frequency"] == "WEEKLY":
        if (rs.get("weekly") or {}).get("dayOfWeek") not in DAYS:
            raise _bad("recurringSchedule.weekly.dayOfWeek is required (MONDAY..SUNDAY).")
    elif rs["frequency"] == "MONTHLY":
        mo = rs.get("monthly") or {}
        if bool(mo.get("monthDay")) == bool(mo.get("weekDayOfMonth")):
            raise _bad("recurringSchedule.monthly needs exactly one of monthDay or weekDayOfMonth.")
        if mo.get("monthDay") is not None and not (mo["monthDay"] == -1 or 1 <= int(mo["monthDay"]) <= 31):
            raise _bad("recurringSchedule.monthly.monthDay must be 1..31 or -1 (last day).")
        w = mo.get("weekDayOfMonth")
        if w and (w.get("weekOrdinal") not in range(-1, 5) or w.get("weekOrdinal") == 0 or w.get("dayOfWeek") not in DAYS):
            raise _bad("recurringSchedule.monthly.weekDayOfMonth needs weekOrdinal (1..4 or -1) and dayOfWeek.")
    if rs.get("startTime"):
        _parse_ts(rs["startTime"], "recurringSchedule.startTime")
    if rs.get("endTime"):
        _parse_ts(rs["endTime"], "recurringSchedule.endTime")
        if rs.get("startTime") and _parse_ts(rs["endTime"], "") <= _parse_ts(rs["startTime"], ""):
            raise _bad("recurringSchedule.endTime must be after startTime.")


def next_execute(rs, after):
    """First fire time strictly after `after` (UTC datetime), or None when past endTime."""
    tz = _tz(rs)
    h, m = _tod(rs)
    local = after.astimezone(tz)
    start = _parse_ts(rs["startTime"], "") if rs.get("startTime") else None
    cur = local.replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(0, 800):
        ok = False
        if rs["frequency"] == "DAILY":
            ok = True
        elif rs["frequency"] == "WEEKLY":
            ok = DAYS[cur.weekday()] == rs["weekly"]["dayOfWeek"]
        else:
            mo = rs["monthly"]
            if mo.get("monthDay") is not None:
                last = _month_days(cur.year, cur.month)
                want = last if mo["monthDay"] == -1 else mo["monthDay"]
                ok = cur.day == min(want, last)
            else:
                w = mo["weekDayOfMonth"]
                ok = _nth_weekday(cur.year, cur.month, DAYS.index(w["dayOfWeek"]), w["weekOrdinal"]).day == cur.day
        if ok:
            cand = cur.replace(hour=h, minute=m).astimezone(timezone.utc)
            if cand > after and (start is None or cand >= start):
                end = _parse_ts(rs["endTime"], "") if rs.get("endTime") else None
                return None if end and cand > end else cand
        cur += timedelta(days=1)
    return None


def _deployment_view(rec):
    return _pub(rec)


def _tick_deployments(store, project):
    now = _now()
    for full, d in list(_x(store, "osc_patch_deployments").items()):
        if d.get("state") != "ACTIVE" or not full.startswith("projects/%s/" % project):
            continue
        if d.get("oneTimeSchedule") and not d.get("lastExecuteTime"):
            if _parse_ts(d["oneTimeSchedule"]["executeTime"], "") <= now:
                _new_job(store, project, d, deployment=full)
                d["lastExecuteTime"] = _iso(now)
        elif d.get("recurringSchedule"):
            rs = d["recurringSchedule"]
            nxt = rs.get("nextExecuteTime")
            fired = 0
            while nxt and _parse_ts(nxt, "") <= now and fired < 3:
                _new_job(store, project, d, deployment=full)
                d["lastExecuteTime"] = rs["lastExecuteTime"] = nxt
                n = next_execute(rs, _parse_ts(nxt, ""))
                rs["nextExecuteTime"] = _iso(n) if n else None
                if not n:
                    rs.pop("nextExecuteTime", None)
                    nxt = None
                else:
                    nxt = rs["nextExecuteTime"]
                fired += 1


def _check_schedule(body):
    one, rec = body.get("oneTimeSchedule"), body.get("recurringSchedule")
    if bool(one) == bool(rec):
        raise _bad("Exactly one of oneTimeSchedule or recurringSchedule is required.")
    if one:
        t = _parse_ts(one.get("executeTime"), "oneTimeSchedule.executeTime")
        if t <= _now():
            raise _bad("oneTimeSchedule.executeTime must be in the future.")
    else:
        _validate_recurring(rec)


def patch_deployments(store, method, project, rest, verb, payload, query):
    deps = _x(store, "osc_patch_deployments")
    _tick_deployments(store, project)
    pre = "projects/%s/patchDeployments/" % project
    if not rest:
        if method == "GET":
            return _page([_deployment_view(v) for k, v in sorted(deps.items()) if k.startswith(pre)], query, "patchDeployments")
        if method == "POST":
            did = query.get("patchDeploymentId") or ""
            if not ID_RE.match(did):
                raise _bad("patchDeploymentId must match [a-z]([-a-z0-9]*[a-z0-9])? and be at most 63 characters.")
            if pre + did in deps:
                raise _E(409, "ALREADY_EXISTS", "Patch deployment %s already exists." % did)
            _check_schedule(payload)
            f = payload.get("instanceFilter")
            _validate_filter(f, "instanceFilter")
            _validate_patch_config(payload.get("patchConfig"))
            _validate_rollout(payload.get("rollout"))
            dur = _dur(payload.get("duration"), "duration", 1800, 86400 * 7)
            if len(deps) >= 100:
                raise _E(429, "RESOURCE_EXHAUSTED", "Patch deployment quota (100 per project) exceeded.")
            now = _now()
            rec = {"name": pre + did, "description": payload.get("description", ""), "instanceFilter": f,
                   "patchConfig": payload.get("patchConfig") or {}, "duration": ("%ds" % dur) if dur else "3600s",
                   "rollout": payload.get("rollout") or {}, "createTime": _iso(now), "updateTime": _iso(now), "state": "ACTIVE"}
            if payload.get("oneTimeSchedule"):
                rec["oneTimeSchedule"] = payload["oneTimeSchedule"]
            else:
                rs = dict(payload["recurringSchedule"])
                rs.setdefault("timeZone", {"id": "UTC"})
                rs["timeCreated"] = _iso(now)
                n = next_execute(rs, now)
                if n:
                    rs["nextExecuteTime"] = _iso(n)
                rec["recurringSchedule"] = rs
            deps[rec["name"]] = rec
            return _deployment_view(rec)
        raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)
    full = pre + rest[0]
    rec = deps.get(full)
    if rec is None:
        raise _nf(full)
    if method == "GET" and not verb:
        return _deployment_view(rec)
    if method == "DELETE":
        del deps[full]
        return {}
    if method == "POST" and verb in ("pause", "resume"):
        if verb == "pause":
            if rec["state"] == "PAUSED":
                raise _E(400, "FAILED_PRECONDITION", "Patch deployment is already paused.")
            rec["state"] = "PAUSED"
        else:
            if rec["state"] == "ACTIVE":
                raise _E(400, "FAILED_PRECONDITION", "Patch deployment is not paused.")
            rec["state"] = "ACTIVE"
            if rec.get("recurringSchedule"):
                n = next_execute(rec["recurringSchedule"], _now())
                rec["recurringSchedule"]["nextExecuteTime"] = _iso(n) if n else None
        rec["updateTime"] = _iso(_now())
        return _deployment_view(rec)
    if method == "PATCH":
        mask = [m for m in (query.get("updateMask") or "").split(",") if m] or [k for k in payload if k in (
            "description", "instanceFilter", "patchConfig", "duration", "rollout", "oneTimeSchedule", "recurringSchedule")]
        for m in mask:
            if m not in ("description", "instanceFilter", "patchConfig", "duration", "rollout", "oneTimeSchedule", "recurringSchedule"):
                raise _bad("Unsupported update_mask path %r." % m)
        merged = dict(rec)
        for m in mask:
            merged[m] = payload.get(m, merged.get(m))
        if "oneTimeSchedule" in mask or "recurringSchedule" in mask:
            merged.pop("oneTimeSchedule" if "recurringSchedule" in mask and "oneTimeSchedule" not in mask else "recurringSchedule", None)
            _check_schedule(merged)
        _validate_filter(merged.get("instanceFilter"), "instanceFilter")
        _validate_patch_config(merged.get("patchConfig"))
        _validate_rollout(merged.get("rollout"))
        if "recurringSchedule" in mask:
            rs = dict(merged["recurringSchedule"])
            rs.setdefault("timeZone", {"id": "UTC"})
            n = next_execute(rs, _now())
            rs["nextExecuteTime"] = _iso(n) if n else None
            merged["recurringSchedule"] = rs
        merged["updateTime"] = _iso(_now())
        deps[full] = merged
        return _deployment_view(merged)
    raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)


# ── OS policy assignments ─────────────────────────────────────────────────────
def _validate_resource(r, where):
    if not isinstance(r, dict) or not ID_RE.match(str(r.get("id", ""))):
        raise _bad("%s.id is required and must match [a-z]([-a-z0-9]*[a-z0-9])?." % where)
    kinds = [k for k in ("pkg", "repository", "exec", "file") if r.get(k)]
    if len(kinds) != 1:
        raise _bad("%s must set exactly one of pkg, repository, exec or file." % where)
    k = kinds[0]
    v = r[k]
    if k == "pkg":
        if v.get("desiredState") not in PKG_STATES:
            raise _bad("%s.pkg.desiredState must be INSTALLED or REMOVED." % where)
        srcs = [s for s in PKG_SOURCES if v.get(s)]
        if len(srcs) != 1:
            raise _bad("%s.pkg must set exactly one package source (%s)." % (where, ", ".join(PKG_SOURCES)))
        if srcs[0] in ("apt", "yum", "zypper", "googet") and not (v[srcs[0]] or {}).get("name"):
            raise _bad("%s.pkg.%s.name is required." % (where, srcs[0]))
    elif k == "repository":
        srcs = [s for s in ("apt", "yum", "zypper", "goo") if v.get(s)]
        if len(srcs) != 1:
            raise _bad("%s.repository must set exactly one of apt, yum, zypper, goo." % where)
        s = v[srcs[0]]
        if srcs[0] == "apt" and not (s.get("uri") and s.get("distribution") and s.get("components")):
            raise _bad("%s.repository.apt needs uri, distribution and components." % where)
        if srcs[0] in ("yum", "zypper") and not (s.get("id") and s.get("baseUrl")):
            raise _bad("%s.repository.%s needs id and baseUrl." % (where, srcs[0]))
        if srcs[0] == "goo" and not (s.get("name") and s.get("url")):
            raise _bad("%s.repository.goo needs name and url." % where)
    elif k == "exec":
        val = v.get("validate")
        if not val or not (val.get("script") or val.get("file")):
            raise _bad("%s.exec.validate needs a script or file." % where)
        if val.get("interpreter") not in INTERPRETERS and val.get("interpreter") is not None:
            raise _bad("%s.exec.validate.interpreter must be SHELL or POWERSHELL." % where)
        if val.get("interpreter") in (None, "INTERPRETER_UNSPECIFIED") and val.get("script"):
            raise _bad("%s.exec.validate.interpreter is required for inline scripts." % where)
    else:
        if not str(v.get("path", "")).startswith(("/", "C:", "c:")) and not re.match(r"^[A-Za-z]:\\", str(v.get("path", ""))):
            raise _bad("%s.file.path must be an absolute path." % where)
        if v.get("state") not in FILE_STATES:
            raise _bad("%s.file.state must be one of %s." % (where, ", ".join(FILE_STATES)))
        if v["state"] != "ABSENT" and not (v.get("content") or v.get("file")):
            raise _bad("%s.file needs content or file when state is %s." % (where, v["state"]))


def _validate_assignment(body):
    pols = body.get("osPolicies")
    if not pols or not isinstance(pols, list):
        raise _bad("osPolicies is required and must contain at least one OS policy.")
    seen = set()
    for pi, p in enumerate(pols):
        w = "osPolicies[%d]" % pi
        if not ID_RE.match(str(p.get("id", ""))):
            raise _bad("%s.id is required and must match [a-z]([-a-z0-9]*[a-z0-9])?." % w)
        if p["id"] in seen:
            raise _bad("Duplicate OS policy id %r." % p["id"])
        seen.add(p["id"])
        if p.get("mode") not in POLICY_MODES:
            raise _bad("%s.mode must be VALIDATION or ENFORCEMENT." % w)
        groups = p.get("resourceGroups")
        if not groups:
            raise _bad("%s.resourceGroups needs at least one resource group." % w)
        rids = set()
        for gi, g in enumerate(groups):
            if not g.get("resources"):
                raise _bad("%s.resourceGroups[%d].resources needs at least one resource." % (w, gi))
            for ri, r in enumerate(g["resources"]):
                _validate_resource(r, "%s.resourceGroups[%d].resources[%d]" % (w, gi, ri))
                if r["id"] in rids:
                    raise _bad("Duplicate resource id %r in OS policy %s." % (r["id"], p["id"]))
                rids.add(r["id"])
    f = body.get("instanceFilter")
    if not isinstance(f, dict) or not (f.get("all") or f.get("inclusionLabels") or f.get("inventories")):
        raise _bad("instanceFilter needs all, inclusionLabels or inventories.")
    if f.get("all") and (f.get("inclusionLabels") or f.get("inventories")):
        raise _bad("instanceFilter.all cannot be combined with inclusionLabels or inventories.")
    ro = body.get("rollout")
    if not ro or not ro.get("disruptionBudget"):
        raise _bad("rollout.disruptionBudget is required.")
    db = ro["disruptionBudget"]
    if ("fixed" in db) == ("percent" in db):
        raise _bad("rollout.disruptionBudget needs exactly one of fixed or percent.")
    if "percent" in db and not (1 <= int(db["percent"]) <= 100):
        raise _bad("rollout.disruptionBudget.percent must be between 1 and 100.")
    if "fixed" in db and int(db["fixed"]) < 1:
        raise _bad("rollout.disruptionBudget.fixed must be at least 1.")
    _dur(ro.get("minWaitDuration"), "rollout.minWaitDuration", 0)


def match_assignment(store, project, zone, f):
    out = []
    for key, inst in _instances(store, project):
        if _zone_of(key) != zone:
            continue
        labels = inst.get("labels") or {}
        ok = bool(f.get("all"))
        if not ok:
            incl = f.get("inclusionLabels") or []
            ok = bool(incl) and any(all(labels.get(k) == v for k, v in (g.get("labels") or {}).items()) for g in incl)
        if ok and any(all(labels.get(k) == v for k, v in (g.get("labels") or {}).items()) for g in (f.get("exclusionLabels") or [])):
            ok = False
        if ok:
            out.append(key)
    return out


def _lro(project, zone, name, response, kind="OSPolicyAssignmentOperationMetadata", verb="CREATE"):
    oid = "operation-%s" % uuid.uuid4().hex[:16]
    return {"name": "projects/%s/locations/%s/operations/%s" % (project, zone, oid), "done": True,
            "metadata": {"@type": "type.googleapis.com/google.cloud.osconfig.v1.%s" % kind, "osPolicyAssignment": name,
                         "apiMethod": verb, "rolloutState": "SUCCEEDED", "rolloutStartTime": _iso(_now()), "rolloutUpdateTime": _iso(_now())},
            "response": response}


def _assignment_view(store, project, zone, rec, rev=None):
    r = dict(rev or rec["_revisions"][-1])
    out = {k: v for k, v in r.items() if not k.startswith("_")}
    out.update({"name": "%s@%s" % (rec["name"], r["revisionId"]), "uid": rec["uid"], "baseline": rec.get("baseline", False),
                "deleted": False, "reconciling": False, "rolloutState": "SUCCEEDED"})
    return out


def os_policy_assignments(store, method, project, zone, rest, verb, payload, query):
    if not ZONE_RE.match(zone):
        raise _bad("Invalid location %r: OS policy assignments are zonal (for example us-central1-a)." % zone)
    coll = _x(store, "osc_policy_assignments")
    pre = "projects/%s/locations/%s/osPolicyAssignments/" % (project, zone)
    if not rest:
        if method == "GET":
            items = [_assignment_view(store, project, zone, v) for k, v in sorted(coll.items()) if k.startswith(pre)]
            return _page(items, query, "osPolicyAssignments")
        if method == "POST":
            aid = query.get("osPolicyAssignmentId") or ""
            if not ID_RE.match(aid):
                raise _bad("osPolicyAssignmentId must match [a-z]([-a-z0-9]*[a-z0-9])? and be at most 63 characters.")
            if pre + aid in coll:
                raise _E(409, "ALREADY_EXISTS", "OS policy assignment %s already exists." % aid)
            _validate_assignment(payload)
            if sum(1 for k in coll if k.startswith(pre)) >= 100:
                raise _E(429, "RESOURCE_EXHAUSTED", "OS policy assignment quota (100 per zone) exceeded.")
            now = _iso(_now())
            rev = {k: payload[k] for k in ("description", "osPolicies", "instanceFilter", "rollout") if k in payload}
            rev.update({"revisionId": uuid.uuid4().hex[:16], "revisionCreateTime": now})
            rec = {"name": pre + aid, "uid": str(uuid.uuid4()), "_revisions": [rev]}
            coll[pre + aid] = rec
            return _lro(project, zone, rec["name"], _assignment_view(store, project, zone, rec))
        raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)
    ident = rest[0]
    if len(rest) == 1 and ":" in ident:
        ident, verb = ident.split(":", 1)
    full = pre + ident.split("@")[0]
    rec = coll.get(full)
    if rec is None:
        raise _nf(full)
    if verb == "listRevisions" and method == "GET":
        return _page([_assignment_view(store, project, zone, rec, r) for r in reversed(rec["_revisions"])], query, "osPolicyAssignments")
    if method == "GET":
        if "@" in ident:
            rev = next((r for r in rec["_revisions"] if r["revisionId"] == ident.split("@", 1)[1]), None)
            if rev is None:
                raise _nf(full)
            return _assignment_view(store, project, zone, rec, rev)
        return _assignment_view(store, project, zone, rec)
    if method == "DELETE":
        del coll[full]
        return _lro(project, zone, rec["name"], {}, verb="DELETE")
    if method == "PATCH":
        cur = rec["_revisions"][-1]
        mask = [m for m in (query.get("updateMask") or "").split(",") if m] or [k for k in payload if k in ("description", "osPolicies", "instanceFilter", "rollout")]
        for m in mask:
            if m not in ("description", "osPolicies", "instanceFilter", "rollout"):
                raise _bad("Unsupported update_mask path %r." % m)
        merged = {k: cur[k] for k in ("description", "osPolicies", "instanceFilter", "rollout") if k in cur}
        for m in mask:
            merged[m] = payload.get(m)
        _validate_assignment(merged)
        merged.update({"revisionId": uuid.uuid4().hex[:16], "revisionCreateTime": _iso(_now())})
        rec["_revisions"].append(merged)
        return _lro(project, zone, rec["name"], _assignment_view(store, project, zone, rec), verb="UPDATE")
    raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)


def assignment_instances(store, project, zone, ident):
    """Instances an assignment currently targets (console: 'Matched VMs')."""
    rec = _x(store, "osc_policy_assignments").get("projects/%s/locations/%s/osPolicyAssignments/%s" % (project, zone, ident))
    if rec is None:
        raise _nf(ident)
    return match_assignment(store, project, zone, rec["_revisions"][-1]["instanceFilter"])


# ── VM extension policies (Compute beta/v1: global/vmExtensionPolicies) ───────
def _compute_op(store, project, op_type, name):
    from core import gcp_compute_instances_core as G
    return G._operation(store, project, None, op_type, name, G._selflink("projects/%s/global/vmExtensionPolicies/%s" % (project, name)))


def vm_extension_policies(store, method, project, rest, payload, query):
    from core import gcp_compute_instances_core as G
    coll = _x(store, "osc_vm_ext_policies")
    pre = "projects/%s/global/vmExtensionPolicies/" % project
    link = lambda n: G._selflink(pre + n)       # noqa: E731
    if not rest:
        if method == "GET":
            items = [dict(v, selfLink=link(v["name"])) for k, v in sorted(coll.items()) if k.startswith(pre)]
            return {"kind": "compute#vmExtensionPolicyList", "id": "projects/%s/global/vmExtensionPolicies" % project, "items": items}
        if method == "POST":
            name = str(payload.get("name", ""))
            if not ID_RE.match(name):
                raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'resource.name': '%s'. Must be a match of regex '[a-z]([-a-z0-9]*[a-z0-9])?'." % name)
            if pre + name in coll:
                raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists" % (link(name)))
            ex = payload.get("extensionPolicies")
            if not ex or not isinstance(ex, dict):
                raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'resource.extensionPolicies': at least one extension is required.")
            for k, v in ex.items():
                if not EXT_NAME_RE.match(k):
                    raise _E(400, "INVALID_ARGUMENT", "Invalid extension name '%s'." % k)
                if k not in KNOWN_EXTENSIONS:
                    raise _E(400, "INVALID_ARGUMENT", "Unknown extension '%s'. Supported: %s." % (k, ", ".join(KNOWN_EXTENSIONS)))
                if v and v.get("pinnedVersion") and not re.match(r"^\d+\.\d+\.\d+([-.][0-9A-Za-z.]+)?$", str(v["pinnedVersion"])):
                    raise _E(400, "INVALID_ARGUMENT", "Invalid pinnedVersion '%s' for extension '%s'." % (v["pinnedVersion"], k))
            sel = payload.get("instanceSelectors") or []
            if not sel:
                raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'resource.instanceSelectors': at least one selector is required.")
            for s in sel:
                if not ((s.get("labelSelector") or {}).get("inclusionLabels")):
                    raise _E(400, "INVALID_ARGUMENT", "instanceSelectors[].labelSelector.inclusionLabels must not be empty.")
            prio = payload.get("priority", 0)
            if not isinstance(prio, int) or not (0 <= prio <= 65535):
                raise _E(400, "INVALID_ARGUMENT", "priority must be between 0 and 65535.")
            plan = ((payload.get("rolloutOperation") or {}).get("rolloutInput") or {}).get("predefinedRolloutPlan")
            if plan is not None and plan not in ROLLOUT_PLANS:
                raise _E(400, "INVALID_ARGUMENT", "predefinedRolloutPlan must be FAST_ROLLOUT or SLOW_ROLLOUT.")
            now = _iso(_now())
            rec = {"kind": "compute#vmExtensionPolicy", "id": str(G._next_id(store)), "name": name,
                   "description": payload.get("description", ""), "extensionPolicies": ex, "instanceSelectors": sel,
                   "priority": prio, "rolloutOperation": payload.get("rolloutOperation") or {},
                   "creationTimestamp": now, "updateTimestamp": now, "state": "ACTIVE"}
            coll[pre + name] = rec
            return _compute_op(store, project, "insert", name)
        raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)
    full = pre + rest[0]
    rec = coll.get(full)
    if rec is None:
        raise _E(404, "NOT_FOUND", "The resource '%s' was not found" % link(rest[0]))
    if method == "GET":
        return dict(rec, selfLink=link(rest[0]))
    if method == "DELETE":
        del coll[full]
        return _compute_op(store, project, "delete", rest[0])
    if method in ("PATCH", "PUT"):
        for k in ("description", "extensionPolicies", "instanceSelectors", "priority", "rolloutOperation"):
            if k in payload:
                rec[k] = payload[k]
        rec["updateTimestamp"] = _iso(_now())
        return _compute_op(store, project, "patch", rest[0])
    raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)


def vm_extension_status(store, project, policy_name):
    """Instances whose labels satisfy a VM extension policy's selectors (the policy's real blast radius)."""
    rec = _x(store, "osc_vm_ext_policies").get("projects/%s/global/vmExtensionPolicies/%s" % (project, policy_name))
    if rec is None:
        return []
    out = []
    for key, inst in _instances(store, project):
        labels = inst.get("labels") or {}
        if any(all(labels.get(k) == v for k, v in ((s.get("labelSelector") or {}).get("inclusionLabels") or {}).items()) for s in rec["instanceSelectors"]):
            out.append(key)
    return out


# ── dispatch ──────────────────────────────────────────────────────────────────
def _err(e):
    return Resp(e.status, {"error": {"code": e.status, "message": e.message, "status": e.gcp_status}})


def dispatch(store, method, path, query=None, headers=None, body=b""):
    """osconfig.googleapis.com v1 REST."""
    query, method = query or {}, method.upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        return _err(_bad("Invalid JSON payload received."))
    p = path.split("?", 1)[0].strip("/")
    verb = ""
    last = p.rsplit("/", 1)[-1]
    if ":" in last:
        p, verb = p.rsplit(":", 1)
    segs = p.split("/")
    try:
        project, rest = segs[2], segs[3:]
        if rest[:1] == ["patchJobs"]:
            out = patch_jobs(store, method, project, rest[1:], verb, payload, query)
        elif rest[:1] == ["patchDeployments"]:
            out = patch_deployments(store, method, project, rest[1:], verb, payload, query)
        elif rest[:1] == ["locations"] and len(rest) >= 3 and rest[2] == "osPolicyAssignments":
            out = os_policy_assignments(store, method, project, rest[1], rest[3:], verb, payload, query)
        else:
            raise _E(404, "NOT_FOUND", "Unknown path: %s" % path)
        if method != "GET" and hasattr(store, "persist"):
            store.persist()
        return Resp(200, out)
    except _E as e:
        return _err(e)
    except (ValueError, TypeError) as e:
        return _err(_bad("Invalid request: %s" % e))


def compute_handle(store, method, project, rest, payload, query):
    """Hook for the Compute dispatcher: (status, obj) for global/vmExtensionPolicies paths else None."""
    if len(rest) < 2 or rest[0] != "global" or rest[1] != "vmExtensionPolicies":
        return None
    try:
        return 200, vm_extension_policies(store, method, project, rest[2:], payload, query)
    except _E as e:
        return e.status, {"error": {"code": e.status, "message": e.message, "status": e.gcp_status}}
