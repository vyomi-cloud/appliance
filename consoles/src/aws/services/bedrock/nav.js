/* Amazon Bedrock side navigation in the order/grouping of the real console (captures B-bedrock 001/004). */
import { createElement as h } from "react";
import Badge from "@cloudscape-design/components/badge";
const NEW = { info: h(Badge, { color: "blue" }, "New") };
const l = (text, href, extra = {}) => ({ type: "link", text, href, ...extra });
export const bedrockNav = [
  { type: "section", text: "Discover", defaultExpanded: true, items: [
    l("Overview", "#/bedrock"), l("Quickstart", "#/bedrock/quickstart", NEW), l("Model catalog", "#/bedrock/models"), l("API keys", "#/bedrock/api-keys"),
  ] },
  { type: "section", text: "Labs", defaultExpanded: true, items: [l("Quotas", "#/bedrock/quotas", NEW), l("Compare models", "#/bedrock/compare-models", NEW)] },
  { type: "section", text: "Test", defaultExpanded: true, items: [l("Playground", "#/bedrock/playground"), l("Tokenizer", "#/bedrock/tokenizer")] },
  { type: "section", text: "Infer", defaultExpanded: true, items: [l("Inference profiles", "#/bedrock/inference-profiles"), l("Batch inference", "#/bedrock/batch-inference"), l("Provisioned Throughput", "#/bedrock/provisioned-throughput")] },
  { type: "section", text: "Tune", defaultExpanded: true, items: [l("Custom models", "#/bedrock/custom-models"), l("Prompt router models", "#/bedrock/prompt-routers"), l("Marketplace model deployments", "#/bedrock/marketplace-deployments")] },
  { type: "section", text: "Build", defaultExpanded: true, items: [
    l("AgentCore", "#/bedrock/agentcore"), l("Knowledge Bases (KB)", "#/bedrock/knowledge-bases"), l("RAG Studio", "#/bedrock/knowledge-bases/studio"), l("Flows", "#/bedrock/flows"),
    l("Automated Reasoning", "#/bedrock/automated-reasoning"), l("Guardrails", "#/bedrock/guardrails"), l("Prompt Management", "#/bedrock/prompt-management"),
    l("Advanced Prompt Optimization", "#/bedrock/prompt-optimization", NEW), l("Data Automation", "#/bedrock/data-automation"), l("Agents (classic)", "#/bedrock/agents"),
  ] },
  { type: "section", text: "Assess", defaultExpanded: true, items: [l("Evaluations", "#/bedrock/evaluations")] },
  { type: "section", text: "Configure and learn", defaultExpanded: true, items: [
    l("Settings", "#/bedrock/settings", NEW), l("Model access", "#/bedrock/model-access"),
    { type: "link", text: "User guide", href: "https://docs.aws.amazon.com/bedrock/latest/userguide/", external: true },
    { type: "link", text: "Bedrock Service Terms", href: "https://aws.amazon.com/service-terms/", external: true },
  ] },
];
