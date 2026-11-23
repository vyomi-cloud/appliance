/* Infrastructure Manager over the NATIVE config.googleapis.com v1 REST API (the wire `gcloud infra-manager` and the
 * google-cloud-config SDKs speak). Mutations return long-running operations; the simulator completes them synchronously,
 * so the returned operation is already done and carries either `response` or `error`. */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
const loc = (region) => `/v1/projects/${e(getProject())}/locations/${e(region)}`;
export const REGIONS = ["us-central1", "us-east1", "us-east4", "us-west1", "us-west2", "europe-west1", "europe-west2", "europe-west3", "europe-west4", "asia-east1", "asia-northeast1", "asia-south1", "asia-southeast1", "australia-southeast1", "southamerica-east1"];
export const idOf = (name) => (name || "").split("/").pop();
export const regionOf = (name) => (name || "").split("/")[3];

async function done(op) {
  if (op.error) { const err = new Error(op.error.message); err.code = "Operation failed"; throw err; }
  return op.response;
}

export async function listDeployments() {
  const out = []; let pageToken;
  do {
    const r = await restJson("GET", `${loc("-")}/deployments`, { query: pageToken ? { pageToken } : undefined });
    out.push(...(r.deployments || [])); pageToken = r.nextPageToken;
  } while (pageToken);
  return out;
}
export const getDeployment = (region, id) => restJson("GET", `${loc(region)}/deployments/${e(id)}`);
export const createDeployment = async (region, id, body) => done(await restJson("POST", `${loc(region)}/deployments`, { query: { deploymentId: id }, body }));
export const updateDeployment = async (region, id, body, updateMask) => done(await restJson("PATCH", `${loc(region)}/deployments/${e(id)}`, { query: { updateMask }, body }));
export const deleteDeployment = async (region, id, deletePolicy = "DELETE") => done(await restJson("DELETE", `${loc(region)}/deployments/${e(id)}`, { query: { deletePolicy } }));
export const getFiles = async (region, id) => (await restJson("GET", `${loc(region)}/deployments/${e(id)}/vyomiFiles`)).files || {};
export const listRevisions =async (region, id) => (await restJson("GET", `${loc(region)}/deployments/${e(id)}/revisions`)).revisions || [];
export const getRevision = (name) => restJson("GET", `/v1/${name}`);
export const listRevisionResources = async (revisionName) => (await restJson("GET", `/v1/${revisionName}/resources`)).resources || [];
export const listPreviews = async () => (await restJson("GET", `${loc("-")}/previews`)).previews || [];
export const createPreview = async (region, id, body) => done(await restJson("POST", `${loc(region)}/previews`, { query: { previewId: id }, body }));
export const deletePreview = async (region, id) => done(await restJson("DELETE", `${loc(region)}/previews/${e(id)}`));

/** The blueprint body for a source choice: { vyomiFiles } (export / pasted), or { gcsSource }. */
export function blueprint(source, inputVars) {
  const bp = source.kind === "gcs" ? { gcsSource: { source: source.gcs } } : { vyomiFiles: source.files };
  const vars = (inputVars || []).filter((v) => v.k);
  if (vars.length) bp.inputValues = Object.fromEntries(vars.map((v) => [v.k, { inputValue: v.v }]));
  return bp;
}

// the export page hands its generated files to the create form through the session (a user can also paste or upload)
const KEY = "vyomi.gcp.im.handoff";
export const handoff = {
  set: (files) => { try { sessionStorage.setItem(KEY, JSON.stringify(files)); } catch {} },
  take: () => { try { const v = sessionStorage.getItem(KEY); sessionStorage.removeItem(KEY); return v ? JSON.parse(v) : null; } catch { return null; } },
};
export const STATE_COLOR = { ACTIVE: "success", APPLIED: "success", SUCCEEDED: "success", CREATING: "info", UPDATING: "info", DELETING: "info", APPLYING: "info", FAILED: "error", SUSPENDED: "warning" };
