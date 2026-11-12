"""Compute Engine v1 methods on the VM store that gcp_compute_instances_core did not serve: disks, snapshots, images, instances.

Real mutations of the same records the console and the core read (store.disks / snapshots / images / instances), validated like
the API (state preconditions, shrink refusal, fingerprint checks, uniqueness), each returning a completed compute#operation
that `operations.get` resolves.  Hooked into gcp_compute_instances_core._dispatch ahead of the generic routing.

  disks       resize, setLabels, getIamPolicy / setIamPolicy / testIamPermissions
  snapshots   setLabels, IAM
  images      setLabels, deprecate, getFromFamily, patch, IAM
  instances   attachDisk, detachDisk, setDiskAutoDelete, setScheduling, setServiceAccount, setMinCpuPlatform, setName,
              addAccessConfig / deleteAccessConfig / updateAccessConfig, updateNetworkInterface, updateDisplayDevice,
              updateShieldedInstanceConfig, getShieldedInstanceIdentity, simulateMaintenanceEvent, listReferrers, IAM
"""
from __future__ import annotations

import hashlib
import json


def _v():
    from core import gcp_compute_instances_core as V
    return V


def _policy_verbs(store, holder, verb, method, payload):
    V = _v()
    if verb == "getIamPolicy":
        return V._json(200, holder.setdefault("_iamPolicy", {"version": 1, "etag": "ACAB", "bindings": []}))
    if verb == "setIamPolicy":
        pol = dict(payload.get("policy") or {})
        for k in ("bindings", "etag", "version"):
            if k in payload and k not in pol:
                pol[k] = payload[k]
        cur = holder.get("_iamPolicy") or {"etag": "ACAB", "bindings": []}
        if pol.get("etag") and cur["bindings"] and pol["etag"] != cur["etag"]:
            raise V._E(409, "ABORTED", "Supplied fingerprint does not match current fingerprint.")
        pol["bindings"] = pol.get("bindings") or []
        pol["version"] = pol.get("version", 1)
        pol["etag"] = hashlib.sha1(json.dumps(pol["bindings"], sort_keys=True).encode()).hexdigest()[:11]
        holder["_iamPolicy"] = pol
        return V._json(200, pol)
    return V._json(200, {"permissions": list(payload.get("permissions") or [])})


def _set_labels(holder, payload):
    V = _v()
    fp = holder.get("labelFingerprint")
    if fp and payload.get("labelFingerprint") and payload["labelFingerprint"] != fp:
        raise V._E(412, "CONDITION_NOT_MET", "Labels fingerprint either invalid or resource labels have changed")
    holder["labels"] = dict(payload.get("labels") or {})
    holder["labelFingerprint"] = V._fingerprint(holder["labels"])


def handle(store, method, project, rest, verb, payload, query):
    """Return a ComputeResponse, or None when the request is not one of these methods."""
    V = _v()
    if not rest:
        return None
    segs = list(rest)
    if not verb and len(segs) >= 4 and segs[-1] in _VERBS and ((segs[0] == "zones" and len(segs) == 5) or (segs[0] == "global" and len(segs) == 4)):
        segs, verb = segs[:-1], segs[-1]
    if not verb and len(segs) == 1 and segs[0] in _PROJECT_VERBS:
        segs, verb = [], segs[0]
    if not verb and segs[0] == "zones" and len(segs) in (3, 4) and segs[2] in ("diskTypes", "acceleratorTypes") and method == "GET":
        return _catalog(project, segs[1], segs[2], segs[3] if len(segs) == 4 else "")
    if not verb and segs[0] == "aggregated" and len(segs) == 2 and segs[1] in ("diskTypes", "acceleratorTypes") and method == "GET":
        V = _v()
        return V._json(200, {"kind": "compute#%sAggregatedList" % segs[1][:-1], "id": "projects/%s/aggregated/%s" % (project, segs[1]),
                             "items": {"zones/" + z: {segs[1]: json.loads(_catalog(project, z, segs[1], "").body)["items"]} for z, _r in V.ZONES}})
    if verb is None or verb == "":
        if len(segs) == 4 and segs[0] == "global" and segs[1] == "images" and segs[2] == "family" and method == "GET":
            return _from_family(store, project, segs[3])
        return None
    try:
        if not segs and verb in _PROJECT_VERBS:
            return _project_verb(store, method, project, verb, payload, query)
        if segs and segs[0] == "global" and len(segs) == 3 and segs[1] == "machineImages":
            return _machine_image(store, method, project, segs[2], verb, payload)
        if segs and segs[0] == "zones" and len(segs) == 2 and verb == "bulkSetLabels":
            return _bulk_labels(store, method, project, segs[1], payload)
        if segs and segs[0] == "zones" and len(segs) == 4 and segs[2] == "disks" and verb == "stopGroupAsyncReplication":
            return V_stop_group(store, project, segs[1], payload)
        if segs and segs[0] == "zones" and len(segs) == 4 and segs[2] == "instances" and verb == "referrers":
            verb = "listReferrers"
        if segs[0] == "zones" and len(segs) == 4 and segs[2] in ("disks", "instances"):
            return (_disk if segs[2] == "disks" else _instance_verb)(store, method, project, segs[1], segs[3], verb, payload, query)
        if segs[0] == "global" and len(segs) == 3 and segs[1] in ("snapshots", "images"):
            return _global_verb(store, method, project, segs[1], segs[2], verb, payload)
    except V._E as e:
        return V._err(e.status, e.gcp_status, e.message)
    return None


