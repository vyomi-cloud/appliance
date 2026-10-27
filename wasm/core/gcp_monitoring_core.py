"""GCP Cloud Monitoring core — substrate-independent. Speaks the native **Cloud Monitoring
REST API v3** (`monitoring.googleapis.com/v3`) so the native `google-cloud-monitoring` SDKs
and `gcloud monitoring ...` work unchanged against it (point them at the endpoint via
api_endpoint / api_endpoint_overrides).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide, so the
SAME file runs offline and in Nano.

Resources (Discovery doc `monitoring/v3`):
    projects/{p}/alertPolicies/{id}            create/get/list/patch/delete
    projects/{p}/notificationChannels/{id}     create/get/list/patch/delete (+ :getVerificationCode,
                                               :sendVerificationCode, :verify)
    projects/{p}/notificationChannelDescriptors  list/get
    projects/{p}/groups/{id}                   create/get/list/update/delete + /members
    projects/{p}/uptimeCheckConfigs/{id}       create/get/list/patch/delete;  uptimeCheckIps.list
    projects/{p}/metricDescriptors/{type}      create/get/list/delete (custom metrics only to write)
    projects/{p}/monitoredResourceDescriptors  list/get
    projects/{p}/timeSeries                    create (write points) / list (filter, interval,
                                               aggregation: per-series aligner + cross-series reducer)
Errors use the Google shape `{"error":{"code","message","status"}}` (INVALID_ARGUMENT,
NOT_FOUND, ALREADY_EXISTS, FAILED_PRECONDITION). Enums are strings on the wire by default;
the Java / .NET REST clients send `$alt=json;enum-encoding=int` and get integers back.
"""
from __future__ import annotations

import base64
import json
import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

CUSTOM_PREFIXES = ("custom.googleapis.com/", "external.googleapis.com/", "workload.googleapis.com/",
                   "prometheus.googleapis.com/")
MAX_SERIES_PER_WRITE = 200
MAX_POINTS_PER_SERIES = 10000
MAX_POLICIES = 500
MAX_CHANNELS = 4000


# ── store ──────────────────────────────────────────────────────────────────
class MonitoringStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.metric_descriptors: dict = {}      # metric type -> user-defined MetricDescriptor
        self.time_series: dict = {}             # series key -> {metric, resource, metricKind, valueType, points[]}
        self.alert_policies: dict = {}          # full name -> AlertPolicy
        self.notification_channels: dict = {}   # full name -> NotificationChannel
        self.groups: dict = {}                  # full name -> Group
        self.uptime_checks: dict = {}           # full name -> UptimeCheckConfig


_SHARED: MonitoringStore | None = None


def shared_store() -> MonitoringStore:
    """The appliance-wide store: the native wire and the console REST share it."""
    global _SHARED
    if _SHARED is None:
        _SHARED = MonitoringStore()
    return _SHARED


@dataclass
class MonResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class _E(Exception):
    def __init__(self, status, gcp_status, message):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _bad(msg):
    return _E(400, "INVALID_ARGUMENT", msg)


def _err(status, gcp_status, message):
    body = {"error": {"code": status, "message": message, "status": gcp_status}}
    return MonResponse(status=status, body=json.dumps(body).encode())


def _json(status, obj):
    return MonResponse(status=status, body=json.dumps(obj).encode())


def _copy(x):
    return json.loads(json.dumps(x))


def _now_dt():
    return datetime.now(timezone.utc)


def _ts(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _now():
    return _ts(_now_dt())


_TS_RE = re.compile(r"^(\d{4})-(\d\d)-(\d\d)[Tt ](\d\d):(\d\d):(\d\d)(?:\.(\d+))?([Zz]|[+-]\d\d:?\d\d)?$")


def parse_ts(s):
    m = _TS_RE.match(str(s or "").strip())
    if not m:
        raise _bad("Invalid timestamp '%s': expected RFC 3339 like 2026-01-02T03:04:05Z." % s)
    y, mo, d, h, mi, se, frac, tz = m.groups()
    dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(se), int((frac or "0")[:6].ljust(6, "0")),
                  tzinfo=timezone.utc)
    if tz and tz not in "Zz":
        sign = 1 if tz[0] == "+" else -1
        t = tz[1:].replace(":", "")
        dt -= sign * timedelta(hours=int(t[:2]), minutes=int(t[2:]))
    return dt


def parse_duration(s, what="duration"):
    """'300s' / '60.5s' -> seconds (float)."""
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return float(s)
    m = re.match(r"^(-?\d+(?:\.\d+)?)s$", str(s or ""))
    if not m:
        raise _bad("Invalid %s '%s': must be a duration in seconds like \"60s\"." % (what, s))
    return float(m.group(1))


def _rand_id():
    return str(random.randrange(10 ** 18, 10 ** 19))


def _snake_to_camel(s):
    parts = s.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


# ── enums (string on the wire; integers for `enum-encoding=int` clients) ────
_ENUMS = {
    "combiner": {"COMBINE_UNSPECIFIED": 0, "AND": 1, "OR": 2, "AND_WITH_MATCHING_RESOURCE": 3},
    "comparison": {"COMPARISON_UNSPECIFIED": 0, "COMPARISON_GT": 1, "COMPARISON_GE": 2, "COMPARISON_LT": 3,
                   "COMPARISON_LE": 4, "COMPARISON_EQ": 5, "COMPARISON_NE": 6},
    "perSeriesAligner": {"ALIGN_NONE": 0, "ALIGN_DELTA": 1, "ALIGN_RATE": 2, "ALIGN_INTERPOLATE": 3,
                         "ALIGN_NEXT_OLDER": 4, "ALIGN_MIN": 10, "ALIGN_MAX": 11, "ALIGN_MEAN": 12,
                         "ALIGN_COUNT": 13, "ALIGN_SUM": 14, "ALIGN_STDDEV": 15, "ALIGN_COUNT_TRUE": 16,
                         "ALIGN_COUNT_FALSE": 24, "ALIGN_FRACTION_TRUE": 17, "ALIGN_PERCENTILE_99": 18,
                         "ALIGN_PERCENTILE_95": 19, "ALIGN_PERCENTILE_50": 20, "ALIGN_PERCENTILE_05": 21,
                         "ALIGN_PERCENT_CHANGE": 23},
    "crossSeriesReducer": {"REDUCE_NONE": 0, "REDUCE_MEAN": 1, "REDUCE_MIN": 2, "REDUCE_MAX": 3, "REDUCE_SUM": 4,
                           "REDUCE_STDDEV": 5, "REDUCE_COUNT": 6, "REDUCE_COUNT_TRUE": 7, "REDUCE_COUNT_FALSE": 15,
                           "REDUCE_FRACTION_TRUE": 8, "REDUCE_PERCENTILE_99": 9, "REDUCE_PERCENTILE_95": 10,
                           "REDUCE_PERCENTILE_50": 11, "REDUCE_PERCENTILE_05": 12},
    "severity": {"SEVERITY_UNSPECIFIED": 0, "CRITICAL": 10, "ERROR": 20, "WARNING": 30},
    "verificationStatus": {"VERIFICATION_STATUS_UNSPECIFIED": 0, "UNVERIFIED": 1, "VERIFIED": 2},
    "metricKind": {"METRIC_KIND_UNSPECIFIED": 0, "GAUGE": 1, "DELTA": 2, "CUMULATIVE": 3},
    "valueType": {"VALUE_TYPE_UNSPECIFIED": 0, "BOOL": 1, "INT64": 2, "DOUBLE": 3, "STRING": 4,
                  "DISTRIBUTION": 5, "MONEY": 6},
    "evaluationMissingData": {"EVALUATION_MISSING_DATA_UNSPECIFIED": 0, "EVALUATION_MISSING_DATA_INACTIVE": 1,
                              "EVALUATION_MISSING_DATA_ACTIVE": 2, "EVALUATION_MISSING_DATA_NO_OP": 3},
    "requestMethod": {"METHOD_UNSPECIFIED": 0, "GET": 1, "POST": 2},
    "contentType": {"TYPE_UNSPECIFIED": 0, "URL_ENCODED": 1, "USER_PROVIDED": 2},
    "checkerType": {"CHECKER_TYPE_UNSPECIFIED": 0, "STATIC_IP_CHECKERS": 1, "VPC_CHECKERS": 3},
    "selectedRegions": {"REGION_UNSPECIFIED": 0, "USA": 1, "EUROPE": 2, "SOUTH_AMERICA": 3, "ASIA_PACIFIC": 4,
                        "USA_OREGON": 5, "USA_IOWA": 6, "USA_VIRGINIA": 7},
    "matcher": {"CONTENT_MATCHER_OPTION_UNSPECIFIED": 0, "CONTAINS_STRING": 1, "NOT_CONTAINS_STRING": 2,
                "MATCHES_REGEX": 3, "NOT_MATCHES_REGEX": 4, "MATCHES_JSON_PATH": 5, "NOT_MATCHES_JSON_PATH": 6},
}
_ENUM_NAMES = {k: {v: n for n, v in m.items()} for k, m in _ENUMS.items()}


_LABEL_VT = {"STRING": 0, "BOOL": 1, "INT64": 2}   # LabelDescriptor.ValueType differs from MetricDescriptor's
_LABEL_VT_NAMES = {v: k for k, v in _LABEL_VT.items()}


