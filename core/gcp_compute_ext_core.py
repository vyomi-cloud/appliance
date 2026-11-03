"""GCP Compute Engine **extension** core — substrate-independent, shared by offline + Nano.

Lives inside the Compute Engine v1 REST namespace (`/compute/v1/projects/{p}/...`) and is
hooked in from core/gcp_compute_instances_core.dispatch, so every client that already
reaches the VM core (google-cloud-compute, gcloud, the v4 console) reaches this too. State
lives in `store.ext` (one dict of collections) so both substrates persist it with the rest
of the Compute store.

Resources (Compute v1 shapes):
    regions/{r}/resourcePolicies            instance schedules, snapshot schedules,
                                            disk consistency groups, group placement
    instances/{i}:addResourcePolicies|removeResourcePolicies
    disks/{d}:addResourcePolicies|removeResourcePolicies|startAsyncReplication|stopAsyncReplication
    zones/{z}/instantSnapshots              (+ disks.insert sourceInstantSnapshot)
    zones/{z}/reservations                  (+ resize; consumption by instances.reservationAffinity)
    regions/{r}/nodeTemplates, zones/{z}/nodeGroups (+ addNodes/deleteNodes/setNodeTemplate/
        listNodes), zones/{z}/nodeTypes     (+ instances.scheduling.nodeAffinities placement)
    zones/{z}/storagePools, storagePoolTypes (+ disks.insert storagePool capacity accounting)
    zones/{z}|global|regions/{r} networkEndpointGroups (+ attach/detach/listNetworkEndpoints)
    + Recommender API v1 (`/v1/projects/{p}/locations/{l}/recommenders/{id}/recommendations`)
      computed from LIVE Compute state (no utilisation telemetry, so state-derived only).

Real engines (no canned data): instance schedules start/stop the real instance on cron fire
times, snapshot schedules create real snapshots on hourly/daily/weekly fire times and prune
by retention. A substrate-independent core has no background thread, so the scheduler is
evaluated lazily on every API call (`tick`) and catches up fire times missed in between.

NO fastapi / docker / socket / subprocess imports → loads under Pyodide.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from core import gcp_compute_instances_core as G
from core.gcp_compute_instances_core import _E, _json

try:                                     # IANA time zones for instance schedules (absent → UTC)
    from zoneinfo import ZoneInfo
except Exception:                        # pragma: no cover
    ZoneInfo = None

POLICY_TYPES = ("instanceSchedulePolicy", "snapshotSchedulePolicy", "diskConsistencyGroupPolicy", "groupPlacementPolicy")

NODE_TYPES = {                      # name -> (vCPU, memory MB, description)
    "n1-node-96-624": (96, 638976, "Node type for 96 vCPUs and 624 GB of memory"),
    "n2-node-80-640": (80, 655360, "Node type for 80 vCPUs and 640 GB of memory"),
    "n2d-node-224-896": (224, 917504, "Node type for 224 vCPUs and 896 GB of memory"),
    "c2-node-60-240": (60, 245760, "Node type for 60 vCPUs and 240 GB of memory"),
    "m1-node-96-1433": (96, 1467392, "Node type for 96 vCPUs and 1433 GB of memory"),
}
NODE_AFFINITY_KEY = "compute.googleapis.com/node-group-name"
STORAGE_POOL_TYPES = {
    "hyperdisk-balanced": {"minCapacityGb": 10240, "maxCapacityGb": 1048576, "minIops": 3000, "maxIops": 5120000,
                           "minThroughputMbps": 140, "maxThroughputMbps": 80000},
    "hyperdisk-throughput": {"minCapacityGb": 10240, "maxCapacityGb": 1048576, "minIops": 0, "maxIops": 0,
                             "minThroughputMbps": 10240, "maxThroughputMbps": 614400},
}
NEG_TYPES = {"zonal": ("GCE_VM_IP_PORT", "GCE_VM_IP", "NON_GCP_PRIVATE_IP_PORT"),
             "global": ("INTERNET_IP_PORT", "INTERNET_FQDN_PORT"),
             "regional": ("SERVERLESS", "PRIVATE_SERVICE_CONNECT")}
DISK_PRICE_GB_MONTH = {"pd-standard": 0.04, "pd-balanced": 0.10, "pd-ssd": 0.17, "pd-extreme": 0.125,
                       "hyperdisk-balanced": 0.08, "hyperdisk-throughput": 0.04, "hyperdisk-extreme": 0.125}
REC_STATES = ("ACTIVE", "CLAIMED", "SUCCEEDED", "FAILED", "DISMISSED")
DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
MAX_CATCHUP = 24


# ── plumbing ─────────────────────────────────────────────────────────────────
def _x(store, coll):
    if not hasattr(store, "ext") or store.ext is None:
        store.ext = {}
    return store.ext.setdefault(coll, {})


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse(ts):
    return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _link(tail):
    return G._selflink(tail)


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _nf(what, full):
    return _E(404, "NOT_FOUND", "The resource '%s' was not found." % full)


def _scope_tail(project, scope_kind, scope):
    return "projects/%s/global" % project if scope_kind == "global" else "projects/%s/%s/%s" % (project, scope_kind, scope)


def _full(project, scope_kind, scope, coll, name):
    return "%s/%s/%s" % (_scope_tail(project, scope_kind, scope), coll, name)


def _check_scope(scope_kind, scope):
    if scope_kind == "zones" and scope not in G.ZONE_REGION:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'zone': %r." % scope)
    if scope_kind == "regions" and scope not in G.REGIONS:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'region': %r." % scope)


def _items(store, coll, project, scope_kind, scope):
    pre = _scope_tail(project, scope_kind, scope) + "/%s/" % coll
    return sorted(k for k in _x(store, coll) if k.startswith(pre))


def _op(store, project, scope_kind, scope, op_type, name, full):
    sc = scope if scope_kind in ("zones", "regions") else None
    return G._operation(store, project, sc, op_type, name, _link(full))


def _agg(store, project, coll, key, view):
    out = {}
    pre = "projects/%s/" % project
    for full in sorted(_x(store, coll)):
        if not full.startswith(pre):
            continue
        segs = full.split("/")
        scope = "global" if segs[2] == "global" else "%s/%s" % (segs[2], segs[3])
        out.setdefault(scope, {key: []})[key].append(view(store, project, full))
    return {"kind": "compute#%sAggregatedList" % key[:-1], "id": "projects/%s/aggregated/%s" % (project, key), "items": out}


def _ref(v):
    return G._last(v)


# ── cron / schedule math ─────────────────────────────────────────────────────
def _cron_field(spec, lo, hi):
    out = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
            if step < 1:
                raise ValueError
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = int(part)
            b = hi if step > 1 else a
        if a < lo or b > hi or a > b:
            raise ValueError
        out.update(range(a, b + 1, step))
    return out


def parse_cron(expr):
    f = str(expr or "").split()
    if len(f) != 5:
        raise ValueError("cron needs 5 fields")
    dow = _cron_field(f[4].replace("7", "0") if f[4] == "7" else f[4], 0, 6)
    return (_cron_field(f[0], 0, 59), _cron_field(f[1], 0, 23), _cron_field(f[2], 1, 31),
            _cron_field(f[3], 1, 12), dow)


def _tz(name):
    if name and name not in ("UTC", "Etc/UTC") and ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            return timezone.utc
    return timezone.utc


def _cron_fires(expr, tzname, since, until):
    mi, hr, dom, mon, dow = parse_cron(expr)
    tz = _tz(tzname)
    t = (since + timedelta(minutes=1)).replace(second=0, microsecond=0)
    out = []
    while t <= until and len(out) < 2000:
        lt = t.astimezone(tz)
        if (lt.minute in mi and lt.hour in hr and lt.day in dom and lt.month in mon
                and ((lt.weekday() + 1) % 7) in dow):
            out.append(t)
        t += timedelta(minutes=1)
    return out


def _hhmm(s, default="00:00"):
    m = re.match(r"^(\d{1,2}):(\d{2})$", s or default)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'startTime': %r. Must be HH:MM (UTC)." % s)
    return int(m.group(1)), int(m.group(2))


def snapshot_fires(sched, created, since, until):
    """Fire times of a snapshotSchedulePolicy.schedule in (since, until], all UTC."""
    out = []
    if "hourlySchedule" in sched:
        h = sched["hourlySchedule"]
        n = int(h.get("hoursInCycle") or 1)
        sh, sm = _hhmm(h.get("startTime"))
        t = (since + timedelta(minutes=1)).replace(minute=sm, second=0, microsecond=0)
        if t < since + timedelta(minutes=1):
            t += timedelta(hours=1)
        while t <= until and len(out) < 5000:
            if (t.hour - sh) % n == 0:
                out.append(t)
            t += timedelta(hours=1)
    elif "dailySchedule" in sched:
        d = sched["dailySchedule"]
        n = int(d.get("daysInCycle") or 1)
        sh, sm = _hhmm(d.get("startTime"))
        day = since.replace(hour=0, minute=0, second=0, microsecond=0)
        while day <= until and len(out) < 5000:
            t = day.replace(hour=sh, minute=sm)
            if since < t <= until and (day.date() - created.date()).days % n == 0:
                out.append(t)
            day += timedelta(days=1)
    elif "weeklySchedule" in sched:
        sl = sched["weeklySchedule"].get("dayOfWeekSchedules") or []
        day = since.replace(hour=0, minute=0, second=0, microsecond=0)
        while day <= until and len(out) < 5000:
            for e in sl:
                if DAYS[day.weekday()] == e.get("day"):
                    sh, sm = _hhmm(e.get("startTime"))
                    t = day.replace(hour=sh, minute=sm)
                    if since < t <= until:
                        out.append(t)
            day += timedelta(days=1)
    return sorted(out)


# ── resource policies ────────────────────────────────────────────────────────
def _validate_policy(payload):
    kinds = [k for k in POLICY_TYPES if k in payload]
    if len(kinds) != 1:
        raise _E(400, "INVALID_ARGUMENT", "Exactly one of %s must be specified." % ", ".join(POLICY_TYPES))
    kind = kinds[0]
    body = payload[kind] or {}
    if kind == "instanceSchedulePolicy":
        start = (body.get("vmStartSchedule") or {}).get("schedule")
        stop = (body.get("vmStopSchedule") or {}).get("schedule")
        if not start and not stop:
            raise _E(400, "INVALID_ARGUMENT", "instanceSchedulePolicy needs vmStartSchedule.schedule and/or vmStopSchedule.schedule.")
        for field, c in (("vmStartSchedule.schedule", start), ("vmStopSchedule.schedule", stop)):
            if c:
                try:
                    parse_cron(c)
                except Exception:
                    raise _E(400, "INVALID_ARGUMENT", "Invalid value for field '%s': %r. Must be a valid unix-cron expression." % (field, c))
        if body.get("timeZone") and body["timeZone"] not in ("UTC", "Etc/UTC") and ZoneInfo is not None:
            try:
                ZoneInfo(body["timeZone"])
            except Exception:
                raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'timeZone': %r." % body["timeZone"])
    elif kind == "snapshotSchedulePolicy":
        sched = body.get("schedule") or {}
        given = [k for k in ("hourlySchedule", "dailySchedule", "weeklySchedule") if k in sched]
        if len(given) != 1:
            raise _E(400, "INVALID_ARGUMENT", "snapshotSchedulePolicy.schedule needs exactly one of hourlySchedule, dailySchedule, weeklySchedule.")
        if given[0] == "hourlySchedule":
            n = int(sched["hourlySchedule"].get("hoursInCycle") or 0)
            if n < 1 or n > 23 or 24 % n:
                raise _E(400, "INVALID_ARGUMENT", "hourlySchedule.hoursInCycle must be a factor of 24 between 1 and 23.")
            _hhmm(sched["hourlySchedule"].get("startTime"))
        elif given[0] == "dailySchedule":
            if int(sched["dailySchedule"].get("daysInCycle") or 0) < 1:
                raise _E(400, "INVALID_ARGUMENT", "dailySchedule.daysInCycle must be >= 1.")
            _hhmm(sched["dailySchedule"].get("startTime"))
        else:
            sl = sched["weeklySchedule"].get("dayOfWeekSchedules") or []
            if not sl or any(e.get("day") not in DAYS for e in sl):
                raise _E(400, "INVALID_ARGUMENT", "weeklySchedule.dayOfWeekSchedules needs entries with day MONDAY..SUNDAY.")
            for e in sl:
                _hhmm(e.get("startTime"))
        rp = body.get("retentionPolicy") or {}
        if rp.get("maxRetentionDays") is not None and int(rp["maxRetentionDays"]) < 1:
            raise _E(400, "INVALID_ARGUMENT", "retentionPolicy.maxRetentionDays must be >= 1.")
    return kind


def insert_resource_policy(store, project, region, payload):
    _check_scope("regions", region)
    name = payload.get("name") or ""
    G._check_name(name, "resource.name")
    full = _full(project, "regions", region, "resourcePolicies", name)
    if full in _x(store, "resourcePolicies"):
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    kind = _validate_policy(payload)
    body = json.loads(json.dumps(payload[kind] or {}))
    if kind == "snapshotSchedulePolicy":
        rp = body.setdefault("retentionPolicy", {})
        rp.setdefault("maxRetentionDays", 14)
        rp.setdefault("onSourceDiskDelete", "KEEP_AUTO_SNAPSHOTS")
    if kind == "instanceSchedulePolicy":
        body.setdefault("timeZone", "UTC")
    rec = {"id": G._next_id(store), "kind": "compute#resourcePolicy", "name": name, "description": payload.get("description", ""),
           "region": _link("projects/%s/regions/%s" % (project, region)), "status": "READY", kind: body,
           "creationTimestamp": G._ts(), "selfLink": _link(full), "_region": region, "_kind": kind}
    _x(store, "resourcePolicies")[full] = rec
    return _op(store, project, "regions", region, "insert", name, full)


def policy_attachments(store, full_policy):
    """(instances, disks) currently carrying this resource policy."""
    link = _link(full_policy)
    inst = [n for n, i in store.instances.items() if link in (i.get("resourcePolicies") or [])]
    disks = [n for n, d in store.disks.items() if link in (d.get("resourcePolicies") or [])]
    return inst, disks


def policy_view(store, project, full):
    rec = _x(store, "resourcePolicies")[full]
    v = _public(rec)
    inst, disks = policy_attachments(store, full)
    v["_display"] = {"type": rec["_kind"], "attachedInstances": [G._last(n) for n in inst], "attachedDisks": [G._last(n) for n in disks],
                     "region": rec["_region"]}
    if rec["_kind"] == "instanceSchedulePolicy":
        v["resourceStatus"] = {"instanceSchedulePolicy": {k: rec[k] for k in ("lastRunStartTime", "nextRunStartTime") if rec.get("_" + k) or rec.get(k)}}
        rs = v["resourceStatus"]["instanceSchedulePolicy"]
        for k in ("lastRunStartTime", "nextRunStartTime"):
            if rec.get("_" + k):
                rs[k] = rec["_" + k]
    return v


def _get_policy(store, project, region, name):
    full = _full(project, "regions", region, "resourcePolicies", name)
    if full not in _x(store, "resourcePolicies"):
        raise _nf("resourcePolicy", full)
    return full, _x(store, "resourcePolicies")[full]


def delete_resource_policy(store, project, region, name):
    full, _ = _get_policy(store, project, region, name)
    inst, disks = policy_attachments(store, full)
    if inst or disks:
        raise _E(400, "RESOURCE_IN_USE_BY_ANOTHER_RESOURCE",
                 "The resource_policy resource '%s' is already being used by '%s'." % (full, (inst + disks)[0]))
    del _x(store, "resourcePolicies")[full]
    return _op(store, project, "regions", region, "delete", name, full)


def _policy_from_link(store, project, link):
    pr = G._last(link)
    m = re.search(r"/regions/([^/]+)/resourcePolicies/", str(link))
    if not m:
        raise _E(400, "INVALID_ARGUMENT", "Invalid resource policy reference %r (expected .../regions/{r}/resourcePolicies/{name})." % link)
    return _get_policy(store, project, m.group(1), pr)


def attach_policies(store, project, target_full, target, links, target_kind):
    """Attach resource policies to an instance ('instances') or a disk ('disks')."""
    region = G._region_of(target["_zone"])
    cur = list(target.get("resourcePolicies") or [])
    for link in links:
        pfull, prec = _policy_from_link(store, project, link)
        if prec["_region"] != region:
            raise _E(400, "INVALID_ARGUMENT", "Resource policy '%s' is in region %s but the %s is in %s." % (prec["name"], prec["_region"], target_kind[:-1], region))
        kind = prec["_kind"]
        ok = {"instances": ("instanceSchedulePolicy", "groupPlacementPolicy"),
              "disks": ("snapshotSchedulePolicy", "diskConsistencyGroupPolicy")}[target_kind]
        if kind not in ok:
            raise _E(400, "INVALID_ARGUMENT", "A %s policy can't be attached to a %s." % (kind, target_kind[:-1]))
        if kind == "snapshotSchedulePolicy" and any(
                _policy_from_link(store, project, c)[1]["_kind"] == "snapshotSchedulePolicy" and _link(pfull) != c for c in cur):
            raise _E(400, "INVALID_ARGUMENT", "A disk can have only one snapshot schedule policy attached.")
        sl = _link(pfull)
        if sl not in cur:
            cur.append(sl)
    target["resourcePolicies"] = cur


def policy_verb(store, project, zone, coll, name, verb, payload):
    target_kind = coll
    full = "projects/%s/zones/%s/%s/%s" % (project, zone, coll, name)
    bucket = store.instances if coll == "instances" else store.disks
    if full not in bucket:
        raise _nf(coll, full)
    t = bucket[full]
    links = payload.get("resourcePolicies") or []
    if verb == "addResourcePolicies":
        attach_policies(store, project, full, t, links, target_kind)
    else:
        drop = {_link(_policy_from_link(store, project, l)[0]) for l in links}
        t["resourcePolicies"] = [l for l in (t.get("resourcePolicies") or []) if l not in drop]
    return G._operation(store, project, zone, verb, name, _link(full))


# ── scheduler engine ─────────────────────────────────────────────────────────
def tick(store, now=None):
    """Run due instance-schedule start/stop and snapshot-schedule fires since the last tick,
    then prune snapshots by retention. Idempotent; cheap when nothing is due."""
    pols = _x(store, "resourcePolicies")
    if not pols:
        return
    now = now or _now()
    st = _x(store, "sched")
    last = _parse(st["lastTick"]) if st.get("lastTick") else now
    st["lastTick"] = _iso(now)
    since = max(last, now - timedelta(days=7))
    for full, pol in list(pols.items()):
        kind = pol["_kind"]
        project = full.split("/")[1]
        inst, disks = policy_attachments(store, full)
        body = pol[kind]
        if kind == "instanceSchedulePolicy":
            tzn = body.get("timeZone")
            events = []
            for key, act in (("vmStartSchedule", "start"), ("vmStopSchedule", "stop")):
                c = (body.get(key) or {}).get("schedule")
                if c:
                    events += [(t, act) for t in _cron_fires(c, tzn, since, now)]
            events.sort()
            if events:
                t_last, act = events[-1]
                pol["_lastRunStartTime"] = _iso(t_last)
                for n in inst:
                    ins = store.instances[n]
                    zone = ins["_zone"]
                    try:
                        if act == "start" and ins["status"] in (G.TERMINATED, G.SUSPENDED):
                            G.set_instance_status(store, project, zone, ins["name"], "start" if ins["status"] == G.TERMINATED else "resume")
                        elif act == "stop" and ins["status"] == G.RUNNING:
                            G.set_instance_status(store, project, zone, ins["name"], "stop")
                    except _E:
                        pass
            nxt = []
            for key in ("vmStartSchedule", "vmStopSchedule"):
                c = (body.get(key) or {}).get("schedule")
                if c:
                    f = _cron_fires(c, tzn, now, now + timedelta(days=8))
                    if f:
                        nxt.append(f[0])
            if nxt:
                pol["_nextRunStartTime"] = _iso(min(nxt))
        elif kind == "snapshotSchedulePolicy":
            created = _parse(pol["creationTimestamp"])
            fires = snapshot_fires(body["schedule"], created, max(since, created), now)[-MAX_CATCHUP:]
            props = body.get("snapshotProperties") or {}
            for dn in disks:
                disk = store.disks[dn]
                for t in fires:
                    sname = ("%s-%s-%s" % (pol["name"], disk["name"], t.strftime("%Y%m%d-%H%M%S")))[:63].rstrip("-")
                    if "projects/%s/global/snapshots/%s" % (project, sname) in store.snapshots:
                        continue
                    try:
                        G.create_snapshot(store, project, disk["_zone"], disk["name"], {"name": sname, "labels": props.get("labels") or {}})
                    except _E:
                        continue
                    s = store.snapshots["projects/%s/global/snapshots/%s" % (project, sname)]
                    s.update({"autoCreated": True, "sourceSnapshotSchedulePolicy": _link(full),
                              "creationTimestamp": _iso(t)})
                    if props.get("storageLocations"):
                        s["storageLocations"] = list(props["storageLocations"])
            _prune(store, full, pol, now)


def _prune(store, pfull, pol, now):
    rp = pol["snapshotSchedulePolicy"].get("retentionPolicy") or {}
    days = int(rp.get("maxRetentionDays") or 14)
    keep_orphans = rp.get("onSourceDiskDelete", "KEEP_AUTO_SNAPSHOTS") == "KEEP_AUTO_SNAPSHOTS"
    link = _link(pfull)
    for n, s in list(store.snapshots.items()):
        if s.get("sourceSnapshotSchedulePolicy") != link:
            continue
        disk_gone = G._last(s.get("sourceDisk")) not in {d["name"] for d in store.disks.values()}
        if disk_gone and keep_orphans:
            continue
        if now - _parse(s["creationTimestamp"]) > timedelta(days=days):
            del store.snapshots[n]


# ── instant snapshots ────────────────────────────────────────────────────────
def insert_instant_snapshot(store, project, zone, payload):
    _check_scope("zones", zone)
    name = payload.get("name") or ""
    G._check_name(name, "resource.name")
    full = _full(project, "zones", zone, "instantSnapshots", name)
    if full in _x(store, "instantSnapshots"):
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    src = payload.get("sourceDisk") or ""
    if not src:
        raise _E(400, "INVALID_ARGUMENT", "Required field 'sourceDisk' not specified.")
    dfull = "projects/%s/zones/%s/disks/%s" % (project, zone, G._last(src))
    if dfull not in store.disks:
        raise _E(404, "NOT_FOUND", "The resource '%s' was not found." % dfull)
    d = store.disks[dfull]
    rec = {"id": G._next_id(store), "kind": "compute#instantSnapshot", "name": name, "description": payload.get("description", ""),
           "status": "READY", "sourceDisk": _link(dfull), "sourceDiskId": d["id"], "diskSizeGb": d["sizeGb"],
           "zone": _link("projects/%s/zones/%s" % (project, zone)), "architecture": d.get("architecture", "X86_64"),
           "labels": payload.get("labels") or {}, "creationTimestamp": G._ts(), "selfLink": _link(full), "_zone": zone}
    _x(store, "instantSnapshots")[full] = rec
    return _op(store, project, "zones", zone, "insert", name, full)


def instant_snapshot_view(store, project, full):
    v = _public(_x(store, "instantSnapshots")[full])
    v["_display"] = {"zone": _x(store, "instantSnapshots")[full]["_zone"], "sourceDiskName": G._last(v["sourceDisk"])}
    return v


def delete_instant_snapshot(store, project, zone, name):
    full = _full(project, "zones", zone, "instantSnapshots", name)
    if full not in _x(store, "instantSnapshots"):
        raise _nf("instantSnapshot", full)
    del _x(store, "instantSnapshots")[full]
    return _op(store, project, "zones", zone, "delete", name, full)


# ── disk hooks (insert_disk) + async replication ─────────────────────────────
def prepare_disk_payload(store, project, zone, payload):
    """Called by insert_disk before the record is made: resolve instant-snapshot / storage-pool
    sources, enforcing the real constraints. Returns the (possibly augmented) payload."""
    payload = dict(payload)
    isn = payload.get("sourceInstantSnapshot")
    if isn:
        ifull = _full(project, "zones", zone, "instantSnapshots", G._last(isn))
        iss = _x(store, "instantSnapshots").get(ifull)
        if not iss:
            raise _E(404, "NOT_FOUND", "The resource '%s' was not found." % ifull)
        if not payload.get("sizeGb"):
            payload["sizeGb"] = iss["diskSizeGb"]
        if int(payload["sizeGb"]) < int(iss["diskSizeGb"]):
            raise _E(400, "INVALID_ARGUMENT", "Requested disk size %sGB is smaller than the instant snapshot size %sGB." % (payload["sizeGb"], iss["diskSizeGb"]))
    pool = payload.get("storagePool")
    if pool:
        pfull = _full(project, "zones", zone, "storagePools", G._last(pool))
        prec = _x(store, "storagePools").get(pfull)
        if not prec:
            raise _E(404, "NOT_FOUND", "The resource '%s' was not found." % pfull)
        dtype = G._last(payload.get("type") or G.DEFAULT_DISK_TYPE)
        if dtype != G._last(prec["storagePoolType"]):
            raise _E(400, "INVALID_ARGUMENT", "Disk type %r does not match the storage pool type %r." % (dtype, G._last(prec["storagePoolType"])))
        used, limit = _pool_usage(store, pfull)
        want = int(payload.get("sizeGb") or G.DEFAULT_DISK_GB)
        if used + want > limit:
            raise _E(400, "QUOTA_EXCEEDED", "Disk size %dGB exceeds the free provisioned capacity of storage pool '%s' (%d of %d GB used)." % (want, prec["name"], used, limit))
    return payload


def finish_disk_insert(store, project, zone, name, payload):
    full = "projects/%s/zones/%s/disks/%s" % (project, zone, name)
    d = store.disks[full]
    if payload.get("sourceInstantSnapshot"):
        d["sourceInstantSnapshot"] = _link(_full(project, "zones", zone, "instantSnapshots", G._last(payload["sourceInstantSnapshot"])))
    if payload.get("storagePool"):
        d["storagePool"] = _link(_full(project, "zones", zone, "storagePools", G._last(payload["storagePool"])))
    for k in ("provisionedIops", "provisionedThroughput"):
        if payload.get(k):
            d[k] = str(payload[k])
    if payload.get("resourcePolicies"):
        try:
            attach_policies(store, project, full, d, payload["resourcePolicies"], "disks")
        except _E:
            del store.disks[full]
            raise


def start_async_replication(store, project, zone, name, payload):
    full = "projects/%s/zones/%s/disks/%s" % (project, zone, name)
    d = store.disks.get(full)
    if not d:
        raise _nf("disk", full)
    sec = (payload.get("asyncSecondaryDisk") or "")
    if not sec:
        raise _E(400, "INVALID_ARGUMENT", "Required field 'asyncSecondaryDisk' not specified.")
    m = re.search(r"/(zones|regions)/([^/]+)/disks/([^/]+)$", sec)
    if not m or m.group(1) != "zones":
        raise _E(400, "INVALID_ARGUMENT", "asyncSecondaryDisk must be projects/{p}/zones/{z}/disks/{d}.")
    szone, sname = m.group(2), m.group(3)
    sfull = "projects/%s/zones/%s/disks/%s" % (project, szone, sname)
    s = store.disks.get(sfull)
    if not s:
        raise _E(404, "NOT_FOUND", "The resource '%s' was not found." % sfull)
    if sfull == full:
        raise _E(400, "INVALID_ARGUMENT", "A disk can't replicate to itself.")
    if G._region_of(szone) == G._region_of(zone):
        raise _E(400, "INVALID_ARGUMENT", "The secondary disk must be in a different region than the primary (%s)." % G._region_of(zone))
    if d.get("asyncPrimaryDisk") or d.get("asyncSecondaryDisks"):
        raise _E(400, "FAILED_PRECONDITION", "Disk '%s' is already part of an async replication pair." % name)
    if s.get("users"):
        raise _E(400, "FAILED_PRECONDITION", "The secondary disk '%s' must not be attached to an instance." % sname)
    if s.get("asyncPrimaryDisk") or s.get("asyncSecondaryDisks"):
        raise _E(400, "FAILED_PRECONDITION", "Disk '%s' is already part of an async replication pair." % sname)
    if int(s["sizeGb"]) < int(d["sizeGb"]):
        raise _E(400, "INVALID_ARGUMENT", "The secondary disk must be at least %s GB." % d["sizeGb"])
    now = G._ts()
    d["asyncSecondaryDisks"] = {sname: {"asyncReplicationDisk": {"disk": _link(sfull), "diskId": s["id"]}}}
    d["resourceStatus"] = {"asyncSecondaryDisks": {sname: {"state": "ACTIVE"}}}
    s["asyncPrimaryDisk"] = {"disk": _link(full), "diskId": d["id"]}
    s["resourceStatus"] = {"asyncPrimaryDisk": {"state": "ACTIVE"}}
    d["_replSince"] = s["_replSince"] = now
    return G._operation(store, project, zone, "startAsyncReplication", name, _link(full))


def stop_async_replication(store, project, zone, name, payload):
    """Stop the pair containing this disk (primary or secondary)."""
    full = "projects/%s/zones/%s/disks/%s" % (project, zone, name)
    d = store.disks.get(full)
    if not d:
        raise _nf("disk", full)
    if d.get("asyncPrimaryDisk"):
        pfull = d["asyncPrimaryDisk"]["disk"].split("/compute/v1/", 1)[-1]
        p = store.disks.get(pfull)
        if p:
            p.pop("asyncSecondaryDisks", None)
            p.pop("resourceStatus", None)
        d.pop("asyncPrimaryDisk", None)
        d.pop("resourceStatus", None)
    elif d.get("asyncSecondaryDisks"):
        for sn, v in list(d["asyncSecondaryDisks"].items()):
            sfull = v["asyncReplicationDisk"]["disk"].split("/compute/v1/", 1)[-1]
            s = store.disks.get(sfull)
            if s:
                s.pop("asyncPrimaryDisk", None)
                s.pop("resourceStatus", None)
        d.pop("asyncSecondaryDisks", None)
        d.pop("resourceStatus", None)
    else:
        raise _E(400, "FAILED_PRECONDITION", "Disk '%s' is not part of an async replication pair." % name)
    return G._operation(store, project, zone, "stopAsyncReplication", name, _link(full))


def replication_pairs(store, project):
    out = []
    for n, d in sorted(store.disks.items()):
        if n.startswith("projects/%s/" % project) and d.get("asyncSecondaryDisks"):
            for sn, v in d["asyncSecondaryDisks"].items():
                sfull = v["asyncReplicationDisk"]["disk"].split("/compute/v1/", 1)[-1]
                s = store.disks.get(sfull)
                out.append({"primary": G._last(n), "primaryZone": d["_zone"], "secondary": sn, "secondaryZone": s["_zone"] if s else None,
                            "state": "ACTIVE" if s else "STOPPED", "sizeGb": d["sizeGb"], "since": d.get("_replSince")})
    return out


# ── reservations ─────────────────────────────────────────────────────────────
def _consumers(store, project, zone):
    """reservation full-name -> [instance names] (stable first-fit, capped by count)."""
    res = _x(store, "reservations")
    names = sorted(k for k in res if k.startswith("projects/%s/zones/%s/reservations/" % (project, zone)))
    out = {n: [] for n in names}
    for iname, ins in sorted(store.instances.items()):
        if not iname.startswith("projects/%s/zones/%s/instances/" % (project, zone)) or ins["status"] in (G.TERMINATED, G.SUSPENDED, G.STOPPING):
            continue
        ra = ins.get("reservationAffinity") or {}
        typ = ra.get("consumeReservationType") or "ANY_RESERVATION"
        if typ == "NO_RESERVATION":
            continue
        mt = G._last(ins["machineType"])
        for rn in names:
            r = res[rn]
            sr = r["specificReservation"]
            if G._last(sr["instanceProperties"]["machineType"]) != mt or len(out[rn]) >= int(sr["count"]):
                continue
            if typ == "SPECIFIC_RESERVATION" and G._last(rn) not in [G._last(v) for v in ra.get("values", [])]:
                continue
            if typ == "ANY_RESERVATION" and r.get("specificReservationRequired"):
                continue
            out[rn].append(ins["name"])
            break
    return out


def insert_reservation(store, project, zone, payload):
    _check_scope("zones", zone)
    name = payload.get("name") or ""
    G._check_name(name, "resource.name")
    full = _full(project, "zones", zone, "reservations", name)
    if full in _x(store, "reservations"):
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    sr = payload.get("specificReservation") or {}
    props = sr.get("instanceProperties") or {}
    mt = G._last(props.get("machineType") or "")
    if mt not in G.MACHINE_SHAPES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'specificReservation.instanceProperties.machineType': %r." % mt)
    count = int(sr.get("count") or 0)
    if count < 1:
        raise _E(400, "INVALID_ARGUMENT", "specificReservation.count must be >= 1.")
    rec = {"id": G._next_id(store), "kind": "compute#reservation", "name": name, "description": payload.get("description", ""),
           "zone": _link("projects/%s/zones/%s" % (project, zone)), "status": "READY",
           "specificReservation": {"count": str(count), "inUseCount": "0",
                                   "instanceProperties": dict(props, machineType=mt)},
           "specificReservationRequired": bool(payload.get("specificReservationRequired", False)),
           "creationTimestamp": G._ts(), "selfLink": _link(full), "_zone": zone}
    if payload.get("shareSettings"):
        rec["shareSettings"] = payload["shareSettings"]
    _x(store, "reservations")[full] = rec
    return _op(store, project, "zones", zone, "insert", name, full)


def reservation_view(store, project, full):
    rec = _x(store, "reservations")[full]
    v = json.loads(json.dumps(_public(rec)))
    used = _consumers(store, project, rec["_zone"]).get(full, [])
    v["specificReservation"]["count"] = str(rec["specificReservation"]["count"])
    v["specificReservation"]["inUseCount"] = str(len(used))
    v["_display"] = {"zone": rec["_zone"], "consumers": used, "machineType": rec["specificReservation"]["instanceProperties"]["machineType"]}
    return v


def resize_reservation(store, project, zone, name, payload):
    full = _full(project, "zones", zone, "reservations", name)
    rec = _x(store, "reservations").get(full)
    if not rec:
        raise _nf("reservation", full)
    n = int(payload.get("specificSkuCount") or 0)
    used = len(_consumers(store, project, zone).get(full, []))
    if n < 1 or n < used:
        raise _E(400, "INVALID_ARGUMENT", "specificSkuCount must be >= 1 and not below the %d VMs consuming the reservation." % used)
    rec["specificReservation"]["count"] = str(n)
    return _op(store, project, "zones", zone, "resize", name, full)


def delete_reservation(store, project, zone, name):
    full = _full(project, "zones", zone, "reservations", name)
    if full not in _x(store, "reservations"):
        raise _nf("reservation", full)
    used = _consumers(store, project, zone).get(full, [])
    if used:
        raise _E(400, "RESOURCE_IN_USE_BY_ANOTHER_RESOURCE", "The reservation '%s' is in use by %d VM(s)." % (name, len(used)))
    del _x(store, "reservations")[full]
    return _op(store, project, "zones", zone, "delete", name, full)


# ── sole-tenant nodes ────────────────────────────────────────────────────────
def node_type_view(project, zone, name):
    cpus, mem, desc = NODE_TYPES[name]
    return {"kind": "compute#nodeType", "id": str(int(hashlib.sha1(name.encode()).hexdigest()[:6], 16)), "name": name, "description": desc,
            "cpuPlatform": "Intel Skylake", "guestCpus": cpus, "memoryMb": mem, "localSsdGb": 0, "zone": zone,
            "selfLink": _link("projects/%s/zones/%s/nodeTypes/%s" % (project, zone, name))}


def insert_node_template(store, project, region, payload):
    _check_scope("regions", region)
    name = payload.get("name") or ""
    G._check_name(name, "resource.name")
    full = _full(project, "regions", region, "nodeTemplates", name)
    if full in _x(store, "nodeTemplates"):
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    nt = G._last(payload.get("nodeType") or "")
    if nt not in NODE_TYPES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'nodeType': %r." % nt)
    rec = {"id": G._next_id(store), "kind": "compute#nodeTemplate", "name": name, "description": payload.get("description", ""),
           "nodeType": nt, "nodeAffinityLabels": payload.get("nodeAffinityLabels") or {}, "status": "READY",
           "cpuOvercommitType": payload.get("cpuOvercommitType") or "NONE", "serverBinding": payload.get("serverBinding") or {"type": "RESTART_NODE_ON_ANY_SERVER"},
           "region": _link("projects/%s/regions/%s" % (project, region)), "creationTimestamp": G._ts(), "selfLink": _link(full), "_region": region}
    _x(store, "nodeTemplates")[full] = rec
    return _op(store, project, "regions", region, "insert", name, full)


def node_template_view(store, project, full):
    rec = _x(store, "nodeTemplates")[full]
    v = _public(rec)
    v["_display"] = {"region": rec["_region"], "groups": [g["name"] for g in _x(store, "nodeGroups").values() if G._last(g["nodeTemplate"]) == rec["name"]]}
    return v


def delete_node_template(store, project, region, name):
    full = _full(project, "regions", region, "nodeTemplates", name)
    if full not in _x(store, "nodeTemplates"):
        raise _nf("nodeTemplate", full)
    users = [g["name"] for g in _x(store, "nodeGroups").values() if G._last(g["nodeTemplate"]) == name and G._region_of(g["_zone"]) == region]
    if users:
        raise _E(400, "RESOURCE_IN_USE_BY_ANOTHER_RESOURCE", "The node template '%s' is used by node group '%s'." % (name, users[0]))
    del _x(store, "nodeTemplates")[full]
    return _op(store, project, "regions", region, "delete", name, full)


def _group_template(store, project, zone, link):
    region = G._region_of(zone)
    full = _full(project, "regions", region, "nodeTemplates", G._last(link))
    t = _x(store, "nodeTemplates").get(full)
    if not t:
        raise _E(404, "NOT_FOUND", "The resource '%s' was not found." % full)
    return t


def _node_affinity_groups(ins):
    out = []
    for a in (ins.get("scheduling") or {}).get("nodeAffinities") or []:
        if a.get("key") == NODE_AFFINITY_KEY and a.get("operator", "IN") == "IN":
            out += list(a.get("values") or [])
    return out


def _place(store, project, zone, group, extra=None, size=None):
    """First-fit placement of the group's instances onto its nodes → (nodes, unplaced)."""
    g = group
    cpus, mem, _ = NODE_TYPES[_group_template(store, project, zone, g["nodeTemplate"])["nodeType"]]
    n = g["size"] if size is None else size
    nodes = [{"name": "%s-%d" % (g["name"], i), "nodeType": _group_template(store, project, zone, g["nodeTemplate"])["nodeType"],
              "status": "READY", "instances": [], "_cpu": 0, "_mem": 0} for i in range(n)]
    members = []
    for iname, ins in sorted(store.instances.items()):
        if iname.startswith("projects/%s/zones/%s/instances/" % (project, zone)) and g["name"] in _node_affinity_groups(ins):
            sh = G.MACHINE_SHAPES.get(G._last(ins["machineType"]))
            members.append((ins["name"], sh["vcpu"], sh["ram_mb"]))
    if extra:
        members.append(extra)
    unplaced = []
    for iname, vc, rm in members:
        for nd in nodes:
            if nd["_cpu"] + vc <= cpus and nd["_mem"] + rm <= mem:
                nd["instances"].append(iname)
                nd["_cpu"] += vc
                nd["_mem"] += rm
                break
        else:
            unplaced.append(iname)
    return nodes, unplaced


