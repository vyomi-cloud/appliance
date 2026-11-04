/* Monitor's own left nav (the service IS the nav tree, same shape as Cost Management —
 * consoles/src/azure/services/cost/CostShell.jsx — unlike a per-resource blade). `pageTitle`
 * is the exact text after "Monitor | " in ui-spec/azure/monitor.json's page title (one page,
 * "Gallery", differs from its nav label, so callers pass it explicitly rather than deriving
 * it from the menu label). */
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Glyph } from "../../kit/common.jsx";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "alerts", label: "Alerts" },
  { id: "metrics", label: "Metrics" },
  { id: "observabilityagents", label: "Observability agents (preview)" },
  { id: "issues", label: "Issues" },
  { id: "logs", label: "Logs" },
  { id: "healthmodels", label: "Health models" },
  { id: "changeanalysis", label: "Change Analysis" },
  { id: "servicehealth", label: "Service health" },
  { id: "workbooks", label: "Workbooks" },
  { id: "grafanadashboards", label: "Dashboards with Grafana" },
  { group: "Insights", items: [
    { id: "insights-applications", label: "Applications" },
    { id: "insights-vms", label: "Virtual Machines" },
    { id: "insights-storage", label: "Storage accounts" },
    { id: "insights-containers", label: "Containers" },
    { id: "insights-networks", label: "Networks" },
    { id: "insights-cosmosdb", label: "Azure Cosmos DB" },
    { id: "insights-keyvaults", label: "Key Vaults" },
    { id: "insights-redis", label: "Azure Cache for Redis" },
    { id: "insights-dataexplorer", label: "Azure Data Explorer Clusters" },
    { id: "loganalyticsworkspaces", label: "Log Analytics workspaces" },
    { id: "insights-azurelocal", label: "Azure Local" },
    { id: "insights-servicebus", label: "Service Bus (preview)" },
    { id: "insightshub", label: "Insights Hub" },
  ] },
  { group: "Managed Services", items: [
    { id: "managedprometheus", label: "Managed Prometheus" },
    { id: "managedgrafana", label: "Azure Managed Grafana" },
    { id: "scommanagedinstance", label: "Azure Monitor SCOM managed instance" },
  ] },
  { group: "Settings", items: [
    { id: "diagnosticsettings", label: "Diagnostic settings" },
    { id: "datacollectionrules", label: "Data Collection Rules" },
    { id: "datacollectionendpoints", label: "Data Collection Endpoints" },
    { id: "pipelines", label: "Azure Monitor pipelines" },
    { id: "autoscale", label: "Autoscale" },
    { id: "privatelinkscopes", label: "Private Link Scopes" },
    { id: "monitoringcoverage", label: "Monitoring Coverage" },
  ] },
  { group: "Support + Troubleshooting", items: [
    { id: "advisor", label: "Advisor recommendations" },
    { id: "support", label: "New support request" },
  ] },
];

const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));

export default function MonitorShell({ active, pageTitle, children }) {
  return (
    <ResourceBlade title="Monitor" subtitle={(pageTitle || LABEL[active]) && `| ${pageTitle || LABEL[active]}`} glyph={<Glyph id="monitor" size={28} />}
      menu={MENU} active={active} hrefFor={(id) => `#/monitor/${id}`}>
      <div className="vy-page">{children}</div>
    </ResourceBlade>
  );
}
