import Topics from "./Topics.jsx";
import CreateTopic from "./CreateTopic.jsx";
import TopicBlade, { MENU } from "./TopicBlade.jsx";
import CreateEventSubscription from "./CreateEventSubscription.jsx";
import SimpleList from "./SimpleList.jsx";
import { Overview } from "./Hub.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const topicCrumb = (p) => ({ text: p.name, href: `#/eventgrid/topics/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });
const topicsCrumb = { text: "Event Grid Topics", href: "#/eventgrid/topics" };
const simple = (typeKey, title, resourceLabel, defaultName) => () =>
  <SimpleList typeKey={typeKey} title={title} resourceLabel={resourceLabel} defaultName={defaultName} closeHref="#/eventgrid" />;

export default {
  routes: [
    { pattern: "/eventgrid", component: Overview },
    { pattern: "/eventgrid/namespaces", component: simple("namespaces", "Event Grid Namespaces", "namespace", "egns-cloudlearn"),
      crumbs: () => [{ text: "Event Grid Namespaces", href: "#/eventgrid/namespaces" }] },
    { pattern: "/eventgrid/systemtopics", component: simple("systemTopics", "System topics", "system topic", "egst-cloudlearn"),
      crumbs: () => [{ text: "System topics", href: "#/eventgrid/systemtopics" }] },
    { pattern: "/eventgrid/domains", component: simple("domains", "Domains", "domain", "egdomain-cloudlearn"),
      crumbs: () => [{ text: "Domains", href: "#/eventgrid/domains" }] },
    { pattern: "/eventgrid/partnerconfigurations", component: simple("partnerConfigurations", "Partner configurations", "partner configuration", "default"),
      crumbs: () => [{ text: "Partner configurations", href: "#/eventgrid/partnerconfigurations" }] },
    { pattern: "/eventgrid/partnertopics", component: simple("partnerTopics", "Partner topics", "partner topic", "egpt-cloudlearn"),
      crumbs: () => [{ text: "Partner topics", href: "#/eventgrid/partnertopics" }] },
    { pattern: "/eventgrid/partnerregistrations", component: simple("partnerRegistrations", "Partner registrations", "partner registration", "egpr-cloudlearn"),
      crumbs: () => [{ text: "Partner registrations", href: "#/eventgrid/partnerregistrations" }] },
    { pattern: "/eventgrid/partnernamespaces", component: simple("partnerNamespaces", "Partner namespaces", "partner namespace", "egpn-cloudlearn"),
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
