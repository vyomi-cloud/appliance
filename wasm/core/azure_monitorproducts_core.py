# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure Monitor companion products - control plane only (``Microsoft.Monitor``, ``Microsoft.Dashboard``). Substrate-free (no fastapi / sockets / subprocess), so the same file runs offline and in Nano.

    Microsoft.Monitor/accounts           Azure Monitor workspace behind Managed Prometheus (api 2023-04-03)
    Microsoft.Dashboard/grafana          Azure Managed Grafana workspace (api 2023-09-01)

Real behaviour: name rules, SKU / version enums, generated endpoint hostnames, system-assigned identity, a Monitor
account really creates its managed Data Collection Endpoint and Data Collection Rule (Microsoft.Insights, in the
account's managed resource group, exactly as Azure does), a Grafana workspace's Azure Monitor workspace
integrations are validated against real Monitor accounts. Deleting a Monitor account removes its managed DCE/DCR; deleting an account still integrated with
a Grafana workspace is refused.

NOT modelled (no engine behind them): Prometheus scraping/ingestion/PromQL (the query endpoint exists but nothing is
ever ingested), a running Grafana server (the endpoint is a stable name, not a live web app). SCOM managed
instances are not modelled at all (they need a SQL managed instance and an Active Directory domain Vyomi has none of). ``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}``.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone

API_VERSIONS = {"microsoft.monitor": "2023-04-03", "microsoft.dashboard": "2023-09-01"}
API_VERSION = API_VERSIONS["microsoft.monitor"]
DEFAULT_LOCATION = "eastus"
GRAFANA_SKUS = ("Standard", "Essential")
GRAFANA_MAJOR = {"9": "9.5.18", "10": "10.4.9", "11": "11.3.1"}
SHORT_LOC = {"eastus": "eus", "eastus2": "eus2", "westus": "wus", "westus2": "wus2", "westus3": "wus3", "centralus": "cus",
             "northeurope": "neu", "westeurope": "weu", "uksouth": "uks", "southeastasia": "sea", "centralindia": "cin"}
_TENANT = "00000000-0000-0000-0000-000000000000"
_TYPES = {  # (namespace lower, collection lower) -> canonical type string
    ("microsoft.monitor", "accounts"): "Microsoft.Monitor/accounts",
    ("microsoft.dashboard", "grafana"): "Microsoft.Dashboard/grafana",
}


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _bad(msg, code="InvalidParameter"):
    return _E(400, code, msg)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _ok(body=None, status=200, headers=None, lro=False, rid="", verb=""):
    return {"status": status, "headers": headers or {}, "body": body, "lro": lro, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}, "lro": False, "rid": "", "verb": ""}


def _h(*parts, n=8):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:n]


def _sysdata():
    n = _now()
    return {"createdBy": "vyomi@example.com", "createdByType": "User", "createdAt": n,
            "lastModifiedBy": "vyomi@example.com", "lastModifiedByType": "User", "lastModifiedAt": n}


def handles(namespace, chain):
    return bool(chain) and (namespace.lower(), chain[0].lower()) in _TYPES


def _rid(sub, rg, ns, coll, name):
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{ns}/{coll}/{name}"


def _of_type(state, typ):
    t = typ.lower()
    return [r for r in state.values() if str(r.get("_type", "")).lower() == t]


def _enum(v, what, allowed):
    if v not in allowed:
        raise _bad(f"The value '{v}' for '{what}' is invalid. Allowed values: {', '.join(allowed)}.")
    return v


def _identity(payload, rid, old=None):
    ident = payload.get("identity")
    if ident is None:
        return old
    t = _enum((ident or {}).get("type") or "None", "identity.type", ("None", "SystemAssigned", "UserAssigned", "SystemAssigned,UserAssigned"))
    out = {"type": t}
    if "SystemAssigned" in t:
        out["principalId"] = str(uuid.uuid5(uuid.NAMESPACE_URL, rid + "#p"))
        out["tenantId"] = _TENANT
    if "UserAssigned" in t:
        out["userAssignedIdentities"] = {k: {"principalId": str(uuid.uuid5(uuid.NAMESPACE_URL, k + "#p")),
                                              "clientId": str(uuid.uuid5(uuid.NAMESPACE_URL, k + "#c"))}
                                          for k in ((ident or {}).get("userAssignedIdentities") or {})}
    return out


