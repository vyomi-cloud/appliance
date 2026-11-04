import ServiceBusNamespaces from "./ServiceBusNamespaces.jsx";
import CreateNamespace from "./CreateNamespace.jsx";
import NamespaceBlade, { MENU } from "./NamespaceBlade.jsx";
import QueueBlade from "./QueueBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const namespace = (p) => ({ text: p.name, href: `#/servicebus/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });
const queueCrumb = (p) => ({ text: p.queue, href: `#/servicebus/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}/queues/${encodeURIComponent(p.queue)}` });

export default {
  routes: [
    { pattern: "/servicebus", component: ServiceBusNamespaces },
    { pattern: "/servicebus/create", component: CreateNamespace, crumbs: () => [{ text: "Create namespace", href: "#/servicebus/create" }] },
    { pattern: "/servicebus/:rg/:name", component: NamespaceBlade, crumbs: (p) => [namespace(p)] },
    { pattern: "/servicebus/:rg/:name/:panel", component: NamespaceBlade, crumbs: (p) => [namespace(p), { text: label[p.panel] || p.panel, href: `#/servicebus/${p.rg}/${p.name}/${p.panel}` }] },
    { pattern: "/servicebus/:rg/:name/queues/:queue", component: QueueBlade, crumbs: (p) => [namespace(p), { text: "Queues", href: `#/servicebus/${p.rg}/${p.name}/queues` }, queueCrumb(p)] },
    { pattern: "/servicebus/:rg/:name/queues/:queue/:panel", component: QueueBlade, crumbs: (p) => [namespace(p), { text: "Queues", href: `#/servicebus/${p.rg}/${p.name}/queues` }, queueCrumb(p), { text: "Service Bus Explorer", href: `#/servicebus/${p.rg}/${p.name}/queues/${p.queue}/explorer` }] },
  ],
};
