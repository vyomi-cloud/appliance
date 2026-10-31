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
    "AzureActivity": ["TimeGenerated", "OperationName", "Caller", "Level", "ResourceGroup", "ResourceId"],
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
        {"name": {"value": "DataAnalyzed", "localizedValue": "Data Analyzed"}, "unit": "Bytes", "currentValue": 0.0,
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
        rows.append([e.get("eventTimestamp"), op, e.get("caller"), e.get("level"), e.get("resourceGroupName"), e.get("resourceId")])
    return rows


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
def dispatch(state, method, sub, rg, chain, names, payload=None, query=None, base=""):
    """Handle one ``Microsoft.OperationalInsights`` ARM request (``chain`` = tokens after the namespace)."""
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
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
