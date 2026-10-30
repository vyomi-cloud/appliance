import CosmosAccounts from "./CosmosAccounts.jsx";
import CreateCosmosAccount from "./CreateCosmosAccount.jsx";
import CosmosAccountBlade, { MENU } from "./CosmosAccountBlade.jsx";

const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const acct = (p) => ({ text: p.name, href: `#/cosmos/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/cosmos", component: CosmosAccounts },
    { pattern: "/cosmos/create", component: CreateCosmosAccount, crumbs: () => [{ text: "Create an Azure Cosmos DB account", href: "#/cosmos/create" }] },
    { pattern: "/cosmos/:rg/:name", component: CosmosAccountBlade, crumbs: (p) => [acct(p)] },
    { pattern: "/cosmos/:rg/:name/:panel", component: CosmosAccountBlade, crumbs: (p) => [acct(p), { text: LABEL[p.panel] || p.panel, href: `#/cosmos/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
