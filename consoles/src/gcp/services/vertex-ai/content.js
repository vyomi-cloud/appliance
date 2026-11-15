/* Static editorial content of the Agent Platform pages: Agent Garden blueprints, tutorials and Overview copy, as the
 * native console shows them (captures 003/006/008). Blueprints are catalogue entries; nothing here is a running resource. */
export const GARDEN = [
  ["Financial Advisor", "ADK", "Python", "Assists human financial advisors by providing educational content about topics related to finance and investments.", "Finance", ["Gemini"]],
  ["Deep Search", "ADK", "Python", "A production-ready blueprint for building sophisticated, fullstack research agents with Gemini that leverage complex agentic workflows, modular design, and Human-in-the-Loop steps.", "Research", ["Gemini", "Human-in-the-Loop"]],
  ["Small Business Loans", "ADK", "Python", "Automating loan origination from intake to final decision, this agent sample leverages specialized sub-agents to extract document data, underwrite applications, and calculate risk-based pricing, all secured by human-in-the-loop approvals.", "Finance", ["Human-in-the-Loop", "Multi-Agent Orchestration"]],
  ["Software Bug Assistant", "ADK", "Java", "Assists in software bug resolution for a coffee machine company, QuantumRoast. This agent queries internal ticketing systems (Cloud SQL, MCP Toolbox for Databases) and crowdsourced knowledge (Google Search). Identifies similar reported issues and surfaces relevant diagnostic information to accelerate troubleshooting for IT support and developers.", "Engineering", ["Google Search", "MCP", "Database"]],
  ["Time Series Forecasting", "ADK", "Java", "Automates time-series forecasting by leveraging BigQuery ML (BQML) with the MCP Toolbox for Databases. Provides clear, explained predictions to support data-driven business decisions.", "Engineering", ["BigQuery", "BQML", "MCP", "Forecasting", "Time Series Analysis"]],
  ["LLM Auditor", "ADK", "Python", "Evaluates LLM-generated answers, verifies actual accuracy using the web, and refines the response to ensure alignment with real-world knowledge.", "Other", ["Google Search", "LLM-as-Judge", "Self Correction"]],
  ["FOMC Research", "ADK", "Python", "Extracts web data, analyzes complex topics with limited input, executes custom functions, and generates summary reports from multi-modal data comparisons.", "Research", ["Google Search", "Report generation", "Summarization"]],
  ["GenMedia for Commerce", "ADK", "Python", "A production-ready solution for generating high-quality retail media, including Virtual Try-On (VTO) videos and 360° product spins, using Gemini and Veo.", "Other", ["Veo", "Gemini", "Virtual Try-On", "360 Product Spin", "Media Generation"]],
  ["High-Volume Document Analyzer", "ADK", "Python", "Securely analyzing massive document collections, this agent bypasses standard AI limits. It processes hundreds of restricted files in batches, allowing enterprises to audit sensitive data without moving it.", "Search & RAG", ["RAG", "Gemini"]],
  ["Brand-Aligned Research & Presentations", "ADK", "Python", "Transforming topics into production-ready presentations, this system automates end-to-end deck generation while strictly adhering to corporate brand guidelines. It seamlessly blends deep external research with internal knowledge to empower sales, marketing, and consulting teams", "Other", ["Google Search", "Report generation"]],
  ["On-Brand GenMedia", "ADK", "Python", "Operating as an intelligent creative studio, this modular pipeline generates, evaluates, and autonomously refines digital media. It ensures all marketing-ready assets strictly align with your corporate visual identity through dynamic self-correction.", "Other", ["Image Generation", "Self Correction", "Media Generation"]],
].map(([title, fw, lang, desc, useCase, tags]) => ({ title, fw, lang, desc, useCase, tags }));

export const USE_CASES = ["Finance", "Research", "Engineering", "Search & RAG", "Other"];
export const TOOLS = ["Google Search", "Java", "MCP", "Database", "API Integration", "BigQuery", "BQML", "Veo", "Gemini"];
export const CAPS = ["RAG", "Human-in-the-Loop", "Forecasting", "Time Series Analysis", "Video Analysis", "Summarization", "Report generation", "Virtual Try-On", "360 Product Spin", "Media Generation", "Image Generation", "Self Correction", "Multi-Agent Orchestration", "LLM-as-Judge"];

export const TUTORIAL_VIDEOS = [["What is Gemini Enterprise Agent Platform?", "9 min"], ["ADK tutorial", "20 min"], ["Build agents on Google Cloud", "30 min"], ["Evaluate Gemma 2 with the generative AI evaluation service", "10 min"], ["Get started with Gemma 3 on Vertex AI", "20 min"]];
export const TUTORIAL_DOCS = [
  ["ADK documentation", "Build agents using ADK framework", "60 min"], ["Agent Engine Quickstart", "Create and deploy an example agent", "30 min"],
  ["Deploy an Agent", "Learn how to deploy an agent in Vertex AI Agent Engine", "20 min"],
  ["Deploy Gemma and make predictions", "This documentation covers deploying and running inference with Gemma using Model Garden and Vertex AI GPU-backed endpoints.", "10 min"],
  ["Deploy open models using Python SDK, CLI, REST API, or console", "This documentation covers deploying a model by using its model card in the Google Cloud console or programmatically.", "20 min"],
  ["Deploy and serve a HuggingFace model", "This documentation covers using Hugging Face models in Model Garden.", "10 min"],
  ["Use vLLM to serve text-only and multimodal models on GPUs", "This documentation covers vLLM serving for text-only and multimodal language models on Cloud GPUs.", "40 min"],
  ["Vertex AI Agent Builder", "Overview of products offered by Google Cloud that support a full agent development lifecycle", "20 min"],
];

export const OVERVIEW_GROUPS = [
  ["Features", [["Studio", "Use the latest models to build and evaluate agents and applications.", "#/vertex-ai/studio"], ["Notebooks", "Use Colab Enterprise or Workbench to access the full Agent Platform.", "#/vertex-ai/workbench"], ["Model Garden", "A single place to discover, customize, and deploy a wide variety of models.", "#/vertex-ai/model-garden"], ["Tuning", "Refine and adapt foundation models using your specific domain data.", "#/vertex-ai/training?tab=tuning"], ["Training Clusters", "Scalable GPU/TPU infrastructure for high performance ML workloads.", "#/vertex-ai/training-clusters"], ["Provisioned Throughput", "Dedicated throughput for your critical workloads.", "#/vertex-ai/provisioned-throughput"]]],
  ["Build", [["Agent Garden", "Pre-built agent library", "#/vertex-ai/agent-garden"], ["ADK", "Agent developer toolkit", "#/vertex-ai/adk"], ["MCP Servers", "External agent capabilities", "#/vertex-ai/mcp-servers"]]],
  ["Scale", [["Deployments", "Agent execution engine", "#/vertex-ai/deployments"], ["Memory Bank", "Long-term agent context", "#/vertex-ai/memory-bank"], ["Sessions", "Active interaction state", "#/vertex-ai/sessions"]]],
  ["Govern", [["Agent Registry", "Central agent catalog", "#/vertex-ai/agent-registry"], ["Policies", "Guardrails and Rules", "#/vertex-ai/policies"], ["Gateways", "Access and traffic control", "#/vertex-ai/gateways"], ["Security", "Data and identity protection", "#/vertex-ai/security"], ["Topology", "Workflow and logic mapping", "#/vertex-ai/topology"]]],
  ["Optimize", [["Evaluation", "Logic and accuracy testing", "#/vertex-ai/evaluation"]]],
];
