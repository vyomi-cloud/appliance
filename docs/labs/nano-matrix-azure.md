# Vyomi Labs on Nano, no Mesh: Azure (OpenAI / Foundry) coverage matrix

Measured 2026-11-25 on `origin/v4-on-main` b3c5bf98c (branch `v4/labs-nano-matrix-gcp-azure`). Question: what can a FREE user deploy and test in the browser on Nano with no Mesh signed in.
Nothing was built or fixed; this is a measurement. No WebLLM model was downloaded or run (model phase: pending, another agent). Raw logs: `nano-matrix-gcp-azure-evidence/`.

## Verdict

**0 of 13 chapters run on free Nano today. All 13 are "Needs Mesh".** Same three walls as GCP, but the Azure Nano backend is further along than the GCP one on the control plane and has two large data-plane holes (AI Search, Log Analytics / App Insights):

1. **The Deploy button refuses.** `labs.js` `needsMesh()` is true for every non-AWS cloud. Driven on `/nano/labs/?cloud=azure&layer=<id>` for all 13 chapters: every one answers "The Mesh is not available in this console. Sign in, then deploy again." (`ui-deploy-nano-nomesh.json`).
2. **Even with the gate lifted, no block can run.** The Nano worker loads Pyodide 0.26.2 and boto3/botocore only. All 52 runnable Azure blocks run through that worker in course order: 52/52 FAIL (38 `No module named 'azure'`, 9 + 2 `KeyError: VYOMI_AZURE_ENDPOINT / VYOMI_AZURE_HTTP_ENDPOINT` because the worker only sets AWS and GCP variables, 1 each `openai`, `jwt`, `opentelemetry`) (`nano-worker-run-as-written.json`).
3. **Behind that, the Nano backend has real gaps** (below), measured by recording every HTTP call the 52 blocks make against the reference simulator (298 requests, `recorded-requests-azure-reference.jsonl`), replaying them into the Nano service worker in the browser, and chaining targeted probes where ids differ (`nano-replay-azure.json`, `nano-chained-probe-azure-{1,2}.json`). AMQP traffic (Service Bus) is not captured by that method.

Reference result (`python -m vyomilabs.labrun azure 10 3 7 12 6 11 9 4 5 1 2 8 13`, venv python 3.13, in-process appliance on TLS localhost): **51 PASS, 1 BLOCKED** (`call_container_app.py`, needs a real container runtime, matches GAPS_azure.md), 0 FAIL (`labrun-reference-azure.log`). So every failure below is a Nano gap or a course/Nano mismatch, not a bad block.

## Chapter matrix

