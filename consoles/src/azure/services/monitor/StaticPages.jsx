/* Monitor nav items that are genuine capability gaps for Vyomi (Azure Local hybrid hardware,
 * Azure Managed Grafana / SCOM managed instance — separate managed services Vyomi does not
 * run, Microsoft support ticketing): title + the honest CapabilityContainer panel, driven by
 * core/capabilities/azure/monitor.json — never a hand-written disclaimer. Grouped here (one
 * tiny file per page would be noise), same pattern as consoles/src/azure/services/cost/StaticPages.jsx.
 * Observability agents, Issues, Health models, Service health, Azure Monitor pipelines and the
 * Container/Redis/Data Explorer Insights pages moved out to their own real pages
 * (ObservabilityAgents.jsx, Issues.jsx, HealthModels.jsx, ServiceHealth.jsx, Pipelines.jsx,
 * ResourceInsights.jsx) once each got a real backend. Data Collection Endpoints, Private Link
 * Scopes and Diagnostic settings moved out earlier the same way. */
import { useState } from "react";
import { Tab, TabList } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

/** [route id, exact page title (after "Monitor | "), capability id]. */
const GAPS = [
  ["insights-azurelocal", "Azure Local", "azure.monitor.azure_local_insights"],
  ["managedgrafana", "Azure Managed Grafana", "azure.monitor.managed_grafana"],
  ["scommanagedinstance", "Azure Monitor SCOM managed instance", "azure.monitor.scom_managed_instance"],
  ["support", "New support request", "azure.monitor.new_support_request"],
];

function GapPage({ active, title, capId }) {
  return (
    <MonitorShell active={active} pageTitle={title}>
      <CapabilityContainer id={capId} title={title} />
    </MonitorShell>
  );
}

export const gapRoutes = () => GAPS.map(([id, title, capId]) => ({
  pattern: `/monitor/${id}`, component: () => <GapPage active={id} title={title} capId={capId} />,
  crumbs: () => [{ text: title, href: `#/monitor/${id}` }],
}));

export function ManagedPrometheus() {
  return (
    <MonitorShell active="managedprometheus">
      <CapabilityContainer id="azure.monitor.managed_prometheus" title="Managed Prometheus" />
    </MonitorShell>
  );
}

export function DashboardsWithGrafana() {
  const [tab, setTab] = useState("all");
  return (
    <MonitorShell active="grafanadashboards">
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Dashboards with Grafana">
        <Tab value="all">All dashboards</Tab>
        <Tab value="saved">Saved dashboards</Tab>
        <Tab value="favorite">Favorite dashboards</Tab>
      </TabList>
      <div style={{ marginTop: 12 }}>
        <CapabilityContainer id="azure.monitor.grafana_dashboards" title="Dashboards with Grafana" />
      </div>
    </MonitorShell>
  );
}

