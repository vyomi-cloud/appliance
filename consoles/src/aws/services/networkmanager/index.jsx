import { GlobalNetworkDetail, GlobalNetworks } from "./Pages.jsx";

const c = (...xs) => () => xs.map(([text, href]) => ({ text, href }));
export default {
  nav: [{ type: "link", text: "Global networks", href: "#/networkmanager/global-networks" }],
  routes: [
    { pattern: "/networkmanager", component: GlobalNetworks, crumbs: c(["Global networks", "#/networkmanager/global-networks"]) },
    { pattern: "/networkmanager/global-networks", component: GlobalNetworks, crumbs: c(["Global networks", "#/networkmanager/global-networks"]) },
    { pattern: "/networkmanager/global-networks/view", component: GlobalNetworkDetail, crumbs: c(["Global networks", "#/networkmanager/global-networks"]) },
  ],
};
