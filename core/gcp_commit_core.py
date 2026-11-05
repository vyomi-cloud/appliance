"""GCP: Committed use discounts (Compute regionCommitments), Migrate to Virtual Machines (vmmigration v1) and Cloud TPU (tpu v2).

Substrate-independent (stdlib only; Pyodide-loadable). State on the Compute (VM) store `ext` dict.

Committed use discounts - /compute/v1/projects/{p}/regions/{r}/commitments (+ aggregated). Resource-based commitments
(type + VCPU/MEMORY) and spend-based (category SPEND_BASED, vyomiSpend.hourlyCommitmentUsd). Utilisation and savings are real
math over the RUNNING instances in the compute store priced with core/cost_model GCP list prices. No money moves; commitments
cannot be cancelled (as on GCP).

Migrate to Virtual Machines - /v1/projects/{p}/locations/{l}/sources[/datacenterConnectors|migratingVms[/replicationCycles|cloneJobs|cutoverJobs]].
State machines are real; clone/cutover create a REAL Compute Engine instance. Replication moves no disk bytes: cycles are records.
There are no source hypervisors: a source's VM inventory is declared in vyomiInventory.

Cloud TPU - /v2/projects/{p}/locations/{zone}/nodes|acceleratorTypes|runtimeVersions. Record-level nodes with a state machine and
quota checks; there is no accelerator, nothing executes.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

from core import gcp_compute_instances_core as G
from core.gcp_compute_instances_core import _E, _json

_LOCK = threading.RLock()


class Resp:
    media_type = "application/json"

    def __init__(self, status, obj):
        self.status, self.headers = status, {}
        self.body = json.dumps(obj).encode()


def _err(e):
    return Resp(e.status, {"error": {"code": e.status, "message": e.message, "status": e.gcp_status}})


def _bad(msg):
    return _E(400, "INVALID_ARGUMENT", msg)


def _nf(what):
    return _E(404, "NOT_FOUND", "Resource '%s' was not found." % what)


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse(ts):
    return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _x(store, coll):
    if getattr(store, "ext", None) is None:
        store.ext = {}
    return store.ext.setdefault(coll, {})


def _pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _body(body):
    if not body:
        return {}
    try:
        p = json.loads(body.decode("utf-8"))
    except Exception:
        raise _bad("Invalid JSON payload received.")
    return p if isinstance(p, dict) else {}


# ═════════════════════════════ committed use discounts ═════════════════════════════
PLANS = {"TWELVE_MONTH": (365, "1 year"), "THIRTY_SIX_MONTH": (1095, "3 years")}
# list-price committed use discount (resource-based, general purpose / compute / memory optimised); spend-based flex 28% / 46%
CUD_TYPES = {"GENERAL_PURPOSE": ("n1", (0.37, 0.55)), "GENERAL_PURPOSE_E2": ("e2", (0.37, 0.55)), "GENERAL_PURPOSE_N2": ("n2", (0.37, 0.55)),
             "GENERAL_PURPOSE_N2D": ("n2d", (0.37, 0.55)), "GENERAL_PURPOSE_T2D": ("t2d", (0.37, 0.55)),
             "COMPUTE_OPTIMIZED": ("c2", (0.37, 0.55)), "MEMORY_OPTIMIZED": ("m1", (0.41, 0.63)), "ACCELERATOR_OPTIMIZED": ("a2", (0.37, 0.55))}
SPEND_DISCOUNT = (0.28, 0.46)
REF_SHAPE = {"n1": "n1-standard-4", "e2": "e2-standard-4", "n2": "n2-standard-4", "n2d": "n2d-standard-4", "t2d": "t2d-standard-4",
             "c2": "c2-standard-4", "m1": "m1-ultramem-40", "a2": "a2-highgpu-1g"}
SPEND_FAMILIES = ("e2", "n1", "n2", "n2d", "t2d", "c2", "c3", "n4")
HOURS_MONTH = 730


def _rate(mt):
    from core import cost_model
    return cost_model.vm_hourly_rate("gcp", mt)


def _family(mt):
    return G._last(mt).split("-")[0]


def _running(store, region):
    out = []
    for k, i in store.instances.items():
        if i.get("status") in ("RUNNING", "PROVISIONING", "STAGING") and G.ZONE_REGION.get(i.get("_zone")) == region:
            sh = G.MACHINE_SHAPES.get(G._last(i["machineType"]))
            if sh:
                out.append((G._last(i["machineType"]), sh))
    return out


def _status(rec):
    return "EXPIRED" if _now() >= _parse(rec["endTimestamp"]) else "ACTIVE"


def _commitment_view(store, rec, usage=None):
    rec["status"] = _status(rec)
    v = _pub(rec)
    v["vyomiUtilisation"] = (usage or utilisation(store, rec["_region"], rec["_project"])).get(rec["name"] if "name" in rec else "", {})
    return v


def utilisation(store, region, project=None):
    """commitment name -> utilisation/savings, computed over the region's running instances (shared pro rata between commitments)."""
    coms = [c for c in _x(store, "commitments").values() if c["_region"] == region and _status(c) == "ACTIVE" and (project is None or c["_project"] == project)]
    running = _running(store, region)
    out = {}
    by_type = {}
    for c in coms:
        by_type.setdefault(c["type"] if c["category"] != "SPEND_BASED" else "__spend", []).append(c)
    for typ, group in by_type.items():
        if typ == "__spend":
            od = 0.0
            for mt, sh in running:
                if _family(mt) in SPEND_FAMILIES:
                    od += _rate(mt)
            total_h = sum(c["_hourly"] for c in group)
            for c in group:
                d = c["_discount"]
                share = c["_hourly"] / total_h if total_h else 0
                covered = min(od * share, c["_hourly"] / (1 - d))
                out[c["name"]] = {"kind": "SPEND_BASED", "hourlyCommitmentUsd": c["_hourly"], "eligibleOnDemandUsdPerHour": round(od * share, 4),
                                  "coveredOnDemandUsdPerHour": round(covered, 4), "utilisationPercent": round(100 * (covered * (1 - d)) / c["_hourly"], 1) if c["_hourly"] else 0.0,
                                  "discountPercent": int(d * 100), "netSavingsUsdPerMonth": round((covered - c["_hourly"]) * HOURS_MONTH, 2),
                                  "committedUsdPerMonth": round(c["_hourly"] * HOURS_MONTH, 2)}
            continue
        fam = CUD_TYPES[typ][0]
        mine = [(mt, sh) for mt, sh in running if _family(mt) == fam]
        used_v = sum(sh["vcpu"] for _, sh in mine)
        used_m = sum(sh["ram_mb"] for _, sh in mine) / 1024.0
        od_per_vcpu = (sum(_rate(mt) for mt, _ in mine) / used_v) if used_v else _rate(REF_SHAPE[fam]) / G.MACHINE_SHAPES.get(REF_SHAPE[fam], {"vcpu": 4})["vcpu"]
        cv = sum(c["_vcpu"] for c in group)
        cm = sum(c["_memGb"] for c in group)
        for c in group:
            d = c["_discount"]
            fv, fm = (c["_vcpu"] / cv if cv else 0), (c["_memGb"] / cm if cm else 0)
            uv, um = min(used_v * fv, c["_vcpu"]), min(used_m * fm, c["_memGb"])
            od_commit = c["_vcpu"] * od_per_vcpu
            cost = od_commit * (1 - d)
            covered = uv * od_per_vcpu
            out[c["name"]] = {"kind": "RESOURCE_BASED", "vcpuCommitted": c["_vcpu"], "vcpuUsed": round(uv, 2),
                              "vcpuUtilisationPercent": round(100 * uv / c["_vcpu"], 1), "memoryGbCommitted": c["_memGb"], "memoryGbUsed": round(um, 2),
                              "memoryUtilisationPercent": round(100 * um / c["_memGb"], 1) if c["_memGb"] else 0.0,
                              "utilisationPercent": round(100 * uv / c["_vcpu"], 1), "discountPercent": int(d * 100),
                              "onDemandUsdPerVcpuHour": round(od_per_vcpu, 5), "committedUsdPerMonth": round(cost * HOURS_MONTH, 2),
                              "coveredOnDemandUsdPerMonth": round(covered * HOURS_MONTH, 2), "netSavingsUsdPerMonth": round((covered - cost) * HOURS_MONTH, 2)}
    return out


