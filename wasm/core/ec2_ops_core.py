# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""EC2 operations extras merged into vpc_core._OPS (AWS-03 / AWS-04): scheduled instance events,
Availability Zones / Local Zone opt-in groups, Spot requests + price history, Reserved Instances,
Capacity Reservations, Dedicated Hosts and the EC2 Recycle Bin (EC2 Query actions + the native
`rbin` REST-JSON service). State lives in the shared EC2/VPC model (`_vpc_model`), so it persists
on both substrates. No fastapi / boto3 imports — loads under Pyodide.

Honest limits (see core/capabilities/aws/ec2.json): there is no billing — prices are illustrative
on-demand multiples; Spot prices are a deterministic hourly function, never real market prices and
no capacity-driven interruptions; reservations/hosts really constrain launches but there is no
physical hardware behind them; Savings Plans, Capacity Manager and UltraServers are not modeled."""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote


def _V():
    from core import vpc_core
    return vpc_core


def _err(code, msg, status=400):
    return _V().VpcError(code, msg, status)


def _x(v):
    return _V()._xml_escape(str(v))


def _iso(ts):
    return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _epoch(s):
    """ISO-8601 (or epoch) -> float seconds; raises on garbage."""
    try:
        return float(s)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise _err("InvalidParameterValue", f"Value ({s}) is not a valid timestamp.")


def _iso_any(s):
    """The vpc_core model stores times as ISO strings; tolerate floats."""
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return _epoch(s)
    except Exception:
        return time.time()


def _bag(m, name):
    return m.setdefault(name, {})


def _idx(p, prefix):
    """`Prefix.N` -> values in numeric order."""
    out = {}
    for k, v in p.items():
        mm = re.match(rf"{re.escape(prefix)}\.(\d+)$", k)
        if mm:
            out[int(mm.group(1))] = v
    return [out[i] for i in sorted(out)]


def _filters(p):
    out = {}
    for k, v in p.items():
        mm = re.match(r"Filter\.(\d+)\.Name$", k)
        if mm:
            out[str(v)] = [str(p[kk]) for kk in sorted(p) if kk.startswith(f"Filter.{mm.group(1)}.Value.")]
    return out


def _bool(p, k, default=False):
    v = p.get(k)
    return default if v is None else str(v).lower() == "true"


def _reply(action, inner):
    return _V()._envelope(action, inner)


def _xml(v, tag=None):
    if isinstance(v, bool):
        s = "true" if v else "false"
    elif isinstance(v, dict):
        s = "".join(_xml(x, k) for k, x in v.items() if x is not None)
    elif isinstance(v, list):
        s = "".join(_xml(x, "item") for x in v)
    elif v is None:
        s = ""
    else:
        s = _x(v)
    return f"<{tag}>{s}</{tag}>" if tag else s


def _tags(t):
    return {"tagSet": [{"key": k, "value": v} for k, v in (t or {}).items()]}


def _specs(p, rtype):
    return _V()._parse_tag_specifications(p).get(rtype, {})


def _od_price(itype):
    """Illustrative on-demand hourly price (no billing): scales with vCPU + memory."""
    spec = _V()._INSTANCE_TYPES.get(itype)
    if not spec:
        return 0.05
    return round(spec["vcpu"] * 0.0045 + spec["mem"] * 0.006, 4)


# ── Availability Zones + Local/Wavelength Zone opt-in ─────────────────────────────────────────
_EXTRA_ZONES = [
    ("us-east-1-bos-1a", "use1-bos1-az1", "local-zone", "us-east-1-bos-1", "us-east-1a"),
    ("us-east-1-nyc-1a", "use1-nyc1-az1", "local-zone", "us-east-1-nyc-1", "us-east-1a"),
    ("us-east-1-wl1-bos-wlz-1", "use1-wl1-bos-wlz1", "wavelength-zone", "us-east-1-wl1", "us-east-1a"),
]


def _zone_rows(m):
    groups = _bag(m["account"], "az_groups")
    rows = []
    for i, az in enumerate(_V()._AZS):
        rows.append({"zoneName": az, "zoneId": f"use1-az{i + 1}", "zoneType": "availability-zone", "groupName": "us-east-1-zg-1",
                     "optInStatus": "opt-in-not-required", "parentZoneName": None})
    for name, zid, ztype, grp, parent in _EXTRA_ZONES:
        opted = groups.get(grp) == "opted-in"
        rows.append({"zoneName": name, "zoneId": zid, "zoneType": ztype, "groupName": grp,
                     "optInStatus": "opted-in" if opted else "not-opted-in", "parentZoneName": parent})
    return rows


def _describe_azs(store, p):
    m = _V()._model(store)
    names, ids = _idx(p, "ZoneName"), _idx(p, "ZoneId")
    flt = _filters(p)
    show_all = _bool(p, "AllAvailabilityZones")
    out = []
    for z in _zone_rows(m):
        if names and z["zoneName"] not in names:
            continue
        if ids and z["zoneId"] not in ids:
            continue
        if not show_all and not names and not ids and z["optInStatus"] == "not-opted-in":
            continue
        if any(z.get({"zone-name": "zoneName", "zone-id": "zoneId", "zone-type": "zoneType", "group-name": "groupName",
                      "opt-in-status": "optInStatus", "parent-zone-name": "parentZoneName"}.get(k, k)) not in vals
               for k, vals in flt.items() if k in ("zone-name", "zone-id", "zone-type", "group-name", "opt-in-status", "parent-zone-name")):
            continue
        state = flt.get("state")
        if state and "available" not in state:
            continue
        out.append({**z, "zoneState": "available", "regionName": "us-east-1", "networkBorderGroup": z["groupName"] if z["zoneType"] != "availability-zone" else "us-east-1",
                    "messageSet": []})
    items = "".join(
        f"<item><zoneName>{_x(z['zoneName'])}</zoneName><zoneId>{_x(z['zoneId'])}</zoneId><zoneState>available</zoneState><state>available</state>"
        f"<regionName>us-east-1</regionName><zoneType>{z['zoneType']}</zoneType><groupName>{_x(z['groupName'])}</groupName>"
        f"<networkBorderGroup>{_x(z['networkBorderGroup'])}</networkBorderGroup><optInStatus>{z['optInStatus']}</optInStatus>"
        + (f"<parentZoneName>{_x(z['parentZoneName'])}</parentZoneName>" if z["parentZoneName"] else "") + "<messageSet/></item>" for z in out)
    return _reply("DescribeAvailabilityZones", f"<availabilityZoneInfo>{items}</availabilityZoneInfo>")


def _modify_az_group(store, p):
    m = _V()._model(store)
    grp, status = str(p.get("GroupName") or ""), str(p.get("OptInStatus") or "")
    known = {g[3] for g in _EXTRA_ZONES}
    if grp not in known:
        raise _err("InvalidParameterValue", f"The zone group '{grp}' does not exist or does not require opt-in.")
    if status not in ("opted-in", "not-opted-in"):
        raise _err("InvalidParameterValue", "OptInStatus must be one of: opted-in | not-opted-in.")
    if status == "not-opted-in" and any(i["state"] in ("pending", "running", "stopped") and i["az"].startswith(grp.rsplit("-", 1)[0])
                                        and i["az"] in {z[0] for z in _EXTRA_ZONES if z[3] == grp} for i in m["instances"].values()):
        raise _err("InvalidParameterValue", f"Zone group {grp} still has instances; terminate them before opting out.")
    _bag(m["account"], "az_groups")[grp] = status
    return _reply("ModifyAvailabilityZoneGroup", "<return>true</return>")


# ── Scheduled events (DescribeInstanceStatus eventsSet) ───────────────────────────────────────
_EVENT_CODES = {"instance-reboot", "system-reboot", "system-maintenance", "instance-retirement", "instance-stop"}


def settle_events(m, now=None):
    """Lazily complete events whose NotBefore passed: instance-stop / instance-retirement stop the
    instance (through the same state-change path as StopInstances); reboots/maintenance are no-ops."""
    now = now or time.time()
    for inst in list(m["instances"].values()):
        for ev in inst.get("events", []):
            if ev["state"] == "scheduled" and ev["not_before"] <= now:
                ev["state"] = "completed"
                ev["description"] = "[Completed] " + ev["description"].replace("[Completed] ", "")
                if ev["code"] in ("instance-stop", "instance-retirement") and inst["state"] in ("running", "pending"):
                    try:
                        _V()._instance_state_change(_StoreShim(m), {"InstanceId.1": inst["id"], "Force": "true"}, "stop", "stopped")
                    except Exception:
                        inst["state"] = "stopped"


class _StoreShim:
    """_instance_state_change expects a store; it only reads the model off it."""
    def __init__(self, m):
        self._vpc_model = m


def events_xml(inst):
    evs = inst.get("events", [])
    if not evs:
        return "<eventsSet/>"
    return "<eventsSet>" + "".join(
        f"<item><instanceEventId>{_x(e['id'])}</instanceEventId><code>{e['code']}</code><description>{_x(e['description'])}</description>"
        f"<notBefore>{_iso(e['not_before'])}</notBefore><notAfter>{_iso(e['not_after'])}</notAfter>"
        f"<notBeforeDeadline>{_iso(e['deadline'])}</notBeforeDeadline></item>" for e in evs) + "</eventsSet>"


def _schedule_event(store, p):
    """Simulator-only helper (AWS has no API that creates an event): schedule a maintenance event."""
    m = _V()._model(store)
    inst = _V()._find_instance(m, p.get("InstanceId"))
    code = str(p.get("Code") or "system-reboot")
    if code not in _EVENT_CODES:
        raise _err("InvalidParameterValue", f"Code must be one of {sorted(_EVENT_CODES)}.")
    nb = _epoch(p["NotBefore"]) if p.get("NotBefore") else time.time() + 3 * 86400
    ev = {"id": "instance-event-" + uuid.uuid4().hex[:17], "code": code, "state": "scheduled", "not_before": nb,
          "not_after": nb + 3600, "deadline": nb + 7 * 86400, "description": str(p.get("Description") or code)}
    inst.setdefault("events", []).append(ev)
    return _reply("VyomiScheduleInstanceEvent", f"<instanceEventId>{ev['id']}</instanceEventId>")


def _modify_event_start(store, p):
    m = _V()._model(store)
    inst = _V()._find_instance(m, p.get("InstanceId"))
    ev = next((e for e in inst.get("events", []) if e["id"] == p.get("InstanceEventId")), None)
    if ev is None:
        raise _err("InvalidInstanceEventID.NotFound", f"The instance event '{p.get('InstanceEventId')}' does not exist.")
    nb = _epoch(p.get("NotBefore"))
    if ev["state"] == "completed":
        raise _err("InvalidParameterValue", "A completed event cannot be rescheduled.")
    if nb > ev["deadline"]:
        raise _err("InvalidParameterValue", "NotBefore is later than the event's NotBeforeDeadline.")
    if nb < time.time():
        raise _err("InvalidParameterValue", "NotBefore must be in the future.")
    ev["not_after"] += nb - ev["not_before"]
    ev["not_before"] = nb
    return _reply("ModifyInstanceEventStartTime", "<return>true</return>")


# ── Spot ─────────────────────────────────────────────────────────────────────────────────────
def spot_price(itype, az, ts=None):
    """Deterministic hourly price: 30%..65% of the illustrative on-demand price."""
    hour = int((ts or time.time()) // 3600)
    h = int(hashlib.md5(f"{itype}|{az}|{hour}".encode()).hexdigest()[:6], 16) % 1000 / 1000.0
    return round(_od_price(itype) * (0.30 + 0.35 * h), 4)


def _spot_xml(r):
    st = {"code": r["status"], "message": r["message"], "updateTime": _iso(r["updated"])}
    ls = {"imageId": r["launch"].get("ImageId", ""), "instanceType": r["launch"].get("InstanceType", "t3.micro"),
          "placement": {"availabilityZone": r["launch"].get("Placement.AvailabilityZone", "")}}
    return _xml({"spotInstanceRequestId": r["id"], "spotPrice": f"{r['max_price']:.6f}", "type": r["type"], "state": r["state"],
                 "status": st, "createTime": _iso(r["created"]), "productDescription": "Linux/UNIX", "launchSpecification": ls,
                 "instanceId": r.get("instance_id") or None, "validUntil": _iso(r["valid_until"]) if r.get("valid_until") else None,
                 "launchedAvailabilityZone": r.get("az") or None, **_tags(r.get("tags"))}, "item")


def _offline_runtime(store):
    """True on the offline appliance, whose instance/AMI runtime (server.py, Docker) is separate from this core model."""
    return type(store).__name__ == "_Ec2CoreSpaceStore"


def _launch_params(r):
    p = dict(r["launch"])
    p["MinCount"] = p["MaxCount"] = 1
    return p


def settle_spot(store, m):
    now = time.time()
    for r in _bag(m, "spot_requests").values():
        if r["state"] in ("closed", "cancelled", "failed"):
            continue
        if r.get("valid_until") and now > r["valid_until"] and r["state"] == "open":
            r.update(state="closed", status="schedule-expired", message="Your Spot request has expired.", updated=now)
            continue
        if r["state"] == "active":
            inst = m["instances"].get(r["instance_id"])
            if inst is None or inst["state"] in ("terminated", "shutting-down"):
                if r["type"] == "persistent":
                    r.update(state="open", status="pending-evaluation", message="Your Spot request is pending evaluation.", instance_id="", updated=now)
                else:
                    r.update(state="closed", status="instance-terminated-by-user", message="Spot Instance terminated by user.", updated=now)
            if r["state"] != "open":
                continue
        if r["state"] == "open":
            az = r["launch"].get("Placement.AvailabilityZone") or _V()._AZS[0]
            price = spot_price(r["launch"].get("InstanceType", "t3.micro"), az, now)
            if price > r["max_price"]:
                r.update(status="price-too-low", message="Your Spot request price is lower than the minimum required Spot request fulfillment price.", updated=now)
                continue
            if _offline_runtime(store):
                r.update(state="failed", status="system-error", updated=now,
                         message="The offline appliance launches instances through its Docker runtime, which Spot fulfilment is not wired into; Spot launches run on the shared core (Nano).")
                continue
            try:
                tags = dict(r.get("instance_tags", {}))
                inst = _V()._launch_one(m, _launch_params(r), {"instance": tags}, 0)
            except _V().VpcError as e:
                r.update(state="failed", status="bad-parameters", message=e.message, updated=now)
                continue
            inst.update(lifecycle="spot", spot_request_id=r["id"])
            r.update(state="active", status="fulfilled", message="Your Spot request is fulfilled.", instance_id=inst["id"], az=inst["az"], updated=now)


def _new_spot(m, launch, max_price, typ, valid_until, tags, instance_tags):
    rid = "sir-" + uuid.uuid4().hex[:8]
    now = time.time()
    r = {"id": rid, "launch": launch, "max_price": max_price, "type": typ, "valid_until": valid_until, "created": now, "updated": now,
         "state": "open", "status": "pending-evaluation", "message": "Your Spot request is pending evaluation.",
         "instance_id": "", "az": "", "tags": tags, "instance_tags": instance_tags}
    _bag(m, "spot_requests")[rid] = r
    return r


def _request_spot(store, p):
    m = _V()._model(store)
    launch = {k[len("LaunchSpecification."):]: v for k, v in p.items() if k.startswith("LaunchSpecification.")}
    if not launch.get("ImageId"):
        raise _err("MissingParameter", "The request must contain the parameter LaunchSpecification.ImageId.")
    if launch["ImageId"] not in m["images"]:
        _V()._seed_amis(m)
    if launch["ImageId"] not in m["images"] and not _offline_runtime(store):
        raise _err("InvalidAMIID.NotFound", f"The image id '[{launch['ImageId']}]' does not exist.")
    itype = launch.get("InstanceType", "t3.micro")
    if itype not in _V()._INSTANCE_TYPES:
        raise _err("InvalidParameterValue", f"The instance type '{itype}' is not supported.")
    price = float(p.get("SpotPrice") or _od_price(itype))
    typ = str(p.get("Type") or "one-time")
    if typ not in ("one-time", "persistent"):
        raise _err("InvalidParameterValue", "Type must be one-time or persistent.")
    count = int(p.get("InstanceCount") or 1)
    vu = _epoch(p["ValidUntil"]) if p.get("ValidUntil") else None
    out = []
    for _ in range(count):
        out.append(_new_spot(m, launch, price, typ, vu, _specs(p, "spot-instances-request"), {}))
    settle_spot(store, m)
    return _reply("RequestSpotInstances", f"<spotInstanceRequestSet>{''.join(_spot_xml(r) for r in out)}</spotInstanceRequestSet>")


def _describe_spot(store, p):
    m = _V()._model(store)
    settle_spot(store, m)
    ids = _idx(p, "SpotInstanceRequestId")
    flt = _filters(p)
    rows = [r for r in _bag(m, "spot_requests").values() if not ids or r["id"] in ids]
    if ids:
        for i in ids:
            if i not in _bag(m, "spot_requests"):
                raise _err("InvalidSpotInstanceRequestID.NotFound", f"The spot instance request ID '{i}' does not exist")
    if "state" in flt:
        rows = [r for r in rows if r["state"] in flt["state"]]
    if "status-code" in flt:
        rows = [r for r in rows if r["status"] in flt["status-code"]]
    return _reply("DescribeSpotInstanceRequests", f"<spotInstanceRequestSet>{''.join(_spot_xml(r) for r in rows)}</spotInstanceRequestSet>")


def _cancel_spot(store, p):
    m = _V()._model(store)
    out = []
    for rid in _idx(p, "SpotInstanceRequestId"):
        r = _bag(m, "spot_requests").get(rid)
        if r is None:
            raise _err("InvalidSpotInstanceRequestID.NotFound", f"The spot instance request ID '{rid}' does not exist")
        running = r["state"] == "active"
        r.update(state="cancelled", status="request-canceled-and-instance-running" if running else "canceled-before-fulfillment",
                 message="Request canceled; instance continues." if running else "Request canceled before fulfillment.", updated=time.time())
        out.append(f"<item><spotInstanceRequestId>{rid}</spotInstanceRequestId><state>cancelled</state></item>")
    return _reply("CancelSpotInstanceRequests", f"<spotInstanceRequestSet>{''.join(out)}</spotInstanceRequestSet>")


def _spot_history(store, p):
    types = _idx(p, "InstanceType") or ["t3.micro"]
    azs = [p["AvailabilityZone"]] if p.get("AvailabilityZone") else _V()._AZS
    end = _epoch(p["EndTime"]) if p.get("EndTime") else time.time()
    start = _epoch(p["StartTime"]) if p.get("StartTime") else end - 86400
    start = max(start, end - 7 * 86400)
    items = []
    t = int(end // 3600) * 3600
    while t >= start:
        for it in types:
            for az in azs:
                items.append(f"<item><instanceType>{_x(it)}</instanceType><productDescription>Linux/UNIX</productDescription>"
                             f"<spotPrice>{spot_price(it, az, t):.6f}</spotPrice><timestamp>{_iso(t)}</timestamp><availabilityZone>{az}</availabilityZone></item>")
        t -= 3600
    return _reply("DescribeSpotPriceHistory", f"<spotPriceHistorySet>{''.join(items)}</spotPriceHistorySet><nextToken/>")


# ── Reserved Instances ───────────────────────────────────────────────────────────────────────
_RI_TERMS = {"1yr": 31536000, "3yr": 94608000}
_RI_FACTOR = {("1yr", "No Upfront"): .70, ("1yr", "Partial Upfront"): .66, ("1yr", "All Upfront"): .63,
              ("3yr", "No Upfront"): .50, ("3yr", "Partial Upfront"): .45, ("3yr", "All Upfront"): .42}


def _offerings(types, cls=None, ptype=None, dur=None):
    out = []
    for it in types:
        for term, secs in _RI_TERMS.items():
            if dur and secs != dur:
                continue
            for pay in ("No Upfront", "Partial Upfront", "All Upfront"):
                if ptype and ptype != pay:
                    continue
                for oc in ("standard", "convertible"):
                    if cls and cls != oc:
                        continue
                    f = _RI_FACTOR[(term, pay)] + (0.05 if oc == "convertible" else 0)
                    rate = _od_price(it) * f
                    hours = secs / 3600
                    fixed = 0.0 if pay == "No Upfront" else rate * hours * (1 if pay == "All Upfront" else 0.5)
                    usage = 0.0 if pay == "All Upfront" else rate * (1 if pay == "No Upfront" else 0.5)
                    oid = hashlib.md5(f"{it}|{term}|{pay}|{oc}".encode()).hexdigest()
                    oid = f"{oid[:8]}-{oid[8:12]}-{oid[12:16]}-{oid[16:20]}-{oid[20:32]}"
                    out.append({"id": oid, "type": it, "duration": secs, "payment": pay, "class": oc, "fixed": round(fixed, 2), "usage": round(usage, 4)})
    return out


def _describe_ri_offerings(store, p):
    types = _idx(p, "InstanceType") or ([p["InstanceType"]] if p.get("InstanceType") else sorted(_V()._INSTANCE_TYPES))
    ids = _idx(p, "ReservedInstancesOfferingId")
    rows = _offerings(types, p.get("OfferingClass"), p.get("OfferingType"), int(p["MinDuration"]) if p.get("MinDuration") else None)
    if ids:
        rows = [r for r in _offerings(sorted(_V()._INSTANCE_TYPES)) if r["id"] in ids]
    maxr = int(p.get("MaxResults") or 100)
    items = "".join(_xml({"reservedInstancesOfferingId": r["id"], "instanceType": r["type"], "availabilityZone": p.get("AvailabilityZone") or None,
                           "duration": r["duration"], "fixedPrice": f"{r['fixed']:.1f}", "usagePrice": f"{r['usage']:.4f}",
                           "productDescription": "Linux/UNIX", "instanceTenancy": "default", "currencyCode": "USD",
                           "offeringClass": r["class"], "offeringType": r["payment"], "marketplace": False, "scope": "AvailabilityZone" if p.get("AvailabilityZone") else "Region"}, "item")
                    for r in rows[:maxr])
    return _reply("DescribeReservedInstancesOfferings", f"<reservedInstancesOfferingsSet>{items}</reservedInstancesOfferingsSet>")


def _purchase_ri(store, p):
    m = _V()._model(store)
    oid = str(p.get("ReservedInstancesOfferingId") or "")
    off = next((o for o in _offerings(sorted(_V()._INSTANCE_TYPES)) if o["id"] == oid), None)
    if off is None:
        raise _err("InvalidReservedInstancesOfferingId", f"The Reserved Instances offering '{oid}' does not exist.")
    count = int(p.get("InstanceCount") or 1)
    if count < 1 or count > 20:
        raise _err("InvalidParameterValue", "InstanceCount must be between 1 and 20.")
    if p.get("LimitPrice.Amount") and float(p["LimitPrice.Amount"]) < off["fixed"] * count:
        raise _err("PriceLimitExceeded", "The Reserved Instances' purchase price exceeds the limit price you specified.")
    now = time.time()
    rid = str(uuid.uuid4())
    _bag(m, "reserved_instances")[rid] = {"id": rid, "offering": off, "count": count, "start": now, "end": now + off["duration"],
                                          "az": str(p.get("AvailabilityZone") or ""), "tags": {}}
    return _reply("PurchaseReservedInstancesOffering", f"<reservedInstancesId>{rid}</reservedInstancesId>")


def _describe_ri(store, p):
    m = _V()._model(store)
    ids = _idx(p, "ReservedInstancesId")
    now = time.time()
    flt = _filters(p)
    rows = []
    for r in _bag(m, "reserved_instances").values():
        state = "active" if now < r["end"] else "retired"
        if ids and r["id"] not in ids:
            continue
        if "state" in flt and state not in flt["state"]:
            continue
        o = r["offering"]
        rows.append(_xml({"reservedInstancesId": r["id"], "instanceType": o["type"], "availabilityZone": r["az"] or None, "start": _iso(r["start"]),
                          "end": _iso(r["end"]), "duration": o["duration"], "fixedPrice": f"{o['fixed']:.1f}", "usagePrice": f"{o['usage']:.4f}",
                          "instanceCount": r["count"], "productDescription": "Linux/UNIX", "state": state, "instanceTenancy": "default",
                          "currencyCode": "USD", "offeringClass": o["class"], "offeringType": o["payment"],
                          "scope": "Availability Zone" if r["az"] else "Region", **_tags(r["tags"])}, "item"))
    return _reply("DescribeReservedInstances", f"<reservedInstancesSet>{''.join(rows)}</reservedInstancesSet>")


# ── Capacity Reservations ────────────────────────────────────────────────────────────────────
def _cr_used(m, cr):
    return sum(1 for i in m["instances"].values() if i.get("capacity_reservation_id") == cr["id"] and i["state"] in ("pending", "running"))


def _cr_settle(m):
    now = time.time()
    for cr in _bag(m, "capacity_reservations").values():
        if cr["state"] == "active" and cr["end_date"] and now >= cr["end_date"]:
            cr["state"] = "expired"


def _cr_xml(m, cr):
    used = _cr_used(m, cr)
    return _xml({"capacityReservationId": cr["id"], "capacityReservationArn": f"arn:aws:ec2:us-east-1:123456789012:capacity-reservation/{cr['id']}",
                 "ownerId": "123456789012", "instanceType": cr["type"], "instancePlatform": cr["platform"], "availabilityZone": cr["az"],
                 "tenancy": "default", "totalInstanceCount": cr["total"], "availableInstanceCount": max(cr["total"] - used, 0) if cr["state"] == "active" else 0,
                 "ebsOptimized": False, "ephemeralStorage": False, "state": cr["state"], "startDate": _iso(cr["created"]),
                 "endDate": _iso(cr["end_date"]) if cr["end_date"] else None, "endDateType": cr["end_date_type"],
                 "instanceMatchCriteria": cr["match"], "createDate": _iso(cr["created"]), **_tags(cr["tags"])}, "item")


def _create_cr(store, p):
    m = _V()._model(store)
    it, az, plat = str(p.get("InstanceType") or ""), str(p.get("AvailabilityZone") or ""), str(p.get("InstancePlatform") or "")
    for name, val in (("InstanceType", it), ("AvailabilityZone", az), ("InstancePlatform", plat)):
        if not val:
            raise _err("MissingParameter", f"The request must contain the parameter {name}.")
    if it not in _V()._INSTANCE_TYPES:
        raise _err("InvalidParameterValue", f"The instance type '{it}' is not supported.")
    if az not in {z["zoneName"] for z in _zone_rows(m) if z["optInStatus"] != "not-opted-in"}:
        raise _err("InvalidParameterValue", f"Invalid Availability Zone '{az}'.")
    if plat not in ("Linux/UNIX", "Red Hat Enterprise Linux", "SUSE Linux", "Windows"):
        raise _err("InvalidParameterValue", f"Invalid InstancePlatform '{plat}'.")
    total = int(p.get("InstanceCount") or 0)
    if total < 1 or total > 1000:
        raise _err("InvalidParameterValue", "InstanceCount must be between 1 and 1000.")
    edt = str(p.get("EndDateType") or "unlimited")
    end = None
    if edt == "limited":
        if not p.get("EndDate"):
            raise _err("MissingParameter", "EndDate is required when EndDateType is limited.")
        end = _epoch(p["EndDate"])
        if end <= time.time():
            raise _err("InvalidParameterValue", "EndDate must be in the future.")
    elif p.get("EndDate"):
        raise _err("InvalidParameterCombination", "EndDate may only be specified when EndDateType is limited.")
    match = str(p.get("InstanceMatchCriteria") or "open")
    cid = "cr-" + uuid.uuid4().hex[:17]
    _bag(m, "capacity_reservations")[cid] = {"id": cid, "type": it, "az": az, "platform": plat, "total": total, "state": "active", "created": time.time(),
                                            "end_date": end, "end_date_type": edt, "match": match, "tags": _specs(p, "capacity-reservation")}
    return _reply("CreateCapacityReservation", f"<capacityReservation>{_cr_xml(m, _bag(m, 'capacity_reservations')[cid]).replace('<item>', '').replace('</item>', '')}</capacityReservation>")


def _describe_cr(store, p):
    m = _V()._model(store)
    _cr_settle(m)
    ids = _idx(p, "CapacityReservationId")
    for i in ids:
        if i not in _bag(m, "capacity_reservations"):
            raise _err("InvalidCapacityReservationId.NotFound", f"The capacity reservation ID '{i}' does not exist")
    flt = _filters(p)
    rows = [c for c in _bag(m, "capacity_reservations").values() if not ids or c["id"] in ids]
    if "state" in flt:
        rows = [c for c in rows if c["state"] in flt["state"]]
    return _reply("DescribeCapacityReservations", f"<capacityReservationSet>{''.join(_cr_xml(m, c) for c in rows)}</capacityReservationSet>")


def _cr_need(m, cid):
    cr = _bag(m, "capacity_reservations").get(str(cid))
    if cr is None:
        raise _err("InvalidCapacityReservationId.NotFound", f"The capacity reservation ID '{cid}' does not exist")
    return cr


def _modify_cr(store, p):
    m = _V()._model(store)
    cr = _cr_need(m, p.get("CapacityReservationId"))
    if cr["state"] != "active":
        raise _err("IncorrectState", f"The capacity reservation is {cr['state']}.")
    if p.get("InstanceCount"):
        n = int(p["InstanceCount"])
        if n < _cr_used(m, cr):
            raise _err("InvalidParameterValue", f"InstanceCount cannot be lower than the {_cr_used(m, cr)} instances currently using the reservation.")
        cr["total"] = n
    if p.get("EndDateType"):
        cr["end_date_type"] = str(p["EndDateType"])
        cr["end_date"] = _epoch(p["EndDate"]) if p.get("EndDate") else None
    return _reply("ModifyCapacityReservation", "<return>true</return>")


def _cancel_cr(store, p):
    m = _V()._model(store)
    cr = _cr_need(m, p.get("CapacityReservationId"))
    if cr["state"] == "cancelled":
        raise _err("IncorrectState", "The capacity reservation is already cancelled.")
    cr["state"] = "cancelled"
    return _reply("CancelCapacityReservation", "<return>true</return>")


# ── Dedicated Hosts ──────────────────────────────────────────────────────────────────────────
HOST_VCPUS = 96   # 2 sockets x 48 cores of schedulable capacity per host (illustrative)


def _host_used(m, h):
    return [i for i in m["instances"].values() if i.get("host_id") == h["id"] and i["state"] in ("pending", "running", "stopping", "stopped")]


def _host_free_vcpus(m, h):
    return HOST_VCPUS - sum(_V()._INSTANCE_TYPES.get(i["instance_type"], {}).get("vcpu", 1) for i in _host_used(m, h))


def _host_xml(m, h):
    used = _host_used(m, h)
    free = _host_free_vcpus(m, h)
    if h["type"]:
        vc = _V()._INSTANCE_TYPES.get(h["type"], {}).get("vcpu", 1)
        avail = {"availableCapacity": {"availableInstanceCapacity": [{"instanceType": h["type"], "availableCapacity": free // vc, "totalCapacity": HOST_VCPUS // vc}],
                                       "availableVCpus": free}}
    else:
        sizes = sorted({t for t, s in _V()._INSTANCE_TYPES.items() if t.split(".")[0] == h["family"]}, key=lambda t: _V()._INSTANCE_TYPES[t]["vcpu"])
        avail = {"availableCapacity": {"availableInstanceCapacity": [{"instanceType": t, "availableCapacity": free // _V()._INSTANCE_TYPES[t]["vcpu"],
                                                                      "totalCapacity": HOST_VCPUS // _V()._INSTANCE_TYPES[t]["vcpu"]} for t in sizes], "availableVCpus": free}}
    return _xml({"hostId": h["id"], "autoPlacement": "on" if h["auto_placement"] else "off", "availabilityZone": h["az"], **avail,
                 "hostProperties": {"sockets": 2, "cores": 48, "totalVCpus": HOST_VCPUS, "instanceType": h["type"] or None, "instanceFamily": h["family"]},
                 "hostReservationId": None, "instances": [{"instanceId": i["id"], "instanceType": i["instance_type"]} for i in used],
                 "state": h["state"], "allocationTime": _iso(h["created"]), "releaseTime": _iso(h["released"]) if h.get("released") else None,
                 "hostRecovery": "on" if h["recovery"] else "off", "allowsMultipleInstanceTypes": "off" if h["type"] else "on",
                 "ownerId": "123456789012", "availabilityZoneId": "use1-az1", "memberOfServiceLinkedResourceGroup": False, **_tags(h["tags"])}, "item")


def _allocate_hosts(store, p):
    m = _V()._model(store)
    az = str(p.get("AvailabilityZone") or "")
    if az not in {z["zoneName"] for z in _zone_rows(m) if z["optInStatus"] != "not-opted-in"}:
        raise _err("InvalidParameterValue", f"Invalid Availability Zone '{az}'.")
    it, fam = str(p.get("InstanceType") or ""), str(p.get("InstanceFamily") or "")
    if bool(it) == bool(fam):
        raise _err("InvalidParameterCombination", "Specify exactly one of InstanceType or InstanceFamily.")
    if it and it not in _V()._INSTANCE_TYPES:
        raise _err("InvalidParameterValue", f"The instance type '{it}' is not supported.")
    if fam and not any(t.split(".")[0] == fam for t in _V()._INSTANCE_TYPES):
        raise _err("InvalidParameterValue", f"The instance family '{fam}' is not supported.")
    qty = int(p.get("Quantity") or 1)
    if qty < 1 or qty > 100:
        raise _err("InvalidParameterValue", "Quantity must be between 1 and 100.")
    ids = []
    for _ in range(qty):
        hid = "h-" + uuid.uuid4().hex[:17]
        _bag(m, "dedicated_hosts")[hid] = {"id": hid, "az": az, "type": it, "family": fam or it.split(".")[0], "state": "available", "created": time.time(),
                                           "auto_placement": str(p.get("AutoPlacement") or "off") == "on", "recovery": str(p.get("HostRecovery") or "off") == "on",
                                           "tags": _specs(p, "dedicated-host")}
        ids.append(hid)
    return _reply("AllocateHosts", "<hostIdSet>" + "".join(f"<item>{i}</item>" for i in ids) + "</hostIdSet>")


def _describe_hosts(store, p):
    m = _V()._model(store)
    ids = _idx(p, "HostId")
    flt = _filters(p)
    rows = [h for h in _bag(m, "dedicated_hosts").values() if not ids or h["id"] in ids]
    if "state" in flt:
        rows = [h for h in rows if h["state"] in flt["state"]]
    return _reply("DescribeHosts", f"<hostSet>{''.join(_host_xml(m, h) for h in rows)}</hostSet>")


def _release_hosts(store, p):
    m = _V()._model(store)
    ok, bad = [], []
    for hid in _idx(p, "HostId"):
        h = _bag(m, "dedicated_hosts").get(hid)
        if h is None or h["state"] == "released":
            bad.append(f"<item><itemId>{hid}</itemId><error><code>InvalidHostID.NotFound</code><message>The host ID '{hid}' does not exist</message></error></item>")
        elif _host_used(m, h):
            bad.append(f"<item><itemId>{hid}</itemId><error><code>HostNotEmpty</code><message>The host '{hid}' still has instances; terminate them first.</message></error></item>")
        else:
            h.update(state="released", released=time.time())
            ok.append(f"<item>{hid}</item>")
    return _reply("ReleaseHosts", f"<successful>{''.join(ok)}</successful><unsuccessful>{''.join(bad)}</unsuccessful>")


def _modify_hosts(store, p):
    m = _V()._model(store)
    ok, bad = [], []
    for hid in _idx(p, "HostId"):
        h = _bag(m, "dedicated_hosts").get(hid)
        if h is None or h["state"] != "available":
            bad.append(f"<item><itemId>{hid}</itemId><error><code>InvalidHostID.NotFound</code><message>The host ID '{hid}' does not exist</message></error></item>")
            continue
        if p.get("AutoPlacement"):
            h["auto_placement"] = str(p["AutoPlacement"]) == "on"
        if p.get("HostRecovery"):
            h["recovery"] = str(p["HostRecovery"]) == "on"
        ok.append(f"<item>{hid}</item>")
    return _reply("ModifyHosts", f"<successful>{''.join(ok)}</successful><unsuccessful>{''.join(bad)}</unsuccessful>")


# ── RunInstances wrapper: spot market options, capacity reservations, dedicated hosts ─────────
def _run_instances(orig, store, p):
    m = _V()._model(store)
    p = dict(p)
    itype = str(p.get("InstanceType") or "t3.micro")
    count = max(1, int(p.get("MaxCount") or p.get("MinCount") or 1))
    spot = str(p.get("InstanceMarketOptions.MarketType") or "") == "spot"
    host = None
    # dedicated host placement
    if str(p.get("Placement.Tenancy") or "") == "host" or p.get("Placement.HostId"):
        p["Placement.Tenancy"] = "host"
        hid = str(p.get("Placement.HostId") or "")
        vc = _V()._INSTANCE_TYPES.get(itype, {}).get("vcpu", 1)
        cands = [_bag(m, "dedicated_hosts").get(hid)] if hid else [h for h in _bag(m, "dedicated_hosts").values() if h["state"] == "available" and h["auto_placement"]]
        cands = [h for h in cands if h]
        if hid and not cands:
            raise _err("InvalidHostID.NotFound", f"The host ID '{hid}' does not exist")
        pick = None
        for h in cands:
            if h["state"] != "available":
                continue
            if h["type"] and h["type"] != itype:
                if hid:
                    raise _err("InvalidParameterCombination", f"Host {h['id']} supports only {h['type']} instances.")
                continue
            if h["family"] != itype.split(".")[0]:
                if hid:
                    raise _err("InvalidParameterCombination", f"Host {h['id']} supports only the {h['family']} family.")
                continue
            if p.get("Placement.AvailabilityZone") and p["Placement.AvailabilityZone"] != h["az"]:
                if hid:
                    raise _err("InvalidParameterValue", f"Host {h['id']} is in {h['az']}, not {p['Placement.AvailabilityZone']}.")
                continue
            if _host_free_vcpus(m, h) >= vc * count:
                pick = h
                break
        if pick is None:
            raise _err("InsufficientHostCapacity", "There is no available host with enough capacity" + (f" on {hid}." if hid else " (no auto-placement host matches)."))
        host = pick
        p["Placement.AvailabilityZone"] = host["az"]
    # capacity reservation targeting
    _cr_settle(m)
    target = str(p.get("CapacityReservationSpecification.CapacityReservationTarget.CapacityReservationId") or "")
    tcr = None
    if target:
        tcr = _cr_need(m, target)
        az = p.get("Placement.AvailabilityZone")
        if tcr["state"] != "active":
            raise _err("CapacityReservationIncorrectState", f"The capacity reservation {target} is {tcr['state']}.")
        if tcr["type"] != itype or (az and az != tcr["az"]):
            raise _err("CapacityReservationMismatch" if False else "InvalidParameterValue", "The launch does not match the reservation's instance type / Availability Zone.")
        if tcr["total"] - _cr_used(m, tcr) < count:
            raise _err("InsufficientInstanceCapacity", f"Capacity reservation {target} has only {tcr['total'] - _cr_used(m, tcr)} available instance(s).")
        p["Placement.AvailabilityZone"] = tcr["az"]
    # spot market validation
    max_price = None
    if spot:
        max_price = float(p.get("InstanceMarketOptions.SpotOptions.MaxPrice") or _od_price(itype))
        az0 = p.get("Placement.AvailabilityZone") or _V()._AZS[0]
        if max_price < spot_price(itype, az0):
            raise _err("SpotMaxPriceTooLow", f"Your Spot request price of {max_price} is lower than the minimum required Spot request fulfillment price of {spot_price(itype, az0)}.")
    before = set(m["instances"])
    res = orig(store, p)
    new = [m["instances"][i] for i in m["instances"] if i not in before]
    for inst in new:
        if host is not None:
            inst.update(host_id=host["id"], tenancy="host")
        if tcr is not None:
            inst["capacity_reservation_id"] = tcr["id"]
        elif p.get("CapacityReservationSpecification.CapacityReservationPreference") != "none":
            for cr in _bag(m, "capacity_reservations").values():
                if cr["state"] == "active" and cr["match"] == "open" and cr["type"] == inst["instance_type"] and cr["az"] == inst["az"] \
                        and cr["total"] > _cr_used(m, cr) and (cr["platform"] == "Windows") == (inst.get("platform") == "windows"):
                    inst["capacity_reservation_id"] = cr["id"]
                    break
        if spot:
            r = _new_spot(m, {"ImageId": inst["image_id"], "InstanceType": inst["instance_type"], "Placement.AvailabilityZone": inst["az"]},
                          max_price, str(p.get("InstanceMarketOptions.SpotOptions.SpotInstanceType") or "one-time"), None, {}, {})
            r.update(state="active", status="fulfilled", message="Your Spot request is fulfilled.", instance_id=inst["id"], az=inst["az"])
            inst.update(lifecycle="spot", spot_request_id=r["id"])
    return res


# ── Recycle Bin ──────────────────────────────────────────────────────────────────────────────
_RTYPES = {"EBS_SNAPSHOT": "snapshots", "EC2_IMAGE": "images"}


def _rb_sweep(m):
    now = time.time()
    items = _bag(m, "rbin_items")
    for k in [k for k, v in items.items() if v["expires_at"] <= now]:
        items.pop(k)
    for r in _bag(m, "rbin_rules").values():
        if r["lock_state"] == "pending_unlock" and r["lock_end"] and now >= r["lock_end"]:
            r["lock_state"] = "unlocked"
            r["lock"] = None


def _rb_match(rule, tags):
    if rule["resource_tags"]:
        if not any(tags.get(t["ResourceTagKey"]) is not None and (not t.get("ResourceTagValue") or tags[t["ResourceTagKey"]] == t["ResourceTagValue"])
                   for t in rule["resource_tags"]):
            return False
    for t in rule.get("exclude_tags") or []:
        if tags.get(t["ResourceTagKey"]) is not None and (not t.get("ResourceTagValue") or tags[t["ResourceTagKey"]] == t["ResourceTagValue"]):
            return False
    return True


def _rb_rule_for(m, rtype, tags):
    """A tag-level rule wins over a region-level one; the longest retention wins ties (AWS keeps the longest)."""
    _rb_sweep(m)
    best = None
    for r in _bag(m, "rbin_rules").values():
        if r["type"] == rtype and r["status"] == "available" and _rb_match(r, tags):
            if best is None or r["days"] > best["days"]:
                best = r
    return best


def _rb_bin_delete(orig, rtype, key_param, store, p):
    m = _V()._model(store)
    rid = str(p.get(key_param) or "")
    rec = m[_RTYPES[rtype]].get(rid)
    rule = _rb_rule_for(m, rtype, (rec or {}).get("tags", {})) if rec else None
    res = orig(store, p)
    if rec is not None and rule is not None:
        now = time.time()
        _bag(m, "rbin_items")[rid] = {"type": rtype, "id": rid, "record": rec, "rule_id": rule["id"], "entered": now, "expires_at": now + rule["days"] * 86400}
    return res


def _list_in_bin(rtype):
    def run(store, p):
        m = _V()._model(store)
        _rb_sweep(m)
        ids = _idx(p, "SnapshotId" if rtype == "EBS_SNAPSHOT" else "ImageId")
        rows = [i for i in _bag(m, "rbin_items").values() if i["type"] == rtype and (not ids or i["id"] in ids)]
        if rtype == "EBS_SNAPSHOT":
            body = "".join(f"<item><snapshotId>{i['id']}</snapshotId><recycleBinEnterTime>{_iso(i['entered'])}</recycleBinEnterTime>"
                           f"<recycleBinExitTime>{_iso(i['expires_at'])}</recycleBinExitTime><description>{_x(i['record'].get('description', ''))}</description>"
                           f"<volumeId>{_x(i['record'].get('volume_id', ''))}</volumeId></item>" for i in rows)
            return _reply("ListSnapshotsInRecycleBin", f"<snapshotSet>{body}</snapshotSet>")
        body = "".join(f"<item><imageId>{i['id']}</imageId><name>{_x(i['record'].get('name', ''))}</name><description>{_x(i['record'].get('description', ''))}</description>"
                       f"<recycleBinEnterTime>{_iso(i['entered'])}</recycleBinEnterTime><recycleBinExitTime>{_iso(i['expires_at'])}</recycleBinExitTime></item>" for i in rows)
        return _reply("ListImagesInRecycleBin", f"<imageSet>{body}</imageSet>")
    return run


def _restore(rtype, key_param, action):
    def run(store, p):
        m = _V()._model(store)
        _rb_sweep(m)
        rid = str(p.get(key_param) or "")
        it = _bag(m, "rbin_items").get(rid)
        if it is None or it["type"] != rtype:
            raise _err("InvalidSnapshot.NotFound" if rtype == "EBS_SNAPSHOT" else "InvalidAMIID.NotFound", f"'{rid}' is not in the Recycle Bin.")
        m[_RTYPES[rtype]][rid] = it["record"]
        _bag(m, "rbin_items").pop(rid)
        if rtype == "EBS_SNAPSHOT":
            r = it["record"]
            return _reply(action, f"<snapshotId>{rid}</snapshotId><description>{_x(r.get('description', ''))}</description><ownerId>{_x(r['owner_id'])}</ownerId>"
                                  f"<progress>100%</progress><state>completed</state><volumeId>{_x(r['volume_id'])}</volumeId><volumeSize>{r['volume_size']}</volumeSize>"
                                  f"<encrypted>{str(r.get('encrypted', False)).lower()}</encrypted>")
        return _reply(action, "<return>true</return>")
    return run


def _rb_json(status, obj=None, code=None):
    body = json.dumps(obj if obj is not None else {}).encode()
    hdrs = {"content-type": "application/json"}
    if code:
        hdrs["x-amzn-errortype"] = code
    return {"status": status, "headers": hdrs, "body": body}


def _rb_err(status, code, msg):
    return _rb_json(status, {"message": msg, "Message": msg, "__type": code}, code)


def _rb_arn(rid):
    return f"arn:aws:rbin:us-east-1:123456789012:rule/{rid}"


def _rb_rule_json(r, full=True):
    out = {"Identifier": r["id"], "Description": r["description"], "RetentionPeriod": {"RetentionPeriodValue": r["days"], "RetentionPeriodUnit": "DAYS"},
           "LockState": r["lock_state"], "RuleArn": _rb_arn(r["id"])}
    if r["lock_end"]:
        out["LockEndTime"] = r["lock_end"]
    if full:
        out.update({"ResourceType": r["type"], "ResourceTags": r["resource_tags"], "Status": r["status"], "ExcludeResourceTags": r.get("exclude_tags") or []})
        if r["lock"]:
            out["LockConfiguration"] = r["lock"]
    return out


def _rb_lock_cfg(cfg):
    ud = (cfg or {}).get("UnlockDelay") or {}
    v, u = ud.get("UnlockDelayValue"), ud.get("UnlockDelayUnit", "DAYS")
    if u != "DAYS" or not isinstance(v, int) or not 7 <= v <= 30:
        raise ValueError("UnlockDelay must be 7-30 DAYS.")
    return {"UnlockDelay": {"UnlockDelayValue": v, "UnlockDelayUnit": "DAYS"}}


def rbin_dispatch(store, method, path, query, headers, body):
    m = _V()._model(store)
    _rb_sweep(m)
    rules = _bag(m, "rbin_rules")
    try:
        data = json.loads(body) if body else {}
    except ValueError:
        return _rb_err(400, "ValidationException", "Invalid JSON body.")
    path = path.split("?")[0]
    mt = re.fullmatch(r"/tags/(.+)", path)
    if mt:
        arn = unquote(mt.group(1))
        rid = arn.rsplit("/", 1)[-1]
        r = rules.get(rid)
        if r is None:
            return _rb_err(404, "ResourceNotFoundException", f"Rule {rid} not found.")
        if method == "GET":
            return _rb_json(200, {"Tags": [{"Key": k, "Value": v} for k, v in r["tags"].items()]})
        if method == "POST":
            for t in data.get("Tags", []):
                r["tags"][t["Key"]] = t.get("Value", "")
            return _rb_json(200)
        if method == "DELETE":
            keys = (query or {}).get("tagKeys") or []
            for k in ([keys] if isinstance(keys, str) else keys):
                r["tags"].pop(k, None)
            return _rb_json(204)
    if path == "/rules" and method == "POST":
        rt = data.get("ResourceType")
        if rt not in _RTYPES:
            return _rb_err(400, "ValidationException", "ResourceType must be EBS_SNAPSHOT or EC2_IMAGE.")
        rp = data.get("RetentionPeriod") or {}
        days = rp.get("RetentionPeriodValue")
        if rp.get("RetentionPeriodUnit") != "DAYS" or not isinstance(days, int) or not 1 <= days <= 3650:
            return _rb_err(400, "ValidationException", "RetentionPeriod must be 1-3650 DAYS.")
        lock = None
        if data.get("LockConfiguration"):
            try:
                lock = _rb_lock_cfg(data["LockConfiguration"])
            except ValueError as e:
                return _rb_err(400, "ValidationException", str(e))
        if len(rules) >= 10:
            return _rb_err(402, "ServiceQuotaExceededException", "You can have at most 10 retention rules per Region.")
        rid = uuid.uuid4().hex[:11]
        rules[rid] = {"id": rid, "type": rt, "days": days, "description": data.get("Description", ""), "resource_tags": data.get("ResourceTags") or [],
                      "exclude_tags": data.get("ExcludeResourceTags") or [], "status": "available", "lock": lock, "lock_state": "locked" if lock else "unlocked",
                      "lock_end": None, "tags": {t["Key"]: t.get("Value", "") for t in data.get("Tags", [])}}
        out = _rb_rule_json(rules[rid])
        out["Tags"] = [{"Key": k, "Value": v} for k, v in rules[rid]["tags"].items()]
        return _rb_json(201, out)
    if path == "/list-rules" and method == "POST":
        rt = data.get("ResourceType")
        if rt not in _RTYPES:
            return _rb_err(400, "ValidationException", "ResourceType must be EBS_SNAPSHOT or EC2_IMAGE.")
        rows = [r for r in rules.values() if r["type"] == rt]
        for t in data.get("ResourceTags") or []:
            rows = [r for r in rows if t in r["resource_tags"]]
        return _rb_json(200, {"Rules": [_rb_rule_json(r, False) for r in rows]})
    mr = re.fullmatch(r"/rules/([^/]+)(/lock|/unlock)?", path)
    if mr:
        rid, sub = mr.group(1), mr.group(2)
        r = rules.get(rid)
        if r is None:
            return _rb_err(404, "ResourceNotFoundException", f"Rule {rid} not found.")
        if method == "GET" and not sub:
            out = _rb_rule_json(r)
            return _rb_json(200, out)
        if method == "PATCH" and sub == "/lock":
            if r["lock_state"] in ("locked", "pending_unlock"):
                return _rb_err(409, "ConflictException", "The rule is already locked.")
            try:
                r["lock"] = _rb_lock_cfg(data.get("LockConfiguration"))
            except ValueError as e:
                return _rb_err(400, "ValidationException", str(e))
            r["lock_state"], r["lock_end"] = "locked", None
            return _rb_json(200, _rb_rule_json(r))
        if method == "PATCH" and sub == "/unlock":
            if r["lock_state"] != "locked":
                return _rb_err(409, "ConflictException", "The rule is not locked.")
            delay = r["lock"]["UnlockDelay"]["UnlockDelayValue"]
            r["lock_state"], r["lock_end"] = "pending_unlock", time.time() + delay * 86400
            return _rb_json(200, _rb_rule_json(r))
        if r["lock_state"] in ("locked", "pending_unlock") and method in ("PATCH", "DELETE") and not sub:
            return _rb_err(409, "ConflictException", "The rule is locked; unlock it (and wait out the unlock delay) before changing or deleting it.")
        if method == "PATCH" and not sub:
            if data.get("RetentionPeriod"):
                rp = data["RetentionPeriod"]
                d = rp.get("RetentionPeriodValue")
                if rp.get("RetentionPeriodUnit") != "DAYS" or not isinstance(d, int) or not 1 <= d <= 3650:
                    return _rb_err(400, "ValidationException", "RetentionPeriod must be 1-3650 DAYS.")
                r["days"] = d
            if "Description" in data:
                r["description"] = data["Description"]
            if "ResourceTags" in data:
                r["resource_tags"] = data["ResourceTags"] or []
            if "ResourceType" in data and data["ResourceType"] in _RTYPES:
                r["type"] = data["ResourceType"]
            return _rb_json(200, _rb_rule_json(r))
        if method == "DELETE" and not sub:
            rules.pop(rid)
            return _rb_json(204)
    return _rb_err(404, "UnknownOperationException", f"Unknown operation {method} {path}")


# ── account-level Auto Scaling limits helper is in autoscaling_core; nothing here ───────────────

_SIMPLE = {
    "DescribeAvailabilityZones": _describe_azs, "ModifyAvailabilityZoneGroup": _modify_az_group,
    "VyomiScheduleInstanceEvent": _schedule_event, "ModifyInstanceEventStartTime": _modify_event_start,
    "RequestSpotInstances": _request_spot, "DescribeSpotInstanceRequests": _describe_spot,
    "CancelSpotInstanceRequests": _cancel_spot, "DescribeSpotPriceHistory": _spot_history,
    "DescribeReservedInstancesOfferings": _describe_ri_offerings, "PurchaseReservedInstancesOffering": _purchase_ri,
    "DescribeReservedInstances": _describe_ri,
    "CreateCapacityReservation": _create_cr, "DescribeCapacityReservations": _describe_cr,
    "ModifyCapacityReservation": _modify_cr, "CancelCapacityReservation": _cancel_cr,
    "AllocateHosts": _allocate_hosts, "DescribeHosts": _describe_hosts, "ReleaseHosts": _release_hosts, "ModifyHosts": _modify_hosts,
    "ListSnapshotsInRecycleBin": _list_in_bin("EBS_SNAPSHOT"), "ListImagesInRecycleBin": _list_in_bin("EC2_IMAGE"),
    "RestoreSnapshotFromRecycleBin": _restore("EBS_SNAPSHOT", "SnapshotId", "RestoreSnapshotFromRecycleBin"),
    "RestoreImageFromRecycleBin": _restore("EC2_IMAGE", "ImageId", "RestoreImageFromRecycleBin"),
}


def install(ops):
    """Merge the new actions into vpc_core._OPS and wrap the ones whose behavior this module extends."""
    ops.update(_SIMPLE)
    run, status, delsnap, dereg = ops["RunInstances"], ops["DescribeInstanceStatus"], ops["DeleteSnapshot"], ops["DeregisterImage"]
    ops["RunInstances"] = lambda store, p: _run_instances(run, store, p)

    def _status(store, p):
        settle_events(_V()._model(store))
        return status(store, p)
    ops["DescribeInstanceStatus"] = _status
    ops["DeleteSnapshot"] = lambda store, p: _rb_bin_delete(delsnap, "EBS_SNAPSHOT", "SnapshotId", store, p)
    ops["DeregisterImage"] = lambda store, p: _rb_bin_delete(dereg, "EC2_IMAGE", "ImageId", store, p)
    for k in ("DescribeInstances",):
        o = ops[k]
        ops[k] = (lambda o_: lambda store, p: (settle_spot(store, _V()._model(store)), o_(store, p))[1])(o)