_VERBS = {"resize", "setLabels", "getIamPolicy", "setIamPolicy", "testIamPermissions", "deprecate", "attachDisk", "detachDisk", "setDiskAutoDelete",
          "setScheduling", "setServiceAccount", "setMinCpuPlatform", "setName", "addAccessConfig", "deleteAccessConfig", "updateAccessConfig",
          "updateNetworkInterface", "updateDisplayDevice", "updateShieldedInstanceConfig", "getShieldedInstanceIdentity", "simulateMaintenanceEvent",
          "listReferrers", "referrers", "setShieldedInstanceConfig", "performMaintenance", "addNetworkInterface", "deleteNetworkInterface",
          "setMachineResources", "setSecurityPolicy", "sendDiagnosticInterrupt", "reportHostAsFaulty", "setShieldedInstanceIntegrityPolicy",
          "startWithEncryptionKey", "getEffectiveFirewalls", "bulkSetLabels", "stopGroupAsyncReplication"}
_PROJECT_VERBS = {"setUsageExportBucket", "setDefaultNetworkTier", "setCloudArmorTier", "getXpnHost", "moveDisk", "moveInstance"}
_ACCEL = (("nvidia-tesla-t4", "NVIDIA T4", 4), ("nvidia-l4", "NVIDIA L4", 8), ("nvidia-tesla-v100", "NVIDIA V100", 8), ("nvidia-a100-80gb", "NVIDIA A100 80GB", 8),
          ("nvidia-h100-80gb", "NVIDIA H100 80GB", 8))


def _disk(store, method, project, zone, name, verb, payload, query):
    V = _v()
    full, disk = V._disk(store, project, zone, name)
    if verb in ("getIamPolicy", "setIamPolicy", "testIamPermissions"):
        return _policy_verbs(store, disk, verb, method, payload)
    if verb == "setLabels" and method == "POST":
        _set_labels(disk, payload)
        return V._json(200, V._operation(store, project, zone, "setLabels", name, V._selflink(full)))
    if verb == "resize" and method == "POST":
        try:
            new = int(payload.get("sizeGb"))
        except (TypeError, ValueError):
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'sizeGb'.")
        if new <= int(disk["sizeGb"]):
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'sizeGb': %d. New size must be larger than the current size (%s GB)." % (new, disk["sizeGb"]))
        if new > 65536:
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'sizeGb': %d. Disk size cannot exceed 65536 GB." % new)
        disk["sizeGb"] = str(new)
        for iname in V._attached_users(store, project, name, zone):   # the attached instance's disk entry grows with it
            for d in store.instances[iname].get("disks", []):
                if V._last(d.get("source", "")) == name:
                    d["diskSizeGb"] = str(new)
        return V._json(200, V._operation(store, project, zone, "resize", name, V._selflink(full)))
    return None


