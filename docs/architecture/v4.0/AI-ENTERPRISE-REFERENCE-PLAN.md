# Enterprise agentic AI on Mesh: plan to 100% conformance with the reference architecture

Status: PLAN (2026-11-14). Nothing is built by this document. Source of the target: the owner's reference architecture
"Building Agentic AI Solution on AWS Bedrock" (`~/Desktop/AI_E2E_Flow.jpeg`): 11 numbered blocks + the knowledge processing pipeline + the governance row = 13 components (section 2).
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
3. Every one of the 13 components has a conformance row: the SDK calls the real service offers for that block, with
   assertions on wire shape, error codes and state transitions, plus the console actions that exist for it.
4. The same scenario then exists for GCP (Vertex) and Azure (Foundry) equivalents.

Explicit non-goal: model QUALITY. Mesh runs a small local model (decision 2026-11-07: Qwen2.5-3B Q4 on native llama.cpp; the
Codespace is 8 GB RAM, not 32). Conformance means wire/semantic fidelity and correct control flow, not answer quality. Every
page and test must say so (see `llm_core.HONEST_LIMIT`). Where a block needs a capability a 3B model cannot supply reliably
(supervisor routing, multi-tool plans), the harness offers a deterministic/scripted backend so the application logic is still
testable.

## 2. The 13 components

The diagram has 11 numbered blocks (1-11) plus two unnumbered ones, the event-driven Knowledge Processing Pipeline (**C12**)
and the cross-cutting Governance and Security row (**C13**). Each component below lists its parts (from the diagram), what
exists on Mesh today (read from code at `origin/v4-on-main`, NOT verified with SDK calls), what "100%" means for it, the work
packages (WP) that deliver it, and the GCP/Azure analogues. WP ids are scheduled in section 4.

State words: SERVED (code exists and is routed), PARTIAL, MISSING.

### C1. Access and perimeter security
- **Parts:** Amazon Cognito (user authentication), Amazon API Gateway, AWS WAF; facilities users (managers, engineers, ops) arriving by web/mobile/chat; user identity and token flow to the runtime.
- **Today:** API Gateway SERVED (v1/v2 control + data plane). Cognito only appears as an authorizer reference: **no user-pool service** (pools, users, groups, app clients, JWKS, token endpoints). **No WAFv2.**
- **100% means:** a user signs in with Cognito, the JWT passes the API Gateway authorizer, WAF rules (managed, custom, rate-based) block/allow in front of the gateway, and the verified identity reaches C3/C4.
- **Work:** WP-A1 Cognito user pools + JWT/JWKS + authorizer; WP-A2 WAFv2 (web ACLs, rules, associations, evaluation in the gateway data plane).
- **Other clouds:** GCP Identity Platform + API Gateway + Cloud Armor; Azure Entra External ID + APIM + Front Door WAF (all MISSING).

### C2. Channels and interface
- **Parts:** Web UI, mobile app, chatbot, API; input guardrails (prompt filtering, threat protection); approver inbox (notifications for pending approvals).
- **Today:** channels are application code (reference app). Bedrock Guardrails SERVED as Dev Simplified (word, topic, PII regex, keyword content filters; no contextual grounding). SNS/SES SERVED for notifications.
- **100% means:** the reference app's channels run on Mesh, inputs pass through guardrails with the native `guardrailConfig`/`ApplyGuardrail` shapes, approvals reach an inbox through SNS/SES.
- **Work:** WP-P0 reference app channels; WP-F6 guardrails v2 (stronger prompt-attack detection, shared by all clouds).
- **Other clouds:** Vertex safety settings, Azure Content Safety / Prompt Shields (MISSING).

