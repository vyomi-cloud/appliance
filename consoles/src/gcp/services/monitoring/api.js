/* Cloud Monitoring over the NATIVE Cloud Monitoring REST API (monitoring.googleapis.com,
 * v3 for alerting/metrics/uptime/groups, v1 for Dashboards and Snoozes) — the same wire the
 * google-cloud-monitoring SDKs and `gcloud monitoring ...` speak. Every call here is a real
 * Cloud Monitoring API operation. */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
const v3 = () => `/v3/projects/${e(getProject())}`;
const v1 = () => `/v1/projects/${e(getProject())}`;

// ── alert policies ──────────────────────────────────────────────────────────
export const listPolicies = async (query) => (await restJson("GET", `${v3()}/alertPolicies`, { query: { pageSize: 500, ...query } })).alertPolicies || [];
export const getPolicy = (id) => restJson("GET", `${v3()}/alertPolicies/${e(id)}`);
export const createPolicy = (body) => restJson("POST", `${v3()}/alertPolicies`, { body });
export const patchPolicy = (id, body, updateMask) => restJson("PATCH", `${v3()}/alertPolicies/${e(id)}`, { query: updateMask ? { updateMask } : undefined, body });
export const deletePolicy = (id) => restJson("DELETE", `${v3()}/alertPolicies/${e(id)}`);

// ── notification channels ────────────────────────────────────────────────────
export const listChannels = async () => (await restJson("GET", `${v3()}/notificationChannels`, { query: { pageSize: 500 } })).notificationChannels || [];
export const createChannel = (body) => restJson("POST", `${v3()}/notificationChannels`, { body });
export const deleteChannel = (id, force) => restJson("DELETE", `${v3()}/notificationChannels/${e(id)}`, { query: force ? { force: "true" } : undefined });
export const channelDescriptors = async () => (await restJson("GET", `${v3()}/notificationChannelDescriptors`)).channelDescriptors || [];

// ── groups ────────────────────────────────────────────────────────────────────
export const listGroups = async () => (await restJson("GET", `${v3()}/groups`)).group || [];
export const createGroup = (body) => restJson("POST", `${v3()}/groups`, { body });
export const deleteGroup = (id, recursive) => restJson("DELETE", `${v3()}/groups/${e(id)}`, { query: recursive ? { recursive: "true" } : undefined });
export const groupMembers = (id) => restJson("GET", `${v3()}/groups/${e(id)}/members`);

// ── uptime checks ────────────────────────────────────────────────────────────
export const listUptimeChecks = async () => (await restJson("GET", `${v3()}/uptimeCheckConfigs`, { query: { pageSize: 500 } })).uptimeCheckConfigs || [];
export const createUptimeCheck = (body) => restJson("POST", `${v3()}/uptimeCheckConfigs`, { body });
export const patchUptimeCheck = (id, body, updateMask) => restJson("PATCH", `${v3()}/uptimeCheckConfigs/${e(id)}`, { query: updateMask ? { updateMask } : undefined, body });
export const deleteUptimeCheck = (id) => restJson("DELETE", `${v3()}/uptimeCheckConfigs/${e(id)}`);
export const uptimeCheckIps = async () => (await restJson("GET", "/v3/uptimeCheckIps")).uptimeCheckIps || [];

// ── services & SLOs ──────────────────────────────────────────────────────────
export const listServices = async () => (await restJson("GET", `${v3()}/services`)).services || [];
export const createService = (body) => restJson("POST", `${v3()}/services`, { body });
export const deleteService = (id) => restJson("DELETE", `${v3()}/services/${e(id)}`);
export const listSlos = async (sid) => (await restJson("GET", `${v3()}/services/${e(sid)}/serviceLevelObjectives`)).serviceLevelObjectives || [];
export const createSlo = (sid, body) => restJson("POST", `${v3()}/services/${e(sid)}/serviceLevelObjectives`, { body });
export const deleteSlo = (sid, oid) => restJson("DELETE", `${v3()}/services/${e(sid)}/serviceLevelObjectives/${e(oid)}`);

