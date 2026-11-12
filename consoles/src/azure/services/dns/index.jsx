import Zones from "./Zones.jsx";
import CreateZone from "./CreateZone.jsx";
import ZoneBlade, { MENU } from "./ZoneBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const zone = (p) => ({ text: p.name, href: `#/dns/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/dns", component: Zones },
    { pattern: "/dns/create", component: CreateZone, crumbs: () => [{ text: "Create DNS zone", href: "#/dns/create" }] },
    { pattern: "/dns/:rg/:name", component: ZoneBlade, crumbs: (p) => [zone(p)] },
    { pattern: "/dns/:rg/:name/:panel", component: ZoneBlade, crumbs: (p) => [zone(p), { text: label[p.panel] || p.panel, href: `#/dns/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