### C3. AgentCore Runtime (session-isolated)
- **Parts:** supervisor agent (plan, route, synthesize) with sub-agents (Facilities, Maintenance, Analytics); agent harness (step/token/cost budgets, checkpoints, timeouts and kill switch); agent framework (Strands, LangGraph).
- **Today:** runtime control plane SERVED; `InvokeAgentRuntime` executes a **declarative agent spec in-process** (`agent_spec_core`), never a container. No multi-agent collaboration, no harness limits, no checkpoints.
- **100% means:** the user's real Strands/LangGraph agent container runs on Mesh compute with session isolation; supervisor/sub-agent collaboration works; budgets, timeouts, checkpoints and kill switch are enforced and observable.
- **Work:** WP-A3 container runtime on Mesh compute + harness; WP-A6a multi-agent collaboration / `InvokeInlineAgent` / `returnControl`.
- **Other clouds:** Vertex Agent Engine (spec-based today, `gcp_agentengine_core`), Azure Foundry Agent Service (assistants-style, PARTIAL).

### C4. AgentCore Gateway
- **Parts:** on-behalf-of identity propagation; central policy check on every tool call (identity, RBAC, ABAC); tool catalog + shared knowledge tools; schema validation; access control policies; request routing and throttling; audit and tracing with user identity; tool and RAG output guardrails (Bedrock guardrails, prompt-injection scan, PII and schema checks).
- **Today:** gateway control plane and MCP `tools/list`/`tools/call` for **Lambda targets only** (SERVED); openApiSchema/smithyModel/mcpServer targets are registered but not callable. **No identity propagation, no policy engine, no audit trail, no output guardrails.**
- **100% means:** every target type is callable; each call carries the caller identity, is authorised by a policy engine, validated, throttled, guardrail-scanned on output, and written to an audit log.
- **Work:** WP-F4 policy engine (Cedar-lite) shared; WP-A4 gateway targets + OBO + audit + output guardrails.
- **Other clouds:** Apigee/API Gateway + MCP (GCP), APIM AI gateway (Azure).

### C5. Actions and approval
- **Parts:** classify operation and risk (low/medium/high); preview proposed change; auto-approval for low risk, human approval for medium/high writes, two approvers + auto-undo for irreversible; durable approval state (Step Functions: pending action, SLA timeout, apply and resume after approval); DynamoDB action and approval ledger (system of record); idempotency keys and per-tool permission contracts; execute approved action; validate result; rollback/compensation.
- **Today:** Step Functions SERVED (`stepfunctions_core`), DynamoDB SERVED. `.waitForTaskToken`, SendTaskSuccess/Failure, heartbeats, Choice/Map depth and SLA timers are **unverified**. The risk-tier, two-approver and compensation patterns are application code.
- **100% means:** the reference approval state machine (risk Choice, human-approval task token with timeout, execute, validate, compensate) runs on Mesh, with the ledger and idempotency semantics enforced by DynamoDB conditional writes.
- **Work:** WP-A9 Step Functions durable-approval verification and fixes; WP-F5 reference definitions + tests.
- **Other clouds:** GCP Workflows, Azure Logic Apps / Durable Functions.

### C6. Knowledge search layer (RAG)
- **Parts:** Amazon OpenSearch Service (semantic vector search for SOPs, policies, manuals, vendor docs; hybrid vector + BM25; metadata filtering; access-aware search by user identity); Bedrock reranker for relevance and accuracy.
- **Today:** Bedrock Knowledge Bases: ingestion, `Retrieve`, `RetrieveAndGenerate` SERVED over an **in-account exact-cosine index** (text files only; PDF/Office counted as failed). **No OpenSearch/Serverless API, no BM25/hybrid, no ACL filtering, no Rerank API.**
- **100% means:** an OpenSearch (Serverless) wire for collections, policies, index/knn/hybrid queries and filters; Knowledge Bases can use it as the store; `Rerank` works; results honour per-user access filters.
- **Work:** WP-F3 retrieval engine (HNSW + BM25, filters, ACL, rerank); WP-A7 OpenSearch wire; WP-A6b KB store types + Rerank API.
- **Other clouds:** Vertex Vector Search SERVED (brute force) + **RAG Engine MISSING** (`ragCorpora`); Azure AI Search vector SERVED, semantic ranker and agentic retrieval MISSING.

