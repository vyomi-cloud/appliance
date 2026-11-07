"""Azure Monitor autoscale ENGINE for App Service plans (``Microsoft.Insights/autoscaleSettings``), substrate-free.

The ARM resource (profiles, rules, notifications) is owned by core/azure_monitor_core.py; this module makes it DO something:
``evaluate(state, now)`` reads each enabled setting that targets a ``Microsoft.Web/serverfarms`` plan, picks the active profile
(a ``fixedDate`` profile whose window contains ``now``, else the default one), evaluates every rule's metric trigger against the
REAL request series the app host recorded (core/azure_webhost_core.py: ``Requests``, ``Http2xx/4xx/5xx``, ``AverageResponseTime``
per site, and the ``CpuPercentage`` / ``MemoryPercentage`` LOAD GAUGE derived from requests per second per instance), and CHANGES
the plan's instance count (``sku.capacity``) the way Azure does:

* scale-out rules: if any triggers, the largest requested count wins; scale-in rules apply only when ALL of them trigger
* ChangeCount / PercentChangeCount / ExactCount actions, result clamped to the profile's ``capacity`` minimum..maximum
* each rule's ``cooldown`` is honoured (no scale action of any kind inside the cooldown after the last one)
* a plan outside [minimum, maximum] is brought back inside; with no triggered rule the count is left alone
* every scale action is recorded: the setting's ``_autoscale.history`` (read via ``history()``), and an Activity Log event
  (``Microsoft.Insights/AutoscaleSettings/Scaleup|Scaledown/Action``), so the Run history / Activity log are real.

Not modelled: ``recurrence`` profiles (stored, never selected), predictive autoscale, metrics other than the ones above
(a rule on an unknown metric is reported in the history as "metric unavailable" and never triggers), instance warm-up time.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

try:
    from core import azure_webhost_core as host
    from core import azure_webapp_core as web
except ImportError:                                    # Pyodide flat layout
    import azure_webhost_core as host                  # type: ignore
    import azure_webapp_core as web                    # type: ignore

SETTING = "microsoft.insights/autoscalesettings"
HIST_MAX = 200


def _secs(iso, default=60):
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", str(iso or ""))
    if not m or not any(m.groups()):
        return default
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _ts(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _sites_on(state, plan_id):
    return [r for r in state.values() if isinstance(r, dict) and str(r.get("type", "")).lower() == "microsoft.web/sites"
            and str((r.get("properties") or {}).get("serverFarmId", "")).lower() == plan_id.lower()]


def _profile(setting, now):
    default = None
    for pr in setting["properties"]["profiles"]:
        fd = pr.get("fixedDate")
        if fd:
            a, b = _ts(fd.get("start")), _ts(fd.get("end"))
            if a is not None and b is not None and a <= now <= b:
                return pr
        elif not pr.get("recurrence") and default is None:
            default = pr
    return default or setting["properties"]["profiles"][0]


def _bucket_value(state, uri, metric, t0, t1, instances):
    """Value of ``metric`` for the resource in [t0, t1) or None when the metric is not one the host really produces."""
    res = state.get(str(uri).lower())
    if res is None:
        return None
    rtype = str(res.get("type", "")).lower()
    sites = _sites_on(state, res["id"]) if rtype == "microsoft.web/serverfarms" else ([res] if rtype == "microsoft.web/sites" else [])
    if not sites:
        return None
    n = metric.lower()
    if n in ("cpupercentage", "memorypercentage"):
        cnt = sum(len([x for x in (s.get("_webhost") or {}).get("log", []) if t0 <= x["t"] < t1]) for s in sites)
        return min(100.0, 100.0 * (cnt / max(1.0, t1 - t0)) / (host.NOMINAL_RPS * max(1, instances)))
    logs = [x for s in sites for x in (s.get("_webhost") or {}).get("log", []) if t0 <= x["t"] < t1]
    if n == "requests":
        return float(len(logs))
    if n in ("http2xx", "http4xx", "http5xx"):
        return float(len([x for x in logs if x["status"] // 100 == int(n[4])]))
    if n in ("averageresponsetime", "httpresponsetime"):
        return (sum(x["ms"] for x in logs) / len(logs) / 1000.0) if logs else 0.0
    return None


_CMP = {"Equals": lambda a, b: a == b, "NotEquals": lambda a, b: a != b, "GreaterThan": lambda a, b: a > b,
        "GreaterThanOrEqual": lambda a, b: a >= b, "LessThan": lambda a, b: a < b, "LessThanOrEqual": lambda a, b: a <= b}


def _trigger(state, rule, now, instances):
    mt = rule["metricTrigger"]
    win, grain = _secs(mt.get("timeWindow"), 600), max(1, _secs(mt.get("timeGrain"), 60))
    vals = []
    t = now - win
    while t < now:
        v = _bucket_value(state, mt["metricResourceUri"], mt["metricName"], t, min(now, t + grain), instances)
        if v is None:
            return None, None
        vals.append(v)
        t += grain
    agg = mt.get("timeAggregation", "Average")
    val = {"Average": lambda: sum(vals) / len(vals), "Minimum": lambda: min(vals), "Maximum": lambda: max(vals),
           "Total": lambda: sum(vals), "Count": lambda: float(len(vals)), "Last": lambda: vals[-1]}[agg]()
    return val, _CMP[mt["operator"]](val, float(mt["threshold"]))


def _target(cur, sa):
    v = int(float(sa.get("value") or 1))
    t = sa["type"]
    sign = 1 if sa["direction"] == "Increase" else -1
    if t == "ExactCount":
        return v
    if t == "PercentChangeCount":
        import math
        d = cur * v / 100.0
        return cur + sign * (math.ceil(d) if sign > 0 else math.ceil(d))
    return cur + sign * v


def _event(state, plan, setting, up, frm, to, reason):
    try:
        web._record_event(state, plan.get("_sub"), plan.get("_rg"), plan["id"],
                          f"Microsoft.Insights/AutoscaleSettings/{'Scaleup' if up else 'Scaledown'}/Action",
                          f"Autoscale scale {'up' if up else 'down'} completed", "Succeeded")
    except Exception:
        pass


def evaluate(state, now=None):
    """Evaluate every enabled autoscale setting once. Returns [{setting, plan, from, to, reason}] for the scale actions taken."""
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    actions = []
    for st in [r for r in list(state.values()) if isinstance(r, dict) and str(r.get("_type", "")).lower() == SETTING]:
        p = st["properties"]
        if not p.get("enabled", True):
            continue
        plan = state.get(str(p.get("targetResourceUri", "")).lower())
        if plan is None or str(plan.get("type", "")).lower() != "microsoft.web/serverfarms":
            continue
        a = st.setdefault("_autoscale", {"history": [], "last_scale": 0.0})
        pr = _profile(st, now)
        mn, mx, df = (int(pr["capacity"][k]) for k in ("minimum", "maximum", "default"))
        cur = int((plan.get("sku") or {}).get("capacity") or 1)
        outs, ins, in_all = [], [], True
        for r in pr.get("rules") or []:
            val, hit = _trigger(state, r, now, cur)
            sa = r["scaleAction"]
            if val is None:
                a["history"].append({"time": now, "profile": pr["name"], "note": f"metric '{r['metricTrigger']['metricName']}' unavailable for "
                                     f"{r['metricTrigger']['metricResourceUri'].rsplit('/', 1)[-1]}; rule skipped"})
                continue
            cd = _secs(sa.get("cooldown"), 300)
            if sa["direction"] == "Increase":
                if hit and now - a["last_scale"] >= cd:
                    outs.append((_target(cur, sa), r["metricTrigger"], val))
            elif sa["direction"] == "Decrease":
                if not (hit and now - a["last_scale"] >= cd):
                    in_all = False
                else:
                    ins.append((_target(cur, sa), r["metricTrigger"], val))
        new, why = cur, None
        if outs:
            new, mt, val = max(outs, key=lambda x: x[0])
            why = f"{mt['metricName']} {mt['statistic']} {round(val, 2)} {mt['operator']} {mt['threshold']} over {mt['timeWindow']}"
        elif ins and in_all:
            new, mt, val = max(ins, key=lambda x: x[0])
            why = f"{mt['metricName']} {mt['statistic']} {round(val, 2)} {mt['operator']} {mt['threshold']} over {mt['timeWindow']}"
        if new < mn or new > mx:
            new = max(mn, min(mx, new))
            why = (why + "; " if why else "") + f"clamped to profile capacity {mn}..{mx}"
        elif not why and (cur < mn or cur > mx):
            new, why = max(mn, min(mx, cur)), f"instance count {cur} outside profile capacity {mn}..{mx}"
        if new != cur:
            plan.setdefault("sku", {})["capacity"] = new
            a["last_scale"] = now
            rec = {"time": now, "profile": pr["name"], "from": cur, "to": new, "reason": why, "plan": plan["id"]}
            a["history"].append(rec)
            del a["history"][:-HIST_MAX]
            _event(state, plan, st, new > cur, cur, new, why)
            actions.append(dict(rec, setting=st["name"]))
    return actions


def history(setting):
    return list((setting.get("_autoscale") or {}).get("history") or [])
