/* Azure Cosmos DB over the native Azure wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.DocumentDB/databaseAccounts/{name}
 *   Data plane:    the native Cosmos DB REST API (SQL / Core API) — /dbs, /dbs/{db}/colls,
 *                  /dbs/{db}/colls/{c}/docs (core/azure_cosmos_core.py) — the shape the
 *                  azure-cosmos SDK speaks against an emulator endpoint. There is no SigV4 /
 *                  x-ms-version signal that names an ACCOUNT the way storage's SharedKey header
 *                  does, so (see core/capabilities/azure/cosmos.json: azure.cosmos.data_explorer)
 *                  every Cosmos account in this Vyomi environment shares one data-plane keyspace.
 */
import { restJson } from "../../../common/wire.js";
import { armType, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.DocumentDB", "databaseAccounts", "2024-05-15");

const shape = (a) => ({ ...a, resourceGroup: parseId(a.id).resourceGroup });

export const listAccounts = async () => (await ARM.list()).map(shape);
export const getAccount = async (rg, name) => shape(await ARM.get(rg, name));
export const createAccount = (rg, name, body) => ARM.put(rg, name, body);
export const updateAccount = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteAccount = (rg, name) => ARM.remove(rg, name);

export const listKeys = (rg, name) => ARM.action(rg, name, "listKeys");
export const listReadOnlyKeys = (rg, name) => ARM.action(rg, name, "listReadOnlyKeys");
export const listConnectionStrings = (rg, name) => ARM.action(rg, name, "listConnectionStrings");
export const regenerateKey = (rg, name, keyKind) => ARM.action(rg, name, "regenerateKey", { keyKind });
/** Manual Failover: promotes a configured region to failoverPriority 0 for real
 *  (azure.cosmos.replicate_data_globally) — ENFORCED on the ARM side. */
export const failoverPriorityChange = (rg, name, failoverPolicies) => ARM.action(rg, name, "failoverPriorityChange", { failoverPolicies });

export const accountEndpoint = (name) => `https://${name}.documents.azure.com:443/`;
export const resourcePath = (rg, name) => ARM.path(rg, name);

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ──────────
const LOCK_API_VERSION = "2020-05-01";
const lockPath = (resPath, lockName) => `${resPath}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;
export const listLocks = async (resPath) => (await restJson("GET", lockPath(resPath), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (resPath, lockName, body) => restJson("PUT", lockPath(resPath, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (resPath, lockName) => restJson("DELETE", lockPath(resPath, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to a resource) ──
/** sinceIso: ISO timestamp lower bound (the timespan picker) — ENFORCED, narrows the result. */
export const listActivityLog = async (resPath, sub, sinceIso) => {
  const filter = `resourceUri eq '${resPath}'` + (sinceIso ? ` and eventTimestamp ge '${sinceIso}'` : "");
  const query = { "api-version": "2015-04-01", "$filter": filter };
  return (await restJson("GET", `/subscriptions/${sub}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Access control (IAM): real ARM resources ────────────────────────────────────────────
const AUTHZ_API = "2022-04-01";
/** Role assignments scoped to THIS account (plus its subscription/resource-group ancestors,
 *  real Azure's "inherited access" — see capabilities.json: azure.cosmos.iam), not every
 *  assignment in the subscription. */
export const listRoleAssignments = async (resPath) =>
  (await restJson("GET", `${resPath}/providers/Microsoft.Authorization/roleAssignments`, { query: { "api-version": AUTHZ_API } })).value || [];
export const listRoleDefinitions = async (sub) => (await restJson("GET", `/subscriptions/${sub}/providers/Microsoft.Authorization/roleDefinitions`, { query: { "api-version": AUTHZ_API } })).value || [];

// ── Cosmos data plane (core/azure_cosmos_core.py, native /dbs wire) ────────────────────
const cosmos = (method, path, opts) => restJson(method, path, opts);

export const listDatabases = async () => (await cosmos("GET", "/dbs")).Databases || [];
export const createDatabase = (id) => cosmos("POST", "/dbs", { body: { id } });
export const deleteDatabase = (id) => cosmos("DELETE", `/dbs/${encodeURIComponent(id)}`);

export const listContainers = async (db) => (await cosmos("GET", `/dbs/${encodeURIComponent(db)}/colls`)).DocumentCollections || [];
/** indexingOff/uniqueKeys/analyticalStore are accepted the way the real Create Container form
 *  submits them; indexingPolicy round-trips through the Cosmos core for real, but
 *  uniqueKeyPolicy / analyticalStorageTtl are not modelled (see capabilities.json). */
export const createContainer = (db, id, partitionKeyPath, { indexingOff, uniqueKeys, analyticalStore } = {}) =>
  cosmos("POST", `/dbs/${encodeURIComponent(db)}/colls`, { body: {
    id, partitionKey: { paths: [partitionKeyPath || "/id"], kind: "Hash" },
    ...(indexingOff ? { indexingPolicy: { indexingMode: "none", automatic: false } } : {}),
    ...(uniqueKeys?.length ? { uniqueKeyPolicy: { uniqueKeys: uniqueKeys.map((k) => ({ paths: [k] })) } } : {}),
    ...(analyticalStore === "On" ? { analyticalStorageTtl: -1 } : {}),
  } });
export const deleteContainer = (db, id) => cosmos("DELETE", `/dbs/${encodeURIComponent(db)}/colls/${encodeURIComponent(id)}`);

/** Every container across every database — the Overview blade's containers table (flattened,
 *  since Cosmos has no "list all containers in an account" call of its own). */
export async function listAllContainers() {
  const dbs = await listDatabases();
  const lists = await Promise.all(dbs.map(async (d) => (await listContainers(d.id)).map((c) => ({ database: d.id, ...c }))));
  return lists.flat();
}

export const listDocuments = async (db, coll) => (await cosmos("GET", `/dbs/${encodeURIComponent(db)}/colls/${encodeURIComponent(coll)}/docs`)).Documents || [];
export const putDocument = (db, coll, doc, upsert = true) =>
  cosmos("POST", `/dbs/${encodeURIComponent(db)}/colls/${encodeURIComponent(coll)}/docs`, { body: doc, headers: upsert ? { "x-ms-documentdb-is-upsert": "true" } : {} });
export const deleteDocument = (db, coll, id) => cosmos("DELETE", `/dbs/${encodeURIComponent(db)}/colls/${encodeURIComponent(coll)}/docs/${encodeURIComponent(id)}`);
export const runQuery = async (db, coll, query) =>
  (await cosmos("POST", `/dbs/${encodeURIComponent(db)}/colls/${encodeURIComponent(coll)}/docs`, {
    body: { query }, headers: { "content-type": "application/query+json", "x-ms-documentdb-isquery": "true" },
  })).Documents || [];

// ── create-form model → ARM body ────────────────────────────────────────────────────────
const REDUNDANCY_CODE = { "Geo-redundant backup storage": "Geo", "Zone-redundant backup storage": "Zone", "Locally-redundant backup storage": "Local" };

export function toArmBody(f) {
  return {
    location: f.location,
    kind: "GlobalDocumentDB",
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      databaseAccountOfferType: "Standard",
      locations: [{ locationName: f.location, failoverPriority: 0, isZoneRedundant: f.availabilityZones === "Enable" }],
      enableMultipleWriteLocations: f.multiRegionWrites === "Enable",
      isVirtualNetworkFilterEnabled: f.connectivity !== "All networks",
      minimalTlsVersion: f.minimumTls,
      capabilities: f.capacityMode === "Serverless" ? [{ name: "EnableServerless" }] : [],
      enableFreeTier: f.freeTier === "Apply",
      consistencyPolicy: { defaultConsistencyLevel: "Session" },
      backupPolicy: f.backupPolicy === "Periodic"
        ? { type: "Periodic", periodicModeProperties: { backupIntervalInMinutes: Number(f.backupInterval), backupRetentionIntervalInHours: Number(f.backupRetention), backupStorageRedundancy: REDUNDANCY_CODE[f.backupRedundancy] || "Geo" } }
        : { type: "Continuous", continuousModeProperties: { tier: f.backupPolicy === "Continuous (30 days)" ? "Continuous30Days" : "Continuous7Days" } },
    },
  };
}
