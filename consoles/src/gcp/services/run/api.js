/* Cloud Run over the NATIVE Cloud Run Admin API v2 (`run.googleapis.com/v2`) — the same wire
 * the `google-cloud-run` SDKs and the real console speak. Domain mappings use the v1
 * Knative-style facade (`apis/domains.cloudrun.com/v1/...`) because that resource has no v2
 * Admin API equivalent. */
import { restJson, WIRE_BASE } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;

export const REGIONS = [
  ["us-central1", "us-central1 (Iowa)"], ["us-east1", "us-east1 (South Carolina)"], ["us-east4", "us-east4 (Northern Virginia)"],
  ["us-east5", "us-east5 (Columbus)"], ["us-south1", "us-south1 (Dallas)"], ["us-west1", "us-west1 (Oregon)"],
  ["us-west2", "us-west2 (Los Angeles)"], ["us-west3", "us-west3 (Salt Lake City)"], ["us-west4", "us-west4 (Las Vegas)"],
  ["europe-west1", "europe-west1 (Belgium)"], ["europe-west2", "europe-west2 (London)"], ["europe-west3", "europe-west3 (Frankfurt)"],
  ["europe-west4", "europe-west4 (Netherlands)"], ["europe-west8", "europe-west8 (Milan)"], ["europe-west9", "europe-west9 (Paris)"],
  ["europe-north1", "europe-north1 (Finland)"], ["europe-central2", "europe-central2 (Warsaw)"],
  ["asia-east1", "asia-east1 (Taiwan)"], ["asia-east2", "asia-east2 (Hong Kong)"], ["asia-northeast1", "asia-northeast1 (Tokyo)"],
  ["asia-northeast2", "asia-northeast2 (Osaka)"], ["asia-south1", "asia-south1 (Mumbai)"], ["asia-southeast1", "asia-southeast1 (Singapore)"],
  ["asia-southeast2", "asia-southeast2 (Jakarta)"], ["australia-southeast1", "australia-southeast1 (Sydney)"],
  ["southamerica-east1", "southamerica-east1 (São Paulo)"], ["northamerica-northeast1", "northamerica-northeast1 (Montréal)"],
  ["me-west1", "me-west1 (Tel Aviv)"], ["africa-south1", "africa-south1 (Johannesburg)"],
];
export const DEFAULT_REGION = "us-central1";
const REGION_KEY = "vyomi.v4.gcp.run.region";
export const getRegion = () => { try { return localStorage.getItem(REGION_KEY) || DEFAULT_REGION; } catch { return DEFAULT_REGION; } };
export const setRegion = (r) => { try { localStorage.setItem(REGION_KEY, r); } catch {} };
export const regionLabel = (r) => REGIONS.find(([v]) => v === r)?.[1] || r;

const base = (region) => `/v2/projects/${e(getProject())}/locations/${e(region)}`;

// ── services ─────────────────────────────────────────────────────────────────────────────
export async function listServices(region) {
  const r = await restJson("GET", `${base(region)}/services`);
  return r.services || [];
}
export const getService = (region, name) => restJson("GET", `${base(region)}/services/${e(name)}`);
export const createService = (region, serviceId, body) =>
  restJson("POST", `${base(region)}/services`, { query: { serviceId }, body });
export const patchService = (region, name, body, updateMask) =>
  restJson("PATCH", `${base(region)}/services/${e(name)}`, { query: updateMask ? { updateMask } : undefined, body });
export const deleteService = (region, name) => restJson("DELETE", `${base(region)}/services/${e(name)}`);

export async function listRevisions(region, name) {
  const r = await restJson("GET", `${base(region)}/services/${e(name)}/revisions`);
  return r.revisions || [];
}
export const deleteRevision = (region, name, rev) => restJson("DELETE", `${base(region)}/services/${e(name)}/revisions/${e(rev)}`);

export const getIamPolicy = (region, name) => restJson("GET", `${base(region)}/services/${e(name)}:getIamPolicy`);
export const setIamPolicy = (region, name, policy) => restJson("POST", `${base(region)}/services/${e(name)}:setIamPolicy`, { body: { policy } });
export const INVOKER_ROLE = "roles/run.invoker";
export const isPublic = (policy) => (policy?.bindings || []).some((b) => b.role === INVOKER_ROLE && b.members?.includes("allUsers"));
export const authLabel = (policy) => (isPublic(policy) ? "Allow unauthenticated" : "Require authentication");
export async function setPublic(region, name, pub) {
  const policy = await getIamPolicy(region, name);
  const bindings = (policy.bindings || []).filter((b) => b.role !== INVOKER_ROLE);
  if (pub) bindings.push({ role: INVOKER_ROLE, members: ["allUsers"] });
  return setIamPolicy(region, name, { ...policy, bindings });
}

