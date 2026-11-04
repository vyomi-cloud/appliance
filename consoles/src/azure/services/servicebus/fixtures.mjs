/* UI-conformance fixtures for Service Bus (ARM control plane for namespaces/queues/topics/
 * authorization rules + the native Service Bus REST data plane for a queue's message
 * backlog). See keyvaults/fixtures.mjs for the same contract. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const NS = "uicsbns";
const nsPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ServiceBus/namespaces/${name}?api-version=2022-10-01-preview`;
const queuePath = (ns, name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ServiceBus/namespaces/${ns}/queues/${name}?api-version=2022-10-01-preview`;
const topicPath = (ns, name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ServiceBus/namespaces/${ns}/topics/${name}?api-version=2022-10-01-preview`;

async function ensureNamespace(wire, name = NS) {
  await wire("PUT", nsPath(name), { svc: null, body: { location: "eastus" } }).catch(() => {});
}
async function ensureQueueEntity(wire, name) {
  await wire("PUT", `/${name}`, { svc: null, headers: { "content-type": "application/atom+xml" } }).catch(() => {});
}

export default {
  "az-namespace": async (wire) => { await ensureNamespace(wire); },

  "live-namespace": async (wire, uniq) => { await wire("PUT", nsPath(uniq), { svc: null, body: { location: "eastus" } }); return uniq; },

  "live-queue": async (wire, uniq) => {
    await ensureNamespace(wire);
    await wire("PUT", queuePath(NS, uniq), { svc: null, body: { properties: { maxSizeInMegabytes: 1024 } } });
    await ensureQueueEntity(wire, uniq);
    return uniq;
  },

  "live-saspolicy": async (wire, uniq) => {
    await ensureNamespace(wire);
    await wire("PUT", `${nsPath(NS).split("?")[0]}/authorizationRules/${uniq}?api-version=2022-10-01-preview`,
      { svc: null, body: { properties: { rights: ["Listen"] } } });
    return uniq;
  },

  "live-topic": async (wire, uniq) => {
    await ensureNamespace(wire);
    await wire("PUT", topicPath(NS, uniq), { svc: null, body: { properties: { maxSizeInMegabytes: 1024 } } });
    return uniq;
  },

  "live-lock": async (wire, uniq) => {
    await ensureNamespace(wire);
    await wire("PUT", `${nsPath(NS).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },

  // A lock write on the shared namespace is a real ARM mutation, so it lands on the
  // unified Microsoft.Insights/eventtypes feed (core/azure_arm_core.py) — the lock NAME
  // becomes the activity entry's "detail", so it is the uniquely-named thing to look for.
  "live-activity": async (wire, uniq) => {
    await ensureNamespace(wire);
    await wire("PUT", `${nsPath(NS).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },
};
