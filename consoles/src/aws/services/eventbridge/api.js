/* EventBridge + EventBridge Scheduler over their native wires.
 *   EventBridge: X-Amz-Target JSON ("AWSEvents.*") — awsJson.
 *   Scheduler:   REST JSON (/schedules, /schedule-groups), SigV4-signed as "scheduler" —
 *                restJson doesn't sign (it's shared with the unsigned GCP/Azure lenses), so
 *                this file builds the same credential-scope header wire.js's own AWS helpers
 *                use, just scoped to the "scheduler" service name.
 * Target pickers (SQS queues / SNS topics / Lambda functions) call those services' own
 * native wires too — exactly what the real EventBridge console does to populate them. */
import { asList, awsJson, awsQuery, getRegion, restJson } from "../../../common/wire.js";

const E = (op, body) => awsJson("events", `AWSEvents.${op}`, body, { version: "1.1" });

// ── event buses ──────────────────────────────────────────────────────────────
export const listEventBuses = (namePrefix) => E("ListEventBuses", namePrefix ? { NamePrefix: namePrefix } : {}).then((r) => r.EventBuses || []);
export const createEventBus = (input) => E("CreateEventBus", input);
export const deleteEventBus = (name) => E("DeleteEventBus", { Name: name });
export const describeEventBus = (name) => E("DescribeEventBus", { Name: name });
export const updateEventBus = (name, description) => E("UpdateEventBus", { Name: name, Description: description });

// ── rules ────────────────────────────────────────────────────────────────────
export const listRules = (eventBusName) => E("ListRules", { EventBusName: eventBusName || "default" }).then((r) => r.Rules || []);
export const describeRule = (name, eventBusName) => E("DescribeRule", { Name: name, EventBusName: eventBusName || "default" });
export const putRule = (input) => E("PutRule", input);
export const deleteRule = (name, eventBusName) => E("DeleteRule", { Name: name, EventBusName: eventBusName || "default" });
export const enableRule = (name, eventBusName) => E("EnableRule", { Name: name, EventBusName: eventBusName || "default" });
export const disableRule = (name, eventBusName) => E("DisableRule", { Name: name, EventBusName: eventBusName || "default" });

export const listTargetsByRule = (rule, eventBusName) => E("ListTargetsByRule", { Rule: rule, EventBusName: eventBusName || "default" }).then((r) => r.Targets || []);
export const putTargets = (rule, eventBusName, targets) => E("PutTargets", { Rule: rule, EventBusName: eventBusName || "default", Targets: targets });
export const removeTargets = (rule, eventBusName, ids) => E("RemoveTargets", { Rule: rule, EventBusName: eventBusName || "default", Ids: ids });

// ── events ───────────────────────────────────────────────────────────────────
export const putEvents = (entries) => E("PutEvents", { Entries: entries });

// ── archives / replay ────────────────────────────────────────────────────────
export const listArchives = (eventSourceArn) => E("ListArchives", eventSourceArn ? { EventSourceArn: eventSourceArn } : {}).then((r) => r.Archives || []);
export const describeArchive = (archiveName) => E("DescribeArchive", { ArchiveName: archiveName });
export const createArchive = (input) => E("CreateArchive", input);
export const deleteArchive = (archiveName) => E("DeleteArchive", { ArchiveName: archiveName });
export const updateArchive = (input) => E("UpdateArchive", input);
export const startReplay = (input) => E("StartReplay", input);
export const listReplays = () => E("ListReplays", {}).then((r) => r.Replays || []);
export const describeReplay = (replayName) => E("DescribeReplay", { ReplayName: replayName });

// ── tags ─────────────────────────────────────────────────────────────────────
export const listTagsForResource = (arn) => E("ListTagsForResource", { ResourceARN: arn }).then((r) => r.Tags || []);
export const tagResource = (arn, tags) => E("TagResource", { ResourceARN: arn, Tags: tags });
export const untagResource = (arn, tagKeys) => E("UntagResource", { ResourceARN: arn, TagKeys: tagKeys });

// ── EventBridge Scheduler (REST, signed as "scheduler") ─────────────────────
// restJson() (consoles/src/common/wire.js) carries no SigV4 — it's shared with the
// unsigned GCP/Azure lenses — so AWS REST services sign their own credential-scope
// header the same way wire.js's awsJson/awsQuery do internally.
const amzDate = () => new Date().toISOString().replace(/[-:]|\.\d{3}/g, "");
function restHeaders(service) {
  const d = amzDate();
  return { authorization: `AWS4-HMAC-SHA256 Credential=VYOMICONSOLE/${d.slice(0, 8)}/${getRegion()}/${service}/aws4_request, SignedHeaders=host;x-amz-date, Signature=0`, "x-amz-date": d };
}
const S = (method, path, opts = {}) => restJson(method, path, { ...opts, headers: { ...restHeaders("scheduler"), ...(opts.headers || {}) } });

