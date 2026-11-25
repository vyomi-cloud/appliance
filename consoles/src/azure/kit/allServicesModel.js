/* Resolves an All services catalog entry (a real-portal service name) to Vyomi: the registry service that
 * simulates it (if any), the link it opens, the Create target, and the icon. */
import { ENTRIES } from "../services/allServicesCatalog.js";
import { byId } from "../services/registry.js";

const CREATE_IDS = new Set(["acr", "aks", "apim", "appconfiguration", "appservices", "cognitiveservices", "containerapps", "cosmos", "dns", "functionapp", "keyvaults", "loganalytics", "nsgs", "resourcegroups", "servicebus", "sql", "storage", "subscriptions", "vms", "vnets"]);

// Entries the real portal lists that are not in the captured category lists.
const EXTRA = { "Application Templates": { d: "A curated collection of workloads that are deployable for the end user.", t: "PREVIEW" } };
// Home-row tiles use the portal's shorter names for services listed elsewhere under another name.
export const TILE_ALIAS = { "SQL databases": "Azure SQL Database", "Virtual networks": "Virtual network", "Cost Management + Billing": "Cost Management + Billing" };

export const slug = (n) => n.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

export function entry(name) {
  const e = { ...(ENTRIES[name] || {}), ...(EXTRA[name] || {}) };
  const reg = e.r ? byId[e.r] : null;
  if (e.r === "allresources") return { name, desc: e.d || "", create: false, dropdown: false, tag: e.t || "", reg: null, icon: "resourcegroups", href: "#/allresources", createHref: null, simulated: true };
  return {
    name, desc: e.d || "", create: !!e.c, dropdown: !!e.dd, tag: e.t || "",
    reg, icon: reg?.icon || "generic",
    href: reg ? (e.r === "allresources" ? "#/allresources" : `#/${reg.id}`) : `#/allservices/${slug(name)}`,
    createHref: reg && CREATE_IDS.has(reg.id) ? `#/${reg.id}/create` : null,
    simulated: !!reg,
  };
}

export const allNames = () => [...Object.keys(ENTRIES), ...Object.keys(EXTRA)];
export const findBySlug = (s) => allNames().find((n) => slug(n) === s);
