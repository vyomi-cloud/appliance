import Home from "./Home.jsx";
import Dashboard from "./Dashboard.jsx";
import EventBuses from "./EventBuses.jsx";
import EventBusDetail from "./EventBusDetail.jsx";
import CreateEventBus from "./CreateEventBus.jsx";
import SendEvents from "./SendEvents.jsx";
import Rules from "./Rules.jsx";
import RuleDetail from "./RuleDetail.jsx";
import CreateRule from "./CreateRule.jsx";
import Archives from "./Archives.jsx";
import CreateArchive from "./CreateArchive.jsx";
import ScheduledRules from "./ScheduledRules.jsx";
import CreateScheduledRule from "./CreateScheduledRule.jsx";
import Schedules from "./Schedules.jsx";
import CreateSchedule from "./CreateSchedule.jsx";
import ScheduleGroups from "./ScheduleGroups.jsx";
import GapRoutes from "./GapRoutes.jsx";

const crumb = (text, href) => ({ text, href });
const root = [crumb("EventBridge", "#/eventbridge")];

export default {
  nav: [
    { type: "link", text: "Dashboard", href: "#/eventbridge/dashboard" },
    { type: "section", text: "Custom event buses", items: [
      { type: "link", text: "Custom event buses", href: "#/eventbridge/event-buses" },
    ] },
    { type: "section", text: "Default event bus", items: [
      { type: "link", text: "Default event bus", href: "#/eventbridge/event-buses/default" },
      { type: "link", text: "Rules", href: "#/eventbridge/rules" },
      { type: "link", text: "Archives", href: "#/eventbridge/archives" },
    ] },
    { type: "section", text: "Pipes", items: [
      { type: "link", text: "Pipes", href: "#/eventbridge/pipes" },
    ] },
    { type: "section", text: "Scheduler", items: [
      { type: "link", text: "Schedules", href: "#/eventbridge/schedules" },
      { type: "link", text: "Schedule groups", href: "#/eventbridge/schedule-groups" },
      { type: "link", text: "Scheduled rules (legacy)", href: "#/eventbridge/scheduled-rules" },
    ] },
    { type: "section", text: "Integration", items: [
      { type: "link", text: "Partner event sources", href: "#/eventbridge/partner-event-sources" },
      { type: "link", text: "API destinations", href: "#/eventbridge/api-destinations" },
      { type: "link", text: "Connections", href: "#/eventbridge/connections" },
    ] },
    { type: "section", text: "Schema registry", items: [
      { type: "link", text: "Schemas", href: "#/eventbridge/schemas" },
    ] },
    { type: "section", text: "Classic event routing", items: [
      { type: "link", text: "Global endpoints", href: "#/eventbridge/global-endpoints" },
    ] },
    { type: "section", text: "Developer resources", items: [
      { type: "link", text: "Learn", href: "#/eventbridge/learn" },
      { type: "link", text: "Sandbox", href: "#/eventbridge/sandbox" },
      { type: "link", text: "Quick starts", href: "#/eventbridge/quick-starts" },
    ] },
  ],
  routes: [
    { pattern: "/eventbridge", component: Home, crumbs: () => root },
    { pattern: "/eventbridge/home", component: Home, crumbs: () => root },
    { pattern: "/eventbridge/dashboard", component: Dashboard, crumbs: () => [...root, crumb("Dashboard", "#/eventbridge/dashboard")] },

    { pattern: "/eventbridge/event-buses", component: EventBuses, crumbs: () => [...root, crumb("Custom event buses", "#/eventbridge/event-buses")] },
    { pattern: "/eventbridge/create-event-bus", component: CreateEventBus, crumbs: () => [...root, crumb("Custom event buses", "#/eventbridge/event-buses"), crumb("Create custom event bus", "#/eventbridge/create-event-bus")] },
    { pattern: "/eventbridge/event-buses/:name", component: EventBusDetail, crumbs: (p) => [...root, crumb(p.name, `#/eventbridge/event-buses/${p.name}`)] },
    { pattern: "/eventbridge/event-buses/:name/edit", component: CreateEventBus, crumbs: (p) => [...root, crumb(p.name, `#/eventbridge/event-buses/${p.name}`), crumb("Edit event bus", `#/eventbridge/event-buses/${p.name}/edit`)] },
    { pattern: "/eventbridge/event-buses/:name/send", component: SendEvents, crumbs: (p) => [...root, crumb(p.name, `#/eventbridge/event-buses/${p.name}`), crumb("Send events", `#/eventbridge/event-buses/${p.name}/send`)] },

    { pattern: "/eventbridge/rules", component: Rules, crumbs: () => [...root, crumb("Default event bus", "#/eventbridge/event-buses/default"), crumb("Rules", "#/eventbridge/rules")] },
    { pattern: "/eventbridge/create-rule", component: CreateRule, crumbs: () => [...root, crumb("Rules", "#/eventbridge/rules"), crumb("Create rule", "#/eventbridge/create-rule")] },
    { pattern: "/eventbridge/rules/:name", component: RuleDetail, crumbs: (p) => [...root, crumb("Rules", "#/eventbridge/rules"), crumb(p.name, `#/eventbridge/rules/${p.name}`)] },
    { pattern: "/eventbridge/rules/:name/edit", component: CreateRule, crumbs: (p) => [...root, crumb("Rules", "#/eventbridge/rules"), crumb(p.name, `#/eventbridge/rules/${p.name}`), crumb("Edit", `#/eventbridge/rules/${p.name}/edit`)] },

    { pattern: "/eventbridge/archives", component: Archives, crumbs: () => [...root, crumb("Default event bus", "#/eventbridge/event-buses/default"), crumb("Archives", "#/eventbridge/archives")] },
    { pattern: "/eventbridge/create-archive", component: CreateArchive, crumbs: () => [...root, crumb("Archives", "#/eventbridge/archives"), crumb("Create archive", "#/eventbridge/create-archive")] },
    { pattern: "/eventbridge/archives/:name/edit", component: CreateArchive, crumbs: (p) => [...root, crumb("Archives", "#/eventbridge/archives"), crumb(p.name, "#/eventbridge/archives"), crumb("Edit", `#/eventbridge/archives/${p.name}/edit`)] },

    { pattern: "/eventbridge/scheduled-rules", component: ScheduledRules, crumbs: () => [...root, crumb("Scheduled rules", "#/eventbridge/scheduled-rules")] },
    { pattern: "/eventbridge/create-scheduled-rule", component: CreateScheduledRule, crumbs: () => [...root, crumb("Scheduled rules", "#/eventbridge/scheduled-rules"), crumb("Create scheduled rule", "#/eventbridge/create-scheduled-rule")] },

    { pattern: "/eventbridge/schedules", component: Schedules, crumbs: () => [...root, crumb("Scheduler", "#/eventbridge/schedules"), crumb("Schedules", "#/eventbridge/schedules")] },
    { pattern: "/eventbridge/create-schedule", component: CreateSchedule, crumbs: () => [...root, crumb("Schedules", "#/eventbridge/schedules"), crumb("Create schedule", "#/eventbridge/create-schedule")] },
    { pattern: "/eventbridge/schedule-groups", component: ScheduleGroups, crumbs: () => [...root, crumb("Scheduler", "#/eventbridge/schedules"), crumb("Schedule groups", "#/eventbridge/schedule-groups")] },

    ...GapRoutes.map(({ path, title, component }) => ({
      pattern: `/eventbridge/${path}`,
      component,
      crumbs: () => [...root, crumb(title, `#/eventbridge/${path}`)],
    })),
  ],
};