def insert_node_group(store, project, zone, payload, query):
    _check_scope("zones", zone)
    name = payload.get("name") or ""
    G._check_name(name, "resource.name")
    full = _full(project, "zones", zone, "nodeGroups", name)
    if full in _x(store, "nodeGroups"):
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    if not payload.get("nodeTemplate"):
        raise _E(400, "INVALID_ARGUMENT", "Required field 'nodeTemplate' not specified.")
    t = _group_template(store, project, zone, payload["nodeTemplate"])
    n = int((query or {}).get("initialNodeCount", payload.get("size", 0)) or 0)
    if n < 0 or n > 100:
        raise _E(400, "INVALID_ARGUMENT", "initialNodeCount must be between 0 and 100.")
    rec = {"id": G._next_id(store), "kind": "compute#nodeGroup", "name": name, "description": payload.get("description", ""),
           "nodeTemplate": _link(_full(project, "regions", G._region_of(zone), "nodeTemplates", t["name"])), "size": n, "status": "READY",
           "maintenancePolicy": payload.get("maintenancePolicy") or "DEFAULT", "zone": _link("projects/%s/zones/%s" % (project, zone)),
           "autoscalingPolicy": payload.get("autoscalingPolicy") or {"mode": "OFF"}, "creationTimestamp": G._ts(),
           "selfLink": _link(full), "fingerprint": G._fingerprint(name), "_zone": zone}
    _x(store, "nodeGroups")[full] = rec
    return _op(store, project, "zones", zone, "insert", name, full)


