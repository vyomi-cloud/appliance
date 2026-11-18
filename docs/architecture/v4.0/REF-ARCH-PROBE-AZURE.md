# Reference architecture on Azure: probe results (step 1)

Date 2026-11-18. Branch `v4/ref-arch-probe-azure`. Source: `examples/ref-arch-probe/azure/` (`run_probe.py` writes `results/azure-probe.json`).

## Method and honesty notes
- Real Azure SDKs (azure-mgmt-*, azure-servicebus, azure-data-tables, azure-cosmos, azure-search-documents, azure-storage-blob, azure-keyvault-keys, azure-monitor-*, openai `AzureOpenAI`), unmodified, against the **real appliance app (`server.py`) running in-process**, fresh state per probe. Nothing mocked.
- `CLOUDLEARN_TIER_ENFORCE=0`: on the Free tier Cosmos (and others) answer `tier_service_locked`, which is a product gate, not a capability result.
- No model was running (a `vyomi-llm` container exists on this Mac but was deliberately not used): model steps are BLOCKED(no model); their API surface is still exercised.
- Cause codes: (a) simulator missing the API, (b) simulator wrong behaviour, (c) needs a model, (d) my probe / SDK usage (SDK refuses non-TLS bearer auth, etc.).
- Service Bus entities in the loop are seeded through the runtime store (harness shortcut) because no native control path reaches the AMQP store (gap G2).
- Only the appliance server was probed. The shared wire router (Nano) serves some paths the appliance does not (e.g. `/openai` GET works in `core.wire_ingress` alone); Nano was not run.

## Summary
| # | Component | Result | Native or assembled | Blocking gaps |
|---|---|---|---|---|
| 1 | Access | FAIL | native | Entra token is not a JWT, no JWKS, no WAF resource types |
| 2 | Channels | FAIL | native | Content Safety not routed; ARM-created Service Bus entities invisible to AMQP |
| 3 | Runtime | FAIL | Assistants + Container Apps | `/openai` GETs 404 on the appliance; Foundry project endpoint absent |
| 4 | Gateway | FAIL | APIM | `choose/when @(...)` skipped; MCP API type not served; no Cedar equivalent on Azure |
| 5 | Approval | FAIL (loop PASSES with workarounds) | assembled | Table PATCH / $filter / ETag; late AMQP delivery; Cosmos ETag / `_self` / patch |
| 6 | Knowledge | FAIL | native | SearchClient wire (`indexes('x')`, host endpoint); engine itself OK |
| 7 | Tools | FAIL | native | ARM function list/keys empty after zipdeploy, param query, hostname form |
| 8 | Observability | FAIL | native | `/v2/track` not served, no AppTraces table |
| 9 | Memory | FAIL | short-term only | thread GET/DELETE 404 (same `/openai` routing) |
| 10 | Models | BLOCKED (no model) | native | embeddings PASS; chat needs a model |
| 11 | Response | FAIL / BLOCKED | native | vector-store file list 404; citations need a model |
| 12 | Pipeline | FAIL | native | no BlobCreated delivery to the function; indexer fills nothing |
| 13 | Governance | BLOCKED(d) | native | KV wrap/unwrap and Activity Log PASS over REST; SDK step blocked by TLS rule |

Step counts per component are in `results/azure-probe.json`.

## Per component
Only non-PASS steps are listed; everything else in the probe passed.

### 1 Access (FAIL)
| Step | Call | Error | Cause |
|---|---|---|---|
| token is a JWT | `POST /{t}/oauth2/v2.0/token` client_credentials | `access_token` is `vyomi.<hex>`, 2 segments | b |
| JWKS | `GET /{t}/discovery/v2.0/keys` | 404 NoSuchBucket (falls to S3) | a |
| APIM validate-jwt with the Entra token | gateway GET with `Authorization: Bearer <entra token>` | 401 "Access token is missing or invalid" (an HS256 JWT signed with the policy key is accepted) | b |
| WAF, Front Door | `FrontDoorManagementClient.policies.begin_create_or_update` | `ResourceTypeNotSupported` Microsoft.Network/FrontDoorWebApplicationFirewallPolicies | a |
| WAF, App Gateway | `web_application_firewall_policies.create_or_update` | `ResourceTypeNotSupported` | a |
| azure-identity credential | `ClientSecretCredential(authority=http://...)` | MSAL needs https | d (BLOCKED) |

APIM subscription-key check and garbage-token rejection PASS. **Answers the doc's "WAF unverified": WAF is not simulated.**

### 2 Channels (FAIL)
- Content Safety: `ContentSafetyClient.analyze_text` returns `MethodNotAllowed` (S3 XML): not routed (a).
- ARM `topics/subscriptions.create_or_update` PASS, but `get_topic_sender("approvals")` over AMQP: `MessagingEntityNotFoundError amqp:not-found` (a/b). The AMQP listener reads `core.azure_servicebus_runtime.get_store()`; ARM and the wire PUT write to the space state store. Entities seeded into the runtime store work: send, receive, complete over AMQP PASS.
- PASS: RAI policy via ARM; a violent prompt on a deployment with that policy is refused `400 content_filter` before any model is called.

