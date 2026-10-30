import StorageAccounts from "./StorageAccounts.jsx";
import CreateStorageAccount from "./CreateStorageAccount.jsx";
import StorageAccountBlade, { MENU } from "./StorageAccountBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const acct = (p) => ({ text: p.name, href: `#/storage/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/storage", component: StorageAccounts },
    { pattern: "/storage/create", component: CreateStorageAccount, crumbs: () => [{ text: "Create a storage account", href: "#/storage/create" }] },
    { pattern: "/storage/:rg/:name", component: StorageAccountBlade, crumbs: (p) => [acct(p)] },
    { pattern: "/storage/:rg/:name/:panel", component: StorageAccountBlade, crumbs: (p) => [acct(p), { text: label[p.panel] || p.panel, href: `#/storage/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
