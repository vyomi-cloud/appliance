/* Service Bus over the native Azure wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.ServiceBus/
 *                  namespaces/{ns}[/queues/{q}|/topics/{t}|/authorizationRules/{r}]
 *                  (queues/topics/authorizationRules are real ARM sub-resources of a namespace —
 *                  no separate data-plane step creates them, same as the real control plane).
 *   Data plane:    the Service Bus REST surface core/azure_servicebus_core.py speaks, scoped
 *                  by entity name only (Vyomi's Service Bus data plane is one flat namespace
 *                  across every account, the same simplification the AWS lens makes for
 *                  KMS/Secrets Manager) — used only by the queue's Service Bus Explorer
 *                  (send/peek/receive/complete/defer/dead-letter; topics have no explorer here).
 */
import { WireError, WIRE_BASE } from "../../../common/wire.js";
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

const AUTHZ_API = "2022-04-01";
const DIAG_API = "2021-05-01-preview";
const DR_API = "2022-10-01-preview";

export const ARM = armType("Microsoft.ServiceBus", "namespaces", "2022-10-01-preview");

const shape = (v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup });

export const listNamespaces = async () => (await ARM.list()).map(shape);
export const getNamespace = async (rg, name) => shape(await ARM.get(rg, name));
export const createNamespace = (rg, name, body) => ARM.put(rg, name, body);
export const updateNamespace = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteNamespace = (rg, name) => ARM.remove(rg, name);

export const namespaceEndpoint = (name) => `https://${name}.servicebus.windows.net/`;
export const skuLabel = (sku) => sku?.name || "Standard";

// ── ISO8601 duration <-> {value, unit} (the portal's "Days / Hours / Minutes / Seconds" pickers) ──
const UNIT_SECONDS = { Seconds: 1, Minutes: 60, Hours: 3600, Days: 86400 };
export function toDuration(value, unit) {
  let sec = Math.max(0, Number(value || 0)) * (UNIT_SECONDS[unit] || 1);
  const d = Math.floor(sec / 86400); sec %= 86400;
  const h = Math.floor(sec / 3600); sec %= 3600;
  const m = Math.floor(sec / 60); const s = Math.floor(sec % 60);
  let out = "P";
  if (d) out += `${d}D`;
  if (h || m || s) { out += "T"; if (h) out += `${h}H`; if (m) out += `${m}M`; if (s) out += `${s}S`; }
  return out === "P" ? "P0D" : out;
}
export function fromDuration(iso) {
  const m = /^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/.exec(iso || "");
  if (!m) return { value: 0, unit: "Seconds" };
  const [, d, h, mi, s] = m.slice(1).map((x) => Number(x || 0));
  if (d) return { value: d, unit: "Days" };
  if (h) return { value: h, unit: "Hours" };
  if (mi) return { value: mi, unit: "Minutes" };
  return { value: s, unit: "Seconds" };
}
export const fmtDuration = (iso) => { const { value, unit } = fromDuration(iso); return `${value} ${unit.toLowerCase()}`; };

// ── Queues (ARM sub-resource of the namespace — real control-plane metadata) ───────────
const queuesPath = (rg, ns) => `${ARM.path(rg, ns)}/queues`;
const queuePath = (rg, ns, name) => `${queuesPath(rg, ns)}/${encodeURIComponent(name)}`;
const q = { "api-version": ARM.apiVersion };

export const listQueues = async (rg, ns) => (await restJson("GET", queuesPath(rg, ns), { query: q })).value || [];
export const getQueueArm = (rg, ns, name) => restJson("GET", queuePath(rg, ns, name), { query: q });
export const putQueueArm = (rg, ns, name, body) => restJson("PUT", queuePath(rg, ns, name), { query: q, body });
export const deleteQueueArm = (rg, ns, name) => restJson("DELETE", queuePath(rg, ns, name), { query: q });

export function queueArmBody(f) {
  return {
    properties: {
      maxSizeInMegabytes: Number(f.maxSizeGb || 1) * 1024,
      maxDeliveryCount: Number(f.maxDeliveryCount || 10),
      defaultMessageTimeToLive: toDuration(f.ttlValue, f.ttlUnit),
      lockDuration: toDuration(f.lockValue, f.lockUnit),
      autoDeleteOnIdleEnabled: !!f.autoDelete,
      requiresDuplicateDetection: !!f.duplicateDetection,
      deadLetteringOnMessageExpiration: !!f.deadLetterOnExpiry,
      enablePartitioning: !!f.partitioning,
      requiresSession: !!f.sessions,
      forwardingEnabled: !!f.forwarding,
    },
  };
}

