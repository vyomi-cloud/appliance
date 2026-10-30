/* UI-conformance fixtures for Pub/Sub (native REST v1, no SigV4 — svc: null). */
const PROJECT = "vyomi-project";   // consoles/src/gcp/project.js DEFAULT_PROJECT
const topicPath = (id) => `/v1/projects/${PROJECT}/topics/${id}`;
const subPath = (id) => `/v1/projects/${PROJECT}/subscriptions/${id}`;
const snapPath = (id) => `/v1/projects/${PROJECT}/snapshots/${id}`;
const topicName = (id) => `projects/${PROJECT}/topics/${id}`;
const subName = (id) => `projects/${PROJECT}/subscriptions/${id}`;

export default {
  "ps-topic": async (wire) => { await wire("PUT", topicPath("uic-topic"), { svc: null, body: {} }).catch(() => {}); return "uic-topic"; },
  "ps-subscription": async (wire) => {
    await wire("PUT", topicPath("uic-topic"), { svc: null, body: {} }).catch(() => {});
    await wire("PUT", subPath("uic-sub"), { svc: null, body: { topic: topicName("uic-topic") } }).catch(() => {});
    return "uic-sub";
  },
  "ps-snapshot": async (wire) => {
    await wire("PUT", topicPath("uic-topic"), { svc: null, body: {} }).catch(() => {});
    await wire("PUT", subPath("uic-sub"), { svc: null, body: { topic: topicName("uic-topic") } }).catch(() => {});
    await wire("PUT", snapPath("uic-snap"), { svc: null, body: { subscription: subName("uic-sub") } }).catch(() => {});
    return "uic-snap";
  },
  "ps-schema": async (wire) => {
    await wire("POST", `/v1/projects/${PROJECT}/schemas?schemaId=uic-schema`, { svc: null, body: { type: "AVRO", definition: "{}" } }).catch(() => {});
    return "uic-schema";
  },
  "live-topic": async (wire, uniq) => { await wire("PUT", topicPath(uniq), { svc: null, body: {} }); return uniq; },
  "live-subscription": async (wire, uniq) => {
    await wire("PUT", topicPath("uic-topic"), { svc: null, body: {} }).catch(() => {});
    await wire("PUT", subPath(uniq), { svc: null, body: { topic: topicName("uic-topic") } });
    return uniq;
  },
  // topic-details shows this page's subscriptions in its default "Subscriptions" tab.
  "live-topic-detail": async (wire, uniq) => {
    await wire("PUT", topicPath("uic-topic"), { svc: null, body: {} }).catch(() => {});
    await wire("PUT", subPath(uniq), { svc: null, body: { topic: topicName("uic-topic") } });
    return uniq;
  },
  // subscription-details shows this subscription's snapshots in its "Snapshots" tab.
  "live-subscription-detail": async (wire, uniq) => {
    await wire("PUT", topicPath("uic-topic"), { svc: null, body: {} }).catch(() => {});
    await wire("PUT", subPath("uic-sub"), { svc: null, body: { topic: topicName("uic-topic") } }).catch(() => {});
    await wire("PUT", snapPath(uniq), { svc: null, body: { subscription: subName("uic-sub") } });
    return uniq;
  },
  "live-snapshot": async (wire, uniq) => {
    await wire("PUT", topicPath("uic-topic"), { svc: null, body: {} }).catch(() => {});
    await wire("PUT", subPath(uniq), { svc: null, body: { topic: topicName("uic-topic") } }).catch(() => {});
    await wire("PUT", snapPath(uniq), { svc: null, body: { subscription: subName(uniq) } });
    return uniq;
  },
  "live-schema": async (wire, uniq) => {
    await wire("POST", `/v1/projects/${PROJECT}/schemas?schemaId=${uniq}`, { svc: null, body: { type: "AVRO", definition: "{}" } });
    return uniq;
  },
};
