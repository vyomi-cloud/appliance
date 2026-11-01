/* UI-conformance fixtures for Azure AI services (Microsoft.CognitiveServices ARM control plane). */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const ACCOUNT = "uiccogsvc";
const AV = "api-version=2024-10-01";
const accountPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.CognitiveServices/accounts/${name}?${AV}`;
const deletedPath = (name) => `/subscriptions/${SUB}/providers/Microsoft.CognitiveServices/locations/eastus/resourceGroups/${RG}/deletedAccounts/${name}?${AV}`;

async function ensureAccount(wire) {
  await wire("PUT", accountPath(ACCOUNT), { svc: null, body: { kind: "OpenAI", sku: { name: "S0" }, location: "eastus" } }).catch(() => {});
}

export default {
  "az-cogsvc": async (wire) => { await ensureAccount(wire); },

  "live-account": async (wire, uniq) => { await wire("PUT", accountPath(uniq), { svc: null, body: { kind: "OpenAI", sku: { name: "S0" }, location: "eastus" } }); return uniq; },

  "live-deleted": async (wire, uniq) => {
    await wire("PUT", accountPath(uniq), { svc: null, body: { kind: "OpenAI", sku: { name: "S0" }, location: "eastus" } });
    await wire("DELETE", accountPath(uniq), { svc: null });
    return uniq;
  },

  "live-deployment": async (wire, uniq) => {
    await ensureAccount(wire);
    await wire("PUT", `${accountPath(ACCOUNT).split("?")[0]}/deployments/${uniq}?${AV}`, { svc: null,
      body: { sku: { name: "Standard", capacity: 1 }, properties: { model: { format: "OpenAI", name: "gpt-4o-mini", version: "2024-07-18" } } } });
    return uniq;
  },

  "live-lock": async (wire, uniq) => {
    await ensureAccount(wire);
    await wire("PUT", `${accountPath(ACCOUNT).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },

  // A lock write on the shared account is a real ARM mutation, so it lands on the unified
  // Microsoft.Insights/eventtypes feed (core/azure_arm_core.py) — the lock NAME becomes the
  // activity entry's operationName.localizedValue ("Create lock: {name}"), so it is the
  // uniquely-named thing to look for.
  "live-activity": async (wire, uniq) => {
    await ensureAccount(wire);
    await wire("PUT", `${accountPath(ACCOUNT).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },
};
