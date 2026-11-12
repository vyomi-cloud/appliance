"""AWS Savings Plans (service `savingsplans`, SigV4 signing name `savingsplans`, rest-json: every operation is `POST /<Operation>`)
plus the EC2 commitment / capacity view that derives from the running inventory.

Substrate-independent (no fastapi / boto3; loads under Pyodide); state lives in the shared EC2/VPC model
(`model["savings_plans"]`) so it persists on both substrates. There is NO billing: a plan is a stored commitment with the real
lifecycle, and its effect is computed against the instances that really run in the simulator:

  * DescribeSavingsPlansOfferings (Compute / EC2Instance, 1 or 3 years, all payment options; filters), CreateSavingsPlan (offering,
    hourly commitment, upfront-payment check, purchaseTime in the future -> `queued`), DescribeSavingsPlans (ids / arns / states /
    filters / paging), DeleteQueuedSavingsPlan, ReturnSavingsPlan (only inside the 7-day window), DescribeSavingsPlanRates
    (per-instance-type Savings Plans rate = on-demand x (1 - discount)), Tag/Untag/ListTagsForResource.
  * Vyomi extensions (`/Vyomi...`): `VyomiCoverage` allocates each active plan's hourly commitment to the on-demand usage of the
    running EC2 instances it applies to (highest discount first) -> coverage %, utilisation %, unused commitment, net savings;
    `VyomiCapacityOverview` summarises capacity by instance type / zone with Reserved Instance, Capacity Reservation, Dedicated Host,
    Spot and Savings Plans coverage - the Capacity Manager page.

Honest limits: discounts and list prices are illustrative (cost_model on-demand x fixed discount per plan type/term), not the real
price list; Database / SageMaker plans and non-EC2 usage are not modelled; coverage and utilisation are a snapshot of the CURRENT
hour's run-rate, not a billing-period history; nothing is invoiced or charged.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone

_ACCOUNT = "123456789012"
_REGION = "us-east-1"
_TERMS = {31536000: "1yr", 94608000: "3yr"}
_PAY = ("All Upfront", "Partial Upfront", "No Upfront")
_TYPES = ("Compute", "EC2Instance")
_DISCOUNT = {("Compute", 31536000): 0.28, ("Compute", 94608000): 0.50, ("EC2Instance", 31536000): 0.40, ("EC2Instance", 94608000): 0.58}
_PAY_BONUS = {"All Upfront": 0.03, "Partial Upfront": 0.015, "No Upfront": 0.0}
_STATES = ("payment-pending", "payment-failed", "active", "retired", "queued", "queued-deleted")
_RETURN_WINDOW = 7 * 86400


class _Err(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def _V():
    try:
        from core import vpc_core
    except ImportError:  # Pyodide flat layout
        import vpc_core  # type: ignore
    return vpc_core


def _cost():
    try:
        from core import cost_model
    except ImportError:
        import cost_model  # type: ignore
    return cost_model


def _iso(ts):
    return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _od(itype):
    return float(_cost().vm_hourly_rate("aws", itype))


def _family(itype):
    return itype.split(".")[0]


def _discount(ptype, dur, pay):
    return round(_DISCOUNT[(ptype, dur)] + _PAY_BONUS[pay], 4)


def _offering_id(ptype, dur, pay, family=""):
    h = hashlib.md5(f"sp|{ptype}|{dur}|{pay}|{family}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def offerings(families):
    out = []
    for ptype in _TYPES:
        for dur in _TERMS:
            for pay in _PAY:
                for fam in (families if ptype == "EC2Instance" else [""]):
                    out.append({"offeringId": _offering_id(ptype, dur, pay, fam), "productTypes": ["EC2"], "planType": ptype,
                                "description": f"{_TERMS[dur].replace('yr', ' year')} {pay} {ptype} Savings Plan" + (f" ({fam} in {_REGION})" if fam else ""),
                                "paymentOption": pay, "durationSeconds": dur, "currency": "USD", "serviceCode": "AmazonEC2",
                                "usageType": f"BoxUsage:{fam}" if fam else "BoxUsage", "operation": "RunInstances",
                                "properties": [{"name": "region", "value": _REGION}] + ([{"name": "instanceFamily", "value": fam}] if fam else []),
                                "_family": fam, "_discount": _discount(ptype, dur, pay)})
    return out


def _families():
    return sorted({_family(t) for t in _V()._INSTANCE_TYPES})


def _state(model) -> dict:
    return model.setdefault("savings_plans", {})


def _plan_state(p, now):
    if p["state"] == "queued" and now >= p["startTs"]:
        p["state"] = "active"
    if p["state"] == "active" and now >= p["endTs"]:
        p["state"] = "retired"
    return p["state"]


def _view(p, now):
    _plan_state(p, now)
    o = p["offering"]
    hours = o["durationSeconds"] / 3600
    upfront = {"All Upfront": p["commitment"] * hours, "Partial Upfront": p["commitment"] * hours / 2}.get(o["paymentOption"], 0.0)
    recurring = {"All Upfront": 0.0, "Partial Upfront": p["commitment"] / 2}.get(o["paymentOption"], p["commitment"])
    v = {"offeringId": o["offeringId"], "savingsPlanId": p["id"], "savingsPlanArn": f"arn:aws:savingsplans::{_ACCOUNT}:savingsplan/{p['id']}",
         "description": o["description"], "start": _iso(p["startTs"]), "end": _iso(p["endTs"]), "state": p["state"], "region": _REGION,
         "savingsPlanType": o["planType"], "paymentOption": o["paymentOption"], "productTypes": ["EC2"], "currency": "USD",
         "commitment": f"{p['commitment']:.3f}", "upfrontPaymentAmount": f"{upfront:.2f}", "recurringPaymentAmount": f"{recurring:.3f}",
         "termDurationInSeconds": o["durationSeconds"], "tags": dict(p["tags"])}
    if o["_family"]:
        v["ec2InstanceFamily"] = o["_family"]
    if p.get("returnableUntil"):
        v["returnableUntil"] = _iso(p["returnableUntil"])
    return v


# ── operations ───────────────────────────────────────────────────────────────
def _page(rows, p, key):
    n = int(p.get("maxResults") or 1000)
    if n < 1 or n > 1000:
        raise _Err("ValidationException", "maxResults must be between 1 and 1000.")
    start = int(p["nextToken"]) if str(p.get("nextToken") or "").isdigit() else 0
    out = {key: rows[start:start + n]}
    if start + n < len(rows):
        out["nextToken"] = str(start + n)
    return out


def op_describe_offerings(model, p, now):
    fams = _families()
    rows = offerings(fams)
    if p.get("offeringIds"):
        rows = [r for r in rows if r["offeringId"] in p["offeringIds"]]
    if p.get("paymentOptions"):
        bad = [x for x in p["paymentOptions"] if x not in _PAY]
        if bad:
            raise _Err("ValidationException", f"Invalid paymentOptions: {bad}. Valid values: {list(_PAY)}")
        rows = [r for r in rows if r["paymentOption"] in p["paymentOptions"]]
    if p.get("planTypes"):
        bad = [x for x in p["planTypes"] if x not in ("Compute", "EC2Instance", "SageMaker", "Database")]
        if bad:
            raise _Err("ValidationException", f"Invalid planTypes: {bad}.")
        rows = [r for r in rows if r["planType"] in p["planTypes"]]
    if p.get("durations"):
        rows = [r for r in rows if r["durationSeconds"] in [int(d) for d in p["durations"]]]
    if p.get("currencies"):
        rows = [r for r in rows if r["currency"] in p["currencies"]]
    if p.get("productType") and p["productType"] != "EC2":
        rows = []
    for f in p.get("filters") or []:
        if f.get("name") == "instanceFamily":
            rows = [r for r in rows if r["_family"] in f.get("values", [])]
        elif f.get("name") == "region":
            rows = [r for r in rows if _REGION in f.get("values", [])]
    rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    return _page(rows, p, "searchResults")


def op_create(model, p, now):
    for need in ("savingsPlanOfferingId", "commitment"):
        if p.get(need) in (None, ""):
            raise _Err("ValidationException", f"{need} is required.")
    off = next((o for o in offerings(_families()) if o["offeringId"] == p["savingsPlanOfferingId"]), None)
    if off is None:
        raise _Err("ResourceNotFoundException", f"The Savings Plan offering {p['savingsPlanOfferingId']} was not found.", 404)
    try:
        commitment = float(p["commitment"])
    except ValueError:
        raise _Err("ValidationException", "commitment must be a decimal USD amount per hour.")
    if commitment < 0.001:
        raise _Err("ValidationException", "The minimum hourly commitment is 0.001 USD.")
    hours = off["durationSeconds"] / 3600
    expect = {"All Upfront": commitment * hours, "Partial Upfront": commitment * hours / 2}.get(off["paymentOption"], 0.0)
    if p.get("upfrontPaymentAmount") not in (None, ""):
        if abs(float(p["upfrontPaymentAmount"]) - expect) > max(0.02, expect * 1e-4):
            raise _Err("ValidationException", f"upfrontPaymentAmount {p['upfrontPaymentAmount']} does not match the {off['paymentOption']} "
                       f"payment for this commitment ({expect:.2f}).")
    elif expect:
        raise _Err("ValidationException", f"upfrontPaymentAmount is required for {off['paymentOption']} offerings (expected {expect:.2f}).")
    start = now
    if p.get("purchaseTime"):
        try:
            start = float(p["purchaseTime"]) if not isinstance(p["purchaseTime"], str) else datetime.fromisoformat(p["purchaseTime"].replace("Z", "+00:00")).timestamp()
        except ValueError:
            raise _Err("ValidationException", "purchaseTime must be a timestamp.")
        if start < now - 60:
            raise _Err("ValidationException", "purchaseTime cannot be in the past.")
        if start > now + 366 * 86400:
            raise _Err("ValidationException", "purchaseTime cannot be more than one year in the future.")
    if p.get("clientToken"):
        for q in _state(model).values():
            if q.get("clientToken") == p["clientToken"]:
                return {"savingsPlanId": q["id"]}
    pid = str(uuid.uuid4())
    queued = start > now + 1
    _state(model)[pid] = {"id": pid, "offering": off, "commitment": commitment, "startTs": start, "endTs": start + off["durationSeconds"],
                          "state": "queued" if queued else "active", "tags": dict(p.get("tags") or {}), "clientToken": p.get("clientToken"),
                          "returnableUntil": start + _RETURN_WINDOW}
    return {"savingsPlanId": pid}


def op_describe(model, p, now):
    ids = set(p.get("savingsPlanIds") or []) | {a.rsplit("/", 1)[-1] for a in p.get("savingsPlanArns") or []}
    for s in p.get("states") or []:
        if s not in _STATES:
            raise _Err("ValidationException", f"Invalid state {s}. Valid values: {list(_STATES)}")
    rows = []
    for plan in sorted(_state(model).values(), key=lambda q: q["startTs"]):
        v = _view(plan, now)
        if ids and v["savingsPlanId"] not in ids:
            continue
        if p.get("states") and v["state"] not in p["states"]:
            continue
        ok = True
        for f in p.get("filters") or []:
            name, vals = f.get("name"), f.get("values", [])
            attr = {"region": "region", "ec2-instance-family": "ec2InstanceFamily", "commitment": "commitment", "upfront": "upfrontPaymentAmount",
                    "term": "termDurationInSeconds", "savings-plan-type": "savingsPlanType", "payment-option": "paymentOption"}.get(name)
            if attr and str(v.get(attr)) not in [str(x) for x in vals]:
                ok = False
        if ok:
            rows.append(v)
    return _page(rows, p, "savingsPlans")


def _plan(model, p, field="savingsPlanId"):
    pid = p.get(field)
    if not pid:
        raise _Err("ValidationException", f"{field} is required.")
    plan = _state(model).get(pid)
    if not plan:
        raise _Err("ResourceNotFoundException", f"Savings Plan {pid} was not found.", 404)
    return plan


def op_delete_queued(model, p, now):
    plan = _plan(model, p)
    if _plan_state(plan, now) != "queued":
        raise _Err("ValidationException", f"Only queued Savings Plans can be deleted; this plan is {plan['state']}. Use ReturnSavingsPlan for an active plan.")
    plan["state"] = "queued-deleted"
    return {}


def op_return(model, p, now):
    plan = _plan(model, p)
    if _plan_state(plan, now) != "active":
        raise _Err("ValidationException", f"Only an active Savings Plan can be returned; this plan is {plan['state']}.")
    if now > plan["returnableUntil"]:
        raise _Err("ValidationException", "The return window for this Savings Plan has passed: a plan can be returned within 7 days of purchase (and within the same calendar month).")
    if datetime.fromtimestamp(plan["startTs"], timezone.utc).month != datetime.fromtimestamp(now, timezone.utc).month:
        raise _Err("ValidationException", "A Savings Plan can only be returned in the calendar month it was purchased.")
    plan["state"] = "retired"
    plan["endTs"] = min(plan["endTs"], now)
    return {"savingsPlanId": plan["id"]}


def op_rates(model, p, now):
    plan = _plan(model, p)
    o = plan["offering"]
    d = o["_discount"]
    rows = []
    for t in sorted(_V()._INSTANCE_TYPES):
        if o["_family"] and _family(t) != o["_family"]:
            continue
        rows.append({"rate": f"{_od(t) * (1 - d):.5f}", "currency": "USD", "unit": "Hrs", "productType": "EC2", "serviceCode": "AmazonEC2",
                     "usageType": f"BoxUsage:{t}", "operation": "RunInstances",
                     "properties": [{"name": "region", "value": _REGION}, {"name": "instanceFamily", "value": _family(t)},
                                    {"name": "instanceType", "value": t}, {"name": "tenancy", "value": "shared"},
                                    {"name": "productDescription", "value": "Linux/UNIX"}]})
    for f in p.get("filters") or []:
        if f.get("name") == "instanceType":
            rows = [r for r in rows if any(x["name"] == "instanceType" and x["value"] in f["values"] for x in r["properties"])]
    return {"savingsPlanId": plan["id"], **_page(rows, p, "searchResults")}


def _tag_target(model, arn):
    m = re.match(r"^arn:aws:savingsplans::\d{12}:savingsplan/(.+)$", str(arn or ""))
    plan = _state(model).get(m.group(1)) if m else None
    if not plan:
        raise _Err("ResourceNotFoundException", f"Resource {arn} was not found.", 404)
    return plan


def op_tag(model, p, now):
    plan = _tag_target(model, p.get("resourceArn"))
    tags = p.get("tags") or {}
    if len(plan["tags"]) + len([k for k in tags if k not in plan["tags"]]) > 50:
        raise _Err("ServiceQuotaExceededException", "A resource can have at most 50 tags.")
    plan["tags"].update({str(k): str(v) for k, v in tags.items()})
    return {}


def op_untag(model, p, now):
    plan = _tag_target(model, p.get("resourceArn"))
    for k in p.get("tagKeys") or []:
        plan["tags"].pop(k, None)
    return {}


def op_list_tags(model, p, now):
    return {"tags": dict(_tag_target(model, p.get("resourceArn"))["tags"])}


# ── usage-derived views ─────────────────────────────────────────────────────
def _eligible(model):
    out = []
    for i in model.get("instances", {}).values():
        if i.get("state") in ("running", "pending"):
            out.append({"id": i["id"], "type": i.get("instance_type", ""), "az": i.get("az", ""), "od": _od(i.get("instance_type", ""))})
    return out


def coverage(model, now):
    """Snapshot of the current hour: allocate every active plan's commitment to the running instances' on-demand usage."""
    usage = _eligible(model)
    remaining = {u["id"]: u["od"] for u in usage}
    total_od = sum(remaining.values())
    plans = []
    active = [p for p in _state(model).values() if _plan_state(p, now) == "active"]
    for plan in sorted(active, key=lambda q: -q["offering"]["_discount"]):
        o, d = plan["offering"], plan["offering"]["_discount"]
        applicable = [u for u in usage if (not o["_family"] or _family(u["type"]) == o["_family"]) and remaining[u["id"]] > 1e-12]
        sp_cost_available = sum(remaining[u["id"]] * (1 - d) for u in applicable)
        used = min(plan["commitment"], sp_cost_available)
        covered_od = used / (1 - d) if d < 1 else 0.0
        left = covered_od
        for u in applicable:
            take = min(remaining[u["id"]], left)
            remaining[u["id"]] -= take
            left -= take
        plans.append({"savingsPlanId": plan["id"], "type": o["planType"], "family": o["_family"] or None, "hourlyCommitment": round(plan["commitment"], 4),
                      "usedCommitment": round(used, 4), "unusedCommitment": round(plan["commitment"] - used, 4),
                      "utilizationPercentage": round(used / plan["commitment"] * 100, 2) if plan["commitment"] else 0.0,
                      "onDemandEquivalent": round(covered_od, 4), "netSavingsPerHour": round(covered_od - used, 4)})
    covered = total_od - sum(remaining.values())
    commit = sum(p["hourlyCommitment"] for p in plans)
    used_total = sum(p["usedCommitment"] for p in plans)
    return {"asOf": _iso(now), "basis": "current hourly run-rate of the running EC2 instances (not a billing-period history)",
            "onDemandCostPerHour": round(total_od, 4), "coveredOnDemandPerHour": round(covered, 4),
            "uncoveredOnDemandPerHour": round(total_od - covered, 4),
            "coveragePercentage": round(covered / total_od * 100, 2) if total_od else 0.0,
            "totalCommitmentPerHour": round(commit, 4), "usedCommitmentPerHour": round(used_total, 4), "unusedCommitmentPerHour": round(commit - used_total, 4),
            "utilizationPercentage": round(used_total / commit * 100, 2) if commit else 0.0,
            "netSavingsPerHour": round(sum(p["netSavingsPerHour"] for p in plans), 4), "plans": plans,
            "instances": [{"id": u["id"], "type": u["type"], "az": u["az"], "onDemandPerHour": round(u["od"], 4),
                           "uncoveredPerHour": round(remaining[u["id"]], 4)} for u in usage]}


def capacity_overview(model, now):
    inst = [i for i in model.get("instances", {}).values()]
    running = [i for i in inst if i.get("state") in ("running", "pending")]
    by_type, by_az = {}, {}
    for i in running:
        t = i.get("instance_type", "")
        vc = _V()._INSTANCE_TYPES.get(t, {}).get("vcpu", 0)
        bt = by_type.setdefault(t, {"instanceType": t, "running": 0, "vcpus": 0, "spot": 0, "reservedInstances": 0, "capacityReservations": 0})
        bt["running"] += 1
        bt["vcpus"] += vc
        if i.get("lifecycle") == "spot" or i.get("instance_lifecycle") == "spot":
            bt["spot"] += 1
        az = by_az.setdefault(i.get("az", ""), {"availabilityZone": i.get("az", ""), "running": 0, "vcpus": 0})
        az["running"] += 1
        az["vcpus"] += vc
    ri_total = ri_matched = 0
    for r in model.get("reserved_instances", {}).values():
        if now < r["end"]:
            t = r["offering"]["type"]
            ri_total += r["count"]
            bt = by_type.setdefault(t, {"instanceType": t, "running": 0, "vcpus": 0, "spot": 0, "reservedInstances": 0, "capacityReservations": 0})
            bt["reservedInstances"] += r["count"]
    for t, bt in by_type.items():
        ri_matched += min(bt["running"], bt["reservedInstances"])
    crs = [c for c in model.get("capacity_reservations", {}).values() if c.get("state", "active") == "active"]
    for c in crs:
        t = c.get("type", "")
        if t:
            bt = by_type.setdefault(t, {"instanceType": t, "running": 0, "vcpus": 0, "spot": 0, "reservedInstances": 0, "capacityReservations": 0})
            bt["capacityReservations"] += int(c.get("total", c.get("instance_count", 0)) or 0)
    cov = coverage(model, now)
    return {"asOf": _iso(now), "runningInstances": len(running), "stoppedInstances": len([i for i in inst if i.get("state") == "stopped"]),
            "runningVcpus": sum(v["vcpus"] for v in by_az.values()),
            "byInstanceType": sorted(by_type.values(), key=lambda x: -x["running"]), "byAvailabilityZone": sorted(by_az.values(), key=lambda x: x["availabilityZone"]),
            "reservedInstances": {"active": ri_total, "matchedByRunningInstances": ri_matched, "unused": ri_total - ri_matched},
            "capacityReservations": len(crs), "dedicatedHosts": len(model.get("dedicated_hosts", {}) or {}),
            "spotRequests": len(model.get("spot_requests", {}) or {}),
            "savingsPlans": {"active": len(cov["plans"]), "coveragePercentage": cov["coveragePercentage"], "utilizationPercentage": cov["utilizationPercentage"],
                             "unusedCommitmentPerHour": cov["unusedCommitmentPerHour"]}}


_OPS = {"DescribeSavingsPlansOfferings": op_describe_offerings, "CreateSavingsPlan": op_create, "DescribeSavingsPlans": op_describe,
        "DeleteQueuedSavingsPlan": op_delete_queued, "ReturnSavingsPlan": op_return, "DescribeSavingsPlanRates": op_rates,
        "TagResource": op_tag, "UntagResource": op_untag, "ListTagsForResource": op_list_tags,
        "VyomiCoverage": lambda m, p, now: coverage(m, now), "VyomiCapacityOverview": lambda m, p, now: capacity_overview(m, now)}
_MUTATING = {"CreateSavingsPlan", "DeleteQueuedSavingsPlan", "ReturnSavingsPlan", "TagResource", "UntagResource"}


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
