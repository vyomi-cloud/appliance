# Vyomi Labs (AWS) on Nano: free edition status

Measured 2026-11-26 on branch `v4/labs-nano-edition` (from `origin/v4-on-main` b3c5bf98c + `v4/nano-cognito-waf`). Headless Chrome 1 machine, no Mesh anywhere, Nano preview on my own port. Baseline = `docs/labs/nano-matrix-aws.md` (20/46 as shipped). Raw logs and drivers: `docs/labs/nano-edition-evidence/` (per-block jsonl, UI deploy JSON, picker screenshot).

## What changed (runtime only)
1. Deploy runs what can run (`wasm/labs/labs.js`). No up-front Mesh refusal on AWS. Each block runs; a failure is classified: model missing -> picker, no in-browser engine/package -> "needs the Mesh" + reason (the run continues), otherwise a real failure. No automatic Mesh escalation.
2. Runner bug fixed (`pyrun-worker.js`): file-like bodies are read (S3 `put_object` / zip upload). Also `urllib` over XHR for same-origin Nano URLs.
3. "Load a model" picker: the four `vyomiWebLLMModels` with sizes, WebGPU detection and a plain no-WebGPU message, Qwen2.5 1.5B recommended, the other three labelled "plumbing only", cache/disk hint on load failure; the step re-runs after loading. The no-model error text (`core/llm_core.py`) now names Labs, Bedrock, Vertex AI and Azure OpenAI instead of only Amazon Bedrock.
4. Lambda sandbox runs real handlers (`core/lambda_sdk.py`, `core/lambda_core.py`): `import os, json, time, boto3, botocore.exceptions, urllib.parse`. boto3 = clients only, over the in-process router (`wire_clients` + botocore-lite, which now also carries the Bedrock/AgentCore models); `endpoint_url` ignored; `os` is a proxy (environ = function env, getenv, getpid, path string helpers, nothing else). Appliance behaviour unchanged. Tests: `tests/conformance/test_lambda_sandbox_sdk.py`.
5. AgentCore runtime on Nano: hosted agents get the same boto3, an in-process-only `urlopen` (gateway MCP, runtimes) and langgraph. langgraph IS loadable in Pyodide 0.26: pure Python, but PyPI's resolver wants native wheels Pyodide lacks, so a pinned set (langgraph 0.6.11, checkpoint 2.1.2, prebuilt 0.6.5, sdk 0.2.9, langchain-core 0.3.86, langsmith 0.4.37 + httpx/tenacity/jsonpatch...) is installed with `deps=False` on Pyodide's own pydantic/msgpack/orjson/xxhash, plus two tiny pure stubs (`ormsgpack`, `uuid_utils.uuid7`) for paths a checkpointer-less graph never takes. Fetched from PyPI on the first runtime invoke (needs the browser online once; offline the error says why). 0.6.x on purpose: <=0.3 rejects the course agent's node `analytics` that is also a state key.
6. Service-worker window: a hosted agent makes many model calls inside one request, which hit the SW's 15 s backend timeout (retried 3x, 500). The kernel now sends keepalives while a hosted-agent request or a WebLLM call is in flight.

## Pass counts per chapter (46 runnable blocks)
Columns: baseline (shipped runner, no model, from the matrix) | now, as shipped, no model | now, Qwen2.5 1.5B loaded + the `models.py` zip fix (see Content bug) | ch1-6 per model, same setup.

| Ch | baseline | now, as shipped, no model | now, Qwen 1.5B + zip fix | SmolLM2 360M | Qwen 0.5B | Llama 3.2 1B | Qwen 1.5B |
|---|---|---|---|---|---|---|---|
| 1 | 0/1 | 0/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| 2 | 0/3 | 1/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| 3 | 3/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 |
| 4 | 3/5 | 4/5 | 4/5 | 4/5 | 4/5 | 4/5 | 4/5 |
| 5 | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| 6 | 3/4 | 2/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 |
| 7 | 3/3 | 3/3 | 2/3 | - | - | - | - |
| 8 | 2/5 | 4/5 | 5/5 | - | - | - | - |
| 9 | 2/6 | 3/6 | 6/6 | - | - | - | - |
| 10 | 0/5 | 5/5 | 5/5 | - | - | - | - |
| 11 | 2/2 | 2/2 | 2/2 | - | - | - | - |
| 12 | 1/2 | 1/2 | 2/2 | - | - | - | - |
| 13 | 1/3 | 2/3 | 3/3 | - | - | - | - |
| all | 20/46 | 34/46 | 44/46 | 19/20 | 19/20 | 19/20 | 19/20 |

