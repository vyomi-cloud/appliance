"""Azure Monitor alerting engine (``Microsoft.AlertsManagement``) - REAL alert evaluation + action-group delivery.

Substrate-free (no fastapi / sockets other than an optional outbound webhook POST), so the SAME file runs offline and in Nano.

ARM resources (azure-mgmt-alertsmanagement / ``az monitor alert-processing-rule`` / ``az rest`` work unchanged):

    Microsoft.AlertsManagement/alerts                  2019-03-01  GetAll / GetById / ChangeState (POST .../changestate?newState=) / GetHistory
    Microsoft.AlertsManagement/alertsSummary           2019-03-01  GET ?groupby=severity,alertState,...
    Microsoft.AlertsManagement/actionRules             2021-08-08  alert PROCESSING rules: CreateOrUpdate / Update / Delete / Get / ListBy*
    Microsoft.AlertsManagement/prometheusRuleGroups    2023-03-01  CreateOrUpdate / Delete / Get / ListBy*  (ARM + rule validation only)
    Microsoft.AlertsManagement/evaluate                Vyomi extension  POST  - run the evaluation loop now (``force``)

What is REAL (an alert is only ever raised because a rule's condition was actually met on stored data):

* ``Microsoft.Insights/metricAlerts``      - each criterion is evaluated over the rule's ``windowSize`` against the SAME metric store the
  Metrics blade reads (``azure_monitor_core.get_metrics``: Activity-log operation counts, storage-account metrics, measured request
  telemetry). All criteria must breach (AND). Auto-mitigate resolves the alert when the condition clears.
* ``Microsoft.Insights/activityLogAlerts`` - every Activity-log row recorded after the rule was created that matches the rule's
  ``condition.allOf`` (category/operationName/resourceGroup/resourceType/resourceId/status/level/caller ...) within its scopes fires one alert.
* ``Microsoft.Insights/scheduledQueryRules`` (log search alerts) - the rule's KQL is executed by the REAL Log Analytics KQL engine
  (``azure_operationalinsights_core.run_kql``) over the workspace's stored rows (``AzureActivity`` + ingested custom ``_CL`` tables) restricted
  to the evaluation window; the Count / measure-column aggregate is compared with the threshold.
* Action groups - a fired alert invokes every receiver of every action group on the rule (plus groups ADDED by a matching processing rule).
  ``webhookReceivers`` get a REAL outbound HTTP POST (common alert schema when ``useCommonAlertSchema``); the result is stored in the alert's
  history. Email/SMS/voice/push receivers cannot be delivered (no mail/SMS gateway in Vyomi): the invocation is recorded as such, never as sent.
* Alert processing rules - ``RemoveAllActionGroups`` suppresses notifications (alert still raised, ``actionStatus.isSuppressed``);
  ``AddActionGroups`` adds groups; scopes, conditions (Equals/NotEquals/Contains/DoesNotContain) and one-off/daily/weekly schedules are enforced.
* Every activation/resolution is written to the Activity log (category ``Alert``).

Evaluation runs on demand (``evaluate``): whenever alerts are read through ARM and via the POST ``evaluate`` extension; each rule honours its
own ``evaluationFrequency`` unless ``force``. There is no background timer inside the core (Nano has none) - a substrate may call ``evaluate``
on a timer.
NOT modelled: dynamic-threshold criteria (need learned baselines), Prometheus rule *evaluation* (no PromQL / Prometheus store),
smart groups, availability (web test) criteria, dimension splitting.
``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}``.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

try:
    from core import azure_monitor_core as mon
    from core import azure_operationalinsights_core as oi
except ImportError:  # pragma: no cover - Pyodide flat layout
    import azure_monitor_core as mon  # type: ignore
    import azure_operationalinsights_core as oi  # type: ignore

NAMESPACE = "Microsoft.AlertsManagement"
API_VERSIONS = {"alerts": "2019-03-01", "alertssummary": "2019-03-01", "actionrules": "2021-08-08", "prometheusrulegroups": "2023-03-01"}
ALERT_TYPE = f"{NAMESPACE}/alerts"
SEVERITIES = {0: "Sev0", 1: "Sev1", 2: "Sev2", 3: "Sev3", 4: "Sev4"}
ALERT_STATES = ("New", "Acknowledged", "Closed")
_EVENT_TYPE = "Microsoft.Insights/eventtypes"
MAX_ALERTS = 2000

#: optional hook (url, body: dict, headers: dict) -> (ok: bool, detail: str); None = built-in urllib POST (3 s timeout)
deliver_webhook = None


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _ok(body=None, status=200, headers=None, rid="", verb=""):
    return {"status": status, "headers": headers or {}, "body": body, "lro": False, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}, "lro": False, "rid": "", "verb": ""}


def _bad(msg):
    return _E(400, "BadRequest", msg)


def _now(d=None):
    return (d or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _parse(ts):
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ═══════════════════════════ actionRules (alert processing rules) ═══════════════
RULE_FIELDS = ("Severity", "MonitorService", "MonitorCondition", "SignalType", "TargetResourceType", "TargetResource",
               "TargetResourceGroup", "AlertRuleId", "AlertRuleName", "Description", "AlertContext")
RULE_OPS = ("Equals", "NotEquals", "Contains", "DoesNotContain")
ACTION_TYPES = ("AddActionGroups", "RemoveAllActionGroups")


def _action_rule_props(props, old=None):
    p = dict(old or {})
    p.update(props)
    scopes = p.get("scopes")
    if not isinstance(scopes, list) or not scopes or not all(isinstance(x, str) and x.lower().startswith("/subscriptions/") for x in scopes):
        raise _bad("The property 'scopes' must contain at least one subscription / resource group / resource id.")
    conds = []
    for c in p.get("conditions") or []:
        if not isinstance(c, dict):
            raise _bad("conditions must contain objects.")
        f = next((x for x in RULE_FIELDS if x.lower() == str(c.get("field", "")).lower()), None)
        o = next((x for x in RULE_OPS if x.lower() == str(c.get("operator", "")).lower()), None)
        vals = c.get("values")
        if f is None:
            raise _bad(f"The condition field '{c.get('field')}' is invalid. Allowed: {', '.join(RULE_FIELDS)}.")
        if o is None:
            raise _bad(f"The condition operator '{c.get('operator')}' is invalid. Allowed: {', '.join(RULE_OPS)}.")
        if not isinstance(vals, list) or not vals:
            raise _bad("Each condition needs a non-empty 'values' array.")
        conds.append({"field": f, "operator": o, "values": [str(v) for v in vals]})
    acts = p.get("actions")
    if not isinstance(acts, list) or not acts:
        raise _bad("The property 'actions' must contain at least one action.")
    norm = []
    for a in acts:
        t = next((x for x in ACTION_TYPES if x.lower() == str((a or {}).get("actionType", "")).lower()), None)
        if t is None:
            raise _bad(f"The actionType '{(a or {}).get('actionType')}' is invalid. Allowed: {', '.join(ACTION_TYPES)}.")
        if t == "AddActionGroups":
            ids = a.get("actionGroupIds")
            if not isinstance(ids, list) or not ids:
                raise _bad("AddActionGroups needs 'actionGroupIds'.")
            norm.append({"actionType": t, "actionGroupIds": [mon._ag_id(i) for i in ids]})
        else:
            norm.append({"actionType": t})
    sched = p.get("schedule")
    if sched is not None:
        if not isinstance(sched, dict):
            raise _bad("The property 'schedule' must be an object.")
        for k in ("effectiveFrom", "effectiveUntil"):
            if sched.get(k) and _parse(sched[k]) is None and not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?", str(sched[k])):
                raise _bad(f"schedule.{k} must be an ISO 8601 date-time.")
        for rec_ in sched.get("recurrences") or []:
            if str((rec_ or {}).get("recurrenceType", "")).lower() not in ("daily", "weekly", "monthly"):
                raise _bad("schedule.recurrences[].recurrenceType must be Daily, Weekly or Monthly.")
    return {"scopes": scopes, "conditions": conds, "actions": norm, "schedule": sched,
            "description": p.get("description") or "", "enabled": bool(p.get("enabled", True))}


def _hms(s, default):
    m = re.fullmatch(r"(\d\d):(\d\d)(?::(\d\d))?", str(s or ""))
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3) or 0)) if m else default


def _schedule_active(sched, now):
    """Is `now` (UTC) inside the processing rule's schedule? No schedule = always."""
    if not sched:
        return True
    f, u = _parse(sched.get("effectiveFrom")), _parse(sched.get("effectiveUntil"))
    if f and now < f:
        return False
    if u and now > u:
        return False
    recs = sched.get("recurrences") or []
    if not recs:
        return True
    secs = now.hour * 3600 + now.minute * 60 + now.second
    for r in recs:
        t = str(r.get("recurrenceType", "")).lower()
        a, b = _hms(r.get("startTime"), 0), _hms(r.get("endTime"), 86399)
        in_time = (a <= secs <= b) if a <= b else (secs >= a or secs <= b)
        if t == "daily" and in_time:
            return True
        if t == "weekly" and in_time and now.strftime("%A").lower() in [str(d).lower() for d in r.get("daysOfWeek") or []]:
            return True
        if t == "monthly" and in_time and now.day in [int(d) for d in r.get("daysOfMonth") or []]:
            return True
    return False