| Ch | Layer | Today | Potential on Nano | Reason and gap |
|---|---|---|---|---|
| 1 | Models | Needs Mesh | Runs with limits | ARM account, model list, deployments, `DeploymentNotFound` 404, embeddings (all-minilm-l6-v2) all served. Chat completion returns 503 `ServiceUnavailable` "No in-browser model is loaded" (c). `openai` imports in Pyodide only with `deps=False` (typing-extensions pin) (d). |
| 2 | Agent Runtime | Needs Mesh | Needs Mesh | Foundry assistants/threads/messages/runs and Container Apps ARM are served (12/12 and 6/6 replayed calls same status class). The runs need a model (c). `try_graph.py` builds a local FastAPI + langgraph app: fastapi does not import in Pyodide (d). `call_container_app.py` needs a container runtime, BLOCKED even in the reference (b). |
| 3 | Tools | Needs Mesh | Needs Mesh | Search service ARM, Table seed, function app plan/site/settings/zipdeploy all served. But zipdeploy of the course's v1 layout (`<name>/__init__.py` + `function.json`) is not parsed (ARM functions list is empty) and a call returns 500 "Entry point 'asset-status' not found in function source" (b). The sandbox is stdlib-only and the tools import `azure.data.tables`, `azure.search.documents` (b). |
| 4 | Knowledge Pipeline | Needs Mesh | Needs Mesh | Blob upload and Event Grid ARM served. **Azure AI Search data plane is not routed on Nano**: `PUT /indexes('facilities-kb')`, datasources, indexers, `search.post.search` all fall through to the S3 handler (`NoSuchBucket`) or 405 (a). Ingest function cannot execute (b). |
| 5 | Knowledge Search (RAG) | Needs Mesh | Needs Mesh | Entire chapter is AI Search queries and vector upserts: not routed (a). |
| 6 | Response Generation | Needs Mesh | Needs Mesh | Content Safety `text:analyze` served. Retrieval (AI Search) missing (a); generation needs a model (c); `file_search` and On Your Data need model plus index. |
| 7 | Agent Memory | Needs Mesh | Runs with limits | Table-backed long-term memory served (10/10 replayed), the "no managed memory API" probe passes. Short-term thread turn needs a model (c). |
| 8 | Agent Gateway | Needs Mesh | Runs with limits | APIM service, API, operations, policies, subscription, MCP server ARM all served. Gateway data-plane calls answer 502 BackendUnavailable because the backend is the function app that cannot run (b). |
| 9 | Actions and Approval | Needs Mesh | Needs Mesh | Service Bus ARM and the Table ledger (including the ETag 412) are served. `azure-servicebus` speaks AMQP 1.0 over TCP, which a browser cannot open; Nano has a REST Service Bus only (d). The two functions cannot execute (b). |
| 10 | Access and Perimeter | Needs Mesh | Runs with limits | Graph applications/addPassword/users, client-credentials token and Front Door WAF ARM served. `validate-jwt` on APIM served; the protected backend is a function (b). `azure-identity` insists on https for bearer tokens, so the plain-http preview needs the block's own workaround. |
| 11 | Channels and Input Guardrails | Needs Mesh | Runs with limits | Content Safety and RAI policy ARM served; the violent-prompt call needs a model (c); `inbox.py` is AMQP (d). |
| 12 | AgentOps and Observability | Needs Mesh | Needs Mesh | Workspace and App Insights component ARM and Monitor metrics served. **App Insights ingestion (`POST /v2.1/track`) answers 405 and the Log Analytics query endpoint answers 405** (a), so export, query and custom-table blocks fail. |
| 13 | Governance and Security | Needs Mesh | Runs with limits after one fix | Vault ARM, Activity Log served. `azure-keyvault-keys` sends `api-version=2026-04-01`; Nano's wire router sends dated `/keys` calls to App Configuration (404 "configuration store was not found"). `api-version=7.5` works (a). |

Counts: Runs in Nano 0/13, Runs with limits today 0/13, Needs Mesh 13/13. Potential once the SDK wall is solved: 6 chapters run with limits (1, 7, 8, 10, 11, 13), 7 stay Needs Mesh (2, 3, 4, 5, 6, 9, 12) until AI Search, Log Analytics / App Insights, function execution and Service Bus transport exist.

## Cause classes, with evidence

**(d) Azure SDK the browser cannot run (hits 52/52).** Azure is better placed than Google here: every `azure-*` package is pure Python. Pyodide probe over 33 packages (`pyodide-sdk-install-probe.json`): 28 install and import clean (azure-core, -identity, all `azure-mgmt-*` the course uses, -ai-agents, -ai-contentsafety, -servicebus, -data-tables, -storage-blob, -search-documents, -monitor-query, -functions, PyJWT, cryptography, uvicorn); 5 fail on dependency pins against Pyodide's bundled versions: `azure-keyvault-keys` (cryptography>=44.0.2 vs 42.0.5), `openai` (typing-extensions>=4.14), `fastapi` (typing-extensions>=4.16), `langgraph`, `azure-monitor-opentelemetry-exporter` (opentelemetry). With `deps=False` keyvault-keys, openai, langgraph import; fastapi and the exporter still do not (`pyodide-sdk-install-probe-deps-false.json`). Importing is not running: `azure-core`'s default transport is `requests`/urllib3 over sockets, and the worker's only HTTP shim patches botocore, so there is no XHR transport for azure-core, no `azure-*` base URL / env wiring in the worker, and AMQP (Service Bus) has no browser path. `wasm/` carries no Azure client wheel set (the botocore-lite approach exists only for AWS). The course does need the native SDK: it is the course premise.

**(b) Function sandbox.** `core/nano_triggers.py` serves function apps through `run_http_function` (restricted exec, stdlib subset, `azure.functions` shim). The course's four functions use the Python v1 layout and import `azure.data.tables`, `azure.search.documents`, `azure.core`; neither the layout nor the imports work. Affects ch3, 4, 5, 8 (backend), 9, 10 (protected backend), 12.

**(c) Needs a model.** With none loaded: chat completions -> HTTP 503 `ServiceUnavailable` "No in-browser model is loaded. Open Amazon Bedrock > Overview > Local model ..." (wrong cloud named); embeddings -> 200 (all-minilm-l6-v2 vector); unknown deployment -> 404 `DeploymentNotFound` as the course expects; Content Safety -> 200. Blocks that call a model: `try_models.py`, `try_more.py` (ch1: stream and chat 503; the `dimensions=256` and 404 parts still pass), `foundry_agents.py` and `try_graph.py` (ch2), `try_respond.py`, `guard.py`, `file_search.py`, `on_your_data.py` (ch6), `short_term.py` (ch7), `content_filter.py` (ch11), `run_agent.py` (ch12). None has a fallback; each fails at the first completion. The runner's "needs a model" escalation exists only on the AWS path.

