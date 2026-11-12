import SqlDatabases from "./SqlDatabases.jsx";
import CreateSqlDatabase from "./CreateSqlDatabase.jsx";
import SqlDatabaseBlade, { MENU as DB_MENU } from "./SqlDatabaseBlade.jsx";
import SqlServerBlade, { MENU as SERVER_MENU } from "./SqlServerBlade.jsx";

const dbLabel = Object.fromEntries(DB_MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const serverLabel = Object.fromEntries(SERVER_MENU.map((i) => [i.id, i.label]));
const db = (p) => ({ text: p.db, href: `#/sql/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.server)}/${encodeURIComponent(p.db)}` });
const server = (p) => ({ text: p.server, href: `#/sql/servers/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.server)}` });

export default {
  routes: [
    { pattern: "/sql", component: SqlDatabases },
    { pattern: "/sql/create", component: CreateSqlDatabase, crumbs: () => [{ text: "Create SQL Database", href: "#/sql/create" }] },
    { pattern: "/sql/servers/:rg/:server", component: SqlServerBlade, crumbs: (p) => [server(p)] },
    { pattern: "/sql/servers/:rg/:server/:panel", component: SqlServerBlade, crumbs: (p) => [server(p), { text: serverLabel[p.panel] || p.panel, href: `#/sql/servers/${p.rg}/${p.server}/${p.panel}` }] },
    { pattern: "/sql/:rg/:server/:db", component: SqlDatabaseBlade, crumbs: (p) => [db(p)] },
    { pattern: "/sql/:rg/:server/:db/:panel", component: SqlDatabaseBlade, crumbs: (p) => [db(p), { text: dbLabel[p.panel] || p.panel, href: `#/sql/${p.rg}/${p.server}/${p.db}/${p.panel}` }] },
  ],
};
