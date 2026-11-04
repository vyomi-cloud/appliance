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
import MonitorShell from "./MonitorShell.jsx";
import SupportPanel from "../../kit/SupportPanel.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

/** [route id, exact page title (after "Monitor | "), capability id]. */
const GAPS = [
  ["insights-azurelocal", "Azure Local", "azure.monitor.azure_local_insights"],
  ["scommanagedinstance", "Azure Monitor SCOM managed instance", "azure.monitor.scom_managed_instance"],
];

function GapPage({ active, title, capId }) {
  return (
    <MonitorShell active={active} pageTitle={title}>
      <CapabilityContainer id={capId} title={title} />
    </MonitorShell>
  );
}

function SupportPage() {
  return (
    <MonitorShell active="support" pageTitle="New support request">
      <SupportPanel service="monitor" title="New support request" />
    </MonitorShell>
  );
}

export const gapRoutes = () => [{ pattern: "/monitor/support", component: SupportPage,
  crumbs: () => [{ text: "New support request", href: "#/monitor/support" }] }].concat(GAPS.map(([id, title, capId]) => ({
  pattern: `/monitor/${id}`, component: () => <GapPage active={id} title={title} capId={capId} />,
  crumbs: () => [{ text: title, href: `#/monitor/${id}` }],
})));
