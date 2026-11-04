/* Pub/Sub over the NATIVE Pub/Sub REST API v1 (the same wire google-cloud-pubsub (REST
 * transport) and `gcloud pubsub` speak). Every call here is a real topics/subscriptions/
 * snapshots/schemas operation — no bespoke /api/* endpoint. */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
const base = () => `/v1/projects/${e(getProject())}`;

// ── names (full resource names, for use in JSON bodies — never URL-encode these as a
// whole, since encoding the "/" separators would break the path builders below) ──────────
export const topicName = (id) => `projects/${getProject()}/topics/${id}`;
export const subName = (id) => `projects/${getProject()}/subscriptions/${id}`;
export const snapshotName = (id) => `projects/${getProject()}/snapshots/${id}`;
export const schemaName = (id) => `projects/${getProject()}/schemas/${id}`;
export const shortId = (name) => (name || "").split("/").pop();

// ── paths (each segment encoded individually, so "/" stays a path separator) ─────────────
const topicPath = (id) => `${base()}/topics/${e(id)}`;
const subPath = (id) => `${base()}/subscriptions/${e(id)}`;
const snapshotPath = (id) => `${base()}/snapshots/${e(id)}`;
const schemaPath = (id) => `${base()}/schemas/${e(id)}`;

// ── topics ───────────────────────────────────────────────────────────────
export async function listTopics() {
  const r = await restJson("GET", `${base()}/topics`);
  return r.topics || [];
}
export const getTopic = (id) => restJson("GET", topicPath(id));
export const createTopic = (id, body) => restJson("PUT", topicPath(id), { body });
export const patchTopic = (id, fields, updateMask) => restJson("PATCH", topicPath(id), { body: { topic: fields, updateMask } });
export const deleteTopic = (id) => restJson("DELETE", topicPath(id));
export const publish = (id, messages) => restJson("POST", `${topicPath(id)}:publish`, { body: { messages } });

// ── subscriptions ────────────────────────────────────────────────────────
export async function listSubscriptions() {
  const r = await restJson("GET", `${base()}/subscriptions`);
  return r.subscriptions || [];
}
export const getSubscription = (id) => restJson("GET", subPath(id));
export const createSubscription = (id, body) => restJson("PUT", subPath(id), { body });
export const patchSubscription = (id, fields, updateMask) => restJson("PATCH", subPath(id), { body: { subscription: fields, updateMask } });
export const deleteSubscription = (id) => restJson("DELETE", subPath(id));
export const pull = (id, maxMessages = 10) => restJson("POST", `${subPath(id)}:pull`, { body: { maxMessages } });
export const acknowledge = (id, ackIds) => restJson("POST", `${subPath(id)}:acknowledge`, { body: { ackIds } });
export const seek = (id, body) => restJson("POST", `${subPath(id)}:seek`, { body });

/** Every subscription attached to one topic — the console derives this client-side
 * (the native API has no "subscriptions of this topic" filter beyond the full list). */
export async function subscriptionsOfTopic(id) {
  const all = await listSubscriptions();
  return all.filter((s) => s.topic === topicName(id));
}

// ── snapshots ────────────────────────────────────────────────────────────
export async function listSnapshots() {
  const r = await restJson("GET", `${base()}/snapshots`);
  return r.snapshots || [];
}
export const createSnapshot = (id, subscription, labels) => restJson("PUT", snapshotPath(id), { body: { subscription, labels } });
export const deleteSnapshot = (id) => restJson("DELETE", snapshotPath(id));

// ── schemas ──────────────────────────────────────────────────────────────
export async function listSchemas() {
  const r = await restJson("GET", `${base()}/schemas`);
  return r.schemas || [];
}
export const getSchema = (id) => restJson("GET", schemaPath(id), { query: { view: "FULL" } });
export const createSchema = (id, type, definition) => restJson("POST", `${base()}/schemas`, { query: { schemaId: id }, body: { type, definition } });
export const deleteSchema = (id) => restJson("DELETE", schemaPath(id));