### C7. Tools (AWS Lambda)
- **Parts:** read-only knowledge search tools (enterprise knowledge, document source retrieval, policy/procedure, maintenance manual, knowledge reference); approval-gated write-capable tools (Maintenance Management, ITSM, ERP); read-only operational data (IoT / asset telemetry).
- **Today:** Lambda SERVED with real invocation, DynamoDB SERVED. No telemetry store (IoT Core / Timestream).
- **100% means:** the reference tools deploy as Lambdas behind the gateway, write tools are reachable only through the approval path, telemetry queries answer from a time-series store.
- **Work:** WP-P0 reference tools; WP-A10 telemetry store (DynamoDB-backed Timestream/IoT subset), decided after Phase 0.
- **Other clouds:** Cloud Functions/Run, Azure Functions.

### C8. AgentOps and observability
- **Parts:** AgentOps lifecycle (ratings and corrections feeding an eval set, offline evals on golden datasets, CI gates, version registry, model pinning, canary with automatic rollback, runtime executes only pinned versions); AgentOps observability (traces, logs, metrics, evaluations and quality, CloudWatch dashboards and alarms; send agentic traces, metrics and logs to a central place).
- **Today:** CloudWatch and X-Ray SERVED (GenAI-specific metrics unchecked); a `mesh_ai` usage ledger exists. **No** Bedrock evaluation jobs, model-invocation logging, prompt management/versions, AgentCore Observability.
- **100% means:** every agent/model/tool call emits traces and metrics; evaluation jobs run on a golden set; prompt and agent versions are pinned and a canary alias can roll back automatically.
- **Work:** WP-A5c AgentCore Observability; WP-A6c prompt management + versions, invocation logging, evaluation jobs; WP-A8b CloudWatch GenAI metrics/dashboards/alarms; WP-F1 usage events -> metrics.
- **Other clouds:** Vertex evaluation + Cloud Trace; Azure Foundry evaluations + Application Insights.

### C9. AgentCore Memory
- **Parts:** short-term memory (session events and context, user/tenant scoped, TTL and automatic expiry); long-term memory (user/tenant scoped, retention and deletion, prompt-injection/poisoning checks).
- **Today:** **MISSING entirely.** No Memory API.
- **100% means:** AgentCore Memory control plane + data plane (memories, events, sessions, retrieval, long-term strategies such as semantic/summary/user-preference), TTL and deletion honoured, tenant isolation, writes validated for injection/poisoning.
- **Work:** WP-F2 memory engine (shared); WP-A5a AgentCore Memory (+ Identity) wire.
- **Other clouds:** Vertex Agent Engine Memory Bank; Foundry thread/agent memory.

### C10. Foundation models via Bedrock
- **Parts:** Claude, Amazon Nova; model router (task, cost and latency-aware routing, quality and availability-based routing, automatic fallback).
- **Today:** model catalog, Converse/ConverseStream, InvokeModel (+stream), embeddings, CountTokens routed; tool use handled (`toolConfig`/`toolUse` in `ai_models_core`). **One local model answers every model id.** Streaming is cosmetic. No inference-profile list/get, no prompt router, no fallback.
- **100% means:** the same SDK calls and error codes as Bedrock; at least two local models (small/fast, default) with the router choosing by task/latency and falling back on failure; real streaming; throttling and context-overflow errors match Bedrock.
- **Work:** WP-F1 seam (streaming, queue + throttle, 2-model router, prompt-cache reuse, usage events); WP-A6d inference profiles + prompt router; WP-F7 Mesh packaging/RAM admission.
- **Other clouds:** Vertex model garden + Gemini (SERVED control plane, tool calling PARTIAL), Azure OpenAI deployments (two implementations disagree; the canned path must go).

