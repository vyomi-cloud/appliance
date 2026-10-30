/* SQS over the native JSON wire (X-Amz-Target AmazonSQS.*), plus the real SNS Query-wire
 * calls the SQS console itself makes for "Subscribe to Amazon SNS topic" (sns:Subscribe
 * with Protocol=sqs really fans a Publish out into the queue — see core/sns_core.py). */
import { awsJson, awsQuery, asList } from "../../../common/wire.js";

const call = (op, body) => awsJson("sqs", `AmazonSQS.${op}`, body, { version: "1.0" });
const snsCall = (action, params) => awsQuery("sns", action, params, { version: "2010-03-31" });

export const nameFromUrl = (url) => (url || "").replace(/\/+$/, "").split("/").pop();
export const isFifoName = (name) => (name || "").endsWith(".fifo");

export const createQueue = (input) => call("CreateQueue", input).then((r) => r.QueueUrl);
export const getQueueUrl = (name) => call("GetQueueUrl", { QueueName: name }).then((r) => r.QueueUrl);
export const listQueueUrls = (prefix) => call("ListQueues", prefix ? { QueueNamePrefix: prefix } : {}).then((r) => r.QueueUrls || []);
export const deleteQueue = (url) => call("DeleteQueue", { QueueUrl: url });
export const getQueueAttributes = (url) => call("GetQueueAttributes", { QueueUrl: url, AttributeNames: ["All"] }).then((r) => r.Attributes || {});
export const setQueueAttributes = (url, attrs) => call("SetQueueAttributes", { QueueUrl: url, Attributes: attrs });
export const purgeQueue = (url) => call("PurgeQueue", { QueueUrl: url });

export const sendMessage = (url, input) => call("SendMessage", { QueueUrl: url, ...input });
export const receiveMessage = (url, opts = {}) => call("ReceiveMessage", { QueueUrl: url, MaxNumberOfMessages: 10, WaitTimeSeconds: 0, ...opts }).then((r) => r.Messages || []);
export const deleteMessage = (url, receiptHandle) => call("DeleteMessage", { QueueUrl: url, ReceiptHandle: receiptHandle });
export const changeMessageVisibility = (url, receiptHandle, timeout) => call("ChangeMessageVisibility", { QueueUrl: url, ReceiptHandle: receiptHandle, VisibilityTimeout: timeout });

export const listQueueTags = (url) => call("ListQueueTags", { QueueUrl: url }).then((r) => r.Tags || {});
export const tagQueue = (url, tags) => call("TagQueue", { QueueUrl: url, Tags: tags });
export const untagQueue = (url, keys) => call("UntagQueue", { QueueUrl: url, TagKeys: keys });

/** The list page's columns (Type, Created, Messages available/in flight, Encryption,
 * Content-based dedup) all come from GetQueueAttributes — one native call per queue. */
export async function listQueues(prefix) {
  const urls = await listQueueUrls(prefix);
  return Promise.all(urls.map(async (url) => {
    const attrs = await getQueueAttributes(url);
    return { url, name: nameFromUrl(url), attrs };
  }));
}

export const queueType = (attrs) => (String(attrs.FifoQueue).toLowerCase() === "true" ? "FIFO" : "Standard");
export const encryptionOf = (attrs) => (attrs.KmsMasterKeyId ? "SSE-KMS" : (String(attrs.SqsManagedSseEnabled ?? "true").toLowerCase() !== "false" ? "SSE-SQS" : "None"));

export function redrivePolicy(attrs) {
  try { return attrs.RedrivePolicy ? JSON.parse(attrs.RedrivePolicy) : null; } catch { return null; }
}
export function redriveAllowPolicy(attrs) {
  try { return attrs.RedriveAllowPolicy ? JSON.parse(attrs.RedriveAllowPolicy) : null; } catch { return null; }
}

// ── dead-letter queue redrive tasks (StartMessageMoveTask et al.) ────────────────────────
export const listDeadLetterSourceQueueUrls = (dlqUrl) => call("ListDeadLetterSourceQueues", { QueueUrl: dlqUrl }).then((r) => r.queueUrls || []);
export async function listDeadLetterSources(dlqUrl) {
  const urls = await listDeadLetterSourceQueueUrls(dlqUrl);
  return Promise.all(urls.map(async (url) => ({ url, name: nameFromUrl(url), attrs: await getQueueAttributes(url) })));
}
export const startMessageMoveTask = (sourceArn, destinationArn) => call("StartMessageMoveTask", { SourceArn: sourceArn, ...(destinationArn ? { DestinationArn: destinationArn } : {}) }).then((r) => r.TaskHandle);
export const listMessageMoveTasks = (sourceArn) => call("ListMessageMoveTasks", { SourceArn: sourceArn, MaxResults: 10 }).then((r) => r.Results || []);

// ── SNS (native Query wire) — real cross-service calls the SQS console itself makes ──────
export const listTopics = async () => asList((await snsCall("ListTopics", {})).ListTopicsResponse?.ListTopicsResult?.Topics?.member).map((m) => (typeof m === "string" ? m : m.TopicArn));

export async function listSubscriptionsForQueue(queueArn) {
  const r = await snsCall("ListSubscriptions", {});
  const members = asList(r.ListSubscriptionsResponse?.ListSubscriptionsResult?.Subscriptions?.member);
  return members.filter((m) => m.Endpoint === queueArn);
}

export const subscribeQueueToTopic = (topicArn, queueArn) => snsCall("Subscribe", { TopicArn: topicArn, Protocol: "sqs", Endpoint: queueArn, ReturnSubscriptionArn: "true" })
  .then((r) => r.SubscribeResponse?.SubscribeResult?.SubscriptionArn);
export const unsubscribe = (subscriptionArn) => snsCall("Unsubscribe", { SubscriptionArn: subscriptionArn });

export const b64 = (s) => btoa(unescape(encodeURIComponent(s)));
