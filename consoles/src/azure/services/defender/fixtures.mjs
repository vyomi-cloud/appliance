/* UI-conformance fixtures for Microsoft Defender for Cloud (Microsoft.Security over ARM). The
 * recommendations are computed from real resources, so the fixtures create resources with a known
 * misconfiguration over the native ARM wire and the pages must then show them. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";

export default {
  "az-defender": async (wire) => {
    await wire("PUT", `/subscriptions/${SUB}/resourcegroups/${RG}?api-version=2021-04-01`, { svc: null, body: { location: "eastus" } }).catch(() => {});
  },

  // A storage account allowing anonymous blob access — Inventory lists it (unhealthy) by name.
  "live-insecure-storage": async (wire, uniq) => {
    await wire("PUT", `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${uniq}?api-version=2023-01-01`,
      { svc: null, body: { location: "eastus", properties: { allowBlobPublicAccess: true } } });
    return uniq;
  },
};
