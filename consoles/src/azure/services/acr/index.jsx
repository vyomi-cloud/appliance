import Registries from "./Registries.jsx";
import CreateRegistry from "./CreateRegistry.jsx";
import RegistryBlade, { MENU } from "./RegistryBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const registry = (p) => ({ text: p.name, href: `#/acr/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/acr", component: Registries },
    { pattern: "/acr/create", component: CreateRegistry, crumbs: () => [{ text: "Create container registry", href: "#/acr/create" }] },
    { pattern: "/acr/:rg/:name", component: RegistryBlade, crumbs: (p) => [registry(p)] },
    { pattern: "/acr/:rg/:name/:panel", component: RegistryBlade, crumbs: (p) => [registry(p), { text: label[p.panel] || p.panel, href: `#/acr/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
