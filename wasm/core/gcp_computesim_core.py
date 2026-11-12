# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""GCP Compute: Rollouts (REAL over managed instance groups) and Preview features (config records).

Substrate-independent (stdlib only; Pyodide-loadable). State on the Compute (VM) store `ext` dict, key "computesim".

* Rollouts (compute v1/beta, global): rolloutPlans (waves over zones/regions) + rollouts that roll an instance template
  over the REAL managed instance groups of the Compute store wave by wave, via the MIG engine's PROACTIVE rolling
  replace (new instances created, old deleted; Docker-backed where the appliance runtime is on), with a per-wave health
  check (every member RUNNING) and rollback to the previous template. Google-managed product updates are not in scope.
    /compute/{v1,beta}/projects/{p}/global/rolloutPlans[/{id}]            GET list|get, POST insert, DELETE
    /compute/{v1,beta}/projects/{p}/global/rollouts[/{id}[:advance|:cancel|:resume|:rollback]]   (POST creates a rollout)
* Preview features (compute beta, global): a Vyomi-held catalogue the project can enroll in. Config record only: no
  Vyomi behaviour is gated by it (labelled so).
    /compute/beta/projects/{p}/global/previewFeatures[/{name}]            GET list|get, PATCH {activationStatus}
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone

_LOCK = threading.RLock()
SOURCE = "Dev Simplified"
PATH_RE = re.compile(
    r"^(/compute/(v1|beta)/projects/[^/]+/global/(rolloutPlans|rollouts|previewFeatures)([/:?]|$)"
    r"|/compute/(v1|beta)/projects/[^/]+/global/operations/vyomiop-)")

NOTE_ROLLOUT = "Rolls an instance template over the managed instance groups in this project (rolling replace + health check + rollback). It does not roll out Google-managed product updates."


class Resp:
    media_type = "application/json"

    def __init__(self, status, obj):
        self.status, self.headers = status, {}
        self.body = json.dumps(obj).encode()


class _E(Exception):
    def __init__(self, status, gstatus, msg):
        self.status, self.gstatus, self.message = status, gstatus, msg


def _bad(msg):
    return _E(400, "INVALID_ARGUMENT", msg)


def _nf(msg):
    return _E(404, "NOT_FOUND", msg)


def _iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _state(store):
    if getattr(store, "ext", None) is None:
        store.ext = {}
    return store.ext.setdefault("computesim", {})


def _coll(store, key):
    return _state(store).setdefault(key, {})


def _body(body):
    if not body:
        return {}
    try:
        p = json.loads(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body)
    except Exception:
        raise _bad("Invalid JSON payload received.")
    return p if isinstance(p, dict) else {}


def _stamp(obj):
    obj["vyomiSimulated"] = True
    obj["vyomiSource"] = SOURCE
    return obj


