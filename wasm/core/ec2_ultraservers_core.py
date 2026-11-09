# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""EC2 Capacity Blocks - time-boxed bookings that REALLY reserve capacity from the Docker-backed instance pool
(SigV4 signing name `vyomi-ultraservers`, rest-json: every operation is `POST /<Operation>`).

Substrate-independent (no fastapi / boto3; loads under Pyodide); state lives in the shared EC2/VPC model:
`model["capacity_blocks"]` (the bookings) and, for each booking, a REAL EC2 Capacity Reservation in
`model["capacity_reservations"]` (core/ec2_ops_core). That reservation is what RunInstances consumes:

  * Nano: ec2_ops_core's RunInstances wrapper rejects a launch that targets a scheduled/expired/full reservation
    (CapacityReservationIncorrectState / InsufficientInstanceCapacity) and counts running instances against it.
  * Offline appliance: server.py's native RunInstances calls `admit_launch()` below, which applies the same rules and counts
    the Docker-backed instances launched against the reservation.

Real here: the pool is sized from the host (physical RAM share, env VYOMI_CAPACITY_POOL_MB) and every booking is checked against the
memory of the instances already booked over the same window (InsufficientCapacity when it does not fit); a block is
scheduled -> active -> expired on the clock and its reservation follows; launches consume and terminations free capacity.

Dev Simplified vs AWS: any instance type the simulator can launch can be booked (AWS limits Capacity Blocks to ML accelerator
types); prices are illustrative and nothing is billed; there is one price per offering, no auction. Accelerator instance types
and UltraServers (multi-host GPU domains) are NOT IN SCOPE: they are physical hardware in AWS data centres.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone

_REGION = "us-east-1"
_DAY = 86400
_MAX_AHEAD = 56 * _DAY      # AWS: start within 8 weeks
_MAX_DAYS = 182
LABEL = "Dev Simplified"
NOT_IN_SCOPE = ("UltraServers and accelerator (GPU/Trainium) capacity are physical hardware in AWS data centres, so they are not in scope; "
                "Vyomi offers Capacity Blocks and Capacity Reservations for the instance types its Docker-backed pool runs.")
_ACCEL_PREFIX = ("p2", "p3", "p4", "p5", "p6", "g3", "g4", "g5", "g6", "trn", "inf", "dl", "u-")
_STATES = ("scheduled", "active", "expired", "cancelled")


class _Err(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def _V():
    try:
        from core import vpc_core
    except ImportError:  # Pyodide flat layout
        import vpc_core  # type: ignore
    return vpc_core


def _iso(ts):
    return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_ts(v, field):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise _Err("ValidationException", f"{field} must be an ISO-8601 timestamp or epoch seconds")


def pool_mb() -> int:
    """Memory (MB) of the instance pool: env VYOMI_CAPACITY_POOL_MB, else half the host's physical RAM, else 8 GiB (browser)."""
    try:
        v = int(os.environ.get("VYOMI_CAPACITY_POOL_MB", "0"))
        if v > 0:
            return v
    except ValueError:
        pass
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 * 1024) // 2)
    except (AttributeError, ValueError, OSError):
        return 8192


def _mem_mb(itype):
    return int(float(_V()._INSTANCE_TYPES[itype]["mem"]) * 1024)


def _rate(itype):
    try:
        try:
            from core import cost_model
        except ImportError:
            import cost_model  # type: ignore
        return float(cost_model.vm_hourly_rate("aws", itype))
    except Exception:
        return 0.05


def _st(model) -> dict:
    s = model.setdefault("capacity_blocks", {})
    s.setdefault("blocks", {})
    s.setdefault("offerings", {})
    return s


def _valid_duration(days):
    return isinstance(days, int) and not isinstance(days, bool) and ((1 <= days <= 14) or (days % 7 == 0 and 0 < days <= _MAX_DAYS))


def _state(b, now):
    if b["state"] == "cancelled":
        return "cancelled"
    if now < b["start"]:
        return "scheduled"
    return "active" if now < b["end"] else "expired"


def settle(model, now=None):
    """Move every block's Capacity Reservation along the clock (scheduled -> active -> expired / cancelled)."""
    now = time.time() if now is None else now
    crs = model.setdefault("capacity_reservations", {})
    for b in _st(model)["blocks"].values():
        cr = crs.get(b["reservationId"])
        if cr is not None and cr.get("state") != "cancelled":
            cr["state"] = _state(b, now)
            cr["start_date"], cr["end_date"] = b["start"], b["end"]
            cr["total"] = b["count"]


