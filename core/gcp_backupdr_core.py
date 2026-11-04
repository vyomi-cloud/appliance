"""Backup and DR Service (backupdr.googleapis.com/v1) on the Compute Engine core — substrate-independent.

Resources (all under projects/{p}/locations/{l}):
  backupVaults                         create/get/list/delete (+ minimum enforced retention, force delete)
  backupVaults/{v}/dataSources         created when a resource is protected; list/get
  .../dataSources/{ds}/backups         list/get/delete (enforced-retention rule), :restore
  backupPlans                          create/get/list/delete (rules: schedule + retention days)
  backupPlanAssociations               protect a Compute instance / disk with a plan; :triggerBackup

A backup is REAL: it takes a real Compute Engine snapshot of every disk of the instance (or of the
disk) through core/gcp_compute_instances_core (visible on the Snapshots page, label
vyomi-backupdr). Restore creates new disks from those snapshots (and a new instance for an instance
backup). Plan rules fire from a lazy tick on every call (and from core/schedule_core's PROVIDERS pass
offline), using the shared schedule seam's spec language. State lives in store.ext["backupdr"] of the
Compute store, so it persists with it on both substrates.

Honest limits: no management server / agent-based workloads (SAP HANA, Oracle, SQL Server, file
systems), no vault cross-region replication, no immutability beyond the enforced-retention rule on
backup deletion, no ransomware/threat analysis; LRO operations complete inline (done=true); schedule
time zones are UTC; missed fires coalesce into one run.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone

try:
    from core import gcp_compute_instances_core as G
    from core import schedule_core as SC
except ImportError:  # pragma: no cover - Pyodide flat layout
    import gcp_compute_instances_core as G  # type: ignore
    import schedule_core as SC  # type: ignore

ID_RE = re.compile(r"^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$")
RES_TYPES = ("compute.googleapis.com/Instance", "compute.googleapis.com/Disk")
RECURRENCE = ("HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY")
_DOW = {"MONDAY": "MON", "TUESDAY": "TUE", "WEDNESDAY": "WED", "THURSDAY": "THU", "FRIDAY": "FRI", "SATURDAY": "SAT", "SUNDAY": "SUN"}
MIN_RETENTION_S = 86400


class Resp:
    media_type = "application/json"

    def __init__(self, status, obj):
        self.status, self.headers = status, {}
        self.body = json.dumps(obj).encode()


class _E(Exception):
    def __init__(self, status, gcp_status, message):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _bad(m):
    return _E(400, "INVALID_ARGUMENT", m)


def _pre(m):
    return _E(400, "FAILED_PRECONDITION", m)


def _nf(kind, name):
    return _E(404, "NOT_FOUND", "%s %s not found" % (kind, name))


def _x(store):
    ext = getattr(store, "ext", None)
    if ext is None:
        raise _E(500, "INTERNAL", "backup store unavailable")
    d = ext.setdefault("backupdr", {})
    for k in ("vaults", "plans", "assocs", "datasources", "backups", "tick"):
        d.setdefault(k, {})
    d.setdefault("seq", 0)
    return d


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _now_iso(now=None):
    return _iso(datetime.fromtimestamp(now, tz=timezone.utc) if now else datetime.now(timezone.utc))


def _parse(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def _uid(*parts):
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:8] + "-" + hashlib.sha1(("u" + "|".join(parts)).encode()).hexdigest()[:12]


def _seconds(v, field):
    m = re.match(r"^(\d+)s$", str(v or ""))
    if not m:
        raise _bad("Invalid value for field '%s': %r. Must be a duration in seconds such as \"86400s\"." % (field, v))
    return int(m.group(1))


def _op(project, loc, verb, target):
    oid = "operation-" + hashlib.sha1((target + verb + _now_iso()).encode()).hexdigest()[:16]
    return {"name": "projects/%s/locations/%s/operations/%s" % (project, loc, oid), "done": True,
            "metadata": {"@type": "type.googleapis.com/google.cloud.backupdr.v1.OperationMetadata", "target": target, "verb": verb,
                         "createTime": _now_iso(), "endTime": _now_iso(), "apiVersion": "v1", "requestedCancellation": False}}


def _wrap(project, loc, verb, target, resp, typ):
    r = dict(resp)
    r["@type"] = "type.googleapis.com/google.cloud.backupdr.v1." + typ
    o = _op(project, loc, verb, target)
    o["response"] = r
    return o


def _clean(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ── schedule mapping ─────────────────────────────────────────────────────────
def _validate_rule(rule, vault_min_s):
    rid = rule.get("ruleId") or ""
    if not ID_RE.match(rid):
        raise _bad("Invalid value for field 'backupRules.ruleId': %r." % rid)
    days = rule.get("backupRetentionDays")
    if not isinstance(days, int) or days < 1:
        raise _bad("backupRules[%s].backupRetentionDays must be a positive integer." % rid)
    if days * 86400 < vault_min_s:
        raise _pre("Rule %s retains backups for %d days, below the vault's minimum enforced retention of %d seconds." % (rid, days, vault_min_s))
    sch = rule.get("standardSchedule") or {}
    rec = sch.get("recurrenceType")
    if rec not in RECURRENCE:
        raise _bad("backupRules[%s].standardSchedule.recurrenceType must be one of %s." % (rid, ", ".join(RECURRENCE)))
    if rec == "HOURLY":
        n = sch.get("hourlyFrequency")
        if not isinstance(n, int) or not 1 <= n <= 23:
            raise _bad("HOURLY schedules need hourlyFrequency between 1 and 23.")
    if rec == "WEEKLY":
        dw = sch.get("daysOfWeek") or []
        if not dw or any(d not in _DOW for d in dw):
            raise _bad("WEEKLY schedules need daysOfWeek (MONDAY..SUNDAY).")
    if rec == "MONTHLY" and not (sch.get("daysOfMonth") or sch.get("weekDayOfMonth")):
        raise _bad("MONTHLY schedules need daysOfMonth or weekDayOfMonth.")
    if rec == "YEARLY" and not (sch.get("months") and (sch.get("daysOfMonth") or sch.get("weekDayOfMonth"))):
        raise _bad("YEARLY schedules need months and daysOfMonth or weekDayOfMonth.")
    bw = sch.get("backupWindow") or {}
    sh, eh = bw.get("startHourOfDay", 0), bw.get("endHourOfDay", 24)
    if not (isinstance(sh, int) and isinstance(eh, int) and 0 <= sh <= 23 and 1 <= eh <= 24 and sh < eh):
        raise _bad("backupWindow needs 0 <= startHourOfDay < endHourOfDay <= 24.")


def _spec(rule):
    sch = rule["standardSchedule"]
    rec, hh = sch["recurrenceType"], (sch.get("backupWindow") or {}).get("startHourOfDay", 0)
    if rec == "HOURLY":
        return "hourly@%d" % sch["hourlyFrequency"]
    if rec == "WEEKLY":
        return "weekly@%02d:00@%s" % (hh, ",".join(_DOW[d] for d in sch["daysOfWeek"]))
    return "daily@%02d:00" % hh      # MONTHLY / YEARLY are gated on the day below


def _day_ok(rule, when):
    sch = rule["standardSchedule"]
    if sch["recurrenceType"] == "MONTHLY":
        return not sch.get("daysOfMonth") or when.day in sch["daysOfMonth"]
    if sch["recurrenceType"] == "YEARLY":
        months = [m[:3] for m in sch.get("months", [])]
        return when.strftime("%b").upper() in months and (not sch.get("daysOfMonth") or when.day in sch["daysOfMonth"])
    return True


# ── vaults ───────────────────────────────────────────────────────────────────
def _vault_name(p, l, v):
    return "projects/%s/locations/%s/backupVaults/%s" % (p, l, v)


def _vault_view(d, rec):
    out = _clean(rec)
    bks = [b for b in d["backups"].values() if b["_vault"] == rec["name"]]
    out["backupCount"] = str(len(bks))
    out["totalStoredBytes"] = str(sum(int(b.get("resourceSizeBytes") or 0) for b in bks))
    out["deletable"] = not bks
    return out


def _vaults(store, d, method, p, l, rest, q, body, now):
    if not rest:
        if method == "POST":
            vid = q.get("backupVaultId") or ""
            if not ID_RE.match(vid):
                raise _bad("Invalid backupVaultId %r: must be 1-63 characters, start with a lowercase letter, contain only lowercase letters, digits and hyphens." % vid)
            name = _vault_name(p, l, vid)
            if name in d["vaults"]:
                raise _E(409, "ALREADY_EXISTS", "Resource %s already exists." % name)
            ret = _seconds(body.get("backupMinimumEnforcedRetentionDuration"), "backupMinimumEnforcedRetentionDuration")
            if ret < MIN_RETENTION_S:
                raise _bad("backupMinimumEnforcedRetentionDuration must be at least 1 day (86400s).")
            now_s = _now_iso(now)
            rec = {"name": name, "description": body.get("description", ""), "labels": body.get("labels") or {},
                   "createTime": now_s, "updateTime": now_s, "backupMinimumEnforcedRetentionDuration": "%ds" % ret,
                   "state": "ACTIVE", "uid": _uid(name), "etag": _uid(name, now_s)[:8], "annotations": body.get("annotations") or {},
                   "accessRestriction": body.get("accessRestriction") or "WITHIN_ORGANIZATION",
                   "serviceAccount": "service-%s@gcp-sa-backupdr.iam.gserviceaccount.com" % hashlib.sha1(p.encode()).hexdigest()[:12]}
            d["vaults"][name] = rec
            return _wrap(p, l, "create", name, _vault_view(d, rec), "BackupVault")
        if method == "GET":
            items = [_vault_view(d, v) for n, v in sorted(d["vaults"].items()) if n.startswith("projects/%s/locations/%s/" % (p, l)) or l == "-" and n.startswith("projects/%s/" % p)]
            return {"backupVaults": items} if items else {}
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    v = rest[0]
    name = _vault_name(p, l, v)
    rec = d["vaults"].get(name)
    if len(rest) == 1:
        if rec is None:
            raise _nf("BackupVault", name)
        if method == "GET":
            return _vault_view(d, rec)
        if method == "PATCH":
            for f in ("description", "labels"):
                if f in body:
                    rec[f] = body[f]
            if "backupMinimumEnforcedRetentionDuration" in body:
                new = _seconds(body["backupMinimumEnforcedRetentionDuration"], "backupMinimumEnforcedRetentionDuration")
                if new < _seconds(rec["backupMinimumEnforcedRetentionDuration"], "x"):
                    raise _pre("The minimum enforced retention duration of a vault can only be increased.")
                rec["backupMinimumEnforcedRetentionDuration"] = "%ds" % new
            rec["updateTime"] = _now_iso(now)
            return _wrap(p, l, "update", name, _vault_view(d, rec), "BackupVault")
        if method == "DELETE":
            bks = [b for b in d["backups"].values() if b["_vault"] == name]
            if bks and str(q.get("force", "")).lower() != "true":
                raise _pre("BackupVault %s has %d backup(s); delete them first or pass force=true." % (name, len(bks)))
            for b in bks:
                _drop_backup(store, d, b, enforce=True, now=now)
            for dn in [n for n, ds in d["datasources"].items() if ds["_vault"] == name]:
                del d["datasources"][dn]
            del d["vaults"][name]
            return _wrap(p, l, "delete", name, {}, "OperationMetadata")
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    if rec is None:
        raise _nf("BackupVault", name)
    if rest[1] != "dataSources":
        raise _E(404, "NOT_FOUND", "Unknown path")
    return _datasources(store, d, method, p, l, name, rest[2:], q, body, now)


# ── data sources + backups ───────────────────────────────────────────────────
def _ds_view(d, ds):
    out = _clean(ds)
    out["backupCount"] = str(sum(1 for b in d["backups"].values() if b["_ds"] == ds["name"]))
    return out


def _datasources(store, d, method, p, l, vname, rest, q, body, now):
    if not rest:
        if method != "GET":
            raise _E(405, "UNIMPLEMENTED", "Data sources are created by associating a backup plan with a resource.")
        return {"dataSources": [_ds_view(d, ds) for _, ds in sorted(d["datasources"].items()) if ds["_vault"] == vname]}
    dsname = "%s/dataSources/%s" % (vname, rest[0])
    ds = d["datasources"].get(dsname)
    if ds is None:
        raise _nf("DataSource", dsname)
    if len(rest) == 1:
        if method == "GET":
            return _ds_view(d, ds)
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    if rest[1] != "backups":
        raise _E(404, "NOT_FOUND", "Unknown path")
    if len(rest) == 2:
        if method != "GET":
            raise _E(405, "UNIMPLEMENTED", "Backups are created by a plan rule or :triggerBackup.")
        return {"backups": [_backup_view(b) for _, b in sorted(d["backups"].items(), reverse=True) if b["_ds"] == dsname]}
    last = rest[2]
    verb = ""
    if ":" in last:
        last, verb = last.split(":", 1)
    bname = "%s/backups/%s" % (dsname, last)
    b = d["backups"].get(bname)
    if b is None:
        raise _nf("Backup", bname)
    if verb == "restore" and method == "POST":
        return _restore(store, d, p, l, b, body, now)
    if verb:
        raise _E(404, "NOT_FOUND", "Unknown method :%s" % verb)
    if method == "GET":
        return _backup_view(b)
    if method == "DELETE":
        _drop_backup(store, d, b, enforce=True, now=now)
        return _wrap(p, l, "delete", bname, {}, "OperationMetadata")
    raise _E(405, "UNIMPLEMENTED", "Method not allowed")


def _backup_view(b):
    out = _clean(b)
    out["gcpBackupPlanInfo"] = b.get("gcpBackupPlanInfo")
    return out


def _drop_backup(store, d, b, enforce, now=None):
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc) if now else datetime.now(timezone.utc)
    if enforce and _parse(b["enforcedRetentionEndTime"]) > now_dt:
        raise _pre("Backup %s cannot be deleted before %s (the vault's enforced retention period)." % (b["name"], b["enforcedRetentionEndTime"]))
    for sn in b["_snapshots"]:
        store.snapshots.pop("projects/%s/global/snapshots/%s" % (b["_project"], sn), None)
    d["backups"].pop(b["name"], None)


# ── plans ────────────────────────────────────────────────────────────────────
def _plans(store, d, method, p, l, rest, q, body, now):
    if not rest:
        if method == "POST":
            pid = q.get("backupPlanId") or ""
            if not ID_RE.match(pid):
                raise _bad("Invalid backupPlanId %r." % pid)
            name = "projects/%s/locations/%s/backupPlans/%s" % (p, l, pid)
            if name in d["plans"]:
                raise _E(409, "ALREADY_EXISTS", "Resource %s already exists." % name)
            rt = body.get("resourceType")
            if rt not in RES_TYPES:
                raise _bad("resourceType must be one of %s (other workload types need a management server, which Vyomi does not run)." % ", ".join(RES_TYPES))
            vault = d["vaults"].get(body.get("backupVault") or "")
            if vault is None:
                raise _nf("BackupVault", body.get("backupVault") or "")
            rules = body.get("backupRules") or []
            if not rules:
                raise _bad("At least one backupRule is required.")
            if len({r.get("ruleId") for r in rules}) != len(rules):
                raise _bad("backupRules.ruleId values must be unique within a plan.")
            vmin = _seconds(vault["backupMinimumEnforcedRetentionDuration"], "x")
            for r in rules:
                _validate_rule(r, vmin)
            now_s = _now_iso(now)
            rec = {"name": name, "description": body.get("description", ""), "labels": body.get("labels") or {}, "backupRules": rules,
                   "state": "ACTIVE", "resourceType": rt, "etag": _uid(name)[:8], "createTime": now_s, "updateTime": now_s,
                   "backupVault": vault["name"], "backupVaultServiceAccount": vault["serviceAccount"]}
            d["plans"][name] = rec
            return _wrap(p, l, "create", name, rec, "BackupPlan")
        if method == "GET":
            return {"backupPlans": [dict(v) for n, v in sorted(d["plans"].items()) if n.startswith("projects/%s/locations/%s/" % (p, l)) or l == "-"]}
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    name = "projects/%s/locations/%s/backupPlans/%s" % (p, l, rest[0])
    rec = d["plans"].get(name)
    if rec is None:
        raise _nf("BackupPlan", name)
    if method == "GET":
        return dict(rec)
    if method == "DELETE":
        users = [a for a in d["assocs"].values() if a["backupPlan"] == name]
        if users:
            raise _pre("BackupPlan %s is still used by %d association(s): %s" % (name, len(users), users[0]["name"]))
        del d["plans"][name]
        return _wrap(p, l, "delete", name, {}, "OperationMetadata")
    raise _E(405, "UNIMPLEMENTED", "Method not allowed")


# ── associations, backups ────────────────────────────────────────────────────
def _res_ref(store, project, rtype, resource):
    """(zone, name, record) of the Compute instance / disk a plan association protects."""
    m = re.match(r"^(?:https://[^/]+/compute/[^/]+/)?projects/([^/]+)/zones/([^/]+)/(instances|disks)/([^/]+)$", resource or "")
    if not m:
        raise _bad("resource must be projects/{project}/zones/{zone}/%s/{name}." % ("instances" if rtype.endswith("Instance") else "disks"))
    if (m.group(3) == "instances") != rtype.endswith("Instance"):
        raise _bad("resource %s does not match the plan's resourceType %s." % (resource, rtype))
    full = "projects/%s/zones/%s/%s/%s" % (m.group(1), m.group(2), m.group(3), m.group(4))
    rec = (store.instances if m.group(3) == "instances" else store.disks).get(full)
    if rec is None:
        raise _nf("Resource", full)
    return m.group(1), m.group(2), m.group(4), rec


def _short(s, n):
    return re.sub(r"[^a-z0-9-]", "", s.lower())[:n]


def _assocs(store, d, method, p, l, rest, q, body, now):
    if not rest or (len(rest) == 1 and rest[0].startswith(":")):
        if method == "POST":
            aid = q.get("backupPlanAssociationId") or ""
            if not ID_RE.match(aid):
                raise _bad("Invalid backupPlanAssociationId %r." % aid)
            name = "projects/%s/locations/%s/backupPlanAssociations/%s" % (p, l, aid)
            if name in d["assocs"]:
                raise _E(409, "ALREADY_EXISTS", "Resource %s already exists." % name)
            plan = d["plans"].get(body.get("backupPlan") or "")
            if plan is None:
                raise _nf("BackupPlan", body.get("backupPlan") or "")
            rt = body.get("resourceType") or plan["resourceType"]
            if rt != plan["resourceType"]:
                raise _bad("resourceType %s does not match the plan's %s." % (rt, plan["resourceType"]))
            rp, zone, rname, rrec = _res_ref(store, p, rt, body.get("resource"))
            if G._region_of(zone) != l and l != zone:
                raise _bad("The resource is in %s but the association location is %s; they must be in the same region." % (G._region_of(zone), l))
            rfull = body["resource"].split("compute/v1/", 1)[-1] if "compute/v1/" in body["resource"] else body["resource"]
            if any(a["resource"] == rfull for a in d["assocs"].values()):
                raise _E(409, "ALREADY_EXISTS", "%s is already protected by a backup plan; remove that association first." % rfull)
            vault = plan["backupVault"]
            dsname = "%s/dataSources/%s" % (vault, "ds-" + _short(rname, 40) + "-" + _uid(rfull)[:6])
            now_s = _now_iso(now)
            if dsname not in d["datasources"]:
                props = {"name": rname, "description": rrec.get("description", "")}
                if rt.endswith("Instance"):
                    props.update({"machineType": G._last(rrec.get("machineType", "")), "totalDiskCount": str(len(rrec.get("disks", [])))})
                d["datasources"][dsname] = {"name": dsname, "state": "ACTIVE", "createTime": now_s, "updateTime": now_s, "_vault": vault,
                                            "dataSourceGcpResource": {"gcpResourcename": "//compute.googleapis.com/" + rfull, "location": l, "type": rt,
                                                                      "computeInstanceDatasourceProperties" if rt.endswith("Instance") else "diskDatasourceProperties": props}}
            rec = {"name": name, "resourceType": rt, "resource": rfull, "backupPlan": plan["name"], "state": "ACTIVE", "createTime": now_s, "updateTime": now_s,
                   "dataSource": dsname, "rulesConfigInfo": [{"ruleId": r["ruleId"], "lastBackupState": "FIRST_BACKUP_PENDING"} for r in plan["backupRules"]]}
            d["assocs"][name] = rec
            for r in plan["backupRules"]:     # baseline per rule: nothing fires on create
                d["tick"].setdefault(name + "#" + r["ruleId"], now or time.time())
            return _wrap(p, l, "create", name, rec, "BackupPlanAssociation")
        if method == "GET":
            return {"backupPlanAssociations": [dict(v) for n, v in sorted(d["assocs"].items()) if n.startswith("projects/%s/locations/%s/" % (p, l)) or l == "-"]}
        raise _E(405, "UNIMPLEMENTED", "Method not allowed")
    last, verb = rest[0], ""
    if ":" in last:
        last, verb = last.split(":", 1)
    name = "projects/%s/locations/%s/backupPlanAssociations/%s" % (p, l, last)
    rec = d["assocs"].get(name)
    if rec is None:
        raise _nf("BackupPlanAssociation", name)
    if verb == "triggerBackup" and method == "POST":
        plan = d["plans"][rec["backupPlan"]]
        rule = next((r for r in plan["backupRules"] if r["ruleId"] == body.get("ruleId")), None)
        if rule is None:
            raise _bad("ruleId %r is not a rule of plan %s." % (body.get("ruleId"), plan["name"]))
        b = _take_backup(store, d, rec, plan, rule, "ON_DEMAND", now)
        return _wrap(p, l, "triggerBackup", name, _backup_view(b), "Backup")
    if verb:
        raise _E(404, "NOT_FOUND", "Unknown method :%s" % verb)
    if method == "GET":
        return dict(rec)
    if method == "DELETE":
        del d["assocs"][name]
        for k in [k for k in d["tick"] if k.startswith(name + "#")]:
            d["tick"].pop(k, None)
        return _wrap(p, l, "delete", name, {}, "OperationMetadata")
    raise _E(405, "UNIMPLEMENTED", "Method not allowed")


def _take_backup(store, d, assoc, plan, rule, btype, now=None):
    """A real backup: one Compute snapshot per disk, recorded under the vault's data source."""
    rp = assoc["resource"].split("/")
    project, zone, kind, rname = rp[1], rp[3], rp[4], rp[5]
    vault = d["vaults"][plan["backupVault"]]
    d["seq"] += 1
    bid = "backup-%s-%04d" % (datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") if not now else datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y%m%d%H%M%S"), d["seq"])
    ds = d["datasources"][assoc["dataSource"]]
    if kind == "instances":
        inst = store.instances.get(assoc["resource"])
        if inst is None:
            raise _pre("Instance %s no longer exists." % assoc["resource"])
        disk_names = [G._last(x["source"]) for x in inst.get("disks", [])]
    else:
        disk_names = [rname]
    snaps, size, disks_meta = [], 0, []
    created_at = datetime.fromtimestamp(now, tz=timezone.utc) if now else datetime.now(timezone.utc)
    for i, dn in enumerate(disk_names):
        disk = store.disks.get("projects/%s/zones/%s/disks/%s" % (project, zone, dn))
        if disk is None:
            continue
        sname = ("bdr-%s-%d-%s" % (_short(dn, 20), d["seq"], created_at.strftime("%H%M%S")))[:63].rstrip("-")
        G.create_snapshot(store, project, zone, dn, {"name": sname, "labels": {"vyomi-backupdr": _short(vault["name"].rsplit("/", 1)[-1], 40)}})
        store.snapshots["projects/%s/global/snapshots/%s" % (project, sname)]["creationTimestamp"] = _iso(created_at)
        snaps.append(sname)
        size += int(store.snapshots["projects/%s/global/snapshots/%s" % (project, sname)].get("storageBytes") or 0)
        disks_meta.append({"name": dn, "boot": bool(next((x for x in (store.instances.get(assoc["resource"], {}).get("disks") or []) if G._last(x["source"]) == dn and x.get("boot")), None)),
                           "sizeGb": disk["sizeGb"], "type": G._last(disk["type"])})
    if not snaps:
        raise _pre("Nothing to back up: the resource has no readable disks.")
    ret = timedelta(days=rule["backupRetentionDays"])
    enforced = timedelta(seconds=_seconds(vault["backupMinimumEnforcedRetentionDuration"], "x"))
    name = "%s/backups/%s" % (ds["name"], bid)
    rec = {"name": name, "createTime": _iso(created_at), "updateTime": _iso(created_at), "labels": {}, "enforcedRetentionEndTime": _iso(created_at + enforced),
           "expireTime": _iso(created_at + ret), "consistencyTime": _iso(created_at), "etag": _uid(name)[:8], "state": "ACTIVE", "backupType": btype,
           "resourceSizeBytes": str(size), "gcpBackupPlanInfo": {"backupPlan": plan["name"], "backupPlanRuleId": rule["ruleId"]},
           "gcpResourcename": "//compute.googleapis.com/" + assoc["resource"],
           "_vault": vault["name"], "_ds": ds["name"], "_project": project, "_zone": zone, "_kind": kind, "_snapshots": snaps, "_disks": disks_meta,
           "_machineType": G._last((store.instances.get(assoc["resource"]) or {}).get("machineType", ""))}
    if kind == "instances":
        rec["computeInstanceBackupProperties"] = {"machineType": rec["_machineType"], "description": (store.instances.get(assoc["resource"]) or {}).get("description", "")}
    else:
        rec["diskBackupProperties"] = {"sizeGb": disks_meta[0]["sizeGb"], "type": disks_meta[0]["type"]}
    d["backups"][name] = rec
    for c in assoc["rulesConfigInfo"]:
        if c["ruleId"] == rule["ruleId"]:
            c["lastBackupState"] = "PASSED"
            c["lastSuccessfulBackupConsistencyTime"] = rec["consistencyTime"]
    assoc["updateTime"] = rec["createTime"]
    return rec


