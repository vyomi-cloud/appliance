# Enterprise agentic AI on Mesh and Nano: plan to 100% conformance with the reference architecture

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

Both substrates are in scope (owner, 2026-11-14), with different bars:

- **Mesh = hard 100% gate** (it will be sold to enterprises). A component is done only when every in-scope operation, error code,
  state transition and console action passes against the pinned SDK versions. No declared substrate limits except model QUALITY.
  Anything the owner leaves out is on a written, owner-approved non-goals list, never an unlisted gap.
- **Nano = 100% with declared limits** (browser backends, WebLLM web models, section 2.3). Accepted Mesh-only items on Nano
  (owner, 2026-11-14): the Browser tool, long-running approvals/timers, real agent containers. Everything else must pass on Nano
  with its substrate limit written down.

How "100%" is measured (so it is not a feeling):

1. **In-scope API inventory, generated mechanically** from the official models: botocore service models for Bedrock, Bedrock Agent(+Runtime),
   AgentCore (+Runtime), Cognito IDP, WAFv2, OpenSearch Serverless, Step Functions, CloudTrail, CloudWatch; Google API discovery docs/protos
   for Vertex AI / Agent Engine / RAG Engine / Cloud Armor / Identity Platform; Azure OpenAPI specs for Cognitive Services / Foundry / AI Search /
   Content Safety / Front Door. Each operation is tagged in-scope or non-goal (owner-approved). The repo already counts ops per service (`wasm/docs`).
2. **Every in-scope operation has a contract test** through the native SDK (pinned versions recorded in the matrix) that checks request validation,
   response shape, error codes and the state change. Coverage = tested in-scope operations / in-scope operations, per service, and must be 100%.
3. **No silent-ignore rule:** an unsupported field, option or API is rejected with the cloud's real error. It is never accepted and ignored.
4. **Console parity:** every in-scope console action works through the UI and is checked against the SDK result (the bi-directional suites used for v4).
5. **Reference app** passes end to end on Mesh on a real Codespace, on every release.

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

### 2.2 Backend technology map (Mesh)

Rule (section 3): wire-compatible lightweight engines, one shared backend per capability, exposed through the AWS, GCP and
Azure wires. Mesh = a headless Codespace (8 GB, 2 cores) running the simulator plus llama.cpp containers (`llm-chat`,
`llm-embed`) with `VYOMI_COMPUTE_BACKEND=docker`; other backends start on demand next to it (found in
`codespace/.devcontainer/mesh/docker-compose.mesh.yml`; the on-demand start is not verified here). "Exists" means present in
the repo today. RAM figures are rough ESTIMATES, not measurements; Phase 0 measures them.

