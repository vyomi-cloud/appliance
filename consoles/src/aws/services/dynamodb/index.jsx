import Tables from "./Tables.jsx";
import CreateTable from "./CreateTable.jsx";
import TableDetail from "./TableDetail.jsx";
import ExploreItems from "./ExploreItems.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";

const ns = (title) => () => <NotSimulatedContainer title={title} />;
const NS = [["dashboard", "Dashboard"], ["update-settings", "Update settings"], ["imports", "Imports from S3"], ["integrations", "Integrations"],
  ["reserved-capacity", "Reserved capacity"], ["settings", "Settings"], ["partiql", "PartiQL editor"], ["backups", "Backups"], ["exports", "Exports to S3"],
  ["dax/clusters", "DAX Clusters"], ["dax/subnet-groups", "DAX Subnet groups"], ["dax/parameter-groups", "DAX Parameter groups"], ["dax/events", "DAX Events"]];

export default {
  nav: [
    { type: "link", text: "Dashboard", href: "#/dynamodb/dashboard" },
    { type: "link", text: "Tables", href: "#/dynamodb/tables" },
    { type: "link", text: "Explore items", href: "#/dynamodb/explore" },
    { type: "link", text: "PartiQL editor", href: "#/dynamodb/partiql" },
    { type: "link", text: "Backups", href: "#/dynamodb/backups" },
    { type: "link", text: "Exports to S3", href: "#/dynamodb/exports" },
    { type: "link", text: "Imports from S3", href: "#/dynamodb/imports" },
    { type: "link", text: "Integrations", href: "#/dynamodb/integrations" },
    { type: "link", text: "Reserved capacity", href: "#/dynamodb/reserved-capacity" },
    { type: "link", text: "Settings", href: "#/dynamodb/settings" },
    { type: "section", text: "DAX", items: [
      { type: "link", text: "Clusters", href: "#/dynamodb/dax/clusters" },
      { type: "link", text: "Subnet groups", href: "#/dynamodb/dax/subnet-groups" },
      { type: "link", text: "Parameter groups", href: "#/dynamodb/dax/parameter-groups" },
      { type: "link", text: "Events", href: "#/dynamodb/dax/events" },
    ] },
  ],
  routes: [
    { pattern: "/dynamodb", component: Tables },
    { pattern: "/dynamodb/tables", component: Tables, crumbs: () => [{ text: "Tables", href: "#/dynamodb/tables" }] },
    { pattern: "/dynamodb/explore", component: Tables, crumbs: () => [{ text: "Explore items", href: "#/dynamodb/explore" }] },
    { pattern: "/dynamodb/create-table", component: CreateTable, crumbs: () => [{ text: "Tables", href: "#/dynamodb/tables" }, { text: "Create table", href: "#/dynamodb/create-table" }] },
    { pattern: "/dynamodb/tables/:name", component: TableDetail, crumbs: (p) => [{ text: "Tables", href: "#/dynamodb/tables" }, { text: p.name, href: `#/dynamodb/tables/${p.name}` }] },
    { pattern: "/dynamodb/tables/:name/items", component: ExploreItems, crumbs: (p) => [{ text: "Explore items", href: "#/dynamodb/explore" }, { text: p.name, href: `#/dynamodb/tables/${p.name}/items` }] },
    ...NS.map(([p, t]) => ({ pattern: `/dynamodb/${p}`, component: ns(t), crumbs: () => [{ text: t, href: `#/dynamodb/${p}` }] })),
  ],
};
