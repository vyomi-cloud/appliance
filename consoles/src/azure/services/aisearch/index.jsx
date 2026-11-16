import SearchServices from "./SearchServices.jsx";
import SearchServiceBlade, { MENU } from "./SearchServiceBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const svc = (p) => ({ text: p.name, href: `#/aisearch/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/aisearch", component: SearchServices },
    { pattern: "/aisearch/:rg/:name", component: SearchServiceBlade, crumbs: (p) => [svc(p)] },
    { pattern: "/aisearch/:rg/:name/:panel", component: SearchServiceBlade, crumbs: (p) => [svc(p), { text: label[p.panel] || p.panel, href: `#/aisearch/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
