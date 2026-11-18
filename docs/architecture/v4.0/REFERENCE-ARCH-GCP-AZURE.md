# Reference architecture on GCP and Azure: component mapping and scope

Status: proposal + probe results (step 1 done), nothing built. Written 2026-11-18 against v4-on-main (v4.0.4 + later trunk commits).

## Where we are
`examples/enterprise-facilities-agent` implements the 13 components of "Agentic AI on AWS Bedrock" with boto3 only (13/13 end to end, Mac, real local model).
GCP and Azure have service-level coverage (1472-claim capability sweep, AI smokes) and a one-agent triage demo (`examples/agent-workflow/agent_gcp.py`, `agent_azure.py`).
They do not have a 13-component application. This doc maps each component to the native GCP and Azure service, says what the simulator has, and sizes the work.

Method: component list from `facilities/components/c01..c13`; simulator coverage from `core/capabilities/{gcp,azure}/*.json` and `core/*_core.py`.
"Present" means a core and capability entry exist; it does NOT mean the specific API call the app needs is covered. Every row needs a probe before build (step 1 of the plan).

## Mapping

| # | Component (AWS) | GCP native | Azure native | GCP state | Azure state |
|---|---|---|---|---|---|
| 1 | Access: Cognito + WAF + API Gateway JWT | Identity Platform / Google ID tokens, API Gateway (JWT), Cloud Armor | Entra ID tokens, APIM `validate-jwt`, WAF on Front Door / App Gateway | API Gateway present; ID tokens via iamcredentials/WIF; **no Identity Platform, Cloud Armor not found** | Entra tokens (graph/webauth cores) and APIM validate-jwt present; **WAF policy unverified** |
| 2 | Channels: input guardrail + approver inbox (SNS to SQS) | Model Armor `sanitizeUserPrompt`; Pub/Sub topic to subscription | Content filters (raiPolicies) / Content Safety; Service Bus topic to queue | Present | Present (Content Safety partial) |
| 3 | Runtime: AgentCore Runtime (supervisor + sub-agents) | Vertex Agent Engine `reasoningEngines` (or Cloud Run) | Foundry Agents (Assistants) or Container Apps / Functions hosting the LangGraph app | Present (Agent Engine core) | Foundry Agents present; **no hosted-code runtime like AgentCore, so the app runs on Container Apps** |
| 4 | Gateway: MCP tool catalog + Cedar policy | agentGateways / mcpServers registry + agentPolicies (Cedar) | APIM as tool/MCP front, Foundry function tools | Present (agentgov core) | APIM present; **MCP-over-APIM and Cedar-style policy not found: use APIM policy, document the difference** |
| 5 | Approval: Step Functions waitForTaskToken + SNS inbox + ledger | Cloud Workflows callbacks + Pub/Sub + Firestore | Logic Apps / Durable Functions + Service Bus + Cosmos | **Workflows not found (biggest GCP gap)** | **Logic Apps and Durable Functions not found (biggest Azure gap)** |
| 6 | Knowledge search: Bedrock KB (vector, hybrid, rerank) | RAG Engine, Vector Search, Vertex AI Search | Azure AI Search (BM25, vector, hybrid, semantic ranker) | Present | Present |
| 7 | Tools: Lambda + DynamoDB | Cloud Functions / Cloud Run + Firestore | Functions + Cosmos DB | Present | Present |
| 8 | Observability: X-Ray + CloudWatch | Cloud Trace, Logging, Monitoring | Application Insights, Log Analytics, Monitor | Present (trace core) | Present (App Insights partial) |
| 9 | Memory: AgentCore Memory (session + long-term) | Agent Platform Sessions + Memory Bank | Assistants threads (short-term); no managed long-term equivalent | Present | **Short-term only; long-term would be our own pattern on Cosmos/AI Search, must not be marketed as a managed Azure feature** |
| 10 | Models: Converse + embeddings | Gemini generateContent, embedContent | Azure OpenAI chat + embeddings deployments | Present | Present |
| 11 | Response: grounded cited answer + output guardrail | Grounding via RAG Engine + Model Armor sanitizeModelResponse | Assistants file_search citations / on-your-data + content filter | Present | Present (citations not exercised in the headless smoke) |
| 12 | Pipeline: S3 to embeddings to KB, re-ingest on upload | GCS + Eventarc + Function + RAG file import | Blob + Event Grid + Function + AI Search indexer | Present | Present |
| 13 | Governance: KMS envelope + CloudTrail | Cloud KMS + Cloud Audit Logs | Key Vault + Activity Log | Present | Present |

