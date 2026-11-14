# Enterprise agentic AI on Mesh: plan to 100% conformance with the reference architecture

Status: PLAN (2026-11-14). Nothing is built by this document. Source of the target: the owner's reference architecture
"Building Agentic AI Solution on AWS Bedrock" (`~/Desktop/AI_E2E_Flow.jpeg`, 11 numbered blocks + governance row).
Current-state facts below were read from code at `origin/v4-on-main` (c0504fbce / 96b140bf7); they are NOT verified with real
SDK round trips. Phase 0 exists to replace every "read from code" claim with a measured one.

## 1. Goal and what "100% conformance" means

Goal: any developer can build, run and test a production-shaped enterprise agent application on a Mesh session using the
NATIVE SDKs and IaC of Bedrock / Vertex AI / Azure AI, with the same architecture as the reference, and later deploy the same
code to the real cloud unchanged.

Definition (proposed, needs owner sign-off):

1. A **reference application** (the Facilities agent from the diagram) exists as real code: IaC (CDK or Terraform, plus
   SAM for Lambdas), a Strands and a LangGraph agent, Lambda tools, Step Functions approval workflow, a RAG ingestion pipeline,
   a web/API channel. It is written ONLY against native SDKs/APIs (no Vyomi-specific calls).
2. It deploys and runs end to end on a Mesh session by changing only endpoint/credentials configuration.
3. Every one of the 11 blocks (+ governance) has a conformance row: the SDK calls the real service offers for that block, with
   assertions on wire shape, error codes and state transitions, plus the console actions that exist for it.
4. The same scenario then exists for GCP (Vertex) and Azure (Foundry) equivalents.

Explicit non-goal: model QUALITY. Mesh runs a small local model (decision 2026-11-07: Qwen2.5-3B Q4 on native llama.cpp; the
Codespace is 8 GB RAM, not 32). Conformance means wire/semantic fidelity and correct control flow, not answer quality. Every
page and test must say so (see `llm_core.HONEST_LIMIT`). Where a block needs a capability a 3B model cannot supply reliably
(supervisor routing, multi-tool plans), the harness offers a deterministic/scripted backend so the application logic is still
testable.

## 2. Reference architecture mapped to Mesh services

State: SERVED = code exists and is routed (unverified with SDK), PARTIAL, MISSING. Cloud analogues in the last column.

| # | Block | AWS pieces | State today | GCP / Azure analogue |
|---|---|---|---|---|
| 1 | Access and perimeter security | Cognito (user pools, JWT), API Gateway (+Cognito/JWT authorizer), WAF | API GW SERVED (apigateway*_core, gateway data plane); Cognito only as an authorizer reference, **no user-pool service**; **no WAFv2** | GCP: Identity Platform + API Gateway + Cloud Armor; Azure: Entra External ID + APIM + Front Door WAF |
| 2 | Channels and interface | Web/mobile/chatbot/API, input guardrails, approver inbox | App side (reference app). Guardrails SERVED (`bedrock_guardrails_core`, Dev Simplified); SNS/SES for notifications SERVED | Vertex safety settings, Azure Content Safety / Prompt Shields (MISSING) |
| 3 | AgentCore Runtime (supervisor + sub-agents, harness, Strands/LangGraph) | AgentCore Runtime | Control plane SERVED; InvokeAgentRuntime runs a declarative **agent spec** in-process (`agent_spec_core`), **no real container/framework code runs**; no multi-agent collaboration; harness limits (step/token/cost budgets, checkpoints, kill switch) MISSING | Vertex Agent Engine (reasoningEngines: spec-based, `gcp_agentengine_core`); Azure Foundry Agent Service (`azure_openai_agents_core`, assistants-style, PARTIAL) |
| 4 | AgentCore Gateway | OBO identity, central policy on every tool call, tool catalog, schema validation, throttling, audit | Gateway control plane + MCP tools/list/call for Lambda targets SERVED; openApi/smithy/mcpServer targets registered but not callable; **no identity propagation, no policy engine, no audit trail** | GCP: Apigee/API Gateway + MCP; Azure: APIM AI gateway |
| 5 | Actions and approval | Risk classification, preview, durable approval (Step Functions), DynamoDB ledger, idempotency, rollback | Step Functions SERVED (`stepfunctions_core`), DynamoDB SERVED; `.waitForTaskToken`/SendTaskSuccess, Map/Choice depth, SLA timers: **unverified**; two-approver and compensation patterns are application code | Workflows (GCP), Logic Apps/Durable Functions (Azure) |
| 6 | Knowledge search layer (RAG) | OpenSearch (Serverless) vector + BM25 hybrid, metadata + access-aware filtering, Bedrock reranker | KB ingestion, Retrieve, RetrieveAndGenerate SERVED with an in-account exact-cosine index; **no OpenSearch/AOSS API, no BM25/hybrid, no Rerank API**; PDF/Office not ingested | GCP: Vertex Vector Search SERVED (brute force), RAG Engine **MISSING** (`ragCorpora`); Azure: AI Search vector SERVED, semantic ranker MISSING |
| 7 | Tools (Lambda) | Read-only search tools, approval-gated write tools, IoT/asset telemetry | Lambda SERVED (real invocation), DynamoDB SERVED; telemetry store (IoT Core/Timestream) MISSING | Cloud Functions/Run, Azure Functions |
| 8 | AgentOps and observability | Lifecycle (evals, CI gates, versioning, pinning, canary), traces/metrics/logs | CloudWatch + X-Ray SERVED (not checked for GenAI metrics); `mesh_ai` usage ledger exists; Bedrock evaluation jobs, model invocation logging, prompt management/versions, AgentCore Observability MISSING | Vertex evaluation, Cloud Trace; Azure Foundry evaluations, App Insights |
| 9 | AgentCore Memory | Short-term (session events), long-term (strategies), TTL, tenant scoping, poisoning checks | **MISSING** (no Memory API at all) | Vertex Agent Engine Memory Bank; Foundry thread/agent memory |
| 10 | Foundation models via Bedrock | Claude/Nova, model router, fallback | Catalog + Converse/Invoke/Stream SERVED; tool use added (`toolConfig`/`toolUse` handled in `ai_models_core`); ONE local model answers every model id; inference-profile list/get, prompt router, fallback routing MISSING | Vertex model garden, Azure deployments (SERVED control plane) |
| 11 | Response generation | Grounded answer + citations, grounding check, PII redaction, policy filter | Citations from RetrieveAndGenerate SERVED; PII/word/topic filters SERVED; **contextual grounding rejected today** | Vertex grounding check; Azure groundedness detection |
| KP | Knowledge processing pipeline (event driven) | S3 -> extraction + guardrails scan -> chunk -> embed -> vector DB | S3, EventBridge/SQS/SNS, Lambda, embeddings SERVED individually; the **wired pipeline** (S3 event -> Lambda/Step Functions -> KB ingest -> index) is untested; Textract-style extraction MISSING | GCS + Eventarc + Document AI; Blob + Event Grid + Document Intelligence |
| G | Governance (IAM, KMS, CloudTrail, guardrails, data governance, policy, cost) | | IAM, KMS, Guardrails, Cost Explorer, `mesh_ai` ledger SERVED; **CloudTrail API (trails, LookupEvents) MISSING**; data lineage/quality MISSING; Cedar-style policy engine MISSING | Cloud Audit Logs, Azure Activity Log/Purview |

