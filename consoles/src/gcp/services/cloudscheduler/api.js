/* Cloud Scheduler over the NATIVE Cloud Scheduler REST API v1 (the same wire the
 * google-cloud-scheduler SDKs and `gcloud scheduler` speak). Every call here is a real
 * jobs.create/get/list/patch/delete/pause/resume/run or locations.list. */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;

// Mirrors core/gcp_cloudscheduler_core.py LOCATIONS — the fixed set of regions Vyomi
// accepts for Cloud Scheduler jobs. There is no aggregated-list method on the native API,
// so the console lists every location and merges, the way the real console's Jobs page does.
export const LOCATIONS = [
  "us-central1", "us-east1", "us-east4", "us-west1", "us-west2", "europe-west1",
  "europe-west2", "europe-west3", "asia-east1", "asia-northeast1", "asia-south1",
  "asia-southeast1", "australia-southeast1", "southamerica-east1",
];
export const DEFAULT_REGION = "us-central1";

const base = (region) => `/v1/projects/${e(getProject())}/locations/${e(region)}/jobs`;

export const jobName = (region, id) => `projects/${getProject()}/locations/${region}/jobs/${id}`;
export const jobId = (job) => job.name.split("/").pop();
export const jobRegion = (job) => job.name.split("/")[3];

export const getJob = (region, id) => restJson("GET", `${base(region)}/${e(id)}`);
export const createJob = (region, body) => restJson("POST", base(region), { body });
export const patchJob = (region, id, body, updateMask) => restJson("PATCH", `${base(region)}/${e(id)}`, { query: updateMask ? { updateMask } : undefined, body });
export const deleteJob = (region, id) => restJson("DELETE", `${base(region)}/${e(id)}`);
export const pauseJob = (region, id) => restJson("POST", `${base(region)}/${e(id)}:pause`);
export const resumeJob = (region, id) => restJson("POST", `${base(region)}/${e(id)}:resume`);
export const runJob = (region, id) => restJson("POST", `${base(region)}/${e(id)}:run`);

/** One region's jobs, following nextPageToken to the end. */
async function listRegion(region) {
  const out = [];
  let pageToken;
  do {
    const r = await restJson("GET", base(region), { query: pageToken ? { pageToken } : undefined });
    out.push(...(r.jobs || []));
    pageToken = r.nextPageToken;
  } while (pageToken);
  return out;
}

/** Every job across every region — the console's single Jobs table. */
export async function listAllJobs() {
  const lists = await Promise.all(LOCATIONS.map((r) => listRegion(r).catch(() => [])));
  return lists.flat();
}

// ── display helpers (the console derives these from the raw REST Job resource) ──────────
export const targetKind = (job) => job.httpTarget ? "HTTP" : job.pubsubTarget ? "Pub/Sub" : job.appEngineHttpTarget ? "App Engine HTTP" : "—";
export function targetText(job) {
  if (job.httpTarget) return `${job.httpTarget.httpMethod || "POST"} ${job.httpTarget.uri || ""}`;
  if (job.pubsubTarget) return job.pubsubTarget.topicName || "";
  if (job.appEngineHttpTarget) return `${job.appEngineHttpTarget.httpMethod || "POST"} ${job.appEngineHttpTarget.relativeUri || "/"}`;
  return "—";
}
export const stateLabel = (job) => ({ ENABLED: "Enabled", PAUSED: "Paused", DISABLED: "Disabled", UPDATE_FAILED: "Update failed" }[job.state] || job.state || "—");
export const lastRunText = (job) => job.lastAttemptTime || "Has not run yet";
export const lastResultText = (job) => job.lastAttemptTime ? (job.status?.code ? `Failed: ${job.status.message || ""}` : "Success") : "Has not run yet";
export const nextRunText = (job) => job.state === "ENABLED" ? (job.scheduleTime || "Not scheduled") : "Not scheduled (paused)";
export function retrySummary(job) {
  const rc = job.retryConfig || {};
  return `${rc.retryCount ?? 0} retries, backoff ${rc.minBackoffDuration || "5s"}-${rc.maxBackoffDuration || "3600s"}, ${rc.maxDoublings ?? 5} doublings`;
}

const TZ_FALLBACK = [
  "Etc/UTC", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
  "America/Sao_Paulo", "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Moscow",
  "Asia/Dubai", "Asia/Kolkata", "Asia/Shanghai", "Asia/Tokyo", "Asia/Singapore",
  "Australia/Sydney", "Pacific/Auckland",
];
/** Every IANA zone the browser knows, else a curated fallback list. */
export function timezones() {
  try { return Intl.supportedValuesOf("timeZone"); } catch { return TZ_FALLBACK; }
}

export const DURATION_UNITS = [["s", "Seconds", 1], ["m", "Minutes", 60], ["h", "Hours", 3600]];
/** "3600s" → {n: "1", unit: "h"} — picks the largest whole unit so round values read cleanly. */
export function splitDuration(wire) {
  const secs = Number(String(wire || "0s").replace(/s$/, ""));
  for (const [unit, , mult] of [...DURATION_UNITS].reverse()) {
    if (secs % mult === 0) return { n: String(secs / mult), unit };
  }
  return { n: String(secs), unit: "s" };
}
export const joinDuration = (n, unit) => `${Number(n || 0) * DURATION_UNITS.find(([u]) => u === unit)[2]}s`;

export const validJobId = (id) => /^[A-Za-z0-9_-]{1,500}$/.test(id || "");

/** Patching with this mask makes PATCH behave like a full save: any field not present
 * in the body (e.g. the target the user switched away from) is cleared, not left stale. */
export const FULL_UPDATE_MASK = "description,schedule,timeZone,retryConfig,attemptDeadline,httpTarget,pubsubTarget,appEngineHttpTarget";