def _label_descriptors(labels, to_int):
    out = []
    for x in labels:
        if isinstance(x, dict) and "valueType" in x:
            v = x["valueType"]
            if to_int and isinstance(v, str):
                v = _LABEL_VT.get(v, v)
            elif not to_int and isinstance(v, int) and not isinstance(v, bool):
                v = _LABEL_VT_NAMES.get(v, v)
            x = dict(x, valueType=v)
        out.append(x)
    return out


def _enum_walk(o, to_int):
    if isinstance(o, list):
        return [_enum_walk(x, to_int) for x in o]
    if not isinstance(o, dict):
        return o
    out = {}
    for k, v in o.items():
        if k == "labels" and isinstance(v, list):
            out[k] = _label_descriptors(v, to_int)
        elif k in _ENUMS and isinstance(v, list):
            out[k] = [_enum_conv(k, x, to_int) for x in v]
        elif k in _ENUMS and not isinstance(v, (dict,)):
            out[k] = _enum_conv(k, v, to_int)
        else:
            out[k] = _enum_walk(v, to_int)
    return out


def _enum_conv(key, v, to_int):
    if to_int and isinstance(v, str) and v in _ENUMS[key]:
        return _ENUMS[key][v]
    if not to_int and isinstance(v, int) and not isinstance(v, bool):
        return _ENUM_NAMES[key].get(v, v)
    return v


def _wants_int_enums(query):
    return "enum-encoding=int" in (query.get("$alt") or query.get("alt") or "").replace("%3D", "=")


# ── filters ────────────────────────────────────────────────────────────────
_CLAUSE = re.compile(r'^\s*([\w.\-]+)\s*(=~|!=|=)\s*(.+?)\s*$')
_FUNC = re.compile(r'^(starts_with|ends_with|has_substring|one_of)\((.*)\)$')


def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _split_and(filt):
    parts, cur, q = [], "", None
    i = 0
    while i < len(filt):
        c = filt[i]
        if q:
            cur += c
            if c == q:
                q = None
        elif c in "\"'":
            q = c
            cur += c
        elif filt[i:i + 5].upper() == " AND " :
            parts.append(cur)
            cur = ""
            i += 4
        else:
            cur += c
        i += 1
    parts.append(cur)
    return [p for p in parts if p.strip()]


def compile_filter(filt, getter, allowed=None):
    """-> predicate(obj). `getter(obj, lhs)` returns the value for a field path (or None)."""
    clauses = []
    for part in _split_and(filt or ""):
        m = _CLAUSE.match(part)
        if not m:
            raise _bad("Invalid filter '%s': expected field = \"value\" clauses joined by AND." % filt)
        lhs, op, rhs = m.groups()
        if allowed and not allowed(lhs):
            raise _bad("Invalid filter '%s': unsupported field '%s'." % (filt, lhs))
        fm = _FUNC.match(rhs.strip())
        if fm:
            fn, args = fm.groups()
            vals = [_unquote(a) for a in re.findall(r'"[^"]*"|\'[^\']*\'', args)] or [_unquote(args)]
            clauses.append((lhs, op, fn, vals))
        else:
            clauses.append((lhs, op, None, [_unquote(rhs)]))

    def pred(obj):
        for lhs, op, fn, vals in clauses:
            v = getter(obj, lhs)
            v = "" if v is None else str(v)
            if fn == "starts_with":
                ok = v.startswith(vals[0])
            elif fn == "ends_with":
                ok = v.endswith(vals[0])
            elif fn == "has_substring":
                ok = vals[0] in v
            elif fn == "one_of":
                ok = v in vals
            elif op == "=~":
                ok = re.search(vals[0], v) is not None
            else:
                ok = v == vals[0]
            if op == "!=":
                ok = not ok
            if not ok:
                return False
        return True
    return pred


def _paginate(items, query, key, extra=None):
    try:
        size = int(query.get("pageSize") or 0)
    except ValueError:
        raise _bad("Invalid pageSize.")
    if size < 0:
        raise _bad("pageSize must be non-negative.")
    start = 0
    tok = query.get("pageToken") or ""
    if tok:
        try:
            start = int(base64.urlsafe_b64decode(tok.encode()).decode())
        except Exception:
            raise _bad("Invalid pageToken.")
    size = size or 1000
    page = items[start:start + size]
    out = {key: page} if page else {}
    out.update(extra or {})
    if start + size < len(items):
        out["nextPageToken"] = base64.urlsafe_b64encode(str(start + size).encode()).decode()
    return out


# ── built-in catalogs ──────────────────────────────────────────────────────
def _md(type_, kind, vtype, unit, desc, labels, display, monitored):
    return {"type": type_, "metricKind": kind, "valueType": vtype, "unit": unit, "description": desc,
            "displayName": display, "labels": labels, "monitoredResourceTypes": monitored, "launchStage": "GA"}


BUILTIN_METRICS = {m["type"]: m for m in [
    _md("compute.googleapis.com/instance/cpu/utilization", "GAUGE", "DOUBLE", "10^2.%",
        "Fractional utilization of allocated CPU on this instance.", [], "CPU utilization", ["gce_instance"]),
    _md("compute.googleapis.com/instance/disk/read_bytes_count", "DELTA", "INT64", "By",
        "Count of bytes read from disk.", [{"key": "device_name", "valueType": "STRING"}], "Disk read bytes",
        ["gce_instance"]),
    _md("compute.googleapis.com/instance/network/received_bytes_count", "DELTA", "INT64", "By",
        "Count of bytes received from the network.", [{"key": "loadbalanced", "valueType": "BOOL"}],
        "Received bytes", ["gce_instance"]),
    _md("storage.googleapis.com/api/request_count", "DELTA", "INT64", "1", "Delta count of API calls.",
        [{"key": "method", "valueType": "STRING"}], "Request count", ["gcs_bucket"]),
    _md("pubsub.googleapis.com/subscription/num_undelivered_messages", "GAUGE", "INT64", "1",
        "Number of unacknowledged messages in a subscription.", [], "Undelivered messages", ["pubsub_subscription"]),
    _md("cloudsql.googleapis.com/database/cpu/utilization", "GAUGE", "DOUBLE", "10^2.%",
        "Current CPU utilization as a fraction of reserved CPU.", [], "CPU utilization", ["cloudsql_database"]),
    _md("kubernetes.io/container/cpu/core_usage_time", "CUMULATIVE", "DOUBLE", "s",
        "Cumulative CPU usage on all cores in seconds.", [], "CPU usage time", ["k8s_container"]),
]}

MONITORED_RESOURCES = {r["type"]: r for r in [
    {"type": "global", "displayName": "Global", "description": "A resource type that represents a generic resource.",
     "labels": [{"key": "project_id", "valueType": "STRING", "description": "The identifier of the GCP project."}]},
    {"type": "gce_instance", "displayName": "VM Instance", "description": "A Compute Engine VM instance.",
     "labels": [{"key": "project_id", "valueType": "STRING"}, {"key": "instance_id", "valueType": "STRING"},
                {"key": "zone", "valueType": "STRING"}]},
    {"type": "gcs_bucket", "displayName": "GCS Bucket", "description": "A Cloud Storage bucket.",
     "labels": [{"key": "project_id", "valueType": "STRING"}, {"key": "bucket_name", "valueType": "STRING"},
                {"key": "location", "valueType": "STRING"}]},
    {"type": "k8s_container", "displayName": "Kubernetes Container", "description": "A Kubernetes container instance.",
     "labels": [{"key": "project_id", "valueType": "STRING"}, {"key": "location", "valueType": "STRING"},
                {"key": "cluster_name", "valueType": "STRING"}, {"key": "namespace_name", "valueType": "STRING"},
                {"key": "pod_name", "valueType": "STRING"}, {"key": "container_name", "valueType": "STRING"}]},
    {"type": "cloudsql_database", "displayName": "Cloud SQL Database", "description": "A Cloud SQL database.",
     "labels": [{"key": "project_id", "valueType": "STRING"}, {"key": "database_id", "valueType": "STRING"},
                {"key": "region", "valueType": "STRING"}]},
    {"type": "pubsub_subscription", "displayName": "Cloud Pub/Sub Subscription",
     "description": "A Pub/Sub subscription.",
     "labels": [{"key": "project_id", "valueType": "STRING"}, {"key": "subscription_id", "valueType": "STRING"}]},
    {"type": "generic_node", "displayName": "Generic Node", "description": "A generic node in your system.",
     "labels": [{"key": "project_id", "valueType": "STRING"}, {"key": "location", "valueType": "STRING"},
                {"key": "namespace", "valueType": "STRING"}, {"key": "node_id", "valueType": "STRING"}]},
    {"type": "generic_task", "displayName": "Generic Task", "description": "A generic task in your system.",
     "labels": [{"key": "project_id", "valueType": "STRING"}, {"key": "location", "valueType": "STRING"},
                {"key": "namespace", "valueType": "STRING"}, {"key": "job", "valueType": "STRING"},
                {"key": "task_id", "valueType": "STRING"}]},
    {"type": "uptime_url", "displayName": "Uptime Check URL", "description": "A URL checked by an uptime check.",
     "labels": [{"key": "project_id", "valueType": "STRING"}, {"key": "host", "valueType": "STRING"}]},
]}
for _r in MONITORED_RESOURCES.values():
    _r["name"] = "projects/{project_id}/monitoredResourceDescriptors/" + _r["type"]

