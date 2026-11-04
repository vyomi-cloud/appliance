/* UI-conformance fixtures for SQL databases (ARM control plane + the azure-sql data-plane
 * query wire). See storage/fixtures.mjs-equivalent note in aws/services/s3/fixtures.mjs. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const SERVER = "uicsqlsrv";
const DB = "uicsqldb";
const serverPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Sql/servers/${name}?api-version=2023-08-01`;
const dbPath = (server, name) => `${serverPath(server).split("?")[0]}/databases/${name}?api-version=2023-08-01`;

async function ensureServer(wire, name = SERVER) {
  await wire("PUT", serverPath(name), { svc: null, body: { location: "eastus", properties: { administratorLogin: "sqladmin", administratorLoginPassword: "Uic#Passw0rd1", version: "12.0" } } }).catch(() => {});
}
async function ensureDb(wire, server = SERVER, name = DB) {
  await ensureServer(wire, server);
  await wire("PUT", dbPath(server, name), {
    svc: null,
    body: { location: "eastus", sku: { name: "GP_S_Gen5", tier: "GeneralPurpose", family: "Gen5", capacity: 2 },
      properties: { collation: "SQL_Latin1_General_CP1_CI_AS", maxSizeBytes: 34359738368, status: "Online", minCapacity: 0.5, autoPauseDelay: 60 } },
  }).catch(() => {});
}

export default {
  "az-sql": async (wire) => { await ensureDb(wire); },

  "live-db": async (wire, uniq) => { await ensureServer(wire); await ensureDb(wire, SERVER, uniq); return uniq; },

  "live-server": async (wire, uniq) => { await ensureServer(wire, uniq); return uniq; },

  "live-lock": async (wire, uniq) => {
    await ensureDb(wire);
    await wire("PUT", `${dbPath(SERVER, DB).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },

  // A lock write on the shared database is a real ARM mutation, so it lands on the unified
  // Microsoft.Insights/eventtypes feed (core/azure_arm_core.py) — the lock NAME becomes the
  // activity entry's "detail", so it is the uniquely-named thing to look for.
  "live-activity": async (wire, uniq) => {
    await ensureDb(wire);
    await wire("PUT", `${dbPath(SERVER, DB).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },

  "live-firewall": async (wire, uniq) => {
    await ensureServer(wire);
    await wire("PUT", `${serverPath(SERVER).split("?")[0]}/firewallRules/${uniq}?api-version=2023-08-01`,
      { svc: null, body: { properties: { startIpAddress: "10.0.0.1", endIpAddress: "10.0.0.1" } } });
    return uniq;
  },
};