**(a) Missing or incorrect Nano backend.**
- Azure AI Search data plane (indexes, datasources, indexers, documents search/index, vector queries). `core/azure_search_core.py` exists in the bundle but the wire router (`core/aws_wire_router.py` `_azure_service`) has no route for it: ch3 (kb-search), 4, 5, 6.
- Log Analytics query and data-collector, App Insights `/v2.1/track` ingestion: ch12.
- Key Vault keys on dated api-versions routed to App Configuration: ch13.
- Function app: v1 layout zip, function enumeration, execution: ch3 and dependants.

## Ranked gap list (effort guesses)

| # | Gap | Chapters | Effort |
|---|---|---|---|
| 1 | azure-* wheels + an `azure-core` transport over XHR (pyodide-http style), pinned to Pyodide's cryptography/typing-extensions, served from the bundle; env (`VYOMI_AZURE_*`) wired by the worker; https-for-bearer handling | all 13 | M to L, 2 to 4 weeks. Smaller than GCP because the packages are pure Python |
| 2 | Lift the Deploy gate and give blocks `needs_runtime` flags (only `call_container_app.py` has one) | all | S once #1 exists |
| 3 | AI Search data plane route in the Nano wire router over the existing `azure_search_core` | 3, 4, 5, 6 | M (1 to 2 weeks); vector and semantic ranker are the long tail |
| 4 | Function app: v1 layout + enumeration + execution beyond the stdlib sandbox | 3, 4, 8, 9, 10, 12 | L to XL; same root as GCP #3 |
| 5 | Log Analytics query + custom table ingestion, App Insights `/v2.1/track` | 12 | M |
| 6 | Service Bus over a browser transport (AMQP over WebSocket endpoint, or a REST-based lab variant) | 9, 11 | L |
| 7 | Key Vault routing for dated api-versions | 13 | S (hours) |
| 8 | Model-less behaviour and catalogue, error text naming the right console | 1, 2, 6, 7, 11, 12 | S for UX; model phase measured elsewhere |
| 9 | Container Apps execution | 2 | XL, offline needs Docker too; keep Mesh |

## Quality read: chapters 1, 3, 9, 13 (full text and code read)

**Chapter 1, Models.** The strongest Azure-specific teaching in the course: it makes the learner create a Cognitive Services account and deployments through `azure-mgmt-cognitiveservices` and then call the deployment name, not the model, which is exactly the thing newcomers get wrong. It shows `stream=True`, `dimensions=256` and the 404 `DeploymentNotFound`. Real `AzureOpenAI` client, models discovered from ARM rather than hard-coded. Weak: authentication is a fixed dev token and a key, with no managed-identity / key-less Entra path (what enterprises require for Azure OpenAI), no TPM/RPM quota or 429 handling, content filter deferred to chapter 11, and the lesson copy is identical to AWS and GCP.

**Chapter 3, Tools.** Uses the real Functions deployment flow (plan, site, app settings, zip deploy, host keys) and the approval-decision function uses ETag-conditional updates, which is a better concurrency story than the GCP twin. The weak points are enterprise ones the chapter itself half admits: connection string and search key sit in plain app settings (the text says Key Vault references would be right), the Python v1 `function.json` layout is the legacy programming model, there is no input-schema validation (`body["asset_id"]`), and least privilege is described but each function runs with the same full table connection string. Prose mentions a `request-approval` tool that is not in the blocks. Good mechanics, not yet a hardened tool tier.

**Chapter 9, Actions and Approval.** The best chapter in the Azure course: Table ledger as the system of record, Service Bus topic + `approver-inbox` over real AMQP with peek-lock/complete/abandon, an unauthorised approver refused, a parked caller that wakes on the status change, reject path, idempotent create, and a demonstrated 412 on a stale ETag. Honest note that Logic Apps and Durable Functions (human-interaction pattern) are the managed alternatives and are not used. Gaps: approver identity is a self-declared string checked against `@example.com`; no message TTL, dead-letter, escalation or timeout; the explain text still talks about callback tokens and workflows (AWS wording) that the lab does not use; "risk levels" in LEARN are not built.