### C11. Response generation
- **Parts:** grounded response with citations (grounding and citation check, PII redaction, policy filter).
- **Today:** citations from `RetrieveAndGenerate` SERVED; PII/word/topic filters SERVED; **contextual grounding is rejected** by the guardrails.
- **100% means:** answers carry citations to retrieved passages, a grounding check can flag/blocks ungrounded text, PII is redacted, policy filters apply, all through native `guardrailConfig`.
- **Work:** WP-F6 guardrails v2 (contextual grounding); WP-A6b citations in all response paths.
- **Other clouds:** Vertex grounding check, Azure groundedness detection (MISSING).

### C12. Knowledge processing pipeline (event-driven)
- **Parts:** Amazon S3 (source docs) -> extraction + guardrails scan -> chunking and parsing -> embedding generation -> vector DB (OpenSearch).
- **Today:** S3, EventBridge/SQS/SNS, Lambda and Bedrock embeddings exist individually. The **wired pipeline is untested**. Extraction of PDF/Office is MISSING; vector DB is the in-account index (see C6).
- **100% means:** dropping a document in S3 triggers the pipeline automatically (S3 event -> Lambda/Step Functions -> extract + scan -> chunk -> embed -> index) and the document becomes retrievable with correct metadata and ACL.
- **Work:** WP-P0 reference pipeline; WP-F3 extraction (PDF/Office) + indexing; WP-A10 extraction stubs only if needed.
- **Other clouds:** GCS + Eventarc + Document AI; Blob + Event Grid + Document Intelligence.

### C13. Governance and security (cross-cutting)
- **Parts:** IAM and Cognito (identity and access); KMS (encryption); CloudTrail (audit logs); Bedrock Guardrails (safety and policy); data governance (lineage, quality, retention); policy controls and access reviews; cost tracking and optimization.
- **Today:** IAM, KMS, Guardrails (Dev Simplified), Cost Explorer and the `mesh_ai` ledger SERVED. **CloudTrail API (trails, LookupEvents) MISSING**; Cognito MISSING (C1); lineage/quality MISSING; no policy engine (C4).
- **100% means:** all actions are recorded and queryable in CloudTrail; KMS keys protect memory/KB/S3 data; policy and access-review data are available; token/cost usage is attributed per session/space.
- **Work:** WP-A8a CloudTrail; WP-F4 policy engine; WP-A1 Cognito; WP-F1 usage/cost attribution; data lineage/quality decided after Phase 0.
- **Other clouds:** Cloud Audit Logs, Azure Activity Log/Purview.

### 2.1 Cross-cloud applicability

The 13 components are a pattern every cloud can implement; the diagram's products are AWS. The equivalents below are the
planning mapping (from product knowledge, NOT read from our code) and decide what each cloud lane builds.

| Component | AWS | GCP | Azure | Applies to all three? |
|---|---|---|---|---|
| C1 Access and perimeter | Cognito, API Gateway, WAF | Identity Platform, API Gateway, Cloud Armor | Entra External ID, API Management, Front Door WAF | Yes |
| C2 Channels, input guardrails | Bedrock Guardrails | Safety filters, Model Armor | Content Safety, Prompt Shields | Yes; guardrail products differ |
| C3 Agent runtime | AgentCore Runtime | Vertex Agent Engine | Foundry Agent Service | Yes; Strands/LangGraph run on all |
| C4 Agent gateway + policy | AgentCore Gateway + AgentCore Policy (Cedar) | Apigee or API Gateway, MCP | API Management AI gateway | **Different:** the Cedar policy layer and tool-catalog gateway are AWS-specific; other clouds are built from generic gateway + policy pieces (F4 serves all) |
| C5 Durable approvals | Step Functions | Workflows | Logic Apps, Durable Functions | Yes |
| C6 Knowledge search (RAG) | OpenSearch, Bedrock reranker | Vertex Vector Search, RAG Engine | AI Search + semantic ranker | Yes |
| C7 Tools and telemetry | Lambda, IoT/Timestream | Cloud Functions/Run, Pub/Sub + BigQuery | Functions, IoT Hub | Mostly; Google retired IoT Core, so GCP telemetry is built from Pub/Sub + a store |
| C8 AgentOps and observability | CloudWatch, AgentCore Observability + Evaluations | Cloud Trace, Vertex evaluation | App Insights, Foundry evaluations | Yes |
| C9 Memory | AgentCore Memory | Agent Engine Memory Bank | Foundry thread/agent memory | Yes; newer, less uniform products |
| C10 Foundation models + router | Bedrock (Claude, Nova), prompt router | Vertex model garden (Gemini) | Azure OpenAI / Foundry models, model router | Yes; router support differs per cloud |
| C11 Response generation | Guardrails grounding check | Vertex grounding check | Groundedness detection | Yes |
| C12 Knowledge pipeline | S3, Lambda, Bedrock embeddings, vector DB | GCS, Eventarc, Document AI | Blob, Event Grid, Document Intelligence | Yes |
| C13 Governance | CloudTrail, KMS, IAM, Cognito | Cloud Audit Logs, KMS, IAM | Activity Log, Key Vault, Entra | Yes |

