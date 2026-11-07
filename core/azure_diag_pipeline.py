"""Azure diagnostic settings -> REAL log / metric forwarding (substrate-independent, Pyodide-loadable).

A Microsoft.Insights/diagnosticSettings resource (core/azure_monitor_core.py) names categories and destinations. This module is the
delivery side: when a resource operation happens (an ARM write/delete/action, or a data-plane call served by a Vyomi
engine) `emit_log` / `emit_metric` look up the diagnostic settings scoped to that resource, keep the ones that enable the
category, and deliver one record to each destination that exists:

  workspaceId          -> a row in the Log Analytics workspace's own store (core/azure_operationalinsights_core.py), table
                          AzureDiagnostics (or the resource-specific table when logAnalyticsDestinationType=Dedicated),
                          AzureMetrics for metrics. It is queryable at once with the workspace KQL engine.
  storageAccountId     -> an append to the blob insights-logs-<category>/resourceId=.../y=/m=/d=/h=/m=00/PT1H.json in the
                          destination account of the simulator's Blob store (JSON lines, the layout real Azure writes). The
                          account's firewall applies as it does for the real service: publicNetworkAccess=Disabled or
                          defaultAction=Deny without the trusted-service bypass (AzureServices) FAILS the delivery.
  eventHubAuthorizationRuleId / marketplacePartnerId -> nothing: the simulator has no Event Hubs or partner service. The
                          delivery is counted as failed (`_delivery` on the setting) rather than pretending.

Which operations emit what is deliberately only what Vyomi really observes: control-plane writes on Key Vault / Service Bus /
Azure AI services (AuditEvent / OperationalLogs / Audit), blob-service requests (StorageRead/Write/Delete), Key Vault,
Service Bus, Azure OpenAI and Cosmos data-plane calls, and the one real metric (ActivityOperations). Anything else
produces no log, exactly as a resource type with no such category would.
"""
from __future__ import annotations

import datetime
import json
import re

BLOB_STORE = [None]            # the Blob store the substrate attached (set by attach_blob_store)

# control-plane operations on these types are logged by the service under this category
CONTROL_CATEGORY = {
    "microsoft.keyvault/vaults": "AuditEvent",
    "microsoft.servicebus/namespaces": "OperationalLogs",
    "microsoft.cognitiveservices/accounts": "Audit",
}
DEDICATED_TABLE = {"AuditEvent": "AZKVAuditLogs", "StorageRead": "StorageBlobLogs", "StorageWrite": "StorageBlobLogs",
                   "StorageDelete": "StorageBlobLogs", "DataPlaneRequests": "CDBDataPlaneRequests"}
_AUDIT_GROUP = {"auditevent", "audit", "operationallogs", "runtimeauditlogs", "requestresponse"}


def attach_blob_store(store) -> None:
    if store is not None:
        BLOB_STORE[0] = store


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def settings_for(state: dict, rid: str) -> list:
    key = (rid or "").lower()
    return [r for r in (state or {}).values() if isinstance(r, dict) and r.get("_diag_scope") == key]


def _enabled(setting: dict, category: str, metric: bool = False) -> bool:
    p = setting.get("properties") or {}
    for c in (p.get("metrics") if metric else p.get("logs")) or []:
        if not c.get("enabled"):
            continue
        if str(c.get("category") or "").lower() == category.lower():
            return True
        grp = str(c.get("categoryGroup") or "").lower()
        if not metric and (grp == "alllogs" or (grp == "audit" and category.lower() in _AUDIT_GROUP)):
            return True
    return False


def _parts(rid: str):
    m = re.match(r"^/subscriptions/([^/]+)(?:/resourcegroups/([^/]+))?(?:/providers/([^/]+)/(.+))?$", rid or "", re.I)
    sub, rg, ns, rest = (m.groups() if m else ("", "", "", ""))
    toks = (rest or "").split("/")
    rtype = "/".join([ns or ""] + toks[0::2]) if rest else ""
    return sub or "", rg or "", rtype, (toks[1] if len(toks) > 1 else "")


