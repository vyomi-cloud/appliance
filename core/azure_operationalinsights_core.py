"""Azure Log Analytics core (``Microsoft.OperationalInsights`` — workspaces, saved searches, tables, data sources).

Substrate-free (no fastapi / sockets / subprocess) so the SAME file runs offline and in Nano.

ARM REST of the ``operationalinsights`` resource provider (azure-rest-api-specs
``specification/operationalinsights/resource-manager``, api-version 2022-10-01 / 2020-08-01), so
``azure-mgmt-loganalytics`` / ``armoperationalinsights`` / ``com.azure.resourcemanager.loganalytics`` and
``az monitor log-analytics workspace …`` work unchanged:

    Microsoft.OperationalInsights/workspaces                       CreateOrUpdate / Update / Delete (?force) / Get / List*
    .../workspaces/{ws}/sharedKeys | getSharedKeys                 POST (primary + secondary key)
    .../workspaces/{ws}/regenerateSharedKey                        POST {name: primary|secondary}
    .../workspaces/{ws}/usages                                     GET
    .../workspaces/{ws}/intelligencePacks[/{pack}/Enable|Disable] GET / POST
    .../workspaces/{ws}/savedSearches/{id}                         CreateOrUpdate / Get / Delete / List
    .../workspaces/{ws}/tables/{table}                             CreateOrUpdate / Update / Get / Delete / ListByWorkspace
    .../workspaces/{ws}/dataSources/{name}                         CreateOrUpdate / Get / Delete / ListByWorkspace (?$filter=kind eq '…')
    .../workspaces/{ws}/api/query                                   POST {query} — the SAME ARM pass-through the
                                                                     Azure Portal's Logs blade uses when it has no
                                                                     data-plane token (real path/shape, api-version
                                                                     2017-10-01); see ``_run_query`` for the small
                                                                     KQL subset understood (table name, where,
                                                                     project, sort by/order by, take/limit, count).

Workspaces live in the shared ARM state map (offline ``azure_services._state``; Nano ``az_arm``), keyed by the
lower-cased resource id; their child collections live INSIDE the workspace record under underscore keys
(never serialised to ARM clients), so they are space-scoped and persisted by the same seams as the rest of ARM.
Data plane (also served by this file, both offline and Nano): ``.../workspaces/{ws}/api/logs`` (HTTP Data Collector: JSON
array, ``Log-Type`` header or ``logType`` query -> table ``<LogType>_CL``, fields suffixed _s/_d/_b like the real service),
``.../workspaces/{ws}/dataCollectionRules/{dcr}/streams/{Custom-X_CL}`` (Logs Ingestion API, 204) and
``.../workspaces/{ws}/api/query`` / ``/query`` (POST {"query"} or GET ?query=) answering with the Log Analytics
``{"tables":[{"name":"PrimaryResult","columns":[..],"rows":[..]}]}`` shape. KQL subset: ``Table | where`` (==, !=, =~, >, <, >=, <=,
contains, !contains, startswith, endswith, has, in, and/or) ``| project | extend``-free ``| take/limit | count | order by/sort by |
summarize count() by col | distinct``. Records live in the workspace record (``_rows``), so they follow the ARM state seams.
Not modelled: the real KQL language beyond that subset, data export, linked services/storage insights,
Query results are real for the built-in ``AzureActivity`` table (the SAME ``Microsoft.Insights/eventtypes`` rows
the Activity log feed reads, filtered to this subscription) and always empty for every other table (Heartbeat,
Perf, Syslog, Event, Usage, AzureDiagnostics, any custom ``_CL``/``_RST`` table) — there is no agent/telemetry
ingestion pipeline to populate them, and no per-workspace Activity Log export gating (every workspace's
AzureActivity table sees the whole subscription feed).
Not modelled: the api.loganalytics.io data-plane host directly (``azure-monitor-query`` / ``LogsQueryClient``
calls that host, not ARM, so they do not reach this module), data export, linked services/storage insights,
clusters, purge and conditional headers (If-Match / If-None-Match).

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}`` (``body`` is a JSON-able object or ``None``).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

NAMESPACE = "Microsoft.OperationalInsights"
WS_TYPE = f"{NAMESPACE}/workspaces"
API_VERSION = "2022-10-01"
DEFAULT_LOCATION = "eastus"
SKUS = ("Free", "Standalone", "PerNode", "PerGB2018", "Standard", "Premium", "CapacityReservation", "LACluster")
CAPACITY_LEVELS = (100, 200, 300, 400, 500, 1000, 2000, 5000, 10000, 25000, 50000)
ACCESS = ("Enabled", "Disabled", "SecuredByPerimeter")
TABLE_PLANS = ("Basic", "Analytics", "Auxiliary")
DS_KINDS = ("AzureActivityLog", "ChangeTrackingContentLocation", "ChangeTrackingCustomPath", "ChangeTrackingDataTypeConfiguration",
            "ChangeTrackingDefaultRegistry", "ChangeTrackingLinuxPath", "ChangeTrackingPath", "ChangeTrackingRegistry",
            "ChangeTrackingServices", "CustomLog", "CustomLogCollection", "DnsAnalytics", "GenericDataSource", "IISLogs",
            "ImportComputerGroup", "Itsm", "LinuxChangeTrackingPath", "LinuxPerformanceCollection", "LinuxPerformanceObject",
            "LinuxSyslog", "LinuxSyslogCollection", "NetworkMonitoring", "Office365", "SecurityCenterSecurityWindowsBaselineConfiguration",
            "SecurityEventCollectionConfiguration", "SecurityInsightsSecurityEventCollectionConfiguration",
            "SecurityWindowsBaselineConfiguration", "SqlDataClassification", "WindowsEvent", "WindowsPerformanceCounter",
            "WindowsTelemetry")
PACKS = ("AzureActivity", "ChangeTracking", "Security", "SecurityInsights", "ServiceMap", "SQLAssessment", "Updates",
         "VMInsights", "LogManagement", "AntiMalware", "AzureAutomation", "Containers", "InfrastructureInsights")
ALWAYS_ON_PACKS = ("LogManagement",)
# built-in tables every workspace starts with: name → (retention floor note, columns)
BASE_TABLES = {
    "Heartbeat": ["TimeGenerated", "Computer", "Category", "OSType", "Version"],
    "Perf": ["TimeGenerated", "Computer", "ObjectName", "CounterName", "CounterValue"],
    "Syslog": ["TimeGenerated", "Computer", "Facility", "SeverityLevel", "SyslogMessage"],
    "Event": ["TimeGenerated", "Computer", "EventLog", "EventID", "RenderedDescription"],
    "AzureActivity": ["TimeGenerated", "OperationName", "Caller", "Level", "ResourceGroup", "ResourceId", "Category", "ActivityStatus", "SubscriptionId"],
    "Usage": ["TimeGenerated", "DataType", "Quantity", "IsBillable", "Solution"],
    "AzureDiagnostics": ["TimeGenerated", "ResourceId", "Category", "OperationName", "ResultType"],
}
BASE_TABLES_LOWER = {n.lower(): n for n in BASE_TABLES}
# ARM table-schema column type → the KQL/Log Analytics Query API type name for the same value.
_ARM_TO_KQL_TYPE = {"string": "string", "int": "int", "long": "long", "real": "real", "boolean": "bool",
                    "datetime": "datetime", "guid": "guid", "dynamic": "dynamic"}
MAX_SAVED = 500
MAX_TABLES = 500
_WS_NAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{2,61}[A-Za-z0-9])$")
_CUSTOM_TABLE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,60}_(CL|RST)$")
_BAD_ID = re.compile(r"[<>*%&:\\?+/#]")


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


def _now(delta_days=0):
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _etag():
    return f'"{uuid.uuid4().hex[:16]}"'


def _ws_rid(sub, rg, name):
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{WS_TYPE}/{name}"


def _not_found(name, rg):
    return _E(404, "ResourceNotFound",
              f"The Resource '{WS_TYPE}/{name}' under resource group '{rg}' was not found. "
              "For more details please go to https://aka.ms/ARMResourceNotFoundFix")


def _child_not_found(kind, name, ws):
    return _E(404, "ResourceNotFound", f"The {kind} '{name}' was not found in workspace '{ws}'.")


def _workspaces(state):
    return [r for r in state.values() if str(r.get("_type", "")).lower() == WS_TYPE.lower()]


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


def _key(seed):
    return base64.b64encode(hashlib.sha512(seed.encode()).digest()).decode()


# ═══════════════════════════ workspace properties ════════════════════════════════
def _workspace_props(props, old=None, name=""):
    """Validate ``props`` (merged over ``old`` for PATCH) and return the stored workspace properties."""
    o = old or {}
    out = dict(o)
    sku_in = props.get("sku")
    if sku_in is not None:
        if not isinstance(sku_in, dict):
            raise _bad("The property 'sku' must be an object.")
        sku = {"name": _enum(sku_in.get("name", "PerGB2018"), "sku.name", SKUS)}
        if sku["name"] == "CapacityReservation":
            cap = _int(sku_in.get("capacityReservationLevel", 100), "sku.capacityReservationLevel", 100, 50000)
            if cap not in CAPACITY_LEVELS:
                raise _bad(f"The property 'sku.capacityReservationLevel' must be one of {', '.join(map(str, CAPACITY_LEVELS))}.")
            sku["capacityReservationLevel"] = cap
        sku["lastSkuUpdate"] = _now()
        out["sku"] = sku
    elif "sku" not in out:
        out["sku"] = {"name": "PerGB2018", "lastSkuUpdate": _now()}
    sku_name = out["sku"]["name"]
    if "retentionInDays" in props and props["retentionInDays"] is not None:
        if sku_name == "Free":
            if int(props["retentionInDays"]) != 7:
                raise _bad("The Free pricing tier does not support changing retentionInDays (fixed at 7 days).")
            out["retentionInDays"] = 7
        else:
            out["retentionInDays"] = _int(props["retentionInDays"], "retentionInDays", 4, 730)
    elif "retentionInDays" not in out:
        out["retentionInDays"] = 7 if sku_name == "Free" else 30
    if "workspaceCapping" in props and props["workspaceCapping"] is not None:
        cap_in = props["workspaceCapping"]
        if not isinstance(cap_in, dict):
            raise _bad("The property 'workspaceCapping' must be an object.")
        try:
            gb = float(cap_in.get("dailyQuotaGb", -1))
        except (TypeError, ValueError):
            raise _bad("The property 'workspaceCapping.dailyQuotaGb' must be a number.")
        if gb != -1 and gb < 0.023:
            raise _bad("The property 'workspaceCapping.dailyQuotaGb' must be -1 (no limit) or at least 0.023.")
        out["workspaceCapping"] = {"dailyQuotaGb": gb, "quotaNextResetTime": _now(1),
                                   "dataIngestionStatus": "RespectQuota"}
    elif "workspaceCapping" not in out:
        out["workspaceCapping"] = {"dailyQuotaGb": -1.0, "quotaNextResetTime": _now(1), "dataIngestionStatus": "RespectQuota"}
    for f in ("publicNetworkAccessForIngestion", "publicNetworkAccessForQuery"):
        if props.get(f) is not None:
            out[f] = _enum(props[f], f, ACCESS)
        else:
            out.setdefault(f, "Enabled")
    feat_in = props.get("features")
    if feat_in is not None:
        if not isinstance(feat_in, dict):
            raise _bad("The property 'features' must be an object.")
        feat = dict(o.get("features") or {})
        feat.update(feat_in)
        out["features"] = feat
    else:
        out.setdefault("features", {"enableLogAccessUsingOnlyResourcePermissions": True})
    if props.get("forceCmkForQuery") is not None:
        out["forceCmkForQuery"] = bool(props["forceCmkForQuery"])
    out.setdefault("customerId", str(uuid.uuid5(uuid.NAMESPACE_URL, name.lower() + "/" + uuid.uuid4().hex)))
    out.setdefault("createdDate", _now())
    out["modifiedDate"] = _now()
    out["provisioningState"] = "Succeeded"
    out.setdefault("privateLinkScopedResources", [])
    return out


def _new_tables(retention):
    return {n.lower(): _table_record(n, cols, retention, "Microsoft") for n, cols in BASE_TABLES.items()}


def _table_record(name, cols, retention, source, plan="Analytics", total=None, desc=None):
    return {"name": name, "type": f"{WS_TYPE}/tables", "properties": {
        "retentionInDays": retention, "totalRetentionInDays": total if total is not None else retention,
        "archiveRetentionInDays": max(0, (total if total is not None else retention) - retention),
        "plan": plan, "lastPlanModifiedDate": _now(), "retentionInDaysAsDefault": True, "totalRetentionInDaysAsDefault": True,
        "schema": {"name": name, "tableType": "Microsoft" if source == "Microsoft" else "CustomLog", "description": desc or f"{name} table",
                   "columns": [{"name": c, "type": "datetime" if c == "TimeGenerated" else "string", "displayName": c} for c in cols],
                   "standardColumns": [], "solutions": ["LogManagement"], "isTroubleshootingAllowed": False, "source": source},
        "provisioningState": "Succeeded"}}


# ═══════════════════════════ workspace CRUD ══════════════════════════════════════
def _put_workspace(state, sub, rg, name, payload, method, query):
    if not _WS_NAME.match(name or ""):
        raise _bad(f"The workspace name '{name}' is invalid. Names must be 4-63 characters of letters, digits and hyphens, "
                   "and start and end with a letter or digit.")
    rid = _ws_rid(sub, rg, name)
    rec = state.get(rid.lower())
    props_in = payload.get("properties")
    if props_in is not None and not isinstance(props_in, dict):
        raise _bad("The property 'properties' must be an object.")
    if method == "PATCH":
        if rec is None:
            raise _not_found(name, rg)
        rec["properties"] = _workspace_props(props_in or {}, rec["properties"], name)
        if isinstance(payload.get("tags"), dict):
            rec["tags"] = dict(payload["tags"])
        rec["etag"] = _etag()
        rec["properties"].pop("etag", None)
        return rec, False
    if not payload.get("location") and rec is None:
        raise _bad("The 'location' property is required when creating a workspace.")
    if rec is None:
        if any(r["name"].lower() == name.lower() and r.get("_sub") == sub for r in _workspaces(state)):
            raise _E(409, "Conflict", f"Workspace name '{name}' is not unique within the subscription.")
        props = _workspace_props(props_in or {}, None, name)
        rec = {"id": rid, "name": name, "type": WS_TYPE, "location": payload["location"], "tags": dict(payload.get("tags") or {}),
               "etag": _etag(), "properties": props, "_type": WS_TYPE, "_sub": sub, "_rg": rg,
               "_saved": {}, "_tables": _new_tables(props["retentionInDays"]), "_ds": {},
               "_packs": {p: True for p in ("LogManagement",)},
               "_keys": {"primary": _key(rid + "/primary"), "secondary": _key(rid + "/secondary")}}
        state[rid.lower()] = rec
        return rec, True
    rec["properties"] = _workspace_props(props_in or {}, rec["properties"], name)
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = dict(payload["tags"])
    if payload.get("location"):
        rec["location"] = payload["location"]
    rec["etag"] = _etag()
    return rec, False


def _list(state, sub, rg):
    items = [r for r in _workspaces(state) if r.get("_sub") == sub and (rg is None or (r.get("_rg") or "").lower() == rg.lower())]
    items.sort(key=lambda r: (r["name"].lower(), r["id"].lower()))
    return _ok({"value": [_view(r) for r in items]})


# ═══════════════════════════ workspace operations ════════════════════════════════
def _usages(rec):
    p = rec["properties"]
    cap = p["workspaceCapping"]["dailyQuotaGb"]
    reset = p["workspaceCapping"]["quotaNextResetTime"]
    n = len(rec["_tables"])
    return {"value": [
        {"name": {"value": "DataAnalyzed", "localizedValue": "Data Analyzed"}, "unit": "Bytes", "currentValue": float(rec.get("_ingest", {}).get(_today(), 0)),
         "limit": 524288000.0 if p["sku"]["name"] == "Free" else (-1.0 if cap == -1 else cap * 1073741824.0),
         "nextResetTime": reset, "quotaPeriod": "P1D"},
        {"name": {"value": "TableCount", "localizedValue": "Tables"}, "unit": "Count", "currentValue": float(n),
         "limit": float(MAX_TABLES), "nextResetTime": reset, "quotaPeriod": "P1D"},
        {"name": {"value": "SavedSearchCount", "localizedValue": "Saved searches"}, "unit": "Count",
         "currentValue": float(len(rec["_saved"])), "limit": float(MAX_SAVED), "nextResetTime": reset, "quotaPeriod": "P1D"},
    ]}


def _pack_view(rec):
    return [{"name": p, "enabled": bool(rec["_packs"].get(p, False))} for p in PACKS]


def _workspace_ops(state, sub, rec, rest, method, payload):
    op = rest[0].lower()
    if op in ("sharedkeys", "getsharedkeys"):
        if method != "POST":
            return _err(405, "MethodNotAllowed", "POST required.")
        return _ok({"primarySharedKey": rec["_keys"]["primary"], "secondarySharedKey": rec["_keys"]["secondary"]})
    if op == "regeneratesharedkey":
        if method != "POST":
            return _err(405, "MethodNotAllowed", "POST required.")
        which = _enum((payload or {}).get("name", "primary"), "name", ("primary", "secondary")).lower()
        rec["_keys"][which] = _key(rec["id"] + "/" + which + "/" + uuid.uuid4().hex)
        return _ok({"primarySharedKey": rec["_keys"]["primary"], "secondarySharedKey": rec["_keys"]["secondary"]})
    if op == "usages":
        return _ok(_usages(rec)) if method == "GET" else _err(405, "MethodNotAllowed", "GET required.")
    if op == "intelligencepacks":
        if len(rest) == 1:
            return _ok(_pack_view(rec)) if method == "GET" else _err(405, "MethodNotAllowed", "GET required.")
        if len(rest) == 3 and method == "POST" and rest[2].lower() in ("enable", "disable"):
            pack = next((p for p in PACKS if p.lower() == rest[1].lower()), None)
            if pack is None:
                raise _E(404, "NotFound", f"Intelligence pack '{rest[1]}' was not found.")
            if rest[2].lower() == "disable":
                if pack in ALWAYS_ON_PACKS:
                    raise _bad(f"The intelligence pack '{pack}' cannot be disabled.")
                rec["_packs"].pop(pack, None)
            else:
                rec["_packs"][pack] = True
            return _ok(None, 200)
    if op == "api" and len(rest) == 2 and rest[1].lower() == "query":
        return _run_query(state, sub, rec, method, payload)
    if op == "purge" and len(rest) == 1:
        return _purge(rec, method, payload)
    if op == "operations" and len(rest) == 2:
        return _purge_status(rec, method, rest[1])
    return _err(404, "ResourceTypeNotSupported", f"The resource type '{WS_TYPE}/{'/'.join(rest)}' is not supported.")


# ═══════════════════════════ logs query (KQL subset) ═════════════════════════════
# A small, real subset of KQL — enough to prove a genuine query engine runs over real data,
# never enough to silently accept syntax it does not understand (unsupported ops/operators
# raise the same ARM-shaped error every other validation failure in this module does).
def _default_col_type(name):
    return "datetime" if name == "TimeGenerated" else "string"


def _table_schema(rec, table):
    """[(column name, KQL type)] for `table` in this workspace, or None if unknown."""
    low = table.lower()
    if low in BASE_TABLES_LOWER:
        return [(c, _default_col_type(c)) for c in BASE_TABLES[BASE_TABLES_LOWER[low]]]
    t = rec["_tables"].get(low)
    if t is not None:
        return [(c["name"], _ARM_TO_KQL_TYPE.get(c.get("type", "string"), "string")) for c in t["properties"]["schema"]["columns"]]
    return None


def _activity_rows(state, sub):
    """AzureActivity rows: the real Microsoft.Insights/eventtypes feed this subscription's
    Activity log page reads, reshaped to [TimeGenerated, OperationName, Caller, Level,
    ResourceGroup, ResourceId] (BASE_TABLES["AzureActivity"])."""
    events = [r for r in state.values()
              if str(r.get("_type", "")).lower() == "microsoft.insights/eventtypes" and r.get("_sub") == sub]
    events.sort(key=lambda e: (e.get("eventTimestamp") or "", e.get("_seq", 0)), reverse=True)
    rows = []
    for e in events:
        op = e.get("operationName")
        op = op.get("value") if isinstance(op, dict) else op
        st = e.get("status")
        rows.append([e.get("eventTimestamp"), op, e.get("caller"), e.get("level"), e.get("resourceGroupName"), e.get("resourceId"),
                     (e.get("category") or {}).get("value") if isinstance(e.get("category"), dict) else (e.get("category") or "Administrative"),
                     st.get("value") if isinstance(st, dict) else st, e.get("subscriptionId") or sub])
    return rows


def activity_table(state, sub):
    """AzureActivity as row dicts, the shape run_kql consumes."""
    names = BASE_TABLES["AzureActivity"]
    return [dict(zip(names, r)) for r in _activity_rows(state, sub)]


def _col_index(schema, name):
    for i, (n, _) in enumerate(schema):
        if n.lower() == name.lower():
            return i
    raise _bad(f"The name '{name}' does not refer to any column, table, variable or function.")


def _apply_op(seg, schema, rows):
    seg = seg.strip()
    low = seg.lower()
    m = re.match(r"^where\s+(\w+)\s*(==|!=|contains|startswith)\s*(.+)$", seg, re.I)
    if m:
        col, op, val = m.group(1), m.group(2).lower(), m.group(3).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        idx = _col_index(schema, col)

        def keep(r, _op=op, _val=val, _idx=idx):
            cell = "" if r[_idx] is None else str(r[_idx])
            if _op == "==":
                return cell.lower() == _val.lower()
            if _op == "!=":
                return cell.lower() != _val.lower()
            if _op == "contains":
                return _val.lower() in cell.lower()
            return cell.lower().startswith(_val.lower())   # startswith
        return schema, [r for r in rows if keep(r)]
    if low.startswith("project "):
        names = [c.strip() for c in seg[len("project "):].split(",") if c.strip()]
        if not names:
            raise _bad("The 'project' operator needs at least one column name.")
        idxs = [_col_index(schema, n) for n in names]
        new_schema = [schema[i] for i in idxs]
        return new_schema, [[r[i] for i in idxs] for r in rows]
    m = re.match(r"^(?:sort by|order by)\s+(\w+)(?:\s+(asc|desc))?$", seg, re.I)
    if m:
        idx = _col_index(schema, m.group(1))
        desc = (m.group(2) or "desc").lower() != "asc"
        return schema, sorted(rows, key=lambda r: (r[idx] is None, r[idx]), reverse=desc)
    m = re.match(r"^(?:take|limit)\s+(\d+)$", seg, re.I)
    if m:
        return schema, rows[: int(m.group(1))]
    if low == "count":
        return [("Count", "long")], [[len(rows)]]
    raise _bad(f"Unsupported query operator: '{seg}'. Vyomi's KQL subset understands "
               "where (==/!=/contains/startswith), project, sort by/order by, take/limit and count.")


def _execute_kql(query, state, sub, rec):
    parts = [p.strip() for p in query.split("|")]
    table = parts[0] if parts else ""
    if not table or not re.fullmatch(r"[A-Za-z_]\w{0,63}", table):
        raise _bad("A query must start with a table name.")
    schema = _table_schema(rec, table)
    if schema is None:
        raise _bad(f"'{table}' does not refer to any known table, tabular variable or function.")
    rows = _activity_rows(state, sub) if table.lower() == "azureactivity" else []
    for seg in parts[1:]:
        if not seg:
            raise _bad("A query cannot contain an empty pipe stage.")
        schema, rows = _apply_op(seg, schema, rows)
    return schema, rows


def _run_query(state, sub, rec, method, payload):
    if method != "POST":
        return _err(405, "MethodNotAllowed", "POST required.")
    q = (payload or {}).get("query")
    if not isinstance(q, str) or not q.strip():
        return _err(400, "BadRequest", "The property 'query' is required.")
    try:
        schema, rows = _execute_kql(q, state, sub, rec)
    except _E as e:
        return _err(e.status, e.code, e.message)
    return _ok({"tables": [{"name": "PrimaryResult",
                            "columns": [{"name": n, "type": t} for n, t in schema], "rows": rows}]})


# ═══════════════════════════ saved searches ══════════════════════════════════════
def _child_id(rec, coll, name):
    return f"{rec['id']}/{coll}/{name}"


def _check_child_name(name, what):
    if not name or len(name) > 260 or _BAD_ID.search(name):
        raise _bad(f"The {what} id '{name}' is invalid. It must be 1-260 characters and cannot contain any of < > * % & : \\ ? + / #.")


def _saved_search(rec, name, payload, existing):
    p = payload.get("properties")
    if not isinstance(p, dict):
        raise _bad("The request body must contain 'properties'.")
    props = dict((existing or {}).get("properties") or {})
    for f in ("category", "displayName", "query"):
        if p.get(f) is not None:
            props[f] = _str(p[f], f)
        elif f not in props:
            raise _bad(f"The property '{f}' is required.")
    if p.get("version") is not None:
        props["version"] = _int(p["version"], "version", 1, 2)
    else:
        props.setdefault("version", 2)
    if p.get("functionAlias") is not None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(p["functionAlias"])):
            raise _bad("The property 'functionAlias' must be a valid identifier.")
        props["functionAlias"] = p["functionAlias"]
    if p.get("functionParameters") is not None:
        props["functionParameters"] = str(p["functionParameters"])
    if p.get("tags") is not None:
        tags = p["tags"]
        if not isinstance(tags, list) or any(not isinstance(t, dict) or "name" not in t or "value" not in t for t in tags):
            raise _bad("The property 'tags' must be a list of {name, value} objects.")
        props["tags"] = tags
    props.setdefault("tags", [])
    return {"id": _child_id(rec, "savedSearches", name), "name": name, "type": f"{WS_TYPE}/savedSearches",
            "etag": _etag(), "properties": props}


def _collection(rec, coll, name, method, payload, query):
    low = coll.lower()
    if low == "savedsearches":
        store, label = rec["_saved"], "saved search"
    elif low == "tables":
        store, label = rec["_tables"], "table"
    else:
        store, label = rec["_ds"], "data source"
    if name is None:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = sorted(store.values(), key=lambda r: r["name"].lower())
        if low == "datasources":
            flt = (query.get("$filter") or "").strip()
            m = re.fullmatch(r"kind\s+eq\s+'([^']+)'", flt, re.I)
            if not m:
                raise _bad("A $filter of the form \"kind eq '<DataSourceKind>'\" is required when listing data sources.")
            items = [r for r in items if r["kind"].lower() == m.group(1).lower()]
        return _ok({"value": [_child_view(rec, low, r) for r in items]})
    key = name.lower()
    cur = store.get(key)
    if method == "GET":
        if cur is None:
            raise _child_not_found(label, name, rec["name"])
        return _ok(_child_view(rec, low, cur))
    if method == "DELETE":
        if low == "tables":
            if cur is None:
                raise _child_not_found(label, name, rec["name"])
            if not _CUSTOM_TABLE.match(cur["name"]):
                raise _bad(f"Only custom tables (names ending in _CL or _RST) can be deleted; '{name}' is a built-in table.")
        store.pop(key, None)
        return _ok(None, 200 if cur is not None else 204)
    if method in ("PUT", "PATCH"):
        if low == "savedsearches":
            _check_child_name(name, "saved search")
            if cur is None and len(store) >= MAX_SAVED:
                raise _E(409, "Conflict", f"A workspace can hold at most {MAX_SAVED} saved searches.")
            new = _saved_search(rec, name, payload, cur)
            store[key] = new
            return _ok(_child_view(rec, low, new), 200)
        if low == "tables":
            return _put_table(rec, store, name, cur, payload, method)
        return _put_data_source(rec, store, name, cur, payload)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _child_view(rec, low, r):
    out = {k: v for k, v in r.items() if not k.startswith("_")}
    if low == "tables":
        out["id"] = _child_id(rec, "tables", r["name"])
    return out


def _put_table(rec, store, name, cur, payload, method):
    p = payload.get("properties")
    if not isinstance(p, dict):
        raise _bad("The request body must contain 'properties'.")
    ws_ret = rec["properties"]["retentionInDays"]
    if cur is None:
        if method == "PATCH":
            raise _child_not_found("table", name, rec["name"])
        if not _CUSTOM_TABLE.match(name):
            raise _bad(f"The table name '{name}' is invalid. Custom table names must end in _CL (custom log) or _RST (restored logs).")
        if len(store) >= MAX_TABLES:
            raise _E(409, "Conflict", f"A workspace can hold at most {MAX_TABLES} tables.")
        sch = p.get("schema")
        if not isinstance(sch, dict) or not isinstance(sch.get("columns"), list) or not sch["columns"]:
            raise _bad("A custom table needs 'schema.columns' with at least one column.")
        names = [c.get("name") for c in sch["columns"] if isinstance(c, dict)]
        if len(names) != len(sch["columns"]) or any(not n for n in names) or "TimeGenerated" not in names:
            raise _bad("Every schema column needs a name and the schema must include a 'TimeGenerated' column.")
        if len({n.lower() for n in names}) != len(names):
            raise _bad("Schema column names must be unique.")
        rec_t = _table_record(name, [], ws_ret, "Customer", desc=sch.get("description"))
        rec_t["properties"]["schema"]["name"] = sch.get("name") or name
        rec_t["properties"]["schema"]["columns"] = [
            {"name": c["name"], "type": _enum(c.get("type", "string"), "schema.columns.type",
                                              ("string", "int", "long", "real", "boolean", "dateTime", "guid", "dynamic")),
             "displayName": c.get("displayName") or c["name"], "description": c.get("description")} for c in sch["columns"]]
        cur = store[name.lower()] = rec_t
    tp = cur["properties"]
    if p.get("retentionInDays") is not None:
        tp["retentionInDays"] = _int(p["retentionInDays"], "retentionInDays", 4, 730)
        tp["retentionInDaysAsDefault"] = False
    if p.get("totalRetentionInDays") is not None:
        tp["totalRetentionInDays"] = _int(p["totalRetentionInDays"], "totalRetentionInDays", 4, 4383)
        tp["totalRetentionInDaysAsDefault"] = False
    if tp["totalRetentionInDays"] < tp["retentionInDays"]:
        raise _bad("The property 'totalRetentionInDays' must not be smaller than 'retentionInDays'.")
    tp["archiveRetentionInDays"] = tp["totalRetentionInDays"] - tp["retentionInDays"]
    if p.get("plan") is not None:
        plan = _enum(p["plan"], "plan", TABLE_PLANS)
        if plan != tp["plan"]:
            tp["lastPlanModifiedDate"] = _now()
        tp["plan"] = plan
    return _ok(_child_view(rec, "tables", cur), 200)


def _put_data_source(rec, store, name, cur, payload):
    _check_child_name(name, "data source")
    kind = _enum(_str(payload.get("kind"), "kind"), "kind", DS_KINDS)
    p = payload.get("properties")
    if not isinstance(p, dict):
        raise _bad("The request body must contain 'properties'.")
    store[name.lower()] = {"id": _child_id(rec, "dataSources", name), "name": name, "type": f"{WS_TYPE}/dataSources",
                           "kind": kind, "etag": _etag(), "properties": p, "tags": dict(payload.get("tags") or {})}
    return _ok(_child_view(rec, "datasources", store[name.lower()]), 200)


# ═══════════════════════════ dispatch ════════════════════════════════════════════
_CTX = {"blob_store": None, "blob_mod": None, "state": None}


def dispatch(state, method, sub, rg, chain, names, payload=None, query=None, base="", blob_store=None, blob_mod=None):
    """Handle one ``Microsoft.OperationalInsights`` ARM request (``chain`` = tokens after the namespace).

    ``blob_store``/``blob_mod`` (optional) are the host's Azure Blob store + core: data export rules write the
    exported rows there as real blobs. Without them an export rule is stored but nothing can be written."""
    method = (method or "GET").upper()
    _CTX.update(blob_store=blob_store, blob_mod=blob_mod, state=state)
    payload = {"_array": payload} if isinstance(payload, list) else (payload if isinstance(payload, dict) else {})
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload, query or {})
    except _E as e:
        return _err(e.status, e.code, e.message)


def handles(chain):
    return bool(chain) and chain[0].lower() == "workspaces"


def _dispatch(state, method, sub, rg, chain, payload, query):
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list(state, sub, rg)
    name = chain[1]
    if rg is None:
        return _err(400, "InvalidResourceId", "workspaces must be addressed within a resource group.")
    rid = _ws_rid(sub, rg, name)
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:
        if rec is None:
            raise _not_found(name, rg)
        head = rest[0].lower()
        if head in ("api", "query", "datacollectionrules"):
            _lr = [x.lower() for x in rest]
            try:
                from core import azure_netaccess as _na
            except ImportError:  # pragma: no cover - Pyodide flat layout
                import azure_netaccess as _na  # type: ignore
            # azure.loganalytics.workspace.networking: publicNetworkAccessForQuery / ForIngestion (+ a private endpoint
            # path) enforced on the data plane against the declared caller (x-vyomi-* headers or same-named query params)
            _d = _na.loganalytics_denied(state, rec, "query" if _lr in (["api", "query"], ["query"]) else "ingestion", None, query)
            if _d:
                return _err(403, "InsufficientAccessError", "The workspace's network configuration blocks this request: " + _d[2])
            if _lr == ["api", "query"] and method != "POST" and not (query or {}).get("query"):
                return _err(405, "MethodNotAllowed", "POST required.")
            if _lr in (["api", "query"], ["query"]):
                # AzureActivity is the real Microsoft.Insights/eventtypes feed (the Activity log): it lives in the
                # ARM state map, so it is injected as a table for the single KQL engine (run_kql) to query.
                return _data_plane(rec, rest, method, payload, query, extra={"AzureActivity": activity_table(state, sub)})
            return _data_plane(rec, rest, method, payload, query)
        if head == "dataexports":
            if len(rest) > 2:
                return _err(404, "ResourceTypeNotSupported", f"The resource type '{WS_TYPE}/{'/'.join(rest)}' is not supported.")
            return _data_exports(rec, rest[1] if len(rest) == 2 else None, method, payload)
        if head in ("savedsearches", "tables", "datasources"):
            if len(rest) > 2:
                return _err(404, "ResourceTypeNotSupported", f"The resource type '{WS_TYPE}/{'/'.join(rest)}' is not supported.")
            return _collection(rec, rest[0], rest[1] if len(rest) == 2 else None, method, payload, query)
        return _workspace_ops(state, sub, rec, rest, method, payload)
    if method == "GET":
        if rec is None:
            raise _not_found(name, rg)
        return _ok(_view(rec))
    if method in ("PUT", "PATCH"):
        rec, created = _put_workspace(state, sub, rg, name, payload, method, query)
        return _ok(_view(rec), 201 if created else 200, lro=created, rid=rid, verb=method.lower())
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        state.pop(rid.lower(), None)
        return _ok(None, 200, lro=True, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def resource_types():
    return [("workspaces", API_VERSION)]


# ═══════════════════════ data plane: ingest + KQL subset ═════════════════════════
MAX_ROWS = 50000


def _bad_arg(msg, code="BadArgumentError"):
    return _err(400, code, msg)


def _data_plane(rec, rest, method, payload, query, extra=None):
    low = [x.lower() for x in rest]
    try:
        if low[:2] == ["api", "logs"] and method == "POST":
            return _ingest_collector(rec, payload, query)
        if low[0] == "datacollectionrules" and len(rest) >= 4 and low[2] == "streams" and method == "POST":
            return _ingest_dcr(rec, rest[3], payload)
        if low == ["api", "query"] or low == ["query"]:
            q = payload.get("query") if method == "POST" else query.get("query")
            if not q and method == "POST":
                q = query.get("query")
            if not isinstance(q, str) or not q.strip():
                return _bad_arg("The request had some invalid properties: query is required.", "BadArgumentError")
            return _ok(run_kql(rec, q, extra))
    except KqlError as e:
        return _bad_arg(str(e), "SemanticError" if e.semantic else "SyntaxError")
    return _err(404, "ResourceTypeNotSupported", f"The resource type '{WS_TYPE}/{'/'.join(rest)}' is not supported.")


def _rows(rec):
    return rec.setdefault("_rows", {})


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _daily_limit_bytes(rec):
    p = rec["properties"]
    if p["sku"]["name"] == "Free":
        return 524288000
    cap = p["workspaceCapping"]["dailyQuotaGb"]
    return None if cap == -1 else int(cap * 1073741824)


def _store(rec, table, rows):
    # Real ingestion volume: bytes accepted today feed the Usage blade; once the daily cap is reached the
    # service silently drops further data until the next reset (it does not error the sender).
    size = len(json.dumps(rows, default=str).encode())
    ing = rec.setdefault("_ingest", {})
    lim = _daily_limit_bytes(rec)
    if lim is not None and ing.get(_today(), 0) >= lim:
        rec["_droppedBytes"] = rec.get("_droppedBytes", 0) + size
        return
    ing[_today()] = ing.get(_today(), 0) + size
    for k in sorted(ing)[:-35]:
        ing.pop(k, None)
    by = rec.setdefault("_ingestByTable", {}).setdefault(_today(), {})
    by[table] = by.get(table, 0) + size
    _export_rows(rec, table, rows)
    tbl = _rows(rec).setdefault(table, [])
    tbl.extend(rows)
    if len(tbl) > MAX_ROWS:
        del tbl[: len(tbl) - MAX_ROWS]
    if table.lower() not in rec.setdefault("_tables", {}):      # custom table appears in the tables list too
        cols = sorted({c for r in rows for c in r} | {"TimeGenerated"})
        rec["_tables"][table.lower()] = _table_record(table, cols, rec["properties"].get("retentionInDays", 30), "Customer")


def _ingest_collector(rec, payload, query):
    log_type = query.get("logType") or query.get("Log-Type") or query.get("log-type")
    if not log_type:
        return _bad_arg("Log-Type header (or logType query parameter) is required.", "InvalidRequest")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,100}", log_type):
        return _bad_arg("Log-Type may only contain letters, numbers and underscore (max 100).", "InvalidRequest")
    records = payload.get("_array") if "_array" in payload else [payload]
    if not isinstance(records, list) or not all(isinstance(x, dict) for x in records):
        return _bad_arg("The body must be a JSON object or an array of objects.", "InvalidRequest")
    tf = query.get("time-generated-field") or query.get("timeGeneratedField")
    out = []
    for r in records:
        row = {"TimeGenerated": _now()}
        for k, v in r.items():
            if tf and k == tf and isinstance(v, str):
                row["TimeGenerated"] = v
                continue
            suffix = "_b" if isinstance(v, bool) else "_d" if isinstance(v, (int, float)) else "_s"
            if isinstance(v, (dict, list)):
                v = json.dumps(v)
            row[re.sub(r"[^A-Za-z0-9_]", "_", k) + suffix] = v
        out.append(row)
    _store(rec, log_type + "_CL", out)
    return {"status": 200, "headers": {}, "body": None, "lro": False, "rid": "", "verb": ""}


def _ingest_dcr(rec, stream, payload):
    records = payload.get("_array")
    if not isinstance(records, list) or not all(isinstance(x, dict) for x in records):
        return _bad_arg("The body must be a JSON array of objects.", "InvalidRequest")
    table = stream[len("Custom-"):] if stream.lower().startswith("custom-") else stream
    out = []
    for r in records:
        row = dict(r)
        row.setdefault("TimeGenerated", _now())
        out.append(row)
    _store(rec, table, out)
    return {"status": 204, "headers": {}, "body": None, "lro": False, "rid": "", "verb": ""}


# ═══════════════════════ data export rules (real blob writes) ════════════════════
MAX_EXPORT_RULES = 10
_EXPORT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{2,62}[A-Za-z0-9]$")
_SA_ID = re.compile(r"^/subscriptions/[^/]+/resourcegroups/[^/]+/providers/microsoft\.storage/storageaccounts/([a-z0-9]{3,24})$", re.I)


def _export_view(rec, r):
    out = {k: v for k, v in r.items() if not k.startswith("_")}
    out["id"] = _child_id(rec, "dataExports", r["name"])
    return out


def _known_table(rec, t):
    return t.lower() in BASE_TABLES_LOWER or t.lower() in rec["_tables"]


def _data_exports(rec, name, method, payload):
    store = rec.setdefault("_exports", {})
    if name is None:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_export_view(rec, r) for r in sorted(store.values(), key=lambda r: r["name"].lower())]})
    key, cur = name.lower(), store.get(name.lower())
    if method == "GET":
        if cur is None:
            raise _child_not_found("data export", name, rec["name"])
        return _ok(_export_view(rec, cur))
    if method == "DELETE":
        if cur is None:
            raise _child_not_found("data export", name, rec["name"])
        store.pop(key)
        return _ok(None, 200)
    if method != "PUT":
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if not _EXPORT_NAME.match(name):
        raise _bad(f"The data export rule name '{name}' is invalid. It must be 4-63 characters: letters, digits and '-', starting and ending with a letter or digit.")
    p = payload.get("properties")
    if not isinstance(p, dict):
        raise _bad("The request body must contain 'properties'.")
    tables = p.get("tableNames")
    if not isinstance(tables, list) or not tables or any(not isinstance(t, str) for t in tables):
        raise _bad("The property 'tableNames' must be a non-empty list of table names.")
    canon = []
    for t in tables:
        if not _known_table(rec, t):
            raise _bad(f"Table '{t}' does not exist in the workspace '{rec['name']}' and cannot be exported.")
        canon.append(BASE_TABLES_LOWER[t.lower()] if t.lower() in BASE_TABLES_LOWER else rec["_tables"][t.lower()]["name"])
    dest = p.get("destination") or {}
    rid = dest.get("resourceId") or p.get("resourceId")
    if not isinstance(rid, str) or not rid:
        raise _bad("The property 'destination.resourceId' is required.")
    m = _SA_ID.match(rid)
    if not m:
        if "microsoft.eventhub" in rid.lower():
            raise _bad("Event Hub export destinations are not supported by Vyomi; use a Storage account.")
        raise _bad("The destination must be a Microsoft.Storage/storageAccounts resource id.")
    state = _CTX.get("state") or {}
    if rid.lower() not in state:
        raise _E(400, "InvalidDestination", f"The destination storage account '{m.group(1)}' was not found.")
    enable = bool(p.get("enable", True))
    if cur is None and len(store) >= MAX_EXPORT_RULES:
        raise _E(409, "Conflict", f"A workspace can hold at most {MAX_EXPORT_RULES} data export rules.")
    if enable:
        for other in store.values():
            if other["name"].lower() != key and other["properties"].get("enable") and \
                    {t.lower() for t in other["properties"]["tableNames"]} & {t.lower() for t in canon}:
                raise _E(409, "Conflict", f"One or more tables are already exported by the enabled rule '{other['name']}'.")
    now = _now()
    props = {"dataExportId": (cur or {}).get("properties", {}).get("dataExportId") or str(uuid.uuid4()),
             "tableNames": canon, "destination": {"resourceId": rid, "type": "StorageAccount", "metaData": {}},
             "enable": enable, "createdDate": (cur or {}).get("properties", {}).get("createdDate") or now, "lastModifiedDate": now}
    new = {"id": _child_id(rec, "dataExports", name), "name": name, "type": f"{WS_TYPE}/dataexports",
           "etag": _etag(), "properties": props}
    store[key] = new
    return _ok(_export_view(rec, new), 200 if cur else 201)


def _export_rows(rec, table, rows):
    """Write freshly ingested rows to every enabled export rule's storage account, as the real service
    does: container ``am-<table>``, blob ``WorkspaceResourceId=<id>/y=…/m=…/d=…/h=…/m=…/PT05M.json``
    (one JSON record per line). Appends to the current 5-minute blob."""
    bs, bm = _CTX.get("blob_store"), _CTX.get("blob_mod")
    if bs is None or bm is None:
        return
    for rule in list((rec.get("_exports") or {}).values()):
        pr = rule["properties"]
        if not pr["enable"] or table.lower() not in {t.lower() for t in pr["tableNames"]}:
            continue
        try:
            acct = _SA_ID.match(pr["destination"]["resourceId"]).group(1).lower()
            cont = "am-" + table.lower().replace("_", "-")
            ck = f"{acct}/{cont}"
            if not bs.container_exists(ck):
                bs.create_container(ck)
            t = datetime.now(timezone.utc)
            blob = (f"WorkspaceResourceId={rec['id'].lower()}/y={t:%Y}/m={t:%m}/d={t:%d}/h={t:%H}/m={t.minute // 5 * 5:02d}/PT05M.json")
            old = b""
            g = bm.dispatch(bs, "GET", f"/{cont}/{blob}", {}, {}, b"", account=acct)
            if g.status == 200:
                old = g.body if isinstance(g.body, bytes) else str(g.body).encode()
            lines = "".join(json.dumps({**r, "Type": table, "_ResourceId": rec["id"]}, default=str) + "\n" for r in rows).encode()
            r = bm.dispatch(bs, "PUT", f"/{cont}/{blob}", {}, {"x-ms-blob-type": "BlockBlob", "content-type": "application/json"}, old + lines, account=acct)
            if r.status >= 300:
                raise RuntimeError(r.status)
            rule["_rows"] = rule.get("_rows", 0) + len(rows)
        except Exception:
            rule["_failures"] = rule.get("_failures", 0) + 1


# ═══════════════════════ purge (really deletes rows) ═════════════════════════════
_PURGE_OPS = ("==", ">", "<", ">=", "<=", "in", "between")


def _purge(rec, method, payload):
    if method != "POST":
        return _err(405, "MethodNotAllowed", "POST required.")
    table = payload.get("table")
    if not isinstance(table, str) or not table:
        raise _bad_p("The 'table' property is required.")
    schema = _table_schema(rec, table)
    if schema is None:
        raise _bad_p(f"Table '{table}' was not found in the workspace.")
    filters = payload.get("filters")
    if not isinstance(filters, list) or not filters:
        raise _bad_p("At least one filter is required: a purge without filters is not allowed.")
    cols = {c.lower(): c for c, _ in schema}
    for f in filters:
        if not isinstance(f, dict) or str(f.get("column", "")).lower() not in cols:
            raise _bad_p(f"Filter column '{(f or {}).get('column')}' does not exist in table '{table}'.")
        if f.get("operator") not in _PURGE_OPS:
            raise _bad_p(f"Filter operator must be one of {', '.join(_PURGE_OPS)}.")
        if "value" not in f and "values" not in f:
            raise _bad_p("Each filter needs a 'value'.")

    def match(row):
        for f in filters:
            col = cols[f["column"].lower()]
            v, rhs, op = row.get(col), f.get("value", f.get("values")), f["operator"]
            if op == "in":
                if v not in (rhs if isinstance(rhs, list) else [rhs]):
                    return False
            elif op == "between":
                if not isinstance(rhs, list) or len(rhs) != 2 or v is None or not (str(rhs[0]) <= str(v) <= str(rhs[1])):
                    return False
            elif v is None or not _cmp(v, op, rhs):
                return False
        return True

    real = next((t for t in _rows(rec) if t.lower() == table.lower()), None)
    before = _rows(rec).get(real, []) if real else []
    keep = [r for r in before if not match(r)]
    removed = len(before) - len(keep)
    if real:
        _rows(rec)[real] = keep
    oid = "purge-" + uuid.uuid4().hex
    rec.setdefault("_purges", {})[oid] = {"status": "completed", "table": table, "rowsPurged": removed, "completed": _now()}
    return _ok({"operationId": oid}, 202, headers={"x-ms-status-location": f"{rec['id']}/operations/{oid}"})


def _bad_p(msg):
    return _E(400, "BadRequest", msg)


def _purge_status(rec, method, oid):
    if method != "GET":
        return _err(405, "MethodNotAllowed", "GET required.")
    op = (rec.get("_purges") or {}).get(oid)
    if op is None:
        raise _E(404, "NotFound", f"Purge operation '{oid}' was not found.")
    return _ok({"status": op["status"]})


class KqlError(Exception):
    def __init__(self, msg, semantic=False):
        super().__init__(msg)
        self.semantic = semantic


def _split_top(text, sep):
    """Split on `sep` outside quotes/parentheses."""
    out, cur, depth, q = [], [], 0, None
    i = 0
    while i < len(text):
        ch = text[i]
        if q:
            cur.append(ch)
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
            cur.append(ch)
        elif ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif depth == 0 and text.startswith(sep, i):
            out.append("".join(cur))
            cur = []
            i += len(sep)
            continue
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [x.strip() for x in out]


def _split_bool(text):
    """`a and b or c` -> [[a,b],[c]] (OR of ANDs), split outside quotes/parens."""
    toks, cur, depth, q, i = [], [], 0, None, 0
    ors = []
    ands = []
    buf = ""
    while i < len(text):
        ch = text[i]
        if q:
            buf += ch
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
            buf += ch
        elif ch == "(":
            depth += 1
            buf += ch
        elif ch == ")":
            depth -= 1
            buf += ch
        elif depth == 0 and re.match(r"\s+and\s+", text[i:], re.I):
            ands.append(buf.strip())
            buf = ""
            i += re.match(r"\s+and\s+", text[i:], re.I).end()
            continue
        elif depth == 0 and re.match(r"\s+or\s+", text[i:], re.I):
            ands.append(buf.strip())
            ors.append(ands)
            ands, buf = [], ""
            i += re.match(r"\s+or\s+", text[i:], re.I).end()
            continue
        else:
            buf += ch
        i += 1
    ands.append(buf.strip())
    ors.append(ands)
    return ors


_OPS = ["!contains", "contains", "!startswith", "startswith", "!endswith", "endswith", "!has", "has", "in", "==", "!=", "=~", ">=", "<=", ">", "<"]


def _literal(tok):
    tok = tok.strip()
    if (len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "'\""):
        return tok[1:-1]
    m = re.fullmatch(r"ago\((\d+(?:\.\d+)?)([smhd])\)", tok, re.I)
    if m:
        secs = float(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2).lower()]
        return (datetime.now(timezone.utc) - timedelta(seconds=secs)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if tok.lower() in ("true", "false"):
        return tok.lower() == "true"
    try:
        return int(tok) if re.fullmatch(r"-?\d+", tok) else float(tok)
    except ValueError:
        raise KqlError(f"Unrecognised literal '{tok}'")


def _parse_pred(text):
    m = re.fullmatch(r"\(?\s*(.*?)\s*\)?", text.strip())
    text = m.group(1) if m and text.strip().startswith("(") and text.strip().endswith(")") else text.strip()
    ops_re = r"^([A-Za-z_][A-Za-z0-9_]*)\s*(" + "|".join(re.escape(o) + (r"(?=[\s(])" if o[-1].isalpha() else "") for o in _OPS) + r")\s*(.+)$"
    m = re.match(ops_re, text, re.S)
    if not m:
        raise KqlError(f"Failed to parse predicate '{text}'")
    col, op, rhs = m.group(1), m.group(2), m.group(3).strip()
    if op == "in":
        inner = re.fullmatch(r"\((.*)\)", rhs, re.S)
        if not inner:
            raise KqlError("'in' requires a parenthesised list")
        return col, op, [_literal(x) for x in _split_top(inner.group(1), ",")]
    return col, op, _literal(rhs)


def _cmp(val, op, rhs):
    if val is None:
        return op in ("!=", "!contains", "!has", "!startswith", "!endswith")
    if op == "in":
        return val in rhs or str(val) in [str(x) for x in rhs]
    neg = op.startswith("!") and op != "!="
    base = op[1:] if neg else op
    if base in ("contains", "has", "startswith", "endswith"):
        a, b = str(val).lower(), str(rhs).lower()
        r = {"contains": b in a, "has": re.search(r"(?<![A-Za-z0-9_])" + re.escape(b) + r"(?![A-Za-z0-9_])", a) is not None,
             "startswith": a.startswith(b), "endswith": a.endswith(b)}[base]
        return (not r) if neg else r
    if op == "=~":
        return str(val).lower() == str(rhs).lower()
    a, b = val, rhs
    if isinstance(b, (int, float)) and not isinstance(b, bool):
        try:
            a = float(a)
        except (TypeError, ValueError):
            return op == "!="
    elif isinstance(a, (int, float)) and not isinstance(a, bool):
        a, b = str(a), str(b)
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    try:
        return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]
    except TypeError:
        return False


def _coltype(v):
    return "bool" if isinstance(v, bool) else "long" if isinstance(v, int) else "real" if isinstance(v, float) else "string"


def _resolve_col(cols, name):
    for c in cols:
        if c.lower() == name.lower():
            return c
    raise KqlError(f"Failed to resolve scalar expression named '{name}'", semantic=True)


# ───────── KQL scalar expressions (extend / summarize / top / where fallback) ─────────
import ast as _ast
import math as _math

_DUR_RE = re.compile(r"^(\d+(?:\.\d+)?)(ms|s|m|h|d)$", re.I)


def _dur_secs(tok):
    m = _DUR_RE.match(str(tok).strip())
    if not m:
        raise KqlError(f"Unrecognised timespan '{tok}'")
    return float(m.group(1)) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2).lower()]


def _iso_dt(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _iso_str(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _fn_bin(v, size):
    size = _dur_secs(size) if isinstance(size, str) else float(size)
    d = _iso_dt(v)
    if d is not None and not isinstance(v, (int, float)):
        t = d.timestamp()
        return _iso_str(datetime.fromtimestamp(t - (t % size), timezone.utc))
    return None if v is None else _math.floor(float(v) / size) * size


def _fn_substring(s, start, n=None):
    s = "" if s is None else str(s)
    return s[start:] if n is None else s[start:start + n]


_KQL_FUNCS = {
    "strcat": lambda *a: "".join("" if x is None else str(x) for x in a),
    "tolower": lambda s: None if s is None else str(s).lower(), "toupper": lambda s: None if s is None else str(s).upper(),
    "tostring": lambda v: "" if v is None else str(v), "strlen": lambda s: len(str(s or "")),
    "toint": lambda v: int(float(v)), "tolong": lambda v: int(float(v)), "todouble": lambda v: float(v), "toreal": lambda v: float(v),
    "round": lambda v, n=0: round(float(v), int(n)), "floor": lambda v, n=1: _math.floor(float(v) / n) * n,
    "abs": lambda v: abs(v), "sqrt": lambda v: _math.sqrt(v), "log": lambda v: _math.log(v), "pow": lambda a, b: a ** b,
    "iff": lambda c, a, b: a if c else b, "iif": lambda c, a, b: a if c else b,
    "isnull": lambda v: v is None, "isnotnull": lambda v: v is not None,
    "isempty": lambda v: v is None or v == "", "isnotempty": lambda v: not (v is None or v == ""),
    "coalesce": lambda *a: next((x for x in a if x is not None and x != ""), None),
    "substring": _fn_substring, "bin": _fn_bin,
    "ago": lambda d: _iso_str(datetime.now(timezone.utc) - timedelta(seconds=_dur_secs(d))),
    "now": lambda: _iso_str(datetime.now(timezone.utc)),
    "datetime_diff": lambda unit, a, b: (_iso_dt(a) - _iso_dt(b)).total_seconds() / {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[str(unit)],
    "startofday": lambda v: _iso_str(_iso_dt(v).replace(hour=0, minute=0, second=0, microsecond=0)),
}


def _compile_expr(text):
    text = text.strip()
    # `x contains 'a'` style needs rewriting to a call; do it structurally before python parsing
    m = re.fullmatch(r"(.+?)\s+(!contains|contains|!startswith|startswith|!endswith|endswith|!has|has)\s+(.+)", text, re.S)
    if m and " and " not in text and " or " not in text:
        lhs, op, rhs = m.groups()
        return ("op", _compile_expr(lhs), op, _compile_expr(rhs))
    mm = re.fullmatch(r"(.+?)\s+in\s*\((.*)\)", text, re.S)
    if mm and " and " not in text and " or " not in text:
        return ("in", _compile_expr(mm.group(1)), [_compile_expr(x) for x in _split_top(mm.group(2), ",")])
    src = text.replace("=~", " ==ci ").replace("!~", " !=ci ")
    src = re.sub(r"\b(\d+(?:\.\d+)?(?:ms|s|m|h|d))\b", lambda x: repr(x.group(1)), src)
    src = re.sub(r"\bnull\b", "None", src, flags=re.I)
    src = re.sub(r"\btrue\b", "True", src, flags=re.I)
    src = re.sub(r"\bfalse\b", "False", src, flags=re.I)
    src = src.replace(" ==ci ", " == ").replace(" !=ci ", " != ")
    src = re.sub(r"\b(and|or|not)\b", lambda x: x.group(1).lower(), src, flags=re.I)
    try:
        tree = _ast.parse(src, mode="eval")
    except SyntaxError:
        raise KqlError(f"Failed to parse expression '{text}'")
    for node in _ast.walk(tree):
        if not isinstance(node, (_ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.Constant, _ast.Name, _ast.Call, _ast.Compare,
                                 _ast.BoolOp, _ast.IfExp, _ast.Load, _ast.operator, _ast.unaryop, _ast.cmpop, _ast.boolop)):
            raise KqlError(f"Unsupported expression '{text}'")
        if isinstance(node, _ast.Call) and not (isinstance(node.func, _ast.Name) and node.func.id.lower() in _KQL_FUNCS and not node.keywords):
            raise KqlError(f"Unknown function in '{text}'", semantic=True)
    return ("py", tree.body, text)


def _eval_node(node, row, cols):
    if isinstance(node, _ast.Constant):
        return node.value
    if isinstance(node, _ast.Name):
        return row.get(_resolve_col(cols, node.id))
    if isinstance(node, _ast.UnaryOp):
        v = _eval_node(node.operand, row, cols)
        return (not v) if isinstance(node.op, _ast.Not) else (None if v is None else (-v if isinstance(node.op, _ast.USub) else +v))
    if isinstance(node, _ast.BinOp):
        a, b = _eval_node(node.left, row, cols), _eval_node(node.right, row, cols)
        if a is None or b is None:
            return None
        if isinstance(node.op, _ast.Add) and (isinstance(a, str) or isinstance(b, str)):
            raise KqlError("Cannot add strings; use strcat()", semantic=True)
        try:
            return {_ast.Add: lambda: a + b, _ast.Sub: lambda: a - b, _ast.Mult: lambda: a * b,
                    _ast.Div: lambda: (a // b if isinstance(a, int) and isinstance(b, int) and a % b == 0 else a / b),
                    _ast.Mod: lambda: a % b}[type(node.op)]()
        except ZeroDivisionError:
            return None
    if isinstance(node, _ast.BoolOp):
        vals = (_eval_node(v, row, cols) for v in node.values)
        return all(vals) if isinstance(node.op, _ast.And) else any(vals)
    if isinstance(node, _ast.IfExp):
        return _eval_node(node.body if _eval_node(node.test, row, cols) else node.orelse, row, cols)
    if isinstance(node, _ast.Compare):
        left = _eval_node(node.left, row, cols)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval_node(comp, row, cols)
            o = {_ast.Eq: "==", _ast.NotEq: "!=", _ast.Gt: ">", _ast.Lt: "<", _ast.GtE: ">=", _ast.LtE: "<="}.get(type(op))
            if o is None or not _cmp(left, o, right):
                return False
            left = right
        return True
    if isinstance(node, _ast.Call):
        return _KQL_FUNCS[node.func.id.lower()](*[_eval_node(a, row, cols) for a in node.args])
    raise KqlError("Unsupported expression")


def _eval(compiled, row, cols):
    if compiled[0] == "py":
        return _eval_node(compiled[1], row, cols)
    if compiled[0] == "op":
        return _cmp(_eval(compiled[1], row, cols), compiled[2], _eval(compiled[3], row, cols))
    return any(_cmp(_eval(compiled[1], row, cols), "==", _eval(x, row, cols)) for x in compiled[2])


def _expr_name(text):
    m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)", text.strip(), re.S)
    if m and not text.strip().startswith(m.group(1) + "=="):
        return m.group(1), m.group(2)
    return None, text


_AGGS = ("count", "countif", "sum", "avg", "min", "max", "dcount", "sumif")


def _summarize(arg, rows, cols):
    by_txt = None
    parts = re.split(r"\s+by\s+", arg, maxsplit=1, flags=re.I)
    agg_txt = parts[0]
    if len(parts) == 2:
        by_txt = parts[1]
    aggs = []
    for a in _split_top(agg_txt, ","):
        if not a:
            continue
        name, body = _expr_name(a)
        m = re.fullmatch(r"([A-Za-z_]+)\((.*)\)", body.strip(), re.S)
        if not m or m.group(1).lower() not in _AGGS:
            raise KqlError(f"Unsupported summarize aggregate '{a}'. Supported: {', '.join(x + '()' for x in _AGGS)}.")
        fn, inner = m.group(1).lower(), m.group(2).strip()
        if fn in ("sum", "avg", "min", "max", "dcount", "countif", "sumif") and not inner:
            raise KqlError(f"{fn}() needs an argument", semantic=True)
        if not name:
            name = "count_" if fn == "count" else f"{fn}_{re.sub(r'[^A-Za-z0-9_]', '', inner.split(',')[0]) or 'x'}"
        sumif_cond = None
        if fn == "sumif":
            xs = _split_top(inner, ",")
            inner, sumif_cond = xs[0], _compile_expr(xs[1])
        aggs.append((name, fn, _compile_expr(inner) if inner else None, sumif_cond))
    keys = []
    if by_txt:
        for k in _split_top(by_txt, ","):
            name, body = _expr_name(k)
            if not name:
                bm = re.fullmatch(r"bin\(\s*([A-Za-z_]\w*)\s*,.*\)", body.strip(), re.I)
                name = bm.group(1) if bm else body.strip()
            keys.append((name, _compile_expr(body)))
    if not aggs:
        aggs = [("count_", "count", None, None)]
    groups = {}
    for r in rows:
        kv = tuple(_eval(c, r, cols) for _, c in keys)
        groups.setdefault(kv, []).append(r)
    if not keys and not groups:
        groups[()] = []
    out = []
    for kv, grp in groups.items():
        row = {n: v for (n, _), v in zip(keys, kv)}
        for name, fn, ex, cond in aggs:
            if fn == "count":
                row[name] = len(grp)
                continue
            if fn == "countif":
                row[name] = sum(1 for r in grp if _eval(ex, r, cols))
                continue
            vals = [_eval(ex, r, cols) for r in grp if cond is None or _eval(cond, r, cols)]
            vals = [v for v in vals if v is not None]
            nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if fn in ("sum", "sumif"):
                row[name] = sum(nums) if nums else 0
            elif fn == "avg":
                row[name] = (sum(nums) / len(nums)) if nums else None
            elif fn == "min":
                row[name] = min(vals) if vals else None
            elif fn == "max":
                row[name] = max(vals) if vals else None
            elif fn == "dcount":
                row[name] = len({str(v) for v in vals})
        out.append(row)
    return out, [n for n, _ in keys] + [a[0] for a in aggs]



def run_kql(rec, query, extra=None):
    stages = _split_top(query.strip().rstrip(";"), "|")
    head = stages[0]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", head):
        raise KqlError(f"Query must start with a table name, got '{head}'")
    store = dict(_rows(rec))
    for k, v in (extra or {}).items():      # state-derived tables (AzureActivity) live outside the workspace record
        store[k] = v
    tkey = next((k for k in list(store) + [t["name"] for t in rec.get("_tables", {}).values()] if k.lower() == head.lower()), None)
    if tkey is None and head.lower() in BASE_TABLES_LOWER:
        tkey = BASE_TABLES_LOWER[head.lower()]
    if tkey is None:
        raise KqlError(f"'{head}' : Failed to resolve table or column expression named '{head}'", semantic=True)
    rows = [dict(r) for r in store.get(tkey, [])]
    cols = []
    for r in rows:
        for c in r:
            if c not in cols:
                cols.append(c)
    if not cols:
        base = next((t for t in rec.get("_tables", {}).values() if t["name"].lower() == head.lower()), None)
        cols = [c["name"] for c in ((base or {}).get("properties", {}).get("schema", {}).get("columns") or [])] \
            or BASE_TABLES.get(BASE_TABLES_LOWER.get(head.lower(), ""), None) or ["TimeGenerated"]
    for stage in stages[1:]:
        m = re.match(r"([A-Za-z]+)\b\s*(.*)$", stage, re.S)
        if not m:
            raise KqlError(f"Unsupported operator in '{stage}'")
        op, arg = m.group(1).lower(), m.group(2).strip()
        if op == "where":
            try:
                groups = [[_parse_pred(a) for a in ands] for ands in _split_bool(arg)]
                for g in groups:
                    for col, _, _ in g:
                        _resolve_col(cols, col)
                rows = [r for r in rows if any(all(_cmp(r.get(_resolve_col(cols, c)), o, v) for c, o, v in g) for g in groups)]
            except KqlError as pe:
                if pe.semantic:
                    raise
                comp = _compile_expr(arg)      # general scalar expression (functions, arithmetic, parenthesised logic)
                rows = [r for r in rows if _eval(comp, r, cols)]
        elif op == "project":
            names = [_resolve_col(cols, x) for x in _split_top(arg, ",")]
            rows = [{n: r.get(n) for n in names} for r in rows]
            cols = names
        elif op in ("take", "limit"):
            if not re.fullmatch(r"\d+", arg):
                raise KqlError(f"'{op}' requires a number")
            rows = rows[: int(arg)]
        elif op == "count":
            rows, cols = [{"Count": len(rows)}], ["Count"]
        elif op in ("order", "sort"):
            body = re.sub(r"^by\s+", "", arg, flags=re.I)
            keys = []
            for part in _split_top(body, ","):
                mm = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?:\s+(asc|desc))?", part, re.I)
                if not mm:
                    raise KqlError(f"Cannot parse sort key '{part}'")
                keys.append((_resolve_col(cols, mm.group(1)), (mm.group(2) or "desc").lower() == "desc"))
            for col, desc in reversed(keys):
                rows.sort(key=lambda r, c=col: (r.get(c) is None, r.get(c) if isinstance(r.get(c), (int, float)) else str(r.get(c))), reverse=desc)
        elif op == "summarize":
            rows, cols = _summarize(arg, rows, cols)
        elif op == "extend":
            for item in _split_top(arg, ","):
                name, body = _expr_name(item)
                if not name:
                    raise KqlError(f"extend needs 'name = expression', got '{item}'")
                comp = _compile_expr(body)
                for r in rows:
                    r[name] = _eval(comp, r, cols)
                if name not in cols:
                    cols = cols + [name]
        elif op == "top":
            mt = re.fullmatch(r"(\d+)\s+by\s+([A-Za-z_]\w*)(?:\s+(asc|desc))?", arg, re.I)
            if not mt:
                raise KqlError("Usage: top <N> by <column> [asc|desc]")
            col = _resolve_col(cols, mt.group(2))
            rows = sorted(rows, key=lambda r: (r.get(col) is None, r.get(col) if isinstance(r.get(col), (int, float)) else str(r.get(col))),
                          reverse=(mt.group(3) or "desc").lower() == "desc")[: int(mt.group(1))]
        elif op == "render":
            pass          # chart hint only; results are unchanged
        elif op == "distinct":
            names = [_resolve_col(cols, x) for x in _split_top(arg, ",")]
            seen, out = set(), []
            for r in rows:
                k = tuple(r.get(n) for n in names)
                if k not in seen:
                    seen.add(k)
                    out.append({n: r.get(n) for n in names})
            rows, cols = out, names
        else:
            raise KqlError(f"Unsupported operator '{op}'. Supported: where, project, extend, take, limit, count, order by, sort by, summarize, top, distinct, render.")
    types = {}
    for c in cols:
        types[c] = next((_coltype(r[c]) for r in rows if r.get(c) is not None), "datetime" if c == "TimeGenerated" else "string")
    if "TimeGenerated" in types:
        types["TimeGenerated"] = "datetime"
    return {"tables": [{"name": "PrimaryResult", "columns": [{"name": c, "type": types[c]} for c in cols],
                        "rows": [[r.get(c) for c in cols] for r in rows]}]}
