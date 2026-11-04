import SearchIcon from "@mui/icons-material/esm/Search.js";
import QueryStatsIcon from "@mui/icons-material/esm/QueryStats.js";
import FunctionsIcon from "@mui/icons-material/esm/Functions.js";
import AltRouteIcon from "@mui/icons-material/esm/AltRoute.js";
import InventoryIcon from "@mui/icons-material/esm/Inventory2.js";
import LogsExplorer from "./LogsExplorer.jsx";
import ObservabilityAnalytics from "./ObservabilityAnalytics.jsx";
import LogMetrics from "./LogMetrics.jsx";
import CreateMetric from "./CreateMetric.jsx";
import LogRouter from "./LogRouter.jsx";
import CreateSink from "./CreateSink.jsx";
import LogsStorage from "./LogsStorage.jsx";
import CreateLogBucket from "./CreateLogBucket.jsx";
import BucketDetail from "./BucketDetail.jsx";

export default {
  nav: [
    { text: "Logs Explorer", href: "#/logs/query", icon: SearchIcon },
    { text: "Observability Analytics", href: "#/logs/analytics", icon: QueryStatsIcon },
    { section: "Configure", items: [
      { text: "Log-based metrics", href: "#/logs/metrics", icon: FunctionsIcon, match: ["#/logs/metrics/edit"] },
      { text: "Log router", href: "#/logs/router", icon: AltRouteIcon, match: ["#/logs/router/sink"] },
      { text: "Logs storage", href: "#/logs/storage", icon: InventoryIcon, match: ["#/logs/storage/bucket"] },
    ] },
  ],
  routes: [
    { pattern: "/logs", component: LogsExplorer },
    { pattern: "/logs/query", component: LogsExplorer },
    { pattern: "/logs/analytics", component: ObservabilityAnalytics },
    { pattern: "/logs/metrics", component: LogMetrics },
    { pattern: "/logs/metrics/edit", component: CreateMetric },
    { pattern: "/logs/router", component: LogRouter },
    { pattern: "/logs/router/sink", component: CreateSink },
    { pattern: "/logs/storage", component: LogsStorage },
    { pattern: "/logs/storage/bucket", component: CreateLogBucket },
    { pattern: "/logs/storage/bucket/:name", component: BucketDetail },
  ],
};