| Component | Backend technology on Mesh | Exists today? | To build / choose | Est. RAM | Rejected |
|---|---|---|---|---|---|
| C1 Cognito, Identity Platform, Entra External ID | In-house OIDC/JWT issuer (RS256 + JWKS, users/groups/app clients in Postgres, hosted-login pages) shared by the three wires | No (only IAM Cedar + authorizer references) | Issuer service in the simulator process | ~0 extra | Keycloak/Authentik (1 GB+ JVM/Python stacks) |
| C1 WAF, Cloud Armor, Front Door WAF | Coraza (Go, OWASP CRS) as a Caddy module in the existing `caddy` gateway, rule model translated from each cloud's rule shape | Caddy gateway exists; Coraza not | Coraza build + rule translators | ~30-60 MB | ModSecurity (heavier), custom regex WAF (no CRS) |
| C2, C11 guardrails and grounding | Deterministic filters (existing) + small classifier: Llama-Guard-3-1B / ShieldGemma-2B GGUF on llama.cpp for prompt attack and content safety; grounding = embedding-similarity + LLM-judge, PII = regex + Presidio-lite patterns | Regex/keyword guardrails exist (`bedrock_guardrails_core`) | Classifier model + grounding check | model ~1 GB when loaded (load on demand) | Full Presidio/spaCy stack (heavy) |
| C3 Agent runtime (AgentCore, Agent Engine, Foundry agents) | Docker containers started by the simulator's compute backend (user's Strands/LangGraph/ADK code), cgroup limits, a runtime supervisor for session isolation, budgets, timeouts, kill switch; checkpoints in Postgres | Docker compute backend exists; `agent_spec_core` is the current in-process fallback | Runtime supervisor + harness + checkpoint store | 200-500 MB per agent container | Firecracker/gVisor (not available in Codespaces), in-process only (no real framework code) |
| C3 Code Interpreter / Browser tools | Resource-limited Docker sandbox (Python); headless Chromium container (Playwright) for Browser | No | Sandbox images + API wires | 100 MB / 500+ MB | Browser in the simulator process |
| C4 Gateway policy | **Cedar** (existing `core/cedar_engine.py`) for tool-call authorization with a decision log; MCP/OpenAPI/Lambda target adapters in the simulator; throttling via Valkey counters | Cedar engine + Lambda MCP targets exist | Policy schema for tool calls, OBO claims, audit sink, other target types | ~0 extra | OPA (second policy language) |
| C5 Durable approvals | In-house ASL interpreter (`stepfunctions_core`) with state, task tokens, heartbeats and timers persisted in Postgres; DynamoDB-local (or the in-house DynamoDB core) as the approval ledger with conditional writes | Both exist | Task-token persistence, timers, verification | DynamoDB-local JVM ~300-500 MB if used | Temporal/Camunda (heavy) |
| C6 Knowledge search (OpenSearch, Vector Search, AI Search, RAG Engine) | **Postgres 16 + pgvector (HNSW) + full-text (tsvector/BM25-style)** with metadata and ACL filters; RRF hybrid (already implemented for Azure AI Search with an exact scan + TF-IDF); reranker = a GGUF cross-encoder (bge-reranker) served by llama.cpp; OpenSearch/AOSS REST, Vertex and Azure wires are shims over this one engine | Postgres image already ships pgvector (`vyomi/postgres:16-alpine-pgvector`); exact-scan hybrid exists; no HNSW use, no rerank | Engine, filters/ACL, rerank model, REST shims | Postgres ~150-300 MB; reranker model ~0.5 GB on demand | Real OpenSearch/Elasticsearch (1 GB+ JVM), Qdrant (evaluate only if pgvector recall/latency fails) |
| C7 Tools (Lambda, Functions) | Docker-based Lambda/Functions runtimes (existing); telemetry store = VictoriaMetrics (existing container) or Postgres time-series tables | Lambda runtime and VictoriaMetrics exist | Timestream/IoT/Azure IoT shims over one store | VictoriaMetrics ~50 MB | TimescaleDB |
| C8 AgentOps and observability | Metrics: VictoriaMetrics (exists) behind CloudWatch/Monitor/Cloud Monitoring wires; traces: spans in Postgres behind X-Ray/Cloud Trace/App Insights shims (Jaeger string appears only in capability text); evaluation jobs: in-house runner using the local model as judge + deterministic metrics against golden sets; prompt/agent versions in Postgres | VictoriaMetrics, CloudWatch core, X-Ray core exist | Trace store, eval runner, prompt registry, GenAI metric names | ~0 extra | Full OpenTelemetry/Jaeger stack |
| C9 Memory | Short-term: **Valkey** with TTL (container exists); long-term: **pgvector** rows with strategies (semantic/summary/preference) built on the embedding model; tenant scoping by key prefix + row filters; provenance + injection screening on write via the guardrail classifier | Valkey + Postgres/pgvector exist; no memory API | Memory engine and the three wires | ~20 MB Valkey | Mem0/Letta servers (extra runtimes) |
| C10 Foundation models and router | llama.cpp `llama-server` (chat model Qwen2.5-3B Q4; second small model for fast tier; embeddings model nomic/bge) behind `core/mesh_llm_gateway`; router = rules on task, latency and failure with automatic fallback; larger models via the runner pool (mesh LLM mesh, up to 10 GitHub runners at 16 GB, llama.cpp RPC) | llama.cpp containers, gateway, `mesh_ai` admission + ledger exist | 2-model router, real streaming, throttling, cloud-correct errors | chat ~2.5 GB, embed ~0.3 GB, second model ~1 GB | Ollama as primary (kept as a compatible alternative) |
| C12 Knowledge pipeline | Events on NATS/EventBridge core -> Lambda/Functions or Step Functions -> extraction (`pypdf`/`pdfminer.six`, `python-docx`, `openpyxl`; tesseract OCR optional) -> guardrails scan -> chunk -> embed (llama-embed) -> pgvector; MinIO (`vyomi-minio`, S3), Azurite, fake-gcs hold source docs | NATS, MinIO, Azurite, fake-gcs, EventBridge/Eventarc/Event Grid cores exist | Extraction workers, wired reference pipeline, S3/GCS/Blob event triggers | small | Apache Tika (JVM) |
| C13 Governance | Audit: append-only event log in Postgres behind CloudTrail, Cloud Audit Logs and Activity Log wires (every simulator call already passes the middleware); KMS: existing KMS cores (Vault container available for key material); IAM: Cedar engine; cost: `mesh_ai` ledger + Cost Explorer core; lineage/quality metadata tables in Postgres only if Phase 0 shows need | Cedar, KMS, Cost Explorer, `mesh_ai` exist; call middleware exists | Audit store + query APIs (LookupEvents, Lake-style queries) | ~0 extra | Separate SIEM/Loki stack |

