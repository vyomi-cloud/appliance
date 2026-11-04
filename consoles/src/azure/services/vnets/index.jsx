import VirtualNetworks from "./VirtualNetworks.jsx";
import CreateVirtualNetwork from "./CreateVirtualNetwork.jsx";
import VnetBlade, { MENU } from "./VnetBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const vnet = (p) => ({ text: p.name, href: `#/vnets/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/vnets", component: VirtualNetworks },
    { pattern: "/vnets/create", component: CreateVirtualNetwork, crumbs: () => [{ text: "Create virtual network", href: "#/vnets/create" }] },
    { pattern: "/vnets/:rg/:name", component: VnetBlade, crumbs: (p) => [vnet(p)] },
    { pattern: "/vnets/:rg/:name/:panel", component: VnetBlade, crumbs: (p) => [vnet(p), { text: label[p.panel] || p.panel, href: `#/vnets/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
