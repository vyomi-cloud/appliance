/* UI-conformance fixtures for Subscriptions (ARM subscription tags + subscription-wide
 * resource groups/resources/deployments/locks/budgets). See resourcegroups/fixtures.mjs for
 * the pattern. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const subPath = () => `/subscriptions/${SUB}`;

export default {
  "az-subscription": async () => {},

  // The one simulated subscription's displayName is never renamed by these fixtures — every
  // page below that needs {resource-name} relies on it staying "CloudLearn Subscription" for
  // the whole conformance run (spec-map.json's static var), so liveness here always comes
  // from a sub-resource (resource group/resource/deployment/lock/budget) instead.
  "live-resourcegroup": async (wire, uniq) => {
    const name = `uic-rg-${uniq}`;
    await wire("PUT", `${subPath()}/resourceGroups/${name}?api-version=2021-04-01`, { svc: null, body: { location: "eastus" } });
    return name;
  },

  "live-resource": async (wire, uniq) => {
    const rg = `uic-rg-${uniq}`;
    const name = `uicsa${uniq}`.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 24);
    await wire("PUT", `${subPath()}/resourceGroups/${rg}?api-version=2021-04-01`, { svc: null, body: { location: "eastus" } });
    await wire("PUT", `${subPath()}/resourceGroups/${rg}/providers/Microsoft.Storage/storageAccounts/${name}?api-version=2023-01-01`,
      { svc: null, body: { location: "eastus" } });
    return name;
  },

  "live-deployment": async (wire, uniq) => {
    const name = `uic-dep-${uniq}`;
    await wire("PUT", `${subPath()}/providers/Microsoft.Resources/deployments/${name}?api-version=2021-04-01`,
      { svc: null, body: { properties: { mode: "Incremental", template: {} } } });
    return name;
  },

  "live-lock": async (wire, uniq) => {
    const name = `uic-lock-${uniq}`;
    await wire("PUT", `${subPath()}/providers/Microsoft.Authorization/locks/${name}?api-version=2016-09-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return name;
  },

  "live-budget": async (wire, uniq) => {
    const name = `uic-budget-${uniq}`;
    await wire("PUT", `${subPath()}/providers/Microsoft.Consumption/budgets/${name}?api-version=2023-11-01`,
      { svc: null, body: { properties: { amount: 100, notifications: {} } } });
    return name;
  },

  // Settings > Usage + quotas: a real public IP, counted live off actual provisioned
  // resources (core/azure_arm_core.py's Microsoft.Network/locations/{loc}/usages) — the
  // page lists the resource names counted toward each quota, so this name renders verbatim.
  "live-usage": async (wire, uniq) => {
    const rg = `uic-quotarg-${uniq}`;
    const name = `uic-pip-${uniq}`;
    await wire("PUT", `${subPath()}/resourceGroups/${rg}?api-version=2021-04-01`, { svc: null, body: { location: "eastus" } });
    await wire("PUT", `${subPath()}/resourceGroups/${rg}/providers/Microsoft.Network/publicIPAddresses/${name}?api-version=2023-11-01`,
      { svc: null, body: { location: "eastus" } });
    return name;
  },
};
