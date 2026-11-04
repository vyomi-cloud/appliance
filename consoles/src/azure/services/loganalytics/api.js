/* Azure Log Analytics (Microsoft.OperationalInsights) over the native ARM wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.OperationalInsights/
 *                  workspaces/{ws}[/savedSearches/{n}|/tables/{n}|/dataSources/{n}]
 *                  + actions: sharedKeys, regenerateSharedKey, usages, intelligencePacks[/{p}/Enable|Disable]
 *   Logs query:    POST .../workspaces/{ws}/api/query — the SAME ARM pass-through path the
 *                  real portal's Logs blade uses when it has no data-plane token.
 *   core/azure_operationalinsights_core.py owns every shape above.
 */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.OperationalInsights", "workspaces", "2022-10-01");

const shape = (v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup });

export const listWorkspaces = async () => (await ARM.list()).map(shape);
export const getWorkspace = async (rg, name) => shape(await ARM.get(rg, name));
export const createWorkspace = (rg, name, body) => ARM.put(rg, name, body);
export const updateWorkspace = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteWorkspace = (rg, name) => ARM.remove(rg, name);

export const skuLabel = (sku) => sku?.name || "PerGB2018";

// ── Shared keys (Agents management) ─────────────────────────────────────────────────────
export const getSharedKeys = (rg, name) => ARM.action(rg, name, "sharedKeys");
export const regenerateSharedKey = (rg, name, which) => ARM.action(rg, name, "regenerateSharedKey", { name: which });

// ── Usage and estimated costs (usages is a GET-only action, unlike sharedKeys/regenerate) ──
export const getUsages = async (rg, name) =>
  (await restJson("GET", `${ARM.path(rg, name)}/usages`, { query: { "api-version": ARM.apiVersion } })).value || [];

// ── Legacy solutions (intelligencePacks) ─────────────────────────────────────────────────
const packsPath = (rg, name) => `${ARM.path(rg, name)}/intelligencePacks`;
export const listPacks = async (rg, name) => (await restJson("GET", packsPath(rg, name), { query: { "api-version": ARM.apiVersion } })) || [];
export const setPack = (rg, name, pack, enabled) =>
  restJson("POST", `${packsPath(rg, name)}/${encodeURIComponent(pack)}/${enabled ? "Enable" : "Disable"}`, { query: { "api-version": ARM.apiVersion }, body: {} });

// ── Saved searches ───────────────────────────────────────────────────────────────────────
const savedPath = (rg, name, id) => `${ARM.path(rg, name)}/savedSearches${id ? `/${encodeURIComponent(id)}` : ""}`;
const q = { "api-version": ARM.apiVersion };
export const listSavedSearches = async (rg, name) => (await restJson("GET", savedPath(rg, name), { query: q })).value || [];
export const putSavedSearch = (rg, name, id, body) => restJson("PUT", savedPath(rg, name, id), { query: q, body });
export const deleteSavedSearch = (rg, name, id) => restJson("DELETE", savedPath(rg, name, id), { query: q });

// ── Tables (built-in + custom _CL/_RST) ──────────────────────────────────────────────────
const tablePath = (rg, name, id) => `${ARM.path(rg, name)}/tables${id ? `/${encodeURIComponent(id)}` : ""}`;
export const listTables = async (rg, name) => (await restJson("GET", tablePath(rg, name), { query: q })).value || [];
export const putTable = (rg, name, id, body) => restJson("PUT", tablePath(rg, name, id), { query: q, body });
export const updateTable = (rg, name, id, body) => restJson("PATCH", tablePath(rg, name, id), { query: q, body });
export const deleteTable = (rg, name, id) => restJson("DELETE", tablePath(rg, name, id), { query: q });

// ── Data sources (listed by kind — ARM requires a $filter) ──────────────────────────────
const dsPath = (rg, name, id) => `${ARM.path(rg, name)}/dataSources${id ? `/${encodeURIComponent(id)}` : ""}`;
export const DS_KINDS = ["WindowsEvent", "LinuxSyslog", "CustomLog", "IISLogs", "WindowsPerformanceCounter", "LinuxPerformanceObject", "ChangeTrackingPath", "Office365", "AzureActivityLog"];
export const listDataSources = async (rg, name, kind) => (await restJson("GET", dsPath(rg, name), { query: { ...q, "$filter": `kind eq '${kind}'` } })).value || [];
export const listAllDataSources = async (rg, name) => {
  const lists = await Promise.all(DS_KINDS.map((k) => listDataSources(rg, name, k).catch(() => [])));
  return lists.flat();
};
export const putDataSource = (rg, name, id, body) => restJson("PUT", dsPath(rg, name, id), { query: q, body });
export const deleteDataSource = (rg, name, id) => restJson("DELETE", dsPath(rg, name, id), { query: q });

// ── Logs query editor (KQL subset) ───────────────────────────────────────────────────────
export const runQuery = (rg, name, query) => restJson("POST", `${ARM.path(rg, name)}/api/query`, { query: { "api-version": "2017-10-01" }, body: { query } });

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ──────────
const LOCK_API_VERSION = "2020-05-01";
const lockPath = (rg, name, lockName) => `${ARM.path(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;
export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to this workspace) ──
export const listActivityLog = async (rg, name) => {
  const rid = ARM.path(rg, name);
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${rid}'` };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── create-workspace form model → ARM body ───────────────────────────────────────────────
export function workspaceArmBody(f) {
  const sku = { name: f.pricingTier };
  if (f.pricingTier === "CapacityReservation") sku.capacityReservationLevel = Number(f.capacityLevel || 100);
  return {
    location: f.location,
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      sku,
      retentionInDays: Number(f.retentionInDays || 30),
      publicNetworkAccessForIngestion: f.publicIngestion === "Disabled" ? "Disabled" : "Enabled",
      publicNetworkAccessForQuery: f.publicQuery === "Disabled" ? "Disabled" : "Enabled",
    },
  };
}