**Shared backends (build once, three wires):** Postgres + pgvector (retrieval, long-term memory, audit, traces, checkpoints,
auth store), Valkey (short-term memory, throttling), llama.cpp (chat, embeddings, rerank, classifier), Cedar (policy and IAM),
Docker compute (agents, tools, sandboxes), VictoriaMetrics (metrics and telemetry), NATS (events), the ASL interpreter
(approvals).

**8 GB budget (estimates):** chat model ~2.5 GB + embed ~0.3 GB + simulator ~0.4 GB + Postgres ~0.3 GB + Valkey/NATS/VictoriaMetrics
~0.1 GB leaves roughly 4 GB for agent containers, the reranker/classifier models and tool sandboxes. Browser (500+ MB) and a
second chat model do not run together with several agents: the AI profile (F7) must admit workloads against the budget and say
so in plain language when it refuses. Bigger models or heavier agents move to the runner pool.

**Nano (browser) substrate:** no Docker, so no real agent containers, Coraza, llama.cpp or Postgres server. Nano gets the same
engines through browser backends (Pyodide, PGlite, WebLLM, Cedar/OPA in WASM); see section 2.3 for the per-component Nano map.

### 2.3 Dual-substrate design: Mesh and Nano (against web LLMs)

Requirement (owner, 2026-11-14): the FULL architecture must work on both Mesh and Nano, with Nano answering from in-browser
web LLMs (WebLLM). Design rule that makes this possible: **every shared engine (memory, retrieval, policy, approvals, guardrails,
auth, audit, evals) is written once as substrate-independent, Pyodide-loadable Python behind one interface, with two backends:
a heavy native one on Mesh and a browser one on Nano.** The cloud wires on top (AWS, GCP, Azure) never know which substrate
they run on. This is how the existing cores already work (`core/*` is built into `wasm/core` by `build_cores.py` and loaded by
`wasm/nano-boot.js`); the new engines must follow it and must be added to the Nano core lists.

What Nano has today (read from `wasm/nano-boot.js`, `core/ai_model_catalog.py`; not tested): a WebLLM bridge
(`vyomiEnableWebLLM`, needs WebGPU) with four models, **SmolLM2 360M, Qwen2.5 0.5B, Llama 3.2 1B, Qwen2.5 1.5B**; `llm_core`
async backend; no embedding model in the browser (embeddings fall back to the labelled feature-hash); Pyodide cores including
Step Functions, event bus, CloudWatch, Lambda, Vertex, S3 vectors and Azure AI Search vector; PGlite for RDS. Nano does NOT load
`agent_spec_core`, `gcp_agentengine_core` or `cedar_engine`, so AgentCore/Agent Engine runtimes and Cedar policy do not run on
Nano yet. A paired Mesh can already serve AI calls for a Nano tab (`mesh-link.js`); that stays the "big model" option.

