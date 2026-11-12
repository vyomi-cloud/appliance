/* Eventarc over the NATIVE Eventarc API v1 (eventarc.googleapis.com): triggers, providers and event types, delivery history.
 * The same wire the google-cloud-eventarc SDKs and `gcloud eventarc` speak. */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
export const LOCATIONS = ["us-central1", "us-east1", "us-east4", "us-west1", "europe-west1", "europe-west2", "europe-west4", "asia-east1", "asia-northeast1", "asia-south1", "asia-southeast1", "australia-southeast1"];
export const DEFAULT_REGION = "us-central1";

const base = (loc) => `/v1/projects/${e(getProject())}/locations/${e(loc)}`;
export const triggerId = (t) => t.name.split("/").pop();
export const triggerRegion = (t) => t.name.split("/")[3];
export const eventType = (t) => (t.eventFilters || []).find((f) => f.attribute === "type")?.value || "—";
export const destinationOf = (t) => {
  const d = t.destination || {};
  if (d.cloudRun) return { kind: "Cloud Run service", name: d.cloudRun.service, region: d.cloudRun.region };
  if (d.cloudRunJob) return { kind: "Cloud Run job", name: d.cloudRunJob.job, region: d.cloudRunJob.region };
  const k = Object.keys(d)[0];
  return { kind: k || "—", name: k ? JSON.stringify(d[k]) : "—" };
};

/** Every trigger in the project (the console's list spans all regions; `locations/-` is the native wildcard). */
export const listTriggers = async () => (await restJson("GET", `${base("-")}/triggers`)).triggers || [];
export const getTrigger = (loc, id) => restJson("GET", `${base(loc)}/triggers/${e(id)}`);
export const createTrigger = (loc, id, body) => restJson("POST", `${base(loc)}/triggers`, { body, query: { triggerId: id } });
export const patchTrigger = (loc, id, body, updateMask) => restJson("PATCH", `${base(loc)}/triggers/${e(id)}`, { body, query: { updateMask } });
export const deleteTrigger = (loc, id) => restJson("DELETE", `${base(loc)}/triggers/${e(id)}`);
export const deliveries = (loc, id) => restJson("GET", `${base(loc)}/triggers/${e(id)}/deliveries`);
export const listProviders = async (loc = DEFAULT_REGION) => (await restJson("GET", `${base(loc)}/providers`)).providers || [];
export const getProvider = (loc, id) => restJson("GET", `${base(loc)}/providers/${e(id)}`);

/** Cloud Run destinations in a region (Run Admin v2). */
export const listRunServices = async (loc) => (await restJson("GET", `/v2/projects/${e(getProject())}/locations/${e(loc)}/services`)).services || [];
export const listRunJobs = async (loc) => (await restJson("GET", `/v2/projects/${e(getProject())}/locations/${e(loc)}/jobs`)).jobs || [];
export const listBuckets = async () => (await restJson("GET", "/storage/v1/b", { query: { project: getProject() } })).items || [];
