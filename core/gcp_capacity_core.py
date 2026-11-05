"""GCP Compute capacity model + Capacity advisor.

Substrate-independent (stdlib only; Pyodide-loadable). SIMULATED capacity: Vyomi has no Google fleet data, so each
(zone, machine family) has a deterministic vCPU pool (configurable). Instances draw from it when they are running
and give it back when stopped / suspended / deleted; reservations hold their capacity (guaranteed) whether or not VMs
use it. The pool is derived from live instance state, so every insert / start / resume (including many concurrent
ones) is accounted for. When a start would overflow a pool it fails with the real GCP stockout error
ZONE_RESOURCE_POOL_EXHAUSTED.

Wire (Vyomi verbs on the Compute API):
  GET    /compute/v1/projects/{p}/vyomi/capacity?region=|zone=      pools with limit/used/reserved/free/utilisation
  POST   /compute/v1/projects/{p}/vyomi/capacityPools              {zone, family, vcpus}  override a pool size
  DELETE /compute/v1/projects/{p}/vyomi/capacityPools?zone=&family=  reset to the default
  POST   /compute/beta/projects/{p}/regions/{r}/advice/capacity    {instanceProperties:{machineType}, size, distributionPolicy:{zones:[{zone}]}}
State: store.ext["capacity_pools"] (overrides only).
"""
from __future__ import annotations

import threading

from core import gcp_compute_instances_core as G
from core.gcp_compute_instances_core import _E, _json

LOCK = threading.RLock()
GENERAL = ("e2", "n1", "n2", "n2d", "t2d", "n4", "c3")
DEFAULT_POOL_VCPU = {"e2": 4096, "n1": 4096, "n2": 4096, "n2d": 2048, "t2d": 1024, "c2": 1024, "m1": 512, "a2": 96, "g2": 64}
FALLBACK_POOL = 2048
ZONE_FACTOR = {"a": 1.0, "b": 1.0, "c": 0.75, "d": 0.6, "f": 0.5}
ACTIVE = ("RUNNING", "PROVISIONING", "STAGING", "REPAIRING")


def family_of(machine_type):
    return G._last(machine_type).split("-")[0]


def _overrides(store):
    if getattr(store, "ext", None) is None:
        store.ext = {}
    return store.ext.setdefault("capacity_pools", {})


def pool_limit(store, zone, family):
    ov = _overrides(store).get("%s/%s" % (zone, family))
    if ov is not None:
        return int(ov)
    base = DEFAULT_POOL_VCPU.get(family, FALLBACK_POOL)
    return int(base * ZONE_FACTOR.get(zone[-1:], 1.0))


def _shape(mt):
    return G.MACHINE_SHAPES.get(G._last(mt))


def _reserved_and_consumed(store, zone, family):
    """(vcpus held by reservations, vcpus of running VMs sitting inside those reservations)."""
    from core import gcp_compute_ext_core as ext
    res = ext._x(store, "reservations")
    held = consumed = 0
    projects = {k.split("/")[1] for k in res if "/zones/%s/" % zone in k}
    for p in projects:
        cons = ext._consumers(store, p, zone)
        for rn, names in cons.items():
            r = res[rn]
            sr = r["specificReservation"]
            mt = sr["instanceProperties"]["machineType"]
            if family_of(mt) != family or not _shape(mt):
                continue
            v = _shape(mt)["vcpu"]
            held += int(sr["count"]) * v
            consumed += min(len(names), int(sr["count"])) * v
    return held, consumed


def pool_usage(store, zone, family):
    running = 0
    for key, ins in store.instances.items():
        if ins.get("_zone") != zone or ins.get("status") not in ACTIVE or family_of(ins.get("machineType", "")) != family:
            continue
        sh = _shape(ins["machineType"])
        running += sh["vcpu"] if sh else 0
    held, consumed = _reserved_and_consumed(store, zone, family)
    limit = pool_limit(store, zone, family)
    used = running - consumed + held          # reservation-backed VMs are already inside the reserved capacity
    return {"zone": zone, "family": family, "limitVcpus": limit, "runningVcpus": running, "reservedVcpus": held,
            "reservedInUseVcpus": consumed, "usedVcpus": used, "freeVcpus": max(0, limit - used),
            "utilisationPercent": round(100.0 * used / limit, 1) if limit else 100.0}


def stockout(zone, project="-"):
    return _E(503, "ZONE_RESOURCE_POOL_EXHAUSTED",
              "The zone 'projects/%s/zones/%s' does not have enough resources available to fulfill the request. "
              "Try a different zone, or try again later. (ZONE_RESOURCE_POOL_EXHAUSTED)" % (project, zone))


def check_after_commit(store, zone, machine_type, project="-"):
    """Call AFTER the VM is marked active: raises the stockout error if its pool now overflows (caller rolls back)."""
    fam = family_of(machine_type)
    u = pool_usage(store, zone, fam)
    if u["usedVcpus"] > u["limitVcpus"]:
        raise stockout(zone, project)