| Component | Mesh backend (2.2) | Nano backend (browser) | Nano limit to declare |
|---|---|---|---|
| C1 Auth | in-house JWT issuer, Postgres | same Python issuer in Pyodide, keys via WebCrypto, state in IndexedDB/OPFS | tokens valid only while the tab/SW is alive |
| C1 WAF | Coraza in Caddy | rule engine (OWASP-lite subset) in the service-worker router | subset of managed rules, Dev Simplified |
| C2/C11 Guardrails | rules + safety classifier model | rules + embedding similarity + the loaded web LLM as judge | no separate classifier model (browser memory) |
| C3 Agent runtime | Docker containers with real Strands/LangGraph/ADK | (a) spec agents in a Pyodide worker (needs `agent_spec_core` in the Nano list); (b) the user's REAL agent code runs on their own machine and calls Nano's wires through the local relay/endpoint (`vyomi-tunnel`); (c) pure-Python frameworks in a Pyodide worker, feasibility to test | hosting a container is impossible; real framework code runs outside the tab. **Mesh-only (accepted).** |
| C3 Code Interpreter | Docker sandbox | Pyodide worker (a natural sandbox) | CPU/memory of the tab, no native libs |
| C3 Browser tool | headless Chromium | none (declared gap, or an iframe-driven simplified browser) | **Mesh-only (accepted)** |
| C4 Policy | Cedar (`cedar_engine`) | Cedar compiled to WASM (cedar-wasm) in a worker; needs the engine added to the Nano list | verify wasm size/perf |
| C5 Approvals | ASL interpreter, Postgres timers | same interpreter (already a Nano core), state in OPFS/IndexedDB | timers and waits only run while a tab/worker is alive; long-running approvals are **Mesh-only (accepted)** |
| C6 Retrieval | Postgres + pgvector HNSW + FTS | PGlite (Postgres WASM) with the same SQL schema; pgvector/FTS availability in PGlite to verify; exact-scan fallback exists | corpus size bounded by tab memory/OPFS |
| C6 Rerank | GGUF cross-encoder | embedding + BM25 blend, or a small ONNX reranker via transformers.js (to evaluate) | lower accuracy, labelled |
| C7 Tools | Docker Lambda/Functions | Python/JS sandbox in a worker (existing Lambda/Functions cores) | no native deps, no container images |
| C8 Observability | VictoriaMetrics, Postgres spans | in-memory series + PGlite spans, persisted to OPFS | retention limited to browser storage |
| C9 Memory | Valkey + pgvector | in-memory TTL map + PGlite vectors, persisted | per-browser, not shared across devices |
| C10 Models and router | llama.cpp 3B + embed model; runner pool | **WebLLM**: 2-3 web models (0.5B fast, 1.5B default) with a router and fallback, an in-browser embedding model (WebLLM embedding models or transformers.js; to verify) | max ~1.5B, one model in VRAM at a time, small context; or link a Mesh |
| C12 Pipeline | NATS, MinIO, extraction workers | S3/event-bus cores in-process, pure-Python `pypdf` + docx/xlsx parsers in Pyodide, embeddings in browser | file size/count bounded by tab |
| C13 Governance | Postgres audit, Cedar, KMS | audit log in PGlite/OPFS, same KMS/IAM cores | not durable across devices |

**Making 0.5B-1.5B web models usable for an enterprise agent:**
- Constrained decoding for tool calls (WebLLM supports JSON-schema/grammar-constrained output; llama.cpp has GBNF on Mesh) so tool-call arguments are always valid JSON; verify the WebLLM function-calling path.
- Compact prompts: short tool schemas, retrieved passages trimmed to the context window (small on web models), summarising memory.
- A **scripted/deterministic backend** (registered through `vyomiRegisterLLM`) so every control-flow assertion (approval routing, tool loops, memory, citations) is testable without model variance. Conformance is about wire, state and control flow, never answer quality.
- WebGPU is required and not universal; without it the honest `ModelNotReady` error stays (no canned answers), and a linked Mesh or the scripted backend takes over.

