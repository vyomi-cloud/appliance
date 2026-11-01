import Tables from "./Tables.jsx";
import CreateTable from "./CreateTable.jsx";
import TableDetail from "./TableDetail.jsx";
import ExploreItems from "./ExploreItems.jsx";
import Dashboard from "./Dashboard.jsx";
import PartiqlEditor from "./PartiqlEditor.jsx";
import Backups from "./Backups.jsx";
import Settings from "./Settings.jsx";
import EditLayoutSettings from "./EditLayoutSettings.jsx";
import EditExploreItemsSettings from "./EditExploreItemsSettings.jsx";
import Exports from "./Exports.jsx";
import ExportToS3 from "./ExportToS3.jsx";
import Imports from "./Imports.jsx";
import ImportFromS3 from "./ImportFromS3.jsx";
import DaxClusters from "./DaxClusters.jsx";
import DaxSubnetGroups from "./DaxSubnetGroups.jsx";
import DaxParameterGroups from "./DaxParameterGroups.jsx";
import DaxEvents from "./DaxEvents.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import { getLayoutSettings } from "./prefs.js";

const ns = (title) => () => <NotSimulatedContainer title={title} />;
const NS = [["update-settings", "Update settings"], ["integrations", "Integrations"], ["reserved-capacity", "Reserved capacity"]];

// The bare "/dynamodb" entry route honours the "Default entry page" console preference
// (Dashboard / Tables / Explore items) — Tables.jsx renders both the Tables and Explore
// items nav destinations today (same list, different crumb), same as the native console.
function Entry() {
  return getLayoutSettings().defaultEntryPage === "Dashboard" ? <Dashboard /> : <Tables />;
}

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
    { pattern: "/dynamodb", component: Entry },
    { pattern: "/dynamodb/dashboard", component: Dashboard, crumbs: () => [{ text: "Dashboard", href: "#/dynamodb/dashboard" }] },
    { pattern: "/dynamodb/tables", component: Tables, crumbs: () => [{ text: "Tables", href: "#/dynamodb/tables" }] },
    { pattern: "/dynamodb/explore", component: Tables, crumbs: () => [{ text: "Explore items", href: "#/dynamodb/explore" }] },
    { pattern: "/dynamodb/create-table", component: CreateTable, crumbs: () => [{ text: "Tables", href: "#/dynamodb/tables" }, { text: "Create table", href: "#/dynamodb/create-table" }] },
    { pattern: "/dynamodb/tables/:name", component: TableDetail, crumbs: (p) => [{ text: "Tables", href: "#/dynamodb/tables" }, { text: p.name, href: `#/dynamodb/tables/${p.name}` }] },
    { pattern: "/dynamodb/tables/:name/items", component: ExploreItems, crumbs: (p) => [{ text: "Explore items", href: "#/dynamodb/explore" }, { text: p.name, href: `#/dynamodb/tables/${p.name}/items` }] },
    { pattern: "/dynamodb/partiql", component: PartiqlEditor, crumbs: () => [{ text: "PartiQL editor", href: "#/dynamodb/partiql" }] },
    { pattern: "/dynamodb/backups", component: Backups, crumbs: () => [{ text: "Backups", href: "#/dynamodb/backups" }] },
    { pattern: "/dynamodb/settings", component: Settings, crumbs: () => [{ text: "Settings", href: "#/dynamodb/settings" }] },
    { pattern: "/dynamodb/settings/layout", component: EditLayoutSettings, crumbs: () => [{ text: "Settings", href: "#/dynamodb/settings" }, { text: "Edit layout and navigation settings", href: "#/dynamodb/settings/layout" }] },
    { pattern: "/dynamodb/settings/explore-items", component: EditExploreItemsSettings, crumbs: () => [{ text: "Settings", href: "#/dynamodb/settings" }, { text: "Edit explore items settings", href: "#/dynamodb/settings/explore-items" }] },
    { pattern: "/dynamodb/exports", component: Exports, crumbs: () => [{ text: "Exports to S3", href: "#/dynamodb/exports" }] },
    { pattern: "/dynamodb/exports/create", component: ExportToS3, crumbs: () => [{ text: "Exports to S3", href: "#/dynamodb/exports" }, { text: "Export table to Amazon S3", href: "#/dynamodb/exports/create" }] },
    { pattern: "/dynamodb/imports", component: Imports, crumbs: () => [{ text: "Imports from S3", href: "#/dynamodb/imports" }] },
    { pattern: "/dynamodb/imports/create", component: ImportFromS3, crumbs: () => [{ text: "Imports from S3", href: "#/dynamodb/imports" }, { text: "Import from S3", href: "#/dynamodb/imports/create" }] },
    { pattern: "/dynamodb/dax/clusters", component: DaxClusters, crumbs: () => [{ text: "DAX", href: "#/dynamodb/dax/clusters" }, { text: "Clusters", href: "#/dynamodb/dax/clusters" }] },
    { pattern: "/dynamodb/dax/subnet-groups", component: DaxSubnetGroups, crumbs: () => [{ text: "DAX", href: "#/dynamodb/dax/clusters" }, { text: "Subnet groups", href: "#/dynamodb/dax/subnet-groups" }] },
    { pattern: "/dynamodb/dax/parameter-groups", component: DaxParameterGroups, crumbs: () => [{ text: "DAX", href: "#/dynamodb/dax/clusters" }, { text: "Parameter groups", href: "#/dynamodb/dax/parameter-groups" }] },
    { pattern: "/dynamodb/dax/events", component: DaxEvents, crumbs: () => [{ text: "DAX", href: "#/dynamodb/dax/clusters" }, { text: "Events", href: "#/dynamodb/dax/events" }] },
    ...NS.map(([p, t]) => ({ pattern: `/dynamodb/${p}`, component: ns(t), crumbs: () => [{ text: t, href: `#/dynamodb/${p}` }] })),
  ],
};