// Real SLO burn-down: the same select_slo_budget_fraction() timeSeries.list filter function
// the native API reserves for SLO queries, computed server-side from the request-based
// good/total-ratio time series the SLO's filters actually match.
export async function sloBudgetFraction(sloName, days) {
  const end = new Date(), start = new Date(end.getTime() - (days || 28) * 86400000);
  const r = await restJson("GET", `${v3()}/timeSeries`, { query: {
    filter: `select_slo_budget_fraction("${sloName}")`, "interval.startTime": start.toISOString(), "interval.endTime": end.toISOString(),
  } });
  const v = r.timeSeries?.[0]?.points?.[0]?.value;
  return v && "doubleValue" in v ? v.doubleValue : null;
}

// ── metric & monitored-resource descriptors ──────────────────────────────────
export const listMetricDescriptors = async (filter) => (await restJson("GET", `${v3()}/metricDescriptors`, { query: { pageSize: 500, ...(filter ? { filter } : {}) } })).metricDescriptors || [];
export const listMonitoredResourceDescriptors = async () => (await restJson("GET", `${v3()}/monitoredResourceDescriptors`)).resourceDescriptors || [];

// ── time series (Metrics Explorer) ───────────────────────────────────────────
export const writeTimeSeries = (timeSeries) => restJson("POST", `${v3()}/timeSeries`, { body: { timeSeries } });
export async function listTimeSeries({ filter, startTime, endTime, aligner, period, reducer, groupBy, view }) {
  const query = { filter, "interval.startTime": startTime, "interval.endTime": endTime, view: view || "FULL" };
  if (aligner && aligner !== "ALIGN_NONE") {
    query["aggregation.perSeriesAligner"] = aligner;
    query["aggregation.alignmentPeriod"] = period || "60s";
  }
  if (reducer && reducer !== "REDUCE_NONE") {
    query["aggregation.crossSeriesReducer"] = reducer;
    if (groupBy?.length) query["aggregation.groupByFields"] = groupBy.join(",");
  }
  const r = await restJson("GET", `${v3()}/timeSeries`, { query });
  return r.timeSeries || [];
}

// ── dashboards (v1) ───────────────────────────────────────────────────────────
export const listDashboards = async () => (await restJson("GET", `${v1()}/dashboards`)).dashboards || [];
export const getDashboard = (id) => restJson("GET", `${v1()}/dashboards/${e(id)}`);
export const createDashboard = (body) => restJson("POST", `${v1()}/dashboards`, { body });
export const patchDashboard = (id, body) => restJson("PATCH", `${v1()}/dashboards/${e(id)}`, { body });
export const deleteDashboard = (id) => restJson("DELETE", `${v1()}/dashboards/${e(id)}`);

// ── metrics scope (Settings > Metric Scope; real cross-project aggregation, Metrics Scopes API v1) ──
export const getMetricsScope = () => restJson("GET", `/v1/locations/global/metricsScopes/${e(getProject())}`);
export const addMonitoredProject = (projectId) => restJson("POST", `/v1/locations/global/metricsScopes/${e(getProject())}/projects`,
  { body: { name: `locations/global/metricsScopes/${getProject()}/projects/${projectId}` } });
export const removeMonitoredProject = (projectId) => restJson("DELETE", `/v1/locations/global/metricsScopes/${e(getProject())}/projects/${e(projectId)}`);

// ── snoozes (v1) ──────────────────────────────────────────────────────────────
export const listSnoozes = async () => (await restJson("GET", `${v1()}/snoozes`)).snoozes || [];
export const createSnooze = (body) => restJson("POST", `${v1()}/snoozes`, { body });
export const patchSnooze = (id, body, updateMask) => restJson("PATCH", `${v1()}/snoozes/${e(id)}`, { query: updateMask ? { updateMask } : undefined, body });