def _alert_field(alert, field):
    e = alert["properties"]["essentials"]
    return {"Severity": e["severity"], "MonitorService": e["monitorService"], "MonitorCondition": e["monitorCondition"],
            "SignalType": e["signalType"], "TargetResourceType": e.get("targetResourceType", ""), "TargetResource": e.get("targetResource", ""),
            "TargetResourceGroup": e.get("targetResourceGroup", ""), "AlertRuleId": e.get("alertRule", ""),
            "AlertRuleName": (e.get("alertRule") or "").rsplit("/", 1)[-1], "Description": e.get("description", ""),
            "AlertContext": json.dumps(alert["properties"].get("context") or {})}[field]


def _cond_match(c, alert):
    v = str(_alert_field(alert, c["field"])).lower()
    vals = [x.lower() for x in c["values"]]
    if c["operator"] == "Equals":
        return v in vals
    if c["operator"] == "NotEquals":
        return v not in vals
    if c["operator"] == "Contains":
        return any(x in v for x in vals)
    return not any(x in v for x in vals)


def _matching_rules(state, sub, alert, now):
    target = (alert["properties"]["essentials"].get("targetResource") or "").lower().rstrip("/")
    out = []
    for r in state.values():
        if str(r.get("_type", "")).lower() != f"{NAMESPACE}/actionRules".lower() or r.get("_sub") != sub:
            continue
        p = r["properties"]
        if not p.get("enabled", True) or not _schedule_active(p.get("schedule"), now):
            continue
        if not any(target == s.lower().rstrip("/") or target.startswith(s.lower().rstrip("/") + "/") for s in p["scopes"]):
            continue
        if all(_cond_match(c, alert) for c in p["conditions"]):
            out.append(r)
    return out


