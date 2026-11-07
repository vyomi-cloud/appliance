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
    if verb is None or verb == "":
        if len(segs) == 4 and segs[0] == "global" and segs[1] == "images" and segs[2] == "family" and method == "GET":
            return _from_family(store, project, segs[3])
        return None
    try:
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
          "listReferrers", "setShieldedInstanceConfig", "performMaintenance"}


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
    if verb == "listReferrers" and method == "GET":
        return V._json(200, {"kind": "compute#instanceListReferrers", "items": [
            {"kind": "compute#reference", "referrer": V._selflink(n), "referenceType": "REFERENCED_BY", "target": V._selflink(full)}
            for n, g in sorted(getattr(store, "instance_groups", {}).items()) if V._selflink(full) in [V._selflink(m) if "://" not in m else m for m in g.get("_members", [])]]})
    return None