AWS-only features (no one-to-one product elsewhere): AgentCore Policy (Cedar), Bedrock prompt routers, AgentCore Browser, Code
Interpreter, Payments and Capacity providers. For GCP and Azure each lane delivers the component's BEHAVIOUR with that cloud's
own native services and wire shapes; it does not clone AWS names.

State per cloud today (read from code): AWS has most engines and consoles (gaps in each component above). GCP has Vertex AI,
Agent Engine (spec-only) and Vector Search; RAG Engine, Memory Bank, Cloud Armor and Identity Platform are missing. Azure has
Cognitive Services, Entra and Front Door consoles; Foundry agents are partial; Content Safety, Prompt Shields and the AI Search
semantic ranker are missing.

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

## 4. Work packages and phases

Work packages (WP) are the unit of branches and claims (one topic branch per WP). The "Components" column shows which of the
13 components each WP delivers; section 2 gives the detail.

### Phase 0: baseline and reference app (1-1.5 weeks, gates everything)
| WP | Content | Components |
|---|---|---|
| P0 | Reference app (Facilities agent) written only against native SDKs: channels, Strands + LangGraph agents, Lambda tools, Step Functions approval flow, S3 ingestion pipeline, IaC. Run it on Mesh, turn every "read from code" claim in section 2 into a measured pass/fail per SDK call; re-verify tool calling/streaming with real boto3, google-genai and openai SDKs; fix the rubric wording with the owner. | C2, C5, C7, C12 (and the baseline for all) |

### Phase 1: shared foundations (about 2 weeks, before the cloud lanes)
| WP | Content | Components |
|---|---|---|
| F1 | LLM seam: real upstream streaming, request queue + cloud-correct throttling, context-overflow errors, 2-model router with fallback, prompt-cache reuse, usage events -> ledger -> metrics | C10, C8, C13 |
| F2 | Memory engine (short-term events, long-term strategies, TTL, tenant scope, poisoning checks) | C9 |
| F3 | Retrieval engine (HNSW + BM25 hybrid, metadata + ACL filters, reranker, PDF/Office extraction, indexing) | C6, C12 |
| F4 | Policy engine (Cedar-lite) + decision log | C4, C13 |
| F5 | Approval/ledger reference definitions (risk Choice, task-token approval, idempotency, compensation) with tests | C5 |
| F6 | Guardrails v2 (contextual grounding, stronger prompt-attack detection, shared across clouds) | C2, C4, C11 |
| F7 | Mesh packaging: AI profile (which backends start), RAM admission via `mesh.allocate("ai")`, model download/boot UX, status chip | C10 (all, as a constraint) |