# ═══════════════════════════ prometheusRuleGroups ═══════════════════════════════
def _prom_props(props, old=None):
    p = dict(old or {})
    p.update(props)
    scopes = p.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        raise _bad("The property 'scopes' must contain the Azure Monitor workspace resource id.")
    rules = p.get("rules")
    if not isinstance(rules, list) or not rules:
        raise _bad("The property 'rules' must contain at least one rule.")
    norm = []
    for i, r in enumerate(rules):
        if not isinstance(r, dict) or not str(r.get("expression") or "").strip():
            raise _bad(f"rules[{i}].expression is required.")
        if bool(r.get("record")) == bool(r.get("alert")):
            raise _bad(f"rules[{i}] must set exactly one of 'record' (recording rule) or 'alert' (alerting rule).")
        expr = str(r["expression"])
        if expr.count("(") != expr.count(")") or expr.count("{") != expr.count("}") or expr.count("[") != expr.count("]"):
            raise _bad(f"rules[{i}].expression has unbalanced brackets.")
        r = dict(r)
        if r.get("alert"):
            sev = r.get("severity", 3)
            if not isinstance(sev, int) or not 0 <= sev <= 4:
                raise _bad(f"rules[{i}].severity must be 0-4.")
            r["actions"] = [{"actionGroupId": mon._ag_id((a or {}).get("actionGroupId")),
                             "actionProperties": dict((a or {}).get("actionProperties") or {})} for a in r.get("actions") or []]
        norm.append(r)
    interval = p.get("interval") or "PT1M"
    if not re.fullmatch(r"P(T\d+[HMS])+|P\d+D", str(interval)):
        raise _bad("The property 'interval' must be an ISO 8601 duration.")
    return {"description": p.get("description") or "", "enabled": bool(p.get("enabled", True)), "clusterName": p.get("clusterName") or "",
            "interval": interval, "scopes": scopes, "rules": norm}


# ═══════════════════════════ firing, resolving, notifying ═══════════════════════
def _seq():
    return int(datetime.now(timezone.utc).timestamp() * 1e6)


def _log_activity(state, sub, rg, rule_id, op, text):
    eid = f"{rule_id}/__event__/{uuid.uuid4().hex}"
    state[eid.lower()] = {
        "id": eid, "_type": _EVENT_TYPE, "_sub": sub, "_seq": _seq(), "eventTimestamp": _now(), "submissionTimestamp": _now(),
        "resourceId": rule_id, "subscriptionId": sub, "resourceGroupName": rg or "",
        "resourceProviderName": {"value": "Microsoft.Insights", "localizedValue": "Microsoft Insights"},
        "category": {"value": "Alert", "localizedValue": "Alert"}, "caller": "Microsoft.Insights/AlertRules", "level": "Warning",
        "eventName": {"value": "Alert", "localizedValue": "Alert"},
        "operationName": {"value": op, "localizedValue": text},
        "status": {"value": "Succeeded", "localizedValue": "Succeeded"}, "subStatus": {"value": "", "localizedValue": ""}}


def _post(url, body, headers):
    if deliver_webhook is not None:
        return deliver_webhook(url, body, headers)
    try:
        import urllib.request
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
        with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310 - user-configured receiver URL (http/https enforced at PUT)
            return 200 <= resp.status < 300, f"HTTP {resp.status}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:160]}"


def _common_schema(alert, resolved=False):
    e = alert["properties"]["essentials"]
    return {"schemaId": "azureMonitorCommonAlertSchema",
            "data": {"essentials": {"alertId": alert["id"], "alertRule": e["alertRule"].rsplit("/", 1)[-1], "severity": e["severity"],
                                    "signalType": e["signalType"], "monitorCondition": "Resolved" if resolved else "Fired",
                                    "monitoringService": e["monitorService"], "alertTargetIDs": [e.get("targetResource", "")],
                                    "originAlertId": alert["name"], "firedDateTime": e["startDateTime"],
                                    "resolvedDateTime": e.get("monitorConditionResolvedDateTime"), "description": e.get("description", ""),
                                    "essentialsVersion": "1.0", "alertContextVersion": "1.0"},
                     "alertContext": alert["properties"].get("context") or {}}}