def _global_verb(store, method, project, coll, name, verb, payload):
    V = _v()
    bucket = store.snapshots if coll == "snapshots" else store.images
    full = "projects/%s/global/%s/%s" % (project, coll, name)
    rec = V._get(store, bucket, full, coll[:-1])
    if verb in ("getIamPolicy", "setIamPolicy", "testIamPermissions"):
        return _policy_verbs(store, rec, verb, method, payload)
    if verb == "setLabels" and method == "POST":
        _set_labels(rec, payload)
        return V._json(200, V._operation(store, project, None, "setLabels", name, V._selflink(full)))
    if coll == "images" and verb == "deprecate" and method == "POST":
        st = payload.get("state") or "ACTIVE"
        if st not in ("ACTIVE", "DEPRECATED", "OBSOLETE", "DELETED"):
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'state': %r." % st)
        if st == "ACTIVE":
            rec.pop("deprecated", None)
        else:
            rep = payload.get("replacement")
            if rep and V._last(rep) and "projects/%s/global/images/%s" % (project, V._last(rep)) not in store.images:
                raise V._E(400, "INVALID_ARGUMENT", "The replacement image '%s' was not found." % rep)
            rec["deprecated"] = {k: payload[k] for k in ("state", "replacement", "deprecated", "obsolete", "deleted") if k in payload}
        return V._json(200, V._operation(store, project, None, "deprecate", name, V._selflink(full)))
    return None


def _from_family(store, project, family):
    V = _v()
    cands = [(i.get("creationTimestamp", ""), n) for n, i in store.images.items()
             if n.startswith("projects/%s/global/images/" % project) and i.get("family") == family and (i.get("deprecated") or {}).get("state", "ACTIVE") == "ACTIVE"]
    if not cands:
        return V._err(404, "NOT_FOUND", "The resource 'projects/%s/global/images/family/%s' was not found." % (project, family))
    return V._json(200, V.image_view(store, max(cands)[1]))


