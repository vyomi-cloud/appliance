/* UI-conformance fixtures for Azure Cosmos DB (ARM control plane + the native Cosmos DB
 * REST data-plane wire). See storage/fixtures.mjs-equivalent note in aws/services/s3/fixtures.mjs. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const ACCOUNT = "uiccosmos";
const accountPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.DocumentDB/databaseAccounts/${name}?api-version=2024-05-15`;

async function ensureAccount(wire, name = ACCOUNT) {
  await wire("PUT", accountPath(name), { svc: null, body: { location: "eastus" } }).catch(() => {});
}

export default {
  "az-cosmos": async (wire) => { await ensureAccount(wire); },

  "live-account": async (wire, uniq) => { await ensureAccount(wire, uniq); return uniq; },

  "live-container": async (wire, uniq) => {
    await ensureAccount(wire);
    await wire("POST", "/dbs", { svc: null, body: { id: "uicdb" } }).catch(() => {});
    await wire("POST", "/dbs/uicdb/colls", { svc: null, body: { id: uniq, partitionKey: { paths: ["/id"], kind: "Hash" } } });
    return uniq;
  },

  // A lock write on the shared account is a real ARM mutation, so it lands on the unified
  // Microsoft.Insights/eventtypes feed (core/azure_arm_core.py) — the lock NAME becomes the
  // activity entry's "detail", so it is the uniquely-named thing to look for.
  "live-activity": async (wire, uniq) => {
    await ensureAccount(wire);
    await wire("PUT", `${accountPath(ACCOUNT).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },

  "live-lock": async (wire, uniq) => {
    await ensureAccount(wire);
    await wire("PUT", `${accountPath(ACCOUNT).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },
};