def _legacy_body(alert, resolved=False):
    e = alert["properties"]["essentials"]
    return {"status": "Resolved" if resolved else "Activated", "context": {
        "id": alert["id"], "name": e["alertRule"].rsplit("/", 1)[-1], "description": e.get("description", ""),
        "timestamp": e["startDateTime"], "resourceId": e.get("targetResource", ""), "resourceName": e.get("targetResourceName", ""),
        "resourceGroupName": e.get("targetResourceGroup", ""), "severity": e["severity"], "details": alert["properties"].get("context") or {}},
        "properties": {}}


def _notify(state, sub, alert, group_ids, extra_props, resolved=False):
    """Invoke every receiver of the action groups; append one history entry per receiver. Returns suppressed=False."""
    seen = set()
    for gid in group_ids:
        if gid.lower() in seen:
            continue
        seen.add(gid.lower())
        g = state.get(gid.lower())
        if g is None or str(g.get("_type", "")).lower() != "microsoft.insights/actiongroups":
            _history(alert, "ActionInvoked", f"Action group '{gid.rsplit('/', 1)[-1]}' not found - skipped")
            continue
        gp = g["properties"]
        if not gp.get("enabled", True):
            _history(alert, "ActionInvoked", f"Action group '{g['name']}' is disabled - skipped")
            continue
        for lst in mon.RECEIVER_LISTS:
            for rcv in gp.get(lst) or []:
                label = f"{g['name']}/{rcv.get('name')}"
                if lst == "webhookReceivers":
                    body = _common_schema(alert, resolved) if rcv.get("useCommonAlertSchema") else _legacy_body(alert, resolved)
                    if not rcv.get("useCommonAlertSchema") and extra_props:
                        body["properties"] = dict(extra_props)
                    ok, detail = _post(rcv["serviceUri"], body, {})
                    _history(alert, "ActionInvoked", f"webhook {label}: {'delivered' if ok else 'FAILED'} ({detail})", delivered=ok)
                else:
                    kind = lst[: -len("Receivers")]
                    _history(alert, "ActionInvoked", f"{kind} {label}: invocation recorded - Vyomi has no {kind} gateway, nothing was sent",
                             delivered=False)


def _history(alert, kind, text, **extra):
    h = alert.setdefault("_history", [])
    h.append({"properties": {"eventType": kind, "timestamp": _now(), "description": text, **extra}})
    del h[:-200]


def _target_parts(target):
    segs = [s for s in str(target).split("/") if s]
    low = [s.lower() for s in segs]
    rg = segs[low.index("resourcegroups") + 1] if "resourcegroups" in low and low.index("resourcegroups") + 1 < len(segs) else ""
    rtype = ""
    if "providers" in low:
        i = low.index("providers")
        tail = segs[i + 1:]
        if len(tail) >= 3:
            rtype = tail[0] + "/" + "/".join(tail[1::2])
    return rg, rtype, segs[-1] if segs else ""


def _new_alert(state, sub, rule, target, signal, service, description, context, severity, now):
    aid = str(uuid.uuid4())
    rg, rtype, tname = _target_parts(target)
    rule_rg = rule.get("_rg") or rg
    props = {"essentials": {
        "severity": SEVERITIES[severity], "signalType": signal, "alertState": "New", "monitorCondition": "Fired",
        "monitorService": service, "targetResource": target, "targetResourceName": tname, "targetResourceGroup": rg,
        "targetResourceType": rtype, "alertRule": rule["id"], "startDateTime": _now(now), "lastModifiedDateTime": _now(now),
        "lastModifiedUserName": "System", "description": description, "actionStatus": {"isSuppressed": False}},
        "context": context}
    rec = {"id": f"/subscriptions/{sub}/providers/{NAMESPACE}/alerts/{aid}", "name": aid, "type": ALERT_TYPE, "properties": props,
           "_type": ALERT_TYPE.lower(), "_sub": sub, "_rg": None, "_rule": rule["id"].lower(), "_target": target.lower()}
    state[rec["id"].lower()] = rec
    _history(rec, "StateChange", "Alert fired (monitor condition Fired, state New)", newValue="New")
    _log_activity(state, sub, rule_rg, rule["id"], "Microsoft.Insights/AlertRules/Activated/action", f"Alert '{rule['name']}' activated")
    rules = _matching_rules(state, sub, rec, now)
    suppressed = any(a["actionType"] == "RemoveAllActionGroups" for r in rules for a in r["properties"]["actions"])
    groups = [] if suppressed else _rule_groups(rule)
    if not suppressed:
        groups += [i for r in rules for a in r["properties"]["actions"] if a["actionType"] == "AddActionGroups" for i in a["actionGroupIds"]]
    if suppressed:
        props["essentials"]["actionStatus"]["isSuppressed"] = True
        _history(rec, "ActionSuppressed", "Notifications suppressed by alert processing rule: "
                 + ", ".join(r["name"] for r in rules if any(a["actionType"] == "RemoveAllActionGroups" for a in r["properties"]["actions"])))
    elif rules:
        _history(rec, "ProcessingRule", "Alert processing rules applied: " + ", ".join(r["name"] for r in rules))
    extra = {}
    for a in (rule["properties"].get("actions") or []) if isinstance(rule["properties"].get("actions"), list) else []:
        extra.update(a.get("webHookProperties") or {})
    _notify(state, sub, rec, groups, extra)
    # cap the store
    alerts = [r for r in state.values() if r.get("_type") == ALERT_TYPE.lower() and r.get("_sub") == sub]
    if len(alerts) > MAX_ALERTS:
        alerts.sort(key=lambda r: r["properties"]["essentials"]["startDateTime"])
        for r in alerts[: len(alerts) - MAX_ALERTS]:
            state.pop(r["id"].lower(), None)
    return rec


