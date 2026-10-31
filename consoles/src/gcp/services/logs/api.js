/* Cloud Logging over the NATIVE Cloud Logging REST API v2 (the same wire
 * google-cloud-logging and `gcloud logging ...` speak). Every call here is a real
 * Cloud Logging operation against core/gcp_logging_core.py. */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
const proj = () => getProject();
const LOCATION = "global";

// ── entries (Logs Explorer / Observability Analytics) ──────────────────────
export const writeEntries = (entries, { logName, resource, labels } = {}) =>
  restJson("POST", "/v2/entries:write", { body: { logName, resource, labels, entries } });

export async function listEntries({ filter, orderBy, pageSize } = {}) {
  const r = await restJson("POST", "/v2/entries:list", {
    body: { resourceNames: [`projects/${proj()}`], filter, orderBy, pageSize: pageSize || 1000 },
  });
  return r.entries || [];
}

export const listLogNames = () =>
  restJson("GET", `/v2/projects/${e(proj())}/logs`).then((r) => (r.logNames || []).map((n) => n.split("/logs/")[1]));

export const SEVERITIES = ["DEFAULT", "DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"];
export const SEVERITY_ORDER = Object.fromEntries(SEVERITIES.map((s, i) => [s, i]));
export const severityColor = (s) =>
  ({ ERROR: "error.main", CRITICAL: "error.main", ALERT: "error.main", EMERGENCY: "error.main", WARNING: "warning.main", NOTICE: "info.main" }[s] || "text.secondary");

export const TIME_RANGES = [
  ["5m", "Last 5 minutes", 5 * 60], ["30m", "Last 30 minutes", 30 * 60], ["1h", "Last 1 hour", 3600],
  ["6h", "Last 6 hours", 6 * 3600], ["24h", "Last 24 hours", 24 * 3600], ["3d", "Last 3 days", 3 * 86400],
  ["7d", "Last 7 days", 7 * 86400], ["14d", "Last 14 days", 14 * 86400],
];

/** Compose the Cloud Logging query-language text shown in the Query box from the
 * Explorer's dropdowns — same subset the raw box accepts, kept in sync both ways. */
export function buildFilter({ resourceType, logName, severity }) {
  const clauses = [];
  if (resourceType && resourceType !== "all") clauses.push(`resource.type="${resourceType}"`);
  if (logName && logName !== "all") clauses.push(`logName="projects/${proj()}/logs/${logName}"`);
  if (severity && severity !== "all") clauses.push(`severity>="${severity}"`);
  return clauses.join("\n");
}

/** Evaluate a (possibly multi-line, AND-joined) Cloud Logging filter against an already
 * fetched LogEntry — the client-side half of the same language core/gcp_logging_core.py
 * parses server-side, used so dropdown + freeform query filtering share one engine. */
export function matchesQuery(entry, text) {
  const clauses = String(text || "").split(/\n|\s+AND\s+/i).map((s) => s.trim()).filter(Boolean);
  for (const c of clauses) {
    const m = c.match(/^(-)?([\w.]+)\s*(>=|<=|!=|=~|>|<|=)\s*"?([^"]*)"?$/);
    if (m) {
      const [, neg, field, op, raw] = m;
      let ok;
      if (field === "severity" && (op === ">=" || op === "<=" || op === ">" || op === "<")) {
        const a = SEVERITY_ORDER[entry.severity] ?? -1, b = SEVERITY_ORDER[raw] ?? 1e9;
        ok = op === ">=" ? a >= b : op === "<=" ? a <= b : op === ">" ? a > b : a < b;
      } else {
        const v = field === "resource.type" ? entry.resource?.type : field === "logName" ? entry.logName : entry[field];
        ok = op === "=~" ? new RegExp(raw).test(String(v || "")) : String(v ?? "") === raw;
        if (op === "!=") ok = !ok;
      }
      if (neg) ok = !ok;
      if (!ok) return false;
    } else if (!JSON.stringify(entry).toLowerCase().includes(c.replace(/^"|"$/g, "").toLowerCase())) {
      return false;
    }
  }
  return true;
}