CHANNEL_DESCRIPTORS = {d["type"]: d for d in [
    {"type": "email", "displayName": "Email", "description": "An email address to which notifications are sent.",
     "labels": [{"key": "email_address", "description": "The email address.", "valueType": "STRING"}],
     "supportedTiers": ["SUPPORTED_TIER_UNSPECIFIED"]},
    {"type": "sms", "displayName": "SMS", "description": "A phone number to which text messages are sent.",
     "labels": [{"key": "number", "description": "The phone number.", "valueType": "STRING"}]},
    {"type": "slack", "displayName": "Slack", "description": "A Slack channel to which notifications are posted.",
     "labels": [{"key": "channel_name", "description": "The Slack channel name.", "valueType": "STRING"}]},
    {"type": "pagerduty", "displayName": "PagerDuty Services",
     "description": "A PagerDuty service key to which notifications are sent.",
     "labels": [{"key": "service_key", "description": "The service key.", "valueType": "STRING"}]},
    {"type": "pubsub", "displayName": "Cloud Pub/Sub", "description": "A Pub/Sub topic to which notifications are published.",
     "labels": [{"key": "topic", "description": "The topic, projects/{p}/topics/{t}.", "valueType": "STRING"}]},
    {"type": "webhook_basicauth", "displayName": "Webhooks with basic auth",
     "description": "A webhook URL with basic auth.",
     "labels": [{"key": "url", "description": "The webhook URL.", "valueType": "STRING"}]},
    {"type": "webhook_tokenauth", "displayName": "Webhooks with token auth",
     "description": "A webhook URL with token auth.",
     "labels": [{"key": "url", "description": "The webhook URL.", "valueType": "STRING"}]},
]}
for _d in CHANNEL_DESCRIPTORS.values():
    _d["name"] = "projects/{project_id}/notificationChannelDescriptors/" + _d["type"]

UPTIME_IPS = [
    ("USA_OREGON", "Portland, Oregon, USA", "35.203.0.1"), ("USA_IOWA", "Council Bluffs, Iowa, USA", "35.209.0.1"),
    ("USA_VIRGINIA", "Ashburn, Virginia, USA", "35.186.0.1"), ("EUROPE", "Belgium", "35.190.0.1"),
    ("SOUTH_AMERICA", "São Paulo, Brazil", "35.198.0.1"), ("ASIA_PACIFIC", "Singapore", "35.185.0.1")]


def _with_project(d, project):
    d = _copy(d)
    d["name"] = d["name"].replace("{project_id}", project)
    return d


# ── alert policies ─────────────────────────────────────────────────────────
_CONDITION_KINDS = ("conditionThreshold", "conditionAbsent", "conditionMatchedLog",
                    "conditionMonitoringQueryLanguage", "conditionPrometheusQueryLanguage")


def _policy_name(project, pid):
    return "projects/%s/alertPolicies/%s" % (project, pid)


def _mutation(actor="vyomi@appliance"):
    return {"mutateTime": _now(), "mutatedBy": actor}


def _validate_policy(p, store, project, creating=True):
    if not str(p.get("displayName") or "").strip():
        raise _bad("Field alert_policy.display_name is required and must be non-empty.")
    if len(p["displayName"]) > 512:
        raise _bad("Field alert_policy.display_name must be at most 512 characters.")
    conds = p.get("conditions")
    if not isinstance(conds, list) or not conds:
        raise _bad("Field alert_policy.conditions is required: an alert policy needs at least one condition.")
    if len(conds) > 6:
        raise _bad("Field alert_policy.conditions has too many values: at most 6 conditions.")
    for i, c in enumerate(conds):
        if not isinstance(c, dict) or not str(c.get("displayName") or "").strip():
            raise _bad("Field alert_policy.conditions[%d].display_name is required and must be non-empty." % i)
        kinds = [k for k in _CONDITION_KINDS if k in c]
        if len(kinds) != 1:
            raise _bad("Field alert_policy.conditions[%d] must specify exactly one condition type "
                       "(condition_threshold, condition_absent, ...)." % i)
        body = c[kinds[0]]
        if kinds[0] in ("conditionThreshold", "conditionAbsent"):
            if not str((body or {}).get("filter") or "").strip():
                raise _bad("Field alert_policy.conditions[%d].%s.filter is required." % (i, _snake(kinds[0])))
            if "duration" in body:
                parse_duration(body["duration"], "alert_policy.conditions[%d].duration" % i)
        if kinds[0] == "conditionThreshold":
            if body.get("comparison") in (None, "COMPARISON_UNSPECIFIED"):
                raise _bad("Field alert_policy.conditions[%d].condition_threshold.comparison is required." % i)
            if body["comparison"] not in _ENUMS["comparison"]:
                raise _bad("Invalid comparison '%s'." % body["comparison"])
            for a in [body.get("aggregations") or []]:
                for ag in a:
                    _check_aggregation(ag)
        if kinds[0] == "conditionAbsent" and "duration" not in body:
            raise _bad("Field alert_policy.conditions[%d].condition_absent.duration is required." % i)
    comb = p.get("combiner")
    if comb is not None and comb not in _ENUMS["combiner"]:
        raise _bad("Invalid combiner '%s': must be AND, OR or AND_WITH_MATCHING_RESOURCE." % comb)
    if len(conds) > 1 and comb in (None, "COMBINE_UNSPECIFIED"):
        raise _bad("Field alert_policy.combiner is required when an alert policy has more than one condition.")
    sev = p.get("severity")
    if sev is not None and sev not in _ENUMS["severity"]:
        raise _bad("Invalid severity '%s'." % sev)
    for ch in p.get("notificationChannels") or []:
        if ch not in store.notification_channels:
            raise _bad("Notification channel %s does not exist." % ch)
    for k, v in (p.get("userLabels") or {}).items():
        if not re.match(r"^[a-z][a-z0-9_-]{0,62}$", k):
            raise _bad("Invalid user label key '%s'." % k)
    doc = p.get("documentation")
    if doc is not None and (not isinstance(doc, dict) or len(doc.get("content") or "") > 8192):
        raise _bad("Field alert_policy.documentation.content must be at most 8192 characters.")


def _snake(s):
    return re.sub(r"([A-Z])", lambda m: "_" + m.group(1).lower(), s)


def _check_aggregation(ag):
    if ag.get("perSeriesAligner") and ag["perSeriesAligner"] not in _ENUMS["perSeriesAligner"]:
        raise _bad("Invalid per_series_aligner '%s'." % ag["perSeriesAligner"])
    if ag.get("crossSeriesReducer") and ag["crossSeriesReducer"] not in _ENUMS["crossSeriesReducer"]:
        raise _bad("Invalid cross_series_reducer '%s'." % ag["crossSeriesReducer"])
    if ag.get("alignmentPeriod"):
        parse_duration(ag["alignmentPeriod"], "alignment_period")


_POLICY_WRITABLE = ("displayName", "documentation", "userLabels", "conditions", "combiner", "enabled",
                    "notificationChannels", "alertStrategy", "severity")


def create_policy(store, project, payload):
    p = {k: _copy(v) for k, v in (payload or {}).items() if k in _POLICY_WRITABLE}
    p.pop("name", None)
    _validate_policy(p, store, project)
    if sum(1 for n in store.alert_policies if n.startswith("projects/%s/" % project)) >= MAX_POLICIES:
        raise _E(429, "RESOURCE_EXHAUSTED", "Quota exceeded for alert policies per project.")
    pid = _rand_id()
    name = _policy_name(project, pid)
    for c in p["conditions"]:
        c["name"] = "%s/conditions/%s" % (name, _rand_id())
    p["name"] = name
    p.setdefault("combiner", "OR")
    p.setdefault("enabled", True)
    p["enabled"] = bool(p["enabled"])
    p.setdefault("notificationChannels", [])
    p.setdefault("userLabels", {})
    p["creationRecord"] = _mutation()
    p["mutationRecord"] = _mutation()
    store.alert_policies[name] = p
    return p


def _get_policy(store, project, pid):
    p = store.alert_policies.get(_policy_name(project, pid))
    if not p:
        raise _E(404, "NOT_FOUND", "Alert policy %s does not exist." % _policy_name(project, pid))
    return p


def _apply_mask(cur, payload, mask, writable, what):
    """Patch `payload` into `cur` per `update_mask` (empty mask → replace every writable field given)."""
    merged = _copy(cur)
    paths = [_camel_path(f.strip()) for f in (mask or "").split(",") if f.strip()]
    if not paths:
        paths = [k for k in payload if k in writable]
        for k in writable:   # an unmasked PATCH replaces the whole writable body
            if k not in payload and k in merged and k not in ("enabled",):
                merged.pop(k, None)
    for path in paths:
        top = path.split(".")[0]
        if top not in writable:
            raise _bad("Invalid update mask: field '%s' is not updatable on %s." % (path, what))
        _set_path(merged, payload, path)
    return merged


def _camel_path(p):
    return ".".join(_snake_to_camel(s) for s in p.split("."))


