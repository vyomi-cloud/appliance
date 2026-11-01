/* App Configuration over the native Azure wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.AppConfiguration/configurationStores/{name}
 *                  (+ listKeys/regenerateKey actions, replicas/{name} and locks sub-resources)
 *   Data plane:    the store's own REST API (/kv, /keys, /labels, /locks, /revisions, /snapshots)
 *                  — the shape azure-data-appconfiguration / azappconfig / `az appconfig kv` use
 *                  against a store's connection string.
 * Vyomi's key-values live INSIDE the store's ARM record (core/azure_appconfiguration_core.py),
 * so — exactly like the Key Vault lens's shared Keys/Secrets/Certificates relay — the data plane
 * has no per-store host to read the store identity from; the console sends the store it's
 * showing as `x-vyomi-store` (see setActiveStore below). */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.AppConfiguration", "configurationStores", "2024-05-01");
export const DATA_API_VERSION = "2023-11-01";

const shape = (v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup });

export const listStores = async () => (await ARM.list()).map(shape);
export const getStore = async (rg, name) => shape(await ARM.get(rg, name));
export const createStore = (rg, name, body) => ARM.put(rg, name, body);
export const updateStore = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteStore = (rg, name) => ARM.remove(rg, name);

export const skuLabel = (sku) => (sku?.name ? sku.name[0].toUpperCase() + sku.name.slice(1).toLowerCase() : "Free");

// ── access keys (ARM actions) ───────────────────────────────────────────────────────────
export const listKeys = async (rg, name) => (await ARM.action(rg, name, "listKeys")).value || [];
export const regenerateKey = (rg, name, id) => ARM.action(rg, name, "regenerateKey", { id });

// ── replicas / Geo-replication (ARM child resource) ─────────────────────────────────────
const replicaPath = (rg, name, replica) => `${ARM.path(rg, name)}/replicas${replica ? `/${encodeURIComponent(replica)}` : ""}`;
export const listReplicas = async (rg, name) => (await restJson("GET", replicaPath(rg, name), { query: { "api-version": ARM.apiVersion } })).value || [];
export const createReplica = (rg, name, replica, body) => restJson("PUT", replicaPath(rg, name, replica), { query: { "api-version": ARM.apiVersion }, body });
export const deleteReplica = (rg, name, replica) => restJson("DELETE", replicaPath(rg, name, replica), { query: { "api-version": ARM.apiVersion } });

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ───────────
const LOCK_API_VERSION = "2020-05-01";
const lockPath = (rg, name, lockName) => `${ARM.path(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;

export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── activity log (Microsoft.Insights/eventtypes/management/values, filtered to this store) ──
export const listActivityLog = async (rg, name, sinceIso) => {
  const rid = ARM.path(rg, name);
  const filter = sinceIso ? `resourceUri eq '${rid}' and eventTimestamp ge '${sinceIso}'` : `resourceUri eq '${rid}'`;
  const query = { "api-version": "2015-04-01", "$filter": filter };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── data plane (the store's own REST API) ────────────────────────────────────────────────
// Which store the blade currently showing is calling for — real App Configuration learns this
// from the store's own hostname ({store}.azconfig.io); Vyomi's one shared relay has no
// per-store host, so the console carries it as a header instead (core/aws_wire_router.py
// reads x-vyomi-store the same way it reads Key Vault's x-vyomi-vault).
let activeStore = "";
export const setActiveStore = (name) => { activeStore = name || ""; };
const dp = (method, path, { query, body } = {}) => restJson(method, path, {
  query: { "api-version": DATA_API_VERSION, ...(query || {}) }, body,
  headers: activeStore ? { "x-vyomi-store": activeStore } : {},
});

export const listKv = async (label) => (await dp("GET", "/kv", { query: label ? { label } : {} })).items || [];
export const getKv = (key, label) => dp("GET", `/kv/${encodeURIComponent(key)}`, { query: label ? { label } : {} });
export const putKv = (key, label, body) => dp("PUT", `/kv/${encodeURIComponent(key)}`, { query: label ? { label } : {}, body });
export const deleteKv = (key, label) => dp("DELETE", `/kv/${encodeURIComponent(key)}`, { query: label ? { label } : {} });
export const lockKv = (key, label) => dp("PUT", `/locks/${encodeURIComponent(key)}`, { query: label ? { label } : {} });
export const unlockKv = (key, label) => dp("DELETE", `/locks/${encodeURIComponent(key)}`, { query: label ? { label } : {} });

// ── Feature manager: feature flags are key-values with a reserved key prefix + content type ──
export const FF_PREFIX = ".appconfig.featureflag/";
export const FF_CONTENT_TYPE = "application/vnd.microsoft.appconfig.ff+json;charset=utf-8";
export const isFeatureFlag = (kv) => kv.key?.startsWith(FF_PREFIX) && kv.content_type === FF_CONTENT_TYPE;
export const featureFlagName = (kv) => kv.key.slice(FF_PREFIX.length);
export const parseFeatureFlag = (kv) => { try { return JSON.parse(kv.value); } catch { return { id: featureFlagName(kv), enabled: false, description: "" }; } };
export const featureFlagBody = (name, { enabled, description }) => JSON.stringify({ id: name, description: description || "", enabled: !!enabled, conditions: { client_filters: [] } });

// ── create-store form model → ARM body ───────────────────────────────────────────────────
export function toArmBody(f) {
  return {
    location: f.location,
    sku: { name: f.pricingTier },
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      publicNetworkAccess: f.publicAccess ? "Enabled" : "Disabled",
    },
  };
}