### Phase 2: AWS lane (4-5 weeks, after F1-F4)
| WP | Content | Components |
|---|---|---|
| A1 | Cognito user pools, JWT/JWKS, API Gateway authorizer | C1, C13 |
| A2 | WAFv2 (web ACLs, managed/custom/rate rules, associations) in front of the gateway data plane | C1 |
| A3 | AgentCore Runtime on Mesh compute: run the user's agent container, session isolation, harness limits, checkpoints | C3 |
| A4 | AgentCore Gateway: all target types callable, OBO identity, policy check, validation, throttling, audit, output guardrails | C4 |
| A5 | AgentCore Memory + Identity + Observability APIs over F2 | C9, C8, C13 |
| A6 | Bedrock: multi-agent collaboration + `InvokeInlineAgent` + `returnControl` (a), Rerank API + KB store types + citations (b), prompt management + versions + invocation logging + evaluation jobs (c), inference profiles + prompt router (d) | C3, C6, C11, C8, C10 |
| A7 | OpenSearch Serverless / OpenSearch Service wire over F3 | C6, C12 |
| A8 | CloudTrail (a); CloudWatch GenAI metrics, dashboards, alarms (b) | C13, C8 |
| A9 | Step Functions durable-approval verification and fixes (`waitForTaskToken`, heartbeat, Map, SLA timers) | C5 |
| A10 | Telemetry store (IoT/Timestream subset) and extraction stubs, only if Phase 0 shows they are needed | C7, C12 |
| A11 | AgentCore Browser + Code Interpreter on Mesh compute (sandboxed, RAM-budgeted); Evaluations + Optimizations/A-B tests consoles | C3, C8 |

### Phase 3: GCP lane (parallel to Phase 2, 3-4 weeks)
Vertex Agent Engine running real containers/ADK (C3), Memory Bank (C9), RAG Engine `ragCorpora` + retrieveContexts (C6, C12),
grounding check + safety settings/ratings (C11, C2), Gemini Developer API alias and function calling depth (C10), Identity
Platform + Cloud Armor (C1), Cloud Audit Logs (C13), evaluation + Cloud Trace (C8), Eventarc pipeline (C12), Workflows approvals (C5).

### Phase 4: Azure lane (parallel, 3-4 weeks)
Foundry Agent Service + Assistants + `/responses` + threads/runs/tool outputs (C3, C9), unify the two Azure OpenAI
implementations and remove the canned `[SIMULATED]` path (C10), Content Safety / Prompt Shields + groundedness (C2, C11), AI Search
semantic ranker + agentic retrieval (C6), Entra External ID + Front Door WAF (C1), Activity Log (C13), evaluations + App Insights
(C8), Event Grid pipeline (C12), Logic Apps/Durable approvals (C5).

### Phase 5: developer experience (1-2 weeks, overlaps)
"Enterprise Agentic starter" template per cloud (the reference app), one-click Mesh launch, docs per component, console actions
for each service (Mesh, not Nano), cost/usage view.

### Phase 6: conformance suite and release gate (continuous, final week)
Per-component SDK suites plus the end-to-end scenario run on a real Codespace Mesh in CI; the matrix (13 components x clouds)
published; "100%" is that matrix fully green with the declared non-goals.

### Coverage check (every component has at least one WP)
| Component | WPs |
|---|---|
| C1 Access and perimeter | A1, A2 |
| C2 Channels and interface | P0, F6 |
| C3 AgentCore Runtime | A3, A6a |
| C4 AgentCore Gateway | F4, A4, F6 |
| C5 Actions and approval | F5, A9 |
| C6 Knowledge search (RAG) | F3, A6b, A7 |
| C7 Tools (Lambda) | P0, A10 |
| C8 AgentOps and observability | F1, A5, A6c, A8b |
| C9 AgentCore Memory | F2, A5 |
| C10 Foundation models | F1, F7, A6d |
| C11 Response generation | F6, A6b |
| C12 Knowledge processing pipeline | P0, F3, A7, A10 |
| C13 Governance and security | F1, F4, A1, A5, A8a |

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