def _set_path(dst, src, path):
    keys = path.split(".")
    s = src
    for k in keys:
        s = s.get(k) if isinstance(s, dict) else None
    d = dst
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    if s is None or s == {}:
        d.pop(keys[-1], None)
    else:
        d[keys[-1]] = _copy(s)


def patch_policy(store, project, pid, payload, mask):
    cur = _get_policy(store, project, pid)
    payload = dict(payload or {})
    payload.pop("name", None)
    merged = _apply_mask(cur, payload, mask, _POLICY_WRITABLE, "alert policy")
    merged.setdefault("enabled", True)
    merged.setdefault("combiner", "OR")
    _validate_policy(merged, store, project, creating=False)
    for c in merged["conditions"]:
        c.setdefault("name", "%s/conditions/%s" % (cur["name"], _rand_id()))
    merged["name"] = cur["name"]
    merged["creationRecord"] = cur.get("creationRecord")
    merged["mutationRecord"] = _mutation()
    store.alert_policies[cur["name"]] = merged
    return merged


def policy_view(p):
    return _copy(p)


def _policy_filter(store_obj_filter):
    def getter(p, lhs):
        l = _snake_to_camel(lhs)
        if l in ("displayName", "name"):
            return p.get(l)
        if l.startswith("userLabels."):
            return (p.get("userLabels") or {}).get(l.split(".", 1)[1])
        return None
    return compile_filter(store_obj_filter, getter, lambda l: _snake_to_camel(l).split(".")[0] in ("displayName", "name", "userLabels"))


def _order(items, order_by, default_key):
    if not order_by:
        return sorted(items, key=default_key)
    out = items
    for spec in reversed([s.strip() for s in order_by.split(",") if s.strip()]):
        desc = spec.startswith("-")
        f = _snake_to_camel(spec.lstrip("+-"))
        out = sorted(out, key=lambda x: str(x.get(f) or ""), reverse=desc)
    return out


def list_policies(store, project, query):
    prefix = "projects/%s/alertPolicies/" % project
    items = [p for n, p in store.alert_policies.items() if n.startswith(prefix)]
    if query.get("filter"):
        items = [p for p in items if _policy_filter(query["filter"])(p)]
    items = _order(items, query.get("orderBy"), lambda p: p["name"])
    return _paginate([policy_view(p) for p in items], query, "alertPolicies", {"totalSize": len(items)})


# ── notification channels ──────────────────────────────────────────────────
def _chan_name(project, cid):
    return "projects/%s/notificationChannels/%s" % (project, cid)


_CHANNEL_WRITABLE = ("type", "displayName", "description", "labels", "userLabels", "enabled")


def _validate_channel(c):
    t = c.get("type")
    if not t:
        raise _bad("Field notification_channel.type is required.")
    desc = CHANNEL_DESCRIPTORS.get(t)
    if not desc:
        raise _bad("Notification channel type '%s' is not supported; valid types: %s." % (t, ", ".join(sorted(CHANNEL_DESCRIPTORS))))
    labels = c.get("labels") or {}
    for l in desc["labels"]:
        if not labels.get(l["key"]):
            raise _bad("Field notification_channel.labels is missing required label '%s' for type '%s'." % (l["key"], t))
    if t == "email" and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", labels["email_address"]):
        raise _bad("Field notification_channel.labels.email_address has an invalid value '%s'." % labels["email_address"])
    if t in ("webhook_basicauth", "webhook_tokenauth") and not re.match(r"^https?://", labels["url"]):
        raise _bad("Field notification_channel.labels.url must be an http(s) URL.")
    if t == "pubsub" and not re.match(r"^projects/[^/]+/topics/[^/]+$", labels["topic"]):
        raise _bad("Field notification_channel.labels.topic must be projects/{project}/topics/{topic}.")
    if len(str(c.get("displayName") or "")) > 512:
        raise _bad("Field notification_channel.display_name must be at most 512 characters.")


def create_channel(store, project, payload):
    c = {k: _copy(v) for k, v in (payload or {}).items() if k in _CHANNEL_WRITABLE}
    _validate_channel(c)
    if sum(1 for n in store.notification_channels if n.startswith("projects/%s/" % project)) >= MAX_CHANNELS:
        raise _E(429, "RESOURCE_EXHAUSTED", "Quota exceeded for notification channels per project.")
    cid = _rand_id()
    name = _chan_name(project, cid)
    c["name"] = name
    c.setdefault("displayName", "")
    c["enabled"] = bool(c.get("enabled", True))
    c.setdefault("userLabels", {})
    c["verificationStatus"] = "VERIFIED"
    c["createTime"] = _now()
    c["mutationRecords"] = [_mutation()]
    store.notification_channels[name] = c
    return c


def _get_channel(store, project, cid):
    c = store.notification_channels.get(_chan_name(project, cid))
    if not c:
        raise _E(404, "NOT_FOUND", "Notification channel %s does not exist." % _chan_name(project, cid))
    return c


def patch_channel(store, project, cid, payload, mask):
    cur = _get_channel(store, project, cid)
    payload = dict(payload or {})
    payload.pop("name", None)
    merged = _apply_mask(cur, payload, mask, _CHANNEL_WRITABLE, "notification channel")
    merged.setdefault("enabled", True)
    _validate_channel(merged)
    merged["name"] = cur["name"]
    merged["verificationStatus"] = cur.get("verificationStatus", "VERIFIED")
    merged["createTime"] = cur.get("createTime")
    merged["mutationRecords"] = (cur.get("mutationRecords") or []) + [_mutation()]
    store.notification_channels[cur["name"]] = merged
    return merged


def delete_channel(store, project, cid, force):
    c = _get_channel(store, project, cid)
    users = [p for p in store.alert_policies.values() if c["name"] in (p.get("notificationChannels") or [])]
    if users and not force:
        raise _E(400, "FAILED_PRECONDITION",
                 "Notification channel %s is in use by %d alert policy(ies); delete them first or pass force=true."
                 % (c["name"], len(users)))
    for p in users:
        p["notificationChannels"] = [x for x in p["notificationChannels"] if x != c["name"]]
    del store.notification_channels[c["name"]]


def list_channels(store, project, query):
    prefix = "projects/%s/notificationChannels/" % project
    items = [c for n, c in store.notification_channels.items() if n.startswith(prefix)]
    if query.get("filter"):
        def getter(c, lhs):
            l = _snake_to_camel(lhs)
            if l.startswith("labels."):
                return (c.get("labels") or {}).get(l.split(".", 1)[1])
            return c.get(l)
        pred = compile_filter(query["filter"], getter)
        items = [c for c in items if pred(c)]
    items = _order(items, query.get("orderBy"), lambda c: c["name"])
    return _paginate(_copy(items), query, "notificationChannels", {"totalSize": len(items)})


# ── groups ─────────────────────────────────────────────────────────────────
_GROUP_WRITABLE = ("displayName", "parentName", "filter", "isCluster")


def _group_name(project, gid):
    return "projects/%s/groups/%s" % (project, gid)


def _validate_group(g, store):
    if not str(g.get("displayName") or "").strip():
        raise _bad("Field group.display_name is required and must be non-empty.")
    if len(g["displayName"]) > 100:
        raise _bad("Field group.display_name must be at most 100 characters.")
    if not str(g.get("filter") or "").strip():
        raise _bad("Field group.filter is required.")
    if g.get("parentName") and g["parentName"] not in store.groups:
        raise _bad("Field group.parent_name refers to a group that does not exist: %s." % g["parentName"])


def create_group(store, project, payload):
    g = {k: _copy(v) for k, v in (payload or {}).items() if k in _GROUP_WRITABLE}
    _validate_group(g, store)
    name = _group_name(project, _rand_id())
    g["name"] = name
    g.setdefault("isCluster", False)
    store.groups[name] = g
    return g


def _get_group(store, project, gid):
    g = store.groups.get(_group_name(project, gid))
    if not g:
        raise _E(404, "NOT_FOUND", "Group %s does not exist." % _group_name(project, gid))
    return g


def update_group(store, project, gid, payload):
    cur = _get_group(store, project, gid)
    g = {k: _copy(v) for k, v in (payload or {}).items() if k in _GROUP_WRITABLE}
    _validate_group(g, store)
    g["name"] = cur["name"]
    g.setdefault("isCluster", False)
    store.groups[cur["name"]] = g
    return g


def delete_group(store, project, gid, recursive):
    g = _get_group(store, project, gid)
    kids = [n for n, x in store.groups.items() if x.get("parentName") == g["name"]]
    if kids and not recursive:
        raise _E(400, "FAILED_PRECONDITION", "Group %s has child groups; pass recursive=true." % g["name"])
    for k in kids:
        store.groups.pop(k, None)
    del store.groups[g["name"]]


