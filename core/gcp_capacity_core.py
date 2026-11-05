"""GCP Compute capacity model + Capacity advisor.

Substrate-independent (stdlib only; Pyodide-loadable). SIMULATED capacity: Vyomi has no Google fleet data, so each
(zone, machine family) has a deterministic vCPU pool (configurable). Instances draw from it when they are running
and give it back when stopped / suspended / deleted; reservations hold their capacity (guaranteed) whether or not VMs
use it. The pool is derived from live instance state, so every insert / start / resume (including many concurrent
ones) is accounted for. When a start would overflow a pool it fails with the real GCP stockout error
ZONE_RESOURCE_POOL_EXHAUSTED.

Capacity advisor: tier 1 project quota (FAILED/QUOTA_EXCEEDED) -> tier 2 reservations (GUARANTEED) -> tier 3 dry-run allocation on a
simulated fleet (HIGH_PROBABILITY / LOW_PROBABILITY / ZONE_RESOURCE_POOL_EXHAUSTED); the probe allocates then deallocates, never consuming capacity.
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


# ── three-tier Capacity advisor ───────────────────────────────────────────────
# Tier 1 project quota -> Tier 2 reservations -> Tier 3 dry-run allocation against a simulated fleet
# (CloudSim-style model: zone = Datacenter, node = Host, requested shape = Vm, background load = fluctuating Cloudlet load).
# This pure-Python model is used on every substrate (Nano has no JVM; offline uses it too, so answers are identical for the
# same seed and state). The cloudsim-backbone JVM bridge is NOT wired to this advisor.
HOST_CORES, HOST_RAM_GB = 128, 512
STATE_RANK = {"GUARANTEED": 0, "HIGH_PROBABILITY": 1, "LOW_PROBABILITY": 2, "ZONE_RESOURCE_POOL_EXHAUSTED": 3, "FAILED": 4}
CONGESTED = 0.85
DEFAULT_QUOTA = {"CPUS": 2400}
FAMILY_QUOTA = {"a2": 96, "g2": 64, "m1": 480}
FAMILY_QUOTA_DEFAULT = 1200
BG_PERIOD_SECONDS = 600.0


def _seed(*parts):
    import hashlib
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16)


class Vm:
    def __init__(self, name, cores, ram_gb):
        self.name, self.cores, self.ram_gb = name, cores, ram_gb


class Host:
    def __init__(self, hid, cores, ram_gb, bg_base, bg_amp, bg_phase):
        self.id, self.cores, self.ram_gb = hid, cores, ram_gb
        self.bg_base, self.bg_amp, self.bg_phase = bg_base, bg_amp, bg_phase
        self.vms = []
        self.bg_cores = 0

    def set_time(self, t):
        import math
        u = self.bg_base + self.bg_amp * math.sin(2 * math.pi * t / BG_PERIOD_SECONDS + self.bg_phase)
        self.bg_cores = int(self.cores * max(0.0, min(0.95, u)))

    def free_cores(self):
        return self.cores - self.bg_cores - sum(v.cores for v in self.vms)

    def free_ram(self):
        return self.ram_gb * (1 - self.bg_cores / float(self.cores)) - sum(v.ram_gb for v in self.vms)


class Datacenter:
    """A zone's fleet of hosts for one machine family. allocate_host_for_vm / deallocate_host_for_vm follow the CloudSim API."""

    def __init__(self, zone, family, limit_vcpus, t, chaos=0.0):
        self.zone, self.family = zone, family
        z = _seed("zone", zone, family)
        # default band 20-50% (+ at most 15% swing, +5% per host): default shapes stay HIGH_PROBABILITY. `chaos` (0..1) is an explicit
        # scenario setting (off by default) that raises the background load to provoke congestion.
        base = 0.2 + 0.3 * ((z % 1000) / 1000.0) + chaos
        amp = 0.05 + 0.10 * (((z >> 10) % 1000) / 1000.0)
        n = max(1, -(-limit_vcpus // HOST_CORES))
        self.hosts = []
        rem = limit_vcpus
        for i in range(n):
            cores = min(HOST_CORES, rem) if rem > 0 else 0
            rem -= cores
            if cores <= 0:
                break
            hz = _seed("host", zone, family, str(i))
            h = Host(i, cores, cores * (HOST_RAM_GB // HOST_CORES), min(0.95, base + 0.05 * ((hz % 100) / 100.0)), amp, (hz % 628) / 100.0)
            h.set_time(t)
            self.hosts.append(h)

    def allocate_host_for_vm(self, vm):
        for h in self.hosts:
            if h.free_cores() >= vm.cores and h.free_ram() >= vm.ram_gb:
                h.vms.append(vm)
                return h
        return None

    def deallocate_host_for_vm(self, vm):
        for h in self.hosts:
            if vm in h.vms:
                h.vms.remove(vm)

    def occupancy(self):
        tot = sum(h.cores for h in self.hosts) or 1
        return sum(h.cores - h.free_cores() for h in self.hosts) / float(tot)

    def background_percent(self):
        tot = sum(h.cores for h in self.hosts) or 1
        return round(100.0 * sum(h.bg_cores for h in self.hosts) / tot, 1)

    def place_real_load(self, store, zone, family):
        """Running instances (and reservation-held capacity) occupy hosts first-fit, exactly as the pool counts them."""
        for key, ins in sorted(store.instances.items()):
            if ins.get("_zone") == zone and ins.get("status") in ACTIVE and family_of(ins.get("machineType", "")) == family:
                sh = _shape(ins["machineType"])
                if sh:
                    self.allocate_host_for_vm(Vm(key, sh["vcpu"], sh["ram_mb"] / 1024.0))


def _quota_limit(store, region, metric):
    ov = _overrides(store).get("quota/%s/%s" % (region, metric))
    if ov is not None:
        return int(ov)
    if metric == "CPUS":
        return DEFAULT_QUOTA["CPUS"]
    return FAMILY_QUOTA.get(metric[:-5].lower(), FAMILY_QUOTA_DEFAULT)


def quota_usage(store, project, region, family):
    used_all = used_fam = 0
    for key, ins in store.instances.items():
        if not key.startswith("projects/%s/" % project) or G.ZONE_REGION.get(ins.get("_zone")) != region or ins.get("status") not in ACTIVE:
            continue
        sh = _shape(ins.get("machineType", ""))
        if not sh:
            continue
        used_all += sh["vcpu"]
        if family_of(ins["machineType"]) == family:
            used_fam += sh["vcpu"]
    m = "%s_CPUS" % family.upper()
    return [{"metric": "CPUS", "limit": _quota_limit(store, region, "CPUS"), "usage": used_all},
            {"metric": m, "limit": _quota_limit(store, region, m), "usage": used_fam}]


def _reservation_headroom(store, zone, machine_type):
    from core import gcp_compute_ext_core as ext
    res = ext._x(store, "reservations")
    free = 0
    for p in {k.split("/")[1] for k in res if "/zones/%s/" % zone in k}:
        for rn, names in ext._consumers(store, p, zone).items():
            sr = res[rn]["specificReservation"]
            if G._last(sr["instanceProperties"]["machineType"]) == machine_type:
                free += max(0, int(sr["count"]) - len(names))
    return free


def probe_zone(store, zone, machine_type, size, t):
    """Tier 2 + 3 for one zone. Never changes capacity (the dry run is allocated then deallocated)."""
    sh = _shape(machine_type)
    fam = family_of(machine_type)
    headroom = _reservation_headroom(store, zone, G._last(machine_type))
    if headroom >= size:
        return {"zone": zone, "machineType": machine_type, "state": "GUARANTEED", "tier": "RESERVATION", "obtainableSize": size,
                "reason": "An active, unutilised matching reservation holds %d slot(s) in this zone." % headroom}
    dc = Datacenter(zone, fam, pool_limit(store, zone, fam), t, chaos=float(_overrides(store).get("scenario/backgroundLoad", 0)) / 100.0)
    dc.place_real_load(store, zone, fam)
    placed = []
    for i in range(size):
        vm = Vm("advisor-probe-%d" % i, sh["vcpu"], sh["ram_mb"] / 1024.0)
        if dc.allocate_host_for_vm(vm) is None:
            break
        placed.append(vm)
    congested = dc.occupancy() >= CONGESTED
    bg = dc.background_percent()
    for vm in placed:                                    # the probe must never consume capacity
        dc.deallocate_host_for_vm(vm)
    n = len(placed)
    free = sum(max(0, h.free_cores()) for h in dc.hosts)
    if n == size and not congested:
        st, why = "HIGH_PROBABILITY", "Dry-run allocation of %d VM(s) succeeded on the simulated fleet." % size
    elif n == size:
        st, why = "LOW_PROBABILITY", "Allocation fits but the zone's hosts are heavily congested (%.0f%% occupied)." % (100 * dc.occupancy())
    elif n > 0:
        st, why = "LOW_PROBABILITY", "Only %d of %d VM(s) fit on the simulated fleet." % (n, size)
    else:
        st, why = "ZONE_RESOURCE_POOL_EXHAUSTED", "The zone does not have enough resources available to fulfill the request."
    return {"zone": zone, "machineType": machine_type, "state": st, "tier": "FLEET", "obtainableSize": n, "freeVcpus": free,
            "backgroundUtilisationPercent": bg, "hosts": len(dc.hosts), "reason": why}


def advise(store, project, region, payload):
    import time
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
    t = float(payload["simulationTime"]) if payload.get("simulationTime") is not None else time.time()
    fam = family_of(mt)
    out = {"kind": "vyomi#capacityAdvice", "project": project, "region": region, "basis": "SIMULATED_FLEET",
           "note": "Simulated fleet (Datacenter/Host/Vm model with a deterministic fluctuating background load); there is no Google fleet data.",
           "simulationTime": t}
    # Tier 1: quota (regional, per CPU / machine-family metric)
    need = sh["vcpu"] * size
    for q in quota_usage(store, project, region, fam):
        if q["usage"] + need > q["limit"]:
            out.update({"state": "FAILED", "reason": "QUOTA_EXCEEDED", "tier": "QUOTA", "quota": q,
                        "message": "Quota '%s' exceeded in %s: limit %d, in use %d, requested %d." % (q["metric"], region, q["limit"], q["usage"], need),
                        "recommendations": [], "alternativeShapes": [], "otherZonesInRegion": []})
            return out
    recs = [probe_zone(store, z, mt, size, t) for z in want]
    recs.sort(key=lambda r: (STATE_RANK[r["state"]], -r["obtainableSize"], r["zone"]))
    out["state"] = recs[0]["state"]
    out["tier"] = recs[0]["tier"]
    out["recommendations"] = recs
    out["quotas"] = quota_usage(store, project, region, fam)
    good = ("GUARANTEED", "HIGH_PROBABILITY")
    alt = []
    for name, s2 in sorted(G.MACHINE_SHAPES.items()):
        if s2["vcpu"] != sh["vcpu"] or name == mt or family_of(name) not in DEFAULT_POOL_VCPU:
            continue
        for z in want:
            r = probe_zone(store, z, name, size, t)
            if r["state"] in good:
                alt.append({"zone": z, "machineType": name, "state": r["state"]})
                break
    out["alternativeShapes"] = alt[:8]
    out["otherZonesInRegion"] = [{"zone": z, "state": r["state"]} for z in region_zones if z not in want
                                 for r in [probe_zone(store, z, mt, size, t)] if r["state"] in good]
    return out


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
    if rest[:1] == ["vyomi"] and rest[1:2] == ["capacityScenario"]:
        ov = _overrides(store)
        if method == "POST":
            v = payload.get("backgroundLoadPercent")
            if not isinstance(v, (int, float)) or not 0 <= v <= 90:
                return G._err(400, "INVALID_ARGUMENT", "backgroundLoadPercent must be a number between 0 and 90 (0 = default, no chaos).")
            ov["scenario/backgroundLoad"] = v
        return _json(200, {"backgroundLoadPercent": ov.get("scenario/backgroundLoad", 0), "default": 0})
    if rest[:1] == ["vyomi"] and rest[1:2] == ["quotas"]:
        try:
            if method == "GET":
                region, fam = query.get("region") or "us-central1", query.get("family") or "e2"
                return _json(200, {"region": region, "quotas": quota_usage(store, project, region, fam)})
            if method == "POST":
                r, m, v = payload.get("region"), payload.get("metric"), payload.get("limit")
                if r not in G.REGIONS or not isinstance(m, str) or not m.endswith("CPUS") or not isinstance(v, int) or v < 0:
                    raise _E(400, "INVALID_ARGUMENT", "region, metric (CPUS or <FAMILY>_CPUS) and an integer limit are required.")
                _overrides(store)["quota/%s/%s" % (r, m)] = v
                return _json(200, {"region": r, "metric": m, "limit": v})
        except _E as e:
            return G._err(e.status, e.gcp_status, e.message)
    if len(rest) == 4 and rest[0] == "regions" and rest[2:] == ["advice", "capacity"] and method == "POST":
        try:
            return _json(200, advise(store, project, rest[1], payload))
        except _E as e:
            return G._err(e.status, e.gcp_status, e.message)
    return None
