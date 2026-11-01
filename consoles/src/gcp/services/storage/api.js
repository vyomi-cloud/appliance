/* Cloud Storage over the NATIVE GCS JSON API v1 (the same wire google-cloud-storage,
 * gsutil and gcloud storage speak). Every call here is a real GCS API operation. */
import { restJson, WIRE_BASE, WireError } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;

export async function listBuckets() {
  const r = await restJson("GET", "/storage/v1/b", { query: { project: getProject() } });
  return r.items || [];
}
export const getBucket = (b) => restJson("GET", `/storage/v1/b/${e(b)}`);
export const insertBucket = (body) => restJson("POST", "/storage/v1/b", { query: { project: getProject() }, body });
export const patchBucket = (b, body) => restJson("PATCH", `/storage/v1/b/${e(b)}`, { body });
export const deleteBucket = (b) => restJson("DELETE", `/storage/v1/b/${e(b)}`);

export const getIamPolicy = (b) => restJson("GET", `/storage/v1/b/${e(b)}/iam`);
export const setIamPolicy = (b, policy) => restJson("PUT", `/storage/v1/b/${e(b)}/iam`, { body: policy });

/** Storage Intelligence: Batch Operations jobs (bulk Delete / SetStorageClass over a
 * bucket+prefix) and Insights dataset configs — see core/gcp_storage_core.py. */
export async function listBatchJobs() {
  const r = await restJson("GET", "/storage/v1/batchOperations");
  return r.jobs || [];
}
export const createBatchJob = (body) => restJson("POST", "/storage/v1/batchOperations", { body });
export const deleteBatchJob = (id) => restJson("DELETE", `/storage/v1/batchOperations/${e(id)}`);

export async function listInsightsDatasets() {
  const r = await restJson("GET", "/storage/v1/insightsDatasets");
  return r.datasets || [];
}
export const createInsightsDataset = (body) => restJson("POST", "/storage/v1/insightsDatasets", { body });
export const deleteInsightsDataset = (id) => restJson("DELETE", `/storage/v1/insightsDatasets/${e(id)}`);

/** Long-running bucket operations (e.g. the Turbo replication switch) — a real,
 * listable resource; see core/gcp_storage_core.py's _bucket_ops. */
export async function listBucketOperations(bucket) {
  const r = await restJson("GET", `/storage/v1/b/${e(bucket)}/operations`);
  return r.items || [];
}

/** Interoperability: HMAC keys for service accounts (projects/{p}/hmacKeys). The
 * secret is only ever returned by createHmacKey, matching the real API. */
export async function listHmacKeys(project) {
  const r = await restJson("GET", `/storage/v1/projects/${e(project)}/hmacKeys`);
  return r.items || [];
}
export const createHmacKey = (project, serviceAccountEmail) =>
  restJson("POST", `/storage/v1/projects/${e(project)}/hmacKeys`, { body: { serviceAccountEmail } });
export const setHmacKeyState = (project, accessId, state) =>
  restJson("PUT", `/storage/v1/projects/${e(project)}/hmacKeys/${e(accessId)}`, { body: { state } });
export const deleteHmacKey = (project, accessId) =>
  restJson("DELETE", `/storage/v1/projects/${e(project)}/hmacKeys/${e(accessId)}`);

/** One "directory" level: folders (prefixes) + objects directly under `prefix`. */
export async function listLevel(bucket, prefix = "") {
  const r = await restJson("GET", `/storage/v1/b/${e(bucket)}/o`, { query: { prefix, delimiter: "/", userProject: getProject() } });
  return {
    folders: (r.prefixes || []).map((p) => ({ key: p, name: p.slice(prefix.length), folder: true })),
    objects: (r.items || []).filter((o) => o.name !== prefix).map((o) => ({ ...o, key: o.name, display: o.name.slice(prefix.length) })),
  };
}
/** Every object under a prefix (flat) — used to delete a folder's contents. */
export async function listAll(bucket, prefix = "") {
  const r = await restJson("GET", `/storage/v1/b/${e(bucket)}/o`, { query: { prefix, userProject: getProject() } });
  return r.items || [];
}

/** Noncurrent object generations kept by versioning / soft delete (gcp.storage.versioning,
 * gcp.storage.soft-delete) — every generation when `soft` is false, only soft-deleted ones when true. */
export async function listVersions(bucket, soft = false) {
  const r = await restJson("GET", `/storage/v1/b/${e(bucket)}/o`,
    { query: soft ? { softDeleted: "true", userProject: getProject() } : { versions: "true", userProject: getProject() } });
  return (r.items || []).filter((o) => !o.name.endsWith("/"));
}
export const restoreObject = (bucket, name, generation) =>
  restJson("POST", `/storage/v1/b/${e(bucket)}/o/${e(name)}/restore`, { query: { generation } });
