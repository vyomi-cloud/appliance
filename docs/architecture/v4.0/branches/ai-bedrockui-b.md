# ai-bedrockui-b: AWS Bedrock console pages 011-016 (Infer + Tune)

- Owner: AI session (round 2). Base: local `v4/ai-integration` (6c5b5536c). Branch: `v4/ai-bedrockui-b`.
- Purpose: match the real Bedrock console for inference profiles (System-defined/Application), batch inference, Provisioned Throughput, custom models (Models/Jobs), prompt routers (Configured/Default) and marketplace deployments, backed by real Bedrock control-plane APIs. Spec: `console-captures/aws/live/B-bedrock/` 011-016. Nav entries come from lane A's `nav.js`; this lane only adds routes (`inferTune/routes.jsx`, one spread in `index.jsx`).

## Backend (core/bedrock_ctl_core.py, mirrored to wasm/core, hooked in aws_wire_router before the agents core)
| API | OSS / engine | Substrate | Declared limit |
|---|---|---|---|
| ListInferenceProfiles (type=SYSTEM_DEFINED/APPLICATION), Get/Create/DeleteInferenceProfile | model aliases of core/ai_models_core (us/eu/apac, per-region model ARNs) | Nano + Mesh | Application profiles resolve in Converse/InvokeModel to their source model |
| CreateModelInvocationJob, Get/List/Stop | local-LLM seam (core/llm_core) over S3 JSONL (s3_object_core) | Nano (WebLLM) + Mesh (llama.cpp) | synchronous, max 25 records/job; no LLM backend => job Failed with message |
| Provisioned throughput CRUD | none (metadata) | both | no capacity reserved, nothing billed; custom-model ARNs accepted |
| ModelCustomizationJob + Custom models | none (metadata) | both | NO training: job completes ~2 s after submit and registers a custom model; invocation uses the base model alias |
| Prompt routers (2 defaults + custom CRUD) | none (metadata) | both | Converse on a router ARN answers with the second (larger) model; no real quality routing |
| Marketplace model endpoints + Register/Deregister | none (metadata) | both | no SageMaker endpoint is created |
Hand-built code is the thin wire adapter only; no OSS engine exists for these control-plane metadata records. State is process-local.

## UI (consoles/src/aws/services/bedrock/inferTune/)
Cloudscape pages with the real "How it works" card, tabs, tables/columns, empty states and Actions; create flows are modals that call the real API (inline modeled errors). Nano boot lists (nano-boot.js, relay-shared-worker.js, nano-endpoint.html, build_cores.py) gained `bedrock_ctl_core.py`.

## Match vs captures (our shots: scratchpad/shots-bedrockui-b/)
- Close: 014 custom models (+jobs), 015 prompt routers (+default), 016 marketplace, 012 batch, 013 provisioned (overview stats, columns, empty state).
- Approximate: 011 inference profiles (33 profiles vs 58 in the real EU view, columns overflow horizontally, no per-column filter toggles, no illustrated icons in How it works); default router models show model ids not friendly names; no illustrations (dog artwork, How-it-works icons).

## Tests
- `PYTHONPATH=. python tests/conformance/test_bedrock_ctl.py` (real boto3): 24 PASS (profiles, batch over S3, provisioned, customization lifecycle, routers, marketplace, converse via app-profile and router ARN).
- `consoles/tests/smoke-aws-bedrock-infer-tune.mjs` on the Nano preview: 7/7 PASS.
- test_local_llm_seam.py has 3 pre-existing FAILs on the integration base (unchanged).

## Open
- wasm/v4/aws bundle not committed (orchestrator rebuilds). Detail pages for jobs/models/routers are not built (names are plain text).
