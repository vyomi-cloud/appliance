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
import { Guardrails, GuardrailDetail } from "./buildpages/Guardrails.jsx";
import { Prompts, PromptDetail } from "./buildpages/Prompts.jsx";
import { Flows, FlowDetail } from "./buildpages/Flows.jsx";
import { Evaluations, EvaluationDetail, ModelAccess, Settings, PromptOptimization } from "./buildpages/Assess.jsx";
import { AutomatedReasoning } from "./buildpages/OutOfScope.jsx";
import DataAutomation from "./buildpages/DataAutomation.jsx";
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
    // lane uiaws: Build / Assess / Configure pages on core/bedrock_build_core.py + core/bedrock_guardrails_core.py
    { pattern: "/bedrock/guardrails", component: Guardrails, crumbs: () => [...top, c("Guardrails", "#/bedrock/guardrails")] },
    { pattern: "/bedrock/guardrails/:id", component: GuardrailDetail, crumbs: (p) => [...top, c("Guardrails", "#/bedrock/guardrails"), c(p.id, `#/bedrock/guardrails/${p.id}`)] },
    { pattern: "/bedrock/prompt-management", component: Prompts, crumbs: () => [...top, c("Prompt management", "#/bedrock/prompt-management")] },
    { pattern: "/bedrock/prompt-management/:id", component: PromptDetail, crumbs: (p) => [...top, c("Prompt management", "#/bedrock/prompt-management"), c(p.id, `#/bedrock/prompt-management/${p.id}`)] },
    { pattern: "/bedrock/flows", component: Flows, crumbs: () => [...top, c("Flows", "#/bedrock/flows")] },
    { pattern: "/bedrock/flows/:id", component: FlowDetail, crumbs: (p) => [...top, c("Flows", "#/bedrock/flows"), c(p.id, `#/bedrock/flows/${p.id}`)] },
    { pattern: "/bedrock/evaluations", component: Evaluations, crumbs: () => [...top, c("Model evaluations", "#/bedrock/evaluations")] },
    { pattern: "/bedrock/evaluations/:id", component: EvaluationDetail, crumbs: (p) => [...top, c("Model evaluations", "#/bedrock/evaluations"), c(p.id, `#/bedrock/evaluations/${p.id}`)] },
    { pattern: "/bedrock/model-access", component: ModelAccess, crumbs: () => [...top, c("Model access", "#/bedrock/model-access")] },
    { pattern: "/bedrock/settings", component: Settings, crumbs: () => [...top, c("Settings", "#/bedrock/settings")] },
    { pattern: "/bedrock/prompt-optimization", component: PromptOptimization, crumbs: () => [...top, c("Advanced prompt optimization", "#/bedrock/prompt-optimization")] },
    { pattern: "/bedrock/automated-reasoning", component: AutomatedReasoning, crumbs: () => [...top, c("Automated Reasoning", "#/bedrock/automated-reasoning")] },
    { pattern: "/bedrock/data-automation", component: DataAutomation, crumbs: () => [...top, c("Data Automation", "#/bedrock/data-automation")] },
  ].map(withHelp),
};
