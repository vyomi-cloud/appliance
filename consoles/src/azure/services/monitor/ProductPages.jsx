/* Managed Prometheus (Azure Monitor workspaces), Azure Managed Grafana and "Dashboards with Grafana".
 * Real control plane (core/azure_monitorproducts_core.py): Microsoft.Monitor/accounts (creates its managed
 * DCE + DCR), Microsoft.Dashboard/grafana (validates its Azure Monitor workspace integrations).
 * No Prometheus scraping and no running Grafana server exist, so the dashboard page renders Vyomi's own
 * real metric (Activity-log operations) itself and says so. */
import { useMemo, useState } from "react";
import { Button, Field, Input, Select } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, InfoBar, Loading } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { listResourceGroups, locationLabel, LOCATIONS } from "../../kit/arm.js";
import { deleteGrafana, deleteMonitorAccount, listActivityLog, listGrafana, listMonitorAccounts, putGrafana, putMonitorAccount } from "./api.js";

const Row = ({ label, children }) => <div className="vy-form-row"><label>{label}</label><div>{children}</div></div>;

function RgLocation({ f, set }) {
  const rgs = useAsync(() => listResourceGroups().catch(() => []), []);
  return (
    <>
      <Row label="Resource group"><Select value={f.rg} onChange={(_, d) => set({ rg: d.value })} aria-label="Resource group">
        <option value="cloudlearn-rg">cloudlearn-rg</option>{(rgs.data || []).filter((r) => r.name !== "cloudlearn-rg").map((r) => <option key={r.name}>{r.name}</option>)}</Select></Row>
      <Row label="Region"><Select value={f.region} onChange={(_, d) => set({ region: d.value })} aria-label="Region">{LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}</Select></Row>
    </>
  );
}

