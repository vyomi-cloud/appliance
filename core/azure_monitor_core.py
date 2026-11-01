"""Azure Monitor core (``Microsoft.Insights`` — action groups, metric alerts, activity log alerts, autoscale,
workbooks, data collection rules).

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
    Microsoft.Insights/eventtypes            2015-04-01  GET .../eventtypes/management/values (Activity Log feed,
                                                         subscription-scoped, ``$filter=resourceUri eq '{id}'``)
    Microsoft.Insights/workbooks             2022-04-01  CreateOrUpdate / Update / Delete / Get / ListBy*
    Microsoft.Insights/dataCollectionRules   2023-03-11  CreateOrUpdate / Update / Delete / Get / ListBy*
    Microsoft.Insights/dataCollectionEndpoints 2023-03-11  CreateOrUpdate / Update / Delete / Get / ListBy*
    Microsoft.Insights/privateLinkScopes  2021-07-01-preview  CreateOrUpdate / Update / Delete / Get / ListBy*
    Microsoft.Insights/diagnosticSettings 2021-05-01-preview  a real ARM EXTENSION resource scoped to any
                                                         other resource's own id (chain re-enters "providers",
                                                         same shape as Microsoft.Authorization/locks —
                                                         core/azure_locks_core.py); see find_diagnostic_marker /
                                                         list_diagnostic_settings / get_diagnostic_setting /
                                                         upsert_diagnostic_setting / remove_diagnostic_setting,
                                                         wired by core/azure_arm_core.AzureArm._diagnostic_settings.

Resources live in the shared ARM state map (offline ``azure_services._state``; Nano ``az_arm``), keyed by the
lower-cased resource id, so they are space-scoped and persisted by the same seams as the rest of ARM. Activity
Log entries are written directly into that same map by the resource providers that generate them (e.g.
core/azure_webapp_core.py's ``_record_event``) as ``Microsoft.Insights/eventtypes`` records; this module only
reads them back for the feed.
Not modelled: metric definitions / metrics and scheduled query rules (resource-scoped extension APIs),
Azure Monitor pipelines, Azure Managed Grafana (``Microsoft.Dashboard``) and Azure Monitor workspaces for
managed Prometheus (``Microsoft.Monitor``) — different resource providers this module does not own — and
conditional headers (If-Match / If-None-Match). Diagnostic settings never actually deliver logs/metrics to
their destination (no agent/telemetry pipeline); private link scopes carry no real private networking.

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}`` (``body`` is a JSON-able object or ``None``).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

try:
    from core import azure_blob_core as blob_engine
except ImportError:  # pragma: no cover - Pyodide flat layout
    import azure_blob_core as blob_engine  # type: ignore

NAMESPACE = "Microsoft.Insights"
API_VERSION = "2018-03-01"                    # primary catalog type (metricAlerts)
DEFAULT_LOCATION = "global"

# lower-case collection name → (ARM type, canonical segment, api-version)
TYPES = {
    "actiongroups": ("actionGroups", "2023-01-01"),
    "metricalerts": ("metricAlerts", "2018-03-01"),
    "activitylogalerts": ("activityLogAlerts", "2020-10-01"),
    "autoscalesettings": ("autoscaleSettings", "2022-10-01"),
    "workbooks": ("workbooks", "2022-04-01"),
    "datacollectionrules": ("dataCollectionRules", "2023-03-11"),
    "datacollectionendpoints": ("dataCollectionEndpoints", "2023-03-11"),
    "privatelinkscopes": ("privateLinkScopes", "2021-07-01-preview"),
    "healthmodels": ("healthModels", "2023-04-01-preview"),
    "pipelinegroups": ("pipelineGroups", "2023-10-01-preview"),
}
# ARM echoes these type strings back (autoscale is lower-cased in the real service)
TYPE_STRINGS = {"actiongroups": "Microsoft.Insights/actionGroups", "metricalerts": "Microsoft.Insights/metricAlerts",
                "activitylogalerts": "Microsoft.Insights/activityLogAlerts",
                "autoscalesettings": "Microsoft.Insights/autoscaleSettings",
                "workbooks": "Microsoft.Insights/workbooks",
                "datacollectionrules": "Microsoft.Insights/dataCollectionRules",
                "datacollectionendpoints": "Microsoft.Insights/dataCollectionEndpoints",
                "privatelinkscopes": "Microsoft.Insights/privateLinkScopes",
                "healthmodels": "Microsoft.Insights/healthModels",
                "pipelinegroups": "Microsoft.Insights/pipelineGroups"}

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


# ═══════════════════════════ workbooks ═══════════════════════════════════════════
def _workbook_props(props, old=None):
    p = dict(old or {})
    p.update(props)
    out = {"displayName": _str(p.get("displayName"), "displayName"), "category": _str(p.get("category"), "category"),
           "serializedData": _str(p.get("serializedData"), "serializedData"), "version": p.get("version") or "Notebook/1.0",
           "sourceId": p.get("sourceId") or "Azure Monitor"}
    return out


# ═══════════════════════════ data collection rules ═══════════════════════════════
def _dcr_destinations(dest):
    if not isinstance(dest, dict):
        raise _bad("The property 'destinations' is required.")
    la = dest.get("logAnalytics")
    if not isinstance(la, list) or not la:
        raise _bad("The property 'destinations.logAnalytics' must contain at least one workspace destination.")
    for d in la:
        if not isinstance(d, dict) or not isinstance(d.get("workspaceResourceId"), str):
            raise _bad("Each destinations.logAnalytics entry needs a 'workspaceResourceId'.")
        _str(d.get("name"), "destinations.logAnalytics.name")
    return dest


def _dcr_dataflows(flows):
    if not isinstance(flows, list) or not flows:
        raise _bad("The property 'dataFlows' must contain at least one flow.")
    out = []
    for f in flows:
        f = dict(f or {})
        streams = f.get("streams")
        if not isinstance(streams, list) or not streams:
            raise _bad("Each dataFlows entry needs a non-empty 'streams' array.")
        dests = f.get("destinations")
        if not isinstance(dests, list) or not dests:
            raise _bad("Each dataFlows entry needs a non-empty 'destinations' array.")
        out.append(f)
    return out


def _dcr_props(props, old=None):
    p = dict(old or {})
    p.update(props)
    out = {"description": p.get("description") or "", "dataSources": dict(p.get("dataSources") or {}),
           "destinations": _dcr_destinations(p.get("destinations")), "dataFlows": _dcr_dataflows(p.get("dataFlows")),
           "provisioningState": "Succeeded"}
    return out


# ═══════════════════════════ data collection endpoints ═══════════════════════════
def _dce_props(props, old=None, name=""):
    p = dict(old or {})
    p.update(props)
    out = {"description": str(p.get("description") or ""), "provisioningState": "Succeeded"}
    if old and old.get("immutableId"):
        for f in ("immutableId", "configurationAccess", "logsIngestion", "metricsIngestion"):
            out[f] = old[f]
    else:
        token = uuid.uuid4().hex[:12]
        out["immutableId"] = f"dce-{token}"
        out["configurationAccess"] = {"endpoint": f"https://{name}-{token}.control.monitor.azure.com"}
        out["logsIngestion"] = {"endpoint": f"https://{name}-{token}.ingest.monitor.azure.com"}
        out["metricsIngestion"] = {"endpoint": f"https://{name}-{token}.metrics.ingest.monitor.azure.com"}
    nacls = p.get("networkAcls")
    pna = nacls.get("publicNetworkAccess") if isinstance(nacls, dict) else None
    out["networkAcls"] = {"publicNetworkAccess": _enum(pna, "networkAcls.publicNetworkAccess", ("Enabled", "Disabled")) if pna else "Enabled"}
    return out


# ═══════════════════════════ private link scopes ═════════════════════════════════
def _plscope_props(props, old=None):
    p = dict(old or {})
    p.update(props)
    ams = p.get("accessModeSettings") if isinstance(p.get("accessModeSettings"), dict) else {}
    def _mode(v, what):
        return _enum(v, what, ("Open", "PrivateOnly")) if v else "Open"
    return {"accessModeSettings": {"queryAccessMode": _mode(ams.get("queryAccessMode"), "accessModeSettings.queryAccessMode"),
                                    "ingestionAccessMode": _mode(ams.get("ingestionAccessMode"), "accessModeSettings.ingestionAccessMode")},
            "provisioningState": "Succeeded"}


# ═══════════════════════════ health models (preview) ═════════════════════════════
# Microsoft.Insights/healthModels: a named collection of member resource ids. Modelled as a
# plain generic-catalog resource (same CRUD shape as workbooks) — the rollup health per member
# is NOT stored here (it is computed at read time by the console from the real Activity log's
# status field, see core/azure_arm_core.py's deployment-failure status="Failed" rows), so a
# model's health can never go stale relative to what actually happened.
def _health_model_props(props, old=None):
    p = dict(old or {})
    p.update(props)
    out = {"displayName": _str(p.get("displayName") or p.get("name") or "", "displayName"),
           "resources": _scopes(p, "resources"), "provisioningState": "Succeeded"}
    return out


# ═══════════════════════════ Azure Monitor pipelines (preview) ════════════════════
# Microsoft.Insights/pipelineGroups: an OpenTelemetry-collector-fleet configuration (platform +
# the collector endpoints it forwards to). Stored and validated exactly like the real resource;
# nothing is ever actually collected or forwarded (there is no on-premises collector fleet to
# run), the same "config real, data flow not" shape as dataCollectionRules/Endpoints above.
PIPELINE_PLATFORMS = ("Linux", "Windows")


def _pipeline_props(props, old=None):
    p = dict(old or {})
    p.update(props)
    platform = _enum(p.get("platform") or "Linux", "platform", PIPELINE_PLATFORMS)
    endpoints = p.get("collectorEndpoints")
    if endpoints is not None and not isinstance(endpoints, list):
        raise _bad("The property 'collectorEndpoints' must be an array.")
    return {"platform": platform, "collectorEndpoints": [str(e) for e in (endpoints or [])],
            "provisioningState": "Succeeded"}


_BUILDERS = {"actiongroups": lambda pr, old, nm: _action_group_props(pr, old),
             "metricalerts": lambda pr, old, nm: _metric_alert_props(pr, old),
             "activitylogalerts": lambda pr, old, nm: _activity_props(pr, old),
             "autoscalesettings": _autoscale_props,
             "workbooks": lambda pr, old, nm: _workbook_props(pr, old),
             "datacollectionrules": lambda pr, old, nm: _dcr_props(pr, old),
             "datacollectionendpoints": _dce_props,
             "privatelinkscopes": lambda pr, old, nm: _plscope_props(pr, old),
             "healthmodels": lambda pr, old, nm: _health_model_props(pr, old),
             "pipelinegroups": lambda pr, old, nm: _pipeline_props(pr, old)}


# ═══════════════════ private link scopes — scoped resources (child resource) ═════
# Microsoft.Insights/privateLinkScopes/{name}/scopedResources/{name} 2021-07-01-preview: links a
# Log Analytics workspace (or other Monitor resource) INTO the scope, the real "Azure Monitor
# Resources" tab of the scope's blade. Modelled as a real sub-resource (linkedResourceId must
# name a resource that actually exists in the shared ARM store) — unlike private endpoint
# connections, which need an actual private-networking stack Vyomi does not have.
_SCOPED_RESOURCE_TYPE = f"{NAMESPACE}/privateLinkScopes/scopedResources"


def _scoped_resource_ops(state, rec, rest, method, payload):
    base = f"{rec['id']}/scopedResources"
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        scope_key = rec["id"].lower()
        items = [r for r in state.values()
                 if r.get("_type") == _SCOPED_RESOURCE_TYPE.lower() and r.get("_plscope") == scope_key]
        items.sort(key=lambda r: r["name"].lower())
        return _ok({"value": [_view(r) for r in items]})
    if len(rest) > 1:
        return _err(404, "ResourceTypeNotSupported",
                    f"The resource type '{_SCOPED_RESOURCE_TYPE}/{'/'.join(rest[1:])}' is not supported.")
    name = rest[0]
    rid = f"{base}/{name}"
    key = rid.lower()
    if method == "GET":
        r = state.get(key)
        if r is None:
            raise _E(404, "NotFound", f"The scoped resource '{name}' was not found.")
        return _ok(_view(r))
    if method in ("PUT", "PATCH"):
        prob = _name_problem(name)
        if prob:
            raise _bad(prob)
        props = (payload or {}).get("properties")
        linked = str((props or {}).get("linkedResourceId") or "").strip()
        if not linked:
            raise _bad("The property 'properties.linkedResourceId' is required.")
        if linked.lower() not in state:
            raise _E(400, "ResourceNotFound", f"The linked resource '{linked}' was not found.")
        existed = key in state
        r = {"id": rid, "name": name, "type": _SCOPED_RESOURCE_TYPE,
             "properties": {"linkedResourceId": linked, "provisioningState": "Succeeded"},
             "_type": _SCOPED_RESOURCE_TYPE.lower(), "_plscope": rec["id"].lower()}
        state[key] = r
        return _ok(_view(r), 201 if not existed else 200, rid=rid, verb="put")
    if method == "DELETE":
        r = state.pop(key, None)
        return _ok(None, 200 if r is not None else 204)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ═══════════════════════════ diagnostic settings (ARM extension resource) ════════
# Microsoft.Insights/diagnosticSettings is scoped to ANY other resource's own id (the chain
# re-enters "providers"), the same shape azure_locks_core.find_marker handles for
# Microsoft.Authorization/locks — so it lives outside the TYPES/_BUILDERS CRUD above and is
# wired directly by core/azure_arm_core.AzureArm._diagnostic_settings (see find_diagnostic_marker).
DIAG_API_VERSION = "2021-05-01-preview"
_DIAG_TYPE = f"{NAMESPACE}/diagnosticSettings"


def find_diagnostic_marker(chain):
    """Index of the ['providers','Microsoft.Insights','diagnosticSettings'] marker in `chain`
    (AzureArm._arm's split of everything after the FIRST namespace token), or None."""
    for i in range(len(chain) - 2):
        if (chain[i].lower() == "providers" and chain[i + 1].lower() == "microsoft.insights"
                and chain[i + 2].lower() == "diagnosticsettings"):
            return i
    return None


def _diag_base(scope_rid):
    return f"{scope_rid}/providers/{NAMESPACE}/diagnosticSettings"


def _diag_category(c, what):
    if not isinstance(c, dict):
        raise _bad(f"Each '{what}' entry must be an object.")
    c = dict(c)
    if not c.get("category") and not c.get("categoryGroup"):
        raise _bad(f"Each '{what}' entry needs a 'category' or 'categoryGroup'.")
    c["enabled"] = _bool(c.get("enabled"), f"{what}.enabled", default=False)
    return c


def _diag_props(props, old=None):
    p = dict(old or {})
    p.update(props)
    out = {}
    for f in ("workspaceId", "storageAccountId", "eventHubAuthorizationRuleId", "marketplacePartnerId"):
        if p.get(f):
            out[f] = str(p[f])
    if not out:
        raise _bad("A diagnostic setting needs at least one destination: workspaceId, storageAccountId, "
                    "eventHubAuthorizationRuleId or marketplacePartnerId.")
    logs_in, metrics_in = p.get("logs"), p.get("metrics")
    if logs_in is not None and not isinstance(logs_in, list):
        raise _bad("The property 'logs' must be an array.")
    if metrics_in is not None and not isinstance(metrics_in, list):
        raise _bad("The property 'metrics' must be an array.")
    out["logs"] = [_diag_category(c, "logs") for c in (logs_in or [])]
    out["metrics"] = [_diag_category(c, "metrics") for c in (metrics_in or [])]
    if not any(c["enabled"] for c in out["logs"] + out["metrics"]):
        raise _bad("At least one log or metric category must be enabled.")
    if p.get("eventHubName"):
        out["eventHubName"] = str(p["eventHubName"])
    if p.get("logAnalyticsDestinationType"):
        out["logAnalyticsDestinationType"] = _enum(p["logAnalyticsDestinationType"], "logAnalyticsDestinationType",
                                                    ("Dedicated", "AzureDiagnostics"))
    return out


def list_diagnostic_settings(state, scope_rid):
    items = [r for r in state.values() if r.get("_diag_scope") == scope_rid.lower()]
    items.sort(key=lambda r: r["name"].lower())
    return _ok({"value": [_view(r) for r in items]})


def get_diagnostic_setting(state, scope_rid, name):
    rec = state.get(f"{_diag_base(scope_rid)}/{name}".lower())
    if rec is None:
        return _err(404, "ResourceNotFound", f"The diagnostic setting '{name}' was not found.")
    return _ok(_view(rec))


def upsert_diagnostic_setting(state, scope_rid, name, payload):
    prob = _name_problem(name)
    if prob:
        return _err(400, "BadRequest", prob)
    rid = f"{_diag_base(scope_rid)}/{name}"
    key = rid.lower()
    rec = state.get(key)
    existed = rec is not None
    try:
        props = _diag_props((payload or {}).get("properties") or {}, rec["properties"] if rec else None)
    except _E as e:
        return _err(e.status, e.code, e.message)
    # v4 WAVE 5b — a storageAccountId destination must name a real resource (real ARM
    # validates the destination exists too); workspaceId/eventHub destinations are left
    # unchecked since no Log Analytics/Event Hub core exists here to validate against.
    dest = props.get("storageAccountId")
    if dest and dest.lower() not in state:
        return _err(400, "BadRequest", f"The destination storage account '{dest}' does not exist.")
    rec = {"id": rid, "name": name, "type": _DIAG_TYPE, "properties": props,
           "_type": _DIAG_TYPE.lower(), "_diag_scope": scope_rid.lower()}
    state[key] = rec
    return _ok(_view(rec), 201 if not existed else 200, rid=rid, verb="put")


def remove_diagnostic_setting(state, scope_rid, name):
    rec = state.pop(f"{_diag_base(scope_rid)}/{name}".lower(), None)
    return _ok(None, 200 if rec is not None else 204)


# ═══════════ metrics data plane (Microsoft.Insights/metricDefinitions, metrics) ══════
# Resource-scoped extension APIs (chain re-enters "providers", same shape as diagnostic
# settings above) — the real Azure Monitor metrics pass-through. Vyomi has exactly ONE real
# metric: "ActivityOperations", a genuine count of this resource's own Activity log rows
# (core/azure_arm_core.py's _record_activity / azure_webapp_core._record_event writes),
# bucketed over the requested interval — never synthetic/random values. Metric definitions and
# the metrics endpoint are both 404 for a resource id that doesn't exist, matching real ARM.
# v4 WAVE 5b: a Microsoft.Storage/storageAccounts scope ALSO exposes six real storage metrics
# (UsedCapacity/BlobCount/ContainerCount/Transactions/Ingress/Egress) derived from
# core/azure_blob_core.py's own counters/state (`account_metrics`) when the platform wired a
# blob store — a single current-value data point each (no persisted metric history).
_METRIC_NAME = "ActivityOperations"
_METRIC_DISPLAY = "Activity operations"
_METRIC_UNIT = "Count"
_METRIC_AGGS = ("Total", "Count", "Average", "Minimum", "Maximum")
METRICS_API_VERSION = "2018-01-01"
STORAGE_METRIC_UNITS = {
    "UsedCapacity": "Bytes", "BlobCount": "Count", "ContainerCount": "Count",
    "Transactions": "Count", "Ingress": "Bytes", "Egress": "Bytes",
}
_STORAGE_METRIC_FIELD = {
    "UsedCapacity": "usedCapacity", "BlobCount": "blobCount", "ContainerCount": "containerCount",
    "Transactions": "transactions", "Ingress": "ingress", "Egress": "egress",
}
_STORAGE_TYPE = "microsoft.storage/storageaccounts"


def find_metrics_marker(chain):
    """Index of the ['providers','Microsoft.Insights','metricDefinitions'|'metrics'] marker."""
    for i in range(len(chain) - 2):
        if (chain[i].lower() == "providers" and chain[i + 1].lower() == "microsoft.insights"
                and chain[i + 2].lower() in ("metricdefinitions", "metrics")):
            return i
    return None


def _storage_account(state, scope_rid, blob_store):
    """The (lower-cased) storage account name when `scope_rid` is a storage account AND a blob
    store is wired (so its real metrics can be computed), else None."""
    if blob_store is None:
        return None
    rec = state.get(scope_rid.lower()) or {}
    if str(rec.get("_type", "")).lower() != _STORAGE_TYPE:
        return None
    return scope_rid.rstrip("/").rsplit("/", 1)[-1].lower()


def _metric_definition(scope_rid, name, display, unit):
    return {
        "id": f"{scope_rid}/providers/{NAMESPACE}/metricDefinitions/{name}",
        "resourceId": scope_rid, "name": {"value": name, "localizedValue": display},
        "namespace": "Platform", "unit": unit, "primaryAggregationType": "Total",
        "supportedAggregationTypes": list(_METRIC_AGGS),
        "metricAvailabilities": [{"timeGrain": g, "retention": "P30D"} for g in WINDOW_SIZES],
    }


def list_metric_definitions(state, scope_rid, blob_store=None):
    if scope_rid.lower() not in state:
        return _err(404, "ResourceNotFound", f"The Resource '{scope_rid}' was not found.")
    defs = [_metric_definition(scope_rid, _METRIC_NAME, _METRIC_DISPLAY, _METRIC_UNIT)]
    if _storage_account(state, scope_rid, blob_store) is not None:
        defs += [_metric_definition(scope_rid, n, n, u) for n, u in STORAGE_METRIC_UNITS.items()]
    return _ok({"value": defs})


def _parse_metric_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def get_metrics(state, scope_rid, query, blob_store=None):
    if scope_rid.lower() not in state:
        return _err(404, "ResourceNotFound", f"The Resource '{scope_rid}' was not found.")
    query = query or {}
    names = [n.strip() for n in str(query.get("metricnames") or _METRIC_NAME).split(",") if n.strip()]
    acct = _storage_account(state, scope_rid, blob_store)
    storage_by_lower = {k.lower(): k for k in STORAGE_METRIC_UNITS} if acct is not None else {}
    for n in names:
        if n.lower() != _METRIC_NAME.lower() and n.lower() not in storage_by_lower:
            return _err(400, "BadRequest",
                        f"Failed to find metric configuration for provider: microsoft.insights, "
                        f"metric name: {n}, metric namespace: Platform.")
    interval = query.get("interval") or "PT1H"
    if interval not in WINDOW_SIZES:
        return _err(400, "BadRequest",
                    f"The property 'interval' has invalid value '{interval}'. Allowed values: {', '.join(WINDOW_SIZES)}.")
    aggs = [a.strip() for a in str(query.get("aggregation") or "Total").split(",") if a.strip()]
    for a in aggs:
        if a not in _METRIC_AGGS:
            return _err(400, "BadRequest",
                        f"The property 'aggregation' has invalid value '{a}'. Allowed values: {', '.join(_METRIC_AGGS)}.")
    now = datetime.now(timezone.utc)
    timespan = query.get("timespan")
    if timespan:
        parts = str(timespan).split("/")
        start, end = (_parse_metric_iso(parts[0]), _parse_metric_iso(parts[1])) if len(parts) == 2 else (None, None)
        if start is None or end is None:
            return _err(400, "BadRequest", "The property 'timespan' must be '<start>/<end>' ISO 8601.")
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if end <= start:
            return _err(400, "BadRequest", "The property 'timespan' end must be after start.")
    else:
        start, end = now - timedelta(hours=24), now
    step_min = _DUR_MIN[interval]
    n_buckets = int((end - start).total_seconds() // (step_min * 60)) + 1
    if n_buckets < 1 or n_buckets > 500:
        return _err(400, "BadRequest", "The requested timespan/interval produces too many data points (max 500).")
    scope_key = scope_rid.lower()
    timestamps = []
    for r in state.values():
        if str(r.get("_type", "")).lower() != "microsoft.insights/eventtypes":
            continue
        if str(r.get("resourceId", "")).lower() != scope_key:
            continue
        ts = _parse_metric_iso(r.get("eventTimestamp"))
        if ts is not None:
            timestamps.append(ts)
    step = timedelta(minutes=step_min)
    buckets = [start + step * i for i in range(n_buckets)]
    counts = [0] * len(buckets)
    for ts in timestamps:
        if ts < start or ts > end:
            continue
        idx = min(int((ts - start).total_seconds() // (step_min * 60)), len(buckets) - 1)
        counts[idx] += 1
    data = []
    for t, c in zip(buckets, counts):
        point = {"timeStamp": t.strftime("%Y-%m-%dT%H:%M:%SZ")}
        if "Total" in aggs:
            point["total"] = c
        if "Count" in aggs:
            point["count"] = c
        if "Average" in aggs:
            point["average"] = c
        if "Minimum" in aggs:
            point["minimum"] = c
        if "Maximum" in aggs:
            point["maximum"] = c
        data.append(point)
    stats = blob_engine.account_metrics(blob_store, acct) if any(n.lower() in storage_by_lower for n in names) else None
    value = []
    for n in names:
        if n.lower() in storage_by_lower:
            value.append(_storage_metric_entry(scope_rid, storage_by_lower[n.lower()], stats, aggs, now))
            continue
        value.append({
            "id": f"{scope_rid}/providers/{NAMESPACE}/metrics/{_METRIC_NAME}",
            "type": "Microsoft.Insights/metrics",
            "name": {"value": _METRIC_NAME, "localizedValue": _METRIC_DISPLAY},
            "displayDescription": "Count of real Azure Resource Manager write/delete operations Vyomi "
                                   "recorded against this resource (from its own Activity log).",
            "unit": _METRIC_UNIT,
            "timeseries": [{"metadatavalues": [], "data": data}],
        })
    return _ok({"cost": 0, "timespan": f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                "interval": interval, "namespace": "Platform", "resourceregion": "", "value": value})


def _storage_metric_entry(scope_rid, name, stats, aggs, now):
    """One storage metric: a single current-value point (no persisted history), every requested
    aggregation carrying that same real value."""
    v = stats[_STORAGE_METRIC_FIELD[name]]
    point = {"timeStamp": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    for a in aggs:
        point[a.lower()] = v
    return {
        "id": f"{scope_rid}/providers/{NAMESPACE}/metrics/{name}", "type": "Microsoft.Insights/metrics",
        "name": {"value": name, "localizedValue": name}, "unit": STORAGE_METRIC_UNITS[name],
        "timeseries": [{"metadatavalues": [], "data": [point]}],
    }


def get_storage_metrics(blob_store, acct: str, query: dict, scope_rid: str = "") -> dict:
    """`blob_store`: core/azure_blob_core.AzureBlobStore. `acct`: the storage account's
    (lower-cased) name. Storage metrics only (no ARM state needed) — a single current-value data
    point per requested metric; unknown names are skipped. The ARM `metrics` endpoint goes
    through get_metrics, which also validates names and mixes in ActivityOperations."""
    query = query or {}
    names = [n for n in (query.get("metricnames") or "").split(",") if n] or list(STORAGE_METRIC_UNITS)
    stats = blob_engine.account_metrics(blob_store, acct)
    now = datetime.now(timezone.utc)
    value = [_storage_metric_entry(scope_rid, n, stats, ["Total"], now)
             for n in names if n in _STORAGE_METRIC_FIELD]
    return _ok({"cost": 0, "timespan": query.get("timespan", ""), "interval": "PT1H", "value": value})


# ═══ data collection rule associations (ARM extension resource, preview Observability agents) ═
# Microsoft.Insights/dataCollectionRuleAssociations: links a target resource (a VM today) to a
# REAL, already-existing Data Collection Rule — the real Azure mechanic behind "Observability
# agents (preview)" / VM insights data collection, modelled the same way scopedResources above
# links a workspace into a Private Link Scope: validated against the shared ARM store, not a
# stored-but-inert setting. No agent process actually runs or ships data.
_DCRA_TYPE = f"{NAMESPACE}/dataCollectionRuleAssociations"
DCRA_API_VERSION = "2023-03-11"


def find_dcra_marker(chain):
    for i in range(len(chain) - 2):
        if (chain[i].lower() == "providers" and chain[i + 1].lower() == "microsoft.insights"
                and chain[i + 2].lower() == "datacollectionruleassociations"):
            return i
    return None


def _dcra_base(scope_rid):
    return f"{scope_rid}/providers/{NAMESPACE}/dataCollectionRuleAssociations"


def list_dcr_associations(state, scope_rid):
    items = [r for r in state.values() if r.get("_dcra_scope") == scope_rid.lower()]
    items.sort(key=lambda r: r["name"].lower())
    return _ok({"value": [_view(r) for r in items]})


def get_dcr_association(state, scope_rid, name):
    rec = state.get(f"{_dcra_base(scope_rid)}/{name}".lower())
    if rec is None:
        return _err(404, "ResourceNotFound", f"The association '{name}' was not found.")
    return _ok(_view(rec))


def upsert_dcr_association(state, scope_rid, name, payload):
    prob = _name_problem(name)
    if prob:
        return _err(400, "BadRequest", prob)
    props_in = (payload or {}).get("properties") or {}
    dcr_id = str(props_in.get("dataCollectionRuleId") or "").strip()
    if not dcr_id:
        return _err(400, "BadRequest", "The property 'properties.dataCollectionRuleId' is required.")
    target = state.get(dcr_id.lower())
    if target is None or str(target.get("_type", "")).lower() != TYPE_STRINGS["datacollectionrules"].lower():
        return _err(400, "ResourceNotFound", f"The data collection rule '{dcr_id}' was not found.")
    rid = f"{_dcra_base(scope_rid)}/{name}"
    key = rid.lower()
    existed = key in state
    rec = {"id": rid, "name": name, "type": _DCRA_TYPE,
           "properties": {"dataCollectionRuleId": dcr_id, "provisioningState": "Succeeded"},
           "_type": _DCRA_TYPE.lower(), "_dcra_scope": scope_rid.lower()}
    state[key] = rec
    return _ok(_view(rec), 201 if not existed else 200, rid=rid, verb="put")


def remove_dcr_association(state, scope_rid, name):
    rec = state.pop(f"{_dcra_base(scope_rid)}/{name}".lower(), None)
    return _ok(None, 200 if rec is not None else 204)


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
    return bool(chain) and (chain[0].lower() in TYPES or chain[0].lower() in ("createnotifications", "notificationstatus", "eventtypes"))


def _activity_log_list(state, sub, query):
    flt = (query or {}).get("$filter") or ""
    m = re.search(r"resourceUri\s+eq\s+'([^']+)'", flt, re.I)
    want = m.group(1).rstrip("/").lower() if m else None
    # A resourceUri that IS a bare resource group id (no further segments after
    # ".../resourceGroups/{rg}") scopes to every resource inside that group too — the real
    # Activity Log behaviour a resource group's own blade relies on — not just an exact
    # resourceId match (which would only ever hit the group's own lifecycle events).
    want_rg = None
    if want:
        wsegs = want.split("/")
        if len(wsegs) >= 2 and wsegs[-2] == "resourcegroups":
            want_rg = wsegs[-1]
    rows = [r for r in state.values()
            if str(r.get("_type", "")).lower() == "microsoft.insights/eventtypes" and r.get("_sub") == sub
            and (want is None or str(r.get("resourceId", "")).lower() == want
                 or (want_rg is not None and str(r.get("resourceGroupName", "")).lower() == want_rg))]
    # Timespan picker: real ARM eventTimestamp ge/le OData predicates. ISO-8601 UTC strings
    # sort lexicographically, so plain string comparison is correct.
    ge = re.search(r"eventTimestamp\s+ge\s+'([^']*)'", flt, re.I)
    le = re.search(r"eventTimestamp\s+le\s+'([^']*)'", flt, re.I)
    if ge:
        rows = [r for r in rows if str(r.get("eventTimestamp") or "") >= ge.group(1)]
    if le:
        rows = [r for r in rows if str(r.get("eventTimestamp") or "") <= le.group(1)]
    rows.sort(key=lambda e: (e.get("eventTimestamp") or "", e.get("_seq", 0)), reverse=True)
    return _ok({"value": [_view(r) for r in rows]})


def _dispatch(state, method, sub, rg, chain, payload, query, base=""):
    low = chain[0].lower()
    if low == "eventtypes":
        if method != "GET" or [c.lower() for c in chain[1:3]] != ["management", "values"]:
            return _err(405, "MethodNotAllowed", "GET .../eventtypes/management/values required.")
        return _activity_log_list(state, sub, query)
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
        if low == "privatelinkscopes" and rest[0].lower() == "scopedresources":
            return _scoped_resource_ops(state, rec, rest[1:], method, payload)
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{low}/{'/'.join(rest)}' is not supported.")
    if method == "GET":
        if rec is None:
            raise _not_found(low, name, rg)
        return _ok(_view(rec))
    if method in ("PUT", "PATCH"):
        rec, created = _put(state, sub, rg, low, name, payload, method)
        # metricAlerts.CreateOrUpdate documents only 200 (the SDKs reject a 201); the other types return 201 on create
        return _ok(_view(rec), 201 if created and low != "metricalerts" else 200, rid=rid, verb=method.lower())
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        state.pop(rid.lower(), None)
        if low == "privatelinkscopes":
            scope_key = rid.lower()
            for k in [k for k, v in state.items() if v.get("_plscope") == scope_key]:
                state.pop(k, None)
        return _ok(None, 200, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def resource_types():
    return [(t, v) for t, v in TYPES.values()]
