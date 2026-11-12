"""AWS Cost Explorer (service `ce`, JSON 1.1, X-Amz-Target `AWSInsightsIndexService.<Op>`) — substrate-independent.

GetCostAndUsage / GetCostForecast / GetDimensionValues over the simulator's REAL resource inventory (EC2 instances + their EBS volumes in the VPC
model, RDS instances), priced with the same on-demand tables as core/cost_model.py (the per-space "real cloud cost" savings metric) and accrued
by real uptime: a running resource costs `hourly rate x hours` from its create time. The numbers are what AWS WOULD have charged, so the
console's "Saved by Vyomi" dashboard (Vyomi-only action `VyomiGetSavings`, never part of real AWS) can show real money not spent: the simulator
bills $0, so saved == the whole bill. Invoices are not modeled; payment methods never.

Honest limits: only EC2, EBS and RDS are metered (other services have no inventory-derived rate here); stopped instances accrue nothing from the
moment they are observed stopped (no stop-time history); Region is the simulator's single region; HOURLY granularity (a paid opt-in on AWS) and
tag / cost-category grouping are not modeled; forecasts extrapolate the current run rate (no ML model).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

try:
    from core import cost_model
except ImportError:  # Pyodide flat layout
    import cost_model  # type: ignore

REGION = "us-east-1"
ACCOUNT = "123456789012"
EBS_GB_MONTH = {"gp3": 0.08, "gp2": 0.10, "io1": 0.125, "io2": 0.125, "st1": 0.045, "sc1": 0.015, "standard": 0.05}
METRICS = {"AmortizedCost", "BlendedCost", "NetAmortizedCost", "NetUnblendedCost", "NormalizedUsageAmount", "UnblendedCost", "UsageQuantity"}
DIMENSIONS = {"SERVICE", "REGION", "INSTANCE_TYPE", "USAGE_TYPE", "LINKED_ACCOUNT", "RECORD_TYPE", "PURCHASE_TYPE"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SVC_EC2, SVC_EBS, SVC_RDS = "Amazon Elastic Compute Cloud - Compute", "EC2 - Other", "Amazon Relational Database Service"


@dataclass
class CeResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class CeError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _now():
    return datetime.now(timezone.utc)


def _parse_ts(v):
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(float(v), timezone.utc)
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            d = datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _line_items(vpc_store, rds_store):
    """[{service, itype, usage, start, hourly, qty_unit}] — running resources with the time they started accruing."""
    out = []
    if vpc_store is not None:
        try:
            from core import vpc_core
            m = vpc_core._model(vpc_store)
        except Exception:
            m = None
        if m:
            for i in m.get("instances", {}).values():
                if i.get("state") not in ("running", "pending"):
                    continue
                start = _parse_ts(i.get("launch_time"))
                if start:
                    rate = cost_model.vm_hourly_rate("aws", i.get("instance_type", ""))
                    out.append({"service": SVC_EC2, "itype": i.get("instance_type", ""), "usage": f"BoxUsage:{i.get('instance_type', '')}", "start": start, "hourly": rate, "id": i["id"]})
            for v in m.get("volumes", {}).values():
                start = _parse_ts(v.get("created"))
                if start and v.get("state") in ("in-use", "available"):
                    per_gb = EBS_GB_MONTH.get(v.get("type", "gp3"), 0.08)
                    out.append({"service": SVC_EBS, "itype": "", "usage": f"EBS:VolumeUsage.{v.get('type', 'gp3')}", "start": start,
                                "hourly": per_gb * float(v.get("size", 8)) / cost_model.HOURS_PER_MONTH, "id": v["id"]})
    if rds_store is not None:
        try:
            for dbid in rds_store.instance_ids():
                db = rds_store.get_instance(dbid) or {}
                if db.get("status", "available") in ("stopped", "deleting"):
                    continue
                start = _parse_ts(db.get("created"))
                if start:
                    cls = db.get("db_instance_class", "db.t3.micro")
                    out.append({"service": SVC_RDS, "itype": cls, "usage": f"InstanceUsage:{cls}", "start": start,
                                "hourly": cost_model.db_hourly_rate("aws", cls), "id": dbid})
        except Exception:
            pass
    return out


def _hours(item, a, b):
    lo, hi = max(item["start"], a), min(b, _now())
    return max(0.0, (hi - lo).total_seconds() / 3600.0)


def _period(p):
    p = p or {}
    s, e = p.get("Start"), p.get("End")
    if not s or not e:
        raise CeError("ValidationException", "TimePeriod with Start and End is required.")
    if not (_DATE.match(str(s)) and _DATE.match(str(e))):
        raise CeError("ValidationException", "TimePeriod dates must be formatted YYYY-MM-DD.")
    try:
        sd, ed = date.fromisoformat(s), date.fromisoformat(e)
    except ValueError:
        raise CeError("ValidationException", "TimePeriod contains an invalid date.")
    if sd >= ed:
        raise CeError("ValidationException", "TimePeriod Start must be before End.")
    return sd, ed


def _buckets(sd, ed, gran):
    out, cur = [], sd
    while cur < ed:
        if gran == "DAILY":
            nxt = cur + timedelta(days=1)
        else:  # MONTHLY: calendar month, clipped to the requested period
            nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        nxt = min(nxt, ed)
        out.append((cur, nxt))
        cur = nxt
    return out


def _dt(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _dim_value(item, key):
    return {"SERVICE": item["service"], "REGION": REGION, "INSTANCE_TYPE": item["itype"] or "No Instance Type", "USAGE_TYPE": item["usage"],
            "LINKED_ACCOUNT": ACCOUNT, "RECORD_TYPE": "Usage", "PURCHASE_TYPE": "On Demand Instances"}[key]


def _matches(expr, item):
    if not expr:
        return True
    if "Dimensions" in expr:
        d = expr["Dimensions"]
        key = d.get("Key")
        if key not in DIMENSIONS:
            raise CeError("ValidationException", f"Unsupported filter dimension {key}.")
        return _dim_value(item, key) in (d.get("Values") or [])
    if "And" in expr:
        return all(_matches(e, item) for e in expr["And"])
    if "Or" in expr:
        return any(_matches(e, item) for e in expr["Or"])
    if "Not" in expr:
        return not _matches(expr["Not"], item)
    if "Tags" in expr or "CostCategories" in expr:
        return False   # tag / cost-category filters are not modeled: nothing matches rather than silently ignoring the filter
    raise CeError("ValidationException", "Unsupported Filter expression.")


def _amount(v, metric):
    unit = "USD" if "Cost" in metric else ("Hrs" if metric == "UsageQuantity" else "N/A")
    return {"Amount": f"{v:.10f}".rstrip("0").rstrip(".") if v else "0", "Unit": unit}


def _metric_value(cost, hrs, metric):
    return hrs if metric in ("UsageQuantity", "NormalizedUsageAmount") else cost


def _get_cost_and_usage(vpc, rds, b):
    sd, ed = _period(b.get("TimePeriod"))
    gran = b.get("Granularity")
    if gran not in ("DAILY", "MONTHLY", "HOURLY"):
        raise CeError("ValidationException", "Granularity must be DAILY, MONTHLY or HOURLY.")
    if gran == "HOURLY":
        raise CeError("DataUnavailableException", "Hourly granularity requires opting in to hourly and resource-level data in Cost Management preferences.")
    metrics = b.get("Metrics") or []
    if not metrics or any(m not in METRICS for m in metrics):
        raise CeError("ValidationException", "Metrics is required and must be from " + ", ".join(sorted(METRICS)) + ".")
    gb = b.get("GroupBy") or []
    if len(gb) > 2:
        raise CeError("ValidationException", "GroupBy accepts at most two group definitions.")
    for g in gb:
        if g.get("Type") != "DIMENSION" or g.get("Key") not in DIMENSIONS:
            raise CeError("ValidationException", "Only DIMENSION group-bys (SERVICE, REGION, INSTANCE_TYPE, USAGE_TYPE, LINKED_ACCOUNT, RECORD_TYPE, PURCHASE_TYPE) are modeled.")
    items = [i for i in _line_items(vpc, rds) if _matches(b.get("Filter"), i)]
    results = []
    for a, z in _buckets(sd, ed, gran):
        tp = {"Start": a.isoformat(), "End": z.isoformat()}
        agg, tot_c, tot_h = {}, 0.0, 0.0
        for it in items:
            h = _hours(it, _dt(a), _dt(z))
            if h <= 0:
                continue
            c = h * it["hourly"]
            tot_c += c
            tot_h += h
            if gb:
                k = tuple(_dim_value(it, g["Key"]) for g in gb)
                cur = agg.setdefault(k, [0.0, 0.0])
                cur[0] += c
                cur[1] += h
        groups = [{"Keys": list(k), "Metrics": {m: _amount(_metric_value(v[0], v[1], m), m) for m in metrics}} for k, v in sorted(agg.items())]
        results.append({"TimePeriod": tp, "Total": {} if gb else {m: _amount(_metric_value(tot_c, tot_h, m), m) for m in metrics},
                        "Groups": groups, "Estimated": _dt(z) > _now() - timedelta(days=1)})
    return {"ResultsByTime": results, "DimensionValueAttributes": [], "GroupDefinitions": [{"Type": g["Type"], "Key": g["Key"]} for g in gb]}


def _get_dimension_values(vpc, rds, b):
    sd, ed = _period(b.get("TimePeriod"))
    dim = b.get("Dimension")
    if dim not in DIMENSIONS:
        raise CeError("ValidationException", f"Dimension must be one of {', '.join(sorted(DIMENSIONS))}.")
    search = str(b.get("SearchString") or "").lower()
    vals = sorted({_dim_value(i, dim) for i in _line_items(vpc, rds) if _hours(i, _dt(sd), _dt(ed)) > 0})
    vals = [v for v in vals if search in v.lower()]
    return {"DimensionValues": [{"Value": v, "Attributes": {}} for v in vals], "ReturnSize": len(vals), "TotalSize": len(vals)}


def _get_cost_forecast(vpc, rds, b):
    sd, ed = _period(b.get("TimePeriod"))
    metric = b.get("Metric")
    if metric not in ("AMORTIZED_COST", "BLENDED_COST", "NET_AMORTIZED_COST", "NET_UNBLENDED_COST", "UNBLENDED_COST", "USAGE_QUANTITY", "NORMALIZED_USAGE_AMOUNT"):
        raise CeError("ValidationException", "Metric must be one of AMORTIZED_COST, BLENDED_COST, NET_AMORTIZED_COST, NET_UNBLENDED_COST, UNBLENDED_COST, USAGE_QUANTITY, NORMALIZED_USAGE_AMOUNT.")
    gran = b.get("Granularity")
    if gran not in ("DAILY", "MONTHLY"):
        raise CeError("ValidationException", "Granularity must be DAILY or MONTHLY.")
    if _dt(sd) < _now().replace(hour=0, minute=0, second=0, microsecond=0):
        raise CeError("ValidationException", "A forecast TimePeriod must start today or later.")
    items = _line_items(vpc, rds)
    if not items:
        raise CeError("DataUnavailableException", "There is not enough historical data to produce a forecast: no resources are running.")
    rate = sum(i["hourly"] for i in items)
    qty = len(items)
    out, total = [], 0.0
    for a, z in _buckets(sd, ed, gran):
        hrs = (z - a).days * 24.0
        v = hrs * (qty if metric == "USAGE_QUANTITY" else rate)
        total += v
        mean = f"{v:.6f}"
        out.append({"TimePeriod": {"Start": a.isoformat(), "End": z.isoformat()}, "MeanValue": mean})
    return {"Total": {"Amount": f"{total:.6f}", "Unit": "USD" if "QUANTITY" not in metric else "Hrs"}, "ForecastResultsByTime": out}


def _vyomi_get_savings(vpc, rds, b):
    """Vyomi-only: what running these resources on real AWS would have cost vs the $0 the simulator billed."""
    now = _now()
    mstart = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    items = _line_items(vpc, rds)
    by_service, by_res, mtd, life = {}, [], 0.0, 0.0
    for it in items:
        c_mtd = _hours(it, mstart, now) * it["hourly"]
        c_life = _hours(it, it["start"], now) * it["hourly"]
        mtd += c_mtd
        life += c_life
        by_service[it["service"]] = by_service.get(it["service"], 0.0) + c_mtd
        by_res.append({"ResourceId": it["id"], "Service": it["service"], "Type": it["itype"] or it["usage"], "HourlyUSD": round(it["hourly"], 6),
                       "SavedLifetimeUSD": round(c_life, 4), "SavedMonthToDateUSD": round(c_mtd, 4)})
    run_rate_month = sum(i["hourly"] for i in items) * cost_model.HOURS_PER_MONTH
    return {"RealCloudCostMonthToDateUSD": round(mtd, 4), "SimulatorCostUSD": 0.0, "SavedMonthToDateUSD": round(mtd, 4), "SavedLifetimeUSD": round(life, 4),
            "MonthlyRunRateUSD": round(run_rate_month, 2), "SavedByService": {k: round(v, 4) for k, v in sorted(by_service.items())},
            "Resources": sorted(by_res, key=lambda r: -r["SavedLifetimeUSD"]), "ResourceCount": len(items),
            "Note": "Estimated from on-demand list prices x real uptime of the simulator's EC2, EBS and RDS inventory. Not an invoice."}


_OPS = {"GetCostAndUsage": _get_cost_and_usage, "GetDimensionValues": _get_dimension_values, "GetCostForecast": _get_cost_forecast,
        "VyomiGetSavings": _vyomi_get_savings}


def dispatch(vpc_store, rds_store, target: str, payload: dict | None = None) -> CeResponse:
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    hdrs = {"x-amzn-requestid": str(uuid.uuid4())}
    op = _OPS.get(action)
    if op is None:
        return CeResponse(400, {"__type": "UnknownOperationException", "message": f"The action {action} is not implemented."}, hdrs)
    try:
        return CeResponse(200, op(vpc_store, rds_store, body), hdrs)
    except CeError as e:
        return CeResponse(e.status, {"__type": e.code, "message": e.message}, hdrs)