export const deleteObjectVersion = (bucket, name, generation) =>
  restJson("DELETE", `/storage/v1/b/${e(bucket)}/o/${e(name)}`, { query: { generation } });
export const getObject = (b, name) => restJson("GET", `/storage/v1/b/${e(b)}/o/${e(name)}`, { query: { userProject: getProject() } });
export const patchObject = (b, name, body) => restJson("PATCH", `/storage/v1/b/${e(b)}/o/${e(name)}`, { query: { userProject: getProject() }, body });
export const deleteObject = (b, name) => restJson("DELETE", `/storage/v1/b/${e(b)}/o/${e(name)}`, { query: { userProject: getProject() } });
export const downloadUrl = (b, name) => `${WIRE_BASE}/storage/v1/b/${e(b)}/o/${e(name)}?alt=media&userProject=${e(getProject())}`;

/** The simulated public static-website host for a bucket (gcp.storage.static-website) —
 * Vyomi's own wire, never a real internet host; serves mainPageSuffix/notFoundPage for real. */
export const websiteUrl = (b) => `${WIRE_BASE}/storage/website/${e(b)}/`;

/** GCP-wide resource tags (Resource Manager tagKeys/tagValues/tagBindings — distinct from
 * labels) attached to a bucket's full resource name. See core/gcp_resourcemanager_core.js. */
const bucketResource = (b) => `//storage.googleapis.com/projects/_/buckets/${b}`;
async function findOrCreateTagKey(parent, shortName) {
  const r = await restJson("GET", "/v3/tagKeys", { query: { parent } });
  return (r.tagKeys || []).find((k) => k.shortName === shortName) || restJson("POST", "/v3/tagKeys", { body: { parent, shortName } });
}
async function findOrCreateTagValue(tagKeyName, shortName) {
  const r = await restJson("GET", "/v3/tagValues", { query: { parent: tagKeyName } });
  return (r.tagValues || []).find((v) => v.shortName === shortName) || restJson("POST", "/v3/tagValues", { body: { parent: tagKeyName, shortName } });
}
export async function addTag(bucket, key, value) {
  const tk = await findOrCreateTagKey(`projects/${getProject()}`, key);
  const tv = await findOrCreateTagValue(tk.name, value);
  return restJson("POST", "/v3/tagBindings", { body: { parent: bucketResource(bucket), tagValue: tv.name } });
}
export async function listTags(bucket) {
  const r = await restJson("GET", "/v3/tagBindings", { query: { parent: bucketResource(bucket) } });
  return r.tagBindings || [];
}
export const removeTagBinding = (name) => restJson("DELETE", `/v3/${name}`);

/** Real request-count metering (gcp.storage.observability) — Cloud Monitoring's own
 * storage.googleapis.com/api/request_count metric, fed by actual API activity in
 * core/gcp_storage_core.py (never synthetic data). */
export async function getRequestCountSeries(bucket, hours) {
  const now = new Date();
  const start = new Date(now.getTime() - hours * 3600_000);
  const r = await restJson("GET", `/v3/projects/${e(getProject())}/timeSeries`, {
    query: {
      filter: `metric.type="storage.googleapis.com/api/request_count" AND resource.label.bucket_name="${bucket}"`,
      "interval.startTime": start.toISOString().replace(/\.\d+Z$/, ".000Z"),
      "interval.endTime": now.toISOString().replace(/\.\d+Z$/, ".000Z"),
    },
  });
  const points = (r.timeSeries || [])[0]?.points || [];
  return points.map((p) => ({ t: p.interval.endTime, v: Number(p.value.int64Value) })).reverse();
}

/** Hierarchical namespace Folders (gcp.storage.hierarchical-namespace) — a real
 * sub-resource with atomic rename, distinct from the flat-namespace zero-byte
 * "name/" placeholder objects createFolder() above writes. */
export async function listFolders(bucket, prefix = "") {
  const r = await restJson("GET", `/storage/v1/b/${e(bucket)}/folders`, { query: { prefix } });
  return r.items || [];
}
export const createHnsFolder = (bucket, name, recursive = false) =>
  restJson("POST", `/storage/v1/b/${e(bucket)}/folders`, { query: recursive ? { recursive: "true" } : {}, body: { name } });
export const renameHnsFolder = (bucket, folder, destinationFolderId) =>
  restJson("POST", `/storage/v1/b/${e(bucket)}/folders/${e(folder)}:renameTo`, { body: { destinationFolderId } });
export const deleteHnsFolder = (bucket, folder) =>
  restJson("DELETE", `/storage/v1/b/${e(bucket)}/folders/${e(folder)}`);

