import { Box, Typography } from "@mui/material";
import DashboardIcon from "@mui/icons-material/esm/Dashboard.js";
import InventoryIcon from "@mui/icons-material/esm/Inventory.js";
import BarChartIcon from "@mui/icons-material/esm/BarChart.js";
import SettingsIcon from "@mui/icons-material/esm/Settings.js";
import InsightsIcon from "@mui/icons-material/esm/Insights.js";
import CheckIcon from "@mui/icons-material/esm/Check.js";
import LayersIcon from "@mui/icons-material/esm/Layers.js";
import AccountTreeIcon from "@mui/icons-material/esm/AccountTree.js";
import Buckets from "./Buckets.jsx";
import CreateBucket from "./CreateBucket.jsx";
import BucketDetail from "./BucketDetail.jsx";
import ObjectDetail from "./ObjectDetail.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";

const ns = (title, feature) => function NotSimulatedPage() {
  return (
    <Box sx={{ pt: 2 }}>
      <Typography variant="h1" component="h1" sx={{ mb: 2 }}>{title}</Typography>
      <NotSimulatedContainer title={title} feature={feature || `Cloud Storage ${title}`} />
    </Box>
  );
};

const GAPS = [
  ["overview", "Overview", DashboardIcon], ["monitoring", "Monitoring", BarChartIcon], ["settings", "Settings", SettingsIcon],
  ["advisor", "Advisor", InsightsIcon], ["batch-operations", "Batch operations", CheckIcon], ["insights-datasets", "Insights datasets", LayersIcon],
  ["intelligence-configuration", "Configuration", AccountTreeIcon],
];
const gap = (id) => GAPS.find((g) => g[0] === id);
const link = (id) => { const [p, t, icon] = gap(id); return { text: t, href: `#/storage/${p}`, icon }; };

export default {
  nav: [
    link("overview"),
    { text: "Buckets", href: "#/storage/browser", icon: InventoryIcon, match: ["#/storage/create-bucket"] },
    link("monitoring"),
    link("settings"),
    { section: "Storage Intelligence", items: [link("advisor"), link("batch-operations"), link("insights-datasets"), link("intelligence-configuration")] },
  ],
  routes: [
    { pattern: "/storage", component: Buckets },
    { pattern: "/storage/browser", component: Buckets },
    { pattern: "/storage/create-bucket", component: CreateBucket },
    { pattern: "/storage/browser/:name", component: BucketDetail },
    { pattern: "/storage/browser/:name/object", component: ObjectDetail },
    ...GAPS.map(([p, t]) => ({ pattern: `/storage/${p}`, component: ns(t === "Configuration" ? "Storage Intelligence configuration" : t) })),
  ],
};