export function summary(entry) {
  if (entry.textPayload) return entry.textPayload;
  if (entry.jsonPayload) return JSON.stringify(entry.jsonPayload);
  if (entry.protoPayload) return JSON.stringify(entry.protoPayload);
  return "";
}

// ── sinks (Log Router) ──────────────────────────────────────────────────────
export const listSinks = () => restJson("GET", `/v2/projects/${e(proj())}/sinks`).then((r) => r.sinks || []);
export const getSink = (id) => restJson("GET", `/v2/projects/${e(proj())}/sinks/${e(id)}`);
export const createSink = (body) =>
  restJson("POST", `/v2/projects/${e(proj())}/sinks`, { query: { uniqueWriterIdentity: true }, body });
export const patchSink = (id, body, updateMask) =>
  restJson("PATCH", `/v2/projects/${e(proj())}/sinks/${e(id)}`, { query: updateMask ? { updateMask } : undefined, body });
export const deleteSink = (id) => restJson("DELETE", `/v2/projects/${e(proj())}/sinks/${e(id)}`);

export const SINK_SERVICES = [
  ["bucket", "Cloud Logging bucket", (dest) => `logging.googleapis.com/projects/${proj()}/locations/${LOCATION}/buckets/${dest}`, true],
  ["bigquery", "BigQuery dataset", (dest) => `bigquery.googleapis.com/projects/${proj()}/datasets/${dest}`, true],
  ["storage", "Cloud Storage bucket", (dest) => `storage.googleapis.com/${dest}`, true],
  ["pubsub", "Pub/Sub topic", (dest) => `pubsub.googleapis.com/projects/${proj()}/topics/${dest}`, true],
  ["splunk", "Splunk", null, false],
  ["other-project", "Other project", null, false],
];
export const destinationKind = (dest) =>
  dest?.startsWith("storage.googleapis.com/") ? "Cloud Storage bucket"
  : dest?.startsWith("bigquery.googleapis.com/") ? "BigQuery dataset"
  : dest?.startsWith("pubsub.googleapis.com/") ? "Pub/Sub topic"
  : dest?.startsWith("logging.googleapis.com/") ? "Cloud Logging bucket" : "Other";

// ── log-based metrics ────────────────────────────────────────────────────────
export const listMetrics = () => restJson("GET", `/v2/projects/${e(proj())}/metrics`).then((r) => r.metrics || []);
export const getMetric = (id) => restJson("GET", `/v2/projects/${e(proj())}/metrics/${e(id)}`);
export const createMetric = (body) => restJson("POST", `/v2/projects/${e(proj())}/metrics`, { body });
export const updateMetric = (id, body) => restJson("PUT", `/v2/projects/${e(proj())}/metrics/${e(id)}`, { body });
export const deleteMetric = (id) => restJson("DELETE", `/v2/projects/${e(proj())}/metrics/${e(id)}`);
export const metricType = (m) => (m.metricDescriptor?.valueType === "DISTRIBUTION" ? "Distribution" : "Counter");

/** [previousMonthCount, monthToDateCount] of entries matching the metric's filter —
 * a real, live-derived stand-in for GCP's billed-bytes usage figures. */
export function metricUsage(entries, metric, nowMs) {
  const now = new Date(nowMs);
  const curStart = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
  const prevStart = new Date(now.getFullYear(), now.getMonth() - 1, 1).getTime();
  let prev = 0, cur = 0;
  for (const en of entries) {
    if (!matchesQuery(en, metric.filter)) continue;
    const t = new Date(en.timestamp).getTime();
    if (t >= curStart) cur++;
    else if (t >= prevStart) prev++;
  }
  return [prev, cur];
}

export const SYSTEM_METRICS = [
  ["log_entry_count", "Count of log entries", "global"],
  ["byte_count", "Count of bytes of logs ingested", "global"],
];