def _rule_groups(rule):
    p = rule["properties"]
    acts = p.get("actions")
    if isinstance(acts, list):                                   # metric alert
        return [a["actionGroupId"] for a in acts]
    if isinstance(acts, dict):
        out = []
        for a in acts.get("actionGroups") or []:
            out.append(a["actionGroupId"] if isinstance(a, dict) else a)
        return out
    return []


def _resolve(state, sub, alert, now, reason):
    e = alert["properties"]["essentials"]
    if e["monitorCondition"] == "Resolved":
        return
    e["monitorCondition"] = "Resolved"
    e["monitorConditionResolvedDateTime"] = _now(now)
    e["lastModifiedDateTime"] = _now(now)
    _history(alert, "StateChange", f"Alert resolved: {reason}", newValue="Resolved")
    rid = alert["_rule"]
    rule = state.get(rid)
    if rule is not None:
        _log_activity(state, sub, rule.get("_rg"), rule["id"], "Microsoft.Insights/AlertRules/Resolved/action", f"Alert '{rule['name']}' resolved")
        if not e["actionStatus"]["isSuppressed"]:
            _notify(state, sub, alert, _rule_groups(rule), {}, resolved=True)


def _open_alert(state, rule_key, target):
    for r in state.values():
        if (r.get("_type") == ALERT_TYPE.lower() and r.get("_rule") == rule_key and r.get("_target") == target.lower()
                and r["properties"]["essentials"]["monitorCondition"] == "Fired"):
            return r
    return None


# ═══════════════════════════ rule evaluation ════════════════════════════════════
_CMP = {"Equals": lambda a, b: a == b, "GreaterThan": lambda a, b: a > b, "GreaterThanOrEqual": lambda a, b: a >= b,
        "LessThan": lambda a, b: a < b, "LessThanOrEqual": lambda a, b: a <= b}


def _agg(values, how):
    if not values:
        return None
    return {"Total": sum(values), "Count": sum(values), "Average": sum(values) / len(values), "Minimum": min(values), "Maximum": max(values)}[how]


def _metric_value(state, scope, crit, win_min, blob_store, now):
    interval = next(i for i in mon.WINDOW_SIZES if win_min / mon._DUR_MIN[i] <= 400)
    start = now - timedelta(minutes=win_min)
    end = now + timedelta(seconds=1)            # the metrics API takes whole seconds; never cut off events from this very second
    ts = f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    how = crit["timeAggregation"]
    r = mon.get_metrics(state, scope, {"metricnames": crit["metricName"], "aggregation": how, "interval": interval, "timespan": ts},
                        blob_store, rg_exists=True)
    if r["status"] != 200:
        return None, r["body"]["error"]["message"]
    series = (r["body"]["value"][0].get("timeseries") or [{}])[0].get("data") or []
    vals = [p[how.lower()] for p in series if p.get(how.lower()) is not None]
    return _agg(vals, how), ""


def _eval_metric(state, sub, rule, blob_store, now, ev):
    p = rule["properties"]
    win = mon._DUR_MIN[p["windowSize"]]
    allof = p["criteria"].get("allOf") or []
    for scope in p["scopes"]:
        breached, parts, nodata = True, [], False
        for c in allof:
            if c.get("criterionType") == "DynamicThresholdCriterion":
                ev["unsupported"].append(f"{rule['name']}: dynamic threshold criteria are not evaluated")
                nodata = True
                break
            v, why = _metric_value(state, scope, c, win, blob_store, now)
            if v is None:
                nodata = True
                ev["nodata"].append(f"{rule['name']}/{c['name']}: {why or 'no data in window'}")
                break
            hit = _CMP[c["operator"]](v, c["threshold"])
            parts.append(f"{c['metricName']} ({c['timeAggregation']}) = {round(v, 3)} {c['operator']} {c['threshold']}")
            breached = breached and hit
        if nodata:
            continue
        yield scope, breached, "; ".join(parts), {"conditionType": "SingleResourceMultipleMetricCriteria", "condition": parts,
                                                   "windowSize": p["windowSize"], "evaluationFrequency": p["evaluationFrequency"]}


