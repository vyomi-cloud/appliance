# Vyomi Labs (AWS / Bedrock) on Nano: what a free user can do in the browser

Measured 2026-11-25 on `origin/v4-on-main` @ b3c5bf98c (branch `v4/labs-nano-matrix-aws`). Measure only, no product code changed.
Raw logs and the drivers are in `docs/labs/nano-matrix-aws-evidence/` (file names quoted below).

## How it was measured

- Nano served by `consoles/nano_preview.mjs` on port 8913 (my own). Headless Chrome (Playwright, `--headless=new`), persistent profile per run, no Mesh, no sign-in.
- The Nano kernel lives in a console tab (`/nano/v4/aws/`); the Labs page (`/nano/labs/`) ran in a second tab of the same browser. The lab blocks ran through the product's own `wasm/labs/pyrun-worker.js` (Pyodide + botocore + the XHR shim), one block at a time, in chapter order, with every earlier chapter's files present. This is the same runner `runInBrowser` uses; I drove it directly so that blocks the UI refuses to start (see "UI gating") could still be measured.
- The real "Deploy this chapter" button was also clicked for chapters 1, 2, 3 and 10 (`ui-deploy-nomesh.json`, `ui-deploy-ch*.png`). The Labs page there was standalone (not iframed in a console), so there is no `VyomiMesh` parent. Not tested: the button inside the console iframe.
- Reference = `python -m vyomilabs.labrun aws <layers>` in a Python 3.13 venv (`reference-labrun.log`, `reference-labrun-with-runtime.log`). The reference uses the in-process appliance and the repo's LLM stub, not a real model. Caveat: in this checkout the reference's own AgentCore runtime fails with `ImportError: cannot import name 'CHAT_MODEL' from 'models' (core/models.py)` (a module-name collision in the in-tree harness), so with runtime on, 9 agent/audit blocks fail for a harness reason, not a Nano reason. Reference totals: 46 runnable blocks; 31 pass / 2 fail / 13 blocked (needs runtime) without runtime; 37 pass / 9 fail with runtime.
- Chapter numbers are the course order (`aws.json` order 1..13). `labs_aws.py` keys are layer ids (ch1=10, ch2=3, ch3=7, ch4=12, ch5=6, ch6=11, ch7=9, ch8=4, ch9=5, ch10=1, ch11=2, ch12=8, ch13=13).

## Headline

46 blocks have a run command. On Nano with no Mesh:

| Condition | Blocks passing | Evidence |
|---|---|---|
| Runner as shipped, no model | 20 / 46 | `nano-plumbing-nomodel.jsonl` |
| Runner with the body-read shim bug neutralised (measurement-only prelude), no model | 24 / 46 | `nano-plumbing-nomodel-shimfix.jsonl` |
| Same plus a loaded WebLLM (Qwen2.5-1.5B, chapters 1-6 measured) | 26 / 46 | `nano-model-qwen25-15b.jsonl` |
| Reference `labrun`, no runtime | 31 / 46 (13 blocked) | `reference-labrun.log` |

What the 20 to 26 are: pure control-plane work (DynamoDB, S3, KB, vector store, guardrails, AgentCore memory, Step Functions definition, SNS/SQS, KMS, CloudTrail). What fails everywhere is anything that must EXECUTE user code: Lambda handlers, the hosted AgentCore agent, and the Step Functions callback loop that depends on them. That one capability gates 9 of the 13 chapters.

## Chapter matrix (no Mesh)

Legend: Runs in Nano = every block passes on Nano as the product ships it (a loaded model counts if the chapter needs one). Runs with limits = some blocks pass, the rest fail for a named reason. Needs Mesh = the chapter's point cannot be reached on Nano today.

Block counts are runnable blocks (pass as shipped / pass with shim fix / total).