// ── usage alerts (Logs Storage "Create usage alert" / "View usage data") ───
// Hands off to Cloud Monitoring exactly like the real console: every entries:write mirrors
// this project's live month-to-date byte/entry counts into Monitoring as the real system
// metric logging.googleapis.com/byte_count (core/gcp_logging_core._sync_usage_metrics), so
// these calls create a REAL AlertPolicy / read REAL timeSeries on core/gcp_monitoring_core.py.
const USAGE_METRIC = "logging.googleapis.com/byte_count";
const usageFilter = () => `metric.type = "${USAGE_METRIC}" AND resource.type = "global"`;

export const createUsageAlert = (displayName, thresholdBytes) =>
  restJson("POST", `/v3/projects/${e(proj())}/alertPolicies`, { body: {
    displayName, combiner: "OR",
    conditions: [{ displayName: `${displayName} condition`, conditionThreshold: {
      filter: usageFilter(), comparison: "COMPARISON_GT", thresholdValue: Number(thresholdBytes), duration: "0s",
    } }],
  } });

export const listUsageAlerts = async () =>
  ((await restJson("GET", `/v3/projects/${e(proj())}/alertPolicies`, { query: { pageSize: 500 } })).alertPolicies || [])
    .filter((p) => (p.conditions || []).some((c) => c.conditionThreshold?.filter === usageFilter()));

export async function usageTimeSeries(days = 30) {
  const end = new Date(), start = new Date(end.getTime() - days * 86400000);
  const r = await restJson("GET", `/v3/projects/${e(proj())}/timeSeries`, { query: {
    filter: usageFilter(), "interval.startTime": start.toISOString(), "interval.endTime": end.toISOString(),
  } });
  return r.timeSeries?.[0]?.points || [];
}

// ── log buckets + views (Logs Storage) ──────────────────────────────────────
export const BUCKET_LOCATION = LOCATION;
export const listBuckets = (location = LOCATION) =>
  restJson("GET", `/v2/projects/${e(proj())}/locations/${e(location)}/buckets`).then((r) => r.buckets || []);
export const getBucket = (id, location = LOCATION) => restJson("GET", `/v2/projects/${e(proj())}/locations/${e(location)}/buckets/${e(id)}`);
export const createBucket = (id, body, location = LOCATION) =>
  restJson("POST", `/v2/projects/${e(proj())}/locations/${e(location)}/buckets`, { query: { bucketId: id }, body });
export const patchBucket = (id, body, updateMask, location = LOCATION) =>
  restJson("PATCH", `/v2/projects/${e(proj())}/locations/${e(location)}/buckets/${e(id)}`, { query: updateMask ? { updateMask } : undefined, body });
export const deleteBucket = (id, location = LOCATION) => restJson("DELETE", `/v2/projects/${e(proj())}/locations/${e(location)}/buckets/${e(id)}`);

export const listViews = (bucketId, location = LOCATION) =>
  restJson("GET", `/v2/projects/${e(proj())}/locations/${e(location)}/buckets/${e(bucketId)}/views`).then((r) => r.views || []);
export const createView = (bucketId, id, body, location = LOCATION) =>
  restJson("POST", `/v2/projects/${e(proj())}/locations/${e(location)}/buckets/${e(bucketId)}/views`, { query: { viewId: id }, body });
export const deleteView = (bucketId, id, location = LOCATION) =>
  restJson("DELETE", `/v2/projects/${e(proj())}/locations/${e(location)}/buckets/${e(bucketId)}/views/${e(id)}`);

export const bucketLocation = (name) => name.match(/\/locations\/([^/]+)\//)?.[1] || LOCATION;
export const bucketId = (name) => name.split("/buckets/")[1];

export const REGIONS = [
  ["us-east1", "us-east1 (South Carolina)"], ["global", "global"], ["us-central1", "us-central1 (Iowa)"],
  ["europe-west1", "europe-west1 (Belgium)"], ["asia-east1", "asia-east1 (Taiwan)"],
];

export const validBucketId = (n) => {
  if (!n) return "A log bucket name is required.";
  if (n.length > 100) return "Log bucket names must be 100 characters or fewer.";
  if (!/^[A-Za-z0-9_-]+$/.test(n)) return "Use only letters, numbers, underscores (_) and hyphens (-).";
  return null;
};