def _public_access(v, old="Enabled"):
    return _enum(v, "publicNetworkAccess", ("Enabled", "Disabled")) if v else old


def _check_name(name, what, lo, hi, allow_hyphen=True):
    ok = re.fullmatch(r"[A-Za-z][A-Za-z0-9" + ("-" if allow_hyphen else "") + r"]*[A-Za-z0-9]", name or "") and lo <= len(name) <= hi
    if not ok:
        raise _bad(f"The name '{name}' is invalid. {what} names must be {lo}-{hi} characters, start with a letter, "
                   f"end with a letter or digit and contain only letters, digits{' and hyphens' if allow_hyphen else ''}.", "InvalidResourceName")


# ═══════════════════════════ Azure Monitor workspace (Managed Prometheus) ════════
def _managed_rg(name, loc):
    return f"MA_{name}_{loc}_managed"


def _new_account(state, rid, sub, rg, name, payload):
    loc = payload.get("location") or DEFAULT_LOCATION
    pay = payload.get("properties") or {}
    mrg = _managed_rg(name, loc)
    dce_id = _rid(sub, mrg, "Microsoft.Insights", "dataCollectionEndpoints", name)
    dcr_id = _rid(sub, mrg, "Microsoft.Insights", "dataCollectionRules", name)
    tok = _h(rid, n=10)
    internal = str(uuid.uuid5(uuid.NAMESPACE_URL, rid))
    props = {
        "accountId": internal, "provisioningState": "Succeeded",
        "metrics": {"prometheusQueryEndpoint": f"https://{name}-{tok}.{loc}.prometheus.monitor.azure.com", "internalId": internal},
        "defaultIngestionSettings": {"dataCollectionRuleResourceId": dcr_id, "dataCollectionEndpointResourceId": dce_id,
                                     "metricsIngestionEndpoint": f"https://{name}-{tok}.{loc}-1.metrics.ingest.monitor.azure.com"},
        "publicNetworkAccess": _public_access(pay.get("publicNetworkAccess")), "privateEndpointConnections": [],
    }
    # the managed DCE + DCR Azure creates alongside every Monitor workspace
    state[dce_id.lower()] = {"id": dce_id, "name": name, "type": "Microsoft.Insights/dataCollectionEndpoints", "location": loc, "tags": {},
        "kind": "Linux", "properties": {"description": f"Managed by Azure Monitor workspace {name}", "provisioningState": "Succeeded",
            "immutableId": f"dce-{tok}", "configurationAccess": {"endpoint": f"https://{name}-{tok}.{loc}.handler.control.monitor.azure.com"},
            "logsIngestion": {"endpoint": f"https://{name}-{tok}.{loc}-1.ingest.monitor.azure.com"},
            "metricsIngestion": {"endpoint": f"https://{name}-{tok}.{loc}-1.metrics.ingest.monitor.azure.com"},
            "networkAcls": {"publicNetworkAccess": "Enabled"}},
        "_type": "Microsoft.Insights/dataCollectionEndpoints", "_sub": sub, "_rg": mrg, "_owner": rid.lower()}
    state[dcr_id.lower()] = {"id": dcr_id, "name": name, "type": "Microsoft.Insights/dataCollectionRules", "location": loc, "tags": {},
        "kind": "Linux", "properties": {"description": f"Managed by Azure Monitor workspace {name}", "dataSources": {},
            "destinations": {"monitoringAccounts": [{"accountResourceId": rid, "accountId": internal, "name": "MonitoringAccount1"}]},
            "dataFlows": [{"streams": ["Microsoft-PrometheusMetrics"], "destinations": ["MonitoringAccount1"]}],
            "dataCollectionEndpointId": dce_id, "provisioningState": "Succeeded", "immutableId": f"dcr-{tok}"},
        "_type": "Microsoft.Insights/dataCollectionRules", "_sub": sub, "_rg": mrg, "_owner": rid.lower()}
    return {"id": rid, "name": name, "type": "Microsoft.Monitor/accounts", "location": loc, "tags": dict(payload.get("tags") or {}),
            "properties": props, "systemData": _sysdata(), "_type": "Microsoft.Monitor/accounts", "_sub": sub, "_rg": rg}


