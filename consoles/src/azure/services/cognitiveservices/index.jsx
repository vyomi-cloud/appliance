import CognitiveServicesAccounts from "./CognitiveServicesAccounts.jsx";
import CreateCognitiveServicesAccount from "./CreateCognitiveServicesAccount.jsx";
import ManageDeletedAccounts from "./ManageDeletedAccounts.jsx";
import CognitiveServicesAccountBlade, { MENU } from "./CognitiveServicesAccountBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const account = (p) => ({ text: p.name, href: `#/cognitiveservices/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/cognitiveservices", component: CognitiveServicesAccounts },
    { pattern: "/cognitiveservices/create", component: CreateCognitiveServicesAccount, crumbs: () => [{ text: "Create an Azure AI services resource", href: "#/cognitiveservices/create" }] },
    { pattern: "/cognitiveservices/deleted", component: ManageDeletedAccounts, crumbs: () => [{ text: "Manage deleted accounts", href: "#/cognitiveservices/deleted" }] },
    { pattern: "/cognitiveservices/:rg/:name", component: CognitiveServicesAccountBlade, crumbs: (p) => [account(p)] },
    { pattern: "/cognitiveservices/:rg/:name/:panel", component: CognitiveServicesAccountBlade, crumbs: (p) => [account(p), { text: label[p.panel] || p.panel, href: `#/cognitiveservices/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