## What the mapping shows
- 9 of 13 components per cloud map to services the simulator already has. The 4 problem rows are 1 (access/WAF), 4 (gateway policy), 5 (approval workflow) and 9 on Azure.
- **Component 5 is the real gap on both clouds.** The cloud-native orchestrator with a human-approval callback (Cloud Workflows, Logic Apps / Durable Functions) is absent. Per the standing rule we do not write our own backend: options are (a) build the approval as Pub/Sub or Service Bus + Functions + a ledger table, which is a legitimate cloud pattern but not the orchestrator, or (b) add the orchestrator on an open-source lightweight engine. Recommend (a) for the first cut and state it plainly in the report; (b) only if customers ask.
- The two clouds are not isomorphic with AWS. The reference app must be honest where a component differs (Azure has no hosted-agent runtime, no managed long-term memory; GCP has Agent Engine and Memory Bank). The report should show "native equivalent" or "assembled from parts" per row.

## Scope (rough; assumes the reuse below)

Reuse: `run_e2e.py`, `report.py`, `runtime.py` (Blocked/PASS/FAIL model), fixtures and the LangGraph agent logic. Step 2 makes them cloud-neutral.

| Step | Work | Estimate |
|---|---|---|
| 0 | Decide the open questions below | 0.5 d (owner) |
| 1 | Probe: for each of the 26 rows, run the exact SDK calls against the simulator; mark PASS/BLOCKED | 1.5 d |
| 2 | Refactor the harness to be cloud-neutral (component interface, per-cloud runtime/naming, shared report) | 1.5 d |
| 3a | GCP app: 13 components on google-cloud SDKs, approval via Pub/Sub + Firestore (no Workflows) | 4-5 d |
| 3b | Azure app: 13 components on azure SDKs, approval via Service Bus + Functions + Cosmos | 4-5 d |
| 4 | Fix simulator gaps the probe finds, plus the real-backend wiring above (floor 2-3 d) | 4-7 d |
| 5 | README, report, Mesh packaging (`vyomi-agent-demo --cloud gcp|azure`), claims register entries | 1.5 d |

Total about 13-18 working days sequential; about 10-12 with two parallel lanes (3a and 3b) after step 2. These are estimates; step 1 is the one that tightens them.

## Verification plan
Same bar as AWS: exit 0 only if all 13 components PASS, real local model, unmodified vendor SDKs, no mocked results, BLOCKED reported as BLOCKED. Then run on a Mesh Codespace (blocked today by the 402 budget error). Nothing is claimed publicly until the claims register has the entries.

## Decisions (owner, 2026-11-18)
- **Approval pattern: assembled** (messaging + function + ledger), not a workflow orchestrator.
- **"Real backend":** the approval path must run on real open-source engines, not on Vyomi's own record-keeping cores, wherever the substrate can run a container (Mesh / offline). Standing rule applies: no new backend of our own.

### What is real today behind the approval path (from `core/capabilities/backends/*.json`)
| Need | GCP | Azure |
|---|---|---|
| Approver inbox (messaging) | Pub/Sub: Vyomi's own core on the SNS/SQS store. A real Google Pub/Sub emulator container exists but is NOT the v4 data plane | Service Bus: Vyomi's own core with a real AMQP 1.0 data plane (pure Python). The Microsoft emulator was rejected earlier (not viable) |
| Ledger (state) | Firestore: Vyomi's own core. A real Firestore emulator container exists but is NOT the v4 data plane | Cosmos DB: Vyomi's own core, no Cosmos engine. Azure Table storage is real offline (Azurite mirror) |
| Tool code | Cloud Run functions: Python really executed in Vyomi's sandbox | Function App: Python in a restricted sandbox |

### Proposed real-backend choice (Mesh / offline)
- **GCP:** Pub/Sub on the real Google Pub/Sub emulator and the ledger on the real Firestore emulator, both already in the repo as cores (`gcp_pubsub_emulator`, `gcp_firestore_emulator`). Work: make them selectable as the data plane for this app (not default for everyone) and prove the approval flow through them.
- **Azure:** Service Bus on its real AMQP 1.0 data plane (our implementation of the real wire, verified with `azure-servicebus`), ledger in Azure Table storage on Azurite (real engine) instead of Cosmos, which has no real engine we can run cheaply.
- **Nano:** no containers in the browser, so Nano keeps Vyomi's in-browser cores and the report states that. Mesh is the "real backend" run.
- Added scope: about 2-3 days (GCP emulators as data plane 1-1.5 d, Azure Table ledger + AMQP flow 1-1.5 d), included in step 4 below as a floor.

