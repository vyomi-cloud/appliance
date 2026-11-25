# Vyomi Labs on Nano, no Mesh: Google Cloud (Vertex) coverage matrix

Measured 2026-11-25 on `origin/v4-on-main` b3c5bf98c (branch `v4/labs-nano-matrix-gcp-azure`). Question: what can a FREE user deploy and test in the browser on Nano with no Mesh signed in.
Nothing was built or fixed; this is a measurement. No WebLLM model was downloaded or run (model phase: pending, another agent). Raw logs: `nano-matrix-gcp-azure-evidence/`.

## Verdict

**0 of 13 chapters run on free Nano today. All 13 are "Needs Mesh", and the reason is not mainly the simulator.** Three independent walls sit in front of the learner, in this order:

1. **The Deploy button refuses.** `wasm/labs/labs.js` `needsMesh()` is true for every non-AWS cloud, so clicking "Deploy this chapter" calls `ensureMesh()`, which rejects with "The Mesh is not available in this console. Sign in, then deploy again." Driven in headless Chrome on `/nano/labs/?cloud=gcp&layer=<id>` for all 13 chapters: identical refusal, every block chip stays "waiting" / "saved on run" (`ui-deploy-nano-nomesh.json`). The page disclaimer says the same ("Deploying needs a Mesh ... Pro / Max").
2. **Even with the gate lifted, no block can run.** The Nano runner (`wasm/labs/pyrun-worker.js`) loads Pyodide 0.26.2 plus boto3/botocore only, with a synchronous-XHR transport patched into botocore. There is no google-* package and no equivalent transport shim. I ran all 49 runnable GCP blocks through that exact worker, in course order: 49/49 FAIL at the first import (`The module 'protobuf' is included in the Pyodide distribution, but it is not installed` for 46 of them via `gcp.py`; `langgraph`, `pyyaml`, `cryptography` for the rest). `nano-worker-run-as-written.json`.
3. **Behind the SDK wall the Nano backend is closer than the UI suggests, with five concrete gaps** (below). I measured this by recording every HTTP call the 49 blocks make against the reference simulator (`labrun`, all PASS) and replaying them into the Nano service worker at `/nano/_wire` in the browser, then chaining targeted probes for the cases where ids differ between runs (`nano-replay-gcp.json`, `nano-chained-probe-gcp-{1,2,3}.json`). gRPC calls (Firestore, Pub/Sub, gapic Logging/Monitoring) are not capturable by that method; I probed their REST equivalents instead.

Reference result (`python -m vyomilabs.labrun gcp 10 3 7 12 6 11 9 4 5 1 2 8 13`, venv python 3.13, real Pub/Sub + Firestore emulators in my own uniquely named containers, removed at exit): **49/49 PASS, 0 BLOCKED** (`labrun-reference-gcp.log`). So every failure below is a Nano gap or a course/Nano mismatch, not a bad block.

## Chapter matrix

Columns: **Today** is what a free user gets as shipped. **Potential** is the best case once wall 2 (SDK in browser) is solved, judged on the Nano backend I measured. "Runs with limits" = the Nano backend serves it but a model or a transport change is needed; "Needs Mesh" = something Nano cannot do.