/** Patch just the template's primary container image, creating a new revision (the
 * console's "Edit & deploy new revision" flow, simplified to the one field that matters). */
export async function deployNewRevision(region, name, service, image) {
  const tpl = JSON.parse(JSON.stringify(service.template));
  tpl.containers[0].image = image;
  return patchService(region, name, { template: tpl }, "template");
}

// ── display helpers (the wire returns the REAL Cloud Run API shape, not a flattened
// console view — every derived display field is computed here in JS) ──────────────────
export const idOf = (resourceName) => resourceName.split("/").pop();
export const regionOf = (resourceName) => resourceName.split("/")[3];
export const deploymentType = (svc) => (isFunction(svc) ? "Function" : "Container");
const INGRESS_LABEL = {
  INGRESS_TRAFFIC_ALL: "All", INGRESS_TRAFFIC_INTERNAL_ONLY: "Internal",
  INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER: "Internal and Cloud Load Balancing", INGRESS_TRAFFIC_NONE: "None",
};
export const ingressLabel = (svc) => INGRESS_LABEL[svc.ingress] || "All";
export const workerPoolImage = (wp) => wp.template?.containers?.[0]?.image || "";
export const workerPoolInstances = (wp) => `${wp.template?.scaling?.minInstanceCount ?? 0}-${wp.template?.scaling?.maxInstanceCount || "unlimited"}`;
export const labelsText = (res) => Object.entries(res.labels || {}).map(([k, v]) => `${k}=${v}`).join(", ") || "—";
export const dmDomain = (dm) => dm.metadata?.name || "";
export const dmRoute = (dm) => dm.spec?.routeName || "";
export const dmCertificate = (dm) => (dm.spec?.certificateMode === "AUTOMATIC" ? "Automatic" : "None");
export const dmStatus = (dm) => ((dm.status?.conditions || []).some((c) => c.type === "Ready" && c.status === "True") ? "Ready" : "Pending");
export const dmRecordsText = (dm) => (dm.status?.resourceRecords || []).map((r) => `${r.type} ${r.rrdata}`).join(", ") || "—";
export const dmCreated = (dm) => dm.metadata?.creationTimestamp || "";

// ── jobs ─────────────────────────────────────────────────────────────────────────────────
export async function listJobs(region) {
  const r = await restJson("GET", `${base(region)}/jobs`);
  return r.jobs || [];
}
export const getJob = (region, name) => restJson("GET", `${base(region)}/jobs/${e(name)}`);
export const createJob = (region, jobId, body) => restJson("POST", `${base(region)}/jobs`, { query: { jobId }, body });
export const deleteJob = (region, name) => restJson("DELETE", `${base(region)}/jobs/${e(name)}`);
export const runJob = (region, name, overrides) => restJson("POST", `${base(region)}/jobs/${e(name)}:run`, { body: overrides ? { overrides } : {} });
export async function listExecutions(region, name) {
  const r = await restJson("GET", `${base(region)}/jobs/${e(name)}/executions`);
  return r.executions || [];
}
export const deleteExecution = (region, jobName, exId) => restJson("DELETE", `${base(region)}/jobs/${e(jobName)}/executions/${e(exId)}`);
export const lastExecutionStatus = (job) => (job.executionCount ? "Succeeded" : "—");
export const lastExecutedAt = (job) => job.latestCreatedExecution?.createTime || null;
export const executionStatus = (ex) => {
  if (ex.failedCount > 0) return "Failed";
  if (ex.cancelledCount > 0) return "Cancelled";
  if (ex.succeededCount >= ex.taskCount) return "Succeeded";
  return "Running";
};

// ── job triggers (Cloud Scheduler bindings on this job's own :run endpoint) ───────────────
// A trigger is a Cloud Scheduler job, in the same region, whose httpTarget names this job's
// Admin API v2 :run endpoint. The appliance's httpTarget delivery (core/aws_wire_router.py
// _sched_invoke) really calls it when the scheduler job fires, so "Add trigger" creates a
// binding that genuinely starts an execution on schedule — not just a stored record.
const schedulerBase = (region) => `/v1/projects/${e(getProject())}/locations/${e(region)}/jobs`;
export const jobRunUri = (region, name) => `${location.origin}${WIRE_BASE}${base(region)}/jobs/${e(name)}:run`;
export async function listJobTriggers(region, name) {
  const uri = jobRunUri(region, name);
  const r = await restJson("GET", schedulerBase(region));
  return (r.jobs || []).filter((j) => j.httpTarget?.uri === uri);
}
export const createJobTrigger = (region, name, triggerId, schedule) => restJson("POST", schedulerBase(region), {
  body: {
    name: `projects/${getProject()}/locations/${region}/jobs/${triggerId}`,
    schedule, timeZone: "Etc/UTC",
    httpTarget: { uri: jobRunUri(region, name), httpMethod: "POST", oidcToken: { serviceAccountEmail: "default-compute@developer.gserviceaccount.com" } },
  },
});
export const runJobTriggerNow = (region, triggerId) => restJson("POST", `${schedulerBase(region)}/${e(triggerId)}:run`);
export const deleteJobTrigger = (region, triggerId) => restJson("DELETE", `${schedulerBase(region)}/${e(triggerId)}`);
export const triggerId = (schedJob) => schedJob.name.split("/").pop();