def _row(rid: str, category: str, operation: str, result: str, props: dict | None) -> dict:
    sub, rg, rtype, name = _parts(rid)
    row = {"TimeGenerated": _now(), "ResourceId": rid.upper(), "Category": category, "OperationName": operation,
           "ResultType": result, "SubscriptionId": sub, "ResourceGroup": rg.upper(), "ResourceProvider": rtype.split("/")[0].upper(),
           "ResourceType": rtype.upper().split("/", 1)[-1], "Resource": name.upper(), "_ResourceId": rid.lower()}
    for k, v in (props or {}).items():
        row[re.sub(r"[^A-Za-z0-9_]", "_", k) + ("_b" if isinstance(v, bool) else "_d" if isinstance(v, (int, float)) else "_s")] = \
            v if isinstance(v, (str, bool, int, float)) else json.dumps(v)
    return row


def _deliver_workspace(state, dest_id, table, row) -> str | None:
    ws = state.get((dest_id or "").lower())
    if not ws or "operationalinsights/workspaces" not in str(ws.get("_type") or ws.get("type") or "").lower():
        return f"destination workspace '{dest_id}' does not exist"
    try:
        from core import azure_operationalinsights_core as oi
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import azure_operationalinsights_core as oi  # type: ignore
    oi._store(ws, table, [row])
    return None


def _deliver_storage(state, dest_id, category, row) -> str | None:
    acct = state.get((dest_id or "").lower())
    if not acct:
        return f"destination storage account '{dest_id}' does not exist"
    store = BLOB_STORE[0]
    if store is None:
        return "no Blob store is attached to this substrate"
    try:
        from core import azure_netaccess as na, azure_blob_core as blob
    except ImportError:  # pragma: no cover
        import azure_netaccess as na, azure_blob_core as blob  # type: ignore
    denied = na.check(state, acct.get("id") or dest_id, "storage", acct.get("properties") or {}, {"trusted_service": "1"})
    if denied:
        return f"storage account firewall refused the delivery ({denied[1]}): enable 'Allow trusted Microsoft services' (networkAcls.bypass=AzureServices)"
    name = (acct.get("name") or dest_id.rsplit("/", 1)[-1])
    cont = "insights-logs-" + category.lower() if row.get("Category") != "AllMetrics" else "insights-metrics-pt1m"
    if re.fullmatch(r"/subscriptions/[^/]+", str(row.get("_ResourceId") or "")):
        cont = "insights-activity-logs"          # the real container the subscription Activity log export writes to
    now = datetime.datetime.now(datetime.timezone.utc)
    path = f"{cont}/resourceId={row['ResourceId']}/y={now:%Y}/m={now:%m}/d={now:%d}/h={now:%H}/m=00/PT1H.json"
    line = json.dumps({"time": row["TimeGenerated"], "resourceId": row["ResourceId"], "category": row["Category"],
                       "operationName": row["OperationName"], "resultType": row["ResultType"],
                       "properties": {k: v for k, v in row.items() if k.endswith(("_s", "_b", "_d"))}}) + "\n"
    saved = getattr(store, "_arm_ctx", None)
    store._arm_ctx = None            # the delivery's own blob writes must not be logged back into the pipeline
    try:
        blob.dispatch(store, "PUT", f"/{cont}", {"restype": "container"}, {}, b"", account=name)
        cur = blob.dispatch(store, "GET", f"/{path}", {}, {}, b"", account=name)
        data = (cur.body if cur.status == 200 else b"") + line.encode()
        r = blob.dispatch(store, "PUT", f"/{path}", {}, {"x-ms-blob-type": "BlockBlob", "content-type": "application/json"}, data, account=name)
    finally:
        store._arm_ctx = saved
    return None if r.status < 300 else f"blob write failed ({r.status})"


