/* Storage accounts over the native Azure wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts/{name}
 *   Data plane:    Blob REST, path-style /{account}/{container}[/{blob}] with x-ms-version —
 *                  the shape azure-storage-blob uses against an emulator endpoint
 *                  (http://host/{account}), so the console and an SDK share one namespace per account.
 * The SharedKey header carries the account name (the routing signal Vyomi reads); like SigV4
 * in the AWS lens, the signature itself is not verified by the simulator. */
import { asList, restJson, WIRE_BASE, WireError, xmlToObj } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.Storage", "storageAccounts", "2023-05-01");
export const X_MS_VERSION = "2021-12-02";

const shape = (a) => ({ ...a, resourceGroup: parseId(a.id).resourceGroup });

export const listStorageAccounts = async () => (await ARM.list()).map(shape);
export const getStorageAccount = async (rg, name) => shape(await ARM.get(rg, name));
export const createStorageAccount = (rg, name, body) => ARM.put(rg, name, body);
export const updateStorageAccount = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteStorageAccount = (rg, name) => ARM.remove(rg, name);
export const listKeys = async (rg, name) => (await ARM.action(rg, name, "listKeys")).keys || [];

/** The account's Blob endpoint on this Vyomi (path-style, same origin as the console). */
export const blobEndpoint = (account) => `${location.origin}${WIRE_BASE}/${account}`;

// ── Blob data plane ─────────────────────────────────────────────────────────────────────
async function blob(account, method, path, { query, headers = {}, body } = {}) {
  const qs = query ? "?" + new URLSearchParams(query).toString() : "";
  const res = await fetch(`${WIRE_BASE}/${account}${path}${qs}`, {
    method, body,
    headers: { "x-ms-version": X_MS_VERSION, "x-ms-date": new Date().toUTCString(), authorization: `SharedKey ${account}:vyomi-console`, ...headers },
  });
  const text = method === "HEAD" || res.status === 202 || res.status === 201 ? "" : await res.text();
  if (!res.ok) {
    let code = res.headers.get("x-ms-error-code"), message;
    if (text.trim().startsWith("<")) {
      const doc = new DOMParser().parseFromString(text, "application/xml");
      code = code || doc.querySelector("Code")?.textContent;
      message = doc.querySelector("Message")?.textContent;
    }
    throw new WireError(res.status, code, message, text);
  }
  return { res, text };
}
const xml = (text) => (text ? xmlToObj(new DOMParser().parseFromString(text, "application/xml").documentElement) : {});

const PUBLIC_ACCESS_LABEL = { blob: "Blob", container: "Container" };
export async function listContainers(account) {
  const { text } = await blob(account, "GET", "", { query: { comp: "list" } });
  return asList(xml(text).Containers?.Container).map((c) => ({ name: c.Name, modified: c.Properties?.["Last-Modified"], lease: c.Properties?.LeaseState, publicAccess: PUBLIC_ACCESS_LABEL[c.Properties?.PublicAccess] || "Private" }));
}
export const createContainer = (account, name, publicAccess = "private") =>
  blob(account, "PUT", `/${encodeURIComponent(name)}`, { query: { restype: "container" }, headers: publicAccess !== "private" ? { "x-ms-blob-public-access": publicAccess } : {} });
export const deleteContainer = (account, name) => blob(account, "DELETE", `/${encodeURIComponent(name)}`, { query: { restype: "container" } });

export async function listBlobs(account, container, prefix = "") {
  const { text } = await blob(account, "GET", `/${encodeURIComponent(container)}`, { query: { restype: "container", comp: "list", ...(prefix ? { prefix } : {}) } });
  return asList(xml(text).Blobs?.Blob).map((b) => ({
    name: b.Name, modified: b.Properties?.["Last-Modified"], size: Number(b.Properties?.["Content-Length"] || 0),
    type: b.Properties?.BlobType, contentType: b.Properties?.["Content-Type"], md5: b.Properties?.["Content-MD5"], tier: b.Properties?.AccessTier || "Hot (Inferred)",
  }));
}
const bpath = (container, name) => `/${encodeURIComponent(container)}/${name.split("/").map(encodeURIComponent).join("/")}`;
export const uploadBlob = (account, container, name, file) =>
  blob(account, "PUT", bpath(container, name), { body: file, headers: { "x-ms-blob-type": "BlockBlob", "content-type": file.type || "application/octet-stream" } });
