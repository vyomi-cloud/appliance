"""Azure Cost Management + Consumption core (substrate-free, Nano/offline-shared).

Models the console's real backends over Vyomi's own ARM inventory (``core/azure_arm_core.py``'s
flat ``state`` dict) and the list-price tables in ``core/cost_model.py`` — the same pricing used
for the per-space "real cloud cost" savings metric, so a dollar in Cost Management and a dollar
in a space summary come from one source of truth.

ARM REST modelled (azure-rest-api-specs ``specification/cost-management`` /
``specification/consumption``), so ``azure-mgmt-costmanagement`` / ``azure-mgmt-consumption`` /
``az costmanagement`` / ``az consumption budget`` work unchanged against ``{scope}`` =
``/subscriptions/{sub}`` or ``/subscriptions/{sub}/resourceGroups/{rg}``:

    POST {scope}/providers/Microsoft.CostManagement/query                      (cost analysis)
    GET/PATCH {scope}/providers/Microsoft.CostManagement/alerts[/{name}]       (budget alerts)
    POST {scope}/providers/Microsoft.CostManagement/alerts/{name}/dismiss|reactivate
    GET/PUT/DELETE/POST(run) {scope}/providers/Microsoft.CostManagement/exports[/{name}[/run]]
    GET/PUT/PATCH/DELETE {scope}/providers/Microsoft.Consumption/budgets[/{name}]

Budgets and exports persist in the SAME flat ``state`` dict as every other ARM resource (keyed
by their lower-cased id), so they survive with the rest of ARM. Alerts are not stored directly —
they are derived live from budgets vs. real spend every call; only their dismissed/reactivated
status is persisted (keyed by the alert's own synthetic id), exactly like a real alert's mutable
state layered over immutable budget-threshold definitions.

``dispatch_costmanagement``/``dispatch_consumption`` return ``{"status","headers","body"}``,
the same shape ``AzureArm._arm`` already returns for its generic CRUD branch.
"""
from __future__ import annotations

import calendar
import uuid
from datetime import datetime, timezone

try:                                              # host: package import
    from core import cost_model
except ImportError:                               # Pyodide: cores are flat on sys.path
    import cost_model                              # type: ignore

COST_NS = "Microsoft.CostManagement"
CONSUMPTION_NS = "Microsoft.Consumption"
BUDGET_TYPE = "budgets"
QUERY_API_VERSION = "2023-11-01"


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _ok(body=None, status=200):
    return {"status": status, "headers": {}, "body": body}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ═══════════════════════════ real inventory → real cost ══════════════════════════
# ARM full type (lower-cased "namespace/type") → (cost_model service key, kind). Only
# billable resource types appear here — role assignments, NSGs, vnets' peers etc. are
# free in real Azure too, so they are simply absent from the cost rows (not a gap).
_TYPE_MAP = {
    "microsoft.compute/virtualmachines": ("vm", "virtualmachines"),
    "microsoft.storage/storageaccounts": ("storage", ""),
    "microsoft.sql/servers": ("sql", "database"),
    "microsoft.servicebus/namespaces": ("servicebus", ""),
    "microsoft.documentdb/databaseaccounts": ("cosmos", ""),
    "microsoft.web/sites": ("functionapp", ""),
    "microsoft.apimanagement/service": ("apim", ""),
    "microsoft.network/virtualnetworks": ("vnet", ""),
    "microsoft.eventgrid/topics": ("eventgrid", ""),
    "microsoft.keyvault/vaults": ("keyvault", ""),
    "microsoft.app/containerapps": ("app", ""),
    "microsoft.appconfiguration/configurationstores": ("appconfiguration", ""),
    "microsoft.network/dnszones": ("dns", ""),
    "microsoft.insights/metricalerts": ("monitor", ""),
    "microsoft.operationalinsights/workspaces": ("operationalinsights", ""),
    "microsoft.cognitiveservices/accounts": ("cognitiveservices", ""),
}