| Ch | Title | Verdict | Blocks | Why (exact error, class) | Gap to close |
|---|---|---|---|---|---|
| 1 | Models | Runs with limits | 0 / 1 / 1 (1 with a model) | No model loaded: `ModelNotReadyException: No in-browser model is loaded. Open Amazon Bedrock > Overview > Local model ... needs a WebGPU browser` (c). The Deploy button then says "A step needs a model, so the deploy continues inside a Mesh" and escalates to Mesh instead of offering to load a model. With a model: passes, but the check only asserts the `embed:` line. | Labs "Load a model" action (and WebGPU message); chapter check should assert chat text and `stopReason`. |
| 2 | Runtime | Needs Mesh | 0 / 1 / 3 | `deploy_runtime`: `TypeError: 'bytes' object cannot be interpreted as an integer` (e: runner shim `bytes(body)` on a BytesIO body, S3 zip upload). After that is neutralised it passes (READY). `invoke_agent`: `RuntimeClientError: Agent returned 500: ModuleNotFoundError: No module named 'boto3'` (d: the in-kernel AgentCore runtime has no boto3/langgraph). `stop_session` fails as a consequence. | Fix shim; give the Nano AgentCore runtime boto3 (via the same shim) and micropip-installable langgraph. |
| 3 | Tools | Runs with limits | 3 / 3 / 4 | tables, seed, deploy PASS. `call_tools`: Lambda returns `{"errorType":"ImportError","errorMessage":"module 'os' is not available in the Lambda sandbox"}` then the script dies `KeyError: 'found'` (b). The UI refuses the whole chapter: "The Mesh is not available in this console. Sign in, then deploy again." | Lambda sandbox must allow `os`, `boto3` (shimmed), `json`, `time`. |
| 4 | Pipeline | Runs with limits | 3 / 4 / 5 | `upload_docs` same shim error as ch2 (e), which cascades to an empty KB (`ingestion COMPLETE | documents scanned: 0`, `search` IndexError). With the shim fixed 4 of 5 pass (real embeddings, 4 docs ingested). `event_driven`: `no new ingestion job appeared` (b: S3 event to Lambda never runs the handler). | Shim; Lambda sandbox + S3 event delivery. |
| 5 | Search | Runs with limits | 0 / 2 / 3 | `search`/`rerank` fail only because ch4 uploaded nothing; with the shim fixed both PASS (hits have text and source; rerank returns 2). `deploy_kb_search`: `KeyError: 'results'` because the handler cannot import (b). | Shim; Lambda sandbox. |
| 6 | Response | Runs with limits | 3 / 2 / 4 (3 with a model) | Guardrail and output filter PASS. `retrieve_and_generate` needs a model: `DependencyFailedException ... No in-browser model is loaded` (c); passes with any of the four models. `grounded_answer`: AgentCore runtime `ModuleNotFoundError: boto3` (d). Note the as-shipped "pass" of `retrieve_and_generate` in the first run was vacuous: `citation blocks: 0` still matched the expected prefix because the KB was empty. | Model loader; runtime deps; tighten the expect (cites > 0). |
| 7 | Memory | Runs in Nano | 3 / 3 / 3 | All pass. `long-term records for maria: 0` is also what the reference prints, so the long-term path is not exercised by the check. | None for Nano. Strengthen the check. |
| 8 | Gateway | Runs with limits | 2 / 2 / 5 | `gateway`, `cedar_policy` PASS. `mcp_list` / `mcp_call`: `urllib.error.URLError: <urlopen error timed out>` (d: the course's `mcp_client.py` uses `urllib.request`, which has no sockets in Pyodide; also not checked whether the SW would serve `/gateways/<id>/mcp`). `agent_via_gateway`: runtime boto3 (d). | Patch urllib in the runner shim (or let Nano serve MCP over the same XHR route). |
| 9 | Approval | Needs Mesh | 2 / 2 / 6 | `approver_inbox`, `state_machine` PASS. `request_work_order`: runtime boto3 (d). `approve` / `reject`: `TypeError: 'NoneType' object is not subscriptable` because the inbox/ledger is empty: Step Functions `waitForTaskToken` invokes the request-approval Lambda, which cannot run (b). `history`: no SUCCEEDED execution. This is the course's core safety story and none of it executes on Nano. | Lambda sandbox + Step Functions to Lambda callback. |
| 10 | Access | Needs Mesh | 0 / 0 / 5 | `CreateUserPool`, `CreateWebACL`, `ListUserPools`: `NotImplementedException: identity services need moto + flask + joserfc` (a: Cognito, WAFv2, and the API Gateway authorizer path have no Nano backend). `call_with_token` / `call_without_token` fail downstream. The reference passes these 4 of 5 (moto-backed). | New Nano engines: cognito-idp (pools, clients, JWT), wafv2, API Gateway authorizer + stage invoke. Largest single item. |
| 11 | Channels | Runs in Nano | 2 / 2 / 2 | `input_guardrail` (`GUARDRAIL_INTERVENED`) and `inbox_channel` PASS. | None. |
| 12 | AgentOps | Runs with limits | 1 / 1 / 2 | `evaluators` PASS (13 listed). `trace_agent`: runtime boto3 (d). | Runtime deps. |
| 13 | Governance | Runs with limits | 1 / 2 / 3 | `trail` PASS; `kms_protect` fails as shipped (shim error on SSE-KMS `put_object`, e) and passes once fixed (encrypt/decrypt context, wrong context refused). `audit`: `approval is fully audited: False`, because the ledger has no EXECUTED row (the ch9 chain never ran). | Shim; the ch9 chain. |

Chapter verdict count: Runs in Nano 2 (ch7, ch11); Runs with limits 8 (ch1, 3, 4, 5, 6, 8, 12, 13); Needs Mesh 3 (ch2, 9, 10). Chapters 1 and 6 become Runs in Nano once a model is loaded and the shim is fixed; chapters 4, 5, 13 do once the shim is fixed and Lambda handlers can run.

### UI gating (what a free user actually sees)

`labs.js` `needsMesh()` is true on AWS for any chapter that has a `needs_runtime` block (ch3, 4, 5, 6, 8, 9, 10, 12, 13) and no Mesh route. Pressing "Deploy this chapter" then calls `ensureMesh` and, with no signed-in Mesh, stops with "The Mesh is not available in this console. Sign in, then deploy again." Nothing runs, not even the steps that work (tables, seed, KB, guardrails). Observed on ch3 and ch10 (`ui-deploy-ch3.png`, `ui-deploy-ch10.png`). Chapters 1 and 2 do start: ch1 shows "needs a model" then "continues inside a Mesh"; ch2 ran and showed "3 step(s) failed" (the shim error plus the runtime errors). Only ch1, 2, 7, 11 can start on Nano today.

## Model x chapter (WebLLM on Nano, no Mesh)

WebGPU finding: works. Headless Chrome (`--headless=new --enable-unsafe-webgpu --use-angle=metal`) and a headed window both return an adapter: vendor apple, arch metal-3, `shader-f16` true, maxBufferSize 4 GiB (Apple Silicon, Chrome stable; `gpu.mjs`). A user without WebGPU gets the honest error from `vyomiEnableWebLLM` ("WebGPU is not available in this browser") and Bedrock calls return `ModelNotReadyException`; the course then has no fallback on Nano for ch1 and ch6 `retrieve_and_generate`.

Model files come from jsdelivr (WebLLM 0.2.79) and Hugging Face. Model load is a manual step in the Bedrock console ("Overview > Local model"); the Labs page does not do it for the learner. In my driver it was `vyomiEnableWebLLM(id)` on the kernel tab. Loads below were cold (empty profile cache, fresh download), so they include download time.

Chapters that call a model directly from a script on Nano: 1 (`try_models`), 6 (`retrieve_and_generate`), and every chapter that goes through the hosted agent (2, 6, 8, 9, 12), which die before any model call (`ModuleNotFoundError: boto3`). Chapters 3, 4, 5, 7, 10, 11, 13 do not call a chat model (the embedding is the in-browser MiniLM, no WebGPU needed). I ran chapters 1-6 under each model; 7-13 are model-independent on Nano today.

| | SmolLM2 360M | Qwen2.5 0.5B | Llama 3.2 1B | Qwen2.5 1.5B |
|---|---|---|---|---|
| Size (listed) / cold load | 0.3 GB / 25.6 s | 0.4 GB / 32.2 s | 0.7 GB / 70.9 s | 1.0 GB / 85.6 s |
| Ch1 `try_models` (check passes?) | PASS | PASS | FAIL on this run (`ModelErrorException: model did not produce a valid tool call after 3 attempts`); the same tool prompt gave a valid `tool_use` in the probe seconds later, so flaky | PASS |
| Ch1 tool-use turn (`stopReason`) | `end_turn`, no `tool_use`; free-text nonsense | `end_turn`, text `asset_status?asset_id:B-12` (right idea, wrong format) | `tool_use`, `asset_status {asset_id: B-12}` (probe) | `tool_use`, `asset_status {asset_id: B-12}` |
| Router JSON (agents.py `ROUTER_PROMPT`, 3 questions) | 0/3 valid lists | 2/3 (first answer was a list of topics, not agents) | 1/3 (others returned JSON objects in fences) | 3/3, plausible plans (fenced) |
| Ch2 / 8 / 9 / 12 agent chapters | blocked by runtime boto3, model irrelevant | same | same | same |
| Ch4, ch5 (embeddings only) | same as no model | same | same | same |
| Ch6 `retrieve_and_generate` | PASS, answer correct, adds a P1 work order step | PASS, answer is a non-answer ("I will refer to the relevant information") | PASS, correct list, slightly garbled ("Raise a P1 (a warning or notification)") | PASS, correct, cites |
| RAG grounding (synth prompt from `agents.py`, KB context) | mentions 30 psi, no `[n]` citation | mentions 30 psi, no citation | mentions 30 psi, no `[n]` citation, cites SOP by name | mentions 30 psi AND cites `[1]` |
| Latency (probe, temp 0) | chat 0.5 s; router 1-2 s; RAG 1.3 s; tool 4.0 s | chat 0.7 s; router ~1 s; RAG 1.2 s; tool 1.2 s | chat 0.5 s; router 1.4-2.4 s; RAG 2.6 s; tool 1.4 s | chat 0.5 s; router ~1-1.4 s; RAG 2.4 s; tool 2.7 s |
| Tokens (RAG, in/out) | 182 / 28 | 176 / 17 | 166 / 63 | 176 / 34 |

Reading: only Qwen2.5 1.5B reliably gives the behaviours the course teaches (JSON routing, a tool call, a cited grounded answer). 0.5B and below fail the router and the tool turn; because `agents.py` degrades to keyword routing when the router output is not valid JSON, the agent would still "work" with a worse model but would be demonstrating the fallback, not the model. All four models are fast enough (sub-3 s per call) once loaded. The first Llama 1B and Qwen 1.5B loads failed with `Cache.add() encountered a network error` while the volume had about 4 GB free (Chrome refuses Cache Storage writes near a full disk); on a fresh profile with 7 GB free both loaded. A free user on a nearly full disk can hit this and the error text gives no hint.

Raw: `nano-model-<model>.jsonl` (per block), `.model.json` (load), `.probe.txt` (prompt outputs, tokens, seconds).

## Quality read (chapters 1, 3, 9, 13, read in full)

1. Prose and structure are good: each chapter has a scene, a problem, an analogy, a four-step flow, pitfalls and a quiz, and the code is short, runnable and uses plain boto3 with no vendor shims. A beginner can follow it.
2. The checks prove "it ran", not "it is right". Ch1's only assertion is the `embed: vector of` line, so a model that returns garbage or never calls the tool still passes (confirmed: SmolLM2 and Qwen 0.5B pass ch1 with `stop_reason = end_turn`). Ch6's `retrieve_and_generate` passes with `citation blocks: 0`. Ch7's `long-term records for maria: 0` passes. These are `expect` substrings of printed lines, not assertions.
3. The prose promises more than the code teaches. Ch9 lists idempotency ("approving twice must not create two work orders") and ch3 lists input validation and least privilege; the code contains zero `ConditionExpression`, no validation in any handler (a tool receiving `"; DROP TABLE assets"` just passes it to `get_item`), no IAM policy (the Lambda role is a fixed fake ARN), no DLQ, retry, timeout handling or budget. The quiz tells the learner these matter; the build does not make them real.
4. Failure paths are thin: ch9 does prove "reject writes nothing" (good), and ch13 proves a wrong KMS encryption context is refused (good). Beyond those two there is no failure injection (tool error, model error, approval timeout, Lambda throttle).
5. Cost is absent. A course about enterprise agents never shows token or request cost, a budget, or a rate limit on the agent. Ch10 adds a WAF rate rule, but on Nano it cannot run.
6. Security depth is the strongest layer: guardrails in both directions, Cedar policy on the gateway, Cognito authorizer, KMS context, CloudTrail audit. It is shown on the happy path with a pre-approved test caller; no abuse case (prompt injection into a tool argument, token replay) is tried against it.
7. Ch13's `audit` script depends on state created by a different chapter's run and fails with a vague `False`; it should say which prerequisite is missing.
8. Verdict: good teaching scaffold, not yet enterprise-grade. Closest to enterprise: ch13 (key context, trail). Furthest: ch3 and ch9 (the safety claims are asserted in text, not enforced or tested in code).

## Ranked Nano gaps (effort is a guess, one engineer)

| # | Gap | Unblocks | Effort |
|---|---|---|---|
| 1 | Nano Lambda sandbox runs real handlers: allow `os`, `json`, `time`, `boto3` (through the same shim) | Ch3, 4 (`event_driven`), 5, 9 (approve/reject/history), 13 audit; about 12 blocks directly or by cascade; also needed by the agent chapters | 4-7 days (Pyodide worker per invoke, import allow-list, env, timeout) |
| 2 | Runner shim reads streaming bodies: `bytes(body)` on `BytesIO` crashes every S3 `put_object` and every zip upload (`pyrun-worker.js` line 39) | Ch2 deploy, ch4 upload (then search, rerank), ch13 kms; +4 blocks by itself, more by cascade | 0.5 day (`body.read()` for file-likes) |
| 3 | AgentCore runtime on Nano: boto3 (shim) and langgraph available inside the kernel runtime | Ch2, 6, 8, 9, 12 agent blocks (about 8 blocks); depends on #1 for the tools they call | 3-5 days |
| 4 | Cognito (pools, clients, JWT), WAFv2 and API Gateway authorizer/stage invoke as Nano engines | Ch10 (0 of 5 today) | 8-12 days (Cognito + JWT is the bulk) |
| 5 | Labs UI gating: run what can run, mark only the blocked blocks; do not refuse a chapter outright when it has one `needs_runtime` block; do not auto-escalate to a Mesh for a missing model | A free user can start ch3, 4, 5, 6, 8, 9, 10, 12, 13 and see real progress | 1 day |
| 6 | Labs "Load a model" action with WebGPU detection and a "pick Qwen2.5 1.5B for chapters 6+" hint; surface the Cache write failure on low disk | Ch1 and ch6 for a free user; model quality (only 1.5B meets the lesson) | 1-2 days |
| 7 | `urllib` in the runner (pyodide-http style patch) and confirm Nano serves `/gateways/<id>/mcp` | Ch8 `mcp_list`, `mcp_call`, agent via gateway | 1-2 days |
| 8 | Step Functions `waitForTaskToken` invoking the (now runnable) Lambda and SNS to SQS inbox fan-out proven end to end on Nano | Ch9 approval chain, ch13 audit | 2-3 days, mostly verification after #1 |
| 9 | Chapter checks that assert behaviour (stop reason, citations > 0, records > 0) so Nano and the reference cannot pass vacuously | Course credibility on every substrate | 2 days content |
| 10 | Reference harness: fix the `models` import collision so the reference agent blocks are a clean comparison | Ability to tell Nano gaps from bad blocks for ch2, 6, 8, 9, 12, 13 | 0.5 day |

If only two things are done: #2 (hours) then #1. Together they move the measured pass count from 20 to roughly 30 of 46 (estimate) and make chapters 3, 4, 5, 13 runnable in the browser; #3 and #4 then decide whether ch2, 8, 9, 10 can ever be Nano-only.

## Limits of this measurement

- One machine (Apple Silicon, Chrome stable), one run per configuration, so model flakiness (Llama ch1 tool turn) is observed, not quantified. Model timings are cold-download loads on a connection in India.
- The "shim fix" runs prepend a small prelude that converts a file-like request body to bytes before the shim's `send`; they show what the chapter would do if the runner were fixed, not what ships. The "checksum env" experiment (`AWS_REQUEST_CHECKSUM_CALCULATION=when_required`) did not help and was discarded.
- Labs was driven standalone, not inside the console iframe, so `VyomiMesh`-based behaviour was not exercised (no Mesh was created anywhere).
- Chapters 7-13 were not re-run per model because none of them reaches a chat model on Nano today.
- I did not check what a logged-in free user's console does differently (Nano tier gating); the `--tier` flag was not used.
