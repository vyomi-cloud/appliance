/* Secret Manager over the NATIVE Secret Manager REST API v1 (the same wire
 * google-cloud-secret-manager, gcloud secrets, and Terraform's google provider speak). */
import { restJson } from "../../../../common/wire.js";
import { getProject } from "../../../project.js";

const e = encodeURIComponent;
const base = (p = getProject()) => `/v1/projects/${e(p)}/secrets`;

export const b64 = (s) => btoa(unescape(encodeURIComponent(s)));
export const unb64 = (s) => decodeURIComponent(escape(atob(s)));

export async function listSecrets() {
  const r = await restJson("GET", base());
  return r.secrets || [];
}
export const getSecret = (name) => restJson("GET", `${base()}/${e(name)}`);
export const createSecret = (secretId, body) => restJson("POST", base(), { query: { secretId }, body });
export const patchSecret = (name, body, updateMask) => restJson("PATCH", `${base()}/${e(name)}`, { query: { updateMask }, body });
export const deleteSecret = (name) => restJson("DELETE", `${base()}/${e(name)}`);

export async function listVersions(name) {
  const r = await restJson("GET", `${base()}/${e(name)}/versions`);
  return r.versions || [];
}
export const addVersion = (name, dataUtf8) => restJson("POST", `${base()}/${e(name)}:addVersion`, { body: { payload: { data: b64(dataUtf8) } } });
export const accessVersion = async (name, ver = "latest") => {
  const r = await restJson("GET", `${base()}/${e(name)}/versions/${e(String(ver))}:access`);
  return unb64(r.payload.data);
};
export const enableVersion = (name, ver) => restJson("POST", `${base()}/${e(name)}/versions/${e(String(ver))}:enable`, { body: {} });
export const disableVersion = (name, ver) => restJson("POST", `${base()}/${e(name)}/versions/${e(String(ver))}:disable`, { body: {} });
export const destroyVersion = (name, ver) => restJson("POST", `${base()}/${e(name)}/versions/${e(String(ver))}:destroy`, { body: {} });

export const getIamPolicy = (name) => restJson("GET", `${base()}/${e(name)}:getIamPolicy`);
export const setIamPolicy = (name, policy) => restJson("POST", `${base()}/${e(name)}:setIamPolicy`, { body: { policy } });

/* Logs tab: the native Cloud Logging v2 entries:list the real console's audit log reads —
 * Secret Manager lifecycle events are written there by the backend (core/aws_wire_router.py). */
export async function listLogs(name) {
  const r = await restJson("POST", "/v2/entries:list", { body: {
    resourceNames: [`projects/${getProject()}`],
    filter: `resource.type="secretmanager.googleapis.com/Secret" AND resource.labels.secret_id="${name}"`,
    orderBy: "timestamp desc",
    pageSize: 50,
  } });
  return r.entries || [];
}

export const shortName = (resourceName) => resourceName.split("/secrets/")[1];
export const versionNumber = (resourceName) => resourceName.split("/versions/")[1];

export function encryptionLabel(secret) {
  const replicas = secret.replication?.userManaged?.replicas || [];
  return replicas.some((r) => r.customerManagedEncryption?.kmsKeyName) ? "Customer-managed" : "Google-managed";
}
export function locationLabel(secret) {
  const um = secret.replication?.userManaged;
  if (!um) return "Automatic";
  const locs = (um.replicas || []).map((r) => r.location).filter(Boolean);
  return locs.length ? locs.join(", ") : "Automatic";
}

export const LOCATIONS = [
  "us-central1", "us-east1", "us-east4", "us-west1", "europe-west1", "europe-west4",
  "asia-south1", "asia-southeast1", "asia-northeast1",
];

export const validSecretId = (n) => {
  if (!n) return "Name is required.";
  if (!/^[a-zA-Z0-9_-]{1,255}$/.test(n)) return "Use letters, numbers, hyphens (-) and underscores (_), up to 255 characters.";
  return null;
};
export const validLabelKey = (k) => /^[a-z][a-z0-9_-]{0,62}$/.test(k);