### 3 Runtime (FAIL)
- Assistants: create agent, thread, run PASS. Run ends `failed` with the LLM-seam 503 (BLOCKED, c).
- `threads.retrieve`, `runs.retrieve`, `messages.list`: 404. `routes/aws_s3.py` routes `/openai/*` to the shared router **only for POST** (a/b); GETs fall to S3.
- `azure-ai-agents AgentsClient` at `/api/projects/p1`: `{"detail":"Not found"}` (a).
- Container Apps env + app via ARM PASS; the returned FQDN does not resolve and no local URL is exposed (a).

### 4 Gateway (FAIL)
PASS: API + 3 operations (tool catalog), subscription keys, `rate-limit` (429), `set-header`, `return-response`. FAIL: `choose/when` with `@(...)` is skipped (`x-vyomi-apim-skipped-policies: choose`; a). MCP: api `type=mcp` accepted by ARM but the gateway `tools/list` returns 404 (a). **Cedar-like policy engine: does not exist on Azure natively; the substitute is APIM policy expressions, which here are not evaluated.**

### 5 Approval (assembled; the key row)
The full loop PASSES: request -> Service Bus topic/subscription over AMQP -> approver -> Function App function -> Table ledger -> waiting caller sees `approved` (about 3 s). It only passes with these workarounds:
1. Service Bus entities seeded into the runtime store (G2).
2. The approver re-attaches a short-lived receiver every 2 s: an already-attached receiver is **never handed a message sent later** (0 messages in 10 s; b).
3. The function writes the ledger with stdlib `urllib` over the Table REST wire: function code that does `import azure.functions` then `import azure.data.tables` fails `ModuleNotFoundError: azure.data` because the azure.functions shim shadows the `azure` namespace (b).

Ledger on Table (azure-data-tables 12.7): create, get, replace (PUT), upsert PASS. FAIL: merge `update_entity(MERGE)` sends real `PATCH`: `UnsupportedHttpVerb` (a); `query_entities("status eq 'x'")` -> `Malformed entity key` (b); stale ETag accepted, no 412 (b).
Ledger on Cosmos (azure-cosmos): upsert, read, replace by id, SQL query, COUNT PASS. FAIL: stale ETag accepted (b); `replace_item(<item dict>)` follows the returned `_self` link: `Database '<rid>' not found` (b); `patch_item` 405 (a).

**Real-backend finding (corrects REFERENCE-ARCH-GCP-AZURE.md).** The doc says Table storage is "real offline (Azurite mirror)". Per `core/capabilities/backends/azure.json` and the probe, only **Blob bytes** are mirrored to Azurite; Queue and Table data live in Vyomi's own state slots. Service Bus (own core + own AMQP engine) and Cosmos (own core) are also Vyomi's own. So the proposed "ledger on Azurite Table = real engine" is not true today. Azurite is running on this Mac (`vyomi-vyomi-azurite-1`) but no ports are published and the Table path never reaches it.