def node_group_view(store, project, full):
    rec = _x(store, "nodeGroups")[full]
    v = _public(rec)
    nodes, _ = _place(store, project, rec["_zone"], rec)
    v["_display"] = {"zone": rec["_zone"], "nodeType": nodes[0]["nodeType"] if nodes else _group_template(store, project, rec["_zone"], rec["nodeTemplate"])["nodeType"],
                     "nodes": [{k: x for k, x in n.items() if not k.startswith("_")} | {"cpuUsed": n["_cpu"], "memoryMbUsed": n["_mem"]} for n in nodes],
                     "instanceCount": sum(len(n["instances"]) for n in nodes), "template": G._last(rec["nodeTemplate"])}
    return v


def _ng(store, project, zone, name):
    full = _full(project, "zones", zone, "nodeGroups", name)
    rec = _x(store, "nodeGroups").get(full)
    if not rec:
        raise _nf("nodeGroup", full)
    return full, rec


def node_group_verb(store, project, zone, name, verb, payload):
    full, g = _ng(store, project, zone, name)
    if verb == "addNodes":
        k = int(payload.get("additionalNodeCount") or 0)
        if k < 1 or g["size"] + k > 100:
            raise _E(400, "INVALID_ARGUMENT", "additionalNodeCount must be >= 1 and the group at most 100 nodes.")
        g["size"] += k
    elif verb == "deleteNodes":
        want = payload.get("nodes") or []
        valid = {"%s-%d" % (name, i) for i in range(g["size"])}
        bad = [n for n in want if n not in valid]
        if bad or not want:
            raise _E(400, "INVALID_ARGUMENT", "Unknown node(s): %s." % ", ".join(bad or ["<none>"]))
        _, unplaced = _place(store, project, zone, g, size=g["size"] - len(want))
        if unplaced:
            raise _E(400, "FAILED_PRECONDITION", "Deleting %d node(s) would leave VM(s) %s without a node." % (len(want), ", ".join(unplaced)))
        g["size"] -= len(want)
    elif verb == "setNodeTemplate":
        t = _group_template(store, project, zone, payload.get("nodeTemplate") or "")
        old = NODE_TYPES[_group_template(store, project, zone, g["nodeTemplate"])["nodeType"]]
        if NODE_TYPES[t["nodeType"]] != old:
            raise _E(400, "FAILED_PRECONDITION", "A node group's template can only change to one with the same node type.")
        g["nodeTemplate"] = _link(_full(project, "regions", G._region_of(zone), "nodeTemplates", t["name"]))
    else:
        raise _E(404, "NOT_FOUND", "Unknown path or method.")
    return _op(store, project, "zones", zone, verb, name, full)


