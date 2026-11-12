import Workspaces from "./Workspaces.jsx";
import CreateWorkspace from "./CreateWorkspace.jsx";
import WorkspaceBlade, { MENU } from "./WorkspaceBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const workspace = (p) => ({ text: p.name, href: `#/loganalytics/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/loganalytics", component: Workspaces },
    { pattern: "/loganalytics/create", component: CreateWorkspace, crumbs: () => [{ text: "Create Log Analytics workspace", href: "#/loganalytics/create" }] },
    { pattern: "/loganalytics/:rg/:name", component: WorkspaceBlade, crumbs: (p) => [workspace(p)] },
    { pattern: "/loganalytics/:rg/:name/:panel", component: WorkspaceBlade, crumbs: (p) => [workspace(p), { text: label[p.panel] || p.panel, href: `#/loganalytics/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
