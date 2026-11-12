"""AKS monitoring toggles backed by the Azure Monitor products (not cluster flags), substrate-free.

Reconciled on every ``Microsoft.ContainerService/managedClusters`` PUT/PATCH (``reconcile``) and on delete (``cleanup``):

* **Container Insights** -- ``addonProfiles.omsagent.enabled`` with ``config.logAnalyticsWorkspaceResourceID``: the workspace
  must exist (Microsoft.OperationalInsights/workspaces); a REAL Data Collection Rule ``MSCI-<region>-<cluster>``
  (stream Microsoft-ContainerInsightsExtension -> that workspace) and the association ``ContainerInsightsExtension`` on the
  cluster are created; disabling removes both.
* **Managed Prometheus** -- ``azureMonitorProfile.metrics.enabled``: needs an Azure Monitor workspace
  (``metrics.azureMonitorWorkspaceResourceId``, a Vyomi/CLI-style input; when omitted the default workspace
  ``DefaultAzureMonitorWorkspace-<region>`` is created in ``DefaultRG-<region>`` like the portal does). Creates the DCR
  ``MSProm-<region>-<cluster>`` (+ DCE reuse of the workspace's) and association ``ContainerInsightsMetricsExtension``.
* **Managed Grafana** -- ``azureMonitorProfile.metrics.grafanaResourceId`` (or ``createGrafana: true`` for a default
  ``DefaultGrafana-<region>``): the Grafana workspace must exist and the Monitor workspace is added to its
  ``azureMonitorWorkspaceIntegrations``. Metrics must be enabled first.

NOT modelled: the monitoring agents (ama-logs / ama-metrics) do not run, nothing is scraped or shipped into the
workspace or the Prometheus store, and Grafana is not a running server (see azure_monitorproducts_core).
"""
from __future__ import annotations

import re

try:
    from core import azure_monitorproducts_core as mp
    from core import azure_monitor_core as mon
except ImportError:                                    # Pyodide flat layout
    import azure_monitorproducts_core as mp            # type: ignore
    import azure_monitor_core as mon                   # type: ignore

AKS = "microsoft.containerservice/managedclusters"
DCR = "Microsoft.Insights/dataCollectionRules"
MSCI, PROM = "ContainerInsightsExtension", "ContainerInsightsMetricsExtension"


def _err(code, msg):
    return {"status": 400, "headers": {}, "body": {"error": {"code": code, "message": msg}}}


def handles(rec):
    return str(rec.get("_type", "")).lower() == AKS


def _dcr(state, rid, name, rg, sub, loc, owner, flows, dests, extra_dest):
    state[rid.lower()] = {"id": rid, "name": name, "type": DCR, "location": loc, "tags": {}, "kind": "Linux",
        "properties": {"description": f"Managed by AKS monitoring ({owner.rsplit('/', 1)[-1]})", "dataSources": {"extensions": []},
                       "destinations": dests, "dataFlows": flows, "provisioningState": "Succeeded", **extra_dest},
        "_type": DCR, "_sub": sub, "_rg": rg, "_owner": owner.lower()}


def _assoc(state, cluster_id, name, dcr_id):
    return mon.upsert_dcr_association(state, cluster_id, name, {"properties": {"dataCollectionRuleId": dcr_id}})


def _drop(state, rec, tag, assoc):
    cid = rec["id"]
    mon.remove_dcr_association(state, cid, assoc)
    for k in [k for k, v in state.items() if isinstance(v, dict) and v.get("_owner") == cid.lower() and v.get("_aksmon") == tag]:
        state.pop(k, None)


def _workspace(state, wid):
    w = state.get(str(wid or "").lower())
    return w if w is not None and str(w.get("_type", "")).lower() == "microsoft.operationalinsights/workspaces" else None