def delete_node_group(store, project, zone, name):
    full, g = _ng(store, project, zone, name)
    nodes, _ = _place(store, project, zone, g)
    if any(n["instances"] for n in nodes):
        raise _E(400, "RESOURCE_IN_USE_BY_ANOTHER_RESOURCE", "The node group '%s' still hosts VM instances." % name)
    del _x(store, "nodeGroups")[full]
    return _op(store, project, "zones", zone, "delete", name, full)


def check_instance_placement(store, project, zone, payload, name):
    """Called before instances.insert: node affinity and reservation references must resolve
    and the VM must fit a sole-tenant node."""
    ra = payload.get("reservationAffinity") or {}
    if ra.get("consumeReservationType") == "SPECIFIC_RESERVATION":
        for v in ra.get("values") or []:
            if _full(project, "zones", zone, "reservations", G._last(v)) not in _x(store, "reservations"):
                raise _E(404, "NOT_FOUND", "The resource 'projects/%s/zones/%s/reservations/%s' was not found." % (project, zone, G._last(v)))
    elif ra.get("consumeReservationType") not in (None, "ANY_RESERVATION", "NO_RESERVATION", "UNSPECIFIED_RESERVATION"):
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'reservationAffinity.consumeReservationType'.")
    mt = G._last(payload.get("machineType") or "e2-medium")
    sh = G.MACHINE_SHAPES.get(mt)
    for gname in _node_affinity_groups({"scheduling": payload.get("scheduling") or {}}):
        gfull = _full(project, "zones", zone, "nodeGroups", gname)
        g = _x(store, "nodeGroups").get(gfull)
        if not g:
            raise _E(404, "NOT_FOUND", "The resource '%s' was not found." % gfull)
        if sh:
            _, unplaced = _place(store, project, zone, g, extra=(name, sh["vcpu"], sh["ram_mb"]))
            if unplaced:
                raise _E(400, "QUOTA_EXCEEDED", "Node group '%s' has no node with %d vCPUs / %d MB free for '%s'." % (gname, sh["vcpu"], sh["ram_mb"], name))


