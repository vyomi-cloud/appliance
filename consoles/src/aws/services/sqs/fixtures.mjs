/* UI-conformance fixtures for SQS (native AmazonSQS.* JSON). See s3/fixtures.mjs. */
const T = (op) => ({ svc: "sqs", target: `AmazonSQS.${op}` });

async function queueUrl(wire, name) {
  const r = await wire("POST", "/", { ...T("GetQueueUrl"), body: { QueueName: name } });
  return r.QueueUrl;
}

export default {
  // Fixed queue used by routes that need a stable, literal name (detail/edit/send-receive/purge/delete).
  "sqs-queue": async (wire) => {
    await wire("POST", "/", { ...T("CreateQueue"), body: { QueueName: "uic-queue.fifo", Attributes: { FifoQueue: "true", ContentBasedDeduplication: "true" } } }).catch(() => {});
    return "uic-queue.fifo";
  },
  // Liveness for the Queues list: a freshly created, uniquely named queue must show up.
  "live-queue": async (wire, uniq) => {
    await wire("POST", "/", { ...T("CreateQueue"), body: { QueueName: uniq } });
    return uniq;
  },
  // Liveness for the queue detail page: tag the fixed queue with a fresh key and look for
  // it under the Tagging tab — proves the detail page isn't a static snapshot.
  "live-queue-tag": async (wire, uniq) => {
    await wire("POST", "/", { ...T("CreateQueue"), body: { QueueName: "uic-queue.fifo", Attributes: { FifoQueue: "true", ContentBasedDeduplication: "true" } } }).catch(() => {});
    const url = await queueUrl(wire, "uic-queue.fifo");
    await wire("POST", "/", { ...T("TagQueue"), body: { QueueUrl: url, Tags: { [uniq]: "1" } } });
    return uniq;
  },
};
