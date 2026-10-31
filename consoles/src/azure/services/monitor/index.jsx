import Overview from "./Overview.jsx";
import ActivityLog from "./ActivityLog.jsx";
import Alerts from "./Alerts.jsx";
import ActionGroups from "./ActionGroups.jsx";
import CreateActionGroup from "./CreateActionGroup.jsx";
import CreateMetricAlert from "./CreateMetricAlert.jsx";
import Metrics from "./Metrics.jsx";
import Logs from "./Logs.jsx";
import Autoscale from "./Autoscale.jsx";
import CreateAutoscale from "./CreateAutoscale.jsx";
import LogAnalyticsWorkspaces from "./LogAnalyticsWorkspaces.jsx";
import CreateLogAnalyticsWorkspace from "./CreateLogAnalyticsWorkspace.jsx";
import MonitoringCoverage from "./MonitoringCoverage.jsx";
import AdvisorRecommendations from "./AdvisorRecommendations.jsx";
import InsightsHub from "./InsightsHub.jsx";
import ResourceInsights from "./ResourceInsights.jsx";
import ChangeAnalysis from "./ChangeAnalysis.jsx";
import Workbooks from "./Workbooks.jsx";
import CreateWorkbook from "./CreateWorkbook.jsx";
import DataCollectionRules from "./DataCollectionRules.jsx";
import CreateDataCollectionRule from "./CreateDataCollectionRule.jsx";
import DataCollectionEndpoints from "./DataCollectionEndpoints.jsx";
import CreateDataCollectionEndpoint from "./CreateDataCollectionEndpoint.jsx";
import PrivateLinkScopes from "./PrivateLinkScopes.jsx";
import CreatePrivateLinkScope from "./CreatePrivateLinkScope.jsx";
import PrivateLinkScopeResources from "./PrivateLinkScopeResources.jsx";
import DiagnosticSettings from "./DiagnosticSettings.jsx";
import DiagnosticSettingsResource from "./DiagnosticSettingsResource.jsx";
import { RESOURCE_TYPES } from "./api.js";
import { gapRoutes, DashboardsWithGrafana, ManagedPrometheus } from "./StaticPages.jsx";

const crumb = (text, href) => [{ text, href: `#/monitor/${href}` }];
const rt = (provider, type) => RESOURCE_TYPES.find((r) => r.provider === provider && r.type === type);

/** Applications / Virtual Machines / Storage accounts / Networks / Azure Cosmos DB / Key Vaults /
 * Service Bus (preview): real per-type inventory (Insights submenu). */
const INSIGHTS_RESOURCE_PAGES = [
  ["insights-applications", "Applications", "Microsoft.Web", "sites", "#/functionapp/create", false],
  ["insights-vms", "Virtual Machines", "Microsoft.Compute", "virtualMachines", null, false],
  ["insights-storage", "Storage accounts", "Microsoft.Storage", "storageAccounts", "#/storage/create", true],
  ["insights-networks", "Networks", "Microsoft.Network", "virtualNetworks", null, false],
  ["insights-cosmosdb", "Azure Cosmos DB", "Microsoft.DocumentDB", "databaseAccounts", null, false],
  ["insights-keyvaults", "Key Vaults", "Microsoft.KeyVault", "vaults", "#/keyvaults/create", true],
  ["insights-servicebus", "Service Bus (preview)", "Microsoft.ServiceBus", "namespaces", null, false],
];