def finish_instance_insert(store, project, zone, name, payload):
    full = "projects/%s/zones/%s/instances/%s" % (project, zone, name)
    ins = store.instances[full]
    if payload.get("reservationAffinity"):
        ins["reservationAffinity"] = payload["reservationAffinity"]
    if payload.get("resourcePolicies"):
        try:
            attach_policies(store, project, full, ins, payload["resourcePolicies"], "instances")
        except _E:
            for d in ins["disks"]:
                dd = store.disks.get("projects/%s/zones/%s/disks/%s" % (project, zone, G._last(d["source"])))
                if dd:
                    dd["users"] = [u for u in dd.get("users", []) if G._last(u) != name]
            del store.instances[full]
            raise


# ── storage pools ────────────────────────────────────────────────────────────
def _pool_usage(store, pfull):
    rec = _x(store, "storagePools")[pfull]
    link = _link(pfull)
    used = sum(int(d["sizeGb"]) for d in store.disks.values() if d.get("storagePool") == link)
    cap = int(rec["poolProvisionedCapacityGb"])
    return used, cap * (5 if rec.get("capacityProvisioningType") == "ADVANCED" else 1)


def insert_storage_pool(store, project, zone, payload):
    _check_scope("zones", zone)
    name = payload.get("name") or ""
    G._check_name(name, "resource.name")
    full = _full(project, "zones", zone, "storagePools", name)
    if full in _x(store, "storagePools"):
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    t = G._last(payload.get("storagePoolType") or "")
    lim = STORAGE_POOL_TYPES.get(t)
    if not lim:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'storagePoolType': %r (one of %s)." % (t, ", ".join(STORAGE_POOL_TYPES)))
    cap = int(payload.get("poolProvisionedCapacityGb") or 0)
    if not lim["minCapacityGb"] <= cap <= lim["maxCapacityGb"]:
        raise _E(400, "INVALID_ARGUMENT", "poolProvisionedCapacityGb must be between %d and %d for %s." % (lim["minCapacityGb"], lim["maxCapacityGb"], t))
    iops = int(payload.get("poolProvisionedIops") or (lim["minIops"] if lim["maxIops"] else 0))
    if lim["maxIops"] and not lim["minIops"] <= iops <= lim["maxIops"]:
        raise _E(400, "INVALID_ARGUMENT", "poolProvisionedIops must be between %d and %d for %s." % (lim["minIops"], lim["maxIops"], t))
    tput = int(payload.get("poolProvisionedThroughput") or lim["minThroughputMbps"])
    if not lim["minThroughputMbps"] <= tput <= lim["maxThroughputMbps"]:
        raise _E(400, "INVALID_ARGUMENT", "poolProvisionedThroughput must be between %d and %d MB/s for %s." % (lim["minThroughputMbps"], lim["maxThroughputMbps"], t))
    rec = {"id": G._next_id(store), "kind": "compute#storagePool", "name": name, "description": payload.get("description", ""),
           "zone": _link("projects/%s/zones/%s" % (project, zone)), "state": "READY", "status": {},
           "storagePoolType": _link("projects/%s/zones/%s/storagePoolTypes/%s" % (project, zone, t)),
           "poolProvisionedCapacityGb": str(cap), "poolProvisionedIops": str(iops), "poolProvisionedThroughput": str(tput),
           "capacityProvisioningType": payload.get("capacityProvisioningType") or "STANDARD",
           "performanceProvisioningType": payload.get("performanceProvisioningType") or "STANDARD",
           "labels": payload.get("labels") or {}, "creationTimestamp": G._ts(), "selfLink": _link(full), "_zone": zone}
    _x(store, "storagePools")[full] = rec
    return _op(store, project, "zones", zone, "insert", name, full)


