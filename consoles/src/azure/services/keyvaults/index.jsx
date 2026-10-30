import KeyVaults from "./KeyVaults.jsx";
import CreateKeyVault from "./CreateKeyVault.jsx";
import KeyVaultBlade, { MENU } from "./KeyVaultBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const vault = (p) => ({ text: p.name, href: `#/keyvaults/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/keyvaults", component: KeyVaults },
    { pattern: "/keyvaults/create", component: CreateKeyVault, crumbs: () => [{ text: "Create a key vault", href: "#/keyvaults/create" }] },
    { pattern: "/keyvaults/:rg/:name", component: KeyVaultBlade, crumbs: (p) => [vault(p)] },
    { pattern: "/keyvaults/:rg/:name/:panel", component: KeyVaultBlade, crumbs: (p) => [vault(p), { text: label[p.panel] || p.panel, href: `#/keyvaults/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
