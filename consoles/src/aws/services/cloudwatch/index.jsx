import Landing from "./Landing.jsx";
import Dashboards from "./Dashboards.jsx";
import CreateDashboard from "./CreateDashboard.jsx";
import DashboardDetail from "./DashboardDetail.jsx";
import Alarms from "./Alarms.jsx";
import CreateAlarm from "./CreateAlarm.jsx";
import AlarmDetail from "./AlarmDetail.jsx";
import LogGroups from "./LogGroups.jsx";
import CreateLogGroup from "./CreateLogGroup.jsx";
import LogGroupDetail from "./LogGroupDetail.jsx";
import LogEvents from "./LogEvents.jsx";
import CreateLogStream from "./CreateLogStream.jsx";
import LogsInsights from "./LogsInsights.jsx";
import LiveTail from "./LiveTail.jsx";
import AllMetrics from "./AllMetrics.jsx";
import Settings from "./Settings.jsx";

const CW = { text: "CloudWatch", href: "#/cloudwatch" };

export default {
  nav: [
    { type: "link", text: "Favorites and recents", href: "#/cloudwatch/home" },
    { type: "link", text: "Dashboards", href: "#/cloudwatch/dashboards" },
    { type: "section", text: "Alarms", items: [
      { type: "link", text: "In alarm", href: "#/cloudwatch/alarms?state=ALARM" },
      { type: "link", text: "All alarms", href: "#/cloudwatch/alarms" },
    ] },
    { type: "section", text: "Logs", items: [
      { type: "link", text: "Log management", href: "#/cloudwatch/logs" },
      { type: "link", text: "Logs Insights", href: "#/cloudwatch/logs-insights" },
      { type: "link", text: "Live Tail", href: "#/cloudwatch/live-tail" },
    ] },
    { type: "section", text: "Metrics", items: [
      { type: "link", text: "All metrics", href: "#/cloudwatch/metrics" },
    ] },
    { type: "link", text: "Settings", href: "#/cloudwatch/settings" },
  ],
  routes: [
    { pattern: "/cloudwatch", component: Landing, crumbs: () => [CW] },
    { pattern: "/cloudwatch/home", component: Landing, crumbs: () => [CW] },

    { pattern: "/cloudwatch/dashboards", component: Dashboards, crumbs: () => [CW, { text: "Dashboards", href: "#/cloudwatch/dashboards" }] },
    { pattern: "/cloudwatch/dashboards/create", component: CreateDashboard, crumbs: () => [CW, { text: "Dashboards", href: "#/cloudwatch/dashboards" }, { text: "Create new dashboard", href: "#/cloudwatch/dashboards/create" }] },
    { pattern: "/cloudwatch/dashboards/:name", component: DashboardDetail, crumbs: (p) => [CW, { text: "Dashboards", href: "#/cloudwatch/dashboards" }, { text: p.name, href: `#/cloudwatch/dashboards/${p.name}` }] },

    { pattern: "/cloudwatch/alarms", component: Alarms, crumbs: () => [CW, { text: "Alarms", href: "#/cloudwatch/alarms" }] },
    { pattern: "/cloudwatch/alarms/create", component: CreateAlarm, crumbs: () => [CW, { text: "Alarms", href: "#/cloudwatch/alarms" }, { text: "Create alarm", href: "#/cloudwatch/alarms/create" }] },
    { pattern: "/cloudwatch/alarms/:name", component: AlarmDetail, crumbs: (p) => [CW, { text: "Alarms", href: "#/cloudwatch/alarms" }, { text: p.name, href: `#/cloudwatch/alarms/${p.name}` }] },

    { pattern: "/cloudwatch/logs", component: LogGroups, crumbs: () => [CW, { text: "Log management", href: "#/cloudwatch/logs" }] },
    { pattern: "/cloudwatch/logs/create", component: CreateLogGroup, crumbs: () => [CW, { text: "Log management", href: "#/cloudwatch/logs" }, { text: "Create log group", href: "#/cloudwatch/logs/create" }] },
    { pattern: "/cloudwatch/logs/:name", component: LogGroupDetail, crumbs: (p) => [CW, { text: "Log management", href: "#/cloudwatch/logs" }, { text: p.name, href: `#/cloudwatch/logs/${p.name}` }] },
    { pattern: "/cloudwatch/logs/:name/streams/create", component: CreateLogStream, crumbs: (p) => [CW, { text: "Log management", href: "#/cloudwatch/logs" }, { text: p.name, href: `#/cloudwatch/logs/${p.name}` }, { text: "Create log stream", href: `#/cloudwatch/logs/${p.name}/streams/create` }] },
    { pattern: "/cloudwatch/logs/:name/streams/:stream", component: LogEvents, crumbs: (p) => [CW, { text: "Log management", href: "#/cloudwatch/logs" }, { text: p.name, href: `#/cloudwatch/logs/${p.name}` }, { text: p.stream, href: `#/cloudwatch/logs/${p.name}/streams/${p.stream}` }] },

    { pattern: "/cloudwatch/logs-insights", component: LogsInsights, crumbs: () => [CW, { text: "Logs Insights", href: "#/cloudwatch/logs-insights" }] },
    { pattern: "/cloudwatch/live-tail", component: LiveTail, crumbs: () => [CW, { text: "Live Tail", href: "#/cloudwatch/live-tail" }] },
    { pattern: "/cloudwatch/metrics", component: AllMetrics, crumbs: () => [CW, { text: "Metrics", href: "#/cloudwatch/metrics" }] },
    { pattern: "/cloudwatch/settings", component: Settings, crumbs: () => [CW, { text: "Settings", href: "#/cloudwatch/settings" }] },
  ],
};