def storage_pool_view(store, project, full):
    rec = _x(store, "storagePools")[full]
    v = _public(rec)
    used, limit = _pool_usage(store, full)
    link = _link(full)
    disks = [G._last(n) for n, d in store.disks.items() if d.get("storagePool") == link]
    v["status"] = {"diskCount": str(len(disks)), "totalProvisionedDiskCapacityGb": str(used),
                   "maxTotalProvisionedDiskCapacityGb": str(limit), "poolUsedCapacityBytes": "0", "poolUserWrittenBytes": "0"}
    v["_display"] = {"zone": rec["_zone"], "type": G._last(rec["storagePoolType"]), "disks": disks, "usedGb": used, "limitGb": limit}
    return v


def delete_storage_pool(store, project, zone, name):
    full = _full(project, "zones", zone, "storagePools", name)
    if full not in _x(store, "storagePools"):
        raise _nf("storagePool", full)
    if _pool_usage(store, full)[0]:
        raise _E(400, "RESOURCE_IN_USE_BY_ANOTHER_RESOURCE", "The storage pool '%s' still contains disks." % name)
    del _x(store, "storagePools")[full]
    return _op(store, project, "zones", zone, "delete", name, full)


def storage_pool_type_view(project, zone, name):
    lim = STORAGE_POOL_TYPES[name]
    return {"kind": "compute#storagePoolType", "name": name, "description": name + " storage pool", "zone": _link("projects/%s/zones/%s" % (project, zone)),
            "minPoolProvisionedCapacityGb": str(lim["minCapacityGb"]), "maxPoolProvisionedCapacityGb": str(lim["maxCapacityGb"]),
            "minPoolProvisionedIops": str(lim["minIops"]), "maxPoolProvisionedIops": str(lim["maxIops"]),
            "minPoolProvisionedThroughput": str(lim["minThroughputMbps"]), "maxPoolProvisionedThroughput": str(lim["maxThroughputMbps"]),
            "selfLink": _link("projects/%s/zones/%s/storagePoolTypes/%s" % (project, zone, name))}


# ── network endpoint groups ──────────────────────────────────────────────────
def insert_neg(store, project, scope_kind, scope, payload):
    _check_scope(scope_kind, scope)
    kind = {"zones": "zonal", "global": "global", "regions": "regional"}[scope_kind]
    name = payload.get("name") or ""
    G._check_name(name, "resource.name")
    full = _full(project, scope_kind, scope, "networkEndpointGroups", name)
    if full in _x(store, "networkEndpointGroups"):
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    typ = payload.get("networkEndpointType") or NEG_TYPES[kind][0]
    if typ not in NEG_TYPES[kind]:
        raise _E(400, "INVALID_ARGUMENT", "networkEndpointType %r isn't valid for a %s NEG (one of %s)." % (typ, kind, ", ".join(NEG_TYPES[kind])))
    rec = {"id": G._next_id(store), "kind": "compute#networkEndpointGroup", "name": name, "description": payload.get("description", ""),
           "networkEndpointType": typ, "size": 0, "creationTimestamp": G._ts(), "selfLink": _link(full),
           "_scope_kind": scope_kind, "_scope": scope, "_endpoints": []}
    if typ in ("GCE_VM_IP_PORT", "GCE_VM_IP", "NON_GCP_PRIVATE_IP_PORT"):
        project_net = "projects/%s/global/networks/" % project
        rec["network"] = _link(project_net + G._last(payload.get("network") or "default"))
        if typ != "NON_GCP_PRIVATE_IP_PORT" or payload.get("subnetwork"):
            rec["subnetwork"] = _link("projects/%s/regions/%s/subnetworks/%s" % (project, G._region_of(scope), G._last(payload.get("subnetwork") or "default")))
        if typ != "GCE_VM_IP":
            port = int(payload.get("defaultPort") or 0)
            if typ == "GCE_VM_IP_PORT" and not 0 <= port <= 65535:
                raise _E(400, "INVALID_ARGUMENT", "defaultPort must be 0-65535.")
            if port:
                rec["defaultPort"] = port
    if typ.startswith("INTERNET") and payload.get("defaultPort"):
        rec["defaultPort"] = int(payload["defaultPort"])
    if typ == "SERVERLESS":
        cr = payload.get("cloudRun") or {}
        if not (cr.get("service") or cr.get("urlMask") or payload.get("cloudFunction") or payload.get("appEngine")):
            raise _E(400, "INVALID_ARGUMENT", "A serverless NEG needs cloudRun.service, cloudFunction or appEngine.")
        for k in ("cloudRun", "cloudFunction", "appEngine"):
            if payload.get(k):
                rec[k] = payload[k]
    if scope_kind == "zones":
        rec["zone"] = _link("projects/%s/zones/%s" % (project, scope))
    elif scope_kind == "regions":
        rec["region"] = _link("projects/%s/regions/%s" % (project, scope))
    _x(store, "networkEndpointGroups")[full] = rec
    return _op(store, project, scope_kind, scope, "insert", name, full)


def neg_view(store, project, full):
    rec = _x(store, "networkEndpointGroups")[full]
    v = _public(rec)
    v["size"] = len(rec["_endpoints"])
    v["_display"] = {"scope": rec["_scope"], "scopeKind": rec["_scope_kind"], "endpoints": len(rec["_endpoints"])}
    return v


