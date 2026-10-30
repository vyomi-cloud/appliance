/* Azure Resource Manager over the native wire: `/_wire/subscriptions/{sub}/…?api-version=…`.
 * Served by the same ARM core on every substrate (appliance: providers/azure_services.handle_arm,
 * Nano + dev server: core/azure_arm_core.AzureArm), so whatever the console creates an
 * azure-mgmt-* SDK or `az` CLI sees, and the reverse. */
import { restJson } from "../../common/wire.js";

/** Vyomi's simulated subscription (the ARM cores' DEFAULT_SUBSCRIPTION). ARM has no
 *  "list subscriptions" in the simulator, so the lens knows this one id and reads it back
 *  with GET /subscriptions/{id}. */
export const DEFAULT_SUBSCRIPTION = "00000000-0000-0000-0000-cloudlearn01";
export const DEFAULT_RG = "cloudlearn-rg";

let current = DEFAULT_SUBSCRIPTION;
export const getSubscription = () => current;
export const setSubscription = (s) => { current = s; };

export const LOCATIONS = [
  ["eastus", "East US"], ["eastus2", "East US 2"], ["westus", "West US"], ["westus2", "West US 2"], ["westus3", "West US 3"],
  ["centralus", "Central US"], ["northeurope", "North Europe"], ["westeurope", "West Europe"], ["uksouth", "UK South"],
  ["centralindia", "Central India"], ["southindia", "South India"], ["southeastasia", "Southeast Asia"], ["japaneast", "Japan East"],
  ["australiaeast", "Australia East"],
];
export const locationLabel = (l) => (LOCATIONS.find(([id]) => id === String(l || "").toLowerCase())?.[1]) || l || "-";

const sub = (s = current) => `/subscriptions/${s}`;

export const getSubscriptionInfo = (s = current) => restJson("GET", sub(s));
export const listResourceGroups = async (s = current) =>
  (await restJson("GET", `${sub(s)}/resourcegroups`, { query: { "api-version": "2021-04-01" } })).value || [];

/** Resource id → {subscription, resourceGroup, provider, type, name}. */
export function parseId(id = "") {
  const p = id.split("/").filter(Boolean);
  const at = (k) => { const i = p.findIndex((x) => x.toLowerCase() === k); return i >= 0 ? p[i + 1] : undefined; };
  return { subscription: at("subscriptions"), resourceGroup: at("resourcegroups"), provider: at("providers"), name: p[p.length - 1] };
}

/** A typed ARM resource client: list (subscription or RG scope), get, put, patch, delete, action. */
export function armType(provider, type, apiVersion) {
  const q = { "api-version": apiVersion };
  const item = (rg, name) => `${sub()}/resourceGroups/${encodeURIComponent(rg)}/providers/${provider}/${type}/${encodeURIComponent(name)}`;
  return {
    apiVersion,
    list: async (rg) => (await restJson("GET", rg ? `${sub()}/resourceGroups/${encodeURIComponent(rg)}/providers/${provider}/${type}` : `${sub()}/providers/${provider}/${type}`, { query: q })).value || [],
    get: (rg, name) => restJson("GET", item(rg, name), { query: q }),
    put: (rg, name, body) => restJson("PUT", item(rg, name), { query: q, body }),
    patch: (rg, name, body) => restJson("PATCH", item(rg, name), { query: q, body }),
    remove: (rg, name) => restJson("DELETE", item(rg, name), { query: q }),
    action: (rg, name, verb, body = {}) => restJson("POST", `${item(rg, name)}/${verb}`, { query: q, body }),
    path: item,
  };
}