export function ManagedPrometheus() {
  const notify = useNotify();
  const list = useAsync(listMonitorAccounts, []);
  const [form, setForm] = useState(null);
  const set = (p) => setForm((f) => ({ ...f, ...p }));
  const create = async () => {
    try { await putMonitorAccount(form.rg, form.name, { location: form.region, properties: {} }); notify.success(`Azure Monitor workspace '${form.name}' created.`, "Create succeeded"); setForm(null); list.reload(); }
    catch (e) { notify.error(e, "Failed to create the Azure Monitor workspace"); }
  };
  return (
    <MonitorShell active="managedprometheus" pageTitle="Managed Prometheus">
      <CapabilityContainer id="azure.monitor.managed_prometheus" title="Azure Monitor workspaces (Managed Prometheus)">
        {form ? (
          <section className="vy-form-section" aria-label="Create Azure Monitor workspace">
            <h3>Create an Azure Monitor workspace</h3>
            <RgLocation f={form} set={set} />
            <Field label="Name"><Input value={form.name} onChange={(_, d) => set({ name: d.value })} aria-label="Workspace name" /></Field>
            <div className="vy-cmdbar"><Button appearance="primary" disabled={!form.name} onClick={create}>Create</Button> <Button onClick={() => setForm(null)}>Cancel</Button></div>
          </section>
        ) : (
          <BrowseGrid resourceName="Azure Monitor workspace" rowKey={(r) => r.id} items={list.data || []} loading={list.loading} error={list.error} onRefresh={list.reload}
            onCreate={() => setForm({ name: "", rg: "cloudlearn-rg", region: "eastus" })}
            onDelete={async (rows) => { try { await Promise.all(rows.map((r) => deleteMonitorAccount(r.resourceGroup, r.name))); } catch (e) { notify.error(e, "Failed to delete"); } list.reload(); }}
            csvName="azure-monitor-workspaces.csv"
            columns={[
              { key: "name", label: "Name" }, { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
              { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
              { key: "q", label: "Prometheus query endpoint", value: (r) => r.properties.metrics?.prometheusQueryEndpoint },
              { key: "dcr", label: "Data collection rule", value: (r) => (r.properties.defaultIngestionSettings?.dataCollectionRuleResourceId || "").split("/").pop() },
            ]} />
        )}
        <InfoBar>The workspace and its managed data collection endpoint and rule are real ARM resources. Vyomi does not scrape or ingest Prometheus metrics, so the query endpoint never returns data.</InfoBar>
      </CapabilityContainer>
    </MonitorShell>
  );
}

export function ManagedGrafana() {
  const notify = useNotify();
  const list = useAsync(listGrafana, []);
  const accounts = useAsync(() => listMonitorAccounts().catch(() => []), []);
  const [form, setForm] = useState(null);
  const set = (p) => setForm((f) => ({ ...f, ...p }));
  const create = async () => {
    try {
      await putGrafana(form.rg, form.name, { location: form.region, sku: { name: form.sku }, identity: { type: "SystemAssigned" },
        properties: { grafanaMajorVersion: form.major, grafanaIntegrations: { azureMonitorWorkspaceIntegrations: form.ws ? [{ azureMonitorWorkspaceResourceId: form.ws }] : [] } } });
      notify.success(`Grafana workspace '${form.name}' created.`, "Create succeeded"); setForm(null); list.reload();
    } catch (e) { notify.error(e, "Failed to create the Grafana workspace"); }
  };
  return (
    <MonitorShell active="managedgrafana" pageTitle="Azure Managed Grafana">
      <CapabilityContainer id="azure.monitor.managed_grafana" title="Azure Managed Grafana">
        {form ? (
          <section className="vy-form-section" aria-label="Create Grafana workspace">
            <h3>Create a Grafana workspace</h3>
            <RgLocation f={form} set={set} />
            <Field label="Name"><Input value={form.name} onChange={(_, d) => set({ name: d.value })} aria-label="Grafana workspace name" /></Field>
            <Row label="Pricing plan"><Select value={form.sku} onChange={(_, d) => set({ sku: d.value })} aria-label="Pricing plan"><option>Standard</option><option>Essential</option></Select></Row>
            <Row label="Grafana version"><Select value={form.major} onChange={(_, d) => set({ major: d.value })} aria-label="Grafana version"><option>9</option><option>10</option><option>11</option></Select></Row>
            <Row label="Azure Monitor workspace"><Select value={form.ws} onChange={(_, d) => set({ ws: d.value })} aria-label="Azure Monitor workspace"><option value="">None</option>{(accounts.data || []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Row>
            <div className="vy-cmdbar"><Button appearance="primary" disabled={!form.name} onClick={create}>Create</Button> <Button onClick={() => setForm(null)}>Cancel</Button></div>
          </section>
        ) : (
          <BrowseGrid resourceName="Grafana workspace" rowKey={(r) => r.id} items={list.data || []} loading={list.loading} error={list.error} onRefresh={list.reload}
            onCreate={() => setForm({ name: "", rg: "cloudlearn-rg", region: "eastus", sku: "Standard", major: "11", ws: "" })}
            onDelete={async (rows) => { try { await Promise.all(rows.map((r) => deleteGrafana(r.resourceGroup, r.name))); } catch (e) { notify.error(e, "Failed to delete"); } list.reload(); }}
            csvName="grafana-workspaces.csv"
            columns={[
              { key: "name", label: "Name" }, { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
              { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
              { key: "sku", label: "Pricing plan", value: (r) => r.sku?.name },
              { key: "ver", label: "Grafana version", value: (r) => r.properties.grafanaVersion },
              { key: "ep", label: "Endpoint", value: (r) => r.properties.endpoint },
              { key: "int", label: "Azure Monitor workspaces", value: (r) => (r.properties.grafanaIntegrations?.azureMonitorWorkspaceIntegrations || []).map((i) => i.azureMonitorWorkspaceResourceId.split("/").pop()).join(", ") || "--" },
            ]} />
        )}
        <InfoBar>The Grafana workspace is a real ARM resource (endpoint, version, identity, Azure Monitor workspace integrations validated). Vyomi does not run a Grafana server, so the endpoint is not a live web app; see Dashboards with Grafana for a dashboard of Vyomi's real metrics.</InfoBar>
      </CapabilityContainer>
    </MonitorShell>
  );
}

function Bars({ rows, label }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <svg width={640} height={Math.max(40, rows.length * 24 + 8)} role="img" aria-label={label} style={{ maxWidth: "100%" }}>
      {rows.map((r, i) => (
        <g key={r.label} transform={`translate(0, ${i * 24 + 4})`}>
          <text x={0} y={14} fontSize="12" fill="currentColor">{r.label}</text>
          <rect x={230} y={2} width={Math.max(2, (r.value / max) * 360)} height={16} fill="#0078d4" />
          <text x={236 + (r.value / max) * 360} y={14} fontSize="12" fill="currentColor">{r.value}</text>
        </g>
      ))}
    </svg>
  );
}

export function DashboardsWithGrafana() {
  const graf = useAsync(() => listGrafana().catch(() => []), []);
  const acts = useAsync(() => listActivityLog(), []);
  const [hours, setHours] = useState(24);
  const stats = useMemo(() => {
    const cutoff = Date.now() - hours * 3600000;
    const rows = (acts.data || []).filter((a) => Date.parse(a.eventTimestamp) >= cutoff);
    const byType = {}, byHour = {};
    for (const a of rows) {
      const t = (a.operationName?.value || "").split("/").slice(0, 2).join("/") || "other";
      byType[t] = (byType[t] || 0) + 1;
      const h = new Date(a.eventTimestamp).toISOString().slice(0, 13);
      byHour[h] = (byHour[h] || 0) + 1;
    }
    return { total: rows.length, types: Object.entries(byType).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([label, value]) => ({ label, value })),
      hours: Object.entries(byHour).sort().slice(-12).map(([label, value]) => ({ label: label.replace("T", " ") + ":00Z", value })) };
  }, [acts.data, hours]);
  return (
    <MonitorShell active="grafanadashboards" pageTitle="Dashboards with Grafana">
      <CapabilityContainer id="azure.monitor.grafana_dashboards" title="Dashboards">
        <h4>Grafana workspaces</h4>
        {graf.loading ? <Loading /> : (graf.data || []).length ? (
          <ul style={{ margin: 0, paddingLeft: 18 }}>{graf.data.map((g) => <li key={g.id}>{g.name} - {g.properties.endpoint} (Grafana {g.properties.grafanaVersion})</li>)}</ul>
        ) : <p>No Grafana workspaces yet. <a href="#/monitor/managedgrafana">Create one</a>.</p>}
        <h4>Vyomi activity dashboard</h4>
        <Row label="Time range"><Select value={String(hours)} onChange={(_, d) => setHours(Number(d.value))} aria-label="Time range">
          <option value="1">Last hour</option><option value="24">Last 24 hours</option><option value="168">Last 7 days</option></Select></Row>
        <ErrorBar error={acts.error} title="Failed to load activity" />
        {acts.loading ? <Loading /> : (
          <>
            <p data-testid="dash-total"><b>{stats.total}</b> operations recorded</p>
            <h5>Operations by resource type</h5>
            <Bars rows={stats.types} label="Operations by resource type" />
            <h5>Operations per hour</h5>
            <Bars rows={stats.hours} label="Operations per hour" />
          </>
        )}
        <InfoBar>This dashboard is rendered by Vyomi itself from the real Activity log. It is not Grafana: Vyomi runs no Grafana server and no Prometheus data source.</InfoBar>
      </CapabilityContainer>
    </MonitorShell>
  );
}