def _view(model, b, now):
    cr = model.get("capacity_reservations", {}).get(b["reservationId"], {})
    return {"capacityBlockId": b["id"], "capacityReservationId": b["reservationId"], "state": _state(b, now), "availabilityZone": b["az"],
            "instanceType": b["type"], "instanceCount": b["count"], "startDate": _iso(b["start"]), "endDate": _iso(b["end"]),
            "durationDays": b["days"], "purchaseTime": _iso(b["created"]), "upfrontFee": f"{b['fee']:.2f}", "currencyCode": "USD",
            "reservedMemoryMb": b["count"] * _mem_mb(b["type"]), "source": LABEL, "reservationState": cr.get("state")}


def _launchable(t):
    return t in _V()._INSTANCE_TYPES and not t.startswith(_ACCEL_PREFIX)


def _booked_mb(model, lo, hi, now, skip=None):
    tot = 0
    for b in _st(model)["blocks"].values():
        if b["id"] == skip or _state(b, now) in ("expired", "cancelled"):
            continue
        if b["start"] < hi and b["end"] > lo:
            tot += b["count"] * _mem_mb(b["type"])
    return tot


def op_describe_offerings(model, p, now):
    t = p.get("InstanceType")
    if not t:
        raise _Err("MissingParameter", "The request must contain the parameter InstanceType")
    if t.startswith(_ACCEL_PREFIX) or t not in _V()._INSTANCE_TYPES:
        if t.startswith(_ACCEL_PREFIX):
            raise _Err("UnsupportedOperation", f"{t}: {NOT_IN_SCOPE}")
        raise _Err("InvalidParameterValue", f"{t} is not an instance type this simulator can launch")
    count, days = p.get("InstanceCount", 1), p.get("CapacityDurationDays", 1)
    if not isinstance(count, int) or isinstance(count, bool) or count < 1 or count > 64:
        raise _Err("InvalidParameterValue", "InstanceCount must be between 1 and 64")
    if not _valid_duration(days):
        raise _Err("InvalidParameterValue", "CapacityDurationDays must be 1-14 days, or a multiple of 7 up to 182 days")
    lo = _parse_ts(p.get("StartDateRange"), "StartDateRange") or now
    hi = _parse_ts(p.get("EndDateRange"), "EndDateRange") or now + _MAX_AHEAD
    if lo < now - 60:
        raise _Err("InvalidParameterValue", "StartDateRange must not be in the past")
    if hi < lo:
        raise _Err("InvalidParameterValue", "EndDateRange must be after StartDateRange")
    hi = min(hi, now + _MAX_AHEAD + days * _DAY)
    if hi - lo < days * _DAY:
        raise _Err("InvalidParameterValue", "The start/end date range must be at least as long as the requested duration")
    offs = []
    need = count * _mem_mb(t)
    if need > pool_mb():
        raise _Err("InsufficientCapacity", f"{count} x {t} needs {need} MB but the host's instance pool is {pool_mb()} MB")
    for i, az in enumerate((f"{_REGION}a", f"{_REGION}b", f"{_REGION}c")):
        start = int(lo) + i * _DAY
        if start + days * _DAY > hi:
            start = int(lo)
        end = start + days * _DAY
        if _booked_mb(model, start, end, now) + need > pool_mb():
            continue
        fee = round(_rate(t) * count * days * 24 * (0.92 + 0.04 * i), 2)
        oid = "cbo-" + uuid.uuid4().hex[:17]
        offs.append({"capacityBlockOfferingId": oid, "availabilityZone": az, "instanceType": t, "instanceCount": count,
                     "startDate": _iso(start), "endDate": _iso(end), "capacityBlockDurationDays": days, "upfrontFee": f"{fee:.2f}",
                     "currencyCode": "USD", "tenancy": "default", "source": LABEL})
        _st(model)["offerings"][oid] = {"type": t, "count": count, "days": days, "az": az, "start": float(start), "fee": fee}
    if not offs:
        raise _Err("InsufficientCapacity", "The pool is already booked for that window; try a later start date or fewer instances")
    return {"capacityBlockOfferings": offs}


