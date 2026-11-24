import Studio from "./Studio.jsx";

const crumbs = () => [{ text: "Management & Governance", href: "#/tfstudio" }, { text: "Infrastructure Studio", href: "#/tfstudio" }];

export default {
  nav: [{ type: "link", text: "Infrastructure Studio", href: "#/tfstudio" }],
  routes: [{ pattern: "/tfstudio", component: Studio, crumbs }],
};