def _restore(store, d, p, l, b, body, now):
    """Restore creates NEW disks from the backup's snapshots (and a new instance for an instance backup)."""
    project = b["_project"]
    if b["_kind"] == "disks":
        env = body.get("diskTargetEnvironment") or {}
        props = body.get("diskRestoreProperties") or {}
        name, zone = props.get("name") or "", env.get("zone") or b["_zone"]
        if not name:
            raise _bad("diskRestoreProperties.name is required.")
        G.insert_disk(store, project, zone, {"name": name, "sizeGb": b["_disks"][0]["sizeGb"], "type": b["_disks"][0]["type"],
                                             "sourceSnapshot": "projects/%s/global/snapshots/%s" % (project, b["_snapshots"][0]),
                                             "labels": {"vyomi-restored-from": "backupdr"}})
        return _wrap(p, l, "restore", b["name"], {"disks": ["projects/%s/zones/%s/disks/%s" % (project, zone, name)]}, "RestoreBackupResponse")
    env = body.get("computeInstanceTargetEnvironment") or {}
    props = body.get("computeInstanceRestoreProperties") or {}
    name, zone = props.get("name") or "", env.get("zone") or b["_zone"]
    if not name:
        raise _bad("computeInstanceRestoreProperties.name is required.")
    if "projects/%s/zones/%s/instances/%s" % (project, zone, name) in store.instances:
        raise _E(409, "ALREADY_EXISTS", "Instance %s already exists; restore creates a new instance." % name)
    disks_in = []
    for i, (sn, meta) in enumerate(zip(b["_snapshots"], b["_disks"])):
        dname = "%s-%s" % (name, _short(meta["name"], 30)) if i else name
        G.insert_disk(store, project, zone, {"name": dname, "sizeGb": meta["sizeGb"], "type": meta["type"],
                                             "sourceSnapshot": "projects/%s/global/snapshots/%s" % (project, sn), "labels": {"vyomi-restored-from": "backupdr"}})
        disks_in.append({"source": "projects/%s/zones/%s/disks/%s" % (project, zone, dname), "boot": meta["boot"] or i == 0, "autoDelete": True})
    G.insert_instance(store, project, zone, {"name": name, "machineType": props.get("machineType") or b["_machineType"] or "e2-medium", "disks": disks_in})
    return _wrap(p, l, "restore", b["name"], {"instance": "projects/%s/zones/%s/instances/%s" % (project, zone, name)}, "RestoreBackupResponse")