/** objects.insert, simple media upload (uploadType=media). */
export async function uploadObject(bucket, name, data, contentType) {
  const qs = new URLSearchParams({ uploadType: "media", name, userProject: getProject() }).toString();
  const res = await fetch(`${WIRE_BASE}/upload/storage/v1/b/${e(bucket)}/o?${qs}`, {
    method: "POST", headers: { "content-type": contentType || "application/octet-stream" }, body: data,
  });
  const text = await res.text();
  let j = {};
  try { j = text ? JSON.parse(text) : {}; } catch {}
  if (!res.ok) throw new WireError(res.status, j.error?.errors?.[0]?.reason || j.error?.status, j.error?.message, text);
  return j;
}
/** The console's "Create folder" on a flat-namespace bucket: a zero-byte "name/" object. */
export const createFolder = (bucket, key) => uploadObject(bucket, key.endsWith("/") ? key : key + "/", new Blob([]), "application/x-directory");

/** Delete a folder (prefix) and everything in it. */
export async function deletePrefix(bucket, prefix) {
  for (const o of await listAll(bucket, prefix)) await deleteObject(bucket, o.name);
}

/** Project-wide default soft delete retention applied to NEW buckets (the console's
 * Settings > Soft delete page) — a real console preference, stored client-side like any
 * other per-project console setting; days=null means "don't enable by default". */
const SOFT_DELETE_DEFAULT_KEY = (project) => `vyomi.v4.gcp.storage.softDeleteDefaultDays.${project}`;
export function getDefaultSoftDeleteDays(project) {
  try { const v = localStorage.getItem(SOFT_DELETE_DEFAULT_KEY(project)); return v === null ? 7 : (v === "" ? null : Number(v)); }
  catch { return 7; }
}
export function setDefaultSoftDeleteDays(project, days) {
  try { localStorage.setItem(SOFT_DELETE_DEFAULT_KEY(project), days === null ? "" : String(days)); } catch {}
}

export const LOCATIONS = {
  "multi-region": [["US", "us (multiple regions in United States)"], ["EU", "eu (multiple regions in European Union)"], ["ASIA", "asia (multiple regions in Asia)"]],
  "dual-region": [["NAM4", "nam4 (Iowa and South Carolina)"], ["EUR4", "eur4 (Netherlands and Finland)"], ["ASIA1", "asia1 (Tokyo and Osaka)"]],
  region: [
    ["US-CENTRAL1", "us-central1 (Iowa)"], ["US-EAST1", "us-east1 (South Carolina)"], ["US-EAST4", "us-east4 (Northern Virginia)"],
    ["US-WEST1", "us-west1 (Oregon)"], ["EUROPE-WEST1", "europe-west1 (Belgium)"], ["EUROPE-WEST4", "europe-west4 (Netherlands)"],
    ["ASIA-SOUTH1", "asia-south1 (Mumbai)"], ["ASIA-SOUTHEAST1", "asia-southeast1 (Singapore)"], ["ASIA-NORTHEAST1", "asia-northeast1 (Tokyo)"],
  ],
};
export const LOCATION_TYPE_LABEL = { "multi-region": "Multi-region", "dual-region": "Dual-region", region: "Region" };
export const STORAGE_CLASSES = [
  ["STANDARD", "Standard", "Best for short-term storage and frequently accessed data"],
  ["NEARLINE", "Nearline", "Best for backups and data accessed less than once a month"],
  ["COLDLINE", "Coldline", "Best for disaster recovery and data accessed less than once a quarter"],
  ["ARCHIVE", "Archive", "Best for long-term digital preservation of data accessed less than once a year"],
];
export const classLabel = (c) => STORAGE_CLASSES.find(([v]) => v === c)?.[1] || c;

export const accessControl = (b) => (b.iamConfiguration?.uniformBucketLevelAccess?.enabled ? "Uniform" : "Fine-grained");
export function publicAccess(b, policy) {
  if (b.iamConfiguration?.publicAccessPrevention === "enforced") return "Not public";
  const pub = (policy?.bindings || []).some((x) => (x.members || []).some((m) => m === "allUsers" || m === "allAuthenticatedUsers"));
  if (pub) return "Public to internet";
  return accessControl(b) === "Uniform" ? "Not public" : "Subject to object ACLs";
}
export const protection = (b) => (b.retentionPolicy ? "Retention policy" : "None");
export const lifecycleSummary = (b) => {
  const n = b.lifecycle?.rule?.length || 0;
  return n ? `${n} rule${n === 1 ? "" : "s"}` : "None";
};

export const validBucketName = (n) => {
  if (!n) return "Bucket name is required.";
  if (n.length < 3 || n.length > 63) return "Bucket names must contain 3-63 characters.";
  if (!/^[a-z0-9][a-z0-9._-]*[a-z0-9]$/.test(n)) return "Use only lowercase letters, numbers, hyphens (-), underscores (_) and dots (.). Start and end with a letter or number.";
  if (/^goog/.test(n) || /g(o|0)(o|0)gle/.test(n)) return "Bucket names can't begin with \"goog\" or contain \"google\".";
  if (/^\d+\.\d+\.\d+\.\d+$/.test(n)) return "Bucket names can't be IP addresses.";
  return null;
};