// ── worker pools ───────────────────────────────────────────────────────────────────────
export async function listWorkerPools(region) {
  const r = await restJson("GET", `${base(region)}/workerPools`);
  return r.workerPools || [];
}
export const createWorkerPool = (region, workerPoolId, body) => restJson("POST", `${base(region)}/workerPools`, { query: { workerPoolId }, body });
export const deleteWorkerPool = (region, name) => restJson("DELETE", `${base(region)}/workerPools/${e(name)}`);

// ── domain mappings (v1 Knative-style facade — single region: see region note in the UI) ──
const DOMAINS_PATH = () => `/apis/domains.cloudrun.com/v1/namespaces/${e(getProject())}/domainmappings`;
export async function listDomainMappings() {
  const r = await restJson("GET", DOMAINS_PATH());
  return r.items || [];
}
export const createDomainMapping = (domain, routeName, certificateMode) =>
  restJson("POST", DOMAINS_PATH(), { body: { metadata: { name: domain }, spec: { routeName, certificateMode } } });
export const deleteDomainMapping = (domain) => restJson("DELETE", `${DOMAINS_PATH()}/${e(domain)}`);

// ── console helpers (shared by Create/Detail) ──────────────────────────────────────────
export const RUNTIMES = ["Node.js 22", "Python 3.13", "Go 1.24", "Java 21", ".NET 8", "Ruby 3.4", "PHP 8.4"];
export const MEMORIES = ["128Mi", "256Mi", "512Mi", "1Gi", "2Gi", "4Gi", "8Gi", "16Gi", "32Gi"];
export const CPUS = ["1", "2", "4", "6", "8"];
export const DEFAULT_IMAGE = "us-docker.pkg.dev/cloudrun/container/hello";

const ANN = { runtime: "vyomi.dev/function-runtime", entry: "vyomi.dev/function-entry-point", source: "vyomi.dev/function-source" };
export const isFunction = (svc) => !!svc?.annotations?.[ANN.runtime];
export const functionRuntime = (svc) => svc?.annotations?.[ANN.runtime] || "";
export const functionEntryPoint = (svc) => svc?.annotations?.[ANN.entry] || "handler";
export const functionSource = (svc) => svc?.annotations?.[ANN.source] || "";
export const functionAnnotations = (runtime, entryPoint, source) => ({
  [ANN.runtime]: runtime, [ANN.entry]: entryPoint || "handler", [ANN.source]: source || "",
});

function fnv1a(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}
/** Deterministic pseudo-image for an inline-source "function" deploy (no real build). The tag
 * is a fingerprint of entry point + source, so editing either changes the image and the Admin
 * API's own revision-diff logic cuts a real new revision. */
export const functionImage = (runtime, entryPoint, source) =>
  `vyomi.dev/function-source/${encodeURIComponent((runtime || "node").toLowerCase().replace(/[^a-z0-9.]+/g, "-"))}:${fnv1a(`${entryPoint || ""} ${source || ""}`)}`;

/** Save source/runtime/entry-point edits AND actually redeploy: the native API only cuts a new
 * revision when the template (here, the container image) changes, so the pseudo-image tag is
 * refreshed from the new source in the same patch that updates the annotations. */
export function redeploySource(region, name, service, runtime, entryPoint, source) {
  const template = JSON.parse(JSON.stringify(service.template));
  template.containers[0].image = functionImage(runtime, entryPoint, source);
  return patchService(region, name, {
    annotations: { ...service.annotations, ...functionAnnotations(runtime, entryPoint, source) },
    template,
  }, "annotations,template");
}

export const DEFAULT_FUNCTION_SOURCE = {
  "Node.js 22": "exports.handler = (event) => {\n  return { message: \"hello from Cloud Run\" };\n};\n",
  "Python 3.13": "def handler(event):\n    return {\"message\": \"hello from Cloud Run\"}\n",
};

export const validName = (n, what = "Service") => {
  if (!n) return `${what} name is required.`;
  if (n.length > 49) return `${what} names must be 49 characters or fewer.`;
  if (!/^[a-z]([-a-z0-9]{0,47}[a-z0-9])?$/.test(n)) return "Use lowercase letters, numbers and hyphens. Start with a letter; don't end with a hyphen.";
  return null;
};
export const validServiceName = (n) => validName(n, "Service");