def list_groups(store, project, query):
    prefix = "projects/%s/groups/" % project
    items = [g for n, g in sorted(store.groups.items()) if n.startswith(prefix)]
    for key, field_ in (("childrenOfGroup", "parentName"), ("ancestorsOfGroup", None), ("descendantsOfGroup", None)):
        v = query.get(key)
        if v and key == "childrenOfGroup":
            items = [g for g in items if g.get("parentName") == v]
        elif v and key == "ancestorsOfGroup":
            chain, cur = [], store.groups.get(v)
            while cur and cur.get("parentName"):
                cur = store.groups.get(cur["parentName"])
                if cur:
                    chain.append(cur["name"])
            items = [g for g in items if g["name"] in chain]
        elif v and key == "descendantsOfGroup":
            def desc(n, seen=()):
                return [k for k, x in store.groups.items() if x.get("parentName") == n]
            ds, frontier = set(), [v]
            while frontier:
                nxt = [k for f in frontier for k in desc(f)]
                ds.update(nxt)
                frontier = nxt
            items = [g for g in items if g["name"] in ds]
    return _paginate(_copy(items), query, "group")


# ── uptime checks ──────────────────────────────────────────────────────────
_UPTIME_WRITABLE = ("displayName", "monitoredResource", "resourceGroup", "httpCheck", "tcpCheck", "period",
                    "timeout", "contentMatchers", "checkerType", "selectedRegions", "isInternal",
                    "internalCheckers", "userLabels")
_UPTIME_PERIODS = (60, 300, 600, 900)


def _validate_uptime(u):
    if not str(u.get("displayName") or "").strip():
        raise _bad("Field uptime_check_config.display_name is required and must be non-empty.")
    if sum(1 for k in ("monitoredResource", "resourceGroup") if u.get(k)) != 1:
        raise _bad("Field uptime_check_config must specify exactly one of monitored_resource or resource_group.")
    if sum(1 for k in ("httpCheck", "tcpCheck") if u.get(k)) != 1:
        raise _bad("Field uptime_check_config must specify exactly one of http_check or tcp_check.")
    mr = u.get("monitoredResource")
    if mr and not mr.get("type"):
        raise _bad("Field uptime_check_config.monitored_resource.type is required.")
    period = parse_duration(u.get("period") or "60s", "period")
    if period not in _UPTIME_PERIODS:
        raise _bad("Field uptime_check_config.period has an invalid value: must be one of 60s, 300s, 600s, 900s.")
    if not u.get("timeout"):
        raise _bad("Field uptime_check_config.timeout is required.")
    timeout = parse_duration(u["timeout"], "timeout")
    if not (1 <= timeout <= 60):
        raise _bad("Field uptime_check_config.timeout must be between 1s and 60s.")
    h = u.get("httpCheck")
    if h:
        port = h.get("port", 80)
        if not isinstance(port, int) or not (1 <= port <= 65535):
            raise _bad("Field uptime_check_config.http_check.port must be between 1 and 65535.")
        if h.get("path") and not str(h["path"]).startswith("/"):
            raise _bad("Field uptime_check_config.http_check.path must begin with '/'.")
    t = u.get("tcpCheck")
    if t and not (isinstance(t.get("port"), int) and 1 <= t["port"] <= 65535):
        raise _bad("Field uptime_check_config.tcp_check.port is required (1-65535).")


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:30] or "check"


def create_uptime(store, project, payload):
    u = {k: _copy(v) for k, v in (payload or {}).items() if k in _UPTIME_WRITABLE}
    _validate_uptime(u)
    u.setdefault("period", "60s")
    if u.get("httpCheck"):
        h = u["httpCheck"]
        h.setdefault("requestMethod", "GET")
        h.setdefault("path", "/")
        h.setdefault("port", 443 if h.get("useSsl") else 80)
        h.setdefault("useSsl", False)
        h.setdefault("validateSsl", False)
    u.setdefault("checkerType", "STATIC_IP_CHECKERS")
    u.setdefault("selectedRegions", [])
    u["isInternal"] = bool(u.get("isInternal", False))
    name = "projects/%s/uptimeCheckConfigs/%s-%s" % (project, _slug(u["displayName"]), _rand_suffix())
    u["name"] = name
    store.uptime_checks[name] = u
    return u


def _rand_suffix():
    return "".join(random.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(10))


def _get_uptime(store, project, uid):
    n = "projects/%s/uptimeCheckConfigs/%s" % (project, uid)
    u = store.uptime_checks.get(n)
    if not u:
        raise _E(404, "NOT_FOUND", "Uptime check %s does not exist." % n)
    return u


def patch_uptime(store, project, uid, payload, mask):
    cur = _get_uptime(store, project, uid)
    payload = dict(payload or {})
    payload.pop("name", None)
    merged = _apply_mask(cur, payload, mask, _UPTIME_WRITABLE, "uptime check")
    _validate_uptime(merged)
    merged["name"] = cur["name"]
    store.uptime_checks[cur["name"]] = merged
    return merged


# ── metric descriptors ─────────────────────────────────────────────────────
def _metric_name(project, type_):
    return "projects/%s/metricDescriptors/%s" % (project, type_)


def _descriptor_view(d, project):
    v = _copy(d)
    v["name"] = _metric_name(project, d["type"])
    return v


def _all_descriptors(store):
    out = dict(BUILTIN_METRICS)
    out.update(store.metric_descriptors)
    return out


def _is_writable_type(t):
    return t.startswith(CUSTOM_PREFIXES)


def _check_metric_type(t, what="metric_descriptor.type"):
    if not t:
        raise _bad("Field %s is required." % what)
    if not _is_writable_type(t):
        raise _bad("Field %s had an invalid value of \"%s\": must begin with one of: %s."
                   % (what, t, ", ".join(CUSTOM_PREFIXES)))
    if len(t) > 200 or not re.match(r"^[A-Za-z0-9_./\-]+$", t):
        raise _bad("Field %s had an invalid value of \"%s\": contains invalid characters or is too long." % (what, t))


def create_descriptor(store, project, payload):
    d = _copy(payload or {})
    t = d.get("type")
    _check_metric_type(t)
    kind = d.get("metricKind") or "GAUGE"
    vtype = d.get("valueType") or "DOUBLE"
    if kind not in ("GAUGE", "DELTA", "CUMULATIVE") or vtype not in _ENUMS["valueType"]:
        raise _bad("Invalid metric_kind/value_type: %s/%s." % (kind, vtype))
    if kind != "GAUGE" and vtype in ("STRING", "BOOL"):
        raise _bad("Field metric_descriptor.value_type %s is only valid for GAUGE metrics." % vtype)
    rec = {"type": t, "metricKind": kind, "valueType": vtype, "unit": d.get("unit") or "",
           "description": d.get("description") or "", "displayName": d.get("displayName") or "",
           "labels": d.get("labels") or [], "launchStage": d.get("launchStage") or "GA"}
    old = store.metric_descriptors.get(t)
    if old and (old["metricKind"], old["valueType"]) != (kind, vtype):
        raise _E(409, "ALREADY_EXISTS", "Metric descriptor %s already exists with a different kind/value type." % t)
    if len(store.metric_descriptors) >= 10000 and not old:
        raise _E(429, "RESOURCE_EXHAUSTED", "Quota exceeded for custom metric descriptors.")
    store.metric_descriptors[t] = rec
    return _descriptor_view(rec, project)


def get_descriptor(store, project, t):
    d = _all_descriptors(store).get(t)
    if not d:
        raise _E(404, "NOT_FOUND", "Cannot find metric descriptor %s." % _metric_name(project, t))
    return _descriptor_view(d, project)


def delete_descriptor(store, project, t):
    if t in BUILTIN_METRICS:
        raise _bad("Cannot delete metric descriptor %s: only user-defined metric descriptors can be deleted." % t)
    if t not in store.metric_descriptors:
        raise _E(404, "NOT_FOUND", "Cannot find metric descriptor %s." % _metric_name(project, t))
    del store.metric_descriptors[t]
    for k in [k for k, s in store.time_series.items() if s["metric"]["type"] == t]:
        del store.time_series[k]


def list_descriptors(store, project, query):
    def getter(d, lhs):
        return d["type"] if lhs == "metric.type" else None
    pred = compile_filter(query.get("filter"), getter, lambda l: l == "metric.type") if query.get("filter") else (lambda d: True)
    items = [_descriptor_view(d, project) for t, d in sorted(_all_descriptors(store).items()) if pred(d)]
    return _paginate(items, query, "metricDescriptors")


# ── time series ────────────────────────────────────────────────────────────
def _series_key(project, metric, resource):
    def lab(x):
        return ",".join("%s=%s" % (k, v) for k, v in sorted((x.get("labels") or {}).items()))
    return "%s|%s|%s|%s|%s" % (project, metric["type"], lab(metric), resource["type"], lab(resource))


def _point_value(v):
    kinds = [k for k in ("boolValue", "int64Value", "doubleValue", "stringValue", "distributionValue") if k in (v or {})]
    if len(kinds) != 1:
        raise _bad("Field value must specify exactly one of bool_value, int64_value, double_value, "
                   "string_value or distribution_value.")
    return kinds[0]


_VT_OF = {"boolValue": "BOOL", "int64Value": "INT64", "doubleValue": "DOUBLE", "stringValue": "STRING",
          "distributionValue": "DISTRIBUTION"}


