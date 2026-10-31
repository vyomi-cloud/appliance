/* Azure Monitor (Microsoft.Insights) + Log Analytics (Microsoft.OperationalInsights) over the
 * native ARM wire: `/_wire/subscriptions/{sub}/…?api-version=…`. Served by
 * core/azure_monitor_core.py and core/azure_operationalinsights_core.py on every substrate
 * (appliance: providers/azure_services.handle_arm; Nano + dev server: core/azure_arm_core.AzureArm),
 * so whatever the console creates an azure-mgmt-monitor / azure-mgmt-loganalytics SDK or `az`
 * CLI sees, and the reverse.
 * Not modelled by the backend (core/azure_monitor_core.py docstring): metric definitions/values,
 * scheduled query rules. Pages for those stay honest. */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ACTION_GROUPS = armType("Microsoft.Insights", "actionGroups", "2023-01-01");
export const METRIC_ALERTS = armType("Microsoft.Insights", "metricAlerts", "2018-03-01");
export const ACTIVITY_LOG_ALERTS = armType("Microsoft.Insights", "activityLogAlerts", "2020-10-01");
export const AUTOSCALE = armType("Microsoft.Insights", "autoscaleSettings", "2022-10-01");
export const WORKSPACES = armType("Microsoft.OperationalInsights", "workspaces", "2022-10-01");
export const WORKBOOKS = armType("Microsoft.Insights", "workbooks", "2022-04-01");
export const DATA_COLLECTION_RULES = armType("Microsoft.Insights", "dataCollectionRules", "2023-03-11");
export const DATA_COLLECTION_ENDPOINTS = armType("Microsoft.Insights", "dataCollectionEndpoints", "2023-03-11");
export const PRIVATE_LINK_SCOPES = armType("Microsoft.Insights", "privateLinkScopes", "2021-07-01-preview");

const withRg = (a) => ({ ...a, resourceGroup: parseId(a.id).resourceGroup });

// ── action groups ───────────────────────────────────────────────────────────────────
export const listActionGroups = async () => (await ACTION_GROUPS.list()).map(withRg);
export const getActionGroup = (rg, name) => ACTION_GROUPS.get(rg, name).then(withRg);
export const putActionGroup = (rg, name, body) => ACTION_GROUPS.put(rg, name, body);
export const deleteActionGroup = (rg, name) => ACTION_GROUPS.remove(rg, name);
export const subscribeActionGroupReceiver = (rg, name, receiverName) => ACTION_GROUPS.action(rg, name, "subscribe", { receiverName });
export const sendTestNotification = (rg, name, alertType = "servicehealth") => ACTION_GROUPS.action(rg, name, "createNotifications", { alertType });

// ── metric alert rules ──────────────────────────────────────────────────────────────
export const listMetricAlerts = async () => (await METRIC_ALERTS.list()).map(withRg);
export const getMetricAlert = (rg, name) => METRIC_ALERTS.get(rg, name).then(withRg);
export const putMetricAlert = (rg, name, body) => METRIC_ALERTS.put(rg, name, body);
export const deleteMetricAlert = (rg, name) => METRIC_ALERTS.remove(rg, name);

// ── activity log alert rules ─────────────────────────────────────────────────────────
export const listActivityLogAlerts = async () => (await ACTIVITY_LOG_ALERTS.list()).map(withRg);
export const putActivityLogAlert = (rg, name, body) => ACTIVITY_LOG_ALERTS.put(rg, name, body);
export const deleteActivityLogAlert = (rg, name) => ACTIVITY_LOG_ALERTS.remove(rg, name);

/** Both alert rule types normalized into one shape for the combined "Alerts" grid. */
export async function listAlertRules() {
  const [metric, activity] = await Promise.all([listMetricAlerts(), listActivityLogAlerts()]);
  return [
    ...metric.map((r) => ({ id: r.id, name: r.name, resourceGroup: r.resourceGroup, kind: "Metric", severity: r.properties.severity,
      enabled: r.properties.enabled, scopes: r.properties.scopes, condition: conditionSummary(r), raw: r })),
    ...activity.map((r) => ({ id: r.id, name: r.name, resourceGroup: r.resourceGroup, kind: "Activity Log", severity: null,
      enabled: r.properties.enabled, scopes: r.properties.scopes, condition: activityConditionSummary(r), raw: r })),
  ];
}
export function conditionSummary(rule) {
  const c = (rule.properties.criteria?.allOf || [])[0];
  if (!c) return "--";
  return `${c.metricName} ${c.operator === "GreaterThan" ? ">" : c.operator === "LessThan" ? "<" : c.operator} ${c.threshold ?? ""}`.trim();
}
export function activityConditionSummary(rule) {
  const cat = (rule.properties.condition?.allOf || []).find((c) => c.field?.toLowerCase() === "category");
  return cat ? `Category = ${cat.equals}` : "--";
}
export const SEVERITY_LABEL = { 0: "0 - Critical", 1: "1 - Error", 2: "2 - Warning", 3: "3 - Informational", 4: "4 - Verbose" };

// ── autoscale settings ───────────────────────────────────────────────────────────────
export const listAutoscaleSettings = async () => (await AUTOSCALE.list()).map(withRg);
export const getAutoscaleSetting = (rg, name) => AUTOSCALE.get(rg, name).then(withRg);
export const putAutoscaleSetting = (rg, name, body) => AUTOSCALE.put(rg, name, body);
export const deleteAutoscaleSetting = (rg, name) => AUTOSCALE.remove(rg, name);

// ── activity log (Microsoft.Insights/eventtypes, subscription-wide ARM activity feed) ──
export async function listActivityLog(resourceId) {
  const query = { "api-version": "2015-04-01" };
  if (resourceId) query["$filter"] = `resourceUri eq '${resourceId}'`;
  const r = await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query });
  return r.value || [];
}

