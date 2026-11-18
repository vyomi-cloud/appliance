# Reference architecture, GCP half: probe results (step 1)

Run 2026-11-18 on a Mac (arm64, Python 3.13), simulator started in-process the way `examples/enterprise-facilities-agent/facilities/server.py` does, fresh state per probe, **no model available**. Code: `examples/ref-arch-probe/gcp/` (`run_probe.py` writes `results/gcp-probe.json`). Nothing was mocked and nothing in the simulator was changed. Status per component: FAIL if any step failed, else BLOCKED if any step needs a model, else PASS. Per-step detail is in the JSON; the failing steps are listed below.

Cause classes: (a) simulator missing the API, (b) simulator wrong behaviour, (c) needs a model, (d) my probe or SDK usage.

## Summary

| # | Component | Status | One line |
|---|---|---|---|
| 1 | Access | FAIL | Identity Platform absent; API Gateway rejects YAML specs and its own ID tokens; Cloud Armor PASS (doc said "not found") |
| 2 | Channels | FAIL | Model Armor and Pub/Sub PASS on REST; the default gRPC client cannot connect |
| 3 | Runtime | FAIL | Agent Engine create/get PASS with a Vyomi spec; a real packaged (pickle) agent cannot run; :query needs a model |
| 4 | Gateway | PASS | agentGateways, mcpServers, agentPolicies (Cedar allow/deny) work; no public Google SDK exists, shapes are Vyomi's own |
| 5 | Approval | FAIL | The assembled loop PASSES end to end (Pub/Sub + function + Firestore); a function cannot write the ledger itself; high-level Firestore client is gRPC-only |
| 5b | Approval on real emulators | FAIL | Real emulators run on this Mac and carry the loop; they are NOT the simulator's data plane |
| 6 | Knowledge | PASS | RAG corpus, GCS import, retrieveContexts, Vector Search, Vertex AI Search all PASS (hash embedding, see notes) |
| 7 | Tools | FAIL | Function deploy + HTTPS invoke PASS; function cannot reach Firestore (sandbox) |
| 8 | Observability | FAIL | Trace write PASS, v1 read broken; Logging/Monitoring SDKs gRPC-only; list_entries returns nothing |
| 9 | Memory | BLOCKED | Sessions + Memory Bank create/retrieve PASS via `vertexai.Client`; only `memories:generate` needs a model |
| 10 | Models | BLOCKED | embedContent PASS; generateContent needs a model (503) |
| 11 | Response | FAIL | sanitizeModelResponse PASS; generateContent with a RAG retrieval tool is rejected |
| 12 | Pipeline | FAIL | No GCS notification API; Eventarc fires but the event function errors; RAG import + re-ingest PASS |
| 13 | Governance | FAIL | KMS works but ignores additional_authenticated_data; admin audit entries PASS |

Real PASS today: 4, 6 and the REST halves of 2, 5, 9, 10. The doc's "9 of 13 present" is true at service level and optimistic at call level.

## Failing and blocked calls

| # | Call | Error text (trimmed) | Cause |
|---|---|---|---|
| 1 | `POST /v1/accounts:signUp` (Identity Platform) | HTTP 405 MethodNotAllowed (S3-style XML) | (a) missing API; confirmed by trying |
| 1 | API Gateway `configs` create with a PyYAML-dumped OpenAPI file | 400 "Cannot parse the OpenAPI document: unexpected list item at line 12." | (b) hand-rolled YAML parser (`core/gcp_apigateway_core.parse_openapi`); also fails flow-style `{...}` |
| 1 | `GET /gcpgw/gw1/ask` with a token from iamcredentials `generateIdToken` | 401 "Jwt verification fails" (no-token 401 is correct) | (b) simulator cannot verify its own ID token |
| 2 | `pubsub_v1.PublisherClient()` (default gRPC) with `PUBSUB_EMULATOR_HOST` = simulator | 503 "Failed parsing HTTP/2 ... Trying to connect an http1.x server" | (a) front door is HTTP/1.1 only; REST transport PASSes |
| 3 | `create_reasoning_engine(package_spec=pickle from GCS)` then `:query` | 400 "no Vyomi agent spec ... the simulator does not run pickle" | (a) documented; real LangGraph/ADK deploy flow unsupported |
| 3 | `reasoningEngines/ID:query` | 503 "Local LLM endpoint http://vyomi-llm:8080 is not reachable" | (c); request shape accepted |
| 5 | Cloud Function `from google.cloud import firestore` | 500 "ImportError: module 'google.cloud' is not available in the function sandbox" | (b) function sandbox is stdlib-compute only, no network |
| 5 | `firestore.Client(project).collection().document().set()` against simulator | 503 gRPC connect failure | (a) no gRPC; the high-level client has no REST transport at all |
| 5b | Topic created / document written through the simulator with the emulator env vars set | Topic/doc absent from the real emulators | (a) in v4 the cores are authoritative (`is_unified`); emulators are only adopted once, not a data plane |
| 7 | Function doing `urllib.request` to read a Firestore doc | 500 "module 'urllib.request' is not available in the function sandbox" | (b) as above |
| 8 | `trace_v1 get_trace` for spans written with v2 | ParseError: spanId 'aaaaaaaaaaaaaaaa' invalid for int | (b) v1 must return decimal uint64 spanId; simulator returns the hex id |
| 8 | `entries:list` with filter `timestamp>="...+0000"` (also `...Z`) | returns zero entries although entries exist | (b) timestamp comparison broken; this makes `logging.Client.list_entries()` (adds that filter by default) return nothing |
| 8 | `LoggingServiceV2Client`, `MetricServiceClient` on REST | KeyError 'rest': only grpc transports exist in the SDK | (a) needs gRPC; raw REST write/read of logs and a custom metric PASS |
| 9 | `memories:generate` | 503 no model | (c) |
| 10 | `generate_content` (plain and with function declarations) | 503 no model | (c); embed_content PASS (256-d hash embedding, lexical not semantic) |
| 11 | `generate_content` with `Tool(retrieval=VertexRagStore)` | 400 "tools.retrieval is not supported by the local model (only functionDeclarations)" | (a) not model-dependent: rejected before any model call |
| 12 | `bucket.notification(...).create()` | 404 Unknown path `/storage/v1/b/B/notificationConfigs` | (a) missing API |
| 12 | Eventarc storage-finalized trigger to a function using `print` | delivery status RETRYING, "NameError: name 'print' is not defined" | (b) event-function sandbox lacks `print` (the http path has it) |
| 13 | `kms decrypt` with wrong or missing `additional_authenticated_data` | 200 with the plaintext | (b) AAD not enforced; a real KMS refuses |
| 13 | KMS Encrypt/Decrypt in the data_access audit log | none seen | not verified: the probe did not enable an auditConfig (d) |

