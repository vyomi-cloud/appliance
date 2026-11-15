import Landing from "./Landing.jsx";
import Quickstart from "./Quickstart.jsx";
import ApiKeys from "./ApiKeys.jsx";
import Quotas from "./Quotas.jsx";
import Compare from "./Compare.jsx";
import Tokenizer from "./Tokenizer.jsx";
import { bedrockNav } from "./nav.js";
import Playground from "./Playground.jsx";
import Models from "./Models.jsx";
import { KnowledgeBases, KnowledgeBaseDetail } from "./KnowledgeBases.jsx";
import { Agents, AgentDetail } from "./Agents.jsx";
import { AgentCore, GatewayDetail } from "./AgentCore.jsx";
import Studio from "./studio/Studio.jsx";
import { INFER_TUNE_ROUTES } from "./inferTune/routes.jsx";
import ScopeSection from "../../../common/ScopeSection.jsx";
import { scopeFor } from "../../../common/scopeHelp.js";

const top = [{ text: "Amazon Bedrock", href: "#/bedrock" }];
const c = (text, h) => ({ text, href: h });

// Right-hand help pane: "Scope and limits" for the page (common/scopeHelp.js, from the ai-*.md branch docs).
const withHelp = (r) => { const e = scopeFor("aws", r.pattern); return e ? { ...r, help: { title: e.title.replace(/: scope and limits$/, ""), body: <ScopeSection entry={e} showTitle={false} /> } } : r; };

export default {
  nav: bedrockNav,
  routes: [
    ...INFER_TUNE_ROUTES,   // lane bedrockui-b: Infer + Tune pages (nav entries live in nav.js)
    { pattern: "/bedrock", component: Landing, crumbs: () => [c("Overview", "#/bedrock")] },
    { pattern: "/bedrock/quickstart", component: Quickstart, crumbs: () => [c("Quickstart", "#/bedrock/quickstart")] },
    { pattern: "/bedrock/api-keys", component: ApiKeys, crumbs: () => [c("API keys", "#/bedrock/api-keys")] },
    { pattern: "/bedrock/quotas", component: Quotas, crumbs: () => [c("Quotas", "#/bedrock/quotas")] },
    { pattern: "/bedrock/compare-models", component: Compare, crumbs: () => [c("Compare models", "#/bedrock/compare-models")] },
    { pattern: "/bedrock/tokenizer", component: Tokenizer, crumbs: () => [c("Tokenizer", "#/bedrock/tokenizer")] },
    { pattern: "/bedrock/playground", component: Playground, crumbs: () => [...top, c("Playground", "#/bedrock/playground")] },
    { pattern: "/bedrock/models", component: Models, crumbs: () => [...top, c("Model catalog", "#/bedrock/models")] },
    { pattern: "/bedrock/knowledge-bases", component: KnowledgeBases, crumbs: () => [...top, c("Knowledge bases", "#/bedrock/knowledge-bases")] },
    { pattern: "/bedrock/knowledge-bases/studio", component: Studio, crumbs: () => [...top, c("Knowledge bases", "#/bedrock/knowledge-bases"), c("RAG Studio", "#/bedrock/knowledge-bases/studio")] },
    { pattern: "/bedrock/knowledge-bases/:id", component: KnowledgeBaseDetail, crumbs: (p) => [...top, c("Knowledge bases", "#/bedrock/knowledge-bases"), c(p.id, `#/bedrock/knowledge-bases/${p.id}`)] },
    { pattern: "/bedrock/agents", component: Agents, crumbs: () => [...top, c("Agents", "#/bedrock/agents")] },
    { pattern: "/bedrock/agents/:id", component: AgentDetail, crumbs: (p) => [...top, c("Agents", "#/bedrock/agents"), c(p.id, `#/bedrock/agents/${p.id}`)] },
    { pattern: "/bedrock/agentcore", component: AgentCore, crumbs: () => [...top, c("AgentCore", "#/bedrock/agentcore")] },
    { pattern: "/bedrock/agentcore/gateways/:id", component: GatewayDetail, crumbs: (p) => [...top, c("AgentCore", "#/bedrock/agentcore"), c(p.id, `#/bedrock/agentcore/gateways/${p.id}`)] },
  ].map(withHelp),
};
