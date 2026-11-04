import { Managers, ManagerBlade, MENU } from "./NetworkManagers.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const mgr = (p) => ({ text: p.name, href: `#/networkmanagers/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/networkmanagers", component: Managers },
    { pattern: "/networkmanagers/:rg/:name", component: ManagerBlade, crumbs: (p) => [mgr(p)] },
    { pattern: "/networkmanagers/:rg/:name/:panel", component: ManagerBlade, crumbs: (p) => [mgr(p), { text: label[p.panel] || p.panel, href: `#/networkmanagers/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