_SERVICE_LABEL = {
    "microsoft.compute/virtualmachines": "Virtual Machines",
    "microsoft.storage/storageaccounts": "Storage",
    "microsoft.sql/servers": "Azure SQL Database",
    "microsoft.servicebus/namespaces": "Service Bus",
    "microsoft.documentdb/databaseaccounts": "Azure Cosmos DB",
    "microsoft.web/sites": "Function App",
    "microsoft.apimanagement/service": "API Management",
    "microsoft.network/virtualnetworks": "Virtual Network",
    "microsoft.eventgrid/topics": "Event Grid",
    "microsoft.keyvault/vaults": "Key Vault",
    "microsoft.app/containerapps": "Container Apps",
    "microsoft.appconfiguration/configurationstores": "App Configuration",
    "microsoft.network/dnszones": "Azure DNS",
    "microsoft.insights/metricalerts": "Azure Monitor",
    "microsoft.operationalinsights/workspaces": "Log Analytics",
    "microsoft.cognitiveservices/accounts": "Cognitive Services",
}


def _mtd_fraction(now):
    """How far into the current month ``now`` is (0 < f <= 1) — the fraction of a flat
    monthly rate that counts as "spent so far", the same logic a real Cost Management
    Month-to-date view applies to a resource's steady run-rate."""
    days = calendar.monthrange(now.year, now.month)[1]
    return now.day / days


def _collect_resource_rows(state, sub, rg=None):
    """Every billable resource Vyomi actually has for ``sub`` (optionally narrowed to
    ``rg``), each priced at its real-cloud monthly rate via ``cost_model``."""
    rows = []
    for rec in state.values():
        if rec.get("_sub") != sub:
            continue
        if rg is not None and (rec.get("_rg") or "").lower() != rg.lower():
            continue
        full_type = str(rec.get("_type") or "").lower()
        mapped = _TYPE_MAP.get(full_type)
        if not mapped:
            continue
        service, kind = mapped
        instance_type = ""
        if full_type == "microsoft.compute/virtualmachines":
            instance_type = ((rec.get("properties") or {}).get("hardwareProfile") or {}).get("vmSize", "")
        monthly = cost_model.estimate_resource_cost("azure", service, kind, instance_type)["monthly_usd"]
        rows.append({
            "name": rec.get("name", ""), "full_type": full_type,
            "service": _SERVICE_LABEL.get(full_type, full_type),
            "location": rec.get("location") or "global",
            "resource_group": rec.get("_rg") or "",
            "monthly_usd": monthly,
        })
    return rows


def _row_matches_filter(row, filt):
    """A tiny subset of the real cost-query/budget filter DSL: an ``and`` list of
    ``{"dimensions": {"name": "ResourceGroupName"|"ServiceName", "operator": "In", "values": [...]}}``.
    No filter (``None``/``{}``) matches everything."""
    if not filt:
        return True
    clauses = filt.get("and") or [filt]
    for clause in clauses:
        dim = (clause or {}).get("dimensions") or {}
        name, values = dim.get("name"), [str(v).lower() for v in (dim.get("values") or [])]
        if not name or not values:
            continue
        actual = {"resourcegroupname": row["resource_group"], "servicename": row["service"],
                  "resourcelocation": row["location"]}.get(name.lower())
        if actual is not None and str(actual).lower() not in values:
            return False
    return True


_GROUP_KEY = {
    "servicename": lambda r: r["service"],
    "resourcelocation": lambda r: r["location"],
    "resourcegroupname": lambda r: r["resource_group"] or "(not grouped)",
    "resourceid": lambda r: r["name"],
}


