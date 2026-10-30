/* UI-conformance fixtures for Event Grid (native ARM wire — svc: null, no AWS signature).
 * See aws/s3/fixtures.mjs for the contract. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "cloudlearn-rg";
const topicPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${name}?api-version=2024-06-01-preview`;
const esPath = (topic, name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${topic}/providers/Microsoft.EventGrid/eventSubscriptions/${name}?api-version=2022-06-15`;

async function ensureTopic(wire, name) {
  await wire("PUT", topicPath(name), { svc: null, body: { location: "eastus" } }).catch(() => {});
}

export default {
  // Fixed topic used by routes that need a stable, literal name (detail/subscriptions/tags).
  "az-eventgrid-topic": async (wire) => { await ensureTopic(wire, "uic-eg-topic"); return "uic-eg-topic"; },
  // Liveness for the Topics list: a freshly created, uniquely named topic must show up.
  "live-topic": async (wire, uniq) => { await wire("PUT", topicPath(uniq), { svc: null, body: { location: "eastus" } }); return uniq; },
  // Liveness for the topic overview + Event Subscriptions list: a freshly created, uniquely
  // named event subscription on the fixed topic must show up.
  "live-subscription": async (wire, uniq) => {
    await ensureTopic(wire, "uic-eg-topic");
    await wire("PUT", esPath("uic-eg-topic", uniq), {
      svc: null,
      body: { properties: { destination: { endpointType: "WebHook", properties: { endpointUrl: "https://example.com/hook" } } } },
    });
    return uniq;
  },
};
