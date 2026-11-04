/* App Services over the native Azure ARM wire:
 *   /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Web/sites/{name}
 *   /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Web/serverfarms/{name}
 * Served by the same ARM core on every substrate (core/azure_webapp_core.py), so whatever
 * the console creates an azure-mgmt-web / `az webapp` / `az appservice plan` sees, and the
 * reverse. */
import { restJson } from "../../../common/wire.js";
import { armType, DEFAULT_RG, getSubscription, parseId } from "../../kit/arm.js";

export const SITES = armType("Microsoft.Web", "sites", "2023-12-01");
export const PLANS = armType("Microsoft.Web", "serverfarms", "2023-12-01");
const WORKSPACES = armType("Microsoft.OperationalInsights", "workspaces", "2022-10-01");

const shape = (s) => ({ ...s, resourceGroup: parseId(s.id).resourceGroup });

// Microsoft.Web/sites lists BOTH kinds (web apps and function apps), like real ARM; this
// blade shows web apps only — function apps live in the Function App blade.
export const isFunctionApp = (s) => /functionapp/i.test(s?.kind || "");
export const listSites = async () => (await SITES.list()).filter((s) => !isFunctionApp(s)).map(shape);
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

// Scale up (pricing tier) changes the App Service plan's SKU; Scale out (manual instance
// count) is a siteConfig field; Change App Service plan re-points the site at a different,
// already-existing plan — all three are plain ARM PATCHes the core already supports.
export const updatePlanSku = (rg, planName, sku) => PLANS.patch(rg, planName, { sku: { name: sku } });
export const changeSitePlan = (rg, name, planId) => SITES.patch(rg, name, { properties: { serverFarmId: planId } });

// Identity is a top-level sibling of `properties` on the site, exactly like real ARM.
export const updateIdentity = (rg, name, identity) => SITES.patch(rg, name, { identity });

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
export const getBackupConfig = (rg, name) => restJson("GET", cfgPath(rg, name, "backup"), { query: q });
export const updateBackupConfig = (rg, name, props) => restJson("PUT", cfgPath(rg, name, "backup"), { query: q, body: { properties: props } });

const backupsPath = (rg, name) => `${SITES.path(rg, name)}/backups`;
export const listBackups = async (rg, name) => (await restJson("GET", backupsPath(rg, name), { query: q })).value || [];
export const backupNow = (rg, name) => restJson("POST", backupsPath(rg, name), { query: q });
export const restoreBackup = (rg, name, backupId) => restJson("POST", `${backupsPath(rg, name)}/${encodeURIComponent(backupId)}/restore`, { query: q });

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

// Access control (IAM): Role assignments are a real ARM extension resource read scoped to
// THIS Web App (plus its subscription/resource-group ancestors, real Azure's inherited-access
// view) over the same generic Microsoft.Authorization/roleAssignments engine the Cosmos DB
// account and VM blades use (core/azure_arm_core.py) — not every assignment in the
// subscription. Roles stays subscription-wide, matching real Azure (built-in role definitions
// are listed tenant-wide too).
const AUTHZ_API_VERSION = "2022-04-01";
export const listRoleAssignments = async (rg, name) =>
  (await restJson("GET", `${SITES.path(rg, name)}/providers/Microsoft.Authorization/roleAssignments`, { query: { "api-version": AUTHZ_API_VERSION } })).value || [];
export const listRoleDefinitions = async () =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/roleDefinitions`, { query: { "api-version": AUTHZ_API_VERSION } })).value || [];

// Diagnostic settings: Microsoft.Insights/diagnosticSettings is a real ARM extension resource
// scoped to ANY other resource's own id (core/azure_monitor_core.py), reached by re-entering
// "providers" under the site's own path — the same shape Microsoft.Authorization/locks uses.
const DIAG_API_VERSION = "2021-05-01-preview";
const diagPath = (rg, name) => `${SITES.path(rg, name)}/providers/Microsoft.Insights/diagnosticSettings`;
export const listDiagnosticSettings = async (rg, name) =>
  (await restJson("GET", diagPath(rg, name), { query: { "api-version": DIAG_API_VERSION } })).value || [];
export const putDiagnosticSetting = (rg, name, dsName, body) =>
  restJson("PUT", `${diagPath(rg, name)}/${encodeURIComponent(dsName)}`, { query: { "api-version": DIAG_API_VERSION }, body });
export const deleteDiagnosticSetting = (rg, name, dsName) =>
  restJson("DELETE", `${diagPath(rg, name)}/${encodeURIComponent(dsName)}`, { query: { "api-version": DIAG_API_VERSION } });
export const listWorkspaces = async () => (await WORKSPACES.list()).map((w) => ({ ...w, resourceGroup: parseId(w.id).resourceGroup }));

// Activity log: the native Microsoft.Insights Activity Log feed (az monitor activity-log list /
// the portal's Activity Log blade), filtered to this Web App's resource id.
export const listActivityLog = async (rg, name) => (await restJson(
  "GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`,
  { query: { "api-version": "2015-04-01", "$filter": `resourceUri eq '${SITES.path(rg, name)}'` } },
)).value || [];

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
