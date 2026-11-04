import DashboardIcon from "@mui/icons-material/esm/Dashboard.js";
import InventoryIcon from "@mui/icons-material/esm/Inventory.js";
import BarChartIcon from "@mui/icons-material/esm/BarChart.js";
import SettingsIcon from "@mui/icons-material/esm/Settings.js";
import InsightsIcon from "@mui/icons-material/esm/Insights.js";
import CheckIcon from "@mui/icons-material/esm/Check.js";
import LayersIcon from "@mui/icons-material/esm/Layers.js";
import AccountTreeIcon from "@mui/icons-material/esm/AccountTree.js";
import AutoAwesomeIcon from "@mui/icons-material/esm/AutoAwesome.js";
import Buckets from "./Buckets.jsx";
import CreateBucket from "./CreateBucket.jsx";
import BucketDetail from "./BucketDetail.jsx";
import ObjectDetail from "./ObjectDetail.jsx";
import BatchOperations from "./BatchOperations.jsx";
import InsightsDatasets from "./InsightsDatasets.jsx";
import { Overview, Monitoring, Settings, Advisor, StorageIntelligenceConfiguration, ObjectEnrichments } from "./Dashboards.jsx";

export default {
  nav: [
    { text: "Overview", href: "#/storage/overview", icon: DashboardIcon },
    { text: "Buckets", href: "#/storage/browser", icon: InventoryIcon, match: ["#/storage/create-bucket"] },
    { text: "Monitoring", href: "#/storage/monitoring", icon: BarChartIcon },
    { text: "Settings", href: "#/storage/settings", icon: SettingsIcon },
    { section: "Storage Intelligence", items: [
      { text: "Advisor", href: "#/storage/advisor", icon: InsightsIcon },
      { text: "Batch operations", href: "#/storage/batch-operations", icon: CheckIcon },
      { text: "Insights datasets", href: "#/storage/insights-datasets", icon: LayersIcon },
      { text: "Configuration", href: "#/storage/intelligence-configuration", icon: AccountTreeIcon },
    ] },
    { section: "Smart Storage", items: [
      { text: "Object enrichments", href: "#/storage/object-enrichments", icon: AutoAwesomeIcon },
    ] },
  ],
  routes: [
    { pattern: "/storage", component: Buckets },
    { pattern: "/storage/browser", component: Buckets },
    { pattern: "/storage/create-bucket", component: CreateBucket },
    { pattern: "/storage/browser/:name", component: BucketDetail },
    { pattern: "/storage/browser/:name/object", component: ObjectDetail },
    { pattern: "/storage/overview", component: Overview },
    { pattern: "/storage/monitoring", component: Monitoring },
    { pattern: "/storage/settings", component: Settings },
    { pattern: "/storage/advisor", component: Advisor },
    { pattern: "/storage/batch-operations", component: BatchOperations },
    { pattern: "/storage/insights-datasets", component: InsightsDatasets },
    { pattern: "/storage/intelligence-configuration", component: StorageIntelligenceConfiguration },
    { pattern: "/storage/object-enrichments", component: ObjectEnrichments },
  ],
};