def run_cost_query(state, sub, rg, payload, now=None):
    """``Microsoft.CostManagement/query`` — aggregate real inventory cost. Returns the
    QueryResult shape (``properties.columns``/``properties.rows``) real SDKs parse."""
    now = now or datetime.now(timezone.utc)
    payload = payload or {}
    dataset = payload.get("dataset") or {}
    grouping = dataset.get("grouping") or []
    rows = [r for r in _collect_resource_rows(state, sub, rg) if _row_matches_filter(r, dataset.get("filter"))]
    frac = _mtd_fraction(now)
    for r in rows:
        r["cost"] = round(r["monthly_usd"] * frac, 6)
    if grouping:
        dim = str(grouping[0].get("name") or "ServiceName")
        key_fn = _GROUP_KEY.get(dim.lower(), _GROUP_KEY["servicename"])
        agg: dict = {}
        for r in rows:
            k = key_fn(r)
            agg[k] = round(agg.get(k, 0.0) + r["cost"], 6)
        items = sorted(agg.items(), key=lambda kv: -kv[1])
        columns = [{"name": "Cost", "type": "Number"}, {"name": dim, "type": "String"}, {"name": "Currency", "type": "String"}]
        out_rows = [[v, k, "USD"] for k, v in items]
    else:
        total = round(sum(r["cost"] for r in rows), 6)
        columns = [{"name": "Cost", "type": "Number"}, {"name": "Currency", "type": "String"}]
        out_rows = [[total, "USD"]]
    return {"id": f"/subscriptions/{sub}/providers/{COST_NS}/query", "name": str(uuid.uuid4()),
            "type": f"{COST_NS}/query", "properties": {"columns": columns, "rows": out_rows}}


# ═══════════════════════════ budgets (Microsoft.Consumption) ═════════════════════
def _budget_rid(sub, name):
    return f"/subscriptions/{sub}/providers/{CONSUMPTION_NS}/{BUDGET_TYPE}/{name}"


def budget_spend(state, rec, now=None):
    """Real month-to-date spend + a flat full-month forecast for one budget's scope/filter."""
    now = now or datetime.now(timezone.utc)
    props = rec.get("properties") or {}
    rg = props.get("_scopeResourceGroup")
    rows = [r for r in _collect_resource_rows(state, rec["_sub"], rg) if _row_matches_filter(r, props.get("filter"))]
    frac = _mtd_fraction(now)
    monthly_total = sum(r["monthly_usd"] for r in rows)
    return {"actual": round(monthly_total * frac, 2), "forecast": round(monthly_total, 2)}


def _budget_view(state, rec, now=None):
    out = _view(rec)
    spend = budget_spend(state, rec, now)
    props = dict(rec["properties"])
    props["currentSpend"] = {"amount": spend["actual"], "unit": "USD"}
    props["forecastSpend"] = {"amount": spend["forecast"], "unit": "USD"}
    out["properties"] = props
    return out


def _budgets_for(state, sub):
    ft = f"{CONSUMPTION_NS}/{BUDGET_TYPE}".lower()
    return [r for r in state.values() if str(r.get("_type", "")).lower() == ft and r.get("_sub") == sub]


def dispatch_consumption(state, method, sub, rg, chain, payload, query, base=""):
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    now = datetime.now(timezone.utc)
    if not chain or chain[0].lower() != BUDGET_TYPE:
        supported = f"{CONSUMPTION_NS}/{BUDGET_TYPE}"
        return _err(404, "ResourceTypeNotSupported", f"'{CONSUMPTION_NS}/{chain[0] if chain else ''}' is not supported. Supported: {supported}.")
    rest = chain[1:]
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = sorted(_budgets_for(state, sub), key=lambda r: r["name"].lower())
        return _ok({"value": [_budget_view(state, r, now) for r in items]})
    name = rest[0]
    rid = _budget_rid(sub, name)
    key = rid.lower()
    if method == "GET":
        rec = state.get(key)
        if not rec:
            return _err(404, "ResourceNotFound", f"The budget '{name}' could not be found.")
        return _ok(_budget_view(state, rec, now))
    if method in ("PUT", "PATCH"):
        existed = key in state
        if method == "PATCH" and not existed:
            return _err(404, "ResourceNotFound", f"The budget '{name}' could not be found.")
        props = payload.get("properties") or {}
        if method == "PUT" and not props.get("amount"):
            return _err(400, "BadRequest", "properties.amount is required.")
        rec = state.get(key) or {"id": rid, "name": name, "type": f"{CONSUMPTION_NS}/{BUDGET_TYPE}",
                                  "_type": f"{CONSUMPTION_NS}/{BUDGET_TYPE}", "_sub": sub, "_rg": None,
                                  "properties": {}, "_created": now.isoformat()}
        merged = dict(rec["properties"])
        merged.update(props)
        merged.setdefault("category", "Cost")
        merged.setdefault("timeGrain", "Monthly")
        if rg is not None:                      # created under a resource-group scope: narrow its spend to that RG
            merged["_scopeResourceGroup"] = rg
        rec["properties"] = merged
        rec["eTag"] = str(uuid.uuid4())
        state[key] = rec
        return _ok(_budget_view(state, rec, now), status=200 if existed else 201)
    if method == "DELETE":
        existed = state.pop(key, None) is not None
        return _ok(None, status=200 if existed else 204)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ═══════════════════════════ alerts (derived from budgets) ═══════════════════════