def insert_commitment(store, project, region, payload):
    if region not in G.REGIONS:
        raise _nf("projects/%s/regions/%s" % (project, region))
    name = payload.get("name") or ""
    G._check_name(name, "resource.name")
    full = "projects/%s/regions/%s/commitments/%s" % (project, region, name)
    if full in _x(store, "commitments"):
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    plan = payload.get("plan")
    if plan not in PLANS:
        raise _bad("Invalid value for field 'resource.plan': %r. Must be TWELVE_MONTH or THIRTY_SIX_MONTH." % plan)
    pi = 0 if plan == "TWELVE_MONTH" else 1
    cat = payload.get("category") or "MACHINE"
    now = _now()
    rec = {"kind": "compute#commitment", "id": G._next_id(store), "creationTimestamp": G._ts(), "name": name, "description": payload.get("description", ""),
           "region": G._selflink("projects/%s/regions/%s" % (project, region)), "plan": plan, "category": cat, "autoRenew": bool(payload.get("autoRenew")),
           "startTimestamp": _iso(now)[:19] + "Z", "endTimestamp": _iso(now + timedelta(days=PLANS[plan][0]))[:19] + "Z", "status": "ACTIVE",
           "statusMessage": "The commitment is active.", "selfLink": G._selflink(full), "_region": region, "_project": project}
    if cat == "SPEND_BASED":
        h = (payload.get("vyomiSpend") or {}).get("hourlyCommitmentUsd")
        try:
            h = float(h)
        except (TypeError, ValueError):
            raise _bad("vyomiSpend.hourlyCommitmentUsd is required for a spend-based commitment.")
        if h <= 0 or h > 100000:
            raise _bad("vyomiSpend.hourlyCommitmentUsd must be > 0 and <= 100000.")
        rec.update({"type": "SPEND_BASED_FLEX", "vyomiSpend": {"hourlyCommitmentUsd": h}, "_hourly": h, "_discount": SPEND_DISCOUNT[pi], "resources": []})
    elif cat == "MACHINE":
        typ = payload.get("type")
        if typ not in CUD_TYPES:
            raise _bad("Invalid value for field 'resource.type': %r. Valid: %s." % (typ, ", ".join(sorted(CUD_TYPES))))
        amounts = {}
        for r in payload.get("resources") or []:
            t = r.get("type")
            try:
                amt = int(r.get("amount"))
            except (TypeError, ValueError):
                raise _bad("resources.amount must be an integer.")
            if t not in ("VCPU", "MEMORY") or amt < 1 or t in amounts:
                raise _bad("resources must contain one VCPU and one MEMORY entry with positive amounts.")
            amounts[t] = amt
        if set(amounts) != {"VCPU", "MEMORY"}:
            raise _bad("A resource-based commitment needs both VCPU and MEMORY resources.")
        gb = amounts["MEMORY"] / 1024.0                      # MEMORY amount is in MB, as in the Compute API
        if amounts["VCPU"] > 20000:
            raise _bad("VCPU amount exceeds the per-commitment maximum of 20000.")
        if not (0.5 * amounts["VCPU"] <= gb <= 8.0 * amounts["VCPU"]):
            raise _bad("MEMORY must be between 0.5 and 8 GB per committed vCPU for type %s." % typ)
        rec.update({"type": typ, "resources": [{"type": "VCPU", "amount": str(amounts["VCPU"])}, {"type": "MEMORY", "amount": str(amounts["MEMORY"])}],
                    "_vcpu": amounts["VCPU"], "_memGb": gb, "_discount": CUD_TYPES[typ][1][pi]})
    else:
        raise _bad("Invalid value for field 'resource.category': %r (MACHINE or SPEND_BASED; LICENSE commitments are not simulated)." % cat)
    _x(store, "commitments")[full] = rec
    return G._operation(store, project, region, "insert", name, G._selflink(full))