def write_time_series(store, project, payload):
    series = (payload or {}).get("timeSeries")
    if not isinstance(series, list) or not series:
        raise _bad("Field time_series is required: at least one TimeSeries must be written.")
    if len(series) > MAX_SERIES_PER_WRITE:
        raise _bad("Field time_series has too many values: at most %d time series per request." % MAX_SERIES_PER_WRITE)
    staged, seen = [], set()
    now = _now_dt()
    new_desc = {}
    for i, s in enumerate(series):
        where = "timeSeries[%d]" % i
        metric, resource = (s.get("metric") or {}), (s.get("resource") or {})
        t = metric.get("type")
        if not t:
            raise _bad("Field %s.metric.type is required." % where)
        if not _is_writable_type(t):
            raise _bad("Field %s.metric had an invalid value of \"%s\": the metric type is not a writable "
                       "user-defined metric (must begin with %s)." % (where, t, " or ".join(CUSTOM_PREFIXES)))
        if not resource.get("type"):
            raise _bad("Field %s.resource.type is required." % where)
        if resource["type"] not in MONITORED_RESOURCES:
            raise _bad("Field %s.resource had an invalid value: unknown monitored resource type '%s'."
                       % (where, resource["type"]))
        pts = s.get("points")
        if not isinstance(pts, list) or len(pts) != 1:
            raise _bad("Field %s.points had an invalid value: Only one point can be written per TimeSeries per request." % where)
        pt = pts[0]
        vk = _point_value(pt.get("value"))
        interval = pt.get("interval") or {}
        if not interval.get("endTime"):
            raise _bad("Field %s.points[0].interval.end_time is required." % where)
        end = parse_ts(interval["endTime"])
        start = parse_ts(interval["startTime"]) if interval.get("startTime") else None
        if end > now + timedelta(minutes=5):
            raise _bad("Field %s.points[0].interval.end_time had an invalid value: timestamp is too far in the future." % where)
        if end < now - timedelta(days=25):
            raise _bad("Field %s.points[0].interval.end_time had an invalid value: timestamp is too old (25 days)." % where)
        if start and start > end:
            raise _bad("Field %s.points[0].interval had an invalid value: start_time must not be later than end_time." % where)
        existing = store.metric_descriptors.get(t) or new_desc.get(t)
        kind = s.get("metricKind") or (existing or {}).get("metricKind") or "GAUGE"
        vtype = s.get("valueType") or (existing or {}).get("valueType") or _VT_OF[vk]
        if existing:
            if kind != existing["metricKind"] and s.get("metricKind"):
                raise _bad("Field %s.metric_kind had an invalid value: %s does not match the metric descriptor kind %s."
                           % (where, kind, existing["metricKind"]))
            vtype = existing["valueType"]
        if _VT_OF[vk] != vtype:
            raise _bad("Field %s.points[0].value had an invalid value: Value type does not match the metric: "
                       "expected %s, got %s." % (where, vtype, _VT_OF[vk]))
        if kind in ("DELTA", "CUMULATIVE") and not start:
            raise _bad("Field %s.points[0].interval.start_time is required for %s metrics." % (where, kind))
        if kind == "GAUGE" and start and start != end:
            raise _bad("Field %s.points[0].interval.start_time must equal end_time for GAUGE metrics." % where)
        key = _series_key(project, metric, resource)
        if key in seen:
            raise _bad("Field %s had an invalid value: Duplicate TimeSeries encountered. Only one point can be "
                       "written per TimeSeries per request." % where)
        seen.add(key)
        prev = store.time_series.get(key)
        if prev and prev["points"]:
            last = parse_ts(prev["points"][-1]["interval"]["endTime"])
            if end <= last:
                raise _bad("Field %s.points[0].interval.end_time had an invalid value: Points must be written in order. "
                           "One or more of the points specified had an older end time than the most recent point." % where)
        if not existing:
            new_desc[t] = {"type": t, "metricKind": kind, "valueType": vtype, "unit": s.get("unit") or "",
                           "description": "", "displayName": "", "labels": [
                               {"key": k, "valueType": "STRING"} for k in sorted((metric.get("labels") or {}))],
                           "launchStage": "GA"}
        staged.append((key, {"metric": {"type": t, "labels": _copy(metric.get("labels") or {})},
                             "resource": {"type": resource["type"], "labels": _copy(resource.get("labels") or {})},
                             "metricKind": kind, "valueType": vtype, "unit": s.get("unit") or ""},
                       {"interval": {k: v for k, v in (("startTime", _ts(start) if start else None),
                                                       ("endTime", _ts(end))) if v},
                        "value": {vk: pt["value"][vk]}}))
    store.metric_descriptors.update(new_desc)   # implicit creation of custom metrics, like the real API
    for key, meta, point in staged:
        rec = store.time_series.setdefault(key, dict(meta, points=[]))
        rec["points"].append(point)
        if len(rec["points"]) > MAX_POINTS_PER_SERIES:
            del rec["points"][: len(rec["points"]) - MAX_POINTS_PER_SERIES]
    return {}


def _ts_getter(s, lhs):
    if lhs == "metric.type":
        return s["metric"]["type"]
    if lhs == "resource.type":
        return s["resource"]["type"]
    m = re.match(r"^(metric|resource)\.labels?\.(.+)$", lhs)
    if m:
        return (s[m.group(1)].get("labels") or {}).get(m.group(2))
    if lhs == "metadata.system_labels" or lhs.startswith("metadata."):
        return None
    return None


def _num(v):
    for k in ("doubleValue", "int64Value"):
        if k in v:
            return float(v[k])
    if "boolValue" in v:
        return 1.0 if v["boolValue"] else 0.0
    return None


_ALIGN = {"ALIGN_MEAN", "ALIGN_MAX", "ALIGN_MIN", "ALIGN_SUM", "ALIGN_COUNT", "ALIGN_NONE", "ALIGN_STDDEV",
          "ALIGN_RATE", "ALIGN_DELTA", "ALIGN_NEXT_OLDER", "ALIGN_INTERPOLATE", "ALIGN_COUNT_TRUE",
          "ALIGN_COUNT_FALSE", "ALIGN_FRACTION_TRUE"}


def _reduce(fn, vals):
    n = len(vals)
    if fn in ("ALIGN_MEAN", "REDUCE_MEAN"):
        return sum(vals) / n
    if fn in ("ALIGN_MAX", "REDUCE_MAX"):
        return max(vals)
    if fn in ("ALIGN_MIN", "REDUCE_MIN"):
        return min(vals)
    if fn in ("ALIGN_SUM", "REDUCE_SUM"):
        return sum(vals)
    if fn in ("ALIGN_COUNT", "REDUCE_COUNT"):
        return n
    if fn in ("ALIGN_STDDEV", "REDUCE_STDDEV"):
        m = sum(vals) / n
        return math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1)) if n > 1 else 0.0
    if fn in ("ALIGN_COUNT_TRUE", "REDUCE_COUNT_TRUE"):
        return sum(1 for x in vals if x)
    if fn in ("ALIGN_COUNT_FALSE", "REDUCE_COUNT_FALSE"):
        return sum(1 for x in vals if not x)
    if fn in ("ALIGN_FRACTION_TRUE", "REDUCE_FRACTION_TRUE"):
        return sum(1 for x in vals if x) / n
    raise _bad("Aggregation '%s' is not supported by this appliance." % fn)


def _val(x, count=False):
    return {"int64Value": str(int(x))} if count else {"doubleValue": float(x)}