// ── incidents — the real alert-evaluation engine's open/closed alerts (see
// gcp.monitoring.incidents): no public incidents.list API exists, so this is modeled on the
// documented webhook notification payload shape, evaluated fresh against stored time series
// on every read. ──────────────────────────────────────────────────────────────
export const listIncidents = async (filter) => (await restJson("GET", `${v3()}/incidents`, { query: { pageSize: 500, ...(filter ? { filter } : {}) } })).incidents || [];
export const acknowledgeIncident = (id) => restJson("POST", `${v3()}/incidents/${e(id)}:acknowledge`, { body: {} });

// ── project IAM policy (Permissions page) — resourcemanager-style getIamPolicy/setIamPolicy
// on the generic IAM policy store every Vyomi GCP resource shares. ──────────────────────────
export const getProjectIamPolicy = () => restJson("POST", `/v1/projects/${e(getProject())}:getIamPolicy`, { body: {} });
export const setProjectIamPolicy = (bindings) => restJson("POST", `/v1/projects/${e(getProject())}:setIamPolicy`, { body: { policy: { bindings } } });

// ── Error reporting (Error Reporting reads error-severity entries out of Cloud Logging;
// Vyomi shows the flat entries, not Google's deduplicated error-group aggregation) ──────────
export async function listErrorEntries() {
  const r = await restJson("POST", "/v2/entries:list", {
    body: { resourceNames: [`projects/${e(getProject())}`], filter: 'severity>="ERROR"', orderBy: "timestamp desc", pageSize: 100 },
  });
  return r.entries || [];
}

// ── built-in metric catalog used by Metrics Explorer / alert condition pickers ──
export const BUILTIN_METRICS = [
  ["compute.googleapis.com/instance/cpu/utilization", "VM Instance", "CPU utilization", "gce_instance"],
  ["compute.googleapis.com/instance/disk/read_bytes_count", "VM Instance", "Disk read bytes", "gce_instance"],
  ["compute.googleapis.com/instance/network/received_bytes_count", "VM Instance", "Received bytes", "gce_instance"],
  ["storage.googleapis.com/api/request_count", "GCS Bucket", "Request count", "gcs_bucket"],
  ["pubsub.googleapis.com/subscription/num_undelivered_messages", "Cloud Pub/Sub Subscription", "Undelivered messages", "pubsub_subscription"],
  ["cloudsql.googleapis.com/database/cpu/utilization", "Cloud SQL Database", "CPU utilization", "cloudsql_database"],
  ["kubernetes.io/container/cpu/core_usage_time", "Kubernetes Container", "CPU usage time", "k8s_container"],
];
export const ALIGNERS = [
  ["ALIGN_NONE", "Unaggregated"], ["ALIGN_MEAN", "mean"], ["ALIGN_MAX", "max"], ["ALIGN_MIN", "min"],
  ["ALIGN_SUM", "sum"], ["ALIGN_COUNT", "count"], ["ALIGN_STDDEV", "std dev"],
];
export const REDUCERS = [
  ["REDUCE_NONE", "None"], ["REDUCE_MEAN", "mean"], ["REDUCE_MAX", "max"], ["REDUCE_MIN", "min"],
  ["REDUCE_SUM", "sum"], ["REDUCE_COUNT", "count"],
];
export const TIME_RANGES = [
  ["5m", "Last 5 minutes"], ["1h", "Last 1 hour"], ["6h", "Last 6 hours"], ["1d", "Last 1 day"], ["7d", "Last 7 days"],
];
export const rangeToMs = (v) => ({ "5m": 300000, "1h": 3600000, "6h": 21600000, "1d": 86400000, "7d": 604800000 }[v] || 300000);

export const comparisonLabel = (c) => ({ COMPARISON_GT: "above threshold", COMPARISON_LT: "below threshold" }[c] || c);
export const channelLabel = (c) => c.displayName || (c.labels && Object.values(c.labels)[0]) || c.name?.split("/").pop();
