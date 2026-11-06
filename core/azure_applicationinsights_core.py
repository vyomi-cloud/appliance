"""Azure Application Insights core (``Microsoft.Insights``) — substrate-independent.

Speaks the ARM control-plane REST API of the ``applicationinsights`` management plane
(azure-rest-api-specs ``specification/applicationinsights``: components 2020-02-02,
webTests 2022-06-15), so ``azure-mgmt-applicationinsights`` / ``armapplicationinsights`` /
``com.azure.resourcemanager.applicationinsights`` and ``az monitor app-insights`` /
``az rest`` work unchanged against it.

NO fastapi / azure-sdk / socket / subprocess imports → loads under Pyodide, so the SAME file
runs offline and in Nano. It does not own a store: it mutates the ARM resource map the
dispatchers already keep (``{lower-cased resource id: record}``), which is space-scoped and
persisted by the existing seams (offline ``azure_arm_state``; Nano ``az_arm`` via
core/nano_persist). API keys and billing features live INSIDE their component record
(underscore keys, never serialised to clients) so the cost model counts one resource per
component / web test.

Resource types
    Microsoft.Insights/components   (+ ApiKeys, currentbillingfeatures, purge, operations, webtests)
    Microsoft.Insights/webtests
Errors use the ARM shape ``{"error":{"code","message"}}``.

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}``; Application Insights
operations are synchronous (``lro`` is always false).
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone

NAMESPACE = "Microsoft.Insights"
API_VERSION = "2020-02-02"
WEBTEST_API_VERSION = "2022-06-15"
DEFAULT_LOCATION = "eastus"
TYPES = ("components", "webtests")
APPLICATION_TYPES = ("web", "other")
FLOW_TYPES = ("Bluefield",)
REQUEST_SOURCES = ("rest",)
INGESTION_MODES = ("ApplicationInsights", "ApplicationInsightsWithDiagnosticSettings", "LogAnalytics")
NETWORK_ACCESS = ("Enabled", "Disabled", "SecuredByPerimeter")
RETENTION_CHOICES = (30, 60, 90, 120, 180, 270, 365, 550, 730)
WEBTEST_KINDS = ("ping", "multistep", "standard")
WEBTEST_FREQUENCIES = (300, 600, 900)
WEBTEST_TIMEOUTS = (30, 60, 90, 120)


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _guid(*parts):
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _ok(body=None, status=200, rid="", verb=""):
    return {"status": status, "headers": {}, "body": body, "lro": False, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "lro": False, "rid": "", "verb": ""}


def _canon(sub, rg, chain, names):
    seg = ["/subscriptions/" + sub] + (["resourceGroups/" + rg] if rg else []) + ["providers", NAMESPACE]
    for i, t in enumerate(chain):
        seg.append(t)
        if i < len(names):
            seg.append(names[i])
    return "/".join(seg)


def _not_found(kind, name, rg):
    return _E(404, "ResourceNotFound",
              f"The Resource '{NAMESPACE}/{kind}/{name}' under resource group '{rg}' was not found. "
              "For more details please go to https://aka.ms/ARMResourceNotFoundFix")


def _to_int(v, field, default=None):
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        raise _E(400, "BadRequest", f"Invalid value for '{field}': {v!r}.")


def _to_bool(v):
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def _region_cluster(loc):
    return (loc or DEFAULT_LOCATION).lower().replace(" ", "")


def _connection_string(ikey, app_id, loc):
    region = _region_cluster(loc)
    return (f"InstrumentationKey={ikey};IngestionEndpoint=https://{region}-0.in.applicationinsights.azure.com/;"
            f"LiveEndpoint=https://{region}.livediagnostics.monitor.azure.com/;ApplicationId={app_id}")


# ── components ──────────────────────────────────────────────────────────────
def _put_component(state, sub, rg, rid, name, payload, method):
    rec = state.get(rid.lower())
    props_in = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
    if method == "PATCH":                                   # UpdateTags — only tags are patchable
        if rec is None:
            raise _not_found("components", name, rg)
        if isinstance(payload.get("tags"), dict):
            rec["tags"] = payload["tags"]
        return rec
    kind = payload.get("kind")
    if rec is None:
        if not kind:
            raise _E(400, "BadRequest", "The 'kind' property is required for an Application Insights component.")
        if not payload.get("location"):
            raise _E(400, "LocationRequired", "The location property is required for this definition.")
        app_type = props_in.get("Application_Type")
        if not app_type:
            raise _E(400, "BadRequest", "Required property 'Application_Type' is missing.")
    else:
        app_type = props_in.get("Application_Type") or rec["properties"]["Application_Type"]
    if app_type not in APPLICATION_TYPES:
        raise _E(400, "BadRequest",
                 f"Invalid Application_Type '{app_type}'. Allowed values: {', '.join(APPLICATION_TYPES)}.")
    ingest = props_in.get("IngestionMode")
    if ingest is not None and ingest not in INGESTION_MODES:
        raise _E(400, "BadRequest", f"Invalid IngestionMode '{ingest}'. Allowed values: {', '.join(INGESTION_MODES)}.")
    retention = _to_int(props_in.get("RetentionInDays"), "RetentionInDays")
    if retention is not None and retention not in RETENTION_CHOICES:
        raise _E(400, "BadRequest",
                 f"Invalid RetentionInDays '{retention}'. Allowed values: {', '.join(map(str, RETENTION_CHOICES))}.")
    sampling = props_in.get("SamplingPercentage")
    if sampling is not None:
        try:
            sampling = float(sampling)
        except (TypeError, ValueError):
            raise _E(400, "BadRequest", f"Invalid SamplingPercentage '{sampling}'.")
        if not 0 < sampling <= 100:
            raise _E(400, "BadRequest", "SamplingPercentage must be greater than 0 and at most 100.")
    for f in ("publicNetworkAccessForIngestion", "publicNetworkAccessForQuery"):
        if props_in.get(f) is not None and props_in[f] not in NETWORK_ACCESS:
            raise _E(400, "BadRequest", f"Invalid {f} '{props_in[f]}'. Allowed values: {', '.join(NETWORK_ACCESS)}.")
    if rec is None:
        loc = payload.get("location")
        app_id = _guid("appid", rid)
        ikey = _guid("ikey", rid, _now())
        props = {
            "ApplicationId": name, "AppId": app_id, "Application_Type": app_type,
            "Flow_Type": props_in.get("Flow_Type") or "Bluefield",
            "Request_Source": props_in.get("Request_Source") or "rest",
            "InstrumentationKey": ikey, "Name": name,
            "CreationDate": _now(), "TenantId": sub,
            "ConnectionString": _connection_string(ikey, app_id, loc),
            "RetentionInDays": retention if retention is not None else 90,
            "SamplingPercentage": sampling,
            "DisableIpMasking": _to_bool(props_in.get("DisableIpMasking", False)),
            "ImmediatePurgeDataOn30Days": _to_bool(props_in.get("ImmediatePurgeDataOn30Days", False)),
            "IngestionMode": ingest or "ApplicationInsights",
            "publicNetworkAccessForIngestion": props_in.get("publicNetworkAccessForIngestion") or "Enabled",
            "publicNetworkAccessForQuery": props_in.get("publicNetworkAccessForQuery") or "Enabled",
            "DisableLocalAuth": _to_bool(props_in.get("DisableLocalAuth", False)),
            "ForceCustomerStorageForProfiler": _to_bool(props_in.get("ForceCustomerStorageForProfiler", False)),
            "provisioningState": "Succeeded",
        }
        if props_in.get("WorkspaceResourceId"):
            props["WorkspaceResourceId"] = props_in["WorkspaceResourceId"]
            props["IngestionMode"] = ingest or "LogAnalytics"
        if props["SamplingPercentage"] is None:
            props.pop("SamplingPercentage")
        rec = {"id": rid, "name": name, "type": f"{NAMESPACE}/components", "kind": kind, "location": loc,
               "tags": payload.get("tags") if isinstance(payload.get("tags"), dict) else {},
               "etag": '"' + _guid("etag", rid)[:8] + '"',
               "properties": props, "_type": f"{NAMESPACE}/components", "_sub": sub, "_rg": rg,
               "_keys": [], "_features": _default_features()}
        state[rid.lower()] = rec
        return rec
    # full update of an existing component (PUT)
    if kind:
        rec["kind"] = kind
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = payload["tags"]
    rec["properties"]["Application_Type"] = app_type
    for f in ("Flow_Type", "Request_Source", "WorkspaceResourceId", "publicNetworkAccessForIngestion",
              "publicNetworkAccessForQuery"):
        if props_in.get(f) is not None:
            rec["properties"][f] = props_in[f]
    if ingest is not None:
        rec["properties"]["IngestionMode"] = ingest
    if retention is not None:
        rec["properties"]["RetentionInDays"] = retention
    if sampling is not None:
        rec["properties"]["SamplingPercentage"] = sampling
    for f in ("DisableIpMasking", "ImmediatePurgeDataOn30Days", "DisableLocalAuth", "ForceCustomerStorageForProfiler"):
        if f in props_in:
            rec["properties"][f] = _to_bool(props_in[f])
    rec["etag"] = '"' + _guid("etag", rid, _now())[:8] + '"'
    return rec


def _default_features():
    return {
        "CurrentBillingFeatures": ["Basic"],
        "DataVolumeCap": {"Cap": 100.0, "WarningThreshold": 90, "ResetTime": 0, "StopSendNotificationWhenHitThreshold": False,
                          "StopSendNotificationWhenHitCap": False, "MaxHistoryCap": 500.0},
    }


def _features_view(rec):
    f = rec["_features"]
    return {"CurrentBillingFeatures": list(f["CurrentBillingFeatures"]), "DataVolumeCap": dict(f["DataVolumeCap"])}


def _api_key_view(rec, key, secret=False):
    out = {"id": key["id"], "name": key["name"], "createdDate": key["createdDate"],
           "linkedReadProperties": key["linkedReadProperties"], "linkedWriteProperties": key["linkedWriteProperties"]}
    if secret:
        out["apiKey"] = key["apiKey"]
    return out


def _linked(rec, items, kind):
    base = rec["id"]
    allowed = {"agentconfig", "aggregate", "api", "draft", "extendqueries", "search", "annotations", "profiler", "sourcemaps"}
    out = []
    for it in items or []:
        tail = str(it).rsplit("/", 1)[-1]
        if tail.lower() not in allowed:
            raise _E(400, "BadRequest", f"Invalid {kind} permission '{tail}'.")
        out.append(f"{base}/{tail}")
    return out


def _component_ops(state, rec, sub, rg, rest, method, payload):
    r0 = rest[0].lower()
    if r0 == "apikeys":
        return _apikey_ops(rec, rest[1:], method, payload)
    if r0 == "currentbillingfeatures":
        if method == "GET":
            return _ok(_features_view(rec))
        if method == "PUT":
            f = rec["_features"]
            if "CurrentBillingFeatures" in payload:
                feats = payload["CurrentBillingFeatures"]
                if not isinstance(feats, list) or not feats or any(x not in ("Basic", "Application Insights Enterprise") for x in feats):
                    raise _E(400, "BadRequest", "CurrentBillingFeatures must contain 'Basic' or 'Application Insights Enterprise'.")
                f["CurrentBillingFeatures"] = feats
            if isinstance(payload.get("DataVolumeCap"), dict):
                f["DataVolumeCap"].update(payload["DataVolumeCap"])
            return _ok(_features_view(rec))
    if r0 == "purge" and method == "POST":
        if not isinstance(payload.get("filters"), list) or not payload.get("table"):
            raise _E(400, "BadRequest", "Purge requires 'table' and 'filters'.")
        return _ok({"operationId": "purge-" + _guid("purge", rec["id"], _now())}, 202, rid=rec["id"], verb="purge")
    if r0 == "operations" and method == "GET":                 # GetPurgeStatus
        return _ok({"status": "completed"})
    if r0 == "webtests" and method == "GET":                   # ListByComponent — linked by the hidden-link tag
        return _ok({"value": [_view(r) for r in state.values()
                              if str(r.get("_type", "")).lower() == f"{NAMESPACE}/webtests".lower() and r.get("_sub") == sub
                              and (r.get("_rg") or "").lower() == (rg or "").lower()
                              and any(str(t).lower() == ("hidden-link:" + rec["id"]).lower() for t in (r.get("tags") or {}))]})
    if r0 == "analyticsitems":
        return _ok([])
    return _err(404, "ResourceTypeNotSupported", f"'{rest[0]}' is not supported on components.")


def _apikey_ops(rec, rest, method, payload):
    keys = rec["_keys"]
    if not rest:
        if method == "GET":
            return _ok({"value": [_api_key_view(rec, k) for k in keys]})
        if method == "POST":
            name = payload.get("name")
            if not name:
                raise _E(400, "BadRequest", "API key 'name' is required.")
            if any(k["name"] == name for k in keys):
                raise _E(409, "Conflict", f"An API key named '{name}' already exists.")
            kid = _guid("key", rec["id"], name, _now())
            key = {"id": f"{rec['id']}/ApiKeys/{kid}", "name": name, "createdDate": _now(),
                   "apiKey": uuid.uuid4().hex + uuid.uuid4().hex[:8],
                   "linkedReadProperties": _linked(rec, payload.get("linkedReadProperties"), "read"),
                   "linkedWriteProperties": _linked(rec, payload.get("linkedWriteProperties"), "write")}
            keys.append(key)
            return _ok(_api_key_view(rec, key, secret=True), 200, rid=key["id"], verb="post")
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    kid = rest[0]
    key = next((k for k in keys if k["id"].rsplit("/", 1)[-1].lower() == kid.lower()), None)
    if key is None:
        raise _E(404, "ResourceNotFound", f"The API key '{kid}' was not found on component '{rec['name']}'.")
    if method == "GET":
        return _ok(_api_key_view(rec, key))
    if method == "DELETE":
        keys.remove(key)
        return _ok(_api_key_view(rec, key), 200, rid=key["id"], verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── web tests ───────────────────────────────────────────────────────────────
def _put_webtest(state, sub, rg, rid, name, payload, method):
    rec = state.get(rid.lower())
    if method == "PATCH":                                   # UpdateTags
        if rec is None:
            raise _not_found("webtests", name, rg)
        if isinstance(payload.get("tags"), dict):
            rec["tags"] = payload["tags"]
        return rec
    props_in = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
    if rec is None:
        if not payload.get("location"):
            raise _E(400, "LocationRequired", "The location property is required for this definition.")
        if not props_in.get("Name"):
            raise _E(400, "BadRequest", "Required property 'Name' is missing.")
        if not props_in.get("Locations"):
            raise _E(400, "BadRequest", "Required property 'Locations' is missing.")
    kind = props_in.get("Kind") or props_in.get("WebTestKind") or (rec or {}).get("properties", {}).get("Kind") or "ping"
    if kind not in WEBTEST_KINDS:
        raise _E(400, "BadRequest", f"Invalid Kind '{kind}'. Allowed values: {', '.join(WEBTEST_KINDS)}.")
    freq = _to_int(props_in.get("Frequency"), "Frequency", (rec or {}).get("properties", {}).get("Frequency", 300))
    if freq not in WEBTEST_FREQUENCIES:
        raise _E(400, "BadRequest", f"Invalid Frequency '{freq}'. Allowed values: {', '.join(map(str, WEBTEST_FREQUENCIES))}.")
    timeout = _to_int(props_in.get("Timeout"), "Timeout", (rec or {}).get("properties", {}).get("Timeout", 30))
    if timeout not in WEBTEST_TIMEOUTS:
        raise _E(400, "BadRequest", f"Invalid Timeout '{timeout}'. Allowed values: {', '.join(map(str, WEBTEST_TIMEOUTS))}.")
    if rec is None:
        rec = {"id": rid, "name": name, "type": f"{NAMESPACE}/webtests", "location": payload["location"],
               "kind": payload.get("kind") or ("ping" if kind == "ping" else "multistep"),
               "tags": payload.get("tags") if isinstance(payload.get("tags"), dict) else {},
               "properties": {"SyntheticMonitorId": name, "Enabled": True, "RetryEnabled": True,
                              "Description": "", "provisioningState": "Succeeded"},
               "_type": f"{NAMESPACE}/webtests", "_sub": sub, "_rg": rg}
        state[rid.lower()] = rec
    p = rec["properties"]
    for f in ("Name", "Description", "Locations", "Configuration", "Request", "ValidationRules"):
        if f in props_in:
            p[f] = props_in[f]
    for f in ("Enabled", "RetryEnabled"):
        if f in props_in:
            p[f] = _to_bool(props_in[f])
    p["Kind"], p["Frequency"], p["Timeout"] = kind, freq, timeout
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = payload["tags"]
    p.setdefault("Locations", [])
    return rec


# ── dispatch ────────────────────────────────────────────────────────────────
def _list(state, sub, rg, tname):
    items = []
    for rec in state.values():
        if str(rec.get("_type", "")).lower() != f"{NAMESPACE}/{tname}".lower() or rec.get("_sub") != sub:
            continue
        if rg is not None and (rec.get("_rg") or "").lower() != rg.lower():
            continue
        items.append(_view(rec))
    return _ok({"value": items})


def dispatch(state, method, sub, rg, chain, names, payload=None, query=None):
    """Handle one ``Microsoft.Insights`` (components / webtests) ARM request.

    ``chain``  = path tokens after the namespace, e.g. ``["components", "ai1", "ApiKeys", "<id>"]``
    ``state``  = the ARM resource map (lower-cased id → record).
    """
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload)
    except _E as e:
        return _err(e.status, e.code, e.message)


def _dispatch(state, method, sub, rg, chain, payload):
    low = chain[0].lower()
    if low not in TYPES:
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{chain[0]}' is not supported.")
    canon = low
    if len(chain) == 1:                                    # collection list
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list(state, sub, rg, canon)
    name = chain[1]
    rid = _canon(sub, rg, [canon], [name])
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:                                               # sub-resource / action
        if rec is None or str(rec.get("_type", "")).lower() != f"{NAMESPACE}/{canon}".lower():
            raise _not_found(canon, name, rg)
        if low == "components":
            return _component_ops(state, rec, sub, rg, rest, method, payload)
        return _err(404, "ResourceTypeNotSupported", f"'{rest[0]}' is not supported on webtests.")
    if method == "GET":
        if rec is None:
            raise _not_found(canon, name, rg)
        return _ok(_view(rec))
    if method in ("PUT", "PATCH"):
        if rg is None:
            return _err(400, "InvalidResourceId", "Application Insights resources must be created in a resource group.")
        if not re.fullmatch(r"[A-Za-z0-9._()-]{1,260}", name) or name.endswith("."):
            return _err(400, "InvalidResourceName",
                        f"The resource name '{name}' is invalid. Names may contain letters, numbers, '.', '_', '-', '(' and ')'.")
        existed = rec is not None
        rec = (_put_component if low == "components" else _put_webtest)(state, sub, rg, rid, name, payload, method)
        return _ok(_view(rec), 200, rid=rid, verb=method.lower())   # the spec defines 200 only (no 201)
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        state.pop(rid.lower(), None)
        if low == "components":                            # web tests are tied to their component by the hidden-link tag
            for k in [k for k, r in state.items() if str(r.get("_type", "")).lower() == f"{NAMESPACE}/webtests".lower()
                      and any(str(t).lower() == rid.lower() or str(t).lower().startswith("hidden-link:" + rid.lower())
                              for t in (r.get("tags") or {}))]:
                state.pop(k, None)
        return _ok(None, 200, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── catalog helpers shared with the dispatchers / console ───────────────────
def resource_types():
    return [("components", API_VERSION), ("webtests", WEBTEST_API_VERSION)]
