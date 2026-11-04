/* Cost Management + Consumption over the native ARM wire: `/_wire/subscriptions/{sub}/…`.
 *   POST {scope}/providers/Microsoft.CostManagement/query                (cost analysis)
 *   GET/PATCH {scope}/providers/Microsoft.CostManagement/alerts[/{n}]    (cost alerts)
 *   POST {scope}/providers/Microsoft.CostManagement/alerts/{n}/dismiss|reactivate
 *   GET/PUT/DELETE/POST(run) {scope}/providers/Microsoft.CostManagement/exports[/{n}[/run]]
 *   GET/PUT/DELETE {scope}/providers/Microsoft.Consumption/budgets[/{n}]
 * Served by core/azure_cost_core.py on every substrate, over the SAME flat ARM resource
 * store storage accounts/VMs/… live in — so cost analysis reads Vyomi's real inventory. */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, getSubscriptionInfo, parseId } from "../../kit/arm.js";

const API_VERSION = "2023-11-01";
const scope = (rg) => `/subscriptions/${getSubscription()}${rg ? `/resourceGroups/${encodeURIComponent(rg)}` : ""}`;
const q = { "api-version": API_VERSION };

// ── scope ────────────────────────────────────────────────────────────────────────────
export const listSubscriptions = async () => [await getSubscriptionInfo()];

// ── cost analysis ────────────────────────────────────────────────────────────────────
export const costQuery = (body, rg) => restJson("POST", `${scope(rg)}/providers/Microsoft.CostManagement/query`, { query: q, body });

// ── budgets (Microsoft.Consumption) ──────────────────────────────────────────────────
export const listBudgets = async (rg) => (await restJson("GET", `${scope(rg)}/providers/Microsoft.Consumption/budgets`, { query: q })).value || [];
export const getBudget = (name, rg) => restJson("GET", `${scope(rg)}/providers/Microsoft.Consumption/budgets/${encodeURIComponent(name)}`, { query: q });
export const putBudget = (name, body, rg) => restJson("PUT", `${scope(rg)}/providers/Microsoft.Consumption/budgets/${encodeURIComponent(name)}`, { query: q, body });
export const deleteBudget = (name, rg) => restJson("DELETE", `${scope(rg)}/providers/Microsoft.Consumption/budgets/${encodeURIComponent(name)}`, { query: q });

// ── cost alerts (Microsoft.CostManagement/alerts, derived from budgets) ─────────────
export const listAlerts = async (rg) => (await restJson("GET", `${scope(rg)}/providers/Microsoft.CostManagement/alerts`, { query: q })).value || [];
export const dismissAlert = (name, rg) => restJson("POST", `${scope(rg)}/providers/Microsoft.CostManagement/alerts/${encodeURIComponent(name)}/dismiss`, { query: q, body: {} });
export const reactivateAlert = (name, rg) => restJson("POST", `${scope(rg)}/providers/Microsoft.CostManagement/alerts/${encodeURIComponent(name)}/reactivate`, { query: q, body: {} });

// ── exports (Microsoft.CostManagement/exports) ──────────────────────────────────────
export const listExports = async (rg) => (await restJson("GET", `${scope(rg)}/providers/Microsoft.CostManagement/exports`, { query: q })).value || [];
export const putExport = (name, body, rg) => restJson("PUT", `${scope(rg)}/providers/Microsoft.CostManagement/exports/${encodeURIComponent(name)}`, { query: q, body });
export const deleteExport = (name, rg) => restJson("DELETE", `${scope(rg)}/providers/Microsoft.CostManagement/exports/${encodeURIComponent(name)}`, { query: q });
export const runExport = (name, rg) => restJson("POST", `${scope(rg)}/providers/Microsoft.CostManagement/exports/${encodeURIComponent(name)}/run`, { query: q, body: {} });

