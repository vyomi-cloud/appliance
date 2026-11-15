import FoundryHub, { PAGE_LABEL } from "./FoundryHub.jsx";

export default {
  routes: [
    { pattern: "/foundry", component: FoundryHub },
    { pattern: "/foundry/:panel", component: FoundryHub, crumbs: (p) => [{ text: PAGE_LABEL[p.panel] || p.panel, href: `#/foundry/${p.panel}` }] },
  ],
};