def _instance_verb(store, method, project, zone, name, verb, payload, query):
    V = _v()
    full, inst = V._instance(store, project, zone, name)
    op = lambda: V._json(200, V._operation(store, project, zone, verb, name, V._selflink(full)))   # noqa: E731
    if verb in ("getIamPolicy", "setIamPolicy", "testIamPermissions"):
        return _policy_verbs(store, inst, verb, method, payload)
    if verb == "attachDisk" and method == "POST":
        src = payload.get("source") or ""
        dname = V._last(src)
        dfull = "projects/%s/zones/%s/disks/%s" % (project, zone, dname)
        if dfull not in store.disks:
            raise V._E(404, "NOT_FOUND", "The resource '%s' was not found." % dfull)
        d = store.disks[dfull]
        if d.get("users") and not payload.get("mode") == "READ_ONLY":
            raise V._E(400, "RESOURCE_IN_USE_BY_ANOTHER_RESOURCE", "The disk resource '%s' is already being used by '%s'." % (dname, V._last(d["users"][0])))
        if any(V._last(x.get("source", "")) == dname for x in inst.get("disks", [])):
            raise V._E(409, "ALREADY_EXISTS", "Disk '%s' is already attached to instance '%s'." % (dname, name))
        dev = payload.get("deviceName") or dname
        if any(x.get("deviceName") == dev for x in inst.get("disks", [])):
            raise V._E(409, "ALREADY_EXISTS", "The device name '%s' is already in use on instance '%s'." % (dev, name))
        inst.setdefault("disks", []).append({"kind": "compute#attachedDisk", "type": "PERSISTENT", "mode": payload.get("mode", "READ_WRITE"), "source": V._selflink(dfull),
                                             "deviceName": dev, "index": len(inst["disks"]) if inst.get("disks") else 0, "boot": bool(payload.get("boot")),
                                             "autoDelete": bool(payload.get("autoDelete")), "interface": payload.get("interface", "SCSI"), "diskSizeGb": d["sizeGb"]})
        d["users"] = list(d.get("users", [])) + [V._selflink(full)]
        return op()
    if verb == "detachDisk" and method == "POST":
        dev = (query or {}).get("deviceName") or payload.get("deviceName")
        match = next((x for x in inst.get("disks", []) if x.get("deviceName") == dev), None)
        if match is None:
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'deviceName': '%s'. No disk with that device name is attached." % dev)
        if match.get("boot"):
            raise V._E(400, "CONDITION_NOT_MET", "The boot disk cannot be detached from a running instance.") if inst["status"] == V.RUNNING else None
        inst["disks"].remove(match)
        d = store.disks.get("projects/%s/zones/%s/disks/%s" % (project, zone, V._last(match.get("source", ""))))
        if d is not None:
            d["users"] = [u for u in d.get("users", []) if V._last(u) != name]
        return op()
    if verb == "setDiskAutoDelete" and method == "POST":
        dev = (query or {}).get("deviceName")
        match = next((x for x in inst.get("disks", []) if x.get("deviceName") == dev), None)
        if match is None:
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'deviceName': '%s'." % dev)
        match["autoDelete"] = str((query or {}).get("autoDelete", "true")).lower() == "true"
        return op()
    if verb == "setScheduling" and method == "POST":
        V._require_state(inst, (V.TERMINATED, V.RUNNING), "setScheduling")
        sch = dict(inst.get("scheduling") or {})
        pm = payload.get("provisioningModel")
        if pm and pm not in ("STANDARD", "SPOT"):
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'provisioningModel': %r." % pm)
        if inst["status"] == V.RUNNING and ("provisioningModel" in payload or "preemptible" in payload) and payload.get("provisioningModel", sch.get("provisioningModel")) != sch.get("provisioningModel"):
            raise V._E(400, "CONDITION_NOT_MET", "The provisioning model can only be changed while the instance is stopped.")
        sch.update(payload)
        inst["scheduling"] = sch
        return op()
    if verb == "setServiceAccount" and method == "POST":
        V._require_state(inst, (V.TERMINATED,), "setServiceAccount")
        inst["serviceAccounts"] = [{"email": payload.get("email") or "default", "scopes": list(payload.get("scopes") or [])}] if payload.get("email") or payload.get("scopes") else []
        return op()
    if verb == "setMinCpuPlatform" and method == "POST":
        V._require_state(inst, (V.TERMINATED,), "setMinCpuPlatform")
        inst["minCpuPlatform"] = payload.get("minCpuPlatform", "")
        return op()
    if verb == "setName" and method == "POST":
        V._require_state(inst, (V.TERMINATED,), "setName")
        new = payload.get("name") or ""
        V._check_name(new, "name")
        nfull = "projects/%s/zones/%s/instances/%s" % (project, zone, new)
        if nfull in store.instances:
            raise V._E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % nfull)
        inst["name"] = new
        inst["selfLink"] = V._selflink(nfull)
        store.instances[nfull] = store.instances.pop(full)
        for d in store.disks.values():
            d["users"] = [V._selflink(nfull) if V._last(u) == name else u for u in d.get("users", [])]
        return V._json(200, V._operation(store, project, zone, verb, new, V._selflink(nfull)))
    if verb in ("addAccessConfig", "updateAccessConfig", "deleteAccessConfig") and method in ("POST", "DELETE"):
        nic_name = (query or {}).get("networkInterface") or "nic0"
        nic = next((n for n in inst.get("networkInterfaces", []) if n.get("name") == nic_name), None)
        if nic is None:
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'networkInterface': '%s'." % nic_name)
        acs = nic.setdefault("accessConfigs", [])
        if verb == "deleteAccessConfig":
            an = (query or {}).get("accessConfig")
            match = next((a for a in acs if a.get("name") == an), None)
            if match is None:
                raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'accessConfig': '%s'." % an)
            acs.remove(match)
        else:
            nm = payload.get("name") or "External NAT"
            if verb == "addAccessConfig":
                if any(a.get("name") == nm for a in acs):
                    raise V._E(409, "ALREADY_EXISTS", "An access config named '%s' already exists on %s." % (nm, nic_name))
                acs.append({"kind": "compute#accessConfig", "type": payload.get("type", "ONE_TO_ONE_NAT"), "name": nm,
                            "natIP": payload.get("natIP") or V._synthetic_ip("34.0", "%s/%s/%s" % (name, nic_name, nm)), "networkTier": payload.get("networkTier", "PREMIUM")})
            else:
                match = next((a for a in acs if a.get("name") == nm), None)
                if match is None:
                    raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'accessConfig': '%s'." % nm)
                match.update({k: payload[k] for k in ("natIP", "networkTier", "setPublicPtr", "publicPtrDomainName") if k in payload})
        return op()
    if verb == "updateNetworkInterface" and method == "PATCH":
        nic_name = (query or {}).get("networkInterface") or "nic0"
        nic = next((n for n in inst.get("networkInterfaces", []) if n.get("name") == nic_name), None)
        if nic is None:
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'networkInterface': '%s'." % nic_name)
        for k in ("aliasIpRanges", "networkIP", "stackType", "nicType"):
            if k in payload:
                nic[k] = payload[k]
        return op()
    if verb == "updateDisplayDevice" and method == "PATCH":
        inst["displayDevice"] = {"enableDisplay": bool(payload.get("enableDisplay"))}
        return op()
    if verb in ("updateShieldedInstanceConfig", "setShieldedInstanceConfig") and method in ("PATCH", "POST"):
        V._require_state(inst, (V.TERMINATED,), verb)
        cfg = dict(inst.get("shieldedInstanceConfig") or {})
        cfg.update({k: bool(payload[k]) for k in ("enableSecureBoot", "enableVtpm", "enableIntegrityMonitoring") if k in payload})
        inst["shieldedInstanceConfig"] = cfg
        return op()
    if verb == "getShieldedInstanceIdentity" and method == "GET":
        h = hashlib.sha256(full.encode()).hexdigest()
        return V._json(200, {"kind": "compute#shieldedInstanceIdentity", "encryptionKey": {"ekPub": h[:64], "ekCert": h[:32]},
                             "signingKey": {"ekPub": h[32:], "ekCert": h[:16]}})
    if verb == "simulateMaintenanceEvent" and method == "POST":
        V._require_state(inst, (V.RUNNING,), verb)
        inst["lastStartTimestamp"] = V._ts()
        return op()
    if verb == "addNetworkInterface" and method == "POST":
        V._require_state(inst, (V.TERMINATED, V.RUNNING), verb)
        nics = inst.setdefault("networkInterfaces", [])
        if len(nics) >= 8:
            raise V._E(400, "QUOTA_EXCEEDED", "Quota 'NETWORK_INTERFACES_PER_INSTANCE' exceeded. Limit: 8.")
        net = payload.get("network")
        if not net:
            raise V._E(400, "INVALID_ARGUMENT", "Required field 'network' not specified.")
        if any(n.get("network") == net for n in nics):
            raise V._E(400, "INVALID_ARGUMENT", "Instance %s already has a network interface in network %s." % (name, V._last(net)))
        nic = {"kind": "compute#networkInterface", "network": net, "subnetwork": payload.get("subnetwork", ""), "name": "nic%d" % len(nics),
               "networkIP": payload.get("networkIP") or V._synthetic_ip("10.128", "%s/nic%d" % (name, len(nics))), "stackType": payload.get("stackType", "IPV4_ONLY")}
        if payload.get("accessConfigs"):
            nic["accessConfigs"] = payload["accessConfigs"]
        nics.append(nic)
        return op()
    if verb == "deleteNetworkInterface" and method == "POST":
        V._require_state(inst, (V.TERMINATED, V.RUNNING), verb)
        nn = (query or {}).get("networkInterfaceName")
        nics = inst.get("networkInterfaces", [])
        match = next((n for n in nics if n.get("name") == nn), None)
        if match is None:
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'networkInterfaceName': '%s'." % nn)
        if nn == "nic0":
            raise V._E(400, "INVALID_ARGUMENT", "The primary network interface nic0 cannot be deleted.")
        nics.remove(match)
        for i, n in enumerate(nics):
            n["name"] = "nic%d" % i
        return op()
    if verb == "setMachineResources" and method == "POST":
        V._require_state(inst, (V.TERMINATED,), verb)
        inst["guestAccelerators"] = list(payload.get("guestAccelerators") or [])
        return op()
    if verb == "setSecurityPolicy" and method == "POST":
        inst.setdefault("networkInterfaces", [{}])[0]["securityPolicy"] = payload.get("securityPolicy", "")
        return op()
    if verb in ("sendDiagnosticInterrupt", "reportHostAsFaulty") and method == "POST":
        V._require_state(inst, (V.RUNNING,), verb)
        if verb == "reportHostAsFaulty":
            inst["_faultReports"] = list(inst.get("_faultReports", [])) + [{"reason": payload.get("faultReasons", []), "at": V._ts()}]
        return op()
    if verb == "setShieldedInstanceIntegrityPolicy" and method == "PATCH":
        cfg = dict(inst.get("shieldedInstanceIntegrityPolicy") or {})
        cfg["updateAutoLearnPolicy"] = bool(payload.get("updateAutoLearnPolicy", True))
        inst["shieldedInstanceIntegrityPolicy"] = cfg
        return op()
    if verb == "startWithEncryptionKey" and method == "POST":
        if not payload.get("disks"):
            raise V._E(400, "INVALID_ARGUMENT", "Required field 'disks' not specified.")
        return V._json(200, V.set_instance_status(store, project, zone, name, "start"))
    if verb == "getEffectiveFirewalls" and method == "GET":
        nic = next((n for n in inst.get("networkInterfaces", []) if n.get("name") == ((query or {}).get("networkInterface") or "nic0")), None)
        if nic is None:
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'networkInterface'.")
        vpc = V._CTX.get("vpc")
        fws = [dict(f) for f in (getattr(vpc, "firewalls", {}) or {}).values() if V._last(f.get("network", f.get("networkName", ""))) == V._last(nic.get("network", ""))] if vpc else []
        return V._json(200, {"firewalls": [{"kind": "compute#firewall", "name": f.get("name"), "priority": f.get("priority", 1000), "direction": f.get("direction", "INGRESS"),
                                            "allowed": f.get("allowed", []), "sourceRanges": f.get("sourceRanges", [])} for f in fws], "firewallPolicys": []})
    if verb == "listReferrers" and method == "GET":
        return V._json(200, {"kind": "compute#instanceListReferrers", "items": [
            {"kind": "compute#reference", "referrer": V._selflink(n), "referenceType": "REFERENCED_BY", "target": V._selflink(full)}
            for n, g in sorted(getattr(store, "instance_groups", {}).items()) if V._selflink(full) in [V._selflink(m) if "://" not in m else m for m in g.get("_members", [])]]})
    return None


