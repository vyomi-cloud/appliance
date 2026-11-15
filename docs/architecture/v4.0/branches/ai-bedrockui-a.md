# ai-bedrockui-a: AWS Bedrock console pages 001-010

- Owner: AI session (round 2). Base: local `v4/ai-integration` (61433968b). Branch: `v4/ai-bedrockui-a`.
- Purpose: make the AWS console Bedrock section match the real console captures (`console-captures/aws/live/B-bedrock/` 001-010).
- Sibling lane `bedrockui-b` owns 011-016; `nav.js` already lists their hrefs (inference-profiles, batch-inference, provisioned-throughput, custom-models, prompt-routers, marketplace-deployments), so they only add routes.

## Pages (consoles/src/aws/services/bedrock/)
| Page | File | Backing API | Match |
|---|---|---|---|
| Side nav (Discover/Labs/Test/Infer/Tune/Build/Assess/Configure, New badges) | nav.js | n/a | close (RAG Studio kept under Build; no Info header) |
| 001/002 Overview | Landing.jsx (+LocalModel in Overview.jsx) | ListFoundationModels | close (no marketing artwork, 3-item spotlight carousel) |
| 004 Quickstart | Quickstart.jsx | n/a (samples for Converse/Invoke) | close |
| 005 Model catalog | Models.jsx | ListFoundationModels | approximate (capture was a spinner; no real spec) |
| 006 API keys (+long-term tab) | ApiKeys.jsx | IAM CreateUser/CreateServiceSpecificCredential(bedrock.amazonaws.com)/List/Update/Reset/Delete | close |
| 007 Quotas | Quotas.jsx | ListFoundationModels | approximate (TPM/RPM "Not enforced"; no Service Quotas engine) |
| 008 Compare models | Compare.jsx | ListFoundationModels | approximate (card layout; pool models, not Anthropic) |
| 009 Playground | Playground.jsx | Converse | close empty state; chat+config panel simplified |
| 010 Tokenizer | Tokenizer.jsx | CountTokens (new) | close |

## Core changes (thin adapters, no new engines)
- `core/ai_models_core.py`: `POST /model/{id}/count-tokens` (Bedrock CountTokens) using `llm_core.estimate_tokens` (~4 chars/token, same heuristic as the seam).
- `core/iam_core.py`: `CredentialAgeDays` on CreateServiceSpecificCredential -> `ExpirationDate` (existing IAM service-specific credentials engine backs Bedrock API keys).
- wasm/core mirror regenerated (`wasm/build_cores.py`).
- Nano boot fix: `wasm/nano-boot.js` and `wasm/relay/relay-shared-worker.js` CORES lists lacked cloudtrail_events_core, agent_spec_core, agentcore_eval_core, agentcore_ext_core, agentcore_runtime_host, gcp_agentengine_core, identity_core, otel_bridge, xray_admin_core: IAM (and any router path) 500'd with ImportError on Nano. Added them (integration-wide issue, `build_cores.py` check did not catch it).

## OSS / thumb rule
No new backend. API keys reuse IAM core; token count reuses llm_core; model data reuses ai_models_core. Both substrates (Nano Pyodide, Mesh container).

## Tests
`consoles/tests/smoke-aws-bedrockui-a.mjs` (Nano preview, 9/9). `smoke-aws-bedrock.mjs` selectors updated for the new Overview/Playground.

## Declared limits
- Short-term API key is a client-generated `bedrock-api-key-` token; the simulator does not verify bearer tokens.
- Responses (OpenAI-compatible) endpoint is not simulated (Quickstart says so).
- Quotas have no enforcement or increase workflow. Compare shows pool models.
- Not built here: Flows, Guardrails UI, Prompt Management, Evaluations, Settings, Model access (nav links fall to "not simulated").
- Build gotcha: `consoles/node_modules` needs `@xyflow/react` and `umap-js` (RAG Studio) to build.