// ── Topics (ARM sub-resource of the namespace) ──────────────────────────────────────────
const topicsPath = (rg, ns) => `${ARM.path(rg, ns)}/topics`;
const topicPath = (rg, ns, name) => `${topicsPath(rg, ns)}/${encodeURIComponent(name)}`;

export const listTopics = async (rg, ns) => (await restJson("GET", topicsPath(rg, ns), { query: q })).value || [];
export const getTopicArm = (rg, ns, name) => restJson("GET", topicPath(rg, ns, name), { query: q });
export const putTopicArm = (rg, ns, name, body) => restJson("PUT", topicPath(rg, ns, name), { query: q, body });
export const deleteTopicArm = (rg, ns, name) => restJson("DELETE", topicPath(rg, ns, name), { query: q });

export function topicArmBody(f) {
  return {
    properties: {
      maxSizeInMegabytes: Number(f.maxSizeGb || 1) * 1024,
      defaultMessageTimeToLive: toDuration(f.ttlValue, f.ttlUnit),
      autoDeleteOnIdleEnabled: !!f.autoDelete,
      requiresDuplicateDetection: !!f.duplicateDetection,
      enablePartitioning: !!f.partitioning,
      supportOrdering: !!f.ordering,
    },
  };
}

// ── Shared access policies (Microsoft.ServiceBus/namespaces/AuthorizationRules) ────────
const sasPath = (rg, ns, name) => `${ARM.path(rg, ns)}/authorizationRules${name ? `/${encodeURIComponent(name)}` : ""}`;

export const listSasPolicies = async (rg, ns) => (await restJson("GET", sasPath(rg, ns), { query: q })).value || [];
export const putSasPolicy = (rg, ns, name, rights) => restJson("PUT", sasPath(rg, ns, name), { query: q, body: { properties: { rights } } });
export const deleteSasPolicy = (rg, ns, name) => restJson("DELETE", sasPath(rg, ns, name), { query: q });
export const listSasKeys = (rg, ns, name) => restJson("POST", `${sasPath(rg, ns, name)}/listKeys`, { query: q, body: {} });
export const sasConnectionString = (ns, ruleName, key) => `Endpoint=sb://${ns}.servicebus.windows.net/;SharedAccessKeyName=${ruleName};SharedAccessKey=${key}`;

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ──────────
const LOCK_API_VERSION = "2020-05-01";
const lockPath = (rg, name, lockName) => `${ARM.path(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;

export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to this namespace) ──
export const listActivityLog = async (rg, name) => {
  const rid = ARM.path(rg, name);
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${rid}'` };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── create-namespace form model → ARM body ──────────────────────────────────────────────
export function namespaceArmBody(f) {
  const premium = f.pricingTier === "Premium";
  return {
    location: f.location,
    sku: { name: f.pricingTier, tier: f.pricingTier, ...(premium ? { capacity: Number(f.messagingUnits || 1) } : {}) },
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      minimumTlsVersion: f.minTls,
      disableLocalAuth: f.localAuth === "Disabled",
      publicNetworkAccess: f.connectivity === "Private access" ? "Disabled" : "Enabled",
      ...(premium ? { premiumMessagingPartitions: Number(f.partitions || 1) } : {}),
    },
  };
}

// ── Data plane: the queue's Service Bus Explorer (direct backlog, no subscription) ─────
// Vyomi's Service Bus data plane (core/azure_servicebus_core.py) is scoped by entity name
// only, like the AWS lens's shared KMS/Secrets Manager stores — two namespaces sharing a
// queue name would share its backlog in this simulator. Acceptable for a single-tenant sim.
async function sbFetch(method, path, { headers = {}, body } = {}) {
  const res = await fetch(`${WIRE_BASE}${path}`, { method, headers, body });
  const text = res.status === 204 ? "" : await res.text();
  if (!res.ok) {
    let detail = text;
    try { detail = JSON.parse(text).detail || text; } catch { /* not JSON */ }
    throw new WireError(res.status, `HTTP${res.status}`, detail, text);
  }
  return text ? JSON.parse(text) : {};
}

