/* Monitor nav items that are genuine capability gaps for Vyomi (no backend models Container
 * insights, Azure Cache for Redis, Azure Local, SCOM, Grafana/Prometheus managed services,
 * diagnostic settings/DCR/DCE/pipelines, Private Link, support ticketing, …): title + the
 * honest CapabilityContainer panel, driven by core/capabilities/azure/monitor.json — never a
 * hand-written disclaimer. Grouped here (one tiny file per page would be noise), same pattern
 * as consoles/src/azure/services/cost/StaticPages.jsx. */
import { useState } from "react";
import { Tab, TabList } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

/** [route id, exact page title (after "Monitor | "), capability id]. */
const GAPS = [
  ["observabilityagents", "Observability agents (preview)", "azure.monitor.observability_agents"],
  ["issues", "Issues", "azure.monitor.issues"],
  ["healthmodels", "Health models", "azure.monitor.health_models"],
  ["servicehealth", "Service health", "azure.monitor.service_health"],
  ["insights-containers", "Containers", "azure.monitor.containers_insights"],
  ["insights-redis", "Azure Cache for Redis", "azure.monitor.redis_insights"],
  ["insights-dataexplorer", "Azure Data Explorer Clusters", "azure.monitor.data_explorer_insights"],
  ["insights-azurelocal", "Azure Local", "azure.monitor.azure_local_insights"],
  ["managedgrafana", "Azure Managed Grafana", "azure.monitor.managed_grafana"],
  ["scommanagedinstance", "Azure Monitor SCOM managed instance", "azure.monitor.scom_managed_instance"],
  ["datacollectionendpoints", "Data Collection Endpoints", "azure.monitor.data_collection_endpoints"],
  ["pipelines", "Azure Monitor pipelines", "azure.monitor.pipelines"],
  ["privatelinkscopes", "Private Link Scopes", "azure.monitor.private_link_scopes"],
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

export function DiagnosticSettings() {
  return (
    <MonitorShell active="diagnosticsettings">
      <CapabilityContainer id="azure.monitor.diagnostic_settings" title="Diagnostic settings" />
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