export const deleteBlob = (account, container, name) => blob(account, "DELETE", bpath(container, name));
export async function downloadBlob(account, container, name) {
  const res = await fetch(`${WIRE_BASE}/${account}${bpath(container, name)}`, { headers: { "x-ms-version": X_MS_VERSION, authorization: `SharedKey ${account}:vyomi-console` } });
  if (!res.ok) throw new WireError(res.status, res.headers.get("x-ms-error-code"), `Download failed (${res.status})`);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await res.blob());
  a.download = name.split("/").pop();
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ── create-form model → ARM body ────────────────────────────────────────────────────────
export const REDUNDANCY = {
  Standard: [["LRS", "Locally-redundant storage (LRS)"], ["ZRS", "Zone-redundant storage (ZRS)"], ["GRS", "Geo-redundant storage (GRS)"], ["GZRS", "Geo-zone-redundant storage (GZRS)"]],
  Premium: [["LRS", "Locally-redundant storage (LRS)"], ["ZRS", "Zone-redundant storage (ZRS)"]],
};
export const PREMIUM_KINDS = [["BlockBlobStorage", "Block blobs"], ["FileStorage", "File shares"], ["StorageV2", "Page blobs"]];

export function skuLabel(sku = "") {
  const [, red = ""] = sku.split("_");
  const ra = red.startsWith("RAG");
  const base = ra ? red.slice(2) : red;
  const all = [...REDUNDANCY.Standard, ...REDUNDANCY.Premium];
  const label = all.find(([k]) => k === base)?.[1] || red;
  return ra ? `Read-access ${label.charAt(0).toLowerCase()}${label.slice(1)}`.replace(/\((\w+)\)/, "(RA-$1)") : label;
}

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ──────────
const LOCK_API_VERSION = "2020-05-01";
const lockPath = (rg, name, lockName) => `${ARM.path(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;

export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── activity log (Microsoft.Insights/eventtypes/management/values, filtered to this account) ──
export const listActivityLog = async (rg, name) => {
  const rid = ARM.path(rg, name);
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${rid}'` };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Data protection (Microsoft.Storage/storageAccounts/blobServices/default) ───────────
// A real nested ARM resource (BlobServices_SetServiceProperties / GetServiceProperties),
// round-tripped exactly as configured — Vyomi stores these flags but the Blob data plane
// (core/azure_blob_core.py) does not enforce soft delete, versioning or the change feed.
const blobServicesPath = (rg, name) => `${ARM.path(rg, name)}/blobServices/default`;
export const getBlobServiceProperties = async (rg, name) => {
  try { return (await restJson("GET", blobServicesPath(rg, name), { query: { "api-version": "2023-01-01" } })).properties || {}; }
  catch { return {}; }
};
export const putBlobServiceProperties = (rg, name, properties) =>
  restJson("PUT", blobServicesPath(rg, name), { query: { "api-version": "2023-01-01" }, body: { properties } });

/** Static website endpoint on this Vyomi — a synthetic path (core/azure_blob_core.py
 * `__website__`), since a single-origin relay has no distinct per-account public hostname
 * the way `account.z#.web.core.windows.net` is a different host from `account.blob...`. */
export const websiteEndpoint = (account) => `${location.origin}${WIRE_BASE}/${account}/__website__/`;

// ── Lifecycle management (Microsoft.Storage/storageAccounts/managementPolicies/default) ──
// A real nested ARM resource (ManagementPolicies_CreateOrUpdate/Get) — core/azure_blob_core.py
// reads it back (via the router's `arm_state=`) to really tier/expire blobs lazily on
// list/get, the daily-background-job behaviour without a scheduler.
const managementPolicyPath = (rg, name) => `${ARM.path(rg, name)}/managementPolicies/default`;
export const getManagementPolicy = async (rg, name) => {
  try { return (await restJson("GET", managementPolicyPath(rg, name), { query: { "api-version": "2023-01-01" } })).properties?.policy?.rules || []; }
  catch { return []; }
};
export const putManagementPolicy = (rg, name, rules) =>
  restJson("PUT", managementPolicyPath(rg, name), { query: { "api-version": "2023-01-01" }, body: { properties: { policy: { rules } } } });