**Test strategy for both substrates:**
- One suite, two runners: Mesh on a Codespace (real llama.cpp), Nano in real Chromium on the localhost portal (:8099, service worker) with (1) the scripted backend for hermetic runs in CI and (2) a WebLLM smoke run on a WebGPU machine (headless CI usually lacks WebGPU, so this run is a local or scheduled gate).
- The conformance matrix has a Mesh column and a Nano column per component and cloud; a Nano cell is "PASS", "PASS with declared limit" or "N/A (substrate)", never silently skipped.

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
| P0 | **API inventory from the official SDK/API models with in-scope/non-goal tags and per-service coverage numbers (the 100% denominator).** Reference app (Facilities agent) written only against native SDKs: channels, Strands + LangGraph agents, Lambda tools, Step Functions approval flow, S3 ingestion pipeline, IaC. Run it on Mesh, turn every "read from code" claim in section 2 into a measured pass/fail per SDK call; re-verify tool calling/streaming with real boto3, google-genai and openai SDKs; fix the rubric wording with the owner. | C2, C5, C7, C12 (and the baseline for all) |

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

### Nano lane (parallel to Phase 2, 3-4 weeks; WebLLM)
| WP | Content | Components |
|---|---|---|
| N1 | WebLLM seam upgrade: streaming, constrained-decoding tool calls, embeddings model in the browser, 2-3 model router with fallback, small-context prompt budgeting, scripted backend | C10, C3, C9 |
| N2 | Shared engines in the Nano core lists (memory, retrieval on PGlite with the same SQL, policy via cedar-wasm, guardrails v2, JWT issuer, audit log, eval runner) and `agent_spec_core` / `gcp_agentengine_core` / `cedar_engine` added to `nano-boot.js` | C1, C2, C4, C6, C8, C9, C11, C13 |
| N3 | Nano agent hosting: spec agents in a Pyodide worker, the user's real agent code via the local relay/endpoint, feasibility spike for pure-Python frameworks in Pyodide; Code Interpreter in a Pyodide worker | C3, C7 |
| N4 | Nano approvals and pipeline durability (OPFS/IndexedDB state, honest timer limits), PDF/Office extraction in Pyodide | C5, C12 |
| N5 | Nano packaging: WebGPU detection, model download/caching UX, storage quota handling, Mesh-link fallback | C10 |
| N6 | Nano conformance runner (scripted backend in CI, WebLLM smoke on WebGPU) and the Nano column of the matrix | all |

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
for each service (Mesh and Nano), cost/usage view.

### Phase 6: conformance suite and release gate (continuous, final week)
Per-component SDK suites (one contract test per in-scope operation, 100% required on Mesh) plus the end-to-end scenario run on a real Codespace Mesh in CI; the matrix (13 components x clouds)
published; "100%" is that matrix fully green with the declared non-goals.

### Coverage check (every component has at least one WP)
| Component | WPs |
|---|---|
| C1 Access and perimeter | A1, A2 |
| C2 Channels and interface | P0, F6 |
| C3 AgentCore Runtime | A3, A6a, N3 |
| C4 AgentCore Gateway | F4, A4, F6 |
| C5 Actions and approval | F5, A9, N4 |
| C6 Knowledge search (RAG) | F3, A6b, A7, N2 |
| C7 Tools (Lambda) | P0, A10 |
| C8 AgentOps and observability | F1, A5, A6c, A8b |
| C9 AgentCore Memory | F2, A5, N1, N2 |
| C10 Foundation models | F1, F7, A6d, N1, N5 |
| C11 Response generation | F6, A6b |
| C12 Knowledge processing pipeline | P0, F3, A7, A10, N4 |
| C13 Governance and security | F1, F4, A1, A5, A8a |

## 5. Estimate and order (rough, NOT measured)

About 17-22 weeks of single-agent effort including the Nano lane; with four parallel lanes (AWS, GCP, Azure, Nano) after Phase 1, about 9-12 weeks wall clock. Critical path:
P0 -> F1/F2/F3/F4 -> A3/A4 (real runtime + gateway), and in parallel P0 -> N1/N2 (WebLLM seam + shared engines in the Nano core lists). If the YC/demo story needs something earlier, the smallest visible slice
is: reference app on Mesh with real Bedrock Converse tool loop, KB RAG with citations, Step Functions approval, guardrails
(most exists), then Memory and the AgentCore container runtime.

