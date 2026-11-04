import CostExplorer from "./CostExplorer.jsx";

const crumbs = () => [{ text: "Cost Management", href: "#/cost-explorer" }, { text: "Cost Explorer", href: "#/cost-explorer" }];

export default {
  nav: [
    { type: "link", text: "Cost Explorer", href: "#/cost-explorer" },
  ],
  routes: [
    { pattern: "/cost-explorer", component: CostExplorer, crumbs },
  ],
};
