import Topics from "./Topics.jsx";
import CreateTopic from "./CreateTopic.jsx";
import TopicBlade, { MENU } from "./TopicBlade.jsx";
import CreateEventSubscription from "./CreateEventSubscription.jsx";
import { Overview, HonestList } from "./Hub.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const topicCrumb = (p) => ({ text: p.name, href: `#/eventgrid/topics/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });
const topicsCrumb = { text: "Event Grid Topics", href: "#/eventgrid/topics" };
const honest = (title, capId) => () => <HonestList title={title} capId={capId} />;

export default {
  routes: [
    { pattern: "/eventgrid", component: Overview },
    { pattern: "/eventgrid/namespaces", component: honest("Event Grid Namespaces", "azure.eventgrid.hub.namespaces"),
      crumbs: () => [{ text: "Event Grid Namespaces", href: "#/eventgrid/namespaces" }] },
    { pattern: "/eventgrid/systemtopics", component: honest("System topics", "azure.eventgrid.hub.systemtopics"),
      crumbs: () => [{ text: "System topics", href: "#/eventgrid/systemtopics" }] },
    { pattern: "/eventgrid/domains", component: honest("Domains", "azure.eventgrid.hub.domains"),
      crumbs: () => [{ text: "Domains", href: "#/eventgrid/domains" }] },
    { pattern: "/eventgrid/partnerconfigurations", component: honest("Partner configurations", "azure.eventgrid.hub.partnerevents"),
      crumbs: () => [{ text: "Partner configurations", href: "#/eventgrid/partnerconfigurations" }] },
    { pattern: "/eventgrid/partnertopics", component: honest("Partner topics", "azure.eventgrid.hub.partnerevents"),
      crumbs: () => [{ text: "Partner topics", href: "#/eventgrid/partnertopics" }] },
    { pattern: "/eventgrid/partnerregistrations", component: honest("Partner registrations", "azure.eventgrid.hub.partnerevents"),
      crumbs: () => [{ text: "Partner registrations", href: "#/eventgrid/partnerregistrations" }] },
    { pattern: "/eventgrid/partnernamespaces", component: honest("Partner namespaces", "azure.eventgrid.hub.partnerevents"),
      crumbs: () => [{ text: "Partner namespaces", href: "#/eventgrid/partnernamespaces" }] },
    { pattern: "/eventgrid/topics", component: Topics, crumbs: () => [topicsCrumb] },
    { pattern: "/eventgrid/topics/create", component: CreateTopic, crumbs: () => [topicsCrumb, { text: "Create Topic", href: "#/eventgrid/topics/create" }] },
    { pattern: "/eventgrid/topics/:rg/:name/subscriptions/create", component: CreateEventSubscription,
      crumbs: (p) => [topicsCrumb, topicCrumb(p), { text: "Create Event Subscription", href: `#/eventgrid/topics/${p.rg}/${p.name}/subscriptions/create` }] },
    { pattern: "/eventgrid/topics/:rg/:name", component: TopicBlade, crumbs: (p) => [topicsCrumb, topicCrumb(p)] },
    { pattern: "/eventgrid/topics/:rg/:name/:panel", component: TopicBlade,
      crumbs: (p) => [topicsCrumb, topicCrumb(p), { text: label[p.panel] || p.panel, href: `#/eventgrid/topics/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
