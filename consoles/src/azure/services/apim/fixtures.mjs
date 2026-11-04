/* UI-conformance fixtures for API Management (native ARM wire — svc: null, no AWS signature).
 * See aws/s3/fixtures.mjs for the contract; keyvaults/fixtures.mjs and eventgrid/fixtures.mjs
 * for the Azure-lens shape (nested sub-resources + Microsoft.Authorization/locks). */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const SVC = "uicapim";
const API_VERSION = "2023-05-01-preview";
const servicePath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${name}?api-version=${API_VERSION}`;
const subPath = (name, kind, id) => `${servicePath(name).split("?")[0]}/${kind}/${id}?api-version=${API_VERSION}`;
const lockPath = (name, lockName) => `${servicePath(name).split("?")[0]}/providers/Microsoft.Authorization/locks/${lockName}?api-version=2020-05-01`;

async function ensureService(wire, name = SVC) {
  await wire("PUT", servicePath(name), { svc: null, body: { location: "eastus", properties: { publisherEmail: "admin@cloudlearn.dev", publisherName: "CloudLearn" } } }).catch(() => {});
}

export default {
  "az-apim": async (wire) => { await ensureService(wire); },

  "live-service": async (wire, uniq) => { await ensureService(wire, uniq); return uniq; },

  "live-api": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "apis", uniq), { svc: null, body: { properties: { displayName: uniq, path: uniq, protocols: ["https"] } } });
    return uniq;
  },

  "live-product": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "products", uniq), { svc: null, body: { properties: { displayName: uniq, state: "published" } } });
    return uniq;
  },

  "live-subscription": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "subscriptions", uniq), { svc: null, body: { properties: { displayName: uniq, scope: "/apis", primaryKey: "simkey1", secondaryKey: "simkey2" } } });
    return uniq;
  },

  "live-namedvalue": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "namedValues", uniq), { svc: null, body: { properties: { displayName: uniq, value: "live" } } });
    return uniq;
  },

  "live-backend": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "backends", uniq), { svc: null, body: { properties: { protocol: "http", url: `https://${uniq}.example.com` } } });
    return uniq;
  },

  // A lock write on the fixed service is a real ARM mutation, so it lands on the unified
  // Microsoft.Insights/eventtypes feed (core/azure_arm_core.py) too — reused for the
  // Activity log liveness check (the lock NAME is the uniquely-named thing to look for).
  "live-lock": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", lockPath(SVC, uniq), { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },

  "live-apitag": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "tags", uniq), { svc: null, body: { properties: { displayName: uniq } } });
    return uniq;
  },

  "live-policyfragment": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "policyFragments", uniq), { svc: null,
      body: { properties: { format: "xml", value: "<fragment><base /></fragment>", description: uniq } } });
    return uniq;
  },

  "live-diagnosticsetting": async (wire, uniq) => {
    await ensureService(wire);
    // The destination storage account must really exist (core/azure_monitor_core.py
    // validates it, v4 WAVE 5b) — create it for real first.
    await wire("PUT", `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/uicdiagsa?api-version=2023-01-01`,
      { svc: null, body: { location: "eastus" } }).catch(() => {});
    await wire("PUT", `${servicePath(SVC).split("?")[0]}/providers/Microsoft.Insights/diagnosticSettings/${uniq}?api-version=2021-05-01-preview`,
      { svc: null, body: { properties: {
        storageAccountId: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/uicdiagsa`,
        logs: [{ categoryGroup: "allLogs", enabled: true }],
      } } });
    return uniq;
  },

  // Developer portal: Users/Groups are real ARM sub-resources (azure.apim.developerportal).
  "live-user": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "users", uniq), { svc: null, body: { properties: { email: `${uniq}@example.com`, firstName: "Live", lastName: "User", state: "active" } } });
    return uniq;
  },

  "live-group": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "groups", uniq), { svc: null, body: { properties: { displayName: uniq, type: "custom" } } });
    return uniq;
  },

  // Tools: Workspaces and Credential manager (azure.apim.workspaces, azure.apim.credentialmanager).
  "live-workspace": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "workspaces", uniq), { svc: null, body: { properties: { displayName: uniq } } });
    return uniq;
  },

  "live-authprovider": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "authorizationProviders", uniq), { svc: null,
      body: { properties: { identityProvider: "generic", oauth2: { grantType: "AuthorizationCode", clientId: "uic", clientSecret: "uic" } } } });
    return uniq;
  },

  // MCP Servers: a real API with apiType "mcp" (azure.apim.mcpservers).
  "live-mcpapi": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "apis", uniq), { svc: null, body: { properties: { displayName: uniq, apiType: "mcp", path: uniq, protocols: ["https"] } } });
    return uniq;
  },

  // Deployment + infrastructure: Certificates and Self-hosted gateways (azure.apim.deployment).
  "live-certificate": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "certificates", uniq), { svc: null, body: { properties: { subject: `CN=${uniq}`, thumbprint: "AABBCCDDEEFF00112233445566778899AABBCCDD", expirationDate: "2030-01-01T00:00:00Z" } } });
    return uniq;
  },

  "live-gateway": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "gateways", uniq), { svc: null, body: { properties: { description: uniq, locationData: { name: "eastus" } } } });
    return uniq;
  },

  // Monitoring: Application Insights (loggers) and Alerts (metricAlerts scoped to the
  // service's own resource id) — azure.apim.monitoring.appinsights / .alerts.
  "live-logger": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", subPath(SVC, "loggers", uniq), { svc: null,
      body: { properties: { loggerType: "applicationInsights", credentials: { instrumentationKey: "00000000-0000-0000-0000-000000000000" } } } });
    return uniq;
  },

  "live-alert": async (wire, uniq) => {
    await ensureService(wire);
    await wire("PUT", `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Insights/metricAlerts/${uniq}?api-version=2018-03-01`,
      { svc: null, body: { location: "global", properties: {
        description: uniq, severity: 3, enabled: true, scopes: [servicePath(SVC).split("?")[0]],
        evaluationFrequency: "PT1M", windowSize: "PT5M",
        criteria: { "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria", allOf: [
          { criterionType: "StaticThresholdCriterion", name: "Crit1", metricName: "Capacity", operator: "GreaterThan", threshold: 80, timeAggregation: "Average" },
        ] },
      } } });
    return uniq;
  },
};