## Probe results (step 1, 2026-11-18) and corrections
Probes: branches `v4/ref-arch-probe-gcp` (572cad779, `docs/architecture/v4.0/REF-ARCH-PROBE-GCP.md`) and `v4/ref-arch-probe-azure` (a089a3606, `REF-ARCH-PROBE-AZURE.md`). Real vendor SDK calls against the in-process appliance app; no model, so model steps are BLOCKED. macOS only; Nano and Mesh were not probed.

**Result: the assembled approval loop PASSES end to end on both clouds** (GCP: Pub/Sub, function, Firestore ledger; Azure: Service Bus AMQP, Function, Table ledger, about 3 s), but Azure needed three workarounds. No component passes cleanly on the unmodified default clients: GCP 2 of 13 PASS (gateway, knowledge), Azure 0 of 13 PASS, the rest FAIL or BLOCKED(no model).

Corrections to the mapping above:
- **Cloud Armor** securityPolicies exist (create/get pass); "not found" was wrong. **Identity Platform** is absent (405).
- **Azure Table is NOT real offline.** Table data, Service Bus and Cosmos are all Vyomi's own cores; only Blob bytes are mirrored to Azurite. The "Table on Azurite" real-backend proposal above does not hold today.
- **GCP real emulators work but are not the data plane.** Docker is present, the local `google-cloud-cli:emulators` image runs real Pub/Sub and Firestore emulators, and the approval loop passes on them with the gRPC clients. Selecting them as the data plane is real build work (about 2.5 d).
- **Azure Service Bus:** ARM/REST-created entities are invisible to AMQP, and an attached receiver never gets a later message (the probe re-attached every 2 s).
- **Azure `/openai` GET/DELETE** fall through to S3 in the appliance, so thread/run/message reads 404; that also blocks components 9 and 11.

### Gaps and estimates (probe lanes' figures, not independently verified)
GCP: gRPC front door / real emulators 2.5 d; function sandbox has no network or SDKs (blocks 5, 7, 12) 2.5 d; Identity Platform 0.5 d (drop) to 2.5 d (build); API Gateway YAML + token check 1 d; four small core fixes (logging timestamp filter, trace v1 span id, KMS AAD, event-function print) 1.5 d; GCS notifications 1 d; generateContent with a RAG retrieval tool 1.5 d. GCP half about 18-21 d (floor about 14 d on REST transports and no Identity Platform).
Azure: `/openai` routing + Foundry endpoint 2.5 d; Service Bus unification + live delivery 1.5 d; Table/Cosmos wire fixes (PATCH, $filter, ETag 412, patch_item) 2 d; AI Search native wire 2 d; Entra JWT + JWKS 1.5 d; WAF types 1 d; Content Safety 1 d; APIM expressions + MCP 2 d; Function shim + ARM list 1.5 d; App Insights ingest 1.5 d; Event Grid delivery + indexer 2 d. Gaps about 16.5 d; Azure half about 12-21 d.

### Revised programme total
Sequential about 33-45 working days (GCP 18-21 + Azure 12-21 + shared harness refactor 1.5 + docs/packaging 1.5). With two parallel lanes about 18-24 days. The earlier 13-18 d figure is withdrawn.

### Options to cut scope
1. **Fix the simulator gaps that real customers' SDK code hits first** (the "default client works" items: gRPC, `/openai` routing, Search wire, Entra JWT) and let the app use REST workarounds elsewhere, reported as BLOCKED rows. About 15-20 d total.
2. **Ship one cloud first.** GCP is closer (4 of 13 close to green; the approval loop works), Azure needs more wire fixes.
3. **Reduce the claim:** keep the AWS reference as the "13-component reference" and call GCP/Azure "agent app development on the services" (the current public wording), until the gaps close.

## Open questions for the owner
1. Confirm "real backend" means this: real open-source engines behind the approval path on Mesh, Nano on in-browser cores? (If you meant every service in the app, say so; that is a much larger scope.)
2. Is "reference architecture on GCP and Azure" a goal for the Beta, or after Codespace verification and the licence work?
3. Is a map of "native equivalent vs assembled from parts" acceptable in the public wording?
4. Where does it run first: Nano (in-browser model only) or Mesh only?
