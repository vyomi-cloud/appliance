/* Liveness fixtures for consoles/tests/ui-conformance.mjs — each creates a uniquely named
 * resource over the native ARM wire (svc: null — Azure sends no AWS signature) and returns
 * the text the page must show back. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "cloudlearn-rg";
const insights = (path, body, av) => (wire, uniq, nameOverride) => {
  const name = nameOverride ? nameOverride(uniq) : `uic${uniq}`.toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 40);
  return wire("PUT", `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Insights/${path}/${name}?api-version=${av}`,
    { svc: null, body: body(name) }).then(() => name);
};

/** A plain resource create — proves Activity log / Change Analysis / Insights Hub, which all
 * read back real ARM writes rather than their own resource type. */
async function createResource(wire, uniq) {
  const name = `uic${uniq}`.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 24);
  await wire("PUT", `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${name}`, {
    svc: null, body: { location: "eastus" },
  });
  return name;
}

const createMetricAlert = insights("metricAlerts", (name) => ({
  location: "global", properties: {
    severity: 3, enabled: true, scopes: [`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/${name}`],
    evaluationFrequency: "PT1M", windowSize: "PT5M",
    criteria: { "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria", allOf: [
      { criterionType: "StaticThresholdCriterion", name: "c1", metricName: "Percentage CPU", operator: "GreaterThan", timeAggregation: "Average", threshold: 80 },
    ] },
  },
}), "2018-03-01");

const createAutoscale = insights("autoscaleSettings", (name) => ({
  location: "eastus", properties: { profiles: [{ name: "default", capacity: { minimum: "1", maximum: "2", default: "1" }, rules: [] }] },
}), "2022-10-01");

const createWorkbook = insights("workbooks", (name) => ({
  location: "eastus", properties: { displayName: name, category: "workbook", serializedData: "{}" },
}), "2022-04-01");

const createDataCollectionRule = insights("dataCollectionRules", () => ({
  location: "eastus", properties: {
    dataSources: {}, destinations: { logAnalytics: [{ name: "dest1", workspaceResourceId: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.OperationalInsights/workspaces/uicws` }] },
    dataFlows: [{ streams: ["Microsoft-Perf"], destinations: ["dest1"] }],
  },
}), "2023-03-11");

const createDataCollectionEndpoint = insights("dataCollectionEndpoints", () => ({
  location: "eastus", properties: {},
}), "2023-03-11");

const createPrivateLinkScope = insights("privateLinkScopes", () => ({
  location: "global", properties: {},
}), "2021-07-01-preview");

/** A resource with a REAL diagnostic setting attached — proves the Microsoft.Insights/
 * diagnosticSettings extension-resource round trip (core/azure_monitor_core.py's
 * find_diagnostic_marker / upsert_diagnostic_setting), not just resource inventory. The
 * Diagnostic settings picker page shows the resource's own name. */
async function createDiagnosticSetting(wire, uniq) {
  const name = `uic${uniq}`.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 24);
  const rid = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${name}`;
  await wire("PUT", rid, { svc: null, body: { location: "eastus" } });
  await wire("PUT", `${rid}/providers/microsoft.insights/diagnosticSettings/diag1?api-version=2021-05-01-preview`, {
    svc: null, body: { properties: { storageAccountId: rid, logs: [{ categoryGroup: "allLogs", enabled: true }] } },
  });
  return name;
}

export default {
  "az-activity-resource": createResource,
  "az-metric-alert": createMetricAlert,
  "az-autoscale": createAutoscale,
  "az-workbook": createWorkbook,
  "az-dcr": createDataCollectionRule,
  "az-dce": createDataCollectionEndpoint,
  "az-privatelinkscope": createPrivateLinkScope,
  "az-diagnostic-setting": createDiagnosticSetting,
};
