import Subscriptions from "./Subscriptions.jsx";
import CreateSubscription from "./CreateSubscription.jsx";
import SubscriptionBlade, { MENU } from "./SubscriptionBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const sub = (id) => ({ text: id, href: `#/subscriptions/${encodeURIComponent(id)}` });

export default {
  routes: [
    { pattern: "/subscriptions", component: Subscriptions },
    { pattern: "/subscriptions/create", component: CreateSubscription, crumbs: () => [{ text: "Create a subscription", href: "#/subscriptions/create" }] },
    { pattern: "/subscriptions/:id", component: SubscriptionBlade, crumbs: (p) => [sub(p.id)] },
    { pattern: "/subscriptions/:id/:panel", component: SubscriptionBlade, crumbs: (p) => [sub(p.id), { text: label[p.panel] || p.panel, href: `#/subscriptions/${p.id}/${p.panel}` }] },
  ],
};
