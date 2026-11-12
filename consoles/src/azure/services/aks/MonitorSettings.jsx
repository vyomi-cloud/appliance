/* AKS Monitor settings: Container Insights / Managed Prometheus / Grafana toggles, backed by REAL Data Collection Rules,
 * rule associations, an Azure Monitor workspace and a Managed Grafana workspace (core/azure_aksmon_core.py). */
import { useState } from "react";
import { Button, Checkbox, Field, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, InfoBar } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function MonitorSettings({ a, reload }) {
  const notify = useNotify();
  const p = a.properties || {};
  const oms = p.addonProfiles?.omsagent || {};
  const met = p.azureMonitorProfile?.metrics || {};
  const laws = useAsync(() => api.listLogWorkspaces(), [a.id]);
  const dcrs = useAsync(async () => {
    const [rules, assocs] = await Promise.all([api.listDcrs(a.resourceGroup), api.listDcrAssociations(a.id)]);
    const ids = new Set(assocs.map((x) => x.properties?.dataCollectionRuleId?.toLowerCase()));
    return { assocs, rules: rules.filter((r) => ids.has(r.id.toLowerCase())) };
  }, [a.id, oms.enabled, met.enabled, JSON.stringify(met)]);
  const [ci, setCi] = useState(!!oms.enabled);
  const [prom, setProm] = useState(!!met.enabled);
  const [graf, setGraf] = useState(!!met.grafanaResourceId);
  const [law, setLaw] = useState(oms.config?.logAnalyticsWorkspaceResourceID || "");
  const [err, setErr] = useState(null);
  const save = async () => {
    setErr(null);
    try {
      const props = {};
      props.addonProfiles = { omsagent: ci ? { enabled: true, config: { logAnalyticsWorkspaceResourceID: await api.ensureWorkspace(a.resourceGroup, a.location, law) } } : { enabled: false } };
      props.azureMonitorProfile = { metrics: prom ? { enabled: true, ...(graf ? { createGrafana: true } : {}) } : { enabled: false } };
      await api.setMonitoring(a.resourceGroup, a.name, props);
      notify.success("Monitoring settings updated.", "Succeeded");
      reload(); dcrs.reload();
    } catch (e) { setErr(e); }
  };
  return (
    <CapabilityContainer id="azure.aks.monitoring" title={`${a.name} | Monitor settings`}>
      <ErrorBar error={err} title="Update failed" />
      <div style={{ display: "grid", gap: 8, maxWidth: 560 }}>
        <Checkbox checked={ci} onChange={(_, d) => setCi(!!d.checked)} label="Enable Container Insights" aria-label="Enable Container Insights" />
        {ci && <Field label="Log Analytics workspace">
          <Select aria-label="Log Analytics workspace" value={law} onChange={(_, d) => setLaw(d.value)}>
            <option value="">(New) DefaultWorkspace-{a.location}</option>
            {(laws.data || []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </Select>
        </Field>}
        <Checkbox checked={prom} onChange={(_, d) => { setProm(!!d.checked); if (!d.checked) setGraf(false); }} label="Enable Managed Prometheus" aria-label="Enable Managed Prometheus" />
        <Checkbox checked={graf} disabled={!prom} onChange={(_, d) => setGraf(!!d.checked)} label="Enable Managed Grafana" aria-label="Enable Managed Grafana" />
        <div><Button appearance="primary" onClick={save}>Apply</Button></div>
      </div>
      <h3 style={{ marginTop: 20 }}>Linked monitoring resources</h3>
      {met.azureMonitorWorkspaceResourceId && <p>Azure Monitor workspace: <code data-testid="mon-workspace">{met.azureMonitorWorkspaceResourceId.split("/").pop()}</code></p>}
      {met.grafanaResourceId && <p>Managed Grafana: <code data-testid="mon-grafana">{met.grafanaResourceId.split("/").pop()}</code></p>}
      <table className="vy-table" aria-label="Data collection rules" style={{ width: "100%" }}>
        <thead><tr><th align="left">Data collection rule</th><th align="left">Association</th><th align="left">Destination</th></tr></thead>
        <tbody>
          {(dcrs.data?.rules || []).map((r) => {
            const as = dcrs.data.assocs.find((x) => x.properties?.dataCollectionRuleId?.toLowerCase() === r.id.toLowerCase());
            const d = r.properties?.destinations || {};
            const dest = d.logAnalytics?.[0]?.workspaceResourceId || d.monitoringAccounts?.[0]?.accountResourceId || "";
            return <tr key={r.id}><td>{r.name}</td><td>{as?.name}</td><td>{dest.split("/").pop()}</td></tr>;
          })}
          {!(dcrs.data?.rules || []).length && <tr><td colSpan={3}>No data collection rules are associated with this cluster.</td></tr>}
        </tbody>
      </table>
    </CapabilityContainer>
  );
}