def _eval_sqr(state, sub, rule, now, ev):
    p = rule["properties"]
    win = timedelta(minutes=mon._DUR_MIN.get(p["windowSize"], 2880 if p["windowSize"] == "P2D" else 5))
    start = _now(now - win)
    for scope in p["scopes"]:
        ws = state.get(scope.lower())
        if ws is None:
            ev["nodata"].append(f"{rule['name']}: workspace '{scope}' not found")
            continue
        rows = {t: [r for r in rs if str(r.get("TimeGenerated") or "") >= start] for t, rs in (ws.get("_rows") or {}).items()}
        act = [r for r in oi.activity_table(state, sub) if str(r.get("TimeGenerated") or "") >= start]
        view = {"_rows": rows, "_tables": ws.get("_tables", {})}
        breached, parts = True, []
        for c in p["criteria"]["allOf"]:
            try:
                res = oi.run_kql(view, c["query"], {"AzureActivity": act})["tables"][0]
            except oi.KqlError as e:
                ev["errors"].append(f"{rule['name']}: {e}")
                breached = None
                break
            names = [x["name"] for x in res["columns"]]
            if c["timeAggregation"] == "Count" and not c.get("metricMeasureColumn"):
                val = len(res["rows"])
            else:
                col = next((n for n in names if n.lower() == str(c.get("metricMeasureColumn", "")).lower()), None)
                if col is None:
                    ev["errors"].append(f"{rule['name']}: result has no column '{c.get('metricMeasureColumn')}'")
                    breached = None
                    break
                nums = [r[names.index(col)] for r in res["rows"] if isinstance(r[names.index(col)], (int, float))]
                val = _agg(nums, c["timeAggregation"])
                if val is None:
                    breached = False
                    continue
            hit = _CMP[c["operator"]](val, c["threshold"])
            parts.append(f"query result {c['timeAggregation']} = {round(val, 3) if isinstance(val, float) else val} {c['operator']} {c['threshold']}")
            breached = breached and hit
        if breached is None:
            continue
        yield scope, breached, "; ".join(parts), {"conditionType": "LogQueryCriteria", "condition": parts,
                                                   "query": p["criteria"]["allOf"][0]["query"], "windowSize": p["windowSize"]}


def _event_value(ev_, field):
    f = field.lower()
    def val(k):
        v = ev_.get(k)
        return v.get("value") if isinstance(v, dict) else v
    if f == "category":
        return val("category") or "Administrative"
    if f in ("operationname",):
        return val("operationName")
    if f == "resourcegroup":
        return ev_.get("resourceGroupName")
    if f == "resourceid":
        return ev_.get("resourceId")
    if f == "resourcetype":
        return _target_parts(ev_.get("resourceId") or "")[1]
    if f == "resourceprovider":
        return (_target_parts(ev_.get("resourceId") or "")[1] or "/").split("/")[0]
    if f == "status":
        return val("status")
    if f == "substatus":
        return val("subStatus")
    if f == "level":
        return ev_.get("level")
    if f == "caller":
        return ev_.get("caller")
    return None


def _activity_match(rule, ev_):
    rid = str(ev_.get("resourceId", "")).lower()
    if not any(rid == s.lower().rstrip("/") or rid.startswith(s.lower().rstrip("/") + "/") for s in rule["properties"]["scopes"]):
        return False
    for c in rule["properties"]["condition"]["allOf"]:
        v = str(_event_value(ev_, c["field"]) or "").lower()
        if c.get("equals") and v != str(c["equals"]).lower():
            return False
        if c.get("containsAny") and not any(str(x).lower() in v for x in c["containsAny"]):
            return False
    return True


