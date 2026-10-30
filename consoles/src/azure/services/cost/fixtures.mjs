/* Liveness fixtures for consoles/tests/ui-conformance.mjs — each creates a uniquely named
 * resource over the native ARM wire (svc: null — Azure sends no AWS signature) and returns
 * the text the page must show back. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "cloudlearn-rg";

async function createResource(wire, uniq) {
  const name = `uic${uniq}`.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 24);
  await wire("PUT", `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${name}`, {
    svc: null, body: { location: "eastus" },
  });
  return name;
}

async function createBudget(wire, uniq) {
  await createResource(wire, uniq);                 // real spend for the budget to evaluate against
  const name = `uic-budget-${uniq}`;
  await wire("PUT", `/subscriptions/${SUB}/providers/Microsoft.Consumption/budgets/${name}`, {
    svc: null, body: { properties: { amount: 0.01, notifications: { Actual_GreaterThan_1: { enabled: true, threshold: 1, thresholdType: "Actual" } } } },
  });
  return name;
}

async function createSavingsPlan(wire, uniq) {
  const name = `uic-sp-${uniq}`;
  await wire("PUT", `/subscriptions/${SUB}/providers/Microsoft.BillingBenefits/savingsPlanOrders/${name}`, {
    svc: null, body: { properties: { term: "P1Y", appliedScopeType: "Shared", commitment: { amount: 0.1, currency: "USD", grain: "Hourly" } } },
  });
  return name;
}

export default {
  "az-cost-resource": createResource,
  "az-cost-budget": createBudget,
  "az-cost-savingsplan": createSavingsPlan,
};