def list_time_series(store, project, query):
    filt = query.get("filter")
    if not filt:
        raise _bad("Field filter is required.")
    if "metric.type" not in filt:
        raise _bad("Field filter had an invalid value of \"%s\": must specify a metric type, e.g. "
                   "metric.type = \"custom.googleapis.com/foo\"." % filt)
    if not query.get("interval.endTime"):
        raise _bad("Field interval.end_time is required.")
    end = parse_ts(query["interval.endTime"])
    start = parse_ts(query["interval.startTime"]) if query.get("interval.startTime") else end
    if start > end:
        raise _bad("Field interval had an invalid value: start_time must not be later than end_time.")
    view = query.get("view") or "FULL"
    if view in ("0", 0):
        view = "FULL"
    if view not in ("FULL", "HEADERS", "1"):
        raise _bad("Field view has an invalid value '%s'." % view)
    headers_only = view in ("HEADERS", "1")
    pred = compile_filter(filt, _ts_getter, lambda l: l in ("metric.type", "resource.type", "project") or re.match(
        r"^(metric|resource)\.labels?\.", l) or l.startswith("metadata."))
    aligner = query.get("aggregation.perSeriesAligner") or "ALIGN_NONE"
    reducer = query.get("aggregation.crossSeriesReducer") or "REDUCE_NONE"
    aligner = _ENUM_NAMES["perSeriesAligner"].get(int(aligner), aligner) if str(aligner).isdigit() else aligner
    reducer = _ENUM_NAMES["crossSeriesReducer"].get(int(reducer), reducer) if str(reducer).isdigit() else reducer
    if aligner not in _ENUMS["perSeriesAligner"] or reducer not in _ENUMS["crossSeriesReducer"]:
        raise _bad("Invalid aggregation: aligner '%s' / reducer '%s'." % (aligner, reducer))
    period = parse_duration(query.get("aggregation.alignmentPeriod") or "0s", "aggregation.alignment_period")
    if aligner != "ALIGN_NONE" and period < 60:
        raise _bad("Field aggregation.alignment_period must be at least 60s when a per_series_aligner is set.")
    if reducer != "REDUCE_NONE" and aligner == "ALIGN_NONE":
        raise _bad("Field aggregation.per_series_aligner is required when cross_series_reducer is set.")
    group_by = [g for g in (query.get("aggregation.groupByFields") or "").split(",") if g]
    selected = []
    for key, s in sorted(store.time_series.items()):
        if not key.startswith(project + "|") or not pred(s):
            continue
        pts = [p for p in s["points"] if start <= parse_ts(p["interval"]["endTime"]) <= end]
        selected.append((s, pts))
    out = []
    if aligner == "ALIGN_NONE":
        for s, pts in selected:
            if not pts:
                continue
            ent = {k: _copy(v) for k, v in s.items() if k != "points"}
            if not headers_only:
                ent["points"] = [_copy(p) for p in reversed(pts)]
            out.append(ent)
    else:
        aligned = []
        for s, pts in selected:
            buckets = {}
            for p in pts:
                e = parse_ts(p["interval"]["endTime"])
                idx = math.ceil((e - start).total_seconds() / period) if e > start else 0
                v = _num(p["value"])
                if v is not None:
                    buckets.setdefault(idx, []).append(v)
            if not buckets:
                continue
            a_pts = []
            for idx in sorted(buckets, reverse=True):
                b_end = start + timedelta(seconds=idx * period)
                b_start = b_end - timedelta(seconds=period)
                val = _reduce(aligner, buckets[idx])
                cnt = aligner in ("ALIGN_COUNT", "ALIGN_COUNT_TRUE", "ALIGN_COUNT_FALSE")
                a_pts.append({"interval": {"startTime": _ts(b_start), "endTime": _ts(b_end)}, "value": _val(val, cnt)})
            vt = "INT64" if aligner in ("ALIGN_COUNT", "ALIGN_COUNT_TRUE", "ALIGN_COUNT_FALSE") else "DOUBLE"
            aligned.append(dict({k: _copy(v) for k, v in s.items() if k != "points"}, valueType=vt,
                                metricKind="GAUGE" if aligner != "ALIGN_DELTA" else "DELTA", points=a_pts))
        if reducer == "REDUCE_NONE":
            for ent in aligned:
                if headers_only:
                    ent.pop("points")
                out.append(ent)
        else:
            groups = {}
            for ent in aligned:
                gk = tuple(_group_label(ent, f) for f in group_by)
                groups.setdefault(gk, []).append(ent)
            for gk, ents in sorted(groups.items()):
                by_end = {}
                for ent in ents:
                    for p in ent["points"]:
                        by_end.setdefault(p["interval"]["endTime"], (p["interval"], []))[1].append(_num(p["value"]))
                pts = []
                for e in sorted(by_end, reverse=True):
                    iv, vals = by_end[e]
                    val = _reduce(reducer, vals)
                    cnt = reducer in ("REDUCE_COUNT", "REDUCE_COUNT_TRUE", "REDUCE_COUNT_FALSE")
                    pts.append({"interval": iv, "value": _val(val, cnt)})
                metric = {"type": ents[0]["metric"]["type"],
                          "labels": {f.split(".", 2)[2]: v for f, v in zip(group_by, gk) if f.startswith("metric.labels.")}}
                res = {"type": ents[0]["resource"]["type"],
                       "labels": {f.split(".", 2)[2]: v for f, v in zip(group_by, gk) if f.startswith("resource.labels.")}}
                ent = {"metric": metric, "resource": res, "metricKind": "GAUGE",
                       "valueType": "INT64" if reducer in ("REDUCE_COUNT", "REDUCE_COUNT_TRUE", "REDUCE_COUNT_FALSE") else "DOUBLE",
                       "unit": ents[0].get("unit", "")}
                if not headers_only:
                    ent["points"] = pts
                out.append(ent)
    res = _paginate(out, query, "timeSeries")
    if out:
        res["unit"] = out[0].get("unit", "")
    return res


def _group_label(ent, f):
    m = re.match(r"^(metric|resource)\.labels\.(.+)$", f)
    return (ent[m.group(1)].get("labels") or {}).get(m.group(2), "") if m else ""


# ── console views ──────────────────────────────────────────────────────────
def _condition_summary(c):
    kind = next((k for k in _CONDITION_KINDS if k in c), None)
    body = c.get(kind) or {}
    if kind == "conditionThreshold":
        op = {"COMPARISON_GT": ">", "COMPARISON_GE": ">=", "COMPARISON_LT": "<", "COMPARISON_LE": "<=",
              "COMPARISON_EQ": "==", "COMPARISON_NE": "!="}.get(body.get("comparison"), "?")
        return "%s %s %s for %s" % (_metric_of(body.get("filter")), op, body.get("thresholdValue", 0),
                                    body.get("duration") or "0s")
    if kind == "conditionAbsent":
        return "%s absent for %s" % (_metric_of(body.get("filter")), body.get("duration"))
    if kind == "conditionMatchedLog":
        return "Log match: %s" % (body.get("filter") or "")
    return c.get("displayName", "")


def _metric_of(filt):
    m = re.search(r'metric\.type\s*=\s*"([^"]+)"', filt or "")
    return m.group(1) if m else (filt or "")


def policy_console_view(store, p):
    pid = p["name"].rsplit("/", 1)[-1]
    conds = p.get("conditions") or []
    chans = []
    for n in p.get("notificationChannels") or []:
        c = store.notification_channels.get(n)
        chans.append((c.get("displayName") or (c.get("labels") or {}).get(
            next(iter(c.get("labels") or {}), ""), "") or n.rsplit("/", 1)[-1]) if c else n.rsplit("/", 1)[-1])
    first = conds[0] if conds else {}
    kind = next((k for k in _CONDITION_KINDS if k in first), None)
    body = first.get(kind) or {}
    sev = p.get("severity")
    v = policy_view(p)
    v.update({
        "id": pid, "resourceName": p["name"], "project": p["name"].split("/")[1],
        "display_name": p.get("displayName", ""),
        "state": "Enabled" if p.get("enabled", True) else "Disabled",
        "severity_text": {"CRITICAL": "Critical", "ERROR": "Error", "WARNING": "Warning"}.get(sev, "No severity"),
        "condition_count": len(conds),
        "condition_summary": "; ".join(_condition_summary(c) for c in conds) or "None",
        "metric_type": _metric_of(body.get("filter")) if body.get("filter") else "None",
        "threshold_text": ("%s %s" % ({"COMPARISON_GT": ">", "COMPARISON_GE": ">=", "COMPARISON_LT": "<",
                                       "COMPARISON_LE": "<=", "COMPARISON_EQ": "==", "COMPARISON_NE": "!="}.get(
                                           body.get("comparison"), "?"), body.get("thresholdValue", 0)))
        if kind == "conditionThreshold" else ("Absent" if kind == "conditionAbsent" else "Log match"),
        "duration_text": body.get("duration") or "0s",
        "combiner_text": {"AND": "All conditions (AND)", "OR": "Any condition (OR)",
                          "AND_WITH_MATCHING_RESOURCE": "All conditions, same resource"}.get(p.get("combiner"), "Any condition (OR)"),
        "channels_text": ", ".join(chans) if chans else "None",
        "channel_count": len(chans),
        "documentation_text": (p.get("documentation") or {}).get("content") or "No documentation",
        "last_modified": (p.get("mutationRecord") or {}).get("mutateTime", ""),
        "created": (p.get("creationRecord") or {}).get("mutateTime", ""),
        "created_by": (p.get("creationRecord") or {}).get("mutatedBy", ""),
        "incidents": "0 open incidents",
        "labels_text": ", ".join("%s=%s" % kv for kv in sorted((p.get("userLabels") or {}).items())) or "None",
    })
    return v


def console_view(store, p):
    return policy_console_view(store, p)


def list_all(store, project=None):
    return [policy_console_view(store, p) for n, p in sorted(store.alert_policies.items())
            if project is None or n.startswith("projects/%s/" % project)]


def form_to_policy(b, store, project="demo"):
    """Console create form (catalog createFields) → AlertPolicy REST body. An e-mail address creates (or
    reuses) an email notification channel and attaches it. Shared by the offline console REST and the
    Nano adapter so both consoles create identical policies."""
    metric = str(b.get("metricType") or "compute.googleapis.com/instance/cpu/utilization").strip()
    rtype = str(b.get("resourceType") or "gce_instance").strip()
    try:
        threshold = float(b.get("threshold") if b.get("threshold") not in (None, "") else 0.8)
    except (TypeError, ValueError):
        raise _bad("Threshold must be a number.")
    comparison = str(b.get("comparison") or "COMPARISON_GT").strip()
    if not comparison.startswith("COMPARISON_"):
        comparison = "COMPARISON_" + comparison.upper()
    name = str(b.get("name") or b.get("displayName") or "").strip()
    pol = {"displayName": name, "combiner": "OR", "enabled": True,
           "conditions": [{"displayName": "%s [%s]" % (name, metric.rsplit("/", 1)[-1]),
                           "conditionThreshold": {
                               "filter": 'metric.type = "%s" AND resource.type = "%s"' % (metric, rtype),
                               "comparison": comparison, "thresholdValue": threshold,
                               "duration": str(b.get("duration") or "300s"),
                               "aggregations": [{"alignmentPeriod": str(b.get("alignmentPeriod") or "60s"),
                                                 "perSeriesAligner": str(b.get("aligner") or "ALIGN_MEAN")}],
                               "trigger": {"count": 1}}}]}
    if b.get("documentation"):
        pol["documentation"] = {"content": str(b["documentation"]), "mimeType": "text/markdown"}
    if b.get("severity"):
        pol["severity"] = str(b["severity"]).upper()
    return pol


