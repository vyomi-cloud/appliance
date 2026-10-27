"""Azure Monitor core (``Microsoft.Insights`` — action groups, metric alerts, activity log alerts, autoscale).

Substrate-free (no fastapi / sockets / subprocess) so the SAME file runs offline and in Nano.

ARM REST of the ``monitor`` resource provider (azure-rest-api-specs ``specification/monitor/resource-manager``),
so ``azure-mgmt-monitor`` / ``armmonitor`` / ``com.azure.resourcemanager.monitor`` and ``az rest`` against
``Microsoft.Insights`` work unchanged:

    Microsoft.Insights/actionGroups          2023-01-01  CreateOrUpdate / Update / Delete / Get / ListBy*
                                                         .../subscribe (EnableReceiver)  .../createNotifications
    Microsoft.Insights/createNotifications   2023-01-01  POST at subscription scope (test notifications)
    Microsoft.Insights/notificationStatus    2023-01-01  GET  .../notificationStatus/{id}
    Microsoft.Insights/metricAlerts          2018-03-01  CreateOrUpdate / Update / Delete / Get / ListBy*  .../status
    Microsoft.Insights/activityLogAlerts     2020-10-01  CreateOrUpdate / Update / Delete / Get / ListBy*
    Microsoft.Insights/autoscaleSettings     2022-10-01  CreateOrUpdate / Update / Delete / Get / ListBy*

Resources live in the shared ARM state map (offline ``azure_services._state``; Nano ``az_arm``), keyed by the
lower-cased resource id, so they are space-scoped and persisted by the same seams as the rest of ARM.
Not modelled: diagnostic settings, metric definitions / metrics and scheduled query rules (resource-scoped
extension APIs), and conditional headers (If-Match / If-None-Match).

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}`` (``body`` is a JSON-able object or ``None``).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

NAMESPACE = "Microsoft.Insights"
API_VERSION = "2018-03-01"                    # primary catalog type (metricAlerts)
DEFAULT_LOCATION = "global"

# lower-case collection name → (ARM type, canonical segment, api-version)
TYPES = {
    "actiongroups": ("actionGroups", "2023-01-01"),
    "metricalerts": ("metricAlerts", "2018-03-01"),
    "activitylogalerts": ("activityLogAlerts", "2020-10-01"),
    "autoscalesettings": ("autoscaleSettings", "2022-10-01"),
}
# ARM echoes these type strings back (autoscale is lower-cased in the real service)
TYPE_STRINGS = {"actiongroups": "Microsoft.Insights/actionGroups", "metricalerts": "Microsoft.Insights/metricAlerts",
                "activitylogalerts": "Microsoft.Insights/activityLogAlerts",
                "autoscalesettings": "Microsoft.Insights/autoscaleSettings"}

EVAL_FREQUENCIES = ("PT1M", "PT5M", "PT15M", "PT30M", "PT1H")
WINDOW_SIZES = ("PT1M", "PT5M", "PT15M", "PT30M", "PT1H", "PT6H", "PT12H", "P1D")
_DUR_MIN = {"PT1M": 1, "PT5M": 5, "PT15M": 15, "PT30M": 30, "PT1H": 60, "PT6H": 360, "PT12H": 720, "P1D": 1440}
OPERATORS = ("Equals", "GreaterThan", "GreaterThanOrEqual", "LessThan", "LessThanOrEqual")
DYNAMIC_OPERATORS = ("GreaterThan", "LessThan", "GreaterOrLessThan")
AGGREGATIONS = ("Average", "Count", "Minimum", "Maximum", "Total")
CRITERIA_TYPES = ("Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
                  "Microsoft.Azure.Monitor.MultipleResourceMultipleMetricCriteria",
                  "Microsoft.Azure.Monitor.WebtestLocationAvailabilityCriteria")
ALERT_CATEGORIES = ("Administrative", "ServiceHealth", "ResourceHealth", "Alert", "Autoscale", "Recommendation",
                    "Security", "Policy")
RECEIVER_LISTS = ("emailReceivers", "smsReceivers", "webhookReceivers", "itsmReceivers", "azureAppPushReceivers",
                  "automationRunbookReceivers", "voiceReceivers", "logicAppReceivers", "azureFunctionReceivers",
                  "armRoleReceivers", "eventHubReceivers")
_BAD_NAME = re.compile(r"[<>*%&:\\?+/#]")


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _ok(body=None, status=200, headers=None, lro=False, rid="", verb=""):
    return {"status": status, "headers": headers or {}, "body": body, "lro": lro, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "lro": False, "rid": "", "verb": ""}


def _bad(msg):
    return _E(400, "BadRequest", msg)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _rid(sub, rg, low, name):
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{NAMESPACE}/{TYPES[low][0]}/{name}"


def _not_found(low, name, rg):
    return _E(404, "ResourceNotFound",
              f"The Resource '{NAMESPACE.lower()}/{low}/{name}' under resource group '{rg}' was not found. "
              "For more details please go to https://aka.ms/ARMResourceNotFoundFix")


def _of_type(state, low):
    want = TYPE_STRINGS[low].lower()
    return [r for r in state.values() if str(r.get("_type", "")).lower() == want]


# ═══════════════════════════ coercion helpers ═══════════════════════════════════
def _bool(v, what, default=None):
    if v is None or v == "":
        if default is None:
            raise _bad(f"The property '{what}' is required.")
        return default
    if isinstance(v, bool):
        return v
    if str(v).lower() in ("true", "false"):
        return str(v).lower() == "true"
    raise _bad(f"The property '{what}' must be a boolean.")


def _num(v, what):
    if isinstance(v, bool):
        raise _bad(f"The property '{what}' must be a number.")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise _bad(f"The property '{what}' must be a number.")
    return int(f) if f == int(f) and not isinstance(v, float) else f


def _int(v, what, lo, hi):
    try:
        i = int(str(v))
    except (TypeError, ValueError):
        raise _bad(f"The property '{what}' must be an integer between {lo} and {hi}.")
    if not lo <= i <= hi:
        raise _bad(f"The property '{what}' must be an integer between {lo} and {hi}.")
    return i


def _enum(v, what, allowed):
    for a in allowed:
        if str(v).lower() == a.lower():
            return a
    raise _bad(f"The property '{what}' has invalid value '{v}'. Allowed values: {', '.join(allowed)}.")


def _str(v, what):
    if not isinstance(v, str) or not v.strip():
        raise _bad(f"The property '{what}' is required.")
    return v


def _scopes(props, what="scopes"):
    sc = props.get(what)
    if not isinstance(sc, list) or not sc:
        raise _bad(f"The property '{what}' must contain at least one resource id.")
    out = []
    for s in sc:
        if not isinstance(s, str) or not s.lower().startswith("/subscriptions/"):
            raise _bad(f"The scope '{s}' is not a valid Azure resource id (expected /subscriptions/...).")
        out.append(s)
    return out


def _ag_id(s):
    if not isinstance(s, str) or not re.fullmatch(
            r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/microsoft\.insights/actionGroups/[^/]+", s, re.I):
        raise _bad(f"The action group id '{s}' is not a valid Microsoft.Insights/actionGroups resource id.")
    return s


def _name_problem(name):
    if not name or len(name) > 260 or _BAD_NAME.search(name) or name != name.strip() or name.endswith("."):
        return (f"The resource name '{name}' is invalid. Names must be 1-260 characters and cannot contain "
                "any of < > * % & : \\ ? + / # or end with a period or space.")
    return None


# ═══════════════════════════ action groups ═══════════════════════════════════════
def _receivers(props):
    names = set()
    out = {}
    for lst in RECEIVER_LISTS:
        items = props.get(lst)
        if items is None:
            continue
        if not isinstance(items, list):
            raise _bad(f"The property '{lst}' must be an array.")
        norm = []
        for r in items:
            if not isinstance(r, dict):
                raise _bad(f"The property '{lst}' must contain objects.")
            r = dict(r)
            nm = _str(r.get("name"), f"{lst}.name")
            if nm.lower() in names:
                raise _bad(f"Receiver names must be unique across the action group; '{nm}' is used more than once.")
            names.add(nm.lower())
            if lst == "emailReceivers":
                addr = _str(r.get("emailAddress"), "emailReceivers.emailAddress")
                if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", addr):
                    raise _bad(f"The email address '{addr}' is invalid.")
                r.setdefault("useCommonAlertSchema", False)
                r["status"] = "Enabled"
            elif lst in ("smsReceivers", "voiceReceivers"):
                _str(r.get("countryCode"), f"{lst}.countryCode")
                if not re.fullmatch(r"\d{4,15}", str(r.get("phoneNumber") or "")):
                    raise _bad(f"The property '{lst}.phoneNumber' must be 4-15 digits.")
                r["status"] = "Enabled"
            elif lst == "webhookReceivers":
                if not re.match(r"https?://[^\s/]+", str(r.get("serviceUri") or "")):
                    raise _bad("The property 'webhookReceivers.serviceUri' must be an http(s) URL.")
                r.setdefault("useCommonAlertSchema", False)
                r.setdefault("useAadAuth", False)
            elif lst == "azureAppPushReceivers":
                _str(r.get("emailAddress"), "azureAppPushReceivers.emailAddress")
            elif lst == "armRoleReceivers":
                _str(r.get("roleId"), "armRoleReceivers.roleId")
                r.setdefault("useCommonAlertSchema", False)
            norm.append(r)
        out[lst] = norm
    return out


def _action_group_props(props, old=None):
    short = props.get("groupShortName", (old or {}).get("groupShortName"))
    short = _str(short, "groupShortName")
    if len(short) > 12:
        raise _bad("The property 'groupShortName' must be at most 12 characters.")
    enabled = _bool(props.get("enabled", (old or {}).get("enabled")), "enabled", default=True)
    out = {"groupShortName": short, "enabled": enabled}
    merged = dict(old or {})
    merged.update({k: v for k, v in props.items() if k in RECEIVER_LISTS})
    rec = _receivers(merged)
    for lst in RECEIVER_LISTS:
        out[lst] = rec.get(lst, [])
    return out


# ═══════════════════════════ metric alerts ═══════════════════════════════════════
def _criterion(c, multi):
    if not isinstance(c, dict):
        raise _bad("criteria.allOf must contain objects.")
    c = dict(c)
    ctype = c.get("criterionType") or "StaticThresholdCriterion"
    c["criterionType"] = _enum(ctype, "criteria.allOf.criterionType", ("StaticThresholdCriterion", "DynamicThresholdCriterion"))
    _str(c.get("name"), "criteria.allOf.name")
    _str(c.get("metricName"), "criteria.allOf.metricName")
    c["timeAggregation"] = _enum(c.get("timeAggregation"), "criteria.allOf.timeAggregation", AGGREGATIONS)
    if c["criterionType"] == "StaticThresholdCriterion":
        c["operator"] = _enum(c.get("operator"), "criteria.allOf.operator", OPERATORS)
        c["threshold"] = _num(c.get("threshold"), "criteria.allOf.threshold")
    else:
        c["operator"] = _enum(c.get("operator"), "criteria.allOf.operator", DYNAMIC_OPERATORS)
        c["alertSensitivity"] = _enum(c.get("alertSensitivity"), "criteria.allOf.alertSensitivity", ("Low", "Medium", "High"))
        fp = c.get("failingPeriods")
        if not isinstance(fp, dict):
            raise _bad("Dynamic threshold criteria require 'failingPeriods'.")
        n, m = _int(fp.get("numberOfEvaluationPeriods"), "failingPeriods.numberOfEvaluationPeriods", 1, 12), \
            _int(fp.get("minFailingPeriodsToAlert"), "failingPeriods.minFailingPeriodsToAlert", 1, 12)
        if m > n:
            raise _bad("minFailingPeriodsToAlert cannot exceed numberOfEvaluationPeriods.")
        c["failingPeriods"] = {"numberOfEvaluationPeriods": n, "minFailingPeriodsToAlert": m}
    if "dimensions" in c and not isinstance(c["dimensions"], list):
        raise _bad("criteria.allOf.dimensions must be an array.")
    return c


def _criteria(cr):
    if not isinstance(cr, dict):
        raise _bad("The property 'criteria' is required.")
    cr = dict(cr)
    cr["odata.type"] = _enum(cr.get("odata.type") or CRITERIA_TYPES[0], "criteria.odata.type", CRITERIA_TYPES)
    if cr["odata.type"].endswith("WebtestLocationAvailabilityCriteria"):
        _str(cr.get("webTestId"), "criteria.webTestId")
        _str(cr.get("componentId"), "criteria.componentId")
        if not isinstance(cr.get("failedLocationCount"), int):
            raise _bad("The property 'criteria.failedLocationCount' is required.")
        return cr
    allof = cr.get("allOf")
    if not isinstance(allof, list) or not allof:
        raise _bad("The property 'criteria.allOf' must contain at least one criterion.")
    multi = cr["odata.type"].endswith("MultipleResourceMultipleMetricCriteria")
    cr["allOf"] = [_criterion(c, multi) for c in allof]
    if len({c["name"].lower() for c in cr["allOf"]}) != len(cr["allOf"]):
        raise _bad("Criterion names must be unique within an alert rule.")
    return cr


def _actions(actions):
    if actions is None:
        return []
    if not isinstance(actions, list):
        raise _bad("The property 'actions' must be an array.")
    return [{"actionGroupId": _ag_id((a or {}).get("actionGroupId")), "webHookProperties": dict((a or {}).get("webHookProperties") or {})}
            for a in actions]


def _metric_alert_props(props, old=None):
    p = dict(old or {})
    p.update(props)
    out = {"description": p.get("description") or "", "severity": _int(p.get("severity"), "severity", 0, 4),
           "enabled": _bool(p.get("enabled"), "enabled"), "scopes": _scopes(p)}
    freq = _enum(p.get("evaluationFrequency"), "evaluationFrequency", EVAL_FREQUENCIES)
    win = _enum(p.get("windowSize"), "windowSize", WINDOW_SIZES)
    if _DUR_MIN[win] < _DUR_MIN[freq]:
        raise _bad("The property 'windowSize' cannot be shorter than 'evaluationFrequency'.")
    out["evaluationFrequency"], out["windowSize"] = freq, win
    out["criteria"] = _criteria(p.get("criteria"))
    for f in ("targetResourceType", "targetResourceRegion"):
        if p.get(f):
            out[f] = str(p[f])
    out["autoMitigate"] = _bool(p.get("autoMitigate"), "autoMitigate", default=True)
    out["actions"] = _actions(p.get("actions"))
    out["isMigrated"] = False
    out["lastUpdatedTime"] = _now()
    return out


# ═══════════════════════════ activity log alerts ═════════════════════════════════
def _activity_props(props, old=None):
    p = dict(old or {})
    p.update(props)
    out = {"description": p.get("description") or "", "enabled": _bool(p.get("enabled"), "enabled", default=True),
           "scopes": _scopes(p)}
    cond = p.get("condition")
    allof = cond.get("allOf") if isinstance(cond, dict) else None
    if not isinstance(allof, list) or not allof:
        raise _bad("The property 'condition.allOf' must contain at least one condition.")
    norm = []
    for c in allof:
        c = dict(c or {})
        _str(c.get("field"), "condition.allOf.field")
        if not c.get("equals") and not c.get("containsAny"):
            raise _bad(f"The condition on field '{c['field']}' needs 'equals' or 'containsAny'.")
        norm.append(c)
    cats = [c for c in norm if c["field"].lower() == "category"]
    if not cats:
        raise _bad("An activity log alert rule must have a condition on the 'category' field.")
    for c in cats:
        if c.get("equals"):
            c["equals"] = _enum(c["equals"], "condition category", ALERT_CATEGORIES)
    out["condition"] = {"allOf": norm}
    ag = (p.get("actions") or {}).get("actionGroups") if isinstance(p.get("actions"), dict) else None
    out["actions"] = {"actionGroups": [{"actionGroupId": _ag_id((a or {}).get("actionGroupId")),
                                        "webhookProperties": dict((a or {}).get("webhookProperties") or {})}
                                       for a in (ag or [])]}
    return out


# ═══════════════════════════ autoscale settings ══════════════════════════════════
def _profile(pr):
    if not isinstance(pr, dict):
        raise _bad("profiles must contain objects.")
    pr = dict(pr)
    _str(pr.get("name"), "profiles.name")
    cap = pr.get("capacity")
    if not isinstance(cap, dict):
        raise _bad("Each autoscale profile requires 'capacity' (minimum, maximum, default).")
    mn, mx, df = (_int(cap.get(k), f"capacity.{k}", 0, 1000) for k in ("minimum", "maximum", "default"))
    if not mn <= df <= mx:
        raise _bad("Autoscale capacity must satisfy minimum <= default <= maximum.")
    pr["capacity"] = {"minimum": str(mn), "maximum": str(mx), "default": str(df)}
    rules = pr.get("rules") or []
    if not isinstance(rules, list):
        raise _bad("profiles.rules must be an array.")
    out = []
    for r in rules:
        r = dict(r or {})
        mt, sa = r.get("metricTrigger"), r.get("scaleAction")
        if not isinstance(mt, dict) or not isinstance(sa, dict):
            raise _bad("Each autoscale rule requires 'metricTrigger' and 'scaleAction'.")
        mt = dict(mt)
        _str(mt.get("metricName"), "metricTrigger.metricName")
        _str(mt.get("metricResourceUri"), "metricTrigger.metricResourceUri")
        mt["statistic"] = _enum(mt.get("statistic"), "metricTrigger.statistic", ("Average", "Min", "Max", "Sum", "Count"))
        mt["timeAggregation"] = _enum(mt.get("timeAggregation"), "metricTrigger.timeAggregation",
                                      ("Average", "Minimum", "Maximum", "Total", "Count", "Last"))
        mt["operator"] = _enum(mt.get("operator"), "metricTrigger.operator",
                               ("Equals", "NotEquals", "GreaterThan", "GreaterThanOrEqual", "LessThan", "LessThanOrEqual"))
        mt["threshold"] = _num(mt.get("threshold"), "metricTrigger.threshold")
        _str(mt.get("timeGrain"), "metricTrigger.timeGrain")
        _str(mt.get("timeWindow"), "metricTrigger.timeWindow")
        sa = dict(sa)
        sa["direction"] = _enum(sa.get("direction"), "scaleAction.direction", ("None", "Increase", "Decrease"))
        sa["type"] = _enum(sa.get("type"), "scaleAction.type",
                           ("ChangeCount", "PercentChangeCount", "ExactCount", "ServiceAllowedNextValue"))
        _str(sa.get("cooldown"), "scaleAction.cooldown")
        if sa.get("value") is not None:
            sa["value"] = str(_int(sa["value"], "scaleAction.value", 0, 1000000))
        r["metricTrigger"], r["scaleAction"] = mt, sa
        out.append(r)
    pr["rules"] = out
    return pr


def _autoscale_props(props, old=None, name=""):
    p = dict(old or {})
    p.update(props)
    profiles = p.get("profiles")
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 20:
        raise _bad("The property 'profiles' must contain between 1 and 20 profiles.")
    out = {"profiles": [_profile(x) for x in profiles], "enabled": _bool(p.get("enabled"), "enabled", default=True),
           "name": p.get("name") or name, "notifications": list(p.get("notifications") or [])}
    if p.get("targetResourceUri"):
        out["targetResourceUri"] = str(p["targetResourceUri"])
    if p.get("targetResourceLocation"):
        out["targetResourceLocation"] = str(p["targetResourceLocation"])
    out["predictiveAutoscalePolicy"] = p.get("predictiveAutoscalePolicy") or {"scaleMode": "Disabled"}
    return out


_BUILDERS = {"actiongroups": lambda pr, old, nm: _action_group_props(pr, old),
             "metricalerts": lambda pr, old, nm: _metric_alert_props(pr, old),
             "activitylogalerts": lambda pr, old, nm: _activity_props(pr, old),
             "autoscalesettings": _autoscale_props}


# ═══════════════════════════ CRUD ════════════════════════════════════════════════
def _put(state, sub, rg, low, name, payload, method):
    prob = _name_problem(name)
    if prob:
        raise _bad(prob)
    rid = _rid(sub, rg, low, name)
    rec = state.get(rid.lower())
    props_in = payload.get("properties")
    if method == "PATCH":
        if rec is None:
            raise _not_found(low, name, rg)
        if props_in is not None and not isinstance(props_in, dict):
            raise _bad("The property 'properties' must be an object.")
        props = _BUILDERS[low](props_in or {}, rec["properties"], name)
    else:
        if not isinstance(props_in, dict):
            raise _bad("The request body must contain 'properties'.")
        props = _BUILDERS[low](props_in, None, name)
    if rec is None:
        loc = payload.get("location") or DEFAULT_LOCATION
        if low in ("actiongroups", "activitylogalerts", "metricalerts") and str(loc).lower() == "global":
            loc = "Global" if low != "metricalerts" else "global"
        rec = {"id": rid, "name": name, "type": TYPE_STRINGS[low], "location": loc,
               "tags": dict(payload.get("tags") or {}), "properties": props,
               "_type": TYPE_STRINGS[low], "_sub": sub, "_rg": rg}
        state[rid.lower()] = rec
        return rec, True
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = dict(payload["tags"])
    if method == "PUT" and payload.get("location"):
        rec["location"] = payload["location"]
    rec["properties"] = props
    return rec, False


def _list(state, low, sub, rg):
    items = [r for r in _of_type(state, low) if r.get("_sub") == sub and (rg is None or (r.get("_rg") or "").lower() == rg.lower())]
    items.sort(key=lambda r: (r["name"].lower(), r["id"].lower()))
    return _ok({"value": [_view(r) for r in items]})


# ═══════════════════════════ action-group operations ═════════════════════════════
def _test_notification(state, sub, rid_hint, receivers):
    nid = uuid.uuid4().hex
    now = _now()
    details = []
    for lst, items in receivers.items():
        for r in items or []:
            details.append({"name": r.get("name"), "status": "Succeeded", "mechanismType": lst[: -len("Receivers")],
                            "subState": "Default", "sendTime": now})
    rec = {"id": f"/subscriptions/{sub}/providers/{NAMESPACE}/notificationStatus/{nid}", "name": nid,
           "type": f"{NAMESPACE}/notificationStatus", "_type": f"{NAMESPACE}/notificationStatus", "_sub": sub, "_rg": None,
           "properties": {}, "state": "Completed", "completedTime": now, "createdTime": now,
           "context": {"notificationSource": "Microsoft.Insights/TestNotification", "contextType": "Microsoft.Insights/ActionGroups"},
           "actionDetailsList": details}
    state[rec["id"].lower()] = rec
    return rec


def _notif_view(rec):
    return {"context": rec["context"], "state": rec["state"], "completedTime": rec["completedTime"],
            "createdTime": rec["createdTime"], "actionDetails": rec["actionDetailsList"]}


def _create_notifications(state, sub, rg, payload, base, group=None):
    if not isinstance(payload, dict):
        raise _bad("The request body is required.")
    _enum(payload.get("alertType") or "servicehealth", "alertType", ("servicehealth", "metricstaticthreshold", "logalertv2",
                                                                     "budget", "activitylog", "resourcehealth", "smartdetector", "nrt"))
    if group is not None:
        receivers = {k: group["properties"].get(k) for k in RECEIVER_LISTS}
    else:
        receivers = _receivers(payload)
        if not any(receivers.values()):
            raise _bad("At least one receiver is required to send a test notification.")
    rec = _test_notification(state, sub, "", receivers)
    url = f"{base}/subscriptions/{sub}/providers/{NAMESPACE}/notificationStatus/{rec['name']}?api-version=2023-01-01"
    return _ok(None, 202, headers={"Location": url, "Retry-After": "0"}, verb="post")


def _action_group_ops(state, rec, rest, method, payload, base):
    op = rest[0].lower()
    if op == "subscribe" and method == "POST":
        name = _str((payload or {}).get("receiverName"), "receiverName")
        for lst in ("emailReceivers", "smsReceivers", "voiceReceivers"):
            for r in rec["properties"].get(lst, []):
                if r.get("name", "").lower() == name.lower():
                    if r.get("status") == "Enabled":
                        raise _E(409, "Conflict", f"The receiver '{name}' is already enabled.")
                    r["status"] = "Enabled"
                    return _ok(None, 200)
        raise _E(404, "NotFound", f"Receiver '{name}' was not found in action group '{rec['name']}'.")
    if op == "createnotifications" and method == "POST":
        return _create_notifications(state, rec["_sub"], rec["_rg"], payload, base, group=rec)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ═══════════════════════════ dispatch ════════════════════════════════════════════
def dispatch(state, method, sub, rg, chain, names, payload=None, query=None, base=""):
    """Handle one ``Microsoft.Insights`` ARM request (``chain`` = tokens after the namespace)."""
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload, query or {}, base)
    except _E as e:
        return _err(e.status, e.code, e.message)


def handles(chain):
    return bool(chain) and (chain[0].lower() in TYPES or chain[0].lower() in ("createnotifications", "notificationstatus"))


def _dispatch(state, method, sub, rg, chain, payload, query, base=""):
    low = chain[0].lower()
    if low == "createnotifications":
        if method != "POST" or len(chain) != 1:
            return _err(405, "MethodNotAllowed", "POST required.")
        return _create_notifications(state, sub, rg, payload.get("properties", payload) if "properties" in payload else payload, base)
    if low == "notificationstatus":
        if method != "GET" or len(chain) != 2:
            return _err(405, "MethodNotAllowed", "GET /notificationStatus/{id} required.")
        rec = state.get(f"/subscriptions/{sub}/providers/{NAMESPACE}/notificationStatus/{chain[1]}".lower())
        if rec is None:
            raise _E(404, "NotFound", f"Notification '{chain[1]}' was not found.")
        return _ok(_notif_view(rec))
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list(state, low, sub, rg)
    name = chain[1]
    if rg is None:
        return _err(400, "InvalidResourceId", f"{TYPES[low][0]} must be addressed within a resource group.")
    rid = _rid(sub, rg, low, name)
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:
        if rec is None:
            raise _not_found(low, name, rg)
        if low == "actiongroups":
            return _action_group_ops(state, rec, rest, method, payload, base)
        if low == "metricalerts" and rest[0].lower() == "status" and method == "GET":
            return _ok({"value": []})
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{low}/{'/'.join(rest)}' is not supported.")
    if method == "GET":
        if rec is None:
            raise _not_found(low, name, rg)
        return _ok(_view(rec))
    if method in ("PUT", "PATCH"):
        rec, created = _put(state, sub, rg, low, name, payload, method)
        return _ok(_view(rec), 201 if created else 200, rid=rid, verb=method.lower())
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        state.pop(rid.lower(), None)
        return _ok(None, 200, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def resource_types():
    return [(t, v) for t, v in TYPES.values()]