// ── savings plans (Microsoft.BillingBenefits/savingsPlanOrders) ─────────────────────
export const listSavingsPlans = async () => (await restJson("GET", `${scope()}/providers/Microsoft.BillingBenefits/savingsPlanOrders`, { query: q })).value || [];
export const putSavingsPlan = (name, body) => restJson("PUT", `${scope()}/providers/Microsoft.BillingBenefits/savingsPlanOrders/${encodeURIComponent(name)}`, { query: q, body });
export const deleteSavingsPlan = (name) => restJson("DELETE", `${scope()}/providers/Microsoft.BillingBenefits/savingsPlanOrders/${encodeURIComponent(name)}`, { query: q });
export const SAVINGSPLAN_TERMS = ["P1Y", "P3Y"];
export const SAVINGSPLAN_TERM_LABEL = { P1Y: "1 year", P3Y: "3 years" };
export const SAVINGSPLAN_SCOPES = ["Shared", "Single subscription"];

// ── reservations (Microsoft.Capacity/reservationOrders) ─────────────────────────────
export const listReservations = async () => (await restJson("GET", `${scope()}/providers/Microsoft.Capacity/reservationOrders`, { query: q })).value || [];
export const putReservation = (name, body) => restJson("PUT", `${scope()}/providers/Microsoft.Capacity/reservationOrders/${encodeURIComponent(name)}`, { query: q, body });
export const deleteReservation = (name) => restJson("DELETE", `${scope()}/providers/Microsoft.Capacity/reservationOrders/${encodeURIComponent(name)}`, { query: q });
export const RESERVATION_TERMS = ["P1Y", "P3Y"];
export const RESERVATION_TERM_LABEL = { P1Y: "1 year", P3Y: "3 years" };
export const listVmSizes = async (location = "eastus") =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Compute/locations/${location}/vmSizes`, { query: q })).value || [];

// ── Azure Hybrid Benefit (Microsoft.Compute/virtualMachines licenseType) ────────────
const VM_ARM = armType("Microsoft.Compute", "virtualMachines", "2023-09-01");
export const listVmsForHybridBenefit = async () => (await VM_ARM.list()).map((v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup }));
export const setHybridBenefit = (rg, name, enabled) =>
  VM_ARM.patch(rg, name, { properties: { licenseType: enabled ? "Windows_Server" : "None" } });

// ── cost allocation rules (Microsoft.CostManagement/costAllocationRules) ────────────
export const listAllocationRules = async () => (await restJson("GET", `${scope()}/providers/Microsoft.CostManagement/costAllocationRules`, { query: q })).value || [];
export const putAllocationRule = (name, body) => restJson("PUT", `${scope()}/providers/Microsoft.CostManagement/costAllocationRules/${encodeURIComponent(name)}`, { query: q, body });
export const deleteAllocationRule = (name) => restJson("DELETE", `${scope()}/providers/Microsoft.CostManagement/costAllocationRules/${encodeURIComponent(name)}`, { query: q });

// ── form helpers ─────────────────────────────────────────────────────────────────────
export const RESET_PERIODS = ["Monthly", "Quarterly", "Annually", "BillingMonth", "BillingQuarter", "BillingAnnual"];
export const RESET_PERIOD_LABEL = { Monthly: "Monthly", Quarterly: "Quarterly", Annually: "Annually", BillingMonth: "Billing month", BillingQuarter: "Billing quarter", BillingAnnual: "Billing year" };

export function budgetTimePeriod(resetPeriod) {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), 1);
  const months = { Monthly: 1, Quarterly: 3, Annually: 12, BillingMonth: 1, BillingQuarter: 3, BillingAnnual: 12 }[resetPeriod] || 1;
  const end = new Date(start.getFullYear(), start.getMonth() + months * 12, start.getDate());  // 1 year of occurrences, like the portal default
  const iso = (d) => d.toISOString().slice(0, 10) + "T00:00:00Z";
  return { startDate: iso(start), endDate: iso(end) };
}

export function toBudgetFilter(resourceGroup) {
  if (!resourceGroup) return undefined;
  return { dimensions: { name: "ResourceGroupName", operator: "In", values: [resourceGroup] } };
}