// ── display helpers ────────────────────────────────────────────────────────
export const labelsText = (labels) => { const n = Object.keys(labels || {}).length; return n ? Object.entries(labels).map(([k, v]) => `${k}: ${v}`).join(", ") : "None"; };
export const encryptionText = (topic) => topic.kmsKeyName || "Google-managed encryption key";
export const durationText = (wire) => {
  if (!wire) return "Not set";
  const secs = Number(String(wire).replace(/s$/, ""));
  if (!secs) return "Not set";
  if (secs % 86400 === 0) return `${secs / 86400} day${secs / 86400 === 1 ? "" : "s"}`;
  if (secs % 3600 === 0) return `${secs / 3600} hour${secs / 3600 === 1 ? "" : "s"}`;
  if (secs % 60 === 0) return `${secs / 60} minute${secs / 60 === 1 ? "" : "s"}`;
  return `${secs} seconds`;
};
export const deliveryTypeText = (sub) => (
  sub.cloudStorageConfig ? "Write to Cloud Storage" : sub.pushConfig?.pushEndpoint ? "Push" : "Pull"
);
export const expirationText = (sub) => {
  const p = sub.expirationPolicy;
  if (!p || Object.keys(p).length === 0) return "Never expires";
  return `${durationText(p.ttl)} of inactivity`;
};
export const orderingText = (sub) => (sub.enableMessageOrdering ? "On" : "Off");
export const exactlyOnceText = (sub) => (sub.enableExactlyOnceDelivery ? "On" : "Off");
export const retentionText = (sub) => durationText(sub.messageRetentionDuration);

export const validId = (id) => /^[A-Za-z][A-Za-z0-9_.~+%-]{2,254}$/.test(id || "");

// ── Metrics tab: real Cloud Monitoring time series mirrored from the core's own activity
// (core/gcp_pubsub_core.py's _sync_topic_metrics / _sync_subscription_metrics) — the
// console reads them back over the native Monitoring timeSeries API, the same cross-API
// hand-off the real console's embedded Metrics widget makes. ────────────────────────────
async function recentSeries(metricType, extraFilter) {
  const end = new Date(), start = new Date(end.getTime() - 3600_000);
  const r = await restJson("GET", `/v3/projects/${e(getProject())}/timeSeries`, { query: {
    filter: `metric.type = "${metricType}" AND ${extraFilter}`,
    "interval.startTime": start.toISOString(), "interval.endTime": end.toISOString(),
  } });
  return r.timeSeries?.[0]?.points || [];
}
export const pointValue = (p) => Number(p?.value?.int64Value ?? p?.value?.doubleValue ?? 0);

export async function topicMetrics(id) {
  await getTopic(id);   // lazily refreshes the mirrored metrics — there is no background poller
  const published = await recentSeries("pubsub.googleapis.com/topic/send_message_operation_count", `resource.labels.topic_id = "${id}"`);
  return { published };
}

export async function subscriptionMetrics(id) {
  await getSubscription(id);
  const [backlog, oldest] = await Promise.all([
    recentSeries("pubsub.googleapis.com/subscription/num_undelivered_messages", `resource.labels.subscription_id = "${id}"`),
    recentSeries("pubsub.googleapis.com/subscription/oldest_unacked_message_age", `resource.labels.subscription_id = "${id}"`),
  ]);
  return { backlog, oldest };
}

export const decode = (b64) => { try { return atob(b64 || ""); } catch { return ""; } };
export const encode = (text) => btoa(text || "");

// ── Messages tab (console-local, not a real Pub/Sub API): Pub/Sub has no "list messages
// published to this topic" call, so the Messages tab shows what THIS browser session has
// actually published, via api.publish() above — never fabricated data. ──
const sentKey = (id) => `vyomi.v4.gcp.pubsub.sent.${id}`;
export function readSentMessages(id) {
  try { return JSON.parse(sessionStorage.getItem(sentKey(id)) || "[]"); } catch { return []; }
}
export function recordSentMessages(id, records) {
  const next = [...records, ...readSentMessages(id)].slice(0, 50);
  try { sessionStorage.setItem(sentKey(id), JSON.stringify(next)); } catch { /* ignore */ }
  return next;
}
