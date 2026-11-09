"""EC2 Capacity Blocks for ML and UltraServers - a Dev Simplified capacity-block market (SigV4 signing name `vyomi-ultraservers`,
rest-json: every operation is `POST /<Operation>`).

Substrate-independent (no fastapi / boto3; loads under Pyodide); state lives in the shared EC2/VPC model
(`model["capacity_blocks"]`) so it persists on both substrates.

Real here: DescribeCapacityBlockOfferings (accelerator instance types and UltraServer types, instance/UltraServer count, duration rules,
start-date window), PurchaseCapacityBlock (an offering id is validated and priced, then stored), DescribeCapacityBlocks /
DescribeCapacityBlockStatus / DescribeUltraServers (UltraServer domains with their member hosts), ExtendCapacityBlock, and a lifecycle that
follows the clock: scheduled -> active -> expired, with a Vyomi-only VyomiCancelCapacityBlock that releases a block that has not started
(real AWS capacity blocks cannot be cancelled once bought).

Honest limits: there is NO accelerator hardware, no GPU/Trainium fabric and no real capacity market. Offerings are generated
deterministically from a fixed catalogue with illustrative prices; a block holds no capacity and RunInstances is not coupled to it.
Nothing is invoiced or charged.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

_REGION = "us-east-1"
_DAY = 86400
_MAX_AHEAD = 56 * _DAY      # AWS: start within 8 weeks
_MAX_DAYS = 182
LABEL = "Dev Simplified"

# type -> (accelerator, accelerators/host, per-host hourly USD (illustrative), max hosts per block)
_HOST_TYPES = {
    "p5.48xlarge": ("NVIDIA H100", 8, 31.46, 64), "p5e.48xlarge": ("NVIDIA H200", 8, 35.0, 64), "p5en.48xlarge": ("NVIDIA H200", 8, 38.0, 64),
    "p4d.24xlarge": ("NVIDIA A100", 8, 11.2, 64), "p4de.24xlarge": ("NVIDIA A100 80GB", 8, 14.0, 64),
    "trn1.32xlarge": ("AWS Trainium", 16, 10.7, 64), "trn2.48xlarge": ("AWS Trainium2", 16, 17.9, 64),
}
# UltraServer type -> (instance type of each host, hosts, accelerators total, accelerator, per-host hourly USD)
_ULTRA = {
    "u-p6e-gb200x72": ("p6e-gb200.36xlarge", 18, 72, "NVIDIA GB200 NVL72", 7.0),
    "u-p6e-gb200x36": ("p6e-gb200.36xlarge", 9, 36, "NVIDIA GB200 NVL36", 7.0),
    "u-trn2uxl": ("trn2u.48xlarge", 4, 64, "AWS Trainium2 (64-chip UltraServer)", 18.5),
}
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


def _st(model) -> dict:
    s = model.setdefault("capacity_blocks", {})
    s.setdefault("blocks", {})
    s.setdefault("offerings", {})
    return s


def _catalogue():
    out = {}
    for t, (acc, per, rate, mx) in _HOST_TYPES.items():
        out[t] = {"kind": "instance", "hostType": t, "hosts": 1, "accelerator": acc, "accelerators": per, "hostRate": rate, "max": mx}
    for u, (ht, hosts, accs, acc, rate) in _ULTRA.items():
        out[u] = {"kind": "ultraserver", "hostType": ht, "hosts": hosts, "accelerator": acc, "accelerators": accs, "hostRate": rate, "max": 8}
    return out


def _valid_duration(days):
    return isinstance(days, int) and not isinstance(days, bool) and ((1 <= days <= 14) or (days % 7 == 0 and 0 < days <= _MAX_DAYS))


def _state(b, now):
    if b["state"] == "cancelled":
        return "cancelled"
    if now < b["start"]:
        return "scheduled"
    return "active" if now < b["end"] else "expired"


def _view(b, now):
    cat = _catalogue()[b["type"]]
    v = {"capacityBlockId": b["id"], "capacityReservationId": b["reservationId"], "state": _state(b, now), "availabilityZone": b["az"],
         "startDate": _iso(b["start"]), "endDate": _iso(b["end"]), "durationDays": b["days"],
         "purchaseTime": _iso(b["created"]), "upfrontFee": f"{b['fee']:.2f}", "currencyCode": "USD",
         "tags": [{"key": k, "value": x} for k, x in b.get("tags", {}).items()],
         "source": LABEL}
    if cat["kind"] == "ultraserver":
        v.update({"ultraServerType": b["type"], "ultraServerCount": b["count"], "instanceType": cat["hostType"],
                  "instanceCount": b["count"] * cat["hosts"], "acceleratorCount": b["count"] * cat["accelerators"]})
    else:
        v.update({"instanceType": b["type"], "instanceCount": b["count"], "acceleratorCount": b["count"] * cat["accelerators"]})
    v["acceleratorName"] = cat["accelerator"]
    return v


def op_describe_offerings(model, p, now):
    cat = _catalogue()
    t = p.get("InstanceType") or p.get("UltraServerType")
    if not t:
        raise _Err("MissingParameter", "The request must contain the parameter InstanceType or UltraServerType")
    if t not in cat:
        raise _Err("InvalidParameterValue", f"{t} is not a capacity-block instance or UltraServer type. Supported: {', '.join(sorted(cat))}")
    c = cat[t]
    count = p.get("UltraServerCount") if c["kind"] == "ultraserver" and "UltraServerCount" in p else p.get("InstanceCount", 1)
    days = p.get("CapacityDurationDays", 1)
    if not isinstance(count, int) or isinstance(count, bool) or count < 1 or count > c["max"]:
        raise _Err("InvalidParameterValue", f"Count must be between 1 and {c['max']} for {t}")
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
    for i, az in enumerate((f"{_REGION}a", f"{_REGION}b", f"{_REGION}c")):
        start = int(lo) + i * _DAY
        if start + days * _DAY > hi:
            start = int(lo)
        fee = round(c["hostRate"] * c["hosts"] * count * days * 24 * (0.92 + 0.04 * i), 2)
        oid = "cbo-" + hashlib.sha1(f"{t}|{count}|{days}|{az}|{start}".encode()).hexdigest()[:17]
        o = {"capacityBlockOfferingId": oid, "availabilityZone": az, "startDate": _iso(start), "endDate": _iso(start + days * _DAY),
             "capacityBlockDurationDays": days, "upfrontFee": f"{fee:.2f}", "currencyCode": "USD", "tenancy": "default", "source": LABEL}
        if c["kind"] == "ultraserver":
            o.update({"ultraServerType": t, "ultraServerCount": count, "instanceType": c["hostType"]})
        else:
            o.update({"instanceType": t, "instanceCount": count})
        offs.append(o)
        _st(model)["offerings"][oid] = {"type": t, "count": count, "days": days, "az": az, "start": float(start), "fee": fee}
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
    bid = "cb-" + uuid.uuid4().hex[:17]
    tags = {}
    for spec in p.get("TagSpecifications") or []:
        for t in spec.get("Tags") or []:
            tags[t.get("Key")] = t.get("Value", "")
    s["blocks"][bid] = {"id": bid, "reservationId": "cr-" + uuid.uuid4().hex[:17], "offering": oid, "type": o["type"], "count": o["count"],
                        "az": o["az"], "days": o["days"], "start": o["start"], "end": o["start"] + o["days"] * _DAY, "fee": o["fee"],
                        "created": now, "state": "ok", "tags": tags}
    return {"capacityBlock": _view(s["blocks"][bid], now)}


def _get(model, bid):
    b = _st(model)["blocks"].get(bid)
    if b is None:
        raise _Err("InvalidCapacityBlockId.NotFound", f"The capacity block '{bid}' does not exist", 404)
    return b


def _select(model, p, now):
    s = _st(model)
    ids = p.get("CapacityBlockIds")
    for i in ids or []:
        _get(model, i)
    out = [b for b in s["blocks"].values() if not ids or b["id"] in ids]
    states = p.get("States")
    if states:
        bad = [x for x in states if x not in _STATES]
        if bad:
            raise _Err("InvalidParameterValue", f"Invalid state {bad[0]}; use one of {', '.join(_STATES)}")
        out = [b for b in out if _state(b, now) in states]
    return sorted(out, key=lambda b: b["created"])


def op_describe_blocks(model, p, now):
    return {"capacityBlocks": [_view(b, now) for b in _select(model, p, now)]}


def op_describe_status(model, p, now):
    out = []
    for b in _select(model, p, now):
        st = _state(b, now)
        c = _catalogue()[b["type"]]
        hosts = b["count"] * c["hosts"]
        up = st == "active"
        out.append({"capacityBlockId": b["id"], "state": st, "totalCapacity": hosts, "totalAvailableCapacity": hosts if up else 0,
                    "totalUnavailableCapacity": 0, "interconnectStatus": "ok" if up else "insufficient-data"})
    return {"capacityBlockStatuses": out}


def op_describe_ultraservers(model, p, now):
    cat = _catalogue()
    out = []
    for b in _select(model, p, now):
        c = cat[b["type"]]
        if c["kind"] != "ultraserver":
            continue
        st = _state(b, now)
        for u in range(b["count"]):
            uid = f"us-{b['id'][3:11]}{u:02d}"
            hosts = [{"hostId": f"{uid}-h{h:02d}", "instanceType": c["hostType"], "acceleratorCount": c["accelerators"] // c["hosts"],
                      "status": "healthy" if st == "active" else "not-ready"} for h in range(c["hosts"])]
            out.append({"ultraServerId": uid, "ultraServerType": b["type"], "capacityBlockId": b["id"], "availabilityZone": b["az"],
                        "state": st, "acceleratorCount": c["accelerators"], "acceleratorName": c["accelerator"],
                        "hostCount": c["hosts"], "hosts": hosts, "startDate": _iso(b["start"]), "endDate": _iso(b["end"]), "source": LABEL})
    ids = p.get("UltraServerIds")
    if ids:
        out = [x for x in out if x["ultraServerId"] in ids]
    return {"ultraServers": out}


def op_extend(model, p, now):
    b = _get(model, p.get("CapacityBlockId"))
    add = p.get("CapacityBlockExtensionDurationDays")
    if not _valid_duration(add):
        raise _Err("InvalidParameterValue", "CapacityBlockExtensionDurationDays must be 1-14 days, or a multiple of 7 up to 182")
    if _state(b, now) != "active":
        raise _Err("IncorrectState", "Only an active capacity block can be extended")
    if b["days"] + add > _MAX_DAYS:
        raise _Err("InvalidParameterValue", f"A capacity block can last at most {_MAX_DAYS} days in total")
    c = _catalogue()[b["type"]]
    b["days"] += add
    b["end"] += add * _DAY
    b["fee"] = round(b["fee"] + c["hostRate"] * c["hosts"] * b["count"] * add * 24, 2)
    return {"capacityBlockExtension": {"capacityBlockId": b["id"], "extendedDays": add, "newEndDate": _iso(b["end"])}}


def op_cancel(model, p, now):
    b = _get(model, p.get("CapacityBlockId"))
    if _state(b, now) != "scheduled":
        raise _Err("IncorrectState", "Only a block that has not started can be released in Vyomi (real AWS capacity blocks cannot be cancelled)")
    b["state"] = "cancelled"
    return {"capacityBlock": _view(b, now)}


def op_overview(model, p, now):
    cat = _catalogue()
    by = {k: 0 for k in _STATES}
    accs = us = 0
    for b in _st(model)["blocks"].values():
        st = _state(b, now)
        by[st] += 1
        if st == "active":
            accs += b["count"] * cat[b["type"]]["accelerators"]
            us += b["count"] if cat[b["type"]]["kind"] == "ultraserver" else 0
    return {"asOf": _iso(now), "source": LABEL, "blocksByState": by, "activeAccelerators": accs, "activeUltraServers": us,
            "supportedTypes": [{"type": t, "kind": c["kind"], "accelerator": c["accelerator"], "acceleratorsPerUnit": c["accelerators"],
                                "hostsPerUnit": c["hosts"], "maxUnits": c["max"]} for t, c in cat.items()]}


def _tag(model, p, now, add):
    b = _get(model, p.get("ResourceId"))
    tags = b.setdefault("tags", {})
    for t in p.get("Tags") or []:
        if add:
            tags[t.get("Key")] = t.get("Value", "")
        else:
            tags.pop(t.get("Key"), None)
    return {}


_OPS = {"DescribeCapacityBlockOfferings": op_describe_offerings, "PurchaseCapacityBlock": op_purchase, "DescribeCapacityBlocks": op_describe_blocks,
        "DescribeCapacityBlockStatus": op_describe_status, "DescribeUltraServers": op_describe_ultraservers, "ExtendCapacityBlock": op_extend,
        "VyomiCancelCapacityBlock": op_cancel, "VyomiOverview": op_overview,
        "CreateTags": lambda m, p, n: _tag(m, p, n, True), "DeleteTags": lambda m, p, n: _tag(m, p, n, False)}
_MUTATING = {"DescribeCapacityBlockOfferings", "PurchaseCapacityBlock", "ExtendCapacityBlock", "VyomiCancelCapacityBlock", "CreateTags", "DeleteTags"}


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