const ENTITY_HEADERS = { "content-type": "application/atom+xml" };

/** Provision (or remove) the data-plane entity backing a queue's message backlog —
 *  one native call per queue, alongside the ARM metadata PUT/DELETE above. */
export const createQueueEntity = (name) => sbFetch("PUT", `/${encodeURIComponent(name)}`, { headers: ENTITY_HEADERS });
export const deleteQueueEntity = (name) => sbFetch("DELETE", `/${encodeURIComponent(name)}`, { headers: ENTITY_HEADERS }).catch(() => {});

export const peekMessages = async (name) => (await sbFetch("GET", `/${encodeURIComponent(name)}/messages`)).messages || [];
export const receiveMessages = async (name, max = 32) => (await sbFetch("DELETE", `/${encodeURIComponent(name)}/messages?max=${max}`)).messages || [];
export const peekDeadLetter = async (name) => (await sbFetch("GET", `/${encodeURIComponent(name)}/$deadletterqueue/messages`)).messages || [];

export function sendMessage(name, bodyText, { label, contentType = "Text/Plain", customProperties = {} } = {}) {
  const broker = { ...(label ? { Label: label } : {}), ...customProperties };
  return sbFetch("POST", `/${encodeURIComponent(name)}/messages`, {
    headers: { "content-type": contentType.toLowerCase(), brokerproperties: JSON.stringify(broker) },
    body: bodyText,
  });
}
export const completeMessage = (name, seq) => sbFetch("POST", `/${encodeURIComponent(name)}/messages/${encodeURIComponent(seq)}/complete`);
export const deferMessage = (name, seq) => sbFetch("POST", `/${encodeURIComponent(name)}/messages/${encodeURIComponent(seq)}/defer`);
export const deadLetterMessage = (name, seq, reason) => sbFetch("POST", `/${encodeURIComponent(name)}/messages/${encodeURIComponent(seq)}/deadletter`, {
  headers: { "content-type": "application/json" }, body: JSON.stringify({ DeadLetterReason: reason || "" }),
});
export const completeDeadLetterMessage = (name, seq) => sbFetch("POST", `/${encodeURIComponent(name)}/$deadletterqueue/messages/${encodeURIComponent(seq)}/complete`);

// ── Access control (IAM): Microsoft.Authorization/roleAssignments + roleDefinitions +
// checkAccess, all real ARM resources/actions resource-scoped to this namespace (plus its
// subscription/resource-group ancestors — real Azure's inherited-access view), the same
// generic extension-resource engine the NSG/VM/VNet/Cosmos blades use (core/azure_arm_core.py). ──
export const listRoleAssignments = async (rg, name) =>
  (await restJson("GET", `${ARM.path(rg, name)}/providers/Microsoft.Authorization/roleAssignments`, { query: { "api-version": AUTHZ_API } })).value || [];
export const listRoleDefinitions = async () =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/roleDefinitions`, { query: { "api-version": AUTHZ_API } })).value || [];
export const checkAccess = async (nsId, principalId, action) =>
  (await restJson("POST", `${nsId}/providers/Microsoft.Authorization/checkAccess`, { query: { "api-version": AUTHZ_API }, body: { principalId, action } })).value || [];

// ── Locks at the Subscription / Resource group scope (the Locks panel's scope-switcher
// buttons) — the SAME generic Microsoft.Authorization/locks engine, just scoped to the
// containing group/subscription instead of this namespace (read-only here: those locks are
// managed from the Resource group / Subscription blades, not from a namespace's Locks panel). ──
export const listLocksAtResourceGroup = async (rg) =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/resourceGroups/${encodeURIComponent(rg)}/providers/Microsoft.Authorization/locks`, { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const listLocksAtSubscription = async () =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/locks`, { query: { "api-version": LOCK_API_VERSION } })).value || [];

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, a real ARM extension
// resource scoped to this namespace's own id — same generic mechanism APIM's Diagnostic
// settings blade uses, core/azure_arm_core.AzureArm._diagnostic_settings). ─────────────────
const diagPath = (rg, name, setting) => `${ARM.path(rg, name)}/providers/Microsoft.Insights/diagnosticSettings${setting ? `/${encodeURIComponent(setting)}` : ""}`;
export const listDiagnosticSettings = async (rg, name) => (await restJson("GET", diagPath(rg, name), { query: { "api-version": DIAG_API } })).value || [];
export const putDiagnosticSetting = (rg, name, setting, body) => restJson("PUT", diagPath(rg, name, setting), { query: { "api-version": DIAG_API }, body });
export const deleteDiagnosticSetting = (rg, name, setting) => restJson("DELETE", diagPath(rg, name, setting), { query: { "api-version": DIAG_API } });
export const listWorkspaces = async () =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.OperationalInsights/workspaces`, { query: { "api-version": "2022-10-01" } })).value || [];

