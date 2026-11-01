import Stores from "./Stores.jsx";
import CreateStore from "./CreateStore.jsx";
import ConfigStoreBlade, { MENU } from "./ConfigStoreBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const store = (p) => ({ text: p.name, href: `#/appconfiguration/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/appconfiguration", component: Stores },
    { pattern: "/appconfiguration/create", component: CreateStore, crumbs: () => [{ text: "Create a configuration store", href: "#/appconfiguration/create" }] },
    { pattern: "/appconfiguration/:rg/:name", component: ConfigStoreBlade, crumbs: (p) => [store(p)] },
    { pattern: "/appconfiguration/:rg/:name/:panel", component: ConfigStoreBlade, crumbs: (p) => [store(p), { text: label[p.panel] || p.panel, href: `#/appconfiguration/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