def op_purchase(model, p, now):
    oid = p.get("CapacityBlockOfferingId")
    if not oid:
        raise _Err("MissingParameter", "The request must contain the parameter CapacityBlockOfferingId")
    s = _st(model)
    o = s["offerings"].get(oid)
    if o is None:
        raise _Err("InvalidCapacityBlockOfferingId.NotFound", f"The capacity block offering '{oid}' does not exist (describe offerings first).", 404)
    if o["start"] < now - 3600:
        raise _Err("InvalidCapacityBlockOffering.Expired", "The offering's start time has passed; describe offerings again.")
    if any(b["offering"] == oid and b["state"] != "cancelled" for b in s["blocks"].values()):
        raise _Err("CapacityBlockOffering.AlreadyPurchased", "This offering was already purchased.")
    end = o["start"] + o["days"] * _DAY
    if _booked_mb(model, o["start"], end, now) + o["count"] * _mem_mb(o["type"]) > pool_mb():
        raise _Err("InsufficientCapacity", "The pool was booked by another block since this offering was described")
    bid, crid = "cb-" + uuid.uuid4().hex[:17], "cr-" + uuid.uuid4().hex[:17]
    s["blocks"][bid] = {"id": bid, "reservationId": crid, "offering": oid, "type": o["type"], "count": o["count"], "az": o["az"],
                        "days": o["days"], "start": o["start"], "end": end, "fee": o["fee"], "created": now, "state": "ok"}
    model.setdefault("capacity_reservations", {})[crid] = {
        "id": crid, "type": o["type"], "az": o["az"], "platform": "Linux/UNIX", "total": o["count"], "state": "scheduled", "created": now,
        "start_date": o["start"], "end_date": end, "end_date_type": "limited", "match": "targeted", "tags": {}, "block_id": bid}
    settle(model, now)
    return {"capacityBlock": _view(model, s["blocks"][bid], now)}


def _get(model, bid):
    b = _st(model)["blocks"].get(bid)
    if b is None:
        raise _Err("InvalidCapacityBlockId.NotFound", f"The capacity block '{bid}' does not exist", 404)
    return b


def _select(model, p, now):
    ids = p.get("CapacityBlockIds")
    for i in ids or []:
        _get(model, i)
    out = [b for b in _st(model)["blocks"].values() if not ids or b["id"] in ids]
    states = p.get("States")
    if states:
        bad = [x for x in states if x not in _STATES]
        if bad:
            raise _Err("InvalidParameterValue", f"Invalid state {bad[0]}; use one of {', '.join(_STATES)}")
        out = [b for b in out if _state(b, now) in states]
    return sorted(out, key=lambda b: b["created"])


def op_describe_blocks(model, p, now):
    settle(model, now)
    return {"capacityBlocks": [_view(model, b, now) for b in _select(model, p, now)]}


def op_describe_status(model, p, now):
    settle(model, now)
    out = []
    for b in _select(model, p, now):
        st = _state(b, now)
        used = _used_by_model(model, b["reservationId"])
        total = b["count"] if st == "active" else 0
        out.append({"capacityBlockId": b["id"], "state": st, "totalCapacity": total, "totalUsedCapacity": used if st == "active" else 0,
                    "totalAvailableCapacity": max(total - used, 0)})
    return {"capacityBlockStatuses": out}


def _used_by_model(model, crid):
    return sum(1 for i in model.get("instances", {}).values() if i.get("capacity_reservation_id") == crid and i.get("state") in ("pending", "running"))


def op_extend(model, p, now):
    b = _get(model, p.get("CapacityBlockId"))
    add = p.get("CapacityBlockExtensionDurationDays")
    if not _valid_duration(add):
        raise _Err("InvalidParameterValue", "CapacityBlockExtensionDurationDays must be 1-14 days, or a multiple of 7 up to 182")
    if _state(b, now) != "active":
        raise _Err("IncorrectState", "Only an active capacity block can be extended")
    if b["days"] + add > _MAX_DAYS:
        raise _Err("InvalidParameterValue", f"A capacity block can last at most {_MAX_DAYS} days in total")
    if _booked_mb(model, b["end"], b["end"] + add * _DAY, now, skip=b["id"]) + b["count"] * _mem_mb(b["type"]) > pool_mb():
        raise _Err("InsufficientCapacity", "The pool is booked by another block during the extension window")
    b["days"] += add
    b["end"] += add * _DAY
    b["fee"] = round(b["fee"] + _rate(b["type"]) * b["count"] * add * 24, 2)
    settle(model, now)
    return {"capacityBlockExtension": {"capacityBlockId": b["id"], "extendedDays": add, "newEndDate": _iso(b["end"])}}