def neg_verb(store, project, scope_kind, scope, name, verb, payload):
    full = _full(project, scope_kind, scope, "networkEndpointGroups", name)
    rec = _x(store, "networkEndpointGroups").get(full)
    if not rec:
        raise _nf("networkEndpointGroup", full)
    typ = rec["networkEndpointType"]
    if verb == "listNetworkEndpoints":
        return _json(200, {"kind": "compute#networkEndpointGroupsListNetworkEndpoints",
                           "items": [{"networkEndpoint": dict(e)} for e in rec["_endpoints"]]})
    eps = payload.get("networkEndpoints") or []
    if not eps:
        raise _E(400, "INVALID_ARGUMENT", "Required field 'networkEndpoints' not specified.")

    def key(e):
        return (G._last(e.get("instance") or ""), e.get("ipAddress") or "", int(e.get("port") or rec.get("defaultPort") or 0), e.get("fqdn") or "")

    if verb == "attachNetworkEndpoints":
        cur = {key(e) for e in rec["_endpoints"]}
        new = []
        for e in eps:
            e = dict(e)
            if typ in ("GCE_VM_IP_PORT", "GCE_VM_IP"):
                ifull = "projects/%s/zones/%s/instances/%s" % (project, scope, G._last(e.get("instance") or ""))
                ins = store.instances.get(ifull)
                if not ins:
                    raise _E(404, "NOT_FOUND", "The resource '%s' was not found." % ifull)
                e["instance"] = _link(ifull)
                e.setdefault("ipAddress", ins.get("_internalIp"))
                nic_nets = [G._last(n.get("network")) for n in ins["networkInterfaces"]]
                if G._last(rec["network"]) not in nic_nets:
                    raise _E(400, "INVALID_ARGUMENT", "Instance '%s' has no network interface in network '%s'." % (ins["name"], G._last(rec["network"])))
            if typ == "INTERNET_FQDN_PORT" and not e.get("fqdn"):
                raise _E(400, "INVALID_ARGUMENT", "An INTERNET_FQDN_PORT endpoint needs 'fqdn'.")
            if typ in ("INTERNET_IP_PORT", "NON_GCP_PRIVATE_IP_PORT") and not e.get("ipAddress"):
                raise _E(400, "INVALID_ARGUMENT", "A %s endpoint needs 'ipAddress'." % typ)
            if typ in ("GCE_VM_IP_PORT", "INTERNET_IP_PORT", "INTERNET_FQDN_PORT", "NON_GCP_PRIVATE_IP_PORT"):
                if not (e.get("port") or rec.get("defaultPort")):
                    raise _E(400, "INVALID_ARGUMENT", "Endpoint needs 'port' (the NEG has no defaultPort).")
                e["port"] = int(e.get("port") or rec["defaultPort"])
            if key(e) in cur or key(e) in {key(n) for n in new}:
                raise _E(400, "ALREADY_EXISTS", "Network endpoint %s is already in the group." % (e.get("ipAddress") or e.get("fqdn")))
            new.append(e)
        if len(rec["_endpoints"]) + len(new) > 10000:
            raise _E(400, "QUOTA_EXCEEDED", "A NEG holds at most 10000 endpoints.")
        rec["_endpoints"].extend(new)
    elif verb == "detachNetworkEndpoints":
        for e in eps:
            k = key(e)
            match = [x for x in rec["_endpoints"] if key(x) == k or (k[0] and key(x)[0] == k[0] and (not k[1] or key(x)[1] == k[1]) and (not k[2] or key(x)[2] == k[2]))]
            if not match:
                raise _E(404, "NOT_FOUND", "Network endpoint %s was not found in the group." % (e.get("ipAddress") or G._last(e.get("instance") or "") or e.get("fqdn")))
            rec["_endpoints"].remove(match[0])
    else:
        raise _E(404, "NOT_FOUND", "Unknown path or method.")
    return _op(store, project, scope_kind, scope, verb, name, full)


def delete_neg(store, project, scope_kind, scope, name):
    full = _full(project, scope_kind, scope, "networkEndpointGroups", name)
    if full not in _x(store, "networkEndpointGroups"):
        raise _nf("networkEndpointGroup", full)
    del _x(store, "networkEndpointGroups")[full]
    return _op(store, project, scope_kind, scope, "delete", name, full)


# ── Recommender API ──────────────────────────────────────────────────────────
RECOMMENDERS = {
    "google.compute.disk.IdleResourceRecommender": "Idle persistent disk recommender",
    "vyomi.compute.disk.BackupCoverageRecommender": "Disk backup coverage recommender",
    "vyomi.compute.reservation.UnusedReservationRecommender": "Unused reservation recommender",
    "vyomi.compute.resourcePolicy.UnattachedPolicyRecommender": "Unattached resource policy recommender",
    "vyomi.compute.nodeGroup.EmptyNodeGroupRecommender": "Empty sole-tenant node group recommender",
}


def _money(monthly):
    units = int(monthly)
    return {"currencyCode": "USD", "units": str(-units), "nanos": -int(round((monthly - units) * 1e9))}


def _rec(project, loc, rid, target_full, subtype, desc, monthly, ops, priority="P3"):
    key = hashlib.sha1((rid + target_full).encode()).hexdigest()[:20]
    name = "projects/%s/locations/%s/recommenders/%s/recommendations/%s" % (project, loc, rid, key)
    impact = ({"category": "COST", "costProjection": {"cost": _money(monthly), "duration": "2592000s"}} if monthly
              else {"category": "MANAGEABILITY"})
    return {"name": name, "description": desc, "recommenderSubtype": subtype, "primaryImpact": impact, "priority": priority,
            "content": {"operationGroups": [{"operations": ops}]}, "stateInfo": {"state": "ACTIVE"},
            "targetResources": ["//compute.googleapis.com/" + target_full], "category_": impact["category"]}


def _remove_op(rtype, target_full):
    return {"action": "remove", "resourceType": rtype, "resource": "//compute.googleapis.com/" + target_full}


def generate_recommendations(store, project, loc, rid):
    out = []
    pre = "projects/%s/zones/%s/" % (project, loc)
    if rid == "google.compute.disk.IdleResourceRecommender":
        snaps = {G._last(s.get("sourceDisk")) for s in store.snapshots.values()}
        for n, d in sorted(store.disks.items()):
            if n.startswith(pre) and not d.get("users") and not d.get("asyncPrimaryDisk"):
                gb = int(d["sizeGb"])
                dt = G._last(d["type"])
                cost = gb * DISK_PRICE_GB_MONTH.get(dt, 0.1)
                snap = d["name"] in snaps
                out.append(_rec(project, loc, rid, n, "DELETE_DISK" if snap else "SNAPSHOT_AND_DELETE_DISK",
                                "Save about $%.2f/month by %s the unattached %s disk '%s' (%d GB)." % (cost, "deleting" if snap else "snapshotting and deleting", dt, d["name"], gb),
                                cost, ([] if snap else [{"action": "add", "resourceType": "compute.googleapis.com/Snapshot", "path": "/", "sourceResource": "//compute.googleapis.com/" + n}])
                                + [_remove_op("compute.googleapis.com/Disk", n)]))
    elif rid == "vyomi.compute.disk.BackupCoverageRecommender":
        snaps = {G._last(s.get("sourceDisk")) for s in store.snapshots.values()}
        for n, d in sorted(store.disks.items()):
            if n.startswith(pre) and d.get("users") and not d.get("resourcePolicies") and d["name"] not in snaps and not d.get("asyncPrimaryDisk"):
                out.append(_rec(project, loc, rid, n, "ATTACH_SNAPSHOT_SCHEDULE",
                                "Protect in-use disk '%s' with a snapshot schedule: it has no snapshot and no resource policy." % d["name"], 0,
                                [{"action": "add", "resourceType": "compute.googleapis.com/ResourcePolicy", "path": "/resourcePolicies/-",
                                  "resource": "//compute.googleapis.com/" + n}]))
    elif rid == "vyomi.compute.reservation.UnusedReservationRecommender":
        cons = _consumers(store, project, loc)
        for n, r in sorted(_x(store, "reservations").items()):
            if n.startswith(pre) and not cons.get(n):
                sr = r["specificReservation"]
                sh = G.MACHINE_SHAPES.get(G._last(sr["instanceProperties"]["machineType"]))
                cost = int(sr["count"]) * (sh["vcpu"] * 0.0335 + sh["ram_mb"] / 1024 * 0.0045) * 730 if sh else 0
                out.append(_rec(project, loc, rid, n, "DELETE_RESERVATION",
                                "Reservation '%s' holds %s x %s but no VM consumes it (~$%.0f/month of reserved capacity)." % (r["name"], sr["count"], sr["instanceProperties"]["machineType"], cost),
                                cost, [_remove_op("compute.googleapis.com/Reservation", n)], "P2"))
    elif rid == "vyomi.compute.resourcePolicy.UnattachedPolicyRecommender":
        region = G._region_of(loc)
        for n, p in sorted(_x(store, "resourcePolicies").items()):
            if n.startswith("projects/%s/regions/%s/" % (project, region)) and not any(policy_attachments(store, n)):
                out.append(_rec(project, loc, rid, n, "DELETE_POLICY",
                                "Resource policy '%s' (%s) isn't attached to any instance or disk." % (p["name"], p["_kind"]), 0,
                                [_remove_op("compute.googleapis.com/ResourcePolicy", n)]))
    elif rid == "vyomi.compute.nodeGroup.EmptyNodeGroupRecommender":
        for n, g in sorted(_x(store, "nodeGroups").items()):
            if n.startswith(pre):
                nodes, _ = _place(store, project, loc, g)
                if g["size"] and not any(nd["instances"] for nd in nodes):
                    nt = NODE_TYPES[_group_template(store, project, loc, g["nodeTemplate"])["nodeType"]]
                    cost = g["size"] * nt[0] * 0.0335 * 730 * 1.1
                    out.append(_rec(project, loc, rid, n, "DELETE_NODE_GROUP",
                                    "Sole-tenant node group '%s' has %d node(s) hosting no VMs (~$%.0f/month)." % (g["name"], g["size"], cost),
                                    cost, [_remove_op("compute.googleapis.com/NodeGroup", n)], "P2"))
    return out


def _decorate(store, rec):
    st = _x(store, "recStates").get(rec["name"])
    rec = dict(rec)
    rec.pop("category_", None)
    if st:
        rec["stateInfo"] = {"state": st["state"], "stateMetadata": st.get("stateMetadata", {})}
    rec["etag"] = '"%s"' % hashlib.sha1((rec["name"] + rec["stateInfo"]["state"]).encode()).hexdigest()[:16]
    rec["lastRefreshTime"] = _x(store, "recStates").get("_refresh", {}).get("t") or G._ts()
    return rec