def _deliver(state, setting, category, operation, row, table_plain, metric=False):
    p = setting.get("properties") or {}
    st = setting.setdefault("_delivery", {"delivered": 0, "failed": 0, "lastError": ""})
    errs = []
    if p.get("workspaceId"):
        table = "AzureMetrics" if metric else (DEDICATED_TABLE.get(category, "AzureDiagnostics")
                                               if p.get("logAnalyticsDestinationType") == "Dedicated" else "AzureDiagnostics")
        e = _deliver_workspace(state, p["workspaceId"], table, row)
        errs.append(e) if e else st.__setitem__("delivered", st["delivered"] + 1)
    if p.get("storageAccountId"):
        e = _deliver_storage(state, p["storageAccountId"], "AllMetrics" if metric else category, row)
        errs.append(e) if e else st.__setitem__("delivered", st["delivered"] + 1)
    for dest in ("eventHubAuthorizationRuleId", "marketplacePartnerId"):
        if p.get(dest):
            errs.append(f"{dest.replace('AuthorizationRuleId', '')} destination is not served: the simulator has no Event Hubs / partner receiver")
    if errs:
        st["failed"] += len(errs)
        st["lastError"] = errs[-1]
    return errs


def emit_log(state: dict, rid: str, category: str, operation: str, result: str = "Success", props: dict | None = None) -> int:
    """Deliver one resource log to every enabled setting scoped to `rid`. -> number of settings that matched."""
    n = 0
    try:
        for s in settings_for(state, rid):
            if _enabled(s, category):
                _deliver(state, s, category, operation, _row(rid, category, operation, result, props), False)
                n += 1
    except Exception:       # a broken destination never breaks the operation being observed
        pass
    return n


def emit_metric(state: dict, rid: str, metric: str, value: float = 1.0, operation: str = "") -> int:
    n = 0
    try:
        for s in settings_for(state, rid):
            if _enabled(s, "AllMetrics", metric=True):
                row = _row(rid, "AllMetrics", operation or metric, "Success", None)
                row.update({"MetricName": metric, "Total": value, "Count": 1, "Average": value, "Minimum": value, "Maximum": value, "TimeGrain": "PT1M"})
                _deliver(state, s, "AllMetrics", metric, row, False, metric=True)
                n += 1
    except Exception:
        pass
    return n


def on_activity(state: dict, blob_store, rid: str, operation_name: str, status: str = "Succeeded") -> None:
    """Hook for AzureArm._record_activity: a control-plane operation on `rid`."""
    attach_blob_store(blob_store)
    if not rid or "/providers/microsoft.insights/diagnosticsettings" in rid.lower():
        return
    _s, _g, rtype, _n = _parts(rid)
    result = "Success" if status == "Succeeded" else "Failure"
    cat = CONTROL_CATEGORY.get(rtype.lower())
    if cat:
        emit_log(state, rid, cat, operation_name, result, {"requestUri": rid})
    emit_metric(state, rid, "ActivityOperations", 1.0, operation_name)
    low = operation_name.lower()
    if "/write" in low or "/delete" in low or "/action" in low:
        sub = _parts(rid)[0]
        if sub:      # Activity Log export: subscription-scoped settings enabling Administrative
            emit_log(state, f"/subscriptions/{sub}", "Administrative", operation_name, result, {"resourceUri": rid})


def emit_named(state: dict, full_type: str, id_suffix: str, category: str, operation: str, status: int = 200, props: dict | None = None) -> int:
    """Data-plane emit for a resource the engine only knows by name (x-vyomi-vault / -namespace / -account)."""
    try:
        try:
            from core import azure_netaccess as na
        except ImportError:  # pragma: no cover
            import azure_netaccess as na  # type: ignore
        rec = na.find_arm(state, full_type, id_suffix)
        if rec:
            return emit_log(state, rec["id"], category, operation, "Success" if int(status) < 400 else "Failure", {**(props or {}), "statusCode": int(status)})
    except Exception:
        pass
    return 0