def op_cancel(model, p, now):
    b = _get(model, p.get("CapacityBlockId"))
    if _state(b, now) != "scheduled":
        raise _Err("IncorrectState", "Only a block that has not started can be released in Vyomi (real AWS capacity blocks cannot be cancelled)")
    b["state"] = "cancelled"
    cr = model.get("capacity_reservations", {}).get(b["reservationId"])
    if cr is not None:
        cr["state"] = "cancelled"
    return {"capacityBlock": _view(model, b, now)}


def op_overview(model, p, now):
    settle(model, now)
    by = {k: 0 for k in _STATES}
    booked = 0
    for b in _st(model)["blocks"].values():
        st = _state(b, now)
        by[st] += 1
        if st in ("active", "scheduled"):
            booked += b["count"] * _mem_mb(b["type"])
    types = [{"type": t, "memoryMb": _mem_mb(t), "vcpu": v["vcpu"], "maxUnits": max(1, min(64, pool_mb() // _mem_mb(t)))}
             for t, v in _V()._INSTANCE_TYPES.items() if _launchable(t)]
    return {"asOf": _iso(now), "source": LABEL, "blocksByState": by, "poolMb": pool_mb(), "bookedMb": booked,
            "supportedTypes": types, "notInScope": NOT_IN_SCOPE}


_OPS = {"DescribeCapacityBlockOfferings": op_describe_offerings, "PurchaseCapacityBlock": op_purchase, "DescribeCapacityBlocks": op_describe_blocks,
        "DescribeCapacityBlockStatus": op_describe_status, "ExtendCapacityBlock": op_extend, "VyomiCancelCapacityBlock": op_cancel,
        "VyomiOverview": op_overview}
_MUTATING = {"DescribeCapacityBlockOfferings", "PurchaseCapacityBlock", "ExtendCapacityBlock", "VyomiCancelCapacityBlock"}


def admit_launch(model, target, itype, az, count, used, now=None):
    """Offline appliance RunInstances hook: the EC2 Capacity Reservation rules for a launch that targets `target`.
    `used` = Docker-backed instances currently pending/running against that reservation. Returns the reservation id or raises
    a (code, message) via _Err; the caller turns it into the native EC2 error."""
    now = time.time() if now is None else now
    settle(model, now)
    cr = model.get("capacity_reservations", {}).get(str(target))
    if cr is None:
        raise _Err("InvalidCapacityReservationId.NotFound", f"The capacity reservation ID '{target}' does not exist")
    if cr["state"] != "active":
        raise _Err("CapacityReservationIncorrectState", f"The capacity reservation {target} is {cr['state']}.")
    if cr["type"] != itype or (az and az != cr["az"]):
        raise _Err("InvalidParameterValue", "The launch does not match the reservation's instance type / Availability Zone.")
    if cr["total"] - used < count:
        raise _Err("InsufficientInstanceCapacity", f"Capacity reservation {target} has only {max(cr['total'] - used, 0)} available instance(s).")
    return cr["id"]


def dispatch(vpc_store, method: str, path: str, body: bytes, now: float | None = None) -> dict:
    now = time.time() if now is None else float(now)
    op = (path or "").split("?", 1)[0].strip("/")
    hdr = {"content-type": "application/json", "x-amzn-requestid": str(uuid.uuid4())}

    def out(status, doc):
        h = dict(hdr)
        if status >= 400:
            h["x-amzn-errortype"] = doc.get("__type", "")
        return {"status": status, "headers": h, "body": json.dumps(doc).encode()}

    fn = _OPS.get(op)
    if fn is None:
        return out(404, {"__type": "UnknownOperationException", "message": f"Operation {op} is not implemented by this simulator."})
    if method.upper() != "POST":
        return out(405, {"__type": "MethodNotAllowedException", "message": f"{op} must be called with POST"})
    try:
        p = json.loads(body or b"{}")
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        return out(400, {"__type": "ValidationException", "message": "The request body must be a JSON object"})
    try:
        model = _V()._model(vpc_store)
        doc = fn(model, p, now)
        if op in _MUTATING:
            getattr(vpc_store, "persist", lambda: None)()
        return out(200, doc)
    except _Err as e:
        return out(e.status, {"__type": e.code, "message": e.message})