## Notes
- **Real emulators (item 5).** Docker is present and the 1.49 GB `google-cloud-cli:emulators` image is already in the local store (nothing pulled). Both emulators start in about 10 s and run the whole approval loop with the unmodified high-level gRPC clients. Selection mechanism: `PUBSUB_EMULATOR_HOST` / `FIRESTORE_EMULATOR_HOST` (compose files set them), but the v4 wire path no longer delegates (only legacy console handlers and one-time adoption do). So "make them selectable as the data plane" is real build work, not a flag.
- **Tier gate.** On a one-off run of the full `server:app`, Firestore returned 403 `tier_service_locked` (needs Max). The in-process harness skips this; the reference app on a licensed appliance must run on a tier that includes Firestore.
- **Functions** run in one restricted sandbox on the wire path (`gcp_console_tabs.run_python_function`): no network, no SDKs, stdlib compute modules only. This blocks "function does the approval / reads Firestore / triggers RAG import" for components 5, 7, 12. The AWS app relies on boto3 inside Lambda. The subprocess runtime `core/gcp_function_runtime` exists but is not what the wire path calls.
- **Cloud Armor** exists as compute `securityPolicies` create/get only; enforcement was not probed.
- **Embeddings** without a model are a lexical hash; RAG retrieval PASSES on them but is not semantic. Real quality needs the model run.
- **Not probed:** Cloud Run-hosted app, anything needing a model end to end, KMS data-access auditing.
- **SDK transport.** `google-cloud-pubsub` and `aiplatform` gapic have REST; `firestore.Client`, logging gapic and monitoring gapic do not. The reference app can use REST transports where they exist (all PASS here), but the "unmodified vendor SDK, default transport" bar from the doc fails for Pub/Sub, Firestore, Logging, Monitoring unless the front door gains gRPC or those services run on the real emulators.

## Gap estimates (working days)

| Gap | Fix | Days |
|---|---|---|
| gRPC for Pub/Sub + Firestore (items 2, 5) | Run the real emulators as the data plane for this app and wire them in: 2-3 d. A gRPC front door for the cores instead: 5+ d, not recommended | 2.5 |
| Logging/Monitoring SDKs gRPC-only (8) | Use `logging.Client(_use_grpc=False)` and REST for metrics in the app (0.5 d), or accept the gap and say so | 0.5 |
| Function sandbox: network + SDKs (5, 7, 12) | Route wire-path functions to the subprocess runtime with deps and outbound HTTP | 2.5 |
| Identity Platform missing (1) | Decision needed: Firebase Auth emulator as a backend (2-3 d) or use Google ID tokens only and say so | 0.5 (2.5 if built) |
| API Gateway YAML parse + own-token verification (1) | Use PyYAML; trust the simulator's own signing key | 1 |
| Logging `timestamp` filter, Trace v1 spanId, KMS AAD, event-function `print` (8, 13, 12) | Four small core fixes | 1.5 |
| GCS bucket notifications (12) | New route set over existing Pub/Sub | 1 |
| generateContent with a RAG retrieval tool (11) | Run retrieval, inject context, return groundingMetadata | 1.5 |
| Agent Engine real packaging (3) | Not fixable cheaply; app deploys a Vyomi spec or Cloud Run service and the report says "assembled" | 0.5 (Cloud Run probe) |
| Model-dependent steps (3, 9, 10, 11) | Unknown until run with a model on Mesh | +1 contingency |

Fix total for the GCP half: about 11 d with the Identity Platform decision on the cheap side, 13 d if built.

## Updated total
Earlier estimate for the GCP half (its share of refactor, step 3a, step 4, step 5): about 9 d. Now: probe 1.5 d (done) + refactor share 0.75 + app 3a 4-5 d + gap fixes 11-13 d + packaging share 0.75 = **about 18-21 d**, versus 9. Most of the increase is step 4. If the owner accepts REST transports, drops Identity Platform and keeps functions as pure decision logic, the floor is about 14 d. The doc's whole-programme total (13-18 d) is therefore too low for GCP alone; the Azure probe is needed before restating it.
