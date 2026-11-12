import Jobs from "./Jobs.jsx";
import JobBlade, { MENU } from "./JobBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const job = (p) => ({ text: p.name, href: `#/streamanalytics/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/streamanalytics", component: Jobs },
    { pattern: "/streamanalytics/:rg/:name", component: JobBlade, crumbs: (p) => [job(p)] },
    { pattern: "/streamanalytics/:rg/:name/:panel", component: JobBlade, crumbs: (p) => [job(p), { text: label[p.panel] || p.panel, href: `#/streamanalytics/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
