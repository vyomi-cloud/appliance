/* UI-conformance fixtures for Resource groups (ARM control plane + resources-in-group +
 * resource-group-scoped locks/deployments). See keyvaults/fixtures.mjs for the pattern. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const rgPath = (name) => `/subscriptions/${SUB}/resourceGroups/${name}`;

async function ensureGroup(wire, name = RG) {
  await wire("PUT", `${rgPath(name)}?api-version=2021-04-01`, { svc: null, body: { location: "eastus" } }).catch(() => {});
}

export default {
  "az-resourcegroup": async (wire) => { await ensureGroup(wire); },

  "live-group": async (wire, uniq) => { await ensureGroup(wire, uniq); return uniq; },

  // A storage account created directly over the wire, inside the shared "uic-rg" group —
  // the Overview blade's Resources tab (GET .../resourceGroups/{rg}/resources) must show it.
  "live-overview": async (wire, uniq) => {
    await ensureGroup(wire);
    await wire("PUT", `${rgPath(RG)}/providers/Microsoft.Storage/storageAccounts/${uniq}?api-version=2023-01-01`,
      { svc: null, body: { location: "eastus" } });
    return uniq;
  },

  // A resource-group-scoped lock write is a real ARM mutation, so it lands on the unified
  // Microsoft.Insights/eventtypes feed (core/azure_arm_core.py) — the lock NAME becomes the
  // activity entry's "detail", so it is the uniquely-named thing to look for.
  "live-activity": async (wire, uniq) => {
    await ensureGroup(wire);
    await wire("PUT", `${rgPath(RG)}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },

  "live-deployment": async (wire, uniq) => {
    await ensureGroup(wire);
    await wire("PUT", `${rgPath(RG)}/providers/Microsoft.Resources/deployments/${uniq}?api-version=2021-04-01`,
      { svc: null, body: { properties: { mode: "Incremental", template: { resources: [] } } } });
    return uniq;
  },

  "live-lock": async (wire, uniq) => {
    await ensureGroup(wire);
    await wire("PUT", `${rgPath(RG)}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },
};