Proposed fix (choose one; recommendation first):
| Option | Work | Est. |
|---|---|---|
| A. State plainly that the ledger runs on Vyomi's Table core; fix PATCH, `$filter`, ETag 412 so it is native-SDK correct | route PATCH, parse `ledger()?$filter`, enforce If-Match | 1.5 d |
| B. Wire the Table service to Azurite (proxy Table REST to the Azurite Table port; unpublished port needs compose change) on Mesh/offline, keep own core for Nano | proxy layer + compose port + state-slot sync decision + tests | 3-4 d |
| C. Ledger on Cosmos (own core, no real engine) | fix ETag, `_self`, patch | 1.5 d |
Recommend A now (needed anyway; B includes A's wire fixes), B only if "real engine" is required for the ledger in the claim.

### 6 Knowledge (FAIL)
- ARM service + admin key PASS; the advertised endpoint `https://<svc>.search.windows.net` is not served (a). The data plane is only on an ARM-extension path `.../searchServices/{svc}/indexes/{name}/...`.
- `SearchIndexClient.create_index` PASS there. `create_or_update_index`, `upload_documents`, `search` (BM25, vector, hybrid, semantic) all FAIL: SDK sends `indexes('kb')` / `docs/search.post.search`; response `Unknown search service operation "indexes('kb')"` (a).
- Engine-level raw REST on the extension path: BM25, vector, hybrid (RRF), and semantic (`@search.rerankerScore`) all PASS. So the gap is **wire compatibility**, not the engine.

### 7 Tools (FAIL)
PASS: Cosmos create/read/query/delete/aggregate; Function App create, zipdeploy, invoke (POST body and GET query) at `/azure-data/functions/{app}/api/{fn}`. FAIL: parameterised query `WHERE c.kind = @k` returns `[]` (b); ARM `list_functions` is empty and `list_function_keys` 404 after zipdeploy (b); the `<app>.azurewebsites.net/api/<fn>` host form 404 (a). Function create via ARM `begin_create_function` stores no code (code only arrives via zipdeploy; one function per app).

### 8 Observability (FAIL)
PASS: workspace + App Insights component, exporter run, custom-table ingest + KQL where/summarize/extend/avg, Monitor metrics, OTLP. FAIL: `POST /v2/track` 405 (a); `AppTraces` table unknown, so App Insights telemetry is not queryable in the workspace (a). `LogsQueryClient`: BLOCKED(d), also documented as not modelled (api.loganalytics.io host).

### 9 Memory (FAIL)
Thread create + messages + metadata PASS. `threads.messages.list`, `threads.delete`: 404 (same `/openai` GET/DELETE routing). Recall via a run: BLOCKED(c). **Confirmed: no managed long-term memory API exists** (`/openai/memory_stores` and `/openai/memories` are absent); long-term memory remains an app pattern on Cosmos/AI Search, not a managed feature.

### 10 Models (BLOCKED, no model)
PASS: deployment list, embeddings (2 x 1536, `dimensions=256`), unknown deployment 404. BLOCKED(c): `chat.completions` (plain, tools, stream) and `responses.create` return the native 503 "Local LLM endpoint ... not reachable".

### 11 Response (FAIL / BLOCKED)
PASS: vector store, file upload and attach, output-source RAI policy accepted by ARM. FAIL: `vector_stores.files.list` 404 (a, same routing). BLOCKED(c): file_search run, `file_citation` annotations, run steps, On-Your-Data. Citations remain unproven (need a model plus the GET fix).

### 12 Pipeline (FAIL)
PASS: Blob upload/download, Function with a blob handler, Event Grid system topic + WebHook subscription, indexer/datasource create and run calls. FAIL: no BlobCreated delivery to the function was observable (a); the indexer run leaves the index empty (a).

### 13 Governance (BLOCKED(d))
PASS: Key Vault via ARM; envelope encryption over the Key Vault REST wire (create RSA key, `wrapkey`, `unwrapkey` round-trip); Activity Log lists the run's operations (also filtered by resource group). BLOCKED(d): `KeyClient` SDK refuses bearer auth over non-TLS even with a transport shim (needs a TLS front, not a simulator gap).

## Gaps and estimates
| ID | Gap | Cause | Est. |
|---|---|---|---|
| G1 | `/openai` GET/DELETE routing on the appliance (also vector-store files, thread/run/message reads); Foundry project endpoint | a | 0.5 d (routing) + 2 d (Foundry agents surface) |
| G2 | Service Bus entities from ARM/wire not visible to AMQP (one store); live delivery to attached receivers | a/b | 1.5 d |
| G3 | Table PATCH, `$filter`, ETag 412; Cosmos ETag 412, `_self`, patch, param query | a/b | 2 d (A) |
| G4 | AI Search native wire: `indexes('x')`, host/endpoint form, `search.post.search` | a | 2 d |
| G5 | Entra tokens as signed JWTs + JWKS + openid-config (so validate-jwt works on the real chain) | b | 1.5 d |
| G6 | WAF policy resource types (Front Door + App Gateway), CRUD only | a | 1 d |
| G7 | Content Safety `text:analyze` | a | 1 d |
| G8 | APIM `@(...)` expressions in choose/when; MCP API type | a | 2 d |
| G9 | Function: azure.functions shim shadowing `azure.*`; ARM function list/keys after zipdeploy; hostname form | b | 1.5 d |
| G10 | App Insights `/v2/track` + AppTraces table | a | 1.5 d |
| G11 | Event Grid BlobCreated delivery to a function + indexer fill from Blob | a | 2 d |
| G12 | Optional: Table on real Azurite (option B) | decision | 3-4 d |
| | Total (G1-G11, excl. G12) | | about 16.5 d |

## Updated Azure-half estimate
REFERENCE-ARCH assumed step 3b (Azure app) 4-5 d plus a share of step 4 (floor 2-3 d for both clouds). The probe shows the Azure gaps alone are about 16.5 d (up to about 20 d with option B), well above the doc's floor. Recommended cut for a first Azure demo: G1, G2, G3, G4, G9 (about 8 d) make the assembled approval loop and RAG path native-SDK clean; G5-G8, G10, G11 can follow. Azure half total: step 3b 4-5 d + gaps 8-16.5 d = about 12-21 d, versus about 6-8 d implied before.

## Not run
Nano (shared wire router) second pass; a real model (all c-cause steps); TLS-fronted SDK paths (KeyClient, LogsQueryClient, azure-identity).