export const listSchedules = (groupName) => S("GET", "/schedules", { query: groupName ? { GroupName: groupName } : {} }).then((r) => r.Schedules || []);
export const getSchedule = (name, groupName) => S("GET", `/schedules/${encodeURIComponent(name)}`, { query: { GroupName: groupName || "default" } });
export const createSchedule = (name, body) => S("POST", `/schedules/${encodeURIComponent(name)}`, { body });
export const updateSchedule = (name, body) => S("PUT", `/schedules/${encodeURIComponent(name)}`, { body });
export const deleteSchedule = (name, groupName) => S("DELETE", `/schedules/${encodeURIComponent(name)}`, { query: { GroupName: groupName || "default" } });

export const listScheduleGroups = () => S("GET", "/schedule-groups").then((r) => r.ScheduleGroups || []);
export const getScheduleGroup = (name) => S("GET", `/schedule-groups/${encodeURIComponent(name)}`);
export const createScheduleGroup = (name) => S("POST", `/schedule-groups/${encodeURIComponent(name)}`);
export const deleteScheduleGroup = (name) => S("DELETE", `/schedule-groups/${encodeURIComponent(name)}`);

// ── target pickers: SQS queues / SNS topics / Lambda functions ─────────────
export async function listQueueTargets() {
  const r = await awsJson("sqs", "AmazonSQS.ListQueues", {});
  const urls = r.QueueUrls || [];
  const out = [];
  for (const url of urls) {
    const a = await awsJson("sqs", "AmazonSQS.GetQueueAttributes", { QueueUrl: url, AttributeNames: ["QueueArn"] });
    const name = url.split("/").pop();
    out.push({ arn: a.Attributes?.QueueArn, label: `SQS queue: ${name}` });
  }
  return out;
}

export async function listTopicTargets() {
  const r = await awsQuery("sns", "ListTopics", {});
  const members = asList(r.ListTopicsResponse?.ListTopicsResult?.Topics?.member);
  return members.filter(Boolean).map((t) => ({ arn: t.TopicArn, label: `SNS topic: ${t.TopicArn.split(":").pop()}` }));
}

export async function listFunctionTargets() {
  const r = await restJson("GET", "/2015-03-31/functions", { headers: restHeaders("lambda") });
  return (r.Functions || []).map((f) => ({ arn: f.FunctionArn, label: `Lambda function: ${f.FunctionName}` }));
}

export async function listStateMachineTargets() {
  const r = await awsJson("states", "AWSStepFunctions.ListStateMachines", {});
  return (r.stateMachines || []).map((m) => ({ arn: m.stateMachineArn, label: `Step Functions state machine: ${m.name}` }));
}

export async function listStreamTargets() {
  const r = await awsJson("kinesis", "Kinesis_20131202.ListStreams", {}, { version: "1.1" });
  return (r.StreamSummaries || []).map((st) => ({ arn: st.StreamARN, label: `Kinesis stream: ${st.StreamName}` }));
}

/** All deliverable target types, for the target picker across Create rule / Create schedule. */
export async function listAllTargets() {
  const [queues, topics, fns, machines, streams] = await Promise.all([
    listQueueTargets(), listTopicTargets(), listFunctionTargets(), listStateMachineTargets(), listStreamTargets(),
  ]);
  return [...queues, ...topics, ...fns, ...machines, ...streams];
}

// ── Pipes (REST, signed as "pipes") ─────────────────────────────────────────
const P = (method, path, opts = {}) => restJson(method, path, { ...opts, headers: { ...restHeaders("pipes"), ...(opts.headers || {}) } });
export const listPipes = () => P("GET", "/v1/pipes").then((r) => r.Pipes || []);
export const describePipe = (name) => P("GET", `/v1/pipes/${encodeURIComponent(name)}`);
export const createPipe = (name, body) => P("POST", `/v1/pipes/${encodeURIComponent(name)}`, { body });
export const updatePipe = (name, body) => P("PUT", `/v1/pipes/${encodeURIComponent(name)}`, { body });
export const deletePipe = (name) => P("DELETE", `/v1/pipes/${encodeURIComponent(name)}`);
export const startPipe = (name) => P("POST", `/v1/pipes/${encodeURIComponent(name)}/start`);
export const stopPipe = (name) => P("POST", `/v1/pipes/${encodeURIComponent(name)}/stop`);

// ── connections / API destinations / global endpoints / sandbox ──────────────
export const listConnections = () => E("ListConnections", {}).then((r) => r.Connections || []);
export const describeConnection = (name) => E("DescribeConnection", { Name: name });
export const createConnection = (input) => E("CreateConnection", input);
export const updateConnection = (input) => E("UpdateConnection", input);
export const deauthorizeConnection = (name) => E("DeauthorizeConnection", { Name: name });
export const deleteConnection = (name) => E("DeleteConnection", { Name: name });
export const listApiDestinations = () => E("ListApiDestinations", {}).then((r) => r.ApiDestinations || []);
export const describeApiDestination = (name) => E("DescribeApiDestination", { Name: name });
export const createApiDestination = (input) => E("CreateApiDestination", input);
export const updateApiDestination = (input) => E("UpdateApiDestination", input);
export const deleteApiDestination = (name) => E("DeleteApiDestination", { Name: name });
export const listEndpoints = () => E("ListEndpoints", {}).then((r) => r.Endpoints || []);
export const describeEndpoint = (name) => E("DescribeEndpoint", { Name: name });
export const createEndpoint = (input) => E("CreateEndpoint", input);
export const updateEndpoint = (input) => E("UpdateEndpoint", input);
export const deleteEndpoint = (name) => E("DeleteEndpoint", { Name: name });
export const testEventPattern = (eventPattern, event) => E("TestEventPattern", { EventPattern: eventPattern, Event: event });

