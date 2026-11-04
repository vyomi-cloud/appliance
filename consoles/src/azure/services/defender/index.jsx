import { Alerts, Compliance, DefenderPlans, Environment, Inventory, NotSimulatedPanel, Overview, Posture, RecommendationDetail, Recommendations } from "./Pages.jsx";
import { LABEL } from "./DefenderShell.jsx";

const crumb = (text, href) => [{ text, href }];

export default {
  routes: [
    { pattern: "/defender", component: Overview },
    { pattern: "/defender/overview", component: Overview },
    { pattern: "/defender/recommendations", component: Recommendations, crumbs: () => crumb("Recommendations", "#/defender/recommendations") },
    { pattern: "/defender/recommendations/:name", component: RecommendationDetail,
      crumbs: (p) => [{ text: "Recommendations", href: "#/defender/recommendations" }, { text: "Recommendation details", href: `#/defender/recommendations/${p.name}` }] },
    { pattern: "/defender/alerts", component: Alerts, crumbs: () => crumb("Security alerts", "#/defender/alerts") },
    { pattern: "/defender/inventory", component: Inventory, crumbs: () => crumb("Inventory", "#/defender/inventory") },
    { pattern: "/defender/posture", component: Posture, crumbs: () => crumb("Security posture", "#/defender/posture") },
    { pattern: "/defender/compliance", component: Compliance, crumbs: () => crumb("Regulatory compliance", "#/defender/compliance") },
    { pattern: "/defender/environment", component: Environment, crumbs: () => crumb("Environment settings", "#/defender/environment") },
    { pattern: "/defender/environment/:sub", component: DefenderPlans,
      crumbs: (p) => [{ text: "Environment settings", href: "#/defender/environment" }, { text: "Defender plans", href: `#/defender/environment/${p.sub}` }] },
    { pattern: "/defender/:panel", component: NotSimulatedPanel, crumbs: (p) => crumb(LABEL[p.panel] || p.panel, `#/defender/${p.panel}`) },
  ],
};