# ── catalogs, project-level verbs, machine images, bulk label ops ──────────────────────────
def _catalog(project, zone, kind, name):
    V = _v()
    if zone not in V.ZONE_REGION:
        return V._err(404, "NOT_FOUND", "The resource 'projects/%s/zones/%s' was not found." % (project, zone))
    if kind == "diskTypes":
        rows = [{"kind": "compute#diskType", "id": str(int(hashlib.sha1(("dt" + t).encode()).hexdigest()[:8], 16)), "name": t, "zone": V._selflink("projects/%s/zones/%s" % (project, zone)),
                 "validDiskSize": "10GB-65536GB" if t.startswith("pd") else "10GB-65536GB", "defaultDiskSizeGb": "500" if t == "pd-standard" else "100",
                 "selfLink": V._selflink("projects/%s/zones/%s/diskTypes/%s" % (project, zone, t))} for t in V.DISK_TYPES]
    else:
        rows = [{"kind": "compute#acceleratorType", "id": str(int(hashlib.sha1(("at" + t).encode()).hexdigest()[:8], 16)), "name": t, "description": d,
                 "zone": V._selflink("projects/%s/zones/%s" % (project, zone)), "maximumCardsPerInstance": mx,
                 "selfLink": V._selflink("projects/%s/zones/%s/acceleratorTypes/%s" % (project, zone, t))} for t, d, mx in _ACCEL]
    if name:
        row = next((r for r in rows if r["name"] == name), None)
        if row is None:
            return V._err(404, "NOT_FOUND", "The resource 'projects/%s/zones/%s/%s/%s' was not found." % (project, zone, kind, name))
        return V._json(200, row)
    return V._json(200, {"kind": "compute#%sList" % kind[:-1], "id": "projects/%s/zones/%s/%s" % (project, zone, kind), "items": rows})