Files: `as-shipped-nomodel.jsonl`, `qwen15b-with-zipfix-ch1-13.jsonl`, `model-<model>-ch1-6.jsonl` (ch7-13 are model independent on Nano; the full Qwen run covers them).

Pass counts per model are equal because the checks only assert printed substrings. Quality differs (same run logs): Qwen 1.5B makes a real tool call (`stop_reason = tool_use`) and answers cleanly; SmolLM2/Qwen 0.5B/Llama 1B answer `end_turn` with no tool call, and the agent answers are loose ("34 psi" restated, a P1 invented in Llama's wording, Qwen 0.5B's `retrieve_and_generate` is a non-answer). Only Qwen 1.5B demonstrates what the lessons teach.

## UI verification (Deploy button, headless Chrome, Labs iframed in the AWS console as the product does)
`ui-deploy-nomodel-all-chapters.json`: all 13 chapters started from the button on a fresh profile with no Mesh (before: only ch1, 2, 7, 11 could start). Chapters 4 steps ran, ch7/9/6/10/11 reported "Deployed" with the "see it running" links. Chapters showing failures in that file fail for the content bug below or the two count expectations below, with the step log visible. The picker appeared on ch1 and ch6 (screenshot `ui-model-picker.png`); picking SmolLM2 downloaded it (about 25-40 s), re-ran the step and chapter 1 reported Deployed (`ui-model-picker-smollm2.json`). `NOGPU=1` run: the picker says "No WebGPU in this browser..." with only a Skip button and the rest of the chapter still runs (`ui-nogpu-picker.json`). That UI pass predates the gateway/keepalive commits; the block-level counts above are the final code.

## Still Mesh-only / not on Nano
- Nothing in the 13 chapters is Mesh-only by an engine gap any more. The classifier still marks a step "needs the Mesh" for `NotImplementedException` and for a hosted-agent package that cannot load (offline langgraph).
- Needs a WebGPU browser and about 2 GB free disk for any model step (ch1 `try_models`, ch6 `retrieve_and_generate`, the agent answers). No WebGPU: those steps stay "needs a model"; nothing else is blocked.
- Hosted agents need network access to PyPI once (langgraph). Offline: reported, those steps need a Mesh.
- Lambda `Timeout` is not enforced (single-threaded Pyodide); the relay/SDK-CLI worker path does not register the Lambda SDK (the Labs and console paths do); langgraph checkpointers are unsupported (stubbed serde).

## Course-content findings for the content owner (not changed here)
1. `deploy_runtime.py` zips only `main.py`, `agents.py`, `mcp_client.py`, but `agents.py` does `import models`. As written the hosted agent dies with `ModuleNotFoundError: No module named 'models'` on every substrate, so as shipped ch2 `invoke_agent`/`stop_session`, ch6 `grounded_answer`, ch8 `agent_via_gateway`, ch9 `request_work_order`/`approve`/`history`, ch12 `trace_agent`, ch13 `audit` fail (the "now, as shipped" column). Adding `z.write("models.py", "models.py")` gives the "Qwen 1.5B + zip fix" column. I did not edit the course; the zip fix was applied in the test driver only (`PATCH_ZIP=1`).
2. Two expectations depend on cross-chapter counts and fail even with everything running: ch4 `event_driven` expects "started ingestion job #2" but Nano reports #3 (an extra ingestion job exists before the S3 event; not yet traced to Nano vs course), and ch7 `memory_events` expects "replayed 2 events" but prints 4 once the hosted agent of ch2/ch6 has written its own memory events.
3. Chapter 1's only check is the `embed:` line and ch6's `citation blocks` check passes vacuously with an empty KB (see the matrix); unchanged.

## Reproduce
`node consoles/nano_preview.mjs --port <p>`; `docs/labs/nano-edition-evidence/scripts/plumb.mjs` (block runner; `MODEL=<id> PATCH_ZIP=1 CH=1,2,...`), `ui.mjs` (Deploy button; `LAYERS=<layer ids> MODEL=<name> NOGPU=1`), `sum.py` (per-chapter table). Scripts carry my scratch paths; edit the port/profile lines.