# ── scheduler ────────────────────────────────────────────────────────────────
def tick(store, now=None):
    """Fire due plan rules (one run per rule per tick, missed fires coalesce) and expire old backups."""
    d = _x(store)
    if not d["assocs"] and not d["backups"]:
        return 0
    now = time.time() if now is None else now
    tk = SC.Ticker(d["tick"])
    ran = 0
    for aname, a in list(d["assocs"].items()):
        plan = d["plans"].get(a["backupPlan"])
        if plan is None or a["resource"] not in (store.instances if a["resource"].split("/")[4] == "instances" else store.disks):
            continue
        for rule in plan["backupRules"]:
            key = aname + "#" + rule["ruleId"]
            if tk.due(key, _spec(rule), now) and _day_ok(rule, datetime.fromtimestamp(now, tz=timezone.utc)):
                try:
                    _take_backup(store, d, a, plan, rule, "SCHEDULED", now)
                    ran += 1
                except _E:
                    for c in a["rulesConfigInfo"]:
                        if c["ruleId"] == rule["ruleId"]:
                            c["lastBackupState"] = "FAILED"
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
    for b in list(d["backups"].values()):
        if _parse(b["expireTime"]) <= now_dt and _parse(b["enforcedRetentionEndTime"]) <= now_dt:
            _drop_backup(store, d, b, enforce=False)
    return ran