def _alert_id(sub, budget_name, notif_key):
    return f"/subscriptions/{sub}/providers/{COST_NS}/alerts/{budget_name}--{notif_key}"


def _synth_alerts(state, sub, now=None):
    now = now or datetime.now(timezone.utc)
    out = []
    for b in sorted(_budgets_for(state, sub), key=lambda r: r["name"].lower()):
        spend = budget_spend(state, b, now)
        amount = float((b.get("properties") or {}).get("amount") or 0)
        notifications = (b.get("properties") or {}).get("notifications") or {}
        for notif_key, notif in notifications.items():
            if isinstance(notif, dict) and notif.get("enabled") is False:
                continue
            threshold = float((notif or {}).get("threshold") or 80)
            is_forecast = str((notif or {}).get("thresholdType") or "Actual").lower() == "forecasted"
            value = spend["forecast"] if is_forecast else spend["actual"]
            if amount <= 0 or (value / amount * 100) < threshold:
                continue
            aid = _alert_id(sub, b["name"], notif_key)
            override = state.get(aid.lower()) or {}
            out.append({
                "id": aid, "name": aid.rsplit("/", 1)[-1], "type": f"{COST_NS}/alerts",
                "properties": {
                    "definition": {"type": "Budget", "category": "Cost"},
                    "description": f"Budget '{b['name']}' {'is forecasted to exceed' if is_forecast else 'has exceeded'} "
                                    f"{threshold:.0f}% of its {amount:.2f} USD amount.",
                    "source": "Preset", "status": override.get("status", "Active"),
                    "creationTime": b.get("_created", now.isoformat()), "closeTime": override.get("closeTime"),
                    "details": {"amount": amount, "budgetName": b["name"], "currentSpend": value,
                                 "unit": "USD", "scope": f"/subscriptions/{sub}"},
                },
            })
    return out


def dispatch_alerts(state, method, sub, rest, payload, query):
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    now = datetime.now(timezone.utc)
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": _synth_alerts(state, sub, now)})
    alert_name = rest[0]
    rid = f"/subscriptions/{sub}/providers/{COST_NS}/alerts/{alert_name}"
    key = rid.lower()
    if len(rest) == 1 and method == "GET":
        hit = next((a for a in _synth_alerts(state, sub, now) if a["name"].lower() == alert_name.lower()), None)
        if not hit:
            return _err(404, "ResourceNotFound", f"The alert '{alert_name}' could not be found.")
        return _ok(hit)
    if len(rest) == 1 and method == "PATCH":
        status = (payload.get("properties") or {}).get("status")
        if not status:
            return _err(400, "BadRequest", "properties.status is required.")
        state[key] = {"status": status, "closeTime": now.isoformat() if status == "Dismissed" else None}
        return _ok({"id": rid, "properties": {"status": status}})
    if len(rest) == 2 and rest[1].lower() in ("dismiss", "reactivate") and method == "POST":
        status = "Dismissed" if rest[1].lower() == "dismiss" else "Active"
        state[key] = {"status": status, "closeTime": now.isoformat() if status == "Dismissed" else None}
        return _ok({"id": rid, "properties": {"status": status}})
    return _err(404, "ResourceTypeNotSupported", f"'{COST_NS}/alerts/{'/'.join(rest)}' is not supported.")