def _put_account(state, sub, rg, rid, name, payload, method):
    _check_name(name, "Azure Monitor workspace", 1, 44)
    rec = state.get(rid.lower())
    if rec is None and method == "PATCH":
        raise _E(404, "ResourceNotFound", f"The Resource 'Microsoft.Monitor/accounts/{name}' under resource group '{rg}' was not found.")
    if rec is None:
        if not payload.get("location"):
            raise _bad("The location property is required for this definition.", "LocationRequired")
        rec = _new_account(state, rid, sub, rg, name, payload)
        state[rid.lower()] = rec
        return rec, True
    if "tags" in payload:
        rec["tags"] = dict(payload.get("tags") or {})
    pna = (payload.get("properties") or {}).get("publicNetworkAccess")
    if pna:
        rec["properties"]["publicNetworkAccess"] = _public_access(pna)
    rec["systemData"]["lastModifiedAt"] = _now()
    return rec, False


def _grafana_using(state, rid):
    key = rid.lower()
    return [g for g in _of_type(state, "Microsoft.Dashboard/grafana")
            if any((i.get("azureMonitorWorkspaceResourceId") or "").lower() == key
                   for i in (g["properties"].get("grafanaIntegrations") or {}).get("azureMonitorWorkspaceIntegrations", []))]


def _delete_account(state, rec):
    users = _grafana_using(state, rec["id"])
    if users:
        raise _E(409, "Conflict", f"The Azure Monitor workspace '{rec['name']}' is integrated with Grafana workspace '{users[0]['name']}'. "
                                  "Remove the integration first.")
    for k in [k for k, v in state.items() if v.get("_owner") == rec["id"].lower()]:
        state.pop(k, None)
    state.pop(rec["id"].lower(), None)


# ═══════════════════════════ Azure Managed Grafana ═══════════════════════════════
def _integrations(state, sub, props):
    gi = props.get("grafanaIntegrations")
    if gi is None:
        return None
    ints = (gi or {}).get("azureMonitorWorkspaceIntegrations") or []
    seen, out = set(), []
    for i in ints:
        rid = (i or {}).get("azureMonitorWorkspaceResourceId")
        if not isinstance(rid, str) or not rid:
            raise _bad("Each azureMonitorWorkspaceIntegrations entry needs an 'azureMonitorWorkspaceResourceId'.")
        if rid.lower() in seen:
            raise _bad(f"Azure Monitor workspace '{rid.rsplit('/', 1)[-1]}' is integrated more than once.")
        seen.add(rid.lower())
        target = state.get(rid.lower())
        if target is None or str(target.get("_type", "")).lower() != "microsoft.monitor/accounts":
            raise _bad(f"The Azure Monitor workspace '{rid}' was not found.", "InvalidAzureMonitorWorkspace")
        out.append({"azureMonitorWorkspaceResourceId": target["id"]})
    return {"azureMonitorWorkspaceIntegrations": out}


def _grafana_props(state, sub, name, loc, rid, pay, old=None):
    major = str(pay.get("grafanaMajorVersion") or (old or {}).get("grafanaMajorVersion") or "11")
    if major not in GRAFANA_MAJOR:
        raise _bad(f"The grafanaMajorVersion '{major}' is not supported. Supported: {', '.join(GRAFANA_MAJOR)}.", "InvalidGrafanaMajorVersion")
    tok = _h(rid, n=8)
    props = dict(old or {})
    props.update({
        "provisioningState": "Succeeded", "grafanaMajorVersion": major, "grafanaVersion": GRAFANA_MAJOR[major],
        "endpoint": props.get("endpoint") or f"https://{name}-{tok}.{SHORT_LOC.get(loc, loc[:3])}.grafana.azure.com",
        "publicNetworkAccess": _public_access(pay.get("publicNetworkAccess"), props.get("publicNetworkAccess", "Enabled")),
        "zoneRedundancy": _enum(pay.get("zoneRedundancy") or props.get("zoneRedundancy", "Disabled"), "zoneRedundancy", ("Enabled", "Disabled")),
        "apiKey": _enum(pay.get("apiKey") or props.get("apiKey", "Disabled"), "apiKey", ("Enabled", "Disabled")),
        "deterministicOutboundIP": _enum(pay.get("deterministicOutboundIP") or props.get("deterministicOutboundIP", "Disabled"), "deterministicOutboundIP", ("Enabled", "Disabled")),
        "autoGeneratedDomainNameLabelScope": props.get("autoGeneratedDomainNameLabelScope") or "TenantReuse",
        "privateEndpointConnections": props.get("privateEndpointConnections") or [],
    })
    ints = _integrations(state, sub, pay)
    if ints is not None:
        props["grafanaIntegrations"] = ints
    props.setdefault("grafanaIntegrations", {"azureMonitorWorkspaceIntegrations": []})
    return props


