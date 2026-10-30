import AppServices from "./AppServices.jsx";
import CreateWebApp from "./CreateWebApp.jsx";
import WebAppBlade, { MENU } from "./WebAppBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const site = (p) => ({ text: p.name, href: `#/appservices/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/appservices", component: AppServices },
    { pattern: "/appservices/create", component: CreateWebApp, crumbs: () => [{ text: "Create Web App", href: "#/appservices/create" }] },
    { pattern: "/appservices/:rg/:name", component: WebAppBlade, crumbs: (p) => [site(p)] },
    { pattern: "/appservices/:rg/:name/:panel", component: WebAppBlade, crumbs: (p) => [site(p), { text: label[p.panel] || p.panel, href: `#/appservices/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