## 6. Risks

- Nano: web models top out at ~1.5B and need WebGPU; tool-call reliability and context size are the weakest point (mitigations in 2.3). Browser memory/storage quotas bound corpus size, and real agent containers are impossible in a tab.
- Two substrates double the test surface; the shared-engine rule (one Python engine, two backends) and the scripted backend keep it manageable.
- 8 GB RAM vs real agent containers + model + engines: needs the AI profile and admission control; may force smaller model for tests.
- 3B model reliability for supervisor routing and multi-step plans: scripted backend for deterministic tests, honest labelling.
- AgentCore/Bedrock APIs move fast; pin the SDK versions the suite targets and record them in the matrix.
- Scope creep via "every" service: the matrix is the contract; anything outside it is a declared gap.
- Code-sharing hazard: these capabilities touch `core/*`, `consoles/src/**`, `wasm/**` which change only on the trunk
  (V4-BRANCH-ARCHITECTURE); lanes need claims in SESSION-CLAIMS.md and one branch per work package.

## 7. Decisions needed from the owner

0. (Answered 2026-11-14) Mesh and Nano both in scope, Nano against WebLLM web models; Nano may keep the Browser tool, long-running approvals and real agent containers Mesh-only; **Mesh must reach a hard 100%** (section 1). Still open: approve the non-goals list (which API operations are out of scope), and the bring-your-own-model switch (section 7A).

1. Approve the conformance definition (section 1) and the "wire-compatible, not real products" rule for OpenSearch/Cognito/WAF.
2. Order: AWS lane first (matches the diagram) with GCP and Azure lanes starting after Phase 1, or all three at once.
3. Run the user's agent containers on Mesh (needs RAM budget) or keep spec-based agents only for the first release.
4. Is the reference app public (marketing + docs) or internal?
5. Relationship to the v4.0.0/4.0.1 release: these are post-beta work packages, not part of the beta cut.

## 7A. Enterprise readiness (what "sell to enterprises" adds on top of conformance)

Conformance proves the APIs behave like the clouds'. An enterprise purchase also needs these gates; each is a WP candidate to
confirm with the owner after Phase 0:

| Gate | What it requires |
|---|---|
| Honest positioning | Mesh is an environment to build and test enterprise agentic apps with native SDKs; it is not a production host and not a replica of model quality, managed-service SLAs or real classifier-grade guardrails. Marketing, docs and the console say so (existing "Dev Simplified" labels stay). Conformance claims name the pinned SDK versions. |
| Model quality gap | Local 3B models cannot represent production answers. Offer a **bring-your-own-model** switch: Mesh points `VYOMI_LLM_ENDPOINT` (OpenAI-compatible, already supported by `llm_core`) at the customer's own vLLM/TGI, or proxies to the customer's real Bedrock/Vertex/Azure OpenAI with their credentials. Needs an owner decision on egress, data handling and billing. |
| Tenant isolation | Per-customer Codespace (enterprise dedicated Codespaces already validated), per-session agent containers with cgroup limits, no cross-tenant state in shared engines (Cedar tenant attributes, key prefixes, row filters), tested. |
| Security review | Threat model for the new surfaces: agent containers and Code Interpreter/Browser sandboxes (escape, egress), the JWT issuer, the WAF, prompt-injection paths through memory and RAG. Independent review before GA. |
| Data handling | What leaves the Codespace (model endpoints, telemetry), retention and deletion of memory/audit/traces, encryption at rest with KMS cores, documented in terms. |
| SSO, audit, admin | Enterprise admin console already exists (portal); add SSO sign-in for Mesh users, exportable audit (the CloudTrail-wire log), usage and cost reporting per tenant. |
| Support and release | Version pinning (Mesh image tags, never `:latest`), release notes with the conformance matrix, regression gates in CI, a support/runbook path. |

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