Net: model invocation, KB/RAG basics, guardrails, Lambda/Step Functions/DynamoDB, API Gateway already exist. The big absences are
(a) real agent runtime execution, (b) Memory, (c) Cognito + WAF, (d) OpenSearch-compatible vector/hybrid/rerank, (e) gateway
policy/identity/audit, (f) CloudTrail, (g) AgentOps (evals, prompt management, routing).

## 3. Constraints that shape the design

- **Mesh = Codespace, 8 GB RAM, 2 cores, no GPU** (decision 2026-11-07). A real OpenSearch, Keycloak, etc. will not fit next to a
  3B model. Rule: **wire-compatible lightweight engines, not the real products** (same principle as the rest of Vyomi).
  Vector/hybrid search = in-process engine (HNSW + BM25) behind OpenSearch/AOSS, Vertex and AI Search wires.
- Mesh has real Docker, so unlike Nano it CAN run the user's agent container (Strands/LangGraph code) for AgentCore Runtime.
  This is the single biggest fidelity win and the main memory consumer; budget it explicitly (`mesh.allocate`).
- CPU inference: agent loops are slow (5-30 s/step on 3B). Prompt caching, one slot, queue + cloud-correct throttling.
- Honest limits everywhere; never a canned answer (existing rule in `llm_core`).
- "One shared engine, per-cloud wires" (playbook): build each capability once (memory, policy, RAG, approvals, evals) and expose
  it through the AWS, GCP and Azure wires in parallel lanes.

## 4. Work packages

### Phase 0: baseline and reference app (1-1.5 weeks, gates everything)
- P0.1 Write the reference app (AWS flavour first) against native SDKs; keep it in `examples/enterprise-agent/`.
- P0.2 Run it on a Mesh session; record every failure; turn the matrix in section 2 into measured pass/fail per SDK call.
- P0.3 Re-verify the AI-PACK-AUDIT items (tool calls, streaming) with real boto3 / google-genai / openai SDKs.
- P0.4 Fix the conformance rubric and the "honest limit" wording with the owner.

### Phase 1: shared foundations (2 weeks)
- F1 Seam: real upstream streaming, request queue + per-cloud 429/ThrottlingException, context-overflow errors, 2-model router
  (small/fast vs default) with fallback, prompt-cache reuse, usage events -> `mesh_ai` ledger -> CloudWatch/Monitor metrics.
- F2 **Memory engine** (new, shared): short-term event log per session/actor, long-term strategies (semantic, summary, user
  preference) using the embedding model, TTL, tenant scoping, poisoning checks (provenance + write validation).
- F3 **Retrieval engine** (shared): HNSW + BM25 hybrid, metadata filters, ACL-aware filtering, reranker (cross-encoder small
  model or lexical+embedding blend, labelled), PDF/Office extraction.