// ── Alert rules (Microsoft.Insights/metricAlerts) — a plain RG-scoped ARM resource whose
// properties.scopes[] names the target(s) it watches; this namespace's Alerts panel lists
// only the rules that target it (core/azure_monitor_core.py owns the generic CRUD). Real
// enforcement stops at "the rule round-trips as configured" — there is no metrics pipeline
// to actually evaluate a condition against, so a rule never fires (azure.servicebus.namespace.alerts). ──
const METRIC_ALERTS_API = "2018-03-01";
const alertPath = (rg, ruleName) => `/subscriptions/${getSubscription()}/resourceGroups/${encodeURIComponent(rg)}/providers/Microsoft.Insights/metricAlerts${ruleName ? `/${encodeURIComponent(ruleName)}` : ""}`;
export const listAlertsForNamespace = async (rg, nsId) => {
  const all = (await restJson("GET", alertPath(rg), { query: { "api-version": METRIC_ALERTS_API } })).value || [];
  return all.filter((r) => (r.properties?.scopes || []).some((s) => s.toLowerCase() === nsId.toLowerCase()));
};
export const putAlert = (rg, ruleName, body) => restJson("PUT", alertPath(rg, ruleName), { query: { "api-version": METRIC_ALERTS_API }, body });
export const deleteAlert = (rg, ruleName) => restJson("DELETE", alertPath(rg, ruleName), { query: { "api-version": METRIC_ALERTS_API } });
export const ALERT_METRICS = ["ActiveMessages", "DeadletteredMessages", "IncomingMessages", "OutgoingMessages", "ServerSendLatency"];
export const ALERT_OPERATORS = ["GreaterThan", "GreaterThanOrEqual", "LessThan", "LessThanOrEqual"];

// ── Logs (a Log Analytics query, defaulted to this namespace's own AzureActivity rows — the
// same POST .../workspaces/{ws}/api/query pass-through the Monitor service's own Logs page
// uses, core/azure_operationalinsights_core.py; only the AzureActivity table returns real
// rows, see azure.monitor.log_query) ────────────────────────────────────────────────────────
export const runLogQuery = (rg, name, query) =>
  restJson("POST", `/subscriptions/${getSubscription()}/resourceGroups/${encodeURIComponent(rg)}/providers/Microsoft.OperationalInsights/workspaces/${encodeURIComponent(name)}/api/query`,
    { query: { "api-version": "2017-10-01" }, body: { query } });

// ── Geo-disaster recovery (Microsoft.ServiceBus/namespaces/{ns}/disasterRecoveryConfigs):
// paired namespaces + alias failover, ENFORCED (core/azure_arm_core.AzureArm._servicebus_georecovery) ──
const drPath = (rg, name, alias) => `${ARM.path(rg, name)}/disasterRecoveryConfigs${alias ? `/${encodeURIComponent(alias)}` : ""}`;
export const listGeoRecovery = async (rg, name) => (await restJson("GET", drPath(rg, name), { query: { "api-version": DR_API } })).value || [];
export const pairGeoRecovery = (rg, name, alias, partnerNamespaceId) =>
  restJson("PUT", drPath(rg, name, alias), { query: { "api-version": DR_API }, body: { properties: { partnerNamespace: partnerNamespaceId } } });
export const breakGeoRecoveryPairing = (rg, name, alias) => restJson("DELETE", drPath(rg, name, alias), { query: { "api-version": DR_API } });
export const failoverGeoRecovery = (rg, name, alias) => restJson("POST", `${drPath(rg, name, alias)}/failOver`, { query: { "api-version": DR_API }, body: {} });