def reconcile(state, rec):
    """None if ok, else an error dict. Idempotent: brings the DCR/DCRA/Grafana links in line with the cluster properties."""
    p = rec.setdefault("properties", {})
    sub, rg, loc, name, cid = rec.get("_sub"), rec.get("_rg"), rec.get("location") or "eastus", rec["name"], rec["id"]
    # ── Container Insights
    oms = ((p.get("addonProfiles") or {}).get("omsagent")) or {}
    if oms.get("enabled") in (True, "true", "True"):
        wid = (oms.get("config") or {}).get("logAnalyticsWorkspaceResourceID")
        ws = _workspace(state, wid)
        if not wid:
            return _err("InvalidAddonProfile", "addonProfiles.omsagent.config.logAnalyticsWorkspaceResourceID is required to enable Container Insights.")
        if ws is None:
            return _err("InvalidLogAnalyticsWorkspace", f"The Log Analytics workspace '{wid}' was not found.")
        dname = f"MSCI-{loc}-{name}"
        rid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Insights/dataCollectionRules/{dname}"
        _dcr(state, rid, dname, rg, sub, loc, cid,
             [{"streams": ["Microsoft-ContainerInsights-Group-Default"], "destinations": ["ciworkspace"]}],
             {"logAnalytics": [{"workspaceResourceId": ws["id"], "name": "ciworkspace"}]},
             {"dataSources": {"extensions": [{"name": "ContainerInsightsExtension", "extensionName": "ContainerInsights", "streams": ["Microsoft-ContainerInsights-Group-Default"],
                                              "extensionSettings": {"dataCollectionSettings": {"interval": "1m", "namespaceFilteringMode": "Off"}}}]}})
        state[rid.lower()]["_aksmon"] = "ci"
        _assoc(state, cid, MSCI, rid)
        oms.setdefault("config", {})["logAnalyticsWorkspaceResourceID"] = ws["id"]
        oms["identity"] = oms.get("identity") or {"resourceId": f"{cid}/addonIdentity/omsagent"}
    elif oms:
        _drop(state, rec, "ci", MSCI)
    # ── Managed Prometheus + Grafana
    amp = p.get("azureMonitorProfile") or {}
    met = amp.get("metrics") or {}
    if met.get("enabled") in (True, "true", "True"):
        mid = met.get("azureMonitorWorkspaceResourceId")
        mw = state.get(str(mid).lower()) if mid else None
        if mid and (mw is None or str(mw.get("_type", "")).lower() != "microsoft.monitor/accounts"):
            return _err("InvalidAzureMonitorWorkspace", f"The Azure Monitor workspace '{mid}' was not found.")
        if mw is None:
            dn, drg = f"DefaultAzureMonitorWorkspace-{loc}", f"DefaultRG-{loc}"
            did = f"/subscriptions/{sub}/resourceGroups/{drg}/providers/Microsoft.Monitor/accounts/{dn}"
            mw = state.get(did.lower())
            if mw is None:
                r = mp.dispatch(state, "PUT", sub, drg, "microsoft.monitor", ["accounts", dn], {"location": loc})
                if r["status"] >= 300:
                    return _err(r["body"]["error"]["code"], r["body"]["error"]["message"])
                mw = state[did.lower()]
        dname = f"MSProm-{loc}-{name}"
        rid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Insights/dataCollectionRules/{dname}"
        ing = mw["properties"]["defaultIngestionSettings"]
        _dcr(state, rid, dname, rg, sub, loc, cid,
             [{"streams": ["Microsoft-PrometheusMetrics"], "destinations": ["MonitoringAccount1"]}],
             {"monitoringAccounts": [{"accountResourceId": mw["id"], "accountId": mw["properties"]["accountId"], "name": "MonitoringAccount1"}]},
             {"dataCollectionEndpointId": ing["dataCollectionEndpointResourceId"], "dataSources": {"prometheusForwarder": [{"name": "PrometheusDataSource", "streams": ["Microsoft-PrometheusMetrics"]}]}})
        state[rid.lower()]["_aksmon"] = "prom"
        _assoc(state, cid, PROM, rid)
        met["azureMonitorWorkspaceResourceId"] = mw["id"]
        state[rid.lower()]["_link"] = {"workspace": mw["id"], "grafana": None}
        met.setdefault("kubeStateMetrics", {})
        gid = met.get("grafanaResourceId")
        if met.get("createGrafana") and not gid:
            gn, grg = f"DefaultGrafana-{loc}"[:23], f"DefaultRG-{loc}"
            gid = f"/subscriptions/{sub}/resourceGroups/{grg}/providers/Microsoft.Dashboard/grafana/{gn}"
            if gid.lower() not in state:
                r = mp.dispatch(state, "PUT", sub, grg, "microsoft.dashboard", ["grafana", gn], {"location": loc, "sku": {"name": "Standard"}})
                if r["status"] >= 300:
                    return _err(r["body"]["error"]["code"], r["body"]["error"]["message"])
        if gid:
            g = state.get(str(gid).lower())
            if g is None or str(g.get("_type", "")).lower() != "microsoft.dashboard/grafana":
                return _err("InvalidGrafanaWorkspace", f"The Azure Managed Grafana workspace '{gid}' was not found.")
            ints = g["properties"].setdefault("grafanaIntegrations", {"azureMonitorWorkspaceIntegrations": []}).setdefault("azureMonitorWorkspaceIntegrations", [])
            if not any(str(i.get("azureMonitorWorkspaceResourceId", "")).lower() == mw["id"].lower() for i in ints):
                ints.append({"azureMonitorWorkspaceResourceId": mw["id"]})
            met["grafanaResourceId"] = g["id"]
            state[rid.lower()]["_link"]["grafana"] = g["id"]
            met.pop("createGrafana", None)
    elif amp or _prom_dcr(state, rec) is not None:
        _unlink_prom(state, rec)
    return None


def _prom_dcr(state, rec):
    return next((v for v in state.values() if isinstance(v, dict) and v.get("_owner") == rec["id"].lower() and v.get("_aksmon") == "prom"), None)


def _unlink_prom(state, rec):
    d = _prom_dcr(state, rec)
    link = (d or {}).get("_link") or {}
    g = state.get(str(link.get("grafana") or "").lower())
    if g is not None:
        ints = g["properties"].get("grafanaIntegrations", {}).get("azureMonitorWorkspaceIntegrations", [])
        g["properties"]["grafanaIntegrations"]["azureMonitorWorkspaceIntegrations"] = [
            i for i in ints if str(i.get("azureMonitorWorkspaceResourceId", "")).lower() != str(link.get("workspace", "")).lower()]
    _drop(state, rec, "prom", PROM)


def cleanup(state, rec):
    _drop(state, rec, "ci", MSCI)
    _unlink_prom(state, rec)