def recommender_dispatch(store, method, p, query, payload):
    m = re.match(r"^/v1/projects/([^/]+)/locations/([^/]+)/recommenders(?:/([^/:]+)(?:/recommendations(?:/([^/:]+))?)?)?(?::(\w+))?$", p)
    if not m:
        raise _E(404, "NOT_FOUND", "Unknown path: %s" % p)
    project, loc, rid, rkey, verb = m.groups()
    if rid and rid not in RECOMMENDERS:
        raise _E(404, "NOT_FOUND", "Recommender '%s' was not found." % rid)
    if not rid:
        return _json(200, {"recommenders": [{"name": r, "displayName": d} for r, d in RECOMMENDERS.items()]})
    if loc not in G.ZONE_REGION:
        raise _E(400, "INVALID_ARGUMENT", "Compute recommenders are zonal; location must be a zone, got %r." % loc)
    _x(store, "recStates").setdefault("_refresh", {})["t"] = G._ts()
    recs = {r["name"]: r for r in generate_recommendations(store, project, loc, rid)}
    if rkey is None:
        if method != "GET":
            raise _E(405, "UNIMPLEMENTED", "Method not allowed.")
        items = [_decorate(store, r) for r in recs.values()]
        flt = (query or {}).get("filter") or ""
        mm = re.search(r"stateInfo\.state\s*=\s*(\w+)", flt)
        if mm:
            items = [r for r in items if r["stateInfo"]["state"] == mm.group(1)]
        return _json(200, {"recommendations": items} if items else {})
    name = "projects/%s/locations/%s/recommenders/%s/recommendations/%s" % (project, loc, rid, rkey)
    if name not in recs:
        raise _E(404, "NOT_FOUND", "Recommendation '%s' was not found." % name)
    if verb:
        new = {"markClaimed": "CLAIMED", "markSucceeded": "SUCCEEDED", "markFailed": "FAILED", "markDismissed": "DISMISSED"}.get(verb)
        if not new or method != "POST":
            raise _E(404, "NOT_FOUND", "Unknown method %s." % verb)
        cur = _decorate(store, recs[name])
        if payload.get("etag") and payload["etag"] != cur["etag"]:
            raise _E(409, "ABORTED", "etag mismatch: the recommendation changed since it was read.")
        if cur["stateInfo"]["state"] in ("SUCCEEDED", "FAILED", "DISMISSED") and new == "CLAIMED":
            raise _E(400, "FAILED_PRECONDITION", "A %s recommendation can't be claimed." % cur["stateInfo"]["state"])
        _x(store, "recStates")[name] = {"state": new, "stateMetadata": payload.get("stateMetadata") or {}}
        return _json(200, _decorate(store, recs[name]))
    return _json(200, _decorate(store, recs[name]))


# ── dispatch hook ────────────────────────────────────────────────────────────
VIEWS = {"resourcePolicies": ("compute#resourcePolicyList", policy_view), "instantSnapshots": ("compute#instantSnapshotList", instant_snapshot_view),
         "reservations": ("compute#reservationList", reservation_view), "nodeTemplates": ("compute#nodeTemplateList", node_template_view),
         "nodeGroups": ("compute#nodeGroupList", node_group_view), "storagePools": ("compute#storagePoolList", storage_pool_view),
         "networkEndpointGroups": ("compute#networkEndpointGroupList", neg_view)}
SCOPE_OF = {"resourcePolicies": "regions", "instantSnapshots": "zones", "reservations": "zones", "nodeTemplates": "regions",
            "nodeGroups": "zones", "storagePools": "zones"}
VERBS = {"instances": ("addResourcePolicies", "removeResourcePolicies"),
         "disks": ("addResourcePolicies", "removeResourcePolicies", "startAsyncReplication", "stopAsyncReplication"),
         "nodeGroups": ("addNodes", "deleteNodes", "setNodeTemplate", "listNodes"),
         "reservations": ("resize",),
         "networkEndpointGroups": ("attachNetworkEndpoints", "detachNetworkEndpoints", "listNetworkEndpoints")}


def handle(store, method, project, rest, verb, payload, query):
    """Return a ComputeResponse for a path this core owns, or None to fall through."""
    if rest and rest[0] == "aggregated" and len(rest) == 2 and rest[1] in VIEWS and method == "GET":
        return _json(200, _agg(store, project, rest[1], rest[1], VIEWS[rest[1]][1]))
    if rest and rest[0] == "aggregated" and rest[1:] == ["asyncReplications"] and method == "GET":
        return _json(200, {"items": replication_pairs(store, project)})
    if len(rest) < 2 or rest[0] not in ("zones", "regions", "global"):
        return None
    if rest[0] == "global":
        scope_kind, scope, tail = "global", None, rest[1:]
    else:
        scope_kind, scope, tail = rest[0], rest[1], rest[2:]
    if not tail:
        return None
    coll, rest2 = tail[0], tail[1:]
    if not verb and rest2 and coll in VERBS and rest2[-1] in VERBS[coll]:
        if len(rest2) == 2:
            verb, rest2 = rest2[-1], rest2[:-1]
    mine = coll in VIEWS or coll in ("nodeTypes", "storagePoolTypes") or (coll in ("instances", "disks") and verb in VERBS.get(coll, ()))
    if not mine:
        return None
    if coll in ("instances", "disks"):
        if method == "POST" and len(rest2) == 1 and scope_kind == "zones":
            if verb in ("addResourcePolicies", "removeResourcePolicies"):
                return _json(200, policy_verb(store, project, scope, coll, rest2[0], verb, payload))
            if coll == "disks" and verb == "startAsyncReplication":
                return _json(200, start_async_replication(store, project, scope, rest2[0], payload))
            if coll == "disks" and verb == "stopAsyncReplication":
                return _json(200, stop_async_replication(store, project, scope, rest2[0], payload))
        return None
    if coll == "nodeTypes" and scope_kind == "zones" and method == "GET":
        if not rest2:
            return _json(200, {"kind": "compute#nodeTypeList", "items": [node_type_view(project, scope, n) for n in NODE_TYPES]})
        if rest2[0] in NODE_TYPES:
            return _json(200, node_type_view(project, scope, rest2[0]))
        raise _E(404, "NOT_FOUND", "Node type '%s' was not found." % rest2[0])
    if coll == "storagePoolTypes" and scope_kind == "zones" and method == "GET":
        if not rest2:
            return _json(200, {"kind": "compute#storagePoolTypeList", "items": [storage_pool_type_view(project, scope, n) for n in STORAGE_POOL_TYPES]})
        if rest2[0] in STORAGE_POOL_TYPES:
            return _json(200, storage_pool_type_view(project, scope, rest2[0]))
        raise _E(404, "NOT_FOUND", "Storage pool type '%s' was not found." % rest2[0])
    want_scope = SCOPE_OF.get(coll)
    if want_scope and scope_kind != want_scope:
        return None
    if coll == "networkEndpointGroups" and scope_kind not in ("zones", "global", "regions"):
        return None
    kind, view = VIEWS[coll]
    ins = {"resourcePolicies": lambda: insert_resource_policy(store, project, scope, payload),
           "instantSnapshots": lambda: insert_instant_snapshot(store, project, scope, payload),
           "reservations": lambda: insert_reservation(store, project, scope, payload),
           "nodeTemplates": lambda: insert_node_template(store, project, scope, payload),
           "nodeGroups": lambda: insert_node_group(store, project, scope, payload, query),
           "storagePools": lambda: insert_storage_pool(store, project, scope, payload),
           "networkEndpointGroups": lambda: insert_neg(store, project, scope_kind, scope, payload)}[coll]
    dele = {"resourcePolicies": delete_resource_policy, "instantSnapshots": delete_instant_snapshot, "reservations": delete_reservation,
            "nodeTemplates": delete_node_template, "nodeGroups": delete_node_group, "storagePools": delete_storage_pool}
    if not rest2:
        if method == "POST":
            return _json(200, ins())
        if method == "GET":
            return _json(200, {"kind": kind, "items": [view(store, project, f) for f in _items(store, coll, project, scope_kind, scope)]})
        return None
    name = rest2[0]
    full = _full(project, scope_kind, scope, coll, name)
    if verb:
        if method != "POST":
            return None
        if coll == "nodeGroups" and verb == "listNodes":
            _ng(store, project, scope, name)
            return _json(200, {"kind": "compute#nodeGroupsListNodes", "items": view(store, project, full)["_display"]["nodes"]})
        if coll == "nodeGroups":
            return _json(200, node_group_verb(store, project, scope, name, verb, payload))
        if coll == "reservations" and verb == "resize":
            return _json(200, resize_reservation(store, project, scope, name, payload))
        if coll == "networkEndpointGroups":
            return neg_verb(store, project, scope_kind, scope, name, verb, payload) if verb == "listNetworkEndpoints" \
                else _json(200, neg_verb(store, project, scope_kind, scope, name, verb, payload))
        return None
    if method == "GET":
        if full not in _x(store, coll):
            raise _nf(coll, full)
        return _json(200, view(store, project, full))
    if method == "DELETE":
        if coll == "networkEndpointGroups":
            return _json(200, delete_neg(store, project, scope_kind, scope, name))
        return _json(200, dele[coll](store, project, scope, name))
    return None
