# v4/ai-gcpui: GCP console Agent Platform (Vertex AI) section

Owner: AI session (round 2 gap lane). Base: v4/ai-integration (61433968b). Spec: `console-captures/gcp/live/B-agent-platform/` (001/003 overview, 004 studio, 005 models, 006 agents, 008 tutorials, 017 gemini model page).

## What changed (consoles/src/gcp)
- Product renamed "Agent Platform" (registry title; route id stays `vertex-ai`).
- `App.jsx` (shared shell, additive): `nav` may be a function of the route; nav entries support `back`, `button`, collapsible `section`, `chevron`, `pinned` (Tutorials). Other products unaffected.
- Route-dependent nav like the real console: top (Overview, Studio, Models>, Agents>, Notebooks>, Tutorials); Models drill-in (Model Garden, Tuning, Evaluation, Model Registry, Endpoints, Batch Inference, Provisioned Throughput; Partner services; More services); Agents drill-in (New agent, Build/Scale/Govern/Optimize groups); Studio has no product nav, its own rail.
- New pages: Overview (welcome, genai snippet, Features/Build/Scale/Govern/Optimize cards, plus resource counts), Agent Studio landing (prompt box answered through generateContent, Models/Agents toggle, rail; the old freeform/chat/embeddings tool stays at `/studio/prompt`), Model Garden (collections/tasks/providers/features rail, search, grid/list, sort, Serverless/Self-deployed chips, Made by Google / partners / Open sections), model detail (Latest/Overview/Documentation, Model ID, Version, Tags), Agent Garden (11 blueprints, use-case/tool/capability filters), Tutorials, Deployments (Agent Engine `reasoningEngines` list over the real aiplatform REST wire).
- Breadcrumbs on the new pages.

## Backing (thumb rule: no new backends)
Publisher models: `/v1/publishers/-/models` (gcp_vertex_core + ai_models catalogue). Prompts: `generateContent` (llm seam). Deployments: `reasoningEngines` (gcp_agentengine_core). Resources counts and all legacy pages: existing aiplatform REST. Adapters are thin UI only.

## Fidelity vs captures
Close: nav grouping/order, Model Garden layout, model detail, Agent Garden, Studio landing, Tutorials, Overview top section. Approximate: Overview lower cards, Tutorials (no thumbnails), Model Garden counts (our ten-model catalogue, not Google's 128), no "What's new" strip (Google news, not ours).
Deliberately omitted: "Enable billing" / free-trial banners (account state, not simulated).
Not simulated (nav entries route to the honest NotSimulated page): Evaluation, Provisioned Throughput, Claude models, Ray, Metadata, Monitoring, ADK, MCP Servers, RAG Engine, Search, Agent Retrieval, Memory Bank, Sessions, Agent Registry, Policies, Gateways, Security, Topology, App builder, Training Clusters.
No capture to verify against (kept as-is): Endpoints, Model Registry, Datasets, Training, Pipelines, Batch, Vector Search, Feature Store, Experiments, Workbench (Notebooks capture 007 is a billing-gate page).
RAG Studio equivalent: skipped (not trivial; needs engine wiring beyond a thin adapter).

## Tests
`consoles/tests/smoke-gcp-vertex-pages.mjs` updated to the new nav/headings and extended (drill-in nav, model detail tabs, Agent Garden filter, Studio landing); 28 checks PASS against dev_server. Deploy-from-Model-Garden is no longer exercised: the ten-model catalogue exposes no deploy action (stale before this lane); the test seeds the endpoint through the wire.
Screenshots: scratchpad `shots-gcpui/`. Bundle `wasm/v4/gcp` not committed (orchestrator rebuilds).
