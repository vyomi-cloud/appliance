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

/** All deliverable target types, for the target picker across Create rule / Create schedule. */
export async function listAllTargets() {
  const [queues, topics, fns] = await Promise.all([listQueueTargets(), listTopicTargets(), listFunctionTargets()]);
  return [...queues, ...topics, ...fns];
}
