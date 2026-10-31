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
    await wire("PUT", `${servicePath(SVC).split("?")[0]}/providers/Microsoft.Insights/diagnosticSettings/${uniq}?api-version=2021-05-01-preview`,
      { svc: null, body: { properties: {
        storageAccountId: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/uicdiagsa`,
        logs: [{ categoryGroup: "allLogs", enabled: true }],
      } } });
    return uniq;
  },
};