def _put_grafana(state, sub, rg, rid, name, payload, method):
    _check_name(name, "Grafana workspace", 2, 23)
    rec = state.get(rid.lower())
    if rec is None and method == "PATCH":
        raise _E(404, "ResourceNotFound", f"The Resource 'Microsoft.Dashboard/grafana/{name}' under resource group '{rg}' was not found.")
    sku = ((payload.get("sku") or {}).get("name")) or (rec["sku"]["name"] if rec else "Standard")
    _enum(sku, "sku.name", GRAFANA_SKUS)
    pay = payload.get("properties") or {}
    if rec is None:
        if not payload.get("location"):
            raise _bad("The location property is required for this definition.", "LocationRequired")
        if any(g["name"].lower() == name.lower() for g in _of_type(state, "Microsoft.Dashboard/grafana") if g["_sub"] == sub):
            raise _E(409, "Conflict", f"A Grafana workspace named '{name}' already exists in this subscription.")
        loc = payload["location"]
        rec = {"id": rid, "name": name, "type": "Microsoft.Dashboard/grafana", "location": loc, "tags": dict(payload.get("tags") or {}),
               "sku": {"name": sku}, "kind": "Standard", "properties": _grafana_props(state, sub, name, loc, rid, pay),
               "systemData": _sysdata(), "_type": "Microsoft.Dashboard/grafana", "_sub": sub, "_rg": rg}
        rec["identity"] = _identity(payload, rid) or {"type": "None"}
        state[rid.lower()] = rec
        return rec, True
    rec["properties"] = _grafana_props(state, sub, name, rec["location"], rid, pay, rec["properties"])
    rec["sku"] = {"name": sku}
    if "tags" in payload:
        rec["tags"] = dict(payload.get("tags") or {})
    if payload.get("identity"):
        rec["identity"] = _identity(payload, rid)
    rec["systemData"]["lastModifiedAt"] = _now()
    return rec, False


# ═══════════════════════════ dispatch ════════════════════════════════════════════
_PUT = {"microsoft.monitor": _put_account, "microsoft.dashboard": _put_grafana}


def dispatch(state, method, sub, rg, namespace, chain, payload=None, query=None, base=""):
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, namespace, list(chain), payload)
    except _E as e:
        return _err(e.status, e.code, e.message)


def _dispatch(state, method, sub, rg, namespace, chain, payload):
    ns = namespace.lower()
    typ = _TYPES[(ns, chain[0].lower())]
    coll = typ.split("/")[1]
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [_view(r) for r in _of_type(state, typ) if r.get("_sub") == sub and (rg is None or (r.get("_rg") or "").lower() == rg.lower())]
        return _ok({"value": items})
    name = chain[1]
    if rg is None:
        return _err(400, "InvalidResourceId", f"{typ} must be addressed within a resource group.")
    rid = _rid(sub, rg, typ.split("/")[0], coll, name)
    rec = state.get(rid.lower())
    if len(chain) > 2:
        if rec is None:
            raise _E(404, "ResourceNotFound", f"The Resource '{typ}/{name}' under resource group '{rg}' was not found.")
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{typ}/{'/'.join(chain[2:])}' is not supported.")
    if method == "GET":
        if rec is None:
            raise _E(404, "ResourceNotFound", f"The Resource '{typ}/{name}' under resource group '{rg}' was not found. "
                     "For more details please go to https://aka.ms/ARMResourceNotFoundFix")
        return _ok(_view(rec))
    if method in ("PUT", "PATCH"):
        rec, created = _PUT[ns](state, sub, rg, rid, name, payload, method)
        return _ok(_view(rec), 201 if created else 200, lro=True, rid=rid, verb=method.lower())
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        if ns == "microsoft.monitor":
            _delete_account(state, rec)
        else:
            state.pop(rid.lower(), None)
        return _ok(None, 200, lro=True, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def resource_types():
    return [("Microsoft.Monitor/accounts", "2023-04-03"), ("Microsoft.Dashboard/grafana", "2023-09-01"),
            ("Microsoft.Scom/managedInstances", "2023-07-07-preview")]
