# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Compute Engine REST (`/compute/v1/...`), the wire `gcloud compute` and the Compute client
libraries speak: networks, subnetworks, firewalls, instances, and the lookups they need (zones,
regions, machine types, images, project, operations).

Serves the SAME records the Nano console shows: networks and instances are ResourceStore
records, subnets and firewalls the console's durable child collections (core/gcp_console_tabs).
Mutations finish immediately, so every Operation comes back DONE.
"""
from __future__ import annotations

import json
import re

from core import gcp_console_tabs as T

ACCOUNT = "default"
_ZONES = {"us-central1": "abcf", "us-east1": "bcd", "europe-west1": "bcd", "asia-south1": "abc"}
_MACHINE_CPUS = {"micro": 2, "small": 2, "medium": 2}


class ComputeError(Exception):
    def __init__(self, status: int, reason: str, message: str):
        super().__init__(message)
        self.status, self.reason, self.message = status, reason, message


def _reply(status, obj):
    return {"status": status, "headers": {"content-type": "application/json"}, "body": json.dumps(obj).encode()}


def _coll(res, service):
    return res.collections.setdefault("gcp/%s/%s" % (ACCOUNT, service), {})


class _Ctx:
    def __init__(self, res, root, project, base):
        self.res, self.root, self.project, self.base = res, root, project, base

    def url(self, *parts):
        return "/".join((self.base, "projects", self.project) + parts)

    def subnets(self, network=None):
        out = []
        for key in [k for k in self.root if k.startswith("vpc/") and k.endswith("/subnets")]:
            if key.split("/")[1] == "_project":
                continue
            for s in self.root[key].values():
                if network is None or s.get("network") == network:
                    out.append(s)
        return out

    def firewalls(self):
        return T.children(self.root, "vpc", "_project", "firewalls", create=True)

    def operation(self, kind, target, scope=None):
        now = T.now_iso()
        name = "operation-%s" % T.numeric_id("%s:%s:%s" % (kind, target, now))
        op = {"kind": "compute#operation", "id": T.numeric_id(name), "name": name, "operationType": kind,
              "targetLink": target, "targetId": T.numeric_id(target), "status": "DONE", "progress": 100,
              "insertTime": now, "startTime": now, "endTime": now, "user": "nano@vyomi.cloud"}
        if scope and scope[0] == "zones":
            op["zone"] = self.url("zones", scope[1])
            op["selfLink"] = self.url("zones", scope[1], "operations", name)
        elif scope and scope[0] == "regions":
            op["region"] = self.url("regions", scope[1])
            op["selfLink"] = self.url("regions", scope[1], "operations", name)
        else:
            op["selfLink"] = self.url("global", "operations", name)
        return op


def _network_view(c, rec):
    name = rec["name"]
    return {"kind": "compute#network", "id": T.numeric_id("network:" + name), "name": name,
            "selfLink": c.url("global", "networks", name),
            "creationTimestamp": rec.get("creationTimestamp") or rec.get("created") or T.now_iso(),
            "autoCreateSubnetworks": bool(rec.get("autoCreateSubnetworks")),
            "routingConfig": rec.get("routingConfig") or {"routingMode": "REGIONAL"},
            "mtu": rec.get("mtu") or 1460, "networkFirewallPolicyEnforcementOrder": "AFTER_CLASSIC_FIREWALL",
            "subnetworks": [c.url("regions", s["region"], "subnetworks", s["name"]) for s in c.subnets(name)]}


def _subnet_view(c, s):
    return {**s, "kind": "compute#subnetwork", "id": T.numeric_id("subnet:%s/%s" % (s["region"], s["name"])),
            "creationTimestamp": s.get("creationTimestamp") or T.now_iso(),
            "network": c.url("global", "networks", s["network"]), "region": c.url("regions", s["region"]),
            "selfLink": c.url("regions", s["region"], "subnetworks", s["name"])}


def _firewall_view(c, f):
    return {**f, "kind": "compute#firewall", "id": T.numeric_id("firewall:" + f["name"]),
            "creationTimestamp": f.get("creationTimestamp") or T.now_iso(), "direction": f.get("direction") or "INGRESS",
            "priority": f.get("priority", 1000), "network": c.url("global", "networks", f.get("network") or "default"),
            "selfLink": c.url("global", "firewalls", f["name"])}


def _instance_view(c, rec):
    zone = T.short(rec.get("zone") or "us-central1-a")
    v = T.describe_instance(rec, c.project, zone)
    region = zone.rsplit("-", 1)[0]
    nics = []
    for n in v.get("networkInterfaces") or []:
        nics.append({**n, "kind": "compute#networkInterface",
                     "network": c.url("global", "networks", T.short(n.get("network") or "default")),
                     "subnetwork": c.url("regions", region, "subnetworks", T.short(n.get("subnetwork") or "default"))})
    status = str(v.get("status") or "RUNNING").upper()
    return {**v, "kind": "compute#instance", "status": "RUNNING" if status == "AVAILABLE" else status,
            "zone": c.url("zones", zone), "machineType": c.url("zones", zone, "machineTypes", T.short(v.get("machineType"))),
            "networkInterfaces": nics, "selfLink": c.url("zones", zone, "instances", v["name"])}


def _not_found(what):
    return ComputeError(404, "notFound", "The resource '%s' was not found" % what)


def _list(kind, c, items, path):
    return {"kind": kind, "id": path, "items": items, "selfLink": c.base + "/" + path}


def _networks(c, m, name, body):
    coll = _coll(c.res, "vpc")
    if name is None:
        if m == "GET":
            return 200, _list("compute#networkList", c, [_network_view(c, r) for r in coll.values()], "projects/%s/global/networks" % c.project)
        if m != "POST":
            raise ComputeError(405, "httpMethodNotAllowed", "Method not allowed.")
        name = T.validate_name(body.get("name"), "resource.name")
        if name in coll:
            raise ComputeError(409, "alreadyExists", "The resource '%s' already exists" % c.url("global", "networks", name).split("/compute/v1/")[-1])
        auto = bool(body.get("autoCreateSubnetworks"))
        coll[name] = {"name": name, "status": "available", "autoCreateSubnetworks": auto, "mode": "auto" if auto else "custom",
                      "routingConfig": body.get("routingConfig") or {"routingMode": "REGIONAL"},
                      "mtu": body.get("mtu") or 1460, "creationTimestamp": T.now_iso(), "description": str(body.get("description") or "")}
        if auto:
            subs = T.children(c.root, "vpc", name, "subnets", create=True)
            for s in T.auto_subnets(name):
                subs["%s/%s" % (s["region"], s["name"])] = {**s, "creationTimestamp": T.now_iso()}
        return 200, c.operation("insert", c.url("global", "networks", name))
    rec = coll.get(name)
    if rec is None:
        raise _not_found("projects/%s/global/networks/%s" % (c.project, name))
    if m == "GET":
        return 200, _network_view(c, rec)
    if m != "DELETE":
        raise ComputeError(405, "httpMethodNotAllowed", "Method not allowed.")
    # Real Compute refuses while something still uses the network (auto-mode subnets go with it).
    in_use = [s["name"] for s in c.subnets(name) if not s.get("autoCreated")]
    in_use += [f["name"] for f in c.firewalls().values() if f.get("network") == name]
    in_use += [i["name"] for i in _coll(c.res, "compute").values()
               if any(T.short(n.get("network")) == name for n in (i.get("networkInterfaces") or []))]
    if in_use:
        raise ComputeError(400, "resourceInUseByAnotherResource",
                           "The network resource 'projects/%s/global/networks/%s' is already being used by '%s'" % (c.project, name, in_use[0]))
    del coll[name]
    c.root.pop("vpc/%s/subnets" % name, None)
    return 200, c.operation("delete", c.url("global", "networks", name))


def _subnetworks(c, m, region, name, body):
    if name is None:
        if m == "GET":
            items = [_subnet_view(c, s) for s in c.subnets() if s.get("region") == region]
            return 200, _list("compute#subnetworkList", c, items, "projects/%s/regions/%s/subnetworks" % (c.project, region))
        if m != "POST":
            raise ComputeError(405, "httpMethodNotAllowed", "Method not allowed.")
        network = T.short(body.get("network"))
        if network not in _coll(c.res, "vpc"):
            raise _not_found("projects/%s/global/networks/%s" % (c.project, network))
        rec = T.validate_subnet({**body, "region": region}, network, c.subnets())
        rec["creationTimestamp"] = T.now_iso()
        T.children(c.root, "vpc", network, "subnets", create=True)["%s/%s" % (region, rec["name"])] = rec
        return 200, c.operation("insert", c.url("regions", region, "subnetworks", rec["name"]), ("regions", region))
    found = next((s for s in c.subnets() if s.get("region") == region and s.get("name") == name), None)
    if found is None:
        raise _not_found("projects/%s/regions/%s/subnetworks/%s" % (c.project, region, name))
    if m == "GET":
        return 200, _subnet_view(c, found)
    if m != "DELETE":
        raise ComputeError(405, "httpMethodNotAllowed", "Method not allowed.")
    T.children(c.root, "vpc", found["network"], "subnets").pop("%s/%s" % (region, name), None)
    return 200, c.operation("delete", c.url("regions", region, "subnetworks", name), ("regions", region))


def _firewalls(c, m, name, body):
    coll = c.firewalls()
    if name is None:
        if m == "GET":
            return 200, _list("compute#firewallList", c, [_firewall_view(c, f) for f in coll.values()], "projects/%s/global/firewalls" % c.project)
        if m != "POST":
            raise ComputeError(405, "httpMethodNotAllowed", "Method not allowed.")
        name = T.validate_name(body.get("name"), "resource.name")
        if name in coll:
            raise ComputeError(409, "alreadyExists", "The resource 'projects/%s/global/firewalls/%s' already exists" % (c.project, name))
        network = T.short(body.get("network")) or "default"
        if network != "default" and network not in _coll(c.res, "vpc"):
            raise _not_found("projects/%s/global/networks/%s" % (c.project, network))
        coll[name] = {**{k: v for k, v in body.items() if k != "network"}, "name": name, "network": network, "creationTimestamp": T.now_iso()}
        return 200, c.operation("insert", c.url("global", "firewalls", name))
    if name not in coll:
        raise _not_found("projects/%s/global/firewalls/%s" % (c.project, name))
    if m == "GET":
        return 200, _firewall_view(c, coll[name])
    if m != "DELETE":
        raise ComputeError(405, "httpMethodNotAllowed", "Method not allowed.")
    del coll[name]
    return 200, c.operation("delete", c.url("global", "firewalls", name))


def _instances(c, m, zone, name, action, body):
    coll = _coll(c.res, "compute")
    in_zone = lambda r: T.short(r.get("zone") or "us-central1-a") == zone
    if name is None:
        if m == "GET":
            return 200, _list("compute#instanceList", c, [_instance_view(c, r) for r in coll.values() if in_zone(r)], "projects/%s/zones/%s/instances" % (c.project, zone))
        if m != "POST":
            raise ComputeError(405, "httpMethodNotAllowed", "Method not allowed.")
        name = T.validate_name(body.get("name"), "resource.name")
        if name in coll:
            raise ComputeError(409, "alreadyExists", "The resource 'projects/%s/zones/%s/instances/%s' already exists" % (c.project, zone, name))
        rec = {"name": name, "zone": zone, "machineType": T.short(body.get("machineType") or "e2-medium")}
        for k in ("labels", "metadata", "tags", "description"):
            if body.get(k):
                rec[k] = body[k]
        nics = body.get("networkInterfaces") or []
        described = T.describe_instance(rec, c.project, zone)
        if nics:
            first = described["networkInterfaces"][0]
            first.update(network=T.short(nics[0].get("network") or "default"), subnetwork=T.short(nics[0].get("subnetwork") or nics[0].get("network") or "default"))
            if not nics[0].get("accessConfigs"):
                first.pop("accessConfigs", None)
        coll[name] = described
        return 200, c.operation("insert", c.url("zones", zone, "instances", name), ("zones", zone))
    rec = coll.get(name)
    if rec is None or not in_zone(rec):
        raise _not_found("projects/%s/zones/%s/instances/%s" % (c.project, zone, name))
    if action:
        if m != "POST" or action not in ("start", "stop", "reset"):
            raise ComputeError(400, "invalid", "Unsupported instance action '%s'." % action)
        rec["status"] = "TERMINATED" if action == "stop" else "RUNNING"
        return 200, c.operation(action, c.url("zones", zone, "instances", name), ("zones", zone))
    if m == "GET":
        return 200, _instance_view(c, rec)
    if m != "DELETE":
        raise ComputeError(405, "httpMethodNotAllowed", "Method not allowed.")
    del coll[name]
    return 200, c.operation("delete", c.url("zones", zone, "instances", name), ("zones", zone))


def _aggregated(c, what):
    scopes = {}
    if what == "instances":
        for r in _coll(c.res, "compute").values():
            z = T.short(r.get("zone") or "us-central1-a")
            scopes.setdefault("zones/" + z, {"instances": []})["instances"].append(_instance_view(c, r))
        return {"kind": "compute#instanceAggregatedList", "items": scopes, "selfLink": c.url("aggregated", "instances")}
    for s in c.subnets():
        scopes.setdefault("regions/" + s["region"], {"subnetworks": []})["subnetworks"].append(_subnet_view(c, s))
    return {"kind": "compute#subnetworkAggregatedList", "items": scopes, "selfLink": c.url("aggregated", "subnetworks")}


def _region_view(c, r):
    return {"kind": "compute#region", "id": T.numeric_id("region:" + r), "name": r, "status": "UP", "selfLink": c.url("regions", r),
            "zones": [c.url("zones", "%s-%s" % (r, z)) for z in _ZONES[r]]}


def _zone_view(c, z):
    r = z.rsplit("-", 1)[0]
    return {"kind": "compute#zone", "id": T.numeric_id("zone:" + z), "name": z, "status": "UP", "region": c.url("regions", r), "selfLink": c.url("zones", z)}


def _all_zones():
    return ["%s-%s" % (r, z) for r, zs in _ZONES.items() for z in zs]


def _lookups(c, parts):
    """Read-only lookups gcloud makes around a create. Returns (status, obj) or None."""
    if parts == ["regions"]:
        return 200, _list("compute#regionList", c, [_region_view(c, r) for r in _ZONES], "projects/%s/regions" % c.project)
    if len(parts) == 2 and parts[0] == "regions":
        if parts[1] not in _ZONES:
            raise _not_found("projects/%s/regions/%s" % (c.project, parts[1]))
        return 200, _region_view(c, parts[1])
    if parts == ["zones"]:
        return 200, _list("compute#zoneList", c, [_zone_view(c, z) for z in _all_zones()], "projects/%s/zones" % c.project)
    if len(parts) == 2 and parts[0] == "zones":
        if parts[1] not in _all_zones():
            raise _not_found("projects/%s/zones/%s" % (c.project, parts[1]))
        return 200, _zone_view(c, parts[1])
    if len(parts) == 4 and parts[0] == "zones" and parts[2] == "machineTypes":
        t = parts[3]
        cpus = _MACHINE_CPUS.get(t.rsplit("-", 1)[-1])
        if cpus is None:
            cpus = int(t.rsplit("-", 1)[-1]) if t.rsplit("-", 1)[-1].isdigit() else 2
        return 200, {"kind": "compute#machineType", "id": T.numeric_id("mt:" + t), "name": t, "guestCpus": cpus, "memoryMb": cpus * 4096,
                     "zone": parts[1], "selfLink": c.url("zones", parts[1], "machineTypes", t)}
    if len(parts) == 4 and parts[2] == "operations":   # zones|regions/{x}/operations/{op}[/wait]
        return 200, {"kind": "compute#operation", "name": parts[3], "status": "DONE", "progress": 100, "selfLink": c.url(*parts)}
    if len(parts) == 5 and parts[2] == "operations" and parts[4] == "wait":
        return 200, {"kind": "compute#operation", "name": parts[3], "status": "DONE", "progress": 100, "selfLink": c.url(*parts[:4])}
    if len(parts) == 3 and parts[:2] == ["global", "operations"]:
        return 200, {"kind": "compute#operation", "name": parts[2], "status": "DONE", "progress": 100, "selfLink": c.url(*parts)}
    if len(parts) == 4 and parts[:2] == ["global", "operations"] and parts[3] == "wait":
        return 200, {"kind": "compute#operation", "name": parts[2], "status": "DONE", "progress": 100, "selfLink": c.url(*parts[:3])}
    return None


def dispatch(res, root, project: dict, method, path, headers=None, body=b""):
    """`res`: the shared resource store ({ns: {name: record}}); `root`: the console's durable child
    collections; `project`: {projectId, projectNumber}. Returns {status, headers, body}."""
    headers = {str(k).lower(): v for k, v in (headers or {}).items()}
    base = "http://%s/compute/v1" % (headers.get("host") or "compute.googleapis.com")
    m = method.upper()
    match = re.match(r"^/compute/v1/projects/([^/]+)(?:/(.*))?$", path.split("?", 1)[0])
    try:
        if not match:
            raise _not_found(path)
        named, rest = match.group(1), [p for p in (match.group(2) or "").split("/") if p]
        # Public image projects (debian-cloud, ...) answer image lookups whatever project this is.
        if len(rest) >= 3 and rest[:2] == ["global", "images"]:
            family = rest[3] if rest[2] == "family" and len(rest) > 3 else ""
            name = family or rest[2]
            url = "%s/projects/%s/global/images/%s" % (base, named, name)
            return _reply(200, {"kind": "compute#image", "id": T.numeric_id("image:" + name), "name": name, "family": family or name,
                                "status": "READY", "diskSizeGb": "10", "selfLink": url})
        if named not in (project.get("projectId"), project.get("projectNumber")):
            raise ComputeError(404, "notFound", "The resource 'projects/%s' was not found" % named)
        c = _Ctx(res, root, project["projectId"], base)
        try:
            data = json.loads(bytes(body).decode() or "{}") if body else {}
        except ValueError:
            raise ComputeError(400, "parseError", "Parse Error")
        if not rest:
            return _reply(200, {"kind": "compute#project", "id": project.get("projectNumber"), "name": c.project,
                                "commonInstanceMetadata": {"items": []}, "defaultNetworkTier": "PREMIUM", "selfLink": c.url()})
        if rest[:1] == ["aggregated"] and len(rest) == 2 and rest[1] in ("instances", "subnetworks"):
            return _reply(200, _aggregated(c, rest[1]))
        if rest[:2] == ["global", "networks"] and len(rest) <= 3:
            st, obj = _networks(c, m, rest[2] if len(rest) == 3 else None, data)
        elif rest[:2] == ["global", "firewalls"] and len(rest) <= 3:
            st, obj = _firewalls(c, m, rest[2] if len(rest) == 3 else None, data)
        elif rest[0] == "regions" and len(rest) >= 3 and rest[2] == "subnetworks" and len(rest) <= 4:
            st, obj = _subnetworks(c, m, rest[1], rest[3] if len(rest) == 4 else None, data)
        elif rest[0] == "zones" and len(rest) >= 3 and rest[2] == "instances" and len(rest) <= 5:
            st, obj = _instances(c, m, rest[1], rest[3] if len(rest) >= 4 else None, rest[4] if len(rest) == 5 else None, data)
        else:
            found = _lookups(c, rest)
            if found is None:
                raise _not_found(path)
            st, obj = found
        return _reply(st, obj)
    except ComputeError as e:
        return _reply(e.status, {"error": {"code": e.status, "message": e.message,
                                           "errors": [{"domain": "global", "reason": e.reason, "message": e.message}]}})
    except T.TabError as e:
        status = getattr(e, "status", 400)
        msg = getattr(e, "message", str(e))
        reason = {409: "alreadyExists", 404: "notFound"}.get(status, "invalid")
        return _reply(status, {"error": {"code": status, "message": msg, "errors": [{"domain": "global", "reason": reason, "message": msg}]}})
