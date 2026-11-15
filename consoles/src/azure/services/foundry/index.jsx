import FoundryHub, { PAGE_LABEL } from "./FoundryHub.jsx";

export default {
  routes: [
    { pattern: "/foundry", component: FoundryHub },
    { pattern: "/foundry/finetuning/:jobId", component: FoundryHub, crumbs: (p) => [{ text: "Fine-tuning", href: "#/foundry/finetuning" }, { text: decodeURIComponent(p.jobId), href: `#/foundry/finetuning/${p.jobId}` }] },
    { pattern: "/foundry/:panel", component: FoundryHub, crumbs: (p) => [{ text: PAGE_LABEL[p.panel] || p.panel, href: `#/foundry/${p.panel}` }] },
  ],
};