def evaluate(state, sub, blob_store=None, force=False, now=None):
    """Run every enabled alert rule once. Returns a summary dict (fired / resolved / evaluated / nodata / errors / unsupported)."""
    now = now or datetime.now(timezone.utc)
    ev = {"evaluated": 0, "fired": 0, "resolved": 0, "nodata": [], "errors": [], "unsupported": []}
    rules = [r for r in list(state.values()) if r.get("_sub") == sub and str(r.get("_type", "")).lower() in
             ("microsoft.insights/metricalerts", "microsoft.insights/activitylogalerts", "microsoft.insights/scheduledqueryrules")]
    for rule in rules:
        if not rule["properties"].get("enabled", True):
            continue
        key = rule["id"].lower()
        st = rule.setdefault("_eval", {})
        rtype = str(rule["_type"]).lower()
        st.setdefault("since", rule.get("_created") or _now(now))
        if rtype != "microsoft.insights/activitylogalerts" and not force:
            freq = mon._DUR_MIN.get(rule["properties"].get("evaluationFrequency"), 1)
            last = _parse(st.get("last"))
            if last and now - last < timedelta(minutes=freq):
                continue
        st["last"] = _now(now)
        ev["evaluated"] += 1
        try:
            if rtype == "microsoft.insights/activitylogalerts":
                since = st["since"]
                seen = st.setdefault("seen", [])
                events = sorted((e for e in state.values() if e.get("_type", "").lower() == _EVENT_TYPE.lower() and e.get("_sub") == sub
                                 and str(e.get("eventTimestamp") or "") >= since and e["id"] not in seen),
                                key=lambda e: (e.get("eventTimestamp") or "", e.get("_seq", 0)))
                for e in events:
                    seen.append(e["id"])
                    if _activity_match(rule, e):
                        _new_alert(state, sub, rule, e.get("resourceId", ""), "Activity Log", "Activity Log - Administrative",
                                   f"{(e.get('operationName') or {}).get('value') if isinstance(e.get('operationName'), dict) else e.get('operationName')} "
                                   f"({(e.get('status') or {}).get('value') if isinstance(e.get('status'), dict) else e.get('status')})",
                                   {"activityLog": {k: e.get(k) for k in ("eventTimestamp", "resourceId", "caller", "operationName", "status")}},
                                   2, now)
                        ev["fired"] += 1
                del seen[:-2000]
                continue
            gen = _eval_metric(state, sub, rule, blob_store, now, ev) if rtype == "microsoft.insights/metricalerts" else _eval_sqr(state, sub, rule, now, ev)
            for target, breached, text, ctx in gen:
                open_ = _open_alert(state, key, target)
                if breached and open_ is None:
                    sev = rule["properties"].get("severity", 3)
                    _new_alert(state, sub, rule, target, "Metric" if rtype.endswith("metricalerts") else "Log",
                               "Platform" if rtype.endswith("metricalerts") else "Log Alerts V2",
                               rule["properties"].get("description") or text, dict(ctx, evaluatedAt=_now(now), result=text), sev, now)
                    ev["fired"] += 1
                elif not breached and open_ is not None and rule["properties"].get("autoMitigate", True):
                    _resolve(state, sub, open_, now, text)
                    ev["resolved"] += 1
        except Exception as e:  # noqa: BLE001 - one broken rule must not stop the others
            ev["errors"].append(f"{rule['name']}: {type(e).__name__}: {e}")
    return ev


# ═══════════════════════════ ARM surface ════════════════════════════════════════
def handles(namespace, chain):
    return str(namespace).lower() == "microsoft.alertsmanagement" and bool(chain) and chain[0].lower() in (
        "alerts", "alertssummary", "actionrules", "prometheusrulegroups", "evaluate")


def _alerts_of(state, sub):
    return [r for r in state.values() if r.get("_type") == ALERT_TYPE.lower() and r.get("_sub") == sub]


def _filter_alerts(items, q):
    def f(key, getter):
        nonlocal items
        v = (q or {}).get(key)
        if v:
            want = {x.strip().lower() for x in str(v).split(",")}
            items = [a for a in items if str(getter(a["properties"]["essentials"]) or "").lower() in want]
    f("severity", lambda e: e["severity"]); f("alertState", lambda e: e["alertState"]); f("monitorCondition", lambda e: e["monitorCondition"])
    f("monitorService", lambda e: e["monitorService"]); f("targetResource", lambda e: e.get("targetResource"))
    f("targetResourceGroup", lambda e: e.get("targetResourceGroup")); f("targetResourceType", lambda e: e.get("targetResourceType"))
    f("alertRule", lambda e: e.get("alertRule"))
    tr = (q or {}).get("timeRange")
    if tr:
        m = re.fullmatch(r"(\d+)([hd])", tr)
        if m:
            cut = _now(datetime.now(timezone.utc) - timedelta(hours=int(m.group(1)) * (24 if m.group(2) == "d" else 1)))
            items = [a for a in items if a["properties"]["essentials"]["startDateTime"] >= cut]
    key = (q or {}).get("sortBy") or "lastModifiedDateTime"
    desc = str((q or {}).get("sortOrder") or "desc").lower() != "asc"
    items.sort(key=lambda a: str(a["properties"]["essentials"].get(key) or ""), reverse=desc)
    return items


def _summary(items, groupby):
    dims = [d.strip() for d in (groupby or "severity").split(",") if d.strip()]
    key = {"severity": "severity", "alertstate": "alertState", "monitorcondition": "monitorCondition", "monitorservice": "monitorService",
           "signaltype": "signalType", "alertrule": "alertRule", "targetresource": "targetResource", "targetresourcetype": "targetResourceType",
           "targetresourcegroup": "targetResourceGroup"}
    for d in dims:
        if d.lower() not in key:
            raise _bad(f"The groupby value '{d}' is not supported. Allowed: {', '.join(sorted(key))}.")

    def level(rows, i):
        if i >= len(dims):
            return None
        groups = {}
        for a in rows:
            groups.setdefault(str(a["properties"]["essentials"].get(key[dims[i].lower()]) or ""), []).append(a)
        out = []
        for name in sorted(groups):
            o = {"name": name, "count": len(groups[name])}
            if i + 1 < len(dims):
                o["groupedby"] = key[dims[i + 1].lower()]
                o["values"] = level(groups[name], i + 1)
            out.append(o)
        return out
    return {"properties": {"groupedby": key[dims[0].lower()], "total": len(items), "values": level(items, 0)}}


