import NetworkSecurityGroups from "./NetworkSecurityGroups.jsx";
import CreateNetworkSecurityGroup from "./CreateNetworkSecurityGroup.jsx";
import NsgBlade, { MENU } from "./NsgBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const nsg = (p) => ({ text: p.name, href: `#/nsgs/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/nsgs", component: NetworkSecurityGroups },
    { pattern: "/nsgs/create", component: CreateNetworkSecurityGroup, crumbs: () => [{ text: "Create network security group", href: "#/nsgs/create" }] },
    { pattern: "/nsgs/:rg/:name", component: NsgBlade, crumbs: (p) => [nsg(p)] },
    { pattern: "/nsgs/:rg/:name/:panel", component: NsgBlade, crumbs: (p) => [nsg(p), { text: label[p.panel] || p.panel, href: `#/nsgs/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
