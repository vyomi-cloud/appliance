import Vaults from "./Vaults.jsx";
import VaultBlade, { MENU } from "./VaultBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const vault = (p) => ({ text: p.name, href: `#/recoveryservices/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });
export default {
  routes: [
    { pattern: "/recoveryservices", component: Vaults },
    { pattern: "/recoveryservices/:rg/:name", component: VaultBlade, crumbs: (p) => [vault(p)] },
    { pattern: "/recoveryservices/:rg/:name/:panel", component: VaultBlade, crumbs: (p) => [vault(p), { text: label[p.panel] || p.panel, href: `#/recoveryservices/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