| Ch | Layer | Today | Potential on Nano | Reason and gap |
|---|---|---|---|---|
| 1 | Models | Needs Mesh | Runs with limits | `generateContent` returns 503 "No in-browser model is loaded" until a WebLLM model is loaded (c). Embedding `text-embedding-005` is served. Course picks models from `/v1beta1/publishers` so no hard-coded ids. google-genai is pure Python and imports in Pyodide only after dependency surgery (d). |
| 2 | Agent Runtime | Needs Mesh | Needs Mesh | `reasoningEngines` create + operation poll are served; `:query` of a source-packaged agent returns 400 "needs the sandboxed subprocess runtime (offline appliance...)" (b). langgraph imports in Pyodide with `deps=False`. Model needed too (c). |
| 3 | Tools | Needs Mesh | Needs Mesh | Functions deploy fine on Nano (generateUploadUrl, PUT, CreateFunction -> ACTIVE) but invocation answers 403, and Nano's function sandbox allows stdlib only (`_FN_SAFE_MODULES` in `core/gcp_console_tabs.py`) while every tool imports `google.cloud.firestore` (b). Firestore client is gRPC (d). |
| 4 | Knowledge Pipeline | Needs Mesh | Runs with limits (upload, corpus); Needs Mesh for the pipeline | GCS upload, RAG corpus create, `ragFiles:import`, list: all served. `notificationConfigs` rejects `projects/vyomi-project/topics/...` because Nano's project is `nano-project` (a). The event-triggered ingest function cannot execute (b). |
| 5 | Knowledge Search (RAG) | Needs Mesh | Runs with limits | `retrieveContexts` served (search.py, check_ranking.py). `deploy_kb_search.py` deploys but the function cannot be invoked (b). |
| 6 | Response Generation | Needs Mesh | Runs with limits | Retrieval and Model Armor sanitize served; generation needs a model (c). |
| 7 | Agent Memory | Needs Mesh | Runs with limits | Sessions, events, memories create/get/retrieve served. `memories:generate` needs a model (c). `memory.py` uses the Firestore gRPC client (d). |
| 8 | Agent Gateway | Needs Mesh | Runs with limits | `agentGateways`, `attachMcpServer`, `agentPolicies` + Cedar test + attach served. The MCP tool server is a function and cannot execute (b). |
| 9 | Actions and Approval | Needs Mesh | Needs Mesh | Whole chapter is functions (b) + Pub/Sub and Firestore gRPC clients (d) + a model for the supervisor turn (c). |
| 10 | Access and Perimeter | Needs Mesh | Runs with limits after two small fixes | Identity Toolkit `accounts:signUp` returns 500 `ImportError: cannot import name 'app_context' from 'core'` (a). API Gateway config create returns 400 "Cannot parse the OpenAPI document: unexpected list item at line 12" for the lab's own PyYAML-dumped spec (a). Cloud Armor and service-account token work, but only against `nano-project` (a). |
| 11 | Channels and Input Guardrails | Needs Mesh | Runs with limits | Model Armor served; Pub/Sub clients are gRPC (d). |
| 12 | AgentOps and Observability | Needs Mesh | Runs with limits | Trace, Logging, Monitoring REST all served. `log_grpc.py` is the explicit gRPC logging path, no gRPC front on Nano (d). One block calls a model (c). |
| 13 | Governance and Security | Needs Mesh | Runs with limits (best chapter) | KMS key ring/key/rotation, encrypt/decrypt with AAD and wrong-AAD refusal, admin-activity audit entries (CreateKeyRing, CreateCryptoKey, CreateTopic) all served. Only `ledger_audit.py` uses the Firestore gRPC client (d). |

Counts: Runs in Nano today 0/13, Runs with limits today 0/13, Needs Mesh today 13/13. Potential once the SDK wall is solved: 10 chapters run with limits (1, 4 partly, 5, 6, 7, 8 partly, 10 after two fixes, 11, 12, 13), 3 stay Needs Mesh (2, 3, 9). No chapter is clean "Runs in Nano" even in the best case: each has a model call, a function execution or a gRPC client somewhere.

## Cause classes, with evidence

