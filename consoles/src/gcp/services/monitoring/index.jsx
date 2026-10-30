import DashboardIcon from "@mui/icons-material/esm/DashboardOutlined.js";
import ViewQuiltIcon from "@mui/icons-material/esm/ViewQuiltOutlined.js";
import AppsIcon from "@mui/icons-material/esm/AppsOutlined.js";
import TroubleshootIcon from "@mui/icons-material/esm/TroubleshootOutlined.js";
import NotificationsActiveIcon from "@mui/icons-material/esm/NotificationsActiveOutlined.js";
import TuneIcon from "@mui/icons-material/esm/TuneOutlined.js";
import OpenInNewIcon from "@mui/icons-material/esm/OpenInNewOutlined.js";
import Overview from "./Overview.jsx";
import Dashboards from "./Dashboards.jsx";
import CreateDashboard from "./CreateDashboard.jsx";
import DashboardDetail from "./DashboardDetail.jsx";
import MetricsExplorer from "./MetricsExplorer.jsx";
import Alerting from "./Alerting.jsx";
import Alerts from "./Alerts.jsx";
import CreateSnooze from "./CreateSnooze.jsx";
import CreateAlertPolicy from "./CreateAlertPolicy.jsx";
import UptimeChecks from "./UptimeChecks.jsx";
import CreateUptimeCheck from "./CreateUptimeCheck.jsx";
import SyntheticMonitoring from "./SyntheticMonitoring.jsx";
import Slos from "./Slos.jsx";
import Groups from "./Groups.jsx";
import Settings from "./Settings.jsx";
import Permissions from "./Permissions.jsx";
import MetricsManagement from "./MetricsManagement.jsx";
import Integrations from "./Integrations.jsx";
import { CostExplorer, ApplicationMonitoring, TraceExplorer, ErrorReporting } from "./SimplePages.jsx";
import { classicHref } from "../registry.js";

const ext = (text) => ({ text, href: classicHref("monitoring"), icon: OpenInNewIcon });

export default {
  nav: [
    { text: "Overview", href: "#/monitoring", icon: DashboardIcon },
    { text: "Dashboards", href: "#/monitoring/dashboards", icon: ViewQuiltIcon, match: ["#/monitoring/dashboards/create"] },
    { text: "Application monitoring", href: "#/monitoring/application-monitoring", icon: AppsIcon },
    { section: "Explore", items: [
      { text: "Metrics explorer", href: "#/monitoring/metrics-explorer", icon: TroubleshootIcon },
      ext("Logs explorer"),
      ext("Observability analytics"),
      { text: "Trace explorer", href: "#/monitoring/trace-explorer" },
      { text: "Cost explorer", href: "#/monitoring/cost-explorer" },
    ] },
    { section: "Detect", items: [
      { text: "Alerting", href: "#/monitoring/alerting", icon: NotificationsActiveIcon, match: ["#/monitoring/alerting/alerts", "#/monitoring/alerting/policies/create", "#/monitoring/alerting/snooze/create"] },
      { text: "Error reporting", href: "#/monitoring/error-reporting" },
      { text: "Uptime checks", href: "#/monitoring/uptime", match: ["#/monitoring/uptime/create"] },
      { text: "Synthetic monitoring", href: "#/monitoring/synthetic-monitoring" },
      { text: "SLOs", href: "#/monitoring/services" },
    ] },
    { section: "Configure", items: [
      { text: "Integrations", href: "#/monitoring/integrations", icon: TuneIcon },
      ext("Log-based metrics"),
      ext("Log router"),
      ext("Logs storage"),
      { text: "Metrics management", href: "#/monitoring/metrics-management" },
      { text: "Groups", href: "#/monitoring/groups" },
      { text: "Settings", href: "#/monitoring/settings" },
      { text: "Permissions", href: "#/monitoring/permissions" },
    ] },
    ext("Observability Scopes"),
    ext("Release Notes"),
  ],
  routes: [
    { pattern: "/monitoring", component: Overview },
    { pattern: "/monitoring/dashboards", component: Dashboards },
    { pattern: "/monitoring/dashboards/create", component: CreateDashboard },
    { pattern: "/monitoring/dashboards/:id", component: DashboardDetail },
    { pattern: "/monitoring/metrics-explorer", component: MetricsExplorer },
    { pattern: "/monitoring/alerting", component: Alerting },
    { pattern: "/monitoring/alerting/alerts", component: Alerts },
    { pattern: "/monitoring/alerting/snooze/create", component: CreateSnooze },
    { pattern: "/monitoring/alerting/policies/create", component: CreateAlertPolicy },
    { pattern: "/monitoring/uptime", component: UptimeChecks },
    { pattern: "/monitoring/uptime/create", component: CreateUptimeCheck },
    { pattern: "/monitoring/synthetic-monitoring", component: SyntheticMonitoring },
    { pattern: "/monitoring/services", component: Slos },
    { pattern: "/monitoring/groups", component: Groups },
    { pattern: "/monitoring/settings", component: Settings },
    { pattern: "/monitoring/permissions", component: Permissions },
    { pattern: "/monitoring/metrics-management", component: MetricsManagement },
    { pattern: "/monitoring/integrations", component: Integrations },
    { pattern: "/monitoring/cost-explorer", component: CostExplorer },
    { pattern: "/monitoring/application-monitoring", component: ApplicationMonitoring },
    { pattern: "/monitoring/trace-explorer", component: TraceExplorer },
    { pattern: "/monitoring/error-reporting", component: ErrorReporting },
  ],
};
