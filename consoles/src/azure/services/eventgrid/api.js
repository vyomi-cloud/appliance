/* Event Grid over native ARM.
 *   Topics:              /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.EventGrid/topics/{name}
 *   Event subscriptions: {topic resource id}/providers/Microsoft.EventGrid/eventSubscriptions/{name}
 *     — a real ARM extension resource scoped to the topic (what azure-mgmt-eventgrid / az CLI send),
 *     owned on the backend by core/azure_eventgrid_core.py. */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.EventGrid", "topics", "2024-06-01-preview");
export const ES_API_VERSION = "2022-06-15";

const shape = (t) => ({ ...t, resourceGroup: parseId(t.id).resourceGroup });

export const listTopics = async () => (await ARM.list()).map(shape);
export const getTopic = async (rg, name) => shape(await ARM.get(rg, name));
export const createTopic = (rg, name, body) => ARM.put(rg, name, body);
export const updateTopic = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteTopic = (rg, name) => ARM.remove(rg, name);
export const listKeys = async (rg, name) => (await ARM.action(rg, name, "listKeys")).keys || [];
export const regenerateKey = (rg, name, keyName) => ARM.action(rg, name, "regenerateKey", { keyName });

// ── Event subscriptions (scoped to a topic) ─────────────────────────────────────────────
const esPath = (rg, topic, name) =>
  `${ARM.path(rg, topic)}/providers/Microsoft.EventGrid/eventSubscriptions${name ? `/${encodeURIComponent(name)}` : ""}`;
const esQuery = { "api-version": ES_API_VERSION };

export const listEventSubscriptions = async (rg, topic) => (await restJson("GET", esPath(rg, topic), { query: esQuery })).value || [];
export const getEventSubscription = (rg, topic, name) => restJson("GET", esPath(rg, topic, name), { query: esQuery });
export const createEventSubscription = (rg, topic, name, body) => restJson("PUT", esPath(rg, topic, name), { query: esQuery, body });
export const deleteEventSubscription = (rg, topic, name) => restJson("DELETE", esPath(rg, topic, name), { query: esQuery });

// ── Create-form model → ARM body ────────────────────────────────────────────────────────
export const ENDPOINT_TYPES = [
  ["WebHook", "Web Hook"], ["EventHub", "Event Hubs"], ["StorageQueue", "Storage Queues"],
  ["ServiceBusQueue", "Service Bus Queue"], ["ServiceBusTopic", "Service Bus Topic"], ["HybridConnection", "Hybrid Connections"],
  ["AzureFunction", "Azure Function"], ["NamespaceTopic", "Namespace topic"],
];

export function toSubscriptionBody(f) {
  const props = {
    eventDeliverySchema: f.eventSchema === "Cloud Event Schema v1.0" ? "CloudEventSchemaV1_0" : "EventGridSchema",
    destination: { endpointType: f.endpointType, properties: { endpointUrl: f.endpoint } },
    filter: {
      includedEventTypes: f.eventTypes ? f.eventTypes.split(",").map((s) => s.trim()).filter(Boolean) : undefined,
      subjectBeginsWith: f.subjectFilter ? f.subjectBeginsWith : undefined,
      subjectEndsWith: f.subjectFilter ? f.subjectEndsWith : undefined,
      isSubjectCaseSensitive: f.subjectFilter ? f.caseSensitive : undefined,
      advancedFilters: f.advancedFilters.filter((a) => a.key).map((a) => ({ key: a.key, operatorType: a.operator, value: a.value })),
    },
    retryPolicy: { maxDeliveryAttempts: Number(f.maxDeliveryAttempts) || 30, eventTimeToLiveInMinutes: Number(f.eventTtl) || 1440 },
    deadLetterDestination: f.deadLetter ? { endpointType: "StorageBlob", properties: {} } : undefined,
    expirationTimeUtc: f.expiration && f.expirationDate ? new Date(f.expirationDate).toISOString() : undefined,
  };
  if (f.deliveryHeaders.filter((h) => h.name).length) {
    props.destination.properties.deliveryAttributeMappings = f.deliveryHeaders.filter((h) => h.name).map((h) => ({
      name: h.name, type: h.secret ? "Static" : "Static", properties: { value: h.value, isSecret: !!h.secret },
    }));
  }
  return { properties: props };
}
