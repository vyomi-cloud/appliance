import ResourceGroups from "./ResourceGroups.jsx";
import CreateResourceGroup from "./CreateResourceGroup.jsx";
import DeleteResourceGroup from "./DeleteResourceGroup.jsx";
import ResourceGroupBlade, { MENU } from "./ResourceGroupBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const rg = (name) => ({ text: name, href: `#/resourcegroups/${encodeURIComponent(name)}` });

export default {
  routes: [
    { pattern: "/resourcegroups", component: ResourceGroups },
    { pattern: "/resourcegroups/create", component: CreateResourceGroup, crumbs: () => [{ text: "Create a resource group", href: "#/resourcegroups/create" }] },
    { pattern: "/resourcegroups/:name", component: ResourceGroupBlade, crumbs: (p) => [rg(p.name)] },
    { pattern: "/resourcegroups/:name/delete", component: DeleteResourceGroup, crumbs: (p) => [rg(p.name), { text: "Delete a resource group", href: `#/resourcegroups/${p.name}/delete` }] },
    { pattern: "/resourcegroups/:name/:panel", component: ResourceGroupBlade, crumbs: (p) => [rg(p.name), { text: label[p.panel] || p.panel, href: `#/resourcegroups/${p.name}/${p.panel}` }] },
  ],
};