# ═══════════════════════════ exports ══════════════════════════════════════════════
def _export_rid(sub, name):
    return f"/subscriptions/{sub}/providers/{COST_NS}/exports/{name}"


def dispatch_exports(state, method, sub, rg, rest, payload, query, now=None):
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    now = now or datetime.now(timezone.utc)
    ft = f"{COST_NS}/exports".lower()
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = sorted((r for r in state.values() if str(r.get("_type", "")).lower() == ft and r.get("_sub") == sub),
                        key=lambda r: r["name"].lower())
        return _ok({"value": [_view(r) for r in items]})
    name = rest[0]
    rid = _export_rid(sub, name)
    key = rid.lower()
    if len(rest) == 2 and rest[1].lower() == "run":
        if method != "POST":
            return _err(405, "MethodNotAllowed", "POST required.")
        rec = state.get(key)
        if not rec:
            return _err(404, "ResourceNotFound", f"The export '{name}' could not be found.")
        result = run_cost_query(state, sub, rg, {"dataset": {}}, now)
        total = result["properties"]["rows"][0][0] if result["properties"]["rows"] else 0
        rec["properties"]["lastRunTime"] = now.isoformat()
        rec["properties"]["lastRunCost"] = {"amount": total, "unit": "USD"}
        return _ok({"properties": {"runHistory": {"value": [{
            "processingStartTime": now.isoformat(), "status": "Completed", "fileName": f"{name}.csv",
        }]}}})
    if method == "GET":
        rec = state.get(key)
        if not rec:
            return _err(404, "ResourceNotFound", f"The export '{name}' could not be found.")
        return _ok(_view(rec))
    if method in ("PUT", "PATCH"):
        existed = key in state
        if method == "PATCH" and not existed:
            return _err(404, "ResourceNotFound", f"The export '{name}' could not be found.")
        props = payload.get("properties") or {}
        rec = state.get(key) or {"id": rid, "name": name, "type": f"{COST_NS}/exports",
                                  "_type": f"{COST_NS}/exports", "_sub": sub, "_rg": None, "properties": {}}
        merged = dict(rec["properties"])
        merged.update(props)
        merged.setdefault("format", "Csv")
        merged.setdefault("definition", {"type": "ActualCost", "timeframe": "MonthToDate"})
        rec["properties"] = merged
        rec["eTag"] = str(uuid.uuid4())
        state[key] = rec
        return _ok(_view(rec), status=200 if existed else 201)
    if method == "DELETE":
        existed = state.pop(key, None) is not None
        return _ok(None, status=200 if existed else 204)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ═══════════════════════════ dispatch ═════════════════════════════════════════════
def dispatch_costmanagement(state, method, sub, rg, chain, payload, query, base=""):
    """Handle one ``Microsoft.CostManagement`` request (``chain`` = tokens after the namespace)."""
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    if not chain:
        return _err(400, "BadRequest", "Missing Microsoft.CostManagement operation.")
    op = chain[0].lower()
    try:
        if op == "query":
            if method != "POST":
                return _err(405, "MethodNotAllowed", "POST required.")
            return _ok(run_cost_query(state, sub, rg, payload))
        if op == "alerts":
            return dispatch_alerts(state, method, sub, chain[1:], payload, query)
        if op == "exports":
            return dispatch_exports(state, method, sub, rg, chain[1:], payload, query)
    except _E as e:
        return _err(e.status, e.code, e.message)
    return _err(404, "ResourceTypeNotSupported", f"'{COST_NS}/{chain[0]}' is not supported. Supported: query, alerts, exports.")


def handles(namespace):
    return namespace.lower() in (COST_NS.lower(), CONSUMPTION_NS.lower())