def savings_summary(store, project):
    rows, total = [], 0.0
    for r in G.REGIONS:
        u = utilisation(store, r, project)
        for n, v in u.items():
            rows.append(dict(v, commitment=n, region=r))
            total += v["netSavingsUsdPerMonth"]
    return {"project": project, "commitments": rows, "netSavingsUsdPerMonth": round(total, 2),
            "note": "On-demand = GCP list price from the cost meter (core/cost_model.py) x running instances; nothing is billed."}


def compute_handle(store, method, project, rest, verb, payload, query):
    """Compute API hook: regionCommitments + the Vyomi savings verb. Returns a ComputeResponse or None."""
    try:
        if rest == ["vyomi", "commitmentSavings"] and method == "GET":
            return _json(200, savings_summary(store, project))
        if rest == ["aggregated", "commitments"] and method == "GET":
            items = {}
            for r in G.REGIONS:
                u = utilisation(store, r, project)
                lst = [dict(_pub(c), status=_status(c), vyomiUtilisation=u.get(c["name"], {})) for c in _x(store, "commitments").values()
                       if c["_region"] == r and c["_project"] == project]
                if lst:
                    items["regions/" + r] = {"commitments": lst}
            return _json(200, {"kind": "compute#commitmentAggregatedList", "items": items})
        if len(rest) >= 3 and rest[0] == "regions" and rest[2] == "commitments":
            region, tail = rest[1], rest[3:]
            if not tail and method == "POST":
                return _json(200, insert_commitment(store, project, region, payload))
            if not tail and method == "GET":
                if region not in G.REGIONS:
                    raise _nf("projects/%s/regions/%s" % (project, region))
                u = utilisation(store, region, project)
                lst = [dict(_pub(c), status=_status(c), vyomiUtilisation=u.get(c["name"], {})) for c in _x(store, "commitments").values()
                       if c["_region"] == region and c["_project"] == project]
                return _json(200, {"kind": "compute#commitmentList", "items": sorted(lst, key=lambda c: c["name"])})
            if len(tail) == 1:
                full = "projects/%s/regions/%s/commitments/%s" % (project, region, tail[0])
                c = _x(store, "commitments").get(full)
                if method == "GET":
                    if not c:
                        raise _nf(full)
                    return _json(200, dict(_pub(c), status=_status(c), vyomiUtilisation=utilisation(store, region, project).get(c["name"], {})))
                if method == "DELETE":
                    if not c:
                        raise _nf(full)
                    raise _E(400, "FAILED_PRECONDITION", "Commitments cannot be cancelled before their term ends; '%s' is non-cancellable." % tail[0])
    except _E as e:
        return G._err(e.status, e.gcp_status, e.message)
    return None


# ═════════════════════════════ Migrate to Virtual Machines (vmmigration v1) ═════════════════════════════
FIRST_SYNC_SECONDS = 2.0
CYCLE_SECONDS = 30.0
TERMINAL_CLONE = ("SUCCEEDED", "FAILED", "CANCELLED")


def _op_done(store, project, loc, resp, kind):
    oid = "operation-" + uuid.uuid4().hex[:16]
    name = "projects/%s/locations/%s/operations/%s" % (project, loc, oid)
    op = {"name": name, "metadata": {"@type": "type.googleapis.com/google.cloud.vmmigration.v1.OperationMetadata", "createTime": _iso(_now()),
          "endTime": _iso(_now()), "target": resp.get("name", ""), "verb": kind, "apiVersion": "v1"}, "done": True, "response": dict(resp, **{"@type": "type.googleapis.com/google.cloud.vmmigration.v1.Resource"})}
    _x(store, "vmm_ops")[name] = op
    return op


def _mk_name(project, loc, rest):
    return "projects/%s/locations/%s/%s" % (project, loc, "/".join(rest))


