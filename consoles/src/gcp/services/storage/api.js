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

/** One "directory" level: folders (prefixes) + objects directly under `prefix`. */
export async function listLevel(bucket, prefix = "") {
  const r = await restJson("GET", `/storage/v1/b/${e(bucket)}/o`, { query: { prefix, delimiter: "/" } });
  return {
    folders: (r.prefixes || []).map((p) => ({ key: p, name: p.slice(prefix.length), folder: true })),
    objects: (r.items || []).filter((o) => o.name !== prefix).map((o) => ({ ...o, key: o.name, display: o.name.slice(prefix.length) })),
  };
}
/** Every object under a prefix (flat) — used to delete a folder's contents. */
export async function listAll(bucket, prefix = "") {
  const r = await restJson("GET", `/storage/v1/b/${e(bucket)}/o`, { query: { prefix } });
  return r.items || [];
}
export const getObject = (b, name) => restJson("GET", `/storage/v1/b/${e(b)}/o/${e(name)}`);
export const deleteObject = (b, name) => restJson("DELETE", `/storage/v1/b/${e(b)}/o/${e(name)}`);
export const downloadUrl = (b, name) => `${WIRE_BASE}/storage/v1/b/${e(b)}/o/${e(name)}?alt=media`;

/** objects.insert, simple media upload (uploadType=media). */
export async function uploadObject(bucket, name, data, contentType) {
  const qs = new URLSearchParams({ uploadType: "media", name }).toString();
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