def create_from_form(store, b, project="demo"):
    pol = form_to_policy(b, store, project)
    email = str(b.get("email") or "").strip()
    if email:
        chan = next((c for c in store.notification_channels.values()
                     if c.get("type") == "email" and (c.get("labels") or {}).get("email_address") == email
                     and c["name"].startswith("projects/%s/" % project)), None)
        if chan is None:
            chan = create_channel(store, project, {"type": "email", "displayName": email,
                                                   "labels": {"email_address": email}})
        pol["notificationChannels"] = [chan["name"]]
    return policy_console_view(store, create_policy(store, project, pol))


# ── dispatch ───────────────────────────────────────────────────────────────
def dispatch(store, method, path, query=None, headers=None, body=b""):
    query = query or {}
    r = _dispatch(store, method, path, query, headers or {}, body)
    if r.status == 200 and _wants_int_enums(query):
        try:
            r.body = json.dumps(_enum_walk(json.loads(r.body), True)).encode()
        except Exception:
            pass
    return r


def _dispatch(store, method, path, query, headers, body):
    method = method.upper()
    for k, v in headers.items():   # REST clients without PATCH (JDK HttpURLConnection) tunnel it over POST
        if k.lower() == "x-http-method-override" and method == "POST" and v:
            method = str(v).upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if not isinstance(payload, dict):
        payload = {}
    payload = _enum_walk(payload, False)   # integer enums in request bodies → names
    p = path.split("?", 1)[0]
    if not (p.startswith("/v3/") or p == "/v3"):
        return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
    p = p[len("/v3"):].strip("/")
    verb = ""
    if ":" in p.rsplit("/", 1)[-1]:
        p, verb = p.rsplit(":", 1)
    segs = [s for s in p.split("/") if s]
    try:
        if segs == ["uptimeCheckIps"] and method == "GET":
            ips = [{"region": r, "location": loc, "ipAddress": ip} for r, loc, ip in UPTIME_IPS]
            return _json(200, _paginate(ips, query, "uptimeCheckIps"))
        if len(segs) < 3 or segs[0] != "projects":
            return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
        project, coll, rest = segs[1], segs[2], segs[3:]
        if coll == "alertPolicies":
            return _policies(store, method, project, rest, payload, query)
        if coll == "notificationChannels":
            return _channels(store, method, project, rest, verb, payload, query)
        if coll == "notificationChannelDescriptors":
            if not rest and method == "GET":
                items = [_with_project(d, project) for _, d in sorted(CHANNEL_DESCRIPTORS.items())]
                return _json(200, _paginate(items, query, "channelDescriptors"))
            if len(rest) == 1 and method == "GET":
                d = CHANNEL_DESCRIPTORS.get(rest[0])
                if not d:
                    raise _E(404, "NOT_FOUND", "Notification channel descriptor %s not found." % rest[0])
                return _json(200, _with_project(d, project))
        elif coll == "groups":
            return _groups(store, method, project, rest, payload, query)
        elif coll == "uptimeCheckConfigs":
            return _uptime(store, method, project, rest, payload, query)
        elif coll == "metricDescriptors":
            t = "/".join(rest)
            if not rest and method == "GET":
                return _json(200, list_descriptors(store, project, query))
            if not rest and method == "POST":
                return _json(200, create_descriptor(store, project, payload))
            if rest and method == "GET":
                return _json(200, get_descriptor(store, project, t))
            if rest and method == "DELETE":
                delete_descriptor(store, project, t)
                return _json(200, {})
        elif coll == "monitoredResourceDescriptors":
            if not rest and method == "GET":
                items = [_with_project(d, project) for _, d in sorted(MONITORED_RESOURCES.items())]
                if query.get("filter"):
                    pred = compile_filter(query["filter"], lambda d, l: d["type"] if l == "resource.type" else None)
                    items = [d for d in items if pred(d)]
                return _json(200, _paginate(items, query, "resourceDescriptors"))
            if len(rest) == 1 and method == "GET":
                d = MONITORED_RESOURCES.get(rest[0])
                if not d:
                    raise _E(404, "NOT_FOUND", "Monitored resource descriptor %s not found." % rest[0])
                return _json(200, _with_project(d, project))
        elif coll == "timeSeries" and not rest:
            if method == "POST" and not verb:
                return _json(200, write_time_series(store, project, payload))
            if method == "GET" and not verb:
                return _json(200, list_time_series(store, project, query))
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
    return _err(404, "NOT_FOUND", "Unknown path or method: %s %s" % (method, path))


def _policies(store, method, project, rest, payload, query):
    if not rest:
        if method == "POST":
            return _json(200, policy_view(create_policy(store, project, payload)))
        if method == "GET":
            return _json(200, list_policies(store, project, query))
        raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on alertPolicies." % method)
    if len(rest) == 1:
        if method == "GET":
            return _json(200, policy_view(_get_policy(store, project, rest[0])))
        if method == "PATCH":
            return _json(200, policy_view(patch_policy(store, project, rest[0], payload, query.get("updateMask", ""))))
        if method == "DELETE":
            p = _get_policy(store, project, rest[0])
            del store.alert_policies[p["name"]]
            return _json(200, {})
    raise _E(404, "NOT_FOUND", "Unknown alert policy path.")


def _channels(store, method, project, rest, verb, payload, query):
    if not rest:
        if method == "POST":
            return _json(200, _copy(create_channel(store, project, payload)))
        if method == "GET":
            return _json(200, list_channels(store, project, query))
        raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on notificationChannels." % method)
    if len(rest) == 1:
        cid = rest[0]
        if verb == "getVerificationCode" and method in ("POST", "GET"):
            _get_channel(store, project, cid)
            code = "".join(random.choice("0123456789") for _ in range(6))
            return _json(200, {"code": code, "expireTime": _ts(_now_dt() + timedelta(days=1))})
        if verb == "sendVerificationCode" and method == "POST":
            _get_channel(store, project, cid)
            return _json(200, {})
        if verb == "verify" and method == "POST":
            c = _get_channel(store, project, cid)
            if not payload.get("code"):
                raise _bad("Field code is required.")
            c["verificationStatus"] = "VERIFIED"
            return _json(200, _copy(c))
        if verb:
            raise _E(404, "NOT_FOUND", "Unknown method :%s" % verb)
        if method == "GET":
            return _json(200, _copy(_get_channel(store, project, cid)))
        if method == "PATCH":
            return _json(200, _copy(patch_channel(store, project, cid, payload, query.get("updateMask", ""))))
        if method == "DELETE":
            delete_channel(store, project, cid, str(query.get("force", "")).lower() == "true")
            return _json(200, {})
    raise _E(404, "NOT_FOUND", "Unknown notification channel path.")


def _groups(store, method, project, rest, payload, query):
    if not rest:
        if method == "POST":
            if str(query.get("validateOnly", "")).lower() == "true":
                g = {k: v for k, v in payload.items() if k in _GROUP_WRITABLE}
                _validate_group(g, store)
                return _json(200, dict(g, name=_group_name(project, "0")))
            return _json(200, _copy(create_group(store, project, payload)))
        if method == "GET":
            return _json(200, list_groups(store, project, query))
        raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on groups." % method)
    gid = rest[0]
    if len(rest) == 2 and rest[1] == "members" and method == "GET":
        _get_group(store, project, gid)
        return _json(200, {"members": [], "totalSize": 0})
    if len(rest) == 1:
        if method == "GET":
            return _json(200, _copy(_get_group(store, project, gid)))
        if method == "PUT":
            return _json(200, _copy(update_group(store, project, gid, payload)))
        if method == "DELETE":
            delete_group(store, project, gid, str(query.get("recursive", "")).lower() == "true")
            return _json(200, {})
    raise _E(404, "NOT_FOUND", "Unknown group path.")


def _uptime(store, method, project, rest, payload, query):
    if not rest:
        if method == "POST":
            return _json(200, _copy(create_uptime(store, project, payload)))
        if method == "GET":
            prefix = "projects/%s/uptimeCheckConfigs/" % project
            items = [_copy(u) for n, u in sorted(store.uptime_checks.items()) if n.startswith(prefix)]
            return _json(200, _paginate(items, query, "uptimeCheckConfigs", {"totalSize": len(items)}))
        raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on uptimeCheckConfigs." % method)
    if len(rest) == 1:
        if method == "GET":
            return _json(200, _copy(_get_uptime(store, project, rest[0])))
        if method == "PATCH":
            return _json(200, _copy(patch_uptime(store, project, rest[0], payload, query.get("updateMask", ""))))
        if method == "DELETE":
            u = _get_uptime(store, project, rest[0])
            del store.uptime_checks[u["name"]]
            return _json(200, {})
    raise _E(404, "NOT_FOUND", "Unknown uptime check path.")