def _project_verb(store, method, project, verb, payload, query):
    V = _v()
    meta = V._proj(store, project)
    if verb == "setUsageExportBucket":
        b = payload.get("bucketName")
        if b:
            gcs = (V._CTX or {}).get("gcs")
            if gcs is not None and not gcs.bucket_exists(b):
                raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'bucketName': '%s'. The bucket does not exist." % b)
            meta["usageExportLocation"] = {"bucketName": b, "reportNamePrefix": payload.get("reportNamePrefix", "usage_gce")}
        else:
            meta.pop("usageExportLocation", None)
    elif verb == "setDefaultNetworkTier":
        t = payload.get("networkTier")
        if t not in ("PREMIUM", "STANDARD"):
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'networkTier': %r." % t)
        meta["defaultNetworkTier"] = t
    elif verb == "setCloudArmorTier":
        t = payload.get("cloudArmorTier")
        if t not in ("CA_STANDARD", "CA_ENTERPRISE_PAYGO", "CA_ENTERPRISE_ANNUAL"):
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'cloudArmorTier': %r." % t)
        meta["cloudArmorTier"] = t
    elif verb == "getXpnHost":
        return V._json(200, {"kind": "compute#project", "name": project, "xpnProjectStatus": meta.get("xpnProjectStatus", "UNSPECIFIED_XPN_PROJECT_STATUS")})
    elif verb in ("moveDisk", "moveInstance"):
        coll = "disks" if verb == "moveDisk" else "instances"
        src = payload.get("targetDisk" if verb == "moveDisk" else "targetInstance") or ""
        dest = payload.get("destinationZone") or ""
        bucket = store.disks if verb == "moveDisk" else store.instances
        m = [n for n in bucket if n.startswith("projects/%s/zones/" % project) and n.endswith("/%s/%s" % (coll, V._last(src)))]
        if not m:
            raise V._E(404, "NOT_FOUND", "The resource '%s' was not found." % src)
        if V._last(dest) not in V.ZONE_REGION:
            raise V._E(400, "INVALID_ARGUMENT", "Invalid value for field 'destinationZone': %r." % dest)
        rec = bucket.pop(m[0])
        nz = V._last(dest)
        nfull = "projects/%s/zones/%s/%s/%s" % (project, nz, coll, rec["name"])
        rec["_zone"] = nz
        rec["zone"] = V._selflink("projects/%s/zones/%s" % (project, nz))
        rec["selfLink"] = V._selflink(nfull)
        bucket[nfull] = rec
    return V._json(200, V._operation(store, project, None, verb, project, V._selflink("projects/%s" % project)))