**Chapter 13, Governance and Security.** Correct envelope pattern: random DEK, AES-GCM locally with the table name as associated data, Key Vault only wraps/unwraps, plus a direct encrypt round trip, and the Activity Log read for the control-plane trail. Honest that RBAC and access policies are not enforced. Gaps: no key rotation policy (the GCP twin has one, this one lists it in neither BUILD nor code), no soft-delete/purge-protection discussion, vault created with empty access policies and no RBAC separation of key admin and key user, and the audit check only asserts that operation names exist, not who performed them or that the log cannot be altered. Thin for an auditor-facing chapter; the encryption half is solid, the evidence half is not.

## Differences from the AWS course structure

- Same 13 chapters, order and narrative copy. AWS has 57 blocks (46 runnable); Azure has 85 (52 runnable): the surplus is `azlab.py`/`azdata.py` plumbing and four `.md` documents shipped as blocks in ch4.
- AWS needs boto3 only, and the worker already ships it with an XHR transport, so AWS chapters can run in the browser; Azure needs about 25 `azure-*` packages plus `openai`, `jwt`, `cryptography`, `langgraph`, `fastapi`, none of which the worker loads. The helpful difference: Azure SDKs are pure Python, so the gap is wheel packaging plus one transport.
- AWS marks Lambda-executing blocks with `needs_runtime` so the page can escalate per block. Azure marks one block; the function-calling ones (ch3, 5, 8, 9) are unmarked.
- Azure control plane (ARM) coverage on Nano is broad: nearly all ARM calls in the course were served. The Azure data planes the course leans on (AI Search, Log Analytics, App Insights) are the holes; AWS has no equivalent holes listed.
- Azure ch9 and ch11 depend on AMQP, which has no equivalent in the AWS course (SQS/SNS are HTTP).

## Appendix: every runnable block

`BR` = backend readiness if the SDK could run in the browser: OK served by Nano; MODEL needs a loaded model; SBX needs function or agent execution; AMQP Service Bus AMQP transport; A:... missing or incorrect Nano backend. Replay caveat: the replay carries recorded ids, so verdicts were confirmed with chained probes where ids differ; AMQP traffic is not in the recording, and the openai/httpx calls were not captured (probed directly).