export default {
  routes: [
    { pattern: "/monitor", component: Overview },
    { pattern: "/monitor/overview", component: Overview },
    { pattern: "/monitor/activitylog", component: ActivityLog, crumbs: () => crumb("Activity log", "activitylog") },
    { pattern: "/monitor/alerts", component: Alerts, crumbs: () => crumb("Alerts", "alerts") },
    { pattern: "/monitor/actiongroups", component: ActionGroups, crumbs: () => crumb("Action groups", "actiongroups") },
    { pattern: "/monitor/createactiongroup", component: CreateActionGroup, crumbs: () => crumb("Create action group", "createactiongroup") },
    { pattern: "/monitor/createalertrule", component: CreateMetricAlert, crumbs: () => crumb("Create an alert rule", "createalertrule") },
    { pattern: "/monitor/metrics", component: Metrics, crumbs: () => crumb("Metrics", "metrics") },
    { pattern: "/monitor/logs", component: Logs, crumbs: () => crumb("Logs", "logs") },
    { pattern: "/monitor/autoscale", component: Autoscale, crumbs: () => crumb("Autoscale", "autoscale") },
    { pattern: "/monitor/createautoscale", component: CreateAutoscale, crumbs: () => crumb("Add an autoscale setting", "createautoscale") },
    { pattern: "/monitor/loganalyticsworkspaces", component: LogAnalyticsWorkspaces, crumbs: () => crumb("Log Analytics workspaces", "loganalyticsworkspaces") },
    { pattern: "/monitor/createloganalyticsworkspace", component: CreateLogAnalyticsWorkspace, crumbs: () => crumb("Create Log Analytics workspace", "createloganalyticsworkspace") },
    { pattern: "/monitor/monitoringcoverage", component: MonitoringCoverage, crumbs: () => crumb("Monitoring Coverage", "monitoringcoverage") },
    { pattern: "/monitor/advisor", component: AdvisorRecommendations, crumbs: () => crumb("Advisor recommendations", "advisor") },
    { pattern: "/monitor/insightshub", component: InsightsHub, crumbs: () => crumb("Insights Hub", "insightshub") },
    { pattern: "/monitor/changeanalysis", component: ChangeAnalysis, crumbs: () => crumb("Change Analysis", "changeanalysis") },
    { pattern: "/monitor/managedprometheus", component: ManagedPrometheus, crumbs: () => crumb("Managed Prometheus", "managedprometheus") },
    { pattern: "/monitor/workbooks", component: Workbooks, crumbs: () => crumb("Gallery", "workbooks") },
    { pattern: "/monitor/createworkbook", component: CreateWorkbook, crumbs: () => crumb("New workbook", "createworkbook") },
    { pattern: "/monitor/grafanadashboards", component: DashboardsWithGrafana, crumbs: () => crumb("Dashboards with Grafana", "grafanadashboards") },
    { pattern: "/monitor/datacollectionrules", component: DataCollectionRules, crumbs: () => crumb("Data Collection Rules", "datacollectionrules") },
    { pattern: "/monitor/createdatacollectionrule", component: CreateDataCollectionRule, crumbs: () => crumb("Create a data collection rule", "createdatacollectionrule") },
    { pattern: "/monitor/datacollectionendpoints", component: DataCollectionEndpoints, crumbs: () => crumb("Data Collection Endpoints", "datacollectionendpoints") },
    { pattern: "/monitor/createdatacollectionendpoint", component: CreateDataCollectionEndpoint, crumbs: () => crumb("Create data collection endpoint", "createdatacollectionendpoint") },
    { pattern: "/monitor/privatelinkscopes", component: PrivateLinkScopes, crumbs: () => crumb("Private Link Scopes", "privatelinkscopes") },
    { pattern: "/monitor/createprivatelinkscope", component: CreatePrivateLinkScope, crumbs: () => crumb("Create Azure Monitor Private Link Scope", "createprivatelinkscope") },
    { pattern: "/monitor/privatelinkscoperesources", component: PrivateLinkScopeResources, crumbs: () => crumb("Azure Monitor Resources", "privatelinkscopes") },
    { pattern: "/monitor/diagnosticsettings", component: DiagnosticSettings, crumbs: () => crumb("Diagnostic settings", "diagnosticsettings") },
    { pattern: "/monitor/diagnosticsettingsresource", component: DiagnosticSettingsResource, crumbs: () => crumb("Diagnostic settings", "diagnosticsettings") },
    ...INSIGHTS_RESOURCE_PAGES.map(([id, label, provider, type, createHref, withFilters]) => ({
      pattern: `/monitor/${id}`,
      component: () => <ResourceInsights active={id} pageTitle={label} resourceType={rt(provider, type)} createHref={createHref} withFilters={withFilters} />,
      crumbs: () => crumb(label, id),
    })),
    ...gapRoutes(),
  ],
};
