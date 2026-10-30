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

export async function listContainers(account) {
  const { text } = await blob(account, "GET", "", { query: { comp: "list" } });
  return asList(xml(text).Containers?.Container).map((c) => ({ name: c.Name, modified: c.Properties?.["Last-Modified"], lease: c.Properties?.LeaseState, publicAccess: c.Properties?.PublicAccess || "Private" }));
}
export const createContainer = (account, name) => blob(account, "PUT", `/${encodeURIComponent(name)}`, { query: { restype: "container" } });
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