| Ch | Block | Reference labrun | Nano as shipped | Same block in the Nano Pyodide worker | Nano backend if the SDK could run | Cause class | Detail |
|---|---|---|---|---|---|---|---|
| 1 | `create_openai.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | account + model list + deployments served (models listed are the Nano set) |
| 1 | `try_models.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: env VYOMI_AZURE_* unset (and no azure-* SDK) | MODEL | (c) model | chat 503 ServiceUnavailable; embeddings served (all-minilm-l6-v2) |
| 1 | `try_more.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing openai | MODEL | (c) model | stream needs a model; dimensions + unknown deployment 404 served |
| 2 | `foundry_agents.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | assistants/threads/messages/runs served (run output needs a model) |
| 2 | `try_graph.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: env VYOMI_AZURE_* unset (and no azure-* SDK) | MODEL | (c) model | local FastAPI app + langgraph + model; fastapi/uvicorn do not install in Pyodide |
| 2 | `deploy_container_app.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | Container Apps ARM served |
| 2 | `call_container_app.py` | BLOCKED | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | SBX | (b) function/agent sandbox | needs a running container: BLOCKED even in the offline reference without a Docker runtime |
| 3 | `create_search.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | Search service ARM + admin keys served |
| 3 | `seed.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | Table storage (azure-data-tables wire) served |
| 3 | `deploy_tools.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | SBX | (b) function/agent sandbox | plan/site/settings/zipdeploy served; v1-layout zip is not parsed (functions list is empty) |
| 3 | `call_tools.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | SBX | (b) function/agent sandbox | 'Entry point asset-status not found in function source'; sandbox has no azure.data.tables |
| 4 | `upload_docs.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | Blob + storage ARM served |
| 4 | `kb_index.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | A | (a) missing/incorrect Nano backend: AI Search data plane | PUT /indexes(...) is not routed (falls to the S3 handler: NoSuchBucket) |
| 4 | `indexer.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | A | (a) missing/incorrect Nano backend: AI Search data plane | datasources/indexers/run not routed |
| 4 | `check_search.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | A | (a) missing/incorrect Nano backend: AI Search data plane | docs/search.post.search not routed |
| 4 | `deploy_ingest.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | SBX | (b) function/agent sandbox | Event Grid + function ARM served; the ingest function cannot execute |
| 4 | `new_doc.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | A | (a) missing/incorrect Nano backend: AI Search data plane | blob upload served; search not routed |
| 5 | `inspect_index.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | A | (a) missing/incorrect Nano backend: AI Search data plane | not routed |
| 5 | `embed_docs.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | A | (a) missing/incorrect Nano backend: AI Search data plane | not routed (vector fields) |
| 5 | `try_search.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | A | (a) missing/incorrect Nano backend: AI Search data plane | not routed |
| 6 | `try_respond.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: env VYOMI_AZURE_* unset (and no azure-* SDK) | MODEL | (c) model | search not routed + chat 503 |
| 6 | `guard.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | A | (a) missing/incorrect Nano backend: AI Search data plane | Content Safety served; respond() path needs Search + model |
| 6 | `file_search.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: env VYOMI_AZURE_* unset (and no azure-* SDK) | MODEL | (c) model | assistants file_search tool needs a model |
| 6 | `on_your_data.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: env VYOMI_AZURE_* unset (and no azure-* SDK) | A | (a) missing/incorrect Nano backend: AI Search data plane | On Your Data uses the Search index + a model |
| 7 | `short_term.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: env VYOMI_AZURE_* unset (and no azure-* SDK) | MODEL | (c) model | threads + a model turn |
| 7 | `try_memory.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | Table-backed memory served |
| 7 | `no_managed_memory.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: env VYOMI_AZURE_* unset (and no azure-* SDK) | OK | - | probes that managed-memory routes 404: served |
| 8 | `create_gateway.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | APIM service, API, operations, policy, subscription served |
| 8 | `call_gateway.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | SBX | (b) function/agent sandbox | APIM gateway answers 502 BackendUnavailable: the backend is the function app |
| 8 | `policies.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: env VYOMI_AZURE_* unset (and no azure-* SDK) | SBX | (b) function/agent sandbox | same backend dependency |
| 8 | `mcp_server.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | APIM MCP server ARM served |
| 9 | `create_bus.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | Service Bus ARM (namespace/topic/subscription) served |
| 9 | `park_request.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | AMQP | (d) AMQP transport | Table ledger OK; azure-servicebus sends over AMQP 1.0/TCP, not possible from a browser; functions (SBX) |
| 9 | `approve_request.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | AMQP | (d) AMQP transport | AMQP receive + functions |
| 9 | `reject_request.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | AMQP | (d) AMQP transport | AMQP + functions; ETag 412 on Table served |
| 10 | `entra.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: env VYOMI_AZURE_* unset (and no azure-* SDK) | OK | - | Graph applications/addPassword/users served |
| 10 | `sign_in.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing jwt | OK | - | client-credentials token served; user password grant via the tenant token endpoint is the block's own workaround |
| 10 | `protect_gateway.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: env VYOMI_AZURE_* unset (and no azure-* SDK) | SBX | (b) function/agent sandbox | APIM validate-jwt served; the gateway backend is a function |
| 10 | `waf.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | Front Door WAF policy ARM served |
| 11 | `screen_input.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | Content Safety text:analyze served |
| 11 | `content_filter.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | MODEL | (c) model | RAI policy ARM served; the violent-prompt call needs a model |
| 11 | `inbox.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | AMQP | (d) AMQP transport | Service Bus AMQP receive |
| 12 | `create_observability.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | Log Analytics workspace + App Insights component ARM served |
| 12 | `run_agent.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: env VYOMI_AZURE_* unset (and no azure-* SDK) | MODEL | (c) model | agent run: model + functions |
| 12 | `export_telemetry.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing opentelemetry | A | (a) missing/incorrect Nano backend: App Insights ingestion | POST /v2.1/track -> 405 |
| 12 | `query_telemetry.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | A | (a) missing/incorrect Nano backend: Log Analytics query | POST .../workspaces/<id>/query -> 405 |
| 12 | `custom_table.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | A | (a) missing/incorrect Nano backend: Log Analytics query | data-collector + KQL query not served |
| 12 | `platform_metrics.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | Monitor metrics ARM served |
| 13 | `create_vault.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | vault ARM served |
| 13 | `make_key.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | A | (a) missing/incorrect Nano backend: Key Vault api-version routing | SDK sends api-version=2026-04-01 -> routed to App Configuration (404 'configuration store not found'); 7.5 works |
| 13 | `envelope.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | A | (a) missing/incorrect Nano backend: Key Vault api-version routing | same, for wrap/unwrap/encrypt |
| 13 | `audit.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing azure | OK | - | Activity Log served |