def _machine_image(store, method, project, name, verb, payload):
    V = _v()
    full = "projects/%s/global/machineImages/%s" % (project, name)
    rec = V._get(store, store.machine_images, full, "machine image")
    if verb in ("getIamPolicy", "setIamPolicy", "testIamPermissions"):
        return _policy_verbs(store, rec, verb, method, payload)
    if verb == "setLabels" and method == "POST":
        _set_labels(rec, payload)
        return V._json(200, V._operation(store, project, None, "setLabels", name, V._selflink(full)))
    return None


def _bulk_labels(store, method, project, zone, payload):
    V = _v()
    if method != "POST":
        return None
    labels = dict(payload.get("labels") or {})
    flt = payload.get("filter") or ""
    n = 0
    for full, d in store.disks.items():
        if not full.startswith("projects/%s/zones/%s/disks/" % (project, zone)):
            continue
        if flt and not (flt.startswith("name") and V._last(full) in flt):
            continue
        d["labels"] = dict(d.get("labels") or {}, **labels)
        d["labelFingerprint"] = V._fingerprint(d["labels"])
        n += 1
    return V._json(200, V._operation(store, project, zone, "bulkSetLabels", "%d-disks" % n, V._selflink("projects/%s/zones/%s" % (project, zone))))


def V_stop_group(store, project, zone, payload):
    V = _v()
    n = 0
    for full, d in store.disks.items():
        if full.startswith("projects/%s/zones/%s/disks/" % (project, zone)) and d.get("asyncPrimaryDisk"):
            d.pop("asyncPrimaryDisk", None)
            d.pop("asyncSecondaryDisks", None)
            n += 1
    return V._json(200, V._operation(store, project, zone, "stopGroupAsyncReplication", "group", V._selflink("projects/%s/zones/%s" % (project, zone))))
