# Reference architecture on GCP and Azure: component mapping and scope

Status: proposal, nothing built. Written 2026-11-18 against v4-on-main (v4.0.4 + later trunk commits).

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
| 4 | Fix simulator gaps the probe finds (unknown until step 1; budget) | 2-4 d |
| 5 | README, report, Mesh packaging (`vyomi-agent-demo --cloud gcp|azure`), claims register entries | 1.5 d |

Total about 11-15 working days sequential; about 8-10 with two parallel lanes (3a and 3b) after step 2. These are estimates; step 1 is the one that tightens them.

## Verification plan
Same bar as AWS: exit 0 only if all 13 components PASS, real local model, unmodified vendor SDKs, no mocked results, BLOCKED reported as BLOCKED. Then run on a Mesh Codespace (blocked today by the 402 budget error). Nothing is claimed publicly until the claims register has the entries.

## Open questions for the owner
1. Is "reference architecture on GCP and Azure" a goal for the Beta, or after Codespace verification and the licence work?
2. Component 5: ship the assembled pattern (recommended) or add Workflows / Logic Apps first?
3. Is a map of "native equivalent vs assembled from parts" acceptable in the public wording?
4. Where does it run first: Nano (in-browser model only) or Mesh only? Headless Nano has no local model, so agent steps would be BLOCKED there, as on AWS.