def dispatch(state, method, sub, rg, namespace, chain, payload=None, query=None, blob_store=None, base=""):
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload, query or {}, blob_store)
    except _E as e:
        return _err(e.status, e.code, e.message)


def _dispatch(state, method, sub, rg, chain, payload, query, blob_store):
    low = chain[0].lower()
    if low == "evaluate":
        if method != "POST":
            return _err(405, "MethodNotAllowed", "POST required.")
        return _ok(evaluate(state, sub, blob_store, force=True))
    if low in ("alerts", "alertssummary"):
        evaluate(state, sub, blob_store)                     # alerts are evaluated when they are read
        items = _alerts_of(state, sub)
        if low == "alertssummary":
            if method != "GET":
                return _err(405, "MethodNotAllowed", "GET required.")
            return _ok(_summary(_filter_alerts(items, query), query.get("groupby")))
        if len(chain) == 1:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "GET required.")
            items = _filter_alerts(items, query)
            return _ok({"value": [_view(a) for a in items]})
        rec = state.get(f"/subscriptions/{sub}/providers/{NAMESPACE}/alerts/{chain[1]}".lower())
        if rec is None:
            raise _E(404, "ResourceNotFound", f"Alert '{chain[1]}' was not found.")
        if len(chain) == 2:
            return _ok(_view(rec)) if method == "GET" else _err(405, "MethodNotAllowed", "GET required.")
        op = chain[2].lower()
        if op == "changestate" and method == "POST":
            ns = next((s for s in ALERT_STATES if s.lower() == str(query.get("newState") or "").lower()), None)
            if ns is None:
                raise _bad(f"The 'newState' parameter must be one of: {', '.join(ALERT_STATES)}.")
            e = rec["properties"]["essentials"]
            old, e["alertState"] = e["alertState"], ns
            e["lastModifiedDateTime"], e["lastModifiedUserName"] = _now(), "admin@vyomi.local"
            _history(rec, "StateChange", f"Alert state changed {old} -> {ns} by admin@vyomi.local", oldValue=old, newValue=ns)
            return _ok(_view(rec))
        if op == "history" and method == "GET":
            return _ok({"value": [dict(h, id=f"{rec['id']}/history/{i}", name=str(i)) for i, h in enumerate(rec.get("_history") or [])]})
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/alerts/{'/'.join(chain[2:])}' is not supported.")

    # actionRules / prometheusRuleGroups: standard ARM resource CRUD
    typ = {"actionrules": ("actionRules", _action_rule_props), "prometheusrulegroups": ("prometheusRuleGroups", _prom_props)}[low]
    tname, builder = typ
    tstr = f"{NAMESPACE}/{tname}"
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [r for r in state.values() if str(r.get("_type", "")).lower() == tstr.lower() and r.get("_sub") == sub
                 and (rg is None or (r.get("_rg") or "").lower() == rg.lower())]
        items.sort(key=lambda r: r["name"].lower())
        return _ok({"value": [_view(r) for r in items]})
    if rg is None:
        return _err(400, "InvalidResourceId", f"{tname} must be addressed within a resource group.")
    name = chain[1]
    if not name or len(name) > 260 or re.search(r"[<>*%&:\\?+/#]", name):
        raise _bad(f"The resource name '{name}' is invalid.")
    rid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{NAMESPACE}/{tname}/{name}"
    rec = state.get(rid.lower())
    if len(chain) > 2:
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{tstr}/{'/'.join(chain[2:])}' is not supported.")
    if method == "GET":
        if rec is None:
            raise _E(404, "ResourceNotFound", f"The Resource '{tstr}/{name}' under resource group '{rg}' was not found.")
        return _ok(_view(rec))
    if method in ("PUT", "PATCH"):
        if method == "PATCH" and rec is None:
            raise _E(404, "ResourceNotFound", f"The Resource '{tstr}/{name}' under resource group '{rg}' was not found.")
        if method == "PATCH":
            props_in = (payload.get("properties") if isinstance(payload.get("properties"), dict) else None)
            props = dict(rec["properties"])
            if "enabled" in payload.get("properties", {}) or (props_in is None and "enabled" in payload):
                props["enabled"] = bool((props_in or payload).get("enabled"))
            rec["properties"] = props
            if isinstance(payload.get("tags"), dict):
                rec["tags"] = dict(payload["tags"])
            return _ok(_view(rec), 200, rid=rid, verb="patch")
        pin = payload.get("properties")
        if not isinstance(pin, dict):
            raise _bad("The request body must contain 'properties'.")
        props = builder(pin, None)
        created = rec is None
        rec = {"id": rid, "name": name, "type": tstr, "location": payload.get("location") or "global", "tags": dict(payload.get("tags") or {}),
               "properties": props, "_type": tstr.lower(), "_sub": sub, "_rg": rg}
        state[rid.lower()] = rec
        return _ok(_view(rec), 201 if created else 200, rid=rid, verb="put")
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        state.pop(rid.lower(), None)
        return _ok(None, 200, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")