def all_pools(store, region=None, zone=None):
    zones = [z for z, r in G.ZONES if (not region or r == region) and (not zone or z == zone)]
    fams = sorted({family_of(n) for n in G.MACHINE_SHAPES})
    rows = []
    for z in zones:
        for f in fams:
            rows.append(pool_usage(store, z, f))
    return rows


def advise(store, project, region, payload):
    props = payload.get("instanceProperties") or {}
    mt = G._last(props.get("machineType") or "")
    sh = _shape(mt)
    if not sh:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'instanceProperties.machineType': %r." % mt)
    size = int(payload.get("size") or 1)
    if size < 1 or size > 1000:
        raise _E(400, "INVALID_ARGUMENT", "size must be between 1 and 1000.")
    region_zones = [z for z, r in G.ZONES if r == region]
    if not region_zones:
        raise _E(404, "NOT_FOUND", "The resource 'projects/%s/regions/%s' was not found." % (project, region))
    want = [G._last(z.get("zone")) for z in ((payload.get("distributionPolicy") or {}).get("zones") or [])] or region_zones
    for z in want:
        if z not in region_zones:
            raise _E(400, "INVALID_ARGUMENT", "Zone %r is not in region %s." % (z, region))
    fam = family_of(mt)
    recs = []
    for z in want:
        u = pool_usage(store, z, fam)
        fit = u["freeVcpus"] // sh["vcpu"]
        recs.append({"zone": z, "machineType": mt, "requestedSize": size, "obtainableSize": min(size, fit), "freeVcpus": u["freeVcpus"],
                     "obtainability": "AVAILABLE" if fit >= size else ("PARTIAL" if fit > 0 else "UNAVAILABLE"),
                     "utilisationPercent": u["utilisationPercent"]})
    recs.sort(key=lambda r: (-r["obtainableSize"], r["utilisationPercent"], r["zone"]))
    alt = []                                      # same zone set, other machine families with room for `size` of the same vCPU count
    for name, s2 in sorted(G.MACHINE_SHAPES.items()):
        if s2["vcpu"] != sh["vcpu"] or family_of(name) == fam or not name.split("-")[0] in DEFAULT_POOL_VCPU:
            continue
        for z in want:
            u = pool_usage(store, z, family_of(name))
            if u["freeVcpus"] // s2["vcpu"] >= size:
                alt.append({"zone": z, "machineType": name, "freeVcpus": u["freeVcpus"]})
                break
    other = [{"zone": z, "freeVcpus": pool_usage(store, z, fam)["freeVcpus"]} for z in region_zones if z not in want]
    return {"kind": "vyomi#capacityAdvice", "project": project, "region": region, "recommendations": recs,
            "alternativeShapes": alt[:8], "otherZonesInRegion": [o for o in other if o["freeVcpus"] // sh["vcpu"] >= size],
            "basis": "SIMULATED_POOLS",
            "note": "Derived from Vyomi's own simulated per-zone capacity pools, reservations and running instances; there is no Google fleet data."}


def handle(store, method, project, rest, verb, payload, query):
    """ComputeResponse for the capacity verbs, else None."""
    if rest[:1] == ["vyomi"] and rest[1:2] == ["capacity"] and method == "GET":
        zone, region = query.get("zone"), query.get("region")
        if zone and zone not in G.ZONE_REGION:
            return G._err(404, "NOT_FOUND", "Zone %r not found." % zone)
        return _json(200, {"items": all_pools(store, region, zone), "basis": "SIMULATED_POOLS"})
    if rest[:1] == ["vyomi"] and rest[1:2] == ["capacityPools"]:
        try:
            if method == "POST":
                z, f, v = payload.get("zone"), payload.get("family"), payload.get("vcpus")
                if z not in G.ZONE_REGION:
                    raise _E(400, "INVALID_ARGUMENT", "Invalid zone %r." % z)
                if not f or not any(family_of(n) == f for n in G.MACHINE_SHAPES):
                    raise _E(400, "INVALID_ARGUMENT", "Unknown machine family %r." % f)
                if not isinstance(v, int) or v < 0 or v > 1000000:
                    raise _E(400, "INVALID_ARGUMENT", "vcpus must be an integer between 0 and 1000000.")
                _overrides(store)["%s/%s" % (z, f)] = v
                return _json(200, pool_usage(store, z, f))
            if method == "DELETE":
                _overrides(store).pop("%s/%s" % (query.get("zone"), query.get("family")), None)
                return _json(200, {})
        except _E as e:
            return G._err(e.status, e.gcp_status, e.message)
    if len(rest) == 4 and rest[0] == "regions" and rest[2:] == ["advice", "capacity"] and method == "POST":
        try:
            return _json(200, advise(store, project, rest[1], payload))
        except _E as e:
            return G._err(e.status, e.gcp_status, e.message)
    return None