// ── Queues data plane (Azure Storage Queue REST) ────────────────────────────────────────
// core/azure_queue_core.py keeps a single global queue namespace per Nano instance (the
// same simplification the Key Vault keys/secrets stores make) — queues are not isolated
// per storage account. No Authorization header is sent: the account segment below is
// cosmetic (it shapes the URL like the real per-account Queue service) and the router's
// SharedKey-name heuristic that disambiguates blob-vs-queue only fires when a SharedKey
// header names that same segment, so omitting it keeps every call routed to the queue core.
async function queueReq(method, path, { query, body } = {}) {
  const qs = query ? "?" + new URLSearchParams(query).toString() : "";
  const res = await fetch(`${WIRE_BASE}${path}${qs}`, { method, body, headers: { "x-ms-version": X_MS_VERSION, "x-ms-date": new Date().toUTCString() } });
  const text = method === "HEAD" || res.status === 204 ? "" : await res.text();
  if (!res.ok) {
    let code = res.headers.get("x-ms-error-code"), message;
    if (text.trim().startsWith("<")) {
      const doc = new DOMParser().parseFromString(text, "application/xml");
      code = code || doc.querySelector("Code")?.textContent;
      message = doc.querySelector("Message")?.textContent;
    }
    throw new WireError(res.status, code, message, text);
  }
  return { res, text };
}
const escXml = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const msgXml = (text) => xml(text).QueueMessagesList?.QueueMessage;

export const queueUrl = (name) => `${location.origin}${WIRE_BASE}/${encodeURIComponent(name)}`;

export async function listQueues(account) {
  const { text } = await queueReq("GET", `/${encodeURIComponent(account)}`, { query: { comp: "list" } });
  return asList(xml(text).Queues?.Queue).map((q) => ({ name: q.Name }));
}
export const createQueue = (name) => queueReq("PUT", `/${encodeURIComponent(name)}`);
export const deleteQueue = (name) => queueReq("DELETE", `/${encodeURIComponent(name)}`);
export async function getQueueMetadata(name) {
  const { res } = await queueReq("GET", `/${encodeURIComponent(name)}`, { query: { comp: "metadata" } });
  return { approximateMessageCount: Number(res.headers.get("x-ms-approximate-messages-count") || 0) };
}
export async function peekMessages(name, num = 32) {
  const { text } = await queueReq("GET", `/${encodeURIComponent(name)}/messages`, { query: { peekonly: "true", numofmessages: String(num) } });
  return asList(msgXml(text)).map((m) => ({ id: m.MessageId, insertionTime: m.InsertionTime, expirationTime: m.ExpirationTime, dequeueCount: Number(m.DequeueCount || 0), text: m.MessageText }));
}
export async function receiveMessages(name, num = 32) {
  const { text } = await queueReq("GET", `/${encodeURIComponent(name)}/messages`, { query: { numofmessages: String(num) } });
  return asList(msgXml(text)).map((m) => ({ id: m.MessageId, popReceipt: m.PopReceipt, insertionTime: m.InsertionTime, expirationTime: m.ExpirationTime, dequeueCount: Number(m.DequeueCount || 0), text: m.MessageText }));
}
export const sendMessage = (name, text) => queueReq("POST", `/${encodeURIComponent(name)}/messages`, { body: `<QueueMessage><MessageText>${escXml(text)}</MessageText></QueueMessage>` });
export const deleteMessage = (name, id, popReceipt) => queueReq("DELETE", `/${encodeURIComponent(name)}/messages/${encodeURIComponent(id)}`, { query: { popreceipt: popReceipt } });
export const clearMessages = (name) => queueReq("DELETE", `/${encodeURIComponent(name)}/messages`);