def _ident(v, what):
    v = str(v or "").strip()
    if not re.match(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$", v):
        raise _bad("%s must match [a-z]([-a-z0-9]*[a-z0-9])? (max 63 characters), got %r." % (what, v))
    return v


# ── Compute operations (everything here completes synchronously) ──────────────────────────────────
def _operation(store, project, op_type, target_link):
    ops = _coll(store, "ops")
    oid = "vyomiop-" + uuid.uuid4().hex[:12]
    now = _iso()
    op = {"kind": "compute#operation", "id": str(int(uuid.uuid4().int % 10**18)), "name": oid, "operationType": op_type,
          "targetLink": target_link, "status": "DONE", "progress": 100, "insertTime": now, "startTime": now, "endTime": now,
          "selfLink": "/compute/v1/projects/%s/global/operations/%s" % (project, oid), "vyomiSource": SOURCE}
    ops[oid] = op
    return op


# ══ Rollouts ══════════════════════════════════════════════════════════════════════════════════════
# REAL: a rollout rolls a new instance template out over the Compute store's managed instance groups, wave by wave,
# using the MIG engine (core/gcp_compute_instances_core: PROACTIVE rolling replace creates the new instances and
# deletes the old ones), checks every member of a wave is RUNNING (health check), and rolls the group back to its
# previous template when a wave fails or on :rollback. Where the appliance runs the Docker compute backend those
# instances are real containers. What is not modelled: Google-managed product updates and org/folder-scoped plans.
ZONE_RE = re.compile(r"^[a-z]+-[a-z]+[0-9]+-[a-z]$")
REGION_RE = re.compile(r"^[a-z]+-[a-z]+[0-9]+$")


def _ci():
    from core import gcp_compute_instances_core as ci
    return ci


def _check_plan(p, name):
    scope = str(p.get("locationScope") or "ZONE").upper()
    if scope not in ("ZONE", "REGION"):
        raise _bad("locationScope must be ZONE or REGION.")
    waves = p.get("waves")
    if not isinstance(waves, list) or not waves:
        raise _bad("waves must contain at least one wave.")
    if len(waves) > 10:
        raise _bad("A rollout plan may have at most 10 waves.")
    rx = ZONE_RE if scope == "ZONE" else REGION_RE
    out = []
    for i, w in enumerate(waves, 1):
        if not isinstance(w, dict):
            raise _bad("waves[%d] must be an object." % (i - 1))
        if int(w.get("number") or i) != i:
            raise _bad("Wave numbers must be sequential starting at 1 (waves[%d].number must be %d)." % (i - 1, i))
        locs = []
        for sel in w.get("selectors") or []:
            locs += ((sel or {}).get("locationSelector") or {}).get("includedLocations") or []
        if not locs:
            raise _bad("waves[%d] needs selectors[].locationSelector.includedLocations." % (i - 1))
        for l in locs:
            if not rx.match(str(l)):
                raise _bad("Location %r is not a valid %s for locationScope=%s." % (l, scope.lower(), scope))
        migs = w.get("vyomiManagedInstanceGroups")
        if migs is not None and (not isinstance(migs, list) or not all(isinstance(m, str) and m for m in migs)):
            raise _bad("waves[%d].vyomiManagedInstanceGroups must be a list of managed instance group names." % (i - 1))
        out.append({**w, "number": i, "displayName": str(w.get("displayName") or "Wave %d" % i)})
    return scope, out


def plan_insert(store, project, p):
    name = _ident(p.get("name"), "name")
    plans = _coll(store, "rolloutPlans")
    key = (project, name)
    if "%s/%s" % key in plans:
        raise _E(409, "ALREADY_EXISTS", "The resource 'projects/%s/global/rolloutPlans/%s' already exists." % key)
    scope, waves = _check_plan(p, name)
    plan = _stamp({"kind": "compute#rolloutPlan", "name": name, "description": str(p.get("description") or ""),
                   "locationScope": scope, "waves": waves, "creationTimestamp": _iso(),
                   "selfLink": "/compute/v1/projects/%s/global/rolloutPlans/%s" % key})
    plan.pop("vyomiSimulated")
    plan["vyomiNote"] = NOTE_ROLLOUT
    plans["%s/%s" % key] = plan
    return plan


def _wave_migs(store, project, scope, wave):
    """The REAL managed instance groups a wave covers: MIGs in the selected zones/regions (optionally filtered by name)."""
    ci = _ci()
    locs = []
    for sel in wave.get("selectors") or []:
        locs += ((sel or {}).get("locationSelector") or {}).get("includedLocations") or []
    names = wave.get("vyomiManagedInstanceGroups")
    out = []
    prefix = "projects/%s/zones/" % project
    for full, mgr in sorted(store.instance_group_managers.items()):
        if not full.startswith(prefix):
            continue
        zone = mgr["_zone"]
        if (zone if scope == "ZONE" else ci.ZONE_REGION.get(zone)) not in locs:
            continue
        if names is not None and mgr["name"] not in names:
            continue
        out.append((zone, mgr["name"]))
    return out


def rollout_create(store, project, p):
    ref = str(p.get("rolloutPlan") or "").strip().split("/")[-1]
    plan = _coll(store, "rolloutPlans").get("%s/%s" % (project, ref))
    if not plan:
        raise _bad("rolloutPlan %r does not exist in project %s." % (p.get("rolloutPlan"), project))
    tpl = str(p.get("instanceTemplate") or "").split("/")[-1]
    if not tpl or ("projects/%s/global/instanceTemplates/%s" % (project, tpl)) not in store.instance_templates:
        raise _bad("instanceTemplate %r (the template to roll out) does not exist." % p.get("instanceTemplate"))
    name = _ident(p.get("name") or "rollout-%s-%s" % (ref, uuid.uuid4().hex[:6]), "name")
    rollouts = _coll(store, "rollouts")
    if "%s/%s" % (project, name) in rollouts:
        raise _E(409, "ALREADY_EXISTS", "The resource 'projects/%s/global/rollouts/%s' already exists." % (project, name))
    details = []
    for w in plan["waves"]:
        migs = _wave_migs(store, project, plan["locationScope"], w)
        if not migs:
            raise _bad("Wave %d selects no managed instance group in %s." % (w["number"], project))
        details.append({"waveNumber": w["number"], "displayName": w["displayName"], "status": "PENDING",
                        "managedInstanceGroups": [{"name": n, "zone": z, "status": "PENDING", "previousTemplate": None, "members": []} for z, n in migs]})
    details[0]["status"] = "IN_PROGRESS"
    now = _iso()
    ro = {"kind": "compute#rollout", "name": name, "rolloutPlan": plan["selfLink"], "instanceTemplate": tpl, "state": "RUNNING",
          "currentWaveNumber": 1, "waveDetails": details, "creationTimestamp": now,
          "rollbackOnFailure": p.get("rollbackOnFailure", True) is not False,
          "selfLink": "/compute/v1/projects/%s/global/rollouts/%s" % (project, name), "vyomiNote": NOTE_ROLLOUT,
          "history": [{"time": now, "event": "Rollout created; wave 1 awaiting advance."}]}
    rollouts["%s/%s" % (project, name)] = ro
    return ro


def _ro(store, project, rid):
    ro = _coll(store, "rollouts").get("%s/%s" % (project, rid))
    if not ro:
        raise _nf("The resource 'projects/%s/global/rollouts/%s' was not found." % (project, rid))
    return ro


def _wave(ro):
    return ro["waveDetails"][ro["currentWaveNumber"] - 1]


def _roll_mig(store, project, zone, name, template):
    """Point the MIG at `template` and rolling-replace its members through the real MIG engine."""
    ci = _ci()
    _, mgr = ci._mig(store, project, zone, name)
    orig = mgr.get("updatePolicy")
    try:
        ci.patch_instance_group_manager(store, project, zone, name, {
            "instanceTemplate": template,
            "updatePolicy": {**(orig or {}), "type": "PROACTIVE", "minimalAction": "REPLACE"}})
    finally:
        mgr["updatePolicy"] = orig
    return list(mgr["members"])


def _health(store, project, zone, members):
    bad = []
    for m in members:
        inst = store.instances.get("projects/%s/zones/%s/instances/%s" % (project, zone, m))
        if not inst or inst.get("status") != "RUNNING":
            bad.append("%s=%s" % (m, (inst or {}).get("status", "MISSING")))
    return bad


def _rollback_wave(store, project, w, history, now):
    ci = _ci()
    for g in reversed(w["managedInstanceGroups"]):
        if g["status"] in ("UPDATED", "FAILED") and g["previousTemplate"]:
            try:
                g["members"] = _roll_mig(store, project, g["zone"], g["name"], g["previousTemplate"])
                g["status"] = "ROLLED_BACK"
            except ci._E as e:
                g["status"] = "ROLLBACK_FAILED"
                g["error"] = e.message
    w["status"] = "ROLLED_BACK"
    history.append({"time": now, "event": "Wave %d rolled back to the previous instance template." % w["waveNumber"]})


def _run_wave(store, project, ro):
    ci = _ci()
    w = _wave(ro)
    failed = None
    for g in w["managedInstanceGroups"]:
        try:
            _, mgr = ci._mig(store, project, g["zone"], g["name"])
            g["previousTemplate"] = ci._last(mgr["instanceTemplate"])
            g["members"] = _roll_mig(store, project, g["zone"], g["name"], ro["instanceTemplate"])
            bad = _health(store, project, g["zone"], g["members"])
            if bad:
                raise ci._E(400, "FAILED_PRECONDITION", "Health check failed: members not RUNNING: %s." % ", ".join(bad))
            g["status"] = "UPDATED"
        except ci._E as e:
            g["status"] = "FAILED"
            g["error"] = e.message
            failed = e.message
            break
    return failed


def rollout_verb(store, project, rid, verb):
    ro = _ro(store, project, rid)
    now = _iso()
    st = ro["state"]
    if verb in ("advance", "resume"):
        if (verb == "advance" and st != "RUNNING") or (verb == "resume" and st != "PAUSED"):
            raise _E(412, "FAILED_PRECONDITION", "%s needs a %s rollout (state is %s)." % (verb, "RUNNING" if verb == "advance" else "PAUSED", st))
        w = _wave(ro)
        if verb == "resume":      # retry the paused wave
            ro["state"] = "RUNNING"
            ro.pop("error", None)
        w["status"] = "IN_PROGRESS"
        failed = _run_wave(store, project, ro)
        if failed:
            ro["error"] = {"code": 9, "message": failed}
            if ro["rollbackOnFailure"]:
                _rollback_wave(store, project, w, ro["history"], now)
                ro["state"] = "ROLLED_BACK"
                ro["history"].append({"time": now, "event": "Wave %d failed (%s); rolled back." % (w["waveNumber"], failed)})
            else:
                w["status"] = "FAILED"
                ro["state"] = "PAUSED"
                ro["history"].append({"time": now, "event": "Wave %d failed (%s); rollout paused." % (w["waveNumber"], failed)})
            return ro
        w["status"] = "SUCCEEDED"
        if ro["currentWaveNumber"] == len(ro["waveDetails"]):
            ro["state"] = "SUCCEEDED"
            ro["history"].append({"time": now, "event": "Wave %d succeeded; rollout succeeded." % w["waveNumber"]})
        else:
            ro["currentWaveNumber"] += 1
            _wave(ro)["status"] = "IN_PROGRESS"
            ro["history"].append({"time": now, "event": "Wave %d succeeded; wave %d awaiting advance." % (w["waveNumber"], ro["currentWaveNumber"])})
    elif verb == "rollback":
        if st in ("CANCELLED", "ROLLED_BACK"):
            raise _E(412, "FAILED_PRECONDITION", "A %s rollout cannot be rolled back." % st)
        for w in reversed(ro["waveDetails"]):
            if any(g["status"] in ("UPDATED", "FAILED") for g in w["managedInstanceGroups"]):
                _rollback_wave(store, project, w, ro["history"], now)
        ro["state"] = "ROLLED_BACK"
        ro["history"].append({"time": now, "event": "Rollout rolled back."})
    elif verb == "cancel":
        if st in ("SUCCEEDED", "CANCELLED", "ROLLED_BACK"):
            raise _E(412, "FAILED_PRECONDITION", "A %s rollout cannot be cancelled." % st)
        ro["state"] = "CANCELLED"
        ro["history"].append({"time": now, "event": "Rollout cancelled; groups already updated keep the new template."})
    else:
        raise _nf("Unknown rollout method :%s." % verb)
    return ro


# ══ Preview features ══════════════════════════════════════════════════════════════════════════════
CATALOGUE = [
    ("vyomi-sample-regional-templates", "Sample preview: regional instance templates v2", "PREVIEW"),
    ("vyomi-sample-fast-resume", "Sample preview: faster suspended-VM resume", "PREVIEW"),
    ("vyomi-sample-snapshot-schedules", "Sample preview: cross-region snapshot schedules", "PREVIEW"),
    ("vyomi-sample-placement-hints", "Sample preview: placement hints for managed instance groups", "ALPHA"),
    ("vyomi-sample-disk-insights", "Sample preview: persistent disk insights", "ALPHA"),
    ("vyomi-sample-flex-cud", "Sample preview: flexible committed use discounts view", "PREVIEW"),
]


def _features(store, project):
    state = _coll(store, "previewFeatures").setdefault(project, {})
    for n, d, stage in CATALOGUE:
        state.setdefault(n, {"activationStatus": "DISABLED", "updated": None})
    return state


def _feature_view(project, name, st):
    meta = next(c for c in CATALOGUE if c[0] == name)
    return _stamp({"kind": "compute#previewFeature", "name": name, "activationStatus": st["activationStatus"],
                   "status": {"description": meta[1], "releaseStatus": {"stage": meta[2]}},
                   "selfLink": "/compute/beta/projects/%s/global/previewFeatures/%s" % (project, name),
                   "vyomiCatalogue": True,
                   "vyomiNote": "Config only: a Vyomi-held catalogue. Enrolling records your choice only; it gates no Compute behaviour.",
                   **({"updateTime": st["updated"]} if st["updated"] else {})})


# ══ dispatch ══════════════════════════════════════════════════════════════════════════════════════
def _paged(items, key, query):
    try:
        size, start = int(query.get("maxResults") or query.get("pageSize") or 500), int(query.get("pageToken") or 0)
    except ValueError:
        raise _bad("maxResults/pageToken must be integers.")
    out = {"kind": "compute#%sList" % key[:-1], "items": items[start:start + size], "vyomiSource": SOURCE}
    if start + size < len(items):
        out["nextPageToken"] = str(start + size)
    return out


def _compute(store, method, p, query, payload):
    segs = p.split("/")            # compute v1 projects P global <coll> [id[:verb]]
    project, coll = segs[3], segs[5]
    rest = segs[6:]
    verb = ""
    if rest and ":" in rest[-1]:
        rest[-1], verb = rest[-1].rsplit(":", 1)
    if coll == "operations":
        op = _coll(store, "ops").get(rest[0]) if rest else None
        if method != "GET" or not op:
            raise _nf("The operation was not found.")
        return op
    if coll == "rolloutPlans":
        plans = _coll(store, "rolloutPlans")
        if not rest:
            if method == "GET":
                return _paged(sorted([v for k, v in plans.items() if k.startswith(project + "/")], key=lambda x: x["name"]), "rolloutPlans", query)
            if method == "POST":
                plan = plan_insert(store, project, payload)
                return _operation(store, project, "insert", plan["selfLink"])
        elif len(rest) == 1 and not verb:
            plan = plans.get("%s/%s" % (project, rest[0]))
            if not plan:
                raise _nf("The resource 'projects/%s/global/rolloutPlans/%s' was not found." % (project, rest[0]))
            if method == "GET":
                return plan
            if method == "DELETE":
                for ro in _coll(store, "rollouts").values():
                    if ro["rolloutPlan"] == plan["selfLink"] and ro["state"] in ("RUNNING", "PAUSED"):
                        raise _E(412, "FAILED_PRECONDITION", "Rollout plan is used by active rollout %s." % ro["name"])
                del plans["%s/%s" % (project, rest[0])]
                return _operation(store, project, "delete", plan["selfLink"])
    elif coll == "rollouts":
        ros = _coll(store, "rollouts")
        if not rest:
            if method == "GET":
                items = sorted([v for k, v in ros.items() if k.startswith(project + "/")], key=lambda x: x["name"])
                flt = str(query.get("filter") or "")
                m = re.search(r"state\s*=\s*\"?([A-Z]+)\"?", flt)
                if m:
                    items = [x for x in items if x["state"] == m.group(1)]
                return _paged(items, "rollouts", query)
            if method == "POST":
                ro = rollout_create(store, project, payload)
                return _operation(store, project, "insert", ro["selfLink"])
        elif len(rest) == 1:
            if verb and method == "POST":
                ro = rollout_verb(store, project, rest[0], verb)
                return _operation(store, project, verb, ro["selfLink"])
            if not verb and method == "GET":
                return _ro(store, project, rest[0])
            if not verb and method == "DELETE":
                ro = _ro(store, project, rest[0])
                if ro["state"] in ("RUNNING", "PAUSED"):
                    raise _E(412, "FAILED_PRECONDITION", "Cancel the rollout before deleting it.")
                del ros["%s/%s" % (project, rest[0])]
                return _operation(store, project, "delete", ro["selfLink"])
    elif coll == "previewFeatures":
        feats = _features(store, project)
        if not rest and method == "GET":
            return _paged([_feature_view(project, n, feats[n]) for n, _, _ in CATALOGUE], "previewFeatures", query)
        if len(rest) == 1:
            if rest[0] not in feats:
                raise _nf("The resource 'projects/%s/global/previewFeatures/%s' was not found." % (project, rest[0]))
            if method == "GET":
                return _feature_view(project, rest[0], feats[rest[0]])
            if method in ("PATCH", "PUT"):
                want = payload.get("activationStatus")
                if want not in ("ACTIVATED", "DISABLED"):
                    raise _bad("activationStatus must be ACTIVATED or DISABLED.")
                feats[rest[0]] = {"activationStatus": want, "updated": _iso()}
                return _operation(store, project, "patch", "/compute/beta/projects/%s/global/previewFeatures/%s" % (project, rest[0]))
    raise _E(405, "UNIMPLEMENTED", "Unknown path or method: %s %s" % (method, p))


def dispatch(store, method, path, query=None, headers=None, body=b""):
    query, method = query or {}, method.upper()
    try:
        p = path.split("?", 1)[0].strip("/")
        with _LOCK:
            payload = _body(body) if method in ("POST", "PATCH", "PUT") else {}
            out = _compute(store, method, p, query, payload)
            if method != "GET" and hasattr(store, "persist"):
                store.persist()
            return Resp(200, out)
    except _E as e:
        return Resp(e.status, {"error": {"code": e.status, "message": e.message, "status": e.gstatus}})