// ── KMS / bus logs / resource policy (sweep AWS-08) ─────────────────────────
export const listKmsKeys = async () => {
  const r = await awsJson("kms", "TrentService.ListKeys", {}, { version: "1.1" });
  const out = [];
  for (const k of r.Keys || []) {
    try { const md = (await awsJson("kms", "TrentService.DescribeKey", { KeyId: k.KeyId }, { version: "1.1" })).KeyMetadata; if (md.KeyState === "Enabled" && (md.KeyUsage || "ENCRYPT_DECRYPT") === "ENCRYPT_DECRYPT" && md.KeyManager !== "AWS") out.push(md); } catch { /* skip */ }
  }
  return out;
};
export const updateEventBusConfig = (name, cfg) => E("UpdateEventBus", { Name: name, ...cfg });
export const putPermission = (input) => E("PutPermission", input);
export const removePermission = (input) => E("RemovePermission", input);
export const busLogGroup = (bus) => `/aws/vendedlogs/events/event-bus/${bus}`;
export const busLogEvents = (bus) => awsJson("logs", "Logs_20140328.FilterLogEvents", { logGroupName: busLogGroup(bus), limit: 50 }, { version: "1.1" })
  .then((r) => r.events || []).catch(() => []);

// ── EventBridge Schemas (REST, signed as "schemas") ──────────────────────────
const SC = (method, path, opts = {}) => restJson(method, path, { ...opts, headers: { ...restHeaders("schemas"), ...(opts.headers || {}) } });
const enc = encodeURIComponent;
export const listSchemaRegistries = () => SC("GET", "/v1/registries").then((r) => r.Registries || []);
export const createSchemaRegistry = (name, description) => SC("POST", `/v1/registries/name/${enc(name)}`, { body: { Description: description || "" } });
export const deleteSchemaRegistry = (name) => SC("DELETE", `/v1/registries/name/${enc(name)}`);
export const listSchemas = (registry) => SC("GET", `/v1/registries/name/${enc(registry)}/schemas`).then((r) => r.Schemas || []);
export const describeSchema = (registry, name, version) => SC("GET", `/v1/registries/name/${enc(registry)}/schemas/name/${enc(name)}`, { query: version ? { schemaVersion: version } : undefined });
export const createSchema = (registry, name, type, content, description) => SC("POST", `/v1/registries/name/${enc(registry)}/schemas/name/${enc(name)}`, { body: { Type: type, Content: content, Description: description || "" } });
export const updateSchema = (registry, name, content) => SC("PUT", `/v1/registries/name/${enc(registry)}/schemas/name/${enc(name)}`, { body: { Content: content } });
export const deleteSchema = (registry, name) => SC("DELETE", `/v1/registries/name/${enc(registry)}/schemas/name/${enc(name)}`);
export const listSchemaVersions = (registry, name) => SC("GET", `/v1/registries/name/${enc(registry)}/schemas/name/${enc(name)}/versions`).then((r) => r.SchemaVersions || []);
export const searchSchemas = (keywords) => SC("GET", "/v1/search/schemas", { query: { keywords } }).then((r) => r.Schemas || []);
export const listDiscoverers = () => SC("GET", "/v1/discoverers").then((r) => r.Discoverers || []);
export const createDiscoverer = (sourceArn, description) => SC("POST", "/v1/discoverers", { body: { SourceArn: sourceArn, Description: description || "" } });
export const deleteDiscoverer = (id) => SC("DELETE", `/v1/discoverers/id/${enc(id)}`);
export const startDiscoverer = (id) => SC("POST", `/v1/discoverers/id/${enc(id)}/start`);
export const stopDiscoverer = (id) => SC("POST", `/v1/discoverers/id/${enc(id)}/stop`);

// ── partner event sources (sweep AWS-13) ─────────────────────────────────────
export const listEventSources = (namePrefix) => E("ListEventSources", namePrefix ? { NamePrefix: namePrefix } : {}).then((r) => r.EventSources || []);
export const createPartnerEventSource = (name, account) => E("CreatePartnerEventSource", { Name: name, Account: account });
export const deletePartnerEventSource = (name, account) => E("DeletePartnerEventSource", { Name: name, Account: account });
export const activateEventSource = (name) => E("ActivateEventSource", { Name: name });
export const deactivateEventSource = (name) => E("DeactivateEventSource", { Name: name });
export const putPartnerEvents = (entries) => E("PutPartnerEvents", { Entries: entries });