// ── Tables data plane (Azure Table REST / OData — core/azure_table_core.py) ────────────
// Like Queues, a single global namespace per Nano instance (no SharedKey account
// scoping) — the account segment in tableUrl() is cosmetic, matching the real per-
// account Table service URL shape.
async function tableReq(method, path, { query, body } = {}) {
  const qs = query ? "?" + new URLSearchParams(query).toString() : "";
  const res = await fetch(`${WIRE_BASE}${path}${qs}`, {
    method, headers: { "content-type": "application/json", accept: "application/json;odata=nometadata" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = res.status === 204 ? "" : await res.text();
  const data = text ? (() => { try { return JSON.parse(text); } catch { return {}; } })() : {};
  if (!res.ok) throw new WireError(res.status, data["odata.error"]?.code, data["odata.error"]?.message?.value, text);
  return data;
}

export const tableUrl = (name) => `${location.origin}${WIRE_BASE}/${encodeURIComponent(name)}`;
export const listTables = async () => (await tableReq("GET", "/Tables")).value || [];
export const createTable = (name) => tableReq("POST", "/Tables", { body: { TableName: name } });
export const deleteTable = (name) => tableReq("DELETE", `/Tables('${encodeURIComponent(name)}')`);
export const listEntities = async (table) => (await tableReq("GET", `/${encodeURIComponent(table)}`)).value || [];
export const insertEntity = (table, entity) => tableReq("POST", `/${encodeURIComponent(table)}`, { body: entity });
const entityKey = (pk, rk) => `(PartitionKey='${encodeURIComponent(pk)}',RowKey='${encodeURIComponent(rk)}')`;
export const deleteEntity = (table, pk, rk) => tableReq("DELETE", `/${encodeURIComponent(table)}${entityKey(pk, rk)}`);

export function toArmBody(f) {
  const red = f.performance === "Standard" && f.readAccess && (f.redundancy === "GRS" || f.redundancy === "GZRS") ? `RA${f.redundancy}` : f.redundancy;
  return {
    location: f.location,
    kind: f.performance === "Premium" ? f.premiumKind : "StorageV2",
    sku: { name: `${f.performance}_${red}`, tier: f.performance },
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      supportsHttpsTrafficOnly: f.secureTransfer,
      allowBlobPublicAccess: f.allowBlobPublicAccess,
      allowSharedKeyAccess: f.allowSharedKeyAccess,
      defaultToOAuthAuthentication: f.defaultToOAuth,
      minimumTlsVersion: f.minimumTls,
      allowedCopyScope: f.copyScope === "any" ? undefined : f.copyScope,
      isHnsEnabled: f.hns,
      allowCrossTenantReplication: f.allowCrossTenantReplication,
      ...(f.performance === "Standard" ? { accessTier: f.accessTier } : {}),
      publicNetworkAccess: f.networkAccess === "disabled" ? "Disabled" : "Enabled",
      networkAcls: { defaultAction: f.networkAccess === "all" ? "Allow" : "Deny", bypass: "AzureServices", virtualNetworkRules: [], ipRules: [] },
      routingPreference: { routingChoice: f.routing },
      encryption: { keySource: "Microsoft.Storage", services: { blob: { enabled: true, keyType: "Account" }, file: { enabled: true, keyType: "Account" } } },
    },
  };
}

// ── Redundancy (Microsoft.Storage/storageAccounts sku.name) — a RA-* sku really exposes a
// read-only secondary endpoint (core/azure_blob_core.py: `{account}-secondary`) ───────────
export const isReadAccessSku = (skuName = "") => /^(standard|premium)_ra/i.test(skuName);
export const secondaryBlobEndpoint = (account) => `${location.origin}${WIRE_BASE}/${account}-secondary`;
export const listContainersSecondary = (account) => listContainers(`${account}-secondary`);

// ── Soft delete / versioning / change feed — real ops over the Blob data plane ─────────
export const listDeletedBlobs = async (account, container) => {
  const { text } = await blob(account, "GET", `/${encodeURIComponent(container)}`, { query: { restype: "container", comp: "list", include: "deleted" } });
  return asList(xml(text).Blobs?.Blob).filter((b) => b.Deleted === "true").map((b) => ({ name: b.Name, modified: b.Properties?.["Last-Modified"] }));
};
export const undeleteBlob = (account, container, name) => blob(account, "PUT", bpath(container, name), { query: { comp: "undelete" } });
export const listDeletedContainers = async (account) => {
  const { text } = await blob(account, "GET", "", { query: { comp: "list", include: "deleted" } });
  return asList(xml(text).Containers?.Container).filter((c) => c.Deleted === "true").map((c) => ({ name: c.Name, modified: c.Properties?.["Last-Modified"] }));
};
export const undeleteContainer = (account, name) => blob(account, "PUT", `/${encodeURIComponent(name)}`, { query: { restype: "container", comp: "undelete" } });
export async function listBlobVersions(account, container, name) {
  const { text } = await blob(account, "GET", `/${encodeURIComponent(container)}`, { query: { restype: "container", comp: "list", include: "versions", prefix: name } });
  return asList(xml(text).Blobs?.Blob).filter((b) => b.Name === name)
    .map((b) => ({ versionId: b.VersionId, isCurrent: b.IsCurrentVersion === "true", modified: b.Properties?.["Last-Modified"], size: Number(b.Properties?.["Content-Length"] || 0) }))
    .sort((x, y) => (x.isCurrent ? 1 : y.isCurrent ? -1 : 0));
}
export async function downloadBlobVersion(account, container, name, versionId) {
  const res = await fetch(`${WIRE_BASE}/${account}${bpath(container, name)}?versionid=${encodeURIComponent(versionId)}`, { headers: { "x-ms-version": X_MS_VERSION, authorization: `SharedKey ${account}:vyomi-console` } });
  if (!res.ok) throw new WireError(res.status, res.headers.get("x-ms-error-code"), `Download failed (${res.status})`);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await res.blob());
  a.download = `${name.split("/").pop()}.${versionId.replace(/[^a-z0-9]/gi, "")}`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
export const getChangeFeed = async (account) => (await blobJson(account, "GET", "", { query: { comp: "changefeed" } })).value || [];

// ── Blob inventory — "Run inventory now" writes a REAL CSV report blob listing the
// account's actual containers/blobs (core/azure_blob_core.py has no job scheduler, so this
// is on-demand rather than the real feature's daily run — same honest simplification
// Lifecycle's lazy evaluation makes) ─────────────────────────────────────────────────────
export async function runInventoryNow(account, destContainer) {
  const containers = await listContainers(account);
  const rows = [["Container", "Name", "Content-Length", "Content-Type", "Last-Modified", "Etag"]];
  for (const c of containers) {
    if (c.name === destContainer) continue;
    for (const b of await listBlobs(account, c.name)) rows.push([c.name, b.name, b.size, b.contentType || "", b.modified || "", ""]);
  }
  const csv = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
  await createContainer(account, destContainer).catch((e) => { if (e.code !== "ContainerAlreadyExists") throw e; });
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const blobName = `${ts}_inventory.csv`;
  await uploadBlob(account, destContainer, blobName, new File([csv], blobName, { type: "text/csv" }));
  return { blobName, rowCount: rows.length - 1 };
}

// ── Data protection / diagnostics synthetic reads (comp=diagnosticlog, comp=changefeed —
// Vyomi-only; see core/azure_blob_core.py's module docstring) ──────────────────────────
async function blobJson(account, method, path, opts) {
  const { text } = await blob(account, method, path, opts);
  return text ? JSON.parse(text) : {};
}
export const getDiagnosticLog = async (account) => blobJson(account, "GET", "", { query: { comp: "diagnosticlog" } });

// ── Access control (IAM) scoped to this storage account (core/azure_iam_core.py) ───────
const AUTHZ_API = "2022-04-01";
const authzPath = (p) => `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/${p}`;
export const listRoleAssignments = async () => (await restJson("GET", authzPath("roleAssignments"), { query: { "api-version": AUTHZ_API } })).value || [];
export const listRoleDefinitions = async () => (await restJson("GET", authzPath("roleDefinitions"), { query: { "api-version": AUTHZ_API } })).value || [];
export const putRoleAssignment = (name, body) => restJson("PUT", authzPath(`roleAssignments/${encodeURIComponent(name)}`), { query: { "api-version": AUTHZ_API }, body });
export const deleteRoleAssignment = (name) => restJson("DELETE", authzPath(`roleAssignments/${encodeURIComponent(name)}`), { query: { "api-version": AUTHZ_API } });
export const checkAccess = (principalId, action, scope) =>
  restJson("POST", authzPath("checkAccess"), { query: { "api-version": AUTHZ_API }, body: { principalId, actions: [{ id: action }], resource: { id: scope } } });
/** Scope inheritance (mirrors core/azure_iam_core.py's `_scope_covers`): an assignment at a
 * broader scope (subscription/resource group) covers this account too. */
export const scopeCovers = (assignmentScope, resourceId) => {
  const a = (assignmentScope || "/").replace(/\/$/, "") || "/";
  const r = (resourceId || "/").replace(/\/$/, "") || "/";
  return a === "/" || a === r || r.startsWith(a + "/");
};

// ── Data Lake Gen2 upgrade (Microsoft.Storage/storageAccounts.properties.isHnsEnabled) —
// a real, one-way PATCH; core/azure_arm_core.py rejects it off an ineligible kind or a
// downgrade attempt (see _storage_hns_block) ───────────────────────────────────────────
export const upgradeToDataLakeGen2 = (rg, name) => ARM.patch(rg, name, { properties: { isHnsEnabled: true } });

// ── Metrics / Insights (Microsoft.Insights/metrics, read-only — core/azure_monitor_core.py
// derives real numbers from the Blob core's own request counters/state) ────────────────
export const STORAGE_METRICS = ["UsedCapacity", "BlobCount", "ContainerCount", "Transactions", "Ingress", "Egress"];
export async function getMetrics(rg, name, metricNames = STORAGE_METRICS) {
  const r = await restJson("GET", `${ARM.path(rg, name)}/providers/Microsoft.Insights/metrics`,
    { query: { "api-version": "2018-01-01", metricnames: metricNames.join(",") } });
  return Object.fromEntries((r.value || []).map((m) => [m.name.value, { unit: m.unit, value: m.timeseries?.[0]?.data?.[0]?.total ?? 0 }]));
}

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, a real ARM extension
// resource scoped to this account — core/azure_arm_core.py._diagnostic_settings) ───────
const DIAG_API = "2021-05-01-preview";
const diagPath = (rg, name, setting) => `${ARM.path(rg, name)}/providers/Microsoft.Insights/diagnosticSettings${setting ? `/${encodeURIComponent(setting)}` : ""}`;
export const listDiagnosticSettings = async (rg, name) => (await restJson("GET", diagPath(rg, name), { query: { "api-version": DIAG_API } })).value || [];
export const putDiagnosticSetting = (rg, name, setting, properties) => restJson("PUT", diagPath(rg, name, setting), { query: { "api-version": DIAG_API }, body: { properties } });
export const deleteDiagnosticSetting = (rg, name, setting) => restJson("DELETE", diagPath(rg, name, setting), { query: { "api-version": DIAG_API } });

// ── Alerts (Microsoft.Insights/metricAlerts) scoped to this account via properties.scopes ──
export const MetricAlerts = armType("Microsoft.Insights", "metricAlerts", "2018-03-01");
export const listMetricAlerts = async (rg, accountId) => (await MetricAlerts.list(rg)).filter((a) => (a.properties?.scopes || []).includes(accountId));
export const putMetricAlert = (rg, alertName, accountId, { metricName, operator, threshold, severity = 3 }) =>
  MetricAlerts.put(rg, alertName, { location: "global", properties: {
    severity, enabled: true, scopes: [accountId], evaluationFrequency: "PT1M", windowSize: "PT5M",
    criteria: { "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
      allOf: [{ name: "c1", metricName, operator, threshold, timeAggregation: "Average" }] },
  } });
export const deleteMetricAlert = (rg, alertName) => MetricAlerts.remove(rg, alertName);
const OPS = { GreaterThan: (v, t) => v > t, GreaterThanOrEqual: (v, t) => v >= t, LessThan: (v, t) => v < t, LessThanOrEqual: (v, t) => v <= t, Equals: (v, t) => v === t };
/** Real evaluation of an alert's criteria against the account's REAL current metric values. */
export function alertFired(alert, metrics) {
  const criteria = (alert.properties?.criteria?.allOf || []);
  return criteria.some((c) => OPS[c.operator]?.(metrics[c.metricName]?.value ?? 0, c.threshold));
}

// ── Workbooks (Microsoft.Insights/workbooks) — real ARM-backed saved views pinned to a
// metric this account actually reports ─────────────────────────────────────────────────
export const Workbooks = armType("Microsoft.Insights", "workbooks", "2022-04-01");
export const listWorkbooks = async (rg, accountId) => (await Workbooks.list(rg)).filter((w) => w.properties?.sourceId === accountId);
export const putWorkbook = (rg, workbookName, accountId, displayName, metricName) =>
  Workbooks.put(rg, workbookName, { location: "global", kind: "shared", properties: {
    displayName, category: "storage", sourceId: accountId, serializedData: JSON.stringify({ metric: metricName }),
  } });
export const deleteWorkbook = (rg, workbookName) => Workbooks.remove(rg, workbookName);
