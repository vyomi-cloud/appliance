# Branch v4/labs-nano-edition

Runtime for the FREE Nano edition of the Vyomi Labs AWS course: a user with no Mesh deploys and tests the chapters in the browser against the four WebLLMs. Measured gap list: `docs/labs/nano-matrix-aws.md` (branch `v4/labs-nano-matrix-aws`). Results: `docs/labs/nano-edition-status.md`. Course prose and checks belong to the content agent; this branch is runtime only.

## Architecture
- `wasm/labs/pyrun-worker.js` (Labs runner): file-like request bodies are read before sending (S3 `put_object` / zip upload crashed on `bytes(BytesIO)`); `urllib.request.urlopen` goes over synchronous XHR (same-origin Nano only).
- `wasm/labs/labs.js` Deploy: on AWS nothing is refused up front. Every block runs; a failure is classified: model missing -> model picker (the four `vyomiWebLLMModels`, size note, WebGPU check, Qwen2.5 1.5B recommended, others labelled plumbing only) then the step re-runs; no engine / package -> "needs the Mesh" with the reason; anything else is a real failure. No automatic Mesh escalation (a button offers it when signed in).
- `core/lambda_sdk.py` + `core/lambda_core.py`: the Lambda sandbox keeps its allow-list but, when the host registered an in-process transport (Nano: `wasm/providers/wire_adapter.py`), a handler may `import boto3` (clients only, calls land in the router, `endpoint_url` ignored), `botocore.exceptions`, `urllib.parse` and a restricted `os` (environ = function env, getenv, getpid, path helpers; no filesystem/process calls). Appliance (no transport): unchanged. Reuses `core/tf_export/wire_clients.py` over `wasm/pylib/botocore-lite.whl`, which now also carries the Bedrock/AgentCore service models and a working `AWSRequest` (SigV4 signing).
- AgentCore inproc runtime (`core/agentcore_runtime_host.py`): hosted agent code gets the same in-process boto3 and an in-process-only `urlopen` (gateway MCP, runtimes). langgraph: `wire_adapter.ensure_agent_deps()` fetches a pinned pure-Python stack (langgraph 0.6.11) from PyPI via micropip on the first runtime invoke, with two small stubs for native deps never used by a checkpointer-less graph.
- `core/llm_core.py`: the no-model message no longer names only Amazon Bedrock.

## Decisions
- One shared SDK module for Lambda and hosted agents instead of a second transport. Rejected: Pyodide worker per Lambda invoke (gap-1 estimate 4-7 days; the in-process sandbox with an allow-list already meets the course handlers).
- langgraph 0.6.x, not older: <=0.3 rejects a node named like a state key (the course agent's `analytics`). Needs the browser online once (PyPI); offline it reports why.
- `agent_main.py`'s zip in `deploy_runtime.py` omits `models.py` (course content; reported to the content owner), so the as-shipped chapter fails at `import models` on any substrate.

## Open
- Lambda `timeout` is not enforced (single-threaded Pyodide). Relay workers (SDK/CLI path) do not register the Lambda SDK. langgraph checkpointers are not supported. Model quality: only Qwen2.5 1.5B follows the lessons.