**(d) Cloud SDK the browser cannot run (dominant, hits 49/49).** Needed: google-genai, google-auth, google-api-core, google-cloud-aiplatform/vertexai, -firestore, -pubsub, -storage, -kms, -logging, -monitoring, -trace, -functions, -eventarc, -api-gateway, -compute, -iam, -modelarmor, -discoveryengine, plus langgraph, pyyaml, functions-framework. Pyodide install probe (`pyodide-sdk-install-probe*.json`): plain `micropip.install` fails for the whole google-cloud family on pins (`requests>=2.33` vs Pyodide's 2.31, `idna>=3.18`); with `deps=False` google-genai, google-cloud-pubsub, langgraph, functions-framework import; firestore, aiplatform, kms, functions fail on `google.protobuf.runtime_version` (Pyodide ships an older protobuf) and storage on a namespace-package clash. gRPC (`grpcio`) has no Pyodide wheel and cannot open a socket in a browser anyway. `wasm/` has `pylib/botocore-lite.whl` (AWS serialisers only) and no GCP client of any kind. The blocks that matter for Nano already use `gcp.rest(...)` (REST transport, fine in principle) but Firestore and Pub/Sub deliberately use the emulator-host gRPC path (ch3, 4, 7, 9, 11, 13).
The course does need the native SDK: its premise is "native cloud SDK as-is", so a hand-written wire client would change what is taught.

**(b) Nano function/agent sandbox limits.** `run_python_function` runs function source in a restricted `exec`: stdlib subset only (json, math, datetime, base64, re, random, uuid, hashlib, hmac, itertools, functools, collections, string, decimal, statistics, textwrap, time), `os.environ`, no network, shims for flask/functions_framework/azure.functions. Every course tool imports google.cloud.firestore or google-cloud-storage and calls the simulator. Affects ch2 (agent query), 3, 4 (ingest), 5 (kb-search), 8 (MCP server), 9, plus the gateway calls that forward to them.

**(c) Needs a model.** Exact behaviour with none loaded: `generateContent` -> HTTP 503 `No in-browser model is loaded. Open Amazon Bedrock > Overview > Local model, pick a model ...`; `memories:generate` -> same 503; `:predict` on `text-embedding-005` -> 200 with a real vector; `:predict` on `nomic-embed-text` (the reference simulator's embed model) -> 404 Publisher Model not found. Note the message names Amazon Bedrock on a Google Cloud space. In the runner, `labs.js` only treats `ModelNotReady|No in-browser model` as "needs a model" and escalates to a Mesh on the AWS path; non-AWS never reaches that code because of the gate.
Blocks that call a model, and what they do with none: `try_models.py` (ch1: chat and tool call fail 503, embedding passes), `try_agent.py`, `query_agent.py` (ch2), `try_response.py`, `safe_response.py`, `grounded_generate.py` (ch6), `session_demo.py`, `generate_memories.py` (ch7), `submit_request.py` (ch9, supervisor turn), `export_trace.py` (ch12, agent run). None has a fallback; each fails on the first model call (reference run answers from the deterministic test stub).

**(a) Missing or incorrect Nano backend.**
- Identity Toolkit (`/v1/accounts:signUp`, `signInWithPassword`, securetoken JWKS): 500 ImportError, ch10 `signin.py`.
- API Gateway OpenAPI parser rejects indentless YAML sequences, ch10 `api_gateway.py`, and so `call_edge.py`.
- Project id: Nano accepts `vyomi-project` in URL paths but resource names, service-account emails and body references come back as `nano-project`; `notificationConfigs` and `generateIdToken` for `agent-sa@vyomi-project...` fail (ch4, ch10).
- Cloud Functions HTTPS invocation (`/gcf/<project>/<region>/<name>`) answers 403/404 (ch3, 5, 8, 9).

**Not a gap, by design (stated in GAPS_gcp.md):** Discovery Engine chapter-6 block was left out of the course because of an operation-metadata type bug in the reference simulator; Nano answers that operation endpoint 200 done, so it is not reproduced there.

## Ranked gap list (effort guesses)

| # | Gap | Chapters | Effort |
|---|---|---|---|
| 1 | google-* SDK + HTTP transport for the browser worker (requests/httpx -> XHR shim, pinned wheels incl. a newer pure-Python protobuf, a Nano-served wheel index so no PyPI at run time) | all 13 | L, 3 to 5 weeks; the shim is small, the wheel curation is the work |
| 2 | Lift the non-AWS Deploy gate and give GCP/Azure blocks the per-block `needs_runtime` flag AWS has (only one Azure block carries it today; no GCP block does, even the function-calling ones) | all | S once #1 exists |
| 3 | Function execution beyond the stdlib sandbox: either run google-cloud-firestore/storage inside the sandbox over the Nano wire, or give tools a REST-only variant | 3, 4, 5, 8, 9 | L (3 to 6 weeks); XL if real packages must load |
| 4 | gRPC-only blocks: rewrite Firestore/Pub/Sub/Logging blocks to REST transport (`transport="rest"` where the client supports it) or accept Mesh-only | 3, 7, 9, 11, 12, 13 | M content change; the clients that have no REST transport stay Mesh |
| 5 | Model-less behaviour: a graceful "load a model" step in the runner, a model catalogue that carries the names the course asks for, and error text that names the right console | 1, 2, 6, 7, 9, 12 | S for the UX, model phase measured elsewhere |
| 6 | Identity Toolkit 500 (`core.app_context` import in the Nano bundle) | 10 | S (hours) |
| 7 | OpenAPI/YAML parser: indentless sequences | 10 | S (hours) |
| 8 | One project id: alias `vyomi-project` everywhere, or tell the course to read the Nano project | 4, 10 | S to M |
| 9 | Reasoning Engine `:query` for source-packaged agents | 2 | L (needs an in-sandbox agent loop) |

## Quality read: chapters 1, 3, 9, 13 (full text and code read)

**Chapter 1, Models.** Genuinely good beginner chapter: model discovery from the catalogue instead of hard-coded ids, tool calling with automatic function calling explicitly disabled so the learner sees "the model asks, your code runs", and an embedding sanity check (paraphrase above unrelated). `gcp.py` is a clean single client factory with the REST/ADC notes an enterprise reader needs. Weak: the lesson text is the same cloud-neutral copy as AWS and Azure (power-socket analogy, same quiz), the BUILD list promises attaching a Model Armor template but no block does it, and "first non-embedding model in the list" is not something an enterprise would ship (no pinning, no quota, retry or timeout handling, no regional/data-residency discussion). Fine as a 25-minute on-ramp, not enterprise-grade on its own.

**Chapter 3, Tools.** Best idea in the course: write tools that refuse without an APPROVED ledger row, never trust the caller, idempotent create, and a script that proves all three (stranger refused, early create refused, double call -> one work order). That is enterprise thinking. Gaps: "least privilege" is taught but the functions deploy under the default service account with no IAM binding shown; `asset_status` does `body["asset_id"]` with no schema validation (a missing field is a 500, which the lesson itself warns about); the approval-decision function reads the ledger row then updates it with no transaction or precondition, a check-then-act race that the Azure version closes with an ETag; the approver allow-list is a string suffix `@example.com` in code. It also deploys three of the five functions it advertises (kb-search and the MCP server come in chapters 4/6), which makes the chapter order hard to follow. Prose mentions a `request-approval` tool that does not exist in the blocks.

**Chapter 9, Actions and Approval.** Honest about being an assembled pattern (Pub/Sub topic + subscription, Firestore ledger, two functions) and the executable proofs are solid: pending row first, nothing in `work-orders`, stranger refused, waiter wakes on APPROVED, reject writes nothing, create is idempotent. But the explain/narrative text is AWS Step Functions language (callback token, durable workflow) while the lab is a polling thread on a ledger; there is no timeout, expiry, escalation or dead-letter handling; the approver is a self-declared string (no authentication of the approver at all, an auditor would stop here); LEARN promises "risk levels: low auto-approves" and nothing builds it; Workflows or Cloud Tasks, the managed Google answers, are named as not used. Good teaching of the shape, short of enterprise approval.

**Chapter 13, Governance and Security.** Real envelope encryption with Cloud KMS, additional authenticated data and a wrong-context refusal that is actually asserted, 90-day rotation, and a read of the admin-activity audit log that asserts CreateKeyRing/CreateCryptoKey/CreateTopic appear. Compact and credible for 30 minutes. Gaps: the explain/flow text still says "store an object with server-side encryption" and "create the trail" (AWS wording; no CMEK object step exists in the blocks); "an audit trail the people it records cannot edit" is the stated lesson but nothing demonstrates immutability (no log sink to a locked bucket, no retention lock, no IAM separation of who may decrypt vs who administers the key); data-access audit logs are opt-in and not covered; no Secret Manager, VPC Service Controls or org-policy layer. Right skeleton, thin on the controls an auditor would ask for.

## Differences from the AWS course structure

- Same 13 chapters, same order, same narrative copy; AWS has 57 blocks (46 runnable), GCP 80 (49 runnable). The extra blocks are `gcp.py` plumbing and function-deploy helpers.
- AWS needs one SDK (boto3) and the worker already ships it with an XHR transport, so most AWS chapters can run in the browser; GCP needs about twenty google-* packages plus gRPC and nothing exists for them in `wasm/`.
- AWS flags Lambda-executing blocks with `needs_runtime` so the page can escalate per block; GCP flags none (Azure flags one), so there is no per-block escalation data even though ch3, 4, 5, 8, 9 execute functions.
- GCP's own gap file lists one gap (Discovery Engine) and stated limits; AWS lists none. The GCP lab relies on two real Docker emulators (Pub/Sub, Firestore) for the reference result, which Nano cannot mirror.
- GCP mixes two transports on purpose: REST (`gcp.rest`) for most, gRPC for Firestore and Pub/Sub. This is the structural difference that decides what can ever run in a browser.

## Appendix: every runnable block

`BR` = backend readiness if the SDK could run in the browser: OK served by Nano; MODEL needs a loaded model; SBX needs function or agent execution; GRPC gRPC transport; A:... missing or incorrect Nano backend. Replay caveat: the replay carries recorded ids, so the verdicts above were confirmed with chained probes wherever ids differ; gRPC traffic is not in the recording.

| Ch | Block | Reference labrun | Nano as shipped | Same block in the Nano Pyodide worker | Nano backend if the SDK could run | Cause class | Detail |
|---|---|---|---|---|---|---|---|
| 1 | `try_models.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | MODEL | (c) model | chat+tool call: HTTP 503 'No in-browser model is loaded'; embedding served |
| 2 | `try_agent.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing langgraph | MODEL | (c) model | langgraph agent calls generateContent -> 503 |
| 2 | `deploy_agent.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | reasoningEngines create + LRO poll served |
| 2 | `query_agent.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | SBX | (b) function/agent sandbox | reasoningEngines:query -> 400 'needs the sandboxed subprocess runtime' |
| 3 | `seed.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | GRPC | (d) gRPC transport | Firestore client uses gRPC (FIRESTORE_EMULATOR_HOST); Nano serves Firestore REST only |
| 3 | `deploy_tools.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | generateUploadUrl, PUT zip, CreateFunction -> ACTIVE served (bucket/project ids differ per space) |
| 3 | `call_asset_status.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | SBX | (b) function/agent sandbox | function URL answers 403; sandbox allows stdlib only, tool imports google.cloud.firestore |
| 3 | `check_write_tool.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | SBX | (b) function/agent sandbox | same as above, plus Firestore gRPC in the script itself |
| 4 | `upload_docs.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | bucket create + object upload served (REST) |
| 4 | `create_kb.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | RAG corpus, ragFiles:import, list served |
| 4 | `notify.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | A | (a) missing/incorrect Nano backend: project alias | notificationConfigs rejects topic 'projects/vyomi-project/...' (Nano project is nano-project); Pub/Sub via gRPC |
| 4 | `deploy_pipeline.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | SBX | (b) function/agent sandbox | functions deploy served; Eventarc trigger needs the function to run; ingest function imports google-cloud-storage |
| 4 | `test_pipeline.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | SBX | (b) function/agent sandbox | depends on the event-triggered ingest function executing |
| 4 | `replace_doc.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | SBX | (b) function/agent sandbox | depends on the ingest function; RAG import itself served |
| 5 | `search.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | retrieveContexts served |
| 5 | `check_ranking.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | retrieveContexts served |
| 5 | `deploy_kb_search.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | SBX | (b) function/agent sandbox | deploy served; function invocation not possible (imports google.cloud + google-auth) |
| 6 | `try_response.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | MODEL | (c) model | retrieve served, generateContent 503 |
| 6 | `screen_output.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | Model Armor template + sanitize served |
| 6 | `safe_response.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | MODEL | (c) model | generateContent 503 |
| 6 | `grounded_generate.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | MODEL | (c) model | generateContent 503 |
| 7 | `memory.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | GRPC | (d) gRPC transport | Firestore client gRPC |
| 7 | `session_demo.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | MODEL | (c) model | sessions + events served; the model turn 503 |
| 7 | `remember.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | memories create/get/retrieve served |
| 7 | `generate_memories.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | MODEL | (c) model | memories:generate 503 (needs a model) |
| 8 | `register_tools.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | SBX | (b) function/agent sandbox | MCP tool server is a Cloud Run function; deploy served, execution not |
| 8 | `create_gateway.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | agentGateways create/get/attachMcpServer served |
| 8 | `use_gateway.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | SBX | (b) function/agent sandbox | gateway /mcp forwards to the function above |
| 8 | `add_policy.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | agentPolicies + Cedar test + attachPolicy served |
| 9 | `setup_inbox.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | GRPC | (d) gRPC transport | Pub/Sub publisher/subscriber clients use gRPC; REST topic/sub create works on Nano |
| 9 | `submit_request.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | MODEL | (c) model | supervisor turn needs a model; Firestore + Pub/Sub gRPC |
| 9 | `approve_request.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | SBX | (b) function/agent sandbox | calls approval-decision and create-work-order functions; Pub/Sub + Firestore gRPC |
| 9 | `reject_request.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | SBX | (b) function/agent sandbox | same |
| 10 | `signin.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | A | (a) missing/incorrect Nano backend: Identity Toolkit | POST /v1/accounts:signUp -> 500 'ImportError: cannot import name app_context from core' |
| 10 | `service_account.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | A | (a) missing/incorrect Nano backend: project alias | SA create served; generateIdToken for agent-sa@vyomi-project -> 403 (the SA is agent-sa@nano-project) |
| 10 | `armor.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | Cloud Armor policy create/get served (stored, not evaluated, as the chapter says) |
| 10 | `api_gateway.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing pyyaml | A | (a) missing/incorrect Nano backend: OpenAPI YAML | config create -> 400 'unexpected list item at line 12' (parser rejects PyYAML-style indentless lists) |
| 10 | `call_edge.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | A | (a) missing/incorrect Nano backend: API Gateway edge | depends on the config above; edge call returned 'No gateway serves this host' |
| 11 | `intake.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | Model Armor served; Pub/Sub publish via gRPC client |
| 11 | `inbox_check.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | GRPC | (d) gRPC transport | Pub/Sub pull via gRPC |
| 12 | `export_trace.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | MODEL | (c) model | agent run calls a model; Cloud Trace batchWrite served |
| 12 | `read_trace.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | Trace read served |
| 12 | `log_run.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | entries:write / entries:list served |
| 12 | `metric.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | Monitoring timeSeries create served (REST) |
| 12 | `log_grpc.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | GRPC | (d) gRPC transport | explicitly the gRPC Logging path; Nano has no gRPC front |
| 13 | `create_key.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | KMS key ring + key + rotation served |
| 13 | `seal_record.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: missing cryptography | OK | - | KMS encrypt/decrypt with AAD, wrong AAD refused: served |
| 13 | `audit_trail.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | OK | - | admin-activity audit entries for CreateKeyRing/CreateCryptoKey/CreateTopic served |
| 13 | `ledger_audit.py` | PASS | BLOCKED (Deploy needs a Mesh) | FAIL: google SDK stack not in Pyodide (first miss: protobuf) | GRPC | (d) gRPC transport | Firestore gRPC |