def _src(store, project, loc, sid):
    full = "projects/%s/locations/%s/sources/%s" % (project, loc, sid)
    s = _x(store, "vmm_sources").get(full)
    if not s:
        raise _nf(full)
    return full, s


def _settle_vm(store, m):
    if m["state"] == "FIRST_SYNC" and (_now() - _parse(m["_syncStart"])).total_seconds() >= FIRST_SYNC_SECONDS:
        m["state"] = "ACTIVE"
    if m["state"] in ("ACTIVE", "FIRST_SYNC", "CUTTING_OVER") and m.get("_syncStart"):
        pass


def _cycles(m):
    """Replication cycles derived from the wall clock while replication is running (record-only: no disk bytes move)."""
    if not m.get("_syncStart"):
        return []
    end_ref = _parse(m["_pausedAt"]) if m.get("_pausedAt") else _now()
    elapsed = (end_ref - _parse(m["_syncStart"])).total_seconds() - m.get("_pausedTotal", 0)
    n = 1 + max(0, int((elapsed - FIRST_SYNC_SECONDS) // CYCLE_SECONDS)) if elapsed >= FIRST_SYNC_SECONDS else 1
    out = []
    for i in range(n):
        start = _parse(m["_syncStart"]) + timedelta(seconds=0 if i == 0 else FIRST_SYNC_SECONDS + (i - 1) * CYCLE_SECONDS)
        done = i < n - 1 or elapsed >= (FIRST_SYNC_SECONDS if i == 0 else FIRST_SYNC_SECONDS + i * CYCLE_SECONDS)
        c = {"name": "%s/replicationCycles/%d" % (m["name"], i + 1), "cycleNumber": i + 1, "startTime": _iso(start),
             "state": "SUCCEEDED" if done else "RUNNING", "progressPercent": 100 if done else 50,
             "steps": [{"initializingReplication": {}, "startTime": _iso(start)}, {"replicating": {}}, {"postProcessing": {}}],
             "vyomiNote": "Record only: no disk data is replicated."}
        if done:
            c["endTime"] = _iso(start + timedelta(seconds=FIRST_SYNC_SECONDS if i == 0 else CYCLE_SECONDS))
        out.append(c)
    return out


def _mvm_view(store, m):
    _settle_vm(store, m)
    v = _pub(m)
    cyc = _cycles(m)
    if cyc:
        v["currentSyncInfo"] = cyc[-1] if cyc[-1]["state"] == "RUNNING" else None
        done = [c for c in cyc if c["state"] == "SUCCEEDED"]
        if done:
            v["lastSync"] = {"lastSyncTime": done[-1]["endTime"]}
        if v["currentSyncInfo"] is None:
            v.pop("currentSyncInfo")
    return v


def _pick_shape(cpus, mem_mb):
    for n, s in sorted(G.MACHINE_SHAPES.items(), key=lambda kv: (kv[1]["vcpu"], kv[1]["ram_mb"])):
        if n.startswith("e2-standard") and s["vcpu"] >= cpus and s["ram_mb"] >= mem_mb:
            return n
    return "e2-standard-8"


def _gce_create(store, project, defaults, vm_name, labels):
    zone = defaults.get("zone")
    img = defaults.get("_image") or "projects/debian-cloud/global/images/family/debian-12"
    body = {"name": vm_name, "machineType": "zones/%s/machineTypes/%s" % (zone, defaults["machineType"]),
            "labels": labels, "disks": [{"boot": True, "autoDelete": True, "initializeParams": {"sourceImage": img, "diskSizeGb": str(defaults.get("_diskGb") or 10)}}],
            "networkInterfaces": [{"network": defaults.get("network") or "global/networks/default"}]}
    full = "projects/%s/zones/%s/instances/%s" % (project, zone, vm_name)
    if full in store.instances:
        raise _E(409, "ALREADY_EXISTS", "The Compute Engine instance '%s' already exists." % vm_name)
    G.insert_instance(store, project, zone, body)
    return full


def _vmm(store, method, project, loc, rest, verb, payload, query):
    srcs = _x(store, "vmm_sources")
    if rest[:1] == ["operations"]:
        if len(rest) == 2 and method == "GET":
            op = _x(store, "vmm_ops").get(_mk_name(project, loc, rest))
            if not op:
                raise _nf(_mk_name(project, loc, rest))
            return op
        raise _nf(_mk_name(project, loc, rest))
    if rest[:1] != ["sources"]:
        raise _nf(_mk_name(project, loc, rest))
    pre = "projects/%s/locations/%s/sources/" % (project, loc)
    if len(rest) == 1:
        if method == "GET":
            return {"sources": [_pub(s) for k, s in sorted(srcs.items()) if k.startswith(pre)]}
        if method == "POST":
            sid = query.get("sourceId") or ""
            G._check_name(sid, "sourceId")
            full = pre + sid
            if full in srcs:
                raise _E(409, "ALREADY_EXISTS", "Source %s already exists." % full)
            kinds = [k for k in ("vmware", "aws", "azure") if payload.get(k)]
            if len(kinds) != 1:
                raise _bad("Exactly one of vmware, aws or azure must be set.")
            d = payload[kinds[0]]
            if kinds[0] == "vmware" and not (d.get("vcenterIp") and d.get("username")):
                raise _bad("vmware.vcenterIp and vmware.username are required.")
            if kinds[0] == "aws" and not d.get("awsRegion"):
                raise _bad("aws.awsRegion is required.")
            if kinds[0] == "azure" and not d.get("subscriptionId"):
                raise _bad("azure.subscriptionId is required.")
            inv = payload.get("vyomiInventory") or []
            for v in inv:
                if not (isinstance(v, dict) and v.get("vmId") and v.get("name")):
                    raise _bad("Each vyomiInventory entry needs vmId and name.")
            now = _iso(_now())
            for k in ("password", "secretAccessKey", "clientSecret"):   # never echo credentials
                d.pop(k, None)
            rec = {"name": full, "description": payload.get("description", ""), "labels": payload.get("labels") or {}, "createTime": now, "updateTime": now,
                   kinds[0]: d, "vyomiInventory": inv}
            srcs[full] = rec
            return _op_done(store, project, loc, rec, "create")
    sid = rest[1]
    full, s = _src(store, project, loc, sid)
    if len(rest) == 2:
        if verb == "fetchInventory" and method == "GET":
            return {"updateTime": _iso(_now()), "vmwareVms": {"details": [{"vmId": v["vmId"], "displayName": v["name"], "committedStorageMb": str(int(v.get("diskGb", 10)) * 1024),
                    "cpuCount": int(v.get("cpus", 2)), "memoryMb": int(v.get("memoryMb", 4096)), "osDescription": v.get("osImage", "debian-12")} for v in s["vyomiInventory"]]},
                    "vyomiNote": "Inventory is declared in the source's vyomiInventory; Vyomi has no hypervisor to scan."}
        if method == "GET":
            return _pub(s)
        if method == "PATCH":
            for k in ("description", "labels", "vyomiInventory"):
                if k in payload:
                    s[k] = payload[k]
            s["updateTime"] = _iso(_now())
            return _op_done(store, project, loc, s, "update")
        if method == "DELETE":
            if any(m["_source"] == full for m in _x(store, "vmm_mvms").values()):
                raise _E(400, "FAILED_PRECONDITION", "Source %s still has migrating VMs; delete them first." % sid)
            for k in [k for k in _x(store, "vmm_dcc") if k.startswith(full + "/")]:
                del _x(store, "vmm_dcc")[k]
            del srcs[full]
            return _op_done(store, project, loc, {"name": full}, "delete")
    kind = rest[2]
    if kind == "datacenterConnectors":
        dccs = _x(store, "vmm_dcc")
        if len(rest) == 3:
            if method == "GET":
                return {"datacenterConnectors": [_pub(d) for k, d in sorted(dccs.items()) if k.startswith(full + "/")]}
            if method == "POST":
                if "vmware" not in s:
                    raise _E(400, "FAILED_PRECONDITION", "Datacenter connectors are only used by VMware sources.")
                did = query.get("datacenterConnectorId") or ""
                G._check_name(did, "datacenterConnectorId")
                dn = "%s/datacenterConnectors/%s" % (full, did)
                if dn in dccs:
                    raise _E(409, "ALREADY_EXISTS", "Datacenter connector %s already exists." % dn)
                now = _iso(_now())
                rec = {"name": dn, "createTime": now, "updateTime": now, "registrationId": uuid.uuid4().hex[:16], "state": "ACTIVE",
                       "version": "1.0.0-vyomi", "applianceInfrastructureVersion": "1.0.0-vyomi", "bucket": "vyomi-vmm-%s" % did}
                dccs[dn] = rec
                return _op_done(store, project, loc, rec, "create")
        else:
            dn = "%s/datacenterConnectors/%s" % (full, rest[3])
            d = dccs.get(dn)
            if not d:
                raise _nf(dn)
            if method == "GET":
                return _pub(d)
            if method == "DELETE":
                if any(m["_source"] == full for m in _x(store, "vmm_mvms").values()) and sum(1 for k in dccs if k.startswith(full + "/")) == 1:
                    raise _E(400, "FAILED_PRECONDITION", "The last connector cannot be removed while the source has migrating VMs.")
                del dccs[dn]
                return _op_done(store, project, loc, {"name": dn}, "delete")
            if verb == "upgradeAppliance" and method == "POST":
                d["version"] = d["applianceInfrastructureVersion"] = "1.1.0-vyomi"
                d["updateTime"] = _iso(_now())
                return _op_done(store, project, loc, d, "upgradeAppliance")
    if kind == "migratingVms":
        mvms = _x(store, "vmm_mvms")
        if len(rest) == 3:
            if method == "GET":
                return {"migratingVms": [_mvm_view(store, m) for k, m in sorted(mvms.items()) if k.startswith(full + "/")]}
            if method == "POST":
                mid = query.get("migratingVmId") or ""
                G._check_name(mid, "migratingVmId")
                mn = "%s/migratingVms/%s" % (full, mid)
                if mn in mvms:
                    raise _E(409, "ALREADY_EXISTS", "Migrating VM %s already exists." % mn)
                if "vmware" in s and not any(k.startswith(full + "/") for k in _x(store, "vmm_dcc")):
                    raise _E(400, "FAILED_PRECONDITION", "Source %s has no active datacenter connector." % sid)
                inv = next((v for v in s["vyomiInventory"] if v["vmId"] == payload.get("sourceVmId")), None)
                if not inv:
                    raise _bad("sourceVmId %r was not found in the source's inventory." % payload.get("sourceVmId"))
                if any(m["sourceVmId"] == inv["vmId"] and m["_source"] == full for m in mvms.values()):
                    raise _E(409, "ALREADY_EXISTS", "VM %s is already being migrated." % inv["vmId"])
                td = dict(payload.get("computeEngineTargetDefaults") or {})
                td.setdefault("vmName", inv["name"])
                td.setdefault("targetProject", "projects/%s" % project)
                td.setdefault("zone", "us-central1-a")
                td.setdefault("machineType", _pick_shape(int(inv.get("cpus", 2)), int(inv.get("memoryMb", 4096))))
                if td["zone"] not in G.ZONE_REGION:
                    raise _bad("Invalid zone %r in computeEngineTargetDefaults." % td["zone"])
                if td["machineType"] not in G.MACHINE_SHAPES:
                    raise _bad("Invalid machineType %r in computeEngineTargetDefaults." % td["machineType"])
                G._check_name(td["vmName"], "computeEngineTargetDefaults.vmName")
                td["_image"] = {"ubuntu": "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts"}.get(str(inv.get("osImage", "")).split("-")[0])
                td["_diskGb"] = int(inv.get("diskGb", 10))
                now = _iso(_now())
                m = {"name": mn, "sourceVmId": inv["vmId"], "displayName": payload.get("displayName") or inv["name"], "description": payload.get("description", ""),
                     "policy": payload.get("policy") or {"idleDuration": "7200s", "skipOsAdaptation": False}, "computeEngineTargetDefaults": td,
                     "state": "READY", "stateTime": now, "createTime": now, "updateTime": now, "labels": payload.get("labels") or {}, "_source": full}
                mvms[mn] = m
                return _op_done(store, project, loc, _mvm_view(store, m), "create")
        mn = "%s/migratingVms/%s" % (full, rest[3])
        m = mvms.get(mn)
        if not m:
            raise _nf(mn)
        if len(rest) == 4:
            if verb:
                return _mvm_verb(store, project, loc, m, verb)
            if method == "GET":
                return _mvm_view(store, m)
            if method == "DELETE":
                if m["state"] in ("CUTTING_OVER", "FINAL_SYNC"):
                    raise _E(400, "FAILED_PRECONDITION", "Cannot delete a migrating VM in state %s." % m["state"])
                del mvms[mn]
                for coll in ("vmm_clone", "vmm_cutover"):
                    for k in [k for k in _x(store, coll) if k.startswith(mn + "/")]:
                        del _x(store, coll)[k]
                return _op_done(store, project, loc, {"name": mn}, "delete")
        sub = rest[4]
        _settle_vm(store, m)
        if sub == "replicationCycles":
            cyc = _cycles(m)
            if len(rest) == 5 and method == "GET":
                return {"replicationCycles": cyc}
            if len(rest) == 6 and method == "GET":
                c = next((c for c in cyc if c["name"].endswith("/" + rest[5])), None)
                if not c:
                    raise _nf("%s/replicationCycles/%s" % (mn, rest[5]))
                return c
        if sub in ("cloneJobs", "cutoverJobs"):
            return _jobs(store, method, project, loc, m, sub, rest[5:], verb, payload, query)
    raise _nf(_mk_name(project, loc, rest))


def _mvm_verb(store, project, loc, m, verb):
    _settle_vm(store, m)
    st = m["state"]
    now = _iso(_now())

    def need(*ok):
        if st not in ok:
            raise _E(400, "FAILED_PRECONDITION", "Cannot %s a migrating VM in state %s." % (verb, st))
    if verb == "startMigration":
        need("READY")
        m["state"], m["_syncStart"], m["_pausedTotal"] = "FIRST_SYNC", now, 0
    elif verb == "pauseMigration":
        need("FIRST_SYNC", "ACTIVE")
        m["state"], m["_pausedAt"] = "PAUSED", now
    elif verb == "resumeMigration":
        need("PAUSED")
        m["_pausedTotal"] = m.get("_pausedTotal", 0) + (_now() - _parse(m.pop("_pausedAt"))).total_seconds()
        m["state"] = "ACTIVE"
    elif verb == "finalizeMigration":
        need("CUTOVER")
        m["state"] = "FINALIZED"
    else:
        raise _nf("%s:%s" % (m["name"], verb))
    m["stateTime"] = m["updateTime"] = now
    return _op_done(store, project, loc, _mvm_view(store, m), verb)


def _jobs(store, method, project, loc, m, sub, tail, verb, payload, query):
    coll = _x(store, "vmm_clone" if sub == "cloneJobs" else "vmm_cutover")
    key = "cloneJob" if sub == "cloneJobs" else "cutoverJob"
    if not tail:
        if method == "GET":
            return {sub: [_pub(j) for k, j in sorted(coll.items()) if k.startswith(m["name"] + "/")]}
        if method == "POST":
            jid = query.get("cloneJobId" if sub == "cloneJobs" else "cutoverJobId") or ""
            G._check_name(jid, "cloneJobId" if sub == "cloneJobs" else "cutoverJobId")
            jn = "%s/%s/%s" % (m["name"], sub, jid)
            if jn in coll:
                raise _E(409, "ALREADY_EXISTS", "%s already exists." % jn)
            if m["state"] != "ACTIVE" or not any(c["state"] == "SUCCEEDED" for c in _cycles(m)):
                raise _E(400, "FAILED_PRECONDITION", "A %s needs the migrating VM to be ACTIVE with at least one completed replication cycle (state is %s)." % (key, m["state"]))
            td = m["computeEngineTargetDefaults"]
            vm_name = td["vmName"] if sub == "cutoverJobs" else "%s-clone-%s" % (td["vmName"], jid)[:63]
            gce = _gce_create(store, project, td, vm_name, {"vyomi-migrated-from": m["sourceVmId"].lower()[:60], "vyomi-vmm-job": sub[:5].lower()})
            now = _iso(_now())
            job = {"name": jn, "createTime": now, "endTime": now, "stateTime": now, "state": "SUCCEEDED",
                   "computeEngineVmDetails": {"project": project, "zone": td["zone"], "vmName": vm_name, "machineType": td["machineType"], "instance": G._selflink(gce)},
                   "steps": [{"preparingVmDisks": {}}, {"instantiatingMigratedVm": {}}], "vyomiNote": "Replication is record-only; the Compute Engine instance is real but boots a stock image, not the source VM's disks."}
            coll[jn] = job
            if sub == "cutoverJobs":
                m["state"], m["stateTime"] = "CUTOVER", now
            return _op_done(store, project, loc, job, "create")
    jn = "%s/%s/%s" % (m["name"], sub, tail[0])
    j = coll.get(jn)
    if not j:
        raise _nf(jn)
    if method == "GET" and not verb:
        return _pub(j)
    if verb == "cancel":
        raise _E(400, "FAILED_PRECONDITION", "%s is already %s and cannot be cancelled." % (jn, j["state"]))
    raise _nf(jn)


# ═════════════════════════════ Cloud TPU v2 ═════════════════════════════
TPU_ZONES = {"v2": ("us-central1-b", "us-central1-c", "europe-west4-a", "asia-east1-c"), "v3": ("europe-west4-a", "us-central1-a"),
             "v4": ("us-central2-b", "us-central1-a"), "v5litepod": ("us-central1-a", "us-west4-a", "europe-west4-b"), "v5p": ("us-east5-a", "us-central1-a")}
TPU_TYPES = {"v2-8": 8, "v2-32": 32, "v2-128": 128, "v3-8": 8, "v3-32": 32, "v3-128": 128, "v4-8": 4, "v4-32": 16, "v5litepod-1": 1, "v5litepod-4": 4,
             "v5litepod-8": 8, "v5p-8": 4}
TPU_RUNTIMES = ["tpu-vm-tf-2.16.1", "tpu-vm-tf-2.15.0", "tpu-vm-pt-2.3", "tpu-ubuntu2204-base", "v2-alpha-tpuv5-lite", "v2-alpha-tpuv5"]
TPU_QUOTA_CHIPS = 64        # per project, per zone, per generation (simulated default)
TPU_READY_SECONDS = 3.0


def _tpu_gen(at):
    return at.rsplit("-", 1)[0]


def _tpu_settle(n):
    if n["state"] == "CREATING" and (_now() - _parse(n["_created"])).total_seconds() >= TPU_READY_SECONDS:
        n["state"], n["health"] = "READY", "HEALTHY"


def _tpu(store, method, project, zone, rest, verb, payload, query):
    if zone not in G.ZONE_REGION and zone not in {z for zs in TPU_ZONES.values() for z in zs}:
        raise _nf("projects/%s/locations/%s" % (project, zone))
    ops = _x(store, "tpu_ops")
    pre = "projects/%s/locations/%s" % (project, zone)

    def op(resp, kind):
        oid = "operation-" + uuid.uuid4().hex[:16]
        o = {"name": "%s/operations/%s" % (pre, oid), "metadata": {"@type": "type.googleapis.com/google.cloud.tpu.v2.OperationMetadata", "createTime": _iso(_now()),
             "endTime": _iso(_now()), "target": resp.get("name", ""), "verb": kind, "apiVersion": "v2"}, "done": True, "response": dict(resp, **{"@type": "type.googleapis.com/google.cloud.tpu.v2.Node"})}
        ops[o["name"]] = o
        return o
    if rest[:1] == ["operations"] and len(rest) == 2 and method == "GET":
        o = ops.get("%s/operations/%s" % (pre, rest[1]))
        if not o:
            raise _nf("%s/operations/%s" % (pre, rest[1]))
        return o
    if rest[:1] == ["acceleratorTypes"]:
        avail = [{"name": "%s/acceleratorTypes/%s" % (pre, t), "type": t.split("-")[0].upper() if not t.startswith("v5") else t.rsplit("-", 1)[0].upper(),
                  "acceleratorConfigs": [{"type": t.rsplit("-", 1)[0].upper(), "topology": "%dx%d" % (max(1, c // 2), 2)}]} for t, c in sorted(TPU_TYPES.items()) if zone in TPU_ZONES.get(_tpu_gen(t), ())]
        if len(rest) == 1:
            return {"acceleratorTypes": avail}
        a = next((x for x in avail if x["name"].endswith("/" + rest[1])), None)
        if not a:
            raise _nf("%s/acceleratorTypes/%s" % (pre, rest[1]))
        return a
    if rest[:1] == ["runtimeVersions"]:
        rv = [{"name": "%s/runtimeVersions/%s" % (pre, r), "version": r} for r in TPU_RUNTIMES]
        if len(rest) == 1:
            return {"runtimeVersions": rv}
        a = next((x for x in rv if x["version"] == rest[1]), None)
        if not a:
            raise _nf("%s/runtimeVersions/%s" % (pre, rest[1]))
        return a
    if rest[:1] != ["nodes"]:
        raise _nf("%s/%s" % (pre, "/".join(rest)))
    nodes = _x(store, "tpu_nodes")
    if len(rest) == 1:
        if method == "GET":
            out = []
            for k, n in sorted(nodes.items()):
                if k.startswith(pre + "/"):
                    _tpu_settle(n)
                    out.append(_pub(n))
            return {"nodes": out}
        if method == "POST":
            nid = query.get("nodeId") or ""
            G._check_name(nid, "nodeId")
            full = "%s/nodes/%s" % (pre, nid)
            if full in nodes:
                raise _E(409, "ALREADY_EXISTS", "Node %s already exists." % full)
            at = payload.get("acceleratorType")
            if at not in TPU_TYPES:
                raise _bad("Invalid acceleratorType %r. Valid: %s." % (at, ", ".join(sorted(TPU_TYPES))))
            if zone not in TPU_ZONES[_tpu_gen(at)]:
                raise _bad("Accelerator type %s is not available in zone %s (available in: %s)." % (at, zone, ", ".join(TPU_ZONES[_tpu_gen(at)])))
            rv = payload.get("runtimeVersion")
            if rv not in TPU_RUNTIMES:
                raise _bad("Invalid runtimeVersion %r." % rv)
            used = sum(TPU_TYPES[n["acceleratorType"]] for k, n in nodes.items() if k.startswith(pre + "/") and _tpu_gen(n["acceleratorType"]) == _tpu_gen(at))
            if used + TPU_TYPES[at] > TPU_QUOTA_CHIPS:
                raise _E(429, "RESOURCE_EXHAUSTED", "Quota limit 'TPUV%sPerProjectPerZoneForTPUAPI' exceeded: %d of %d TPU units already in use in %s; requested %d." % (
                    _tpu_gen(at)[1:].upper(), used, TPU_QUOTA_CHIPS, zone, TPU_TYPES[at]))
            now = _iso(_now())
            sched = payload.get("schedulingConfig") or {}
            n = {"name": full, "description": payload.get("description", ""), "acceleratorType": at, "state": "CREATING", "health": "HEALTH_UNSPECIFIED",
                 "runtimeVersion": rv, "networkConfig": payload.get("networkConfig") or {"network": "default", "enableExternalIps": True}, "cidrBlock": "10.128.0.0/29",
                 "schedulingConfig": {"preemptible": bool(sched.get("preemptible")), "reserved": bool(sched.get("reserved")), "spot": bool(sched.get("spot"))},
                 "networkEndpoints": [{"ipAddress": "10.128.0.%d" % (2 + len(nodes) % 200), "port": 8470}], "apiVersion": "V2", "labels": payload.get("labels") or {},
                 "createTime": now, "vyomiNote": "Record only: no accelerator exists and nothing runs on this node.", "_created": now}
            nodes[full] = n
            return op(_pub(n), "create")
    if len(rest) == 2:
        full = "%s/nodes/%s" % (pre, rest[1])
        n = nodes.get(full)
        if not n:
            raise _nf(full)
        _tpu_settle(n)
        if verb in ("stop", "start") and method == "POST":
            if verb == "stop" and n["state"] != "READY":
                raise _E(400, "FAILED_PRECONDITION", "Node %s must be READY to stop (state %s)." % (rest[1], n["state"]))
            if verb == "start" and n["state"] != "STOPPED":
                raise _E(400, "FAILED_PRECONDITION", "Node %s must be STOPPED to start (state %s)." % (rest[1], n["state"]))
            n["state"] = "STOPPED" if verb == "stop" else "READY"
            return op(_pub(n), verb)
        if method == "GET":
            return _pub(n)
        if method == "PATCH":
            for k in ("description", "labels"):
                if k in payload:
                    n[k] = payload[k]
            return op(_pub(n), "update")
        if method == "DELETE":
            del nodes[full]
            return op({"name": full}, "delete")
    raise _nf("%s/%s" % (pre, "/".join(rest)))


def dispatch(store, method, path, query=None, headers=None, body=b""):
    """vmmigration v1 (/v1/projects/p/locations/l/...) and tpu v2 (/v2/projects/p/locations/zone/...)."""
    query, method = query or {}, method.upper()
    try:
        payload = _body(body)
        p = path.split("?", 1)[0].strip("/")
        verb = ""
        if ":" in p.rsplit("/", 1)[-1]:
            p, verb = p.rsplit(":", 1)
        segs = p.split("/")
        with _LOCK:
            if segs[0] == "v2":
                out = _tpu(store, method, segs[2], segs[4], segs[5:], verb, payload, query)
            else:
                out = _vmm(store, method, segs[2], segs[4], segs[5:], verb, payload, query)
            if method != "GET" and hasattr(store, "persist"):
                store.persist()
        return Resp(200, out)
    except _E as e:
        return _err(e)
    except (ValueError, TypeError, IndexError) as e:
        return _err(_bad("Invalid request: %s" % e))
