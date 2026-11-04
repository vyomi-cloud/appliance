import Overview from "./Overview.jsx";
import Playground from "./Playground.jsx";
import Models from "./Models.jsx";
import { KnowledgeBases, KnowledgeBaseDetail } from "./KnowledgeBases.jsx";
import { Agents, AgentDetail } from "./Agents.jsx";
import { AgentCore, GatewayDetail } from "./AgentCore.jsx";

const top = [{ text: "Amazon Bedrock", href: "#/bedrock" }];
const c = (text, h) => ({ text, href: h });

export default {
  nav: [
    { type: "link", text: "Overview", href: "#/bedrock" },
    { type: "section", text: "Test", items: [
      { type: "link", text: "Chat / text playground", href: "#/bedrock/playground" },
    ] },
    { type: "section", text: "Discover", items: [
      { type: "link", text: "Model catalog", href: "#/bedrock/models" },
    ] },
    { type: "section", text: "Build", items: [
      { type: "link", text: "Knowledge bases", href: "#/bedrock/knowledge-bases" },
      { type: "link", text: "Agents", href: "#/bedrock/agents" },
    ] },
    { type: "section", text: "AgentCore", items: [
      { type: "link", text: "Gateways and runtimes", href: "#/bedrock/agentcore" },
    ] },
  ],
  routes: [
    { pattern: "/bedrock", component: Overview, crumbs: () => top },
    { pattern: "/bedrock/playground", component: Playground, crumbs: () => [...top, c("Playground", "#/bedrock/playground")] },
    { pattern: "/bedrock/models", component: Models, crumbs: () => [...top, c("Model catalog", "#/bedrock/models")] },
    { pattern: "/bedrock/knowledge-bases", component: KnowledgeBases, crumbs: () => [...top, c("Knowledge bases", "#/bedrock/knowledge-bases")] },
    { pattern: "/bedrock/knowledge-bases/:id", component: KnowledgeBaseDetail, crumbs: (p) => [...top, c("Knowledge bases", "#/bedrock/knowledge-bases"), c(p.id, `#/bedrock/knowledge-bases/${p.id}`)] },
    { pattern: "/bedrock/agents", component: Agents, crumbs: () => [...top, c("Agents", "#/bedrock/agents")] },
    { pattern: "/bedrock/agents/:id", component: AgentDetail, crumbs: (p) => [...top, c("Agents", "#/bedrock/agents"), c(p.id, `#/bedrock/agents/${p.id}`)] },
    { pattern: "/bedrock/agentcore", component: AgentCore, crumbs: () => [...top, c("AgentCore", "#/bedrock/agentcore")] },
    { pattern: "/bedrock/agentcore/gateways/:id", component: GatewayDetail, crumbs: (p) => [...top, c("AgentCore", "#/bedrock/agentcore"), c(p.id, `#/bedrock/agentcore/gateways/${p.id}`)] },
  ],
};
