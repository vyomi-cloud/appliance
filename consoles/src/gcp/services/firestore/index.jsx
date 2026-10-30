import StorageIcon from "@mui/icons-material/esm/Storage.js";
import TableChartIcon from "@mui/icons-material/esm/TableChart.js";
import ListAltIcon from "@mui/icons-material/esm/ListAlt.js";
import ImportExportIcon from "@mui/icons-material/esm/ImportExport.js";
import HealthAndSafetyIcon from "@mui/icons-material/esm/HealthAndSafety.js";
import ScheduleIcon from "@mui/icons-material/esm/Schedule.js";
import GppGoodIcon from "@mui/icons-material/esm/GppGood.js";
import InsightsIcon from "@mui/icons-material/esm/Insights.js";
import BarChartIcon from "@mui/icons-material/esm/BarChart.js";
import GridOnIcon from "@mui/icons-material/esm/GridOn.js";
import Databases from "./Databases.jsx";
import CreateDatabase from "./CreateDatabase.jsx";
import FirestoreStudio from "./FirestoreStudio.jsx";
import Indexes from "./Indexes.jsx";
import CreateIndex from "./CreateIndex.jsx";
import Ttl from "./Ttl.jsx";
import SecurityRules from "./SecurityRules.jsx";
import ImportExport from "./ImportExport.jsx";
import DisasterRecovery from "./DisasterRecovery.jsx";
import GapPage from "./GapPage.jsx";

const gap = (title, id) => () => <GapPage title={title} id={id} />;

/** The database id the current route is scoped to, e.g. "/firestore/databases/mydb/studio" -> "mydb". */
function currentDatabase() {
  const m = location.hash.match(/^#\/firestore\/databases\/([^/?]+)\/[^/?]+/);
  return m ? decodeURIComponent(m[1]) : null;
}

const subnav = (db) => [
  { text: "Firestore Studio", href: `#/firestore/databases/${encodeURIComponent(db)}/studio`, icon: TableChartIcon },
  { text: "Indexes", href: `#/firestore/databases/${encodeURIComponent(db)}/indexes`, icon: ListAltIcon, match: [`#/firestore/databases/${encodeURIComponent(db)}/create-index`] },
  { text: "Import/Export", href: `#/firestore/databases/${encodeURIComponent(db)}/import-export`, icon: ImportExportIcon },
  { text: "Disaster recovery", href: `#/firestore/databases/${encodeURIComponent(db)}/disaster-recovery`, icon: HealthAndSafetyIcon },
  { text: "Time-to-live (TTL)", href: `#/firestore/databases/${encodeURIComponent(db)}/ttl`, icon: ScheduleIcon },
  { text: "Security rules", href: `#/firestore/databases/${encodeURIComponent(db)}/rules`, icon: GppGoodIcon },
  { text: "Insights", href: `#/firestore/databases/${encodeURIComponent(db)}/insights`, icon: InsightsIcon },
  { text: "Usage", href: `#/firestore/databases/${encodeURIComponent(db)}/usage`, icon: BarChartIcon },
  { text: "Key Visualizer", href: `#/firestore/databases/${encodeURIComponent(db)}/key-visualizer`, icon: GridOnIcon },
];

export default {
  get nav() {
    const base = [{ text: "All databases", href: "#/firestore/databases", icon: StorageIcon, match: ["#/firestore/create-database"] }];
    const db = currentDatabase();
    return db ? [...base, { section: db, items: subnav(db) }] : base;
  },
  routes: [
    { pattern: "/firestore", component: Databases },
    { pattern: "/datastore", component: Databases },
    { pattern: "/firestore/databases", component: Databases },
    { pattern: "/firestore/create-database", component: CreateDatabase },
    { pattern: "/firestore/databases/:name/studio", component: FirestoreStudio },
    { pattern: "/firestore/databases/:name/indexes", component: Indexes },
    { pattern: "/firestore/databases/:name/create-index", component: CreateIndex },
    { pattern: "/firestore/databases/:name/ttl", component: Ttl },
    { pattern: "/firestore/databases/:name/rules", component: SecurityRules },
    { pattern: "/firestore/databases/:name/import-export", component: ImportExport },
    { pattern: "/firestore/databases/:name/disaster-recovery", component: DisasterRecovery },
    { pattern: "/firestore/databases/:name/insights", component: gap("Insights", "gcp.firestore.insights") },
    { pattern: "/firestore/databases/:name/usage", component: gap("Usage", "gcp.firestore.usage") },
    { pattern: "/firestore/databases/:name/key-visualizer", component: gap("Key Visualizer", "gcp.firestore.key-visualizer") },
  ],
};
