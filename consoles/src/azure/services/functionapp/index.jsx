import FunctionApps from "./FunctionApps.jsx";
import CreateFunctionAppHosting from "./CreateFunctionAppHosting.jsx";
import CreateFunctionApp from "./CreateFunctionApp.jsx";
import CreateFunction from "./CreateFunction.jsx";
import FunctionDetail from "./FunctionDetail.jsx";
import FunctionAppBlade, { MENU } from "./FunctionAppBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const app = (p) => ({ text: p.name, href: `#/functionapp/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/functionapp", component: FunctionApps },
    { pattern: "/functionapp/create", component: CreateFunctionAppHosting, crumbs: () => [{ text: "Create Function App", href: "#/functionapp/create" }] },
    { pattern: "/functionapp/create/:hosting", component: CreateFunctionApp, crumbs: () => [{ text: "Create Function App", href: "#/functionapp/create" }, { text: "Create Function App (Flex Consumption)" }] },
    { pattern: "/functionapp/:rg/:name", component: FunctionAppBlade, crumbs: (p) => [app(p)] },
    { pattern: "/functionapp/:rg/:name/:panel", component: FunctionAppBlade, crumbs: (p) => [app(p), { text: label[p.panel] || p.panel }] },
    { pattern: "/functionapp/:rg/:name/functions/create", component: CreateFunction, crumbs: (p) => [app(p), { text: "Create function" }] },
    { pattern: "/functionapp/:rg/:name/functions/:fn", component: FunctionDetail, crumbs: (p) => [app(p), { text: p.fn }] },
  ],
};