// ── Log Analytics workspaces (Microsoft.OperationalInsights) ───────────────────────────
export const listWorkspaces = async () => (await WORKSPACES.list()).map(withRg);
export const getWorkspace = (rg, name) => WORKSPACES.get(rg, name).then(withRg);
export const putWorkspace = (rg, name, body) => WORKSPACES.put(rg, name, body);
export const deleteWorkspace = (rg, name) => WORKSPACES.remove(rg, name);
export const WORKSPACE_SKUS = ["PerGB2018", "Free", "Standalone", "PerNode", "Standard", "Premium", "CapacityReservation"];

// ── workbooks (Microsoft.Insights/workbooks) ────────────────────────────────────────
export const listWorkbooks = async () => (await WORKBOOKS.list()).map(withRg);
export const putWorkbook = (rg, name, body) => WORKBOOKS.put(rg, name, body);
export const deleteWorkbook = (rg, name) => WORKBOOKS.remove(rg, name);

// ── data collection rules (Microsoft.Insights/dataCollectionRules) ──────────────────
export const listDataCollectionRules = async () => (await DATA_COLLECTION_RULES.list()).map(withRg);
export const putDataCollectionRule = (rg, name, body) => DATA_COLLECTION_RULES.put(rg, name, body);
export const deleteDataCollectionRule = (rg, name) => DATA_COLLECTION_RULES.remove(rg, name);

// ── data collection endpoints (Microsoft.Insights/dataCollectionEndpoints) ──────────
export const listDataCollectionEndpoints = async () => (await DATA_COLLECTION_ENDPOINTS.list()).map(withRg);
export const putDataCollectionEndpoint = (rg, name, body) => DATA_COLLECTION_ENDPOINTS.put(rg, name, body);
export const deleteDataCollectionEndpoint = (rg, name) => DATA_COLLECTION_ENDPOINTS.remove(rg, name);

// ── private link scopes (Microsoft.Insights/privateLinkScopes) ─────────────────────
export const listPrivateLinkScopes = async () => (await PRIVATE_LINK_SCOPES.list()).map(withRg);
export const putPrivateLinkScope = (rg, name, body) => PRIVATE_LINK_SCOPES.put(rg, name, body);
export const deletePrivateLinkScope = (rg, name) => PRIVATE_LINK_SCOPES.remove(rg, name);

// ── diagnostic settings (Microsoft.Insights/diagnosticSettings) — a real ARM extension
// resource scoped to ANY other resource's own id (the path re-enters "providers", the same
// shape Microsoft.Authorization/locks uses), so it's a plain restJson call keyed off the
// resource's own full id rather than an armType() (which only knows RG-scoped collections).
export const DIAGNOSTIC_SETTINGS_API_VERSION = "2021-05-01-preview";
export const listDiagnosticSettings = async (resourceId) =>
  (await restJson("GET", `${resourceId}/providers/Microsoft.Insights/diagnosticSettings`,
    { query: { "api-version": DIAGNOSTIC_SETTINGS_API_VERSION } })).value || [];
export const putDiagnosticSetting = (resourceId, name, body) =>
  restJson("PUT", `${resourceId}/providers/Microsoft.Insights/diagnosticSettings/${encodeURIComponent(name)}`,
    { query: { "api-version": DIAGNOSTIC_SETTINGS_API_VERSION }, body });
export const deleteDiagnosticSetting = (resourceId, name) =>
  restJson("DELETE", `${resourceId}/providers/Microsoft.Insights/diagnosticSettings/${encodeURIComponent(name)}`,
    { query: { "api-version": DIAGNOSTIC_SETTINGS_API_VERSION } });

// ── generic resource inventory (Insights per-resource-type dashboards, Metrics scope) ──
// Microsoft.Insights has no metric-VALUE data plane in Vyomi (not modelled); these dashboards
// show the real inventory of each resource type instead of a telemetry rollup.
export const RESOURCE_TYPES = [
  { provider: "Microsoft.Compute", type: "virtualMachines", apiVersion: "2023-09-01", label: "Virtual machine" },
  { provider: "Microsoft.Storage", type: "storageAccounts", apiVersion: "2023-01-01", label: "Storage account" },
  { provider: "Microsoft.Web", type: "sites", apiVersion: "2023-12-01", label: "App Service" },
  { provider: "Microsoft.Network", type: "virtualNetworks", apiVersion: "2023-11-01", label: "Virtual network" },
  { provider: "Microsoft.DocumentDB", type: "databaseAccounts", apiVersion: "2024-05-15", label: "Azure Cosmos DB account" },
  { provider: "Microsoft.KeyVault", type: "vaults", apiVersion: "2023-07-01", label: "Key vault" },
  { provider: "Microsoft.ServiceBus", type: "namespaces", apiVersion: "2022-10-01-preview", label: "Service Bus namespace" },
];
export async function listResourcesOfType(rt) {
  const items = await armType(rt.provider, rt.type, rt.apiVersion).list();
  return items.map(withRg);
}
/** Vyomi's full real inventory across every type a Monitor scope picker would offer. */
export async function listAllResources() {
  const lists = await Promise.all(RESOURCE_TYPES.map((rt) => listResourcesOfType(rt).catch(() => [])));
  return RESOURCE_TYPES.flatMap((rt, i) => lists[i].map((r) => ({ ...r, resourceType: `${rt.provider}/${rt.type}`, typeLabel: rt.label })));
}
export const LOCATIONS_OF = (resources) => [...new Set(resources.map((r) => r.location).filter(Boolean))].sort();
