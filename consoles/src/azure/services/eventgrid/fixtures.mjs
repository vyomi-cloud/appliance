/* UI-conformance fixtures for Event Grid (native ARM wire — svc: null, no AWS signature).
 * See aws/s3/fixtures.mjs for the contract. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "cloudlearn-rg";
const topicPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${name}?api-version=2024-06-01-preview`;
const esPath = (topic, name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${topic}/providers/Microsoft.EventGrid/eventSubscriptions/${name}?api-version=2022-06-15`;
const lockPath = (topic, name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${topic}/providers/Microsoft.Authorization/locks/${name}?api-version=2016-09-01`;
// Sibling resource types (Namespaces, System topics, Domains, Partner events) — same generic
// ARM catalog CRUD as topics, just a different (namespace, type).
const siblingPath = (type, name, apiVersion) =>
  `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.EventGrid/${type}/${name}?api-version=${apiVersion}`;

async function ensureTopic(wire, name) {
  await wire("PUT", topicPath(name), { svc: null, body: { location: "eastus" } }).catch(() => {});
}

function liveSibling(type, apiVersion) {
  return async (wire, uniq) => { await wire("PUT", siblingPath(type, uniq, apiVersion), { svc: null, body: { location: "eastus" } }); return uniq; };
}

export default {
  // Fixed topic used by routes that need a stable, literal name (detail/subscriptions/tags).
  "az-eventgrid-topic": async (wire) => { await ensureTopic(wire, "uic-eg-topic"); return "uic-eg-topic"; },
  // Liveness for the Topics list: a freshly created, uniquely named topic must show up.
  "live-topic": async (wire, uniq) => { await wire("PUT", topicPath(uniq), { svc: null, body: { location: "eastus" } }); return uniq; },
  // Liveness for the topic overview + Event Subscriptions list + Activity log (every mutating
  // ARM dispatch records a cloudsim event, so creating a uniquely named subscription is enough
  // to make the topic's Activity log show that name too).
  "live-subscription": async (wire, uniq) => {
    await ensureTopic(wire, "uic-eg-topic");
    await wire("PUT", esPath("uic-eg-topic", uniq), {
      svc: null,
      body: { properties: { destination: { endpointType: "WebHook", properties: { endpointUrl: "https://example.com/hook" } } } },
    });
    return uniq;
  },
  // Liveness for the Locks list on the fixed topic: a freshly created, uniquely named lock.
  "live-lock": async (wire, uniq) => {
    await ensureTopic(wire, "uic-eg-topic");
    await wire("PUT", lockPath("uic-eg-topic", uniq), { svc: null, body: { properties: { level: "CanNotDelete", notes: "demo" } } });
    return uniq;
  },
  // Liveness for the sibling resource-type lists.
  "live-namespace": liveSibling("namespaces", "2023-12-15-preview"),
  "live-systemtopic": liveSibling("systemTopics", "2022-06-15"),
  "live-domain": liveSibling("domains", "2024-06-01-preview"),
  "live-partnerconfiguration": liveSibling("partnerConfigurations", "2022-06-15"),
  "live-partnertopic": liveSibling("partnerTopics", "2022-06-15"),
  "live-partnerregistration": liveSibling("partnerRegistrations", "2022-06-15"),
  "live-partnernamespace": liveSibling("partnerNamespaces", "2022-06-15"),
};