_SEG = {"backupVaults": _vaults, "backupPlans": _plans, "backupPlanAssociations": _assocs}


def dispatch(store, method, path, query=None, headers=None, body=b"", now=None):
    query, method = dict(query or {}), method.upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        return Resp(400, {"error": {"code": 400, "message": "Invalid JSON payload received.", "status": "INVALID_ARGUMENT"}})
    segs = path.split("?", 1)[0].strip("/").split("/")
    try:
        if len(segs) < 6 or segs[0] != "v1" or segs[1] != "projects" or segs[3] != "locations":
            raise _E(404, "NOT_FOUND", "Unknown path: %s" % path)
        project, loc, kind, rest = segs[2], segs[4], segs[5], segs[6:]
        if ":" in kind:     # collection-level verb, e.g. backupPlanAssociations:fetchForResourceType
            kind, verb = kind.split(":", 1)
            rest = [":" + verb] + rest
        fn = _SEG.get(kind)
        if fn is None:
            raise _E(404, "NOT_FOUND", "%s is not simulated by Vyomi Backup and DR." % kind)
        d = _x(store)
        tick(store, now)
        out = fn(store, d, method, project, loc, rest, query, payload, now)
        if method != "GET" and hasattr(store, "persist"):
            try:
                store.persist()
            except Exception:
                pass
        return Resp(200, out)
    except G._E as e:       # surfaced from the Compute core (snapshot / disk / instance create)
        return Resp(e.status, {"error": {"code": e.status, "message": e.message, "status": e.gcp_status}})
    except _E as e:
        return Resp(e.status, {"error": {"code": e.status, "message": e.message, "status": e.gcp_status}})