- F4 **Policy engine** (shared): Cedar-lite evaluation for gateway tool calls (identity, RBAC/ABAC attributes), decision log.
- F5 **Approval/ledger library** patterns (idempotency keys, rollback, two-approver) as tested Step Functions + DynamoDB
  reference definitions (application code, but proven on the simulator).
- F6 Guardrails v2: contextual grounding check, stronger prompt-attack detection (still labelled Dev Simplified), shared by all clouds.
- F7 Mesh packaging: AI profile (which backends start), RAM admission via `mesh.allocate("ai")`, model download/boot UX, status chip.

### Phase 2: AWS lane (4-5 weeks, after F1-F4)
- A1 Cognito user pools (users, groups, app clients, JWKS, token endpoints, hosted flows minimal) + API GW Cognito/JWT authorizer.
- A2 WAFv2 (web ACLs, managed + custom + rate-based rules, associations, evaluated in front of the gateway data plane).
- A3 AgentCore Runtime: run the user's agent container on Mesh compute (Strands/LangGraph), session isolation, harness limits
  (step/token/cost budgets, timeouts, kill switch), checkpoints.
- A4 AgentCore Gateway: openApi/smithy/mcpServer/Lambda targets all callable, OBO identity propagation, policy check on every
  call (F4), schema validation, throttling, audit events.
- A5 AgentCore Memory + Identity + Observability APIs on F2.
- A6 Bedrock: Rerank API, KB with OpenSearch-Serverless store type, multi-agent collaboration, returnControl, InvokeInlineAgent,
  inference profiles list/get, prompt router, prompt management + versions, model invocation logging, evaluation jobs.
- A7 OpenSearch Serverless / OpenSearch Service wire (collections, policies, index/query/knn/hybrid) over F3.
- A8 CloudTrail (trails, LookupEvents, event history of all simulator calls) and CloudWatch GenAI metrics/dashboards/alarms.
- A9 Step Functions durable approvals verification and fixes (`waitForTaskToken`, heartbeat, Map, SLA timers).
- A10 Textract/Comprehend-class extraction stubs only if the pipeline needs them (decide after P0).

### Phase 3: GCP lane (parallel to Phase 2, 3-4 weeks)
Vertex: Agent Engine running real containers/ADK, Memory Bank, RAG Engine (`ragCorpora`, import, retrieveContexts), grounding
check, safety settings/ratings, Gemini Developer API alias, Identity Platform, Cloud Armor, Cloud Audit Logs, evaluation, Eventarc
pipeline.

### Phase 4: Azure lane (parallel, 3-4 weeks)
Foundry Agent Service + Assistants + `/responses` + threads/runs/tool outputs, unify the two Azure OpenAI implementations (the
canned `[SIMULATED]` path must go), Content Safety / Prompt Shields, AI Search semantic ranker + agentic retrieval, Entra
External ID, Front Door WAF, Activity Log, evaluations, Event Grid pipeline.

### Phase 5: developer experience (1-2 weeks, overlaps)
"Enterprise Agentic starter" template per cloud (the reference app), one-click Mesh launch, docs per block, console actions for
each service (Nano is out of scope: this is Mesh), cost/usage view.

### Phase 6: conformance suite and release gate (continuous, final 1 week)
Per-block SDK suites plus the end-to-end scenario run on a real Codespace Mesh in CI; matrix published; "100%" is the matrix
turning fully green, with explicit declared non-goals.

## 5. Estimate and order (rough, NOT measured)

About 14-18 weeks of single-agent effort; with three parallel lanes after Phase 1, about 8-10 weeks wall clock. Critical path:
P0 -> F1/F2/F3/F4 -> A3/A4 (real runtime + gateway). If the YC/demo story needs something earlier, the smallest visible slice
is: reference app on Mesh with real Bedrock Converse tool loop, KB RAG with citations, Step Functions approval, guardrails
(most exists), then Memory and the AgentCore container runtime.

## 6. Risks

- 8 GB RAM vs real agent containers + model + engines: needs the AI profile and admission control; may force smaller model for tests.
- 3B model reliability for supervisor routing and multi-step plans: scripted backend for deterministic tests, honest labelling.
- AgentCore/Bedrock APIs move fast; pin the SDK versions the suite targets and record them in the matrix.
- Scope creep via "every" service: the matrix is the contract; anything outside it is a declared gap.
- Code-sharing hazard: these capabilities touch `core/*`, `consoles/src/**`, `wasm/**` which change only on the trunk
  (V4-BRANCH-ARCHITECTURE); lanes need claims in SESSION-CLAIMS.md and one branch per work package.

## 7. Decisions needed from the owner

1. Approve the conformance definition (section 1) and the "wire-compatible, not real products" rule for OpenSearch/Cognito/WAF.
2. Order: AWS lane first (matches the diagram) with GCP and Azure lanes starting after Phase 1, or all three at once.
3. Run the user's agent containers on Mesh (needs RAM budget) or keep spec-based agents only for the first release.
4. Is the reference app public (marketing + docs) or internal?
5. Relationship to the v4.0.0/4.0.1 release: these are post-beta work packages, not part of the beta cut.
