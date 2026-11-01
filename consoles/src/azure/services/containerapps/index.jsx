import ContainerAppsEnvironments from "./ContainerAppsEnvironments.jsx";
import CreateEnvironment from "./CreateEnvironment.jsx";
import EnvironmentBlade, { MENU as ENV_MENU } from "./EnvironmentBlade.jsx";
import ContainerApps from "./ContainerApps.jsx";
import CreateContainerApp from "./CreateContainerApp.jsx";
import ContainerAppBlade, { MENU as APP_MENU } from "./ContainerAppBlade.jsx";
import ContainerAppsJobs from "./ContainerAppsJobs.jsx";
import CreateJob from "./CreateJob.jsx";
import JobBlade, { MENU as JOB_MENU } from "./JobBlade.jsx";

const labelOf = (menu) => Object.fromEntries(menu.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const envLabel = labelOf(ENV_MENU);
const appLabel = labelOf(APP_MENU);
const jobLabel = labelOf(JOB_MENU);

const env = (p) => ({ text: p.name, href: `#/containerapps/environments/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });
const app = (p) => ({ text: p.name, href: `#/containerapps/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });
const job = (p) => ({ text: p.name, href: `#/containerapps/jobs/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/containerapps", component: ContainerApps },
    { pattern: "/containerapps/create", component: CreateContainerApp, crumbs: () => [{ text: "Create Container App", href: "#/containerapps/create" }] },
    { pattern: "/containerapps/environments", component: ContainerAppsEnvironments, crumbs: () => [{ text: "Container Apps Environments", href: "#/containerapps/environments" }] },
    { pattern: "/containerapps/environments/create", component: CreateEnvironment, crumbs: () => [{ text: "Container Apps Environments", href: "#/containerapps/environments" }, { text: "Create", href: "#/containerapps/environments/create" }] },
    { pattern: "/containerapps/environments/:rg/:name", component: EnvironmentBlade, crumbs: (p) => [{ text: "Container Apps Environments", href: "#/containerapps/environments" }, env(p)] },
    { pattern: "/containerapps/environments/:rg/:name/:panel", component: EnvironmentBlade, crumbs: (p) => [{ text: "Container Apps Environments", href: "#/containerapps/environments" }, env(p), { text: envLabel[p.panel] || p.panel, href: `#/containerapps/environments/${p.rg}/${p.name}/${p.panel}` }] },
    { pattern: "/containerapps/jobs", component: ContainerAppsJobs, crumbs: () => [{ text: "Container Apps Jobs", href: "#/containerapps/jobs" }] },
    { pattern: "/containerapps/jobs/create", component: CreateJob, crumbs: () => [{ text: "Container Apps Jobs", href: "#/containerapps/jobs" }, { text: "Create", href: "#/containerapps/jobs/create" }] },
    { pattern: "/containerapps/jobs/:rg/:name", component: JobBlade, crumbs: (p) => [{ text: "Container Apps Jobs", href: "#/containerapps/jobs" }, job(p)] },
    { pattern: "/containerapps/jobs/:rg/:name/:panel", component: JobBlade, crumbs: (p) => [{ text: "Container Apps Jobs", href: "#/containerapps/jobs" }, job(p), { text: jobLabel[p.panel] || p.panel, href: `#/containerapps/jobs/${p.rg}/${p.name}/${p.panel}` }] },
    { pattern: "/containerapps/:rg/:name", component: ContainerAppBlade, crumbs: (p) => [app(p)] },
    { pattern: "/containerapps/:rg/:name/:panel", component: ContainerAppBlade, crumbs: (p) => [app(p), { text: appLabel[p.panel] || p.panel, href: `#/containerapps/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
