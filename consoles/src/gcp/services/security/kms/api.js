/* Cloud KMS over the NATIVE Cloud KMS REST API v1 (the same wire google-cloud-kms /
 * gcloud kms speak): /v1/projects/{p}/locations/{l}/keyRings/{kr}/cryptoKeys/{k}[/cryptoKeyVersions/{v}].
 * Location "-" aggregates across every location (keyRing "-" additionally aggregates across
 * every key ring) — the real API's project-wide search, used by the Key rings tab and Key inventory. */
import { restJson } from "../../../../common/wire.js";
import { getProject } from "../../../project.js";

const e = encodeURIComponent;
const base = () => `/v1/projects/${e(getProject())}`;
const ring = (loc, kr) => `${base()}/locations/${e(loc)}/keyRings/${e(kr)}`;
const key = (loc, kr, k) => `${ring(loc, kr)}/cryptoKeys/${e(k)}`;
const version = (loc, kr, k, v) => `${key(loc, kr, k)}/cryptoKeyVersions/${e(v)}`;

export const parseRingName = (name) => {
  const m = /^projects\/([^/]+)\/locations\/([^/]+)\/keyRings\/([^/]+)$/.exec(name) || [];
  return { project: m[1], location: m[2], keyRing: m[3] };
};
export const parseKeyName = (name) => {
  const m = /^projects\/([^/]+)\/locations\/([^/]+)\/keyRings\/([^/]+)\/cryptoKeys\/([^/]+)$/.exec(name) || [];
  return { project: m[1], location: m[2], keyRing: m[3], key: m[4] };
};
export const parseVersionId = (versionName) => (versionName || "").split("/").pop();

export const listKeyRings = () => restJson("GET", `${base()}/locations/-/keyRings`).then((r) => r.keyRings || []);
export const getKeyRing = (loc, kr) => restJson("GET", ring(loc, kr));
export const createKeyRing = (loc, id) => restJson("POST", `${base()}/locations/${e(loc)}/keyRings`, { query: { keyRingId: id } });

export const listKeysInRing = (loc, kr) => restJson("GET", `${ring(loc, kr)}/cryptoKeys`).then((r) => r.cryptoKeys || []);
export const listAllKeys = () => restJson("GET", `${base()}/locations/-/keyRings/-/cryptoKeys`).then((r) => r.cryptoKeys || []);
export const getKey = (loc, kr, k) => restJson("GET", key(loc, kr, k));
export const createKey = (loc, kr, id, body) => restJson("POST", `${ring(loc, kr)}/cryptoKeys`, { query: { cryptoKeyId: id }, body });
export const patchKey = (loc, kr, k, body, mask) => restJson("PATCH", key(loc, kr, k), { query: { updateMask: mask.join(",") }, body });
export const setPrimaryVersion = (loc, kr, k, versionId) =>
  restJson("POST", `${key(loc, kr, k)}:updateCryptoKeyPrimaryVersion`, { body: { cryptoKeyVersionId: versionId } });
export const getIamPolicy = (loc, kr, k) => restJson("GET", `${key(loc, kr, k)}:getIamPolicy`);
export const setIamPolicy = (loc, kr, k, policy) => restJson("POST", `${key(loc, kr, k)}:setIamPolicy`, { body: { policy } });

export const listVersions = (loc, kr, k) => restJson("GET", `${key(loc, kr, k)}/cryptoKeyVersions`).then((r) => r.cryptoKeyVersions || []);
export const createVersion = (loc, kr, k) => restJson("POST", `${key(loc, kr, k)}/cryptoKeyVersions`, { body: {} });
export const setVersionState = (loc, kr, k, v, state) => restJson("PATCH", version(loc, kr, k, v), { query: { updateMask: "state" }, body: { state } });
export const destroyVersion = (loc, kr, k, v) => restJson("POST", `${version(loc, kr, k, v)}:destroy`, { body: {} });
export const restoreVersion = (loc, kr, k, v) => restJson("POST", `${version(loc, kr, k, v)}:restore`, { body: {} });

// GCP KMS resource locations (regions + the two multi-region aggregates + global).
export const LOCATIONS = [
  ["global", "global"],
  ["us", "us (multi-region)"], ["europe", "europe (multi-region)"], ["asia", "asia (multi-region)"],
  ["us-central1", "us-central1 (Iowa)"], ["us-east1", "us-east1 (South Carolina)"], ["us-east4", "us-east4 (Northern Virginia)"],
  ["us-west1", "us-west1 (Oregon)"], ["europe-west1", "europe-west1 (Belgium)"], ["europe-west4", "europe-west4 (Netherlands)"],
  ["asia-south1", "asia-south1 (Mumbai)"], ["asia-southeast1", "asia-southeast1 (Singapore)"], ["asia-northeast1", "asia-northeast1 (Tokyo)"],
];

export const PURPOSES = [
  ["ENCRYPT_DECRYPT", "Symmetric encrypt/decrypt"], ["ASYMMETRIC_SIGN", "Asymmetric sign"],
  ["ASYMMETRIC_DECRYPT", "Asymmetric decrypt"], ["MAC", "MAC signing"], ["RAW_ENCRYPT_DECRYPT", "Raw encrypt/decrypt"],
];
export const purposeLabel = (p) => PURPOSES.find(([v]) => v === p)?.[1] || p;

export const ROTATION_PERIODS = [["", "Never"], ["2592000s", "90 days"], ["7776000s", "6 months (90 days x2)"], ["31536000s", "365 days"]];
export const rotationLabel = (p) => (p ? ROTATION_PERIODS.find(([v]) => v === p)?.[1] || `${Math.round(Number(p.replace("s", "")) / 86400)} days` : "—");

export const STATE_LABEL = {
  ENABLED: "Enabled", DISABLED: "Disabled", DESTROY_SCHEDULED: "Scheduled for destruction", DESTROYED: "Destroyed",
};
export const primaryState = (ck) => STATE_LABEL[ck.primary?.state] || ck.primary?.state || "—";
