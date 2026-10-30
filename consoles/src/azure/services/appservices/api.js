/* App Services over the native Azure ARM wire:
 *   /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Web/sites/{name}
 *   /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Web/serverfarms/{name}
 * Served by the same ARM core on every substrate (core/azure_webapp_core.py), so whatever
 * the console creates an azure-mgmt-web / `az webapp` / `az appservice plan` sees, and the
 * reverse. */
import { restJson } from "../../../common/wire.js";
import { armType, DEFAULT_RG, parseId } from "../../kit/arm.js";

export const SITES = armType("Microsoft.Web", "sites", "2023-12-01");
export const PLANS = armType("Microsoft.Web", "serverfarms", "2023-12-01");

const shape = (s) => ({ ...s, resourceGroup: parseId(s.id).resourceGroup });

export const listSites = async () => (await SITES.list()).map(shape);
export const getSite = async (rg, name) => shape(await SITES.get(rg, name));
export const createSite = (rg, name, body) => SITES.put(rg, name, body);
export const updateSiteTags = (rg, name, tags, site) => SITES.put(rg, name, { ...site, tags });
export const deleteSite = (rg, name) => SITES.remove(rg, name);
export const startSite = (rg, name) => SITES.action(rg, name, "start");
export const stopSite = (rg, name) => SITES.action(rg, name, "stop");
export const restartSite = (rg, name) => SITES.action(rg, name, "restart");
export const swapSlot = (rg, name, targetSlot) => SITES.action(rg, name, "slotsswap", { targetSlot });

export const listPlans = async () => (await PLANS.list()).map(shape);
export const getPlan = (rg, name) => PLANS.get(rg, name);
export const createPlan = (rg, name, body) => PLANS.put(rg, name, body);
export const deletePlan = (rg, name) => PLANS.remove(rg, name);

const cfgPath = (rg, name, ...tail) => `${SITES.path(rg, name)}/config/${tail.join("/")}`;
const q = { "api-version": "2023-12-01" };

export const getSiteConfig = (rg, name) => restJson("GET", cfgPath(rg, name, "web"), { query: q });
export const updateSiteConfig = (rg, name, props) => restJson("PUT", cfgPath(rg, name, "web"), { query: q, body: { properties: props } });
export const getAppSettings = async (rg, name) => (await restJson("GET", cfgPath(rg, name, "appsettings"), { query: q })).properties || {};
export const updateAppSettings = (rg, name, props) => restJson("PUT", cfgPath(rg, name, "appsettings"), { query: q, body: { properties: props } });
export const getConnectionStrings = async (rg, name) => (await restJson("GET", cfgPath(rg, name, "connectionstrings"), { query: q })).properties || {};
export const updateConnectionStrings = (rg, name, props) => restJson("PUT", cfgPath(rg, name, "connectionstrings"), { query: q, body: { properties: props } });
export const getAppServiceLogs = (rg, name) => restJson("GET", cfgPath(rg, name, "logs"), { query: q });
export const updateAppServiceLogs = (rg, name, props) => restJson("PUT", cfgPath(rg, name, "logs"), { query: q, body: { properties: props } });

const slotsPath = (rg, name) => `${SITES.path(rg, name)}/slots`;
export const listSlots = async (rg, name) => (await restJson("GET", slotsPath(rg, name), { query: q })).value || [];
export const createSlot = (rg, name, slot) => restJson("PUT", `${slotsPath(rg, name)}/${encodeURIComponent(slot)}`, { query: q, body: {} });
export const deleteSlot = (rg, name, slot) => restJson("DELETE", `${slotsPath(rg, name)}/${encodeURIComponent(slot)}`, { query: q });

const domainsPath = (rg, name) => `${SITES.path(rg, name)}/hostNameBindings`;
export const listCustomDomains = async (rg, name) => (await restJson("GET", domainsPath(rg, name), { query: q })).value || [];
export const addCustomDomain = (rg, name, host) => restJson("PUT", `${domainsPath(rg, name)}/${encodeURIComponent(host)}`, { query: q, body: {} });
export const removeCustomDomain = (rg, name, host) => restJson("DELETE", `${domainsPath(rg, name)}/${encodeURIComponent(host)}`, { query: q });

const locksPath = (rg, name) => `${SITES.path(rg, name)}/providers/Microsoft.Authorization/locks`;
export const listLocks = async (rg, name) => (await restJson("GET", locksPath(rg, name), { query: q })).value || [];
export const addLock = (rg, name, lockName, level, notes) =>
  restJson("PUT", `${locksPath(rg, name)}/${encodeURIComponent(lockName)}`, { query: q, body: { properties: { level, notes } } });
export const removeLock = (rg, name, lockName) => restJson("DELETE", `${locksPath(rg, name)}/${encodeURIComponent(lockName)}`, { query: q });

// ── labels ───────────────────────────────────────────────────────────────────────────────
export const RUNTIMES = [
  [".NET 9 (STS)", "DOTNETCORE|9.0"], [".NET 8 (LTS)", "DOTNETCORE|8.0"], ["Java 21", "JAVA|21-java21"], ["Java 17", "JAVA|17-java17"],
  ["Node 22 LTS", "NODE|22-lts"], ["Node 20 LTS", "NODE|20-lts"], ["PHP 8.4", "PHP|8.4"], ["Python 3.13", "PYTHON|3.13"], ["Python 3.12", "PYTHON|3.12"],
];
export const PLAN_SKUS = [
  ["F1", "Free F1"], ["B1", "Basic B1"], ["B2", "Basic B2"], ["B3", "Basic B3"],
  ["S1", "Standard S1"], ["S2", "Standard S2"], ["S3", "Standard S3"],
  ["P1v2", "Premium V2 P1v2"], ["P1v3", "Premium V3 P1v3"], ["P2v3", "Premium V3 P2v3"],
];
export const appType = (kind = "") => (kind.includes("linux") ? "Web App (Linux)" : "Web App");
export const pricingTier = (sku = "") => PLAN_SKUS.find(([k]) => k === sku)?.[1] || sku;
export const planName = (serverFarmId = "") => serverFarmId.split("/").pop();

export { DEFAULT_RG };