## 8. Appendix: services to build and console-capture coverage

Console fidelity ("match the native console, offered as individual services") depends on the screenshot library at
`~/Applications/simulator/console-captures` (separate repo, about 1.0 GB, the part that survived the 2026-11-01 deletion of
`appliance/console_captures`): 239 AWS, 123 GCP, 30 Azure captures, each a PNG plus a text dump. They cover landing pages
and second-level pages/tabs; most do NOT include create wizards or resource detail pages, and several services have only a
landing shot. Counts below were taken on 2026-11-14.

| Cloud | Service to build | Components | Captures we have | Enough to match the native console? |
|---|---|---|---|---|
| AWS | AgentCore (Runtime, Gateway, Memory, Identity, Policy, Observability, Evaluations, Browser, Code Interpreter, Optimizations/A-B tests, Payments, Capacity providers) | C3, C4, C8, C9 | 24 pages incl. sessions/traces/spans, evaluators, gateways, policy, memory | Good |
| AWS | CloudTrail | C13 | 20 (event history, trails, Lake query, insights) | Good |
| AWS | Bedrock: Guardrails, Knowledge Bases, prompt management, evaluations, inference profiles, Mantle | C2, C6, C8, C10, C11 | 19 + 13 (inference profiles, batch inference, quotas visible; guardrails/evaluations pages not checked) | Good, gap check needed |
| AWS | Cognito | C1 | landing only | No |
| AWS | WAFv2 | C1 | landing only (+1 Pro variant) | No |
| AWS | OpenSearch Service / Serverless | C6, C12 | none | No |
| AWS | Timestream, IoT, Textract, Comprehend, Step Functions approvals | C7, C12, C5 | landing only each (Step Functions already has a console) | No |
| GCP | Agent Platform (Vertex Studio, Agents, Models) | C3, C10 | 11 | Partial |
| GCP | Identity Platform | C1 | 6, but marketing tabs (pricing/docs), not the console | No |
| GCP | Cloud Armor | C1 | landing and docs only | No |
| GCP | RAG Engine, Memory Bank | C6, C9 | none | No |
| GCP | Cloud Logging, Security Command Center | C13 | 20 and 12 | Good |
| Azure | Foundry hub (OpenAI, AI Search, Content Safety tiles) | C2, C6, C10, C11 | 14, mostly the hub listing, not each service's blades | Partial |
| Azure | Entra, Monitor | C1, C8, C13 | 43 and 48 | Good |
| Azure | Front Door WAF, Purview | C1, C13 | none | No |

Existing consoles in our source: AWS Bedrock (with an AgentCore page), CloudWatch, Step Functions; GCP Vertex AI; Azure Cognitive
Services, Entra, Front Door.

**AgentCore scope addition.** The AgentCore captures show areas the first draft did not list: Browser, Code Interpreter,
Evaluations, Optimizations/A-B tests, Payments, Capacity providers, Knowledge bases and Policy. Policy (Cedar) belongs with C4
(F4/A4); Evaluations and Optimizations with C8 (A6c/A5); Browser and Code Interpreter are new WP-A11 (AgentCore tools:
sandboxed code execution and headless browser on Mesh compute, sized against the 8 GB budget); Payments and Capacity providers
are declared non-goals unless Phase 0 shows the reference app needs them.

**Offering each as an individual service** goes through the service-expansion pipeline: an engine, a capability manifest, a
console page matching its captures, and the gates (API, SDK, CLI, UI, Playwright). A service without good captures can ship
API/SDK first, but its console cannot match the native one until it is captured from the real console.

**Capture backlog (needs the owner's cloud logins):** Cognito, WAFv2, OpenSearch (Serverless collections), Timestream/IoT,
Textract/Comprehend detail pages, Bedrock Guardrails/evaluations if missing; GCP Cloud Armor, Identity Platform console, RAG
Engine, Memory Bank; Azure Content Safety, AI Search, Front Door WAF, Purview, and the Foundry service blades.
