# v4/ai-runtime: AgentCore Runtime hosting

Owner: AI lane `runtime` (round 2). Base: `v4/ai-integration` (5cb53ee00). Purpose: `InvokeAgentRuntime` now really runs the hosted agent.
Reference-app component 3 (supervisor + Facilities/Maintenance/Analytics sub-agents) executes inside the runtime, not in the caller's process.

## What was built
- `core/agentcore_runtime_host.py` (new, stdlib only, mirrored to `wasm/core/`): runs the AgentCore runtime contract (`GET /ping`, `POST /invocations`, session header, JSON or SSE).
- `core/bedrock_agents_core.py` (small additive edits): `agentRuntimeArtifact.codeConfiguration` (zip in S3 + `entryPoint`) accepted on Create/Update; per-version snapshot of artifact + env; `InvokeAgentRuntime` routes to the host when the runtime has code (or a local image with `VYOMI_RUNTIME_BACKEND=docker`) and no `VYOMI_AGENT_SPEC`; `StopRuntimeSession` / `DeleteAgentRuntime` stop processes; DEFAULT endpoint follows the latest version on update. The existing agent-spec path is untouched.
- Example app: `examples/enterprise-facilities-agent/agent_runtime/main.py` (entrypoint, `handler(payload, context)`, discovers state machine + gateway by reference name through the standard SDK env) and `facilities/components/c03_runtime.py` (zips `facilities/` + `main.py`, uploads to S3, CreateAgentRuntime, invoke by `runtimeSessionId`, isolation, StopRuntimeSession; falls back to the client-side graph only so later components still run if hosting fails).
- Test: `tests/conformance/test_agentcore_runtime_host.py` (real boto3, in-process simulator).

## OSS / building-block choices
| Concern | Choice | Substrate | Why / limit |
|---|---|---|---|
| Agent process contract | AgentCore contract as in bedrock-agentcore SDK / starter toolkit (Apache-2.0); loader also accepts a real `BedrockAgentCoreApp` object (`app.handlers['main']`) | both | We implement only the thin HTTP adapter (stdlib `http.server`); no new engine. SDK itself is not required |
| Isolation + execution | one OS process per (runtime, version, session), started from the host file | Mesh / offline | cheap, no image pull; process isolation only, not microVM. Idle TTL 15 min, max 16 sessions |
| Containers | `docker run` of a LOCAL image, container port 8080 | Mesh with Docker | **Not verified here** (no Docker/disk); never pulls images |
| Nano | same entrypoint exec'd in-process (`inproc`), one namespace per session | Nano / Pyodide | **Subset**: handler functions only, same thread, process-global env, no per-session process isolation; boto3 is not in Pyodide so Nano agents must use the simulator's own client or plain HTTP. Verified only with plain CPython `VYOMI_RUNTIME_BACKEND=inproc`, not inside Pyodide |
| Agent -> simulator calls | standard SDK env: `AWS_ENDPOINT_URL`, dummy keys, region; endpoint from `VYOMI_SELF_ENDPOINT` else the request Host header | both | agent code is unmodified boto3 |
Hand-built: only the adapter/host (about 300 lines), because no OSS runtime supervisor exists that speaks the simulator's S3-zip deploy.

## Verified
- `test_agentcore_runtime_host.py`: all PASS (entrypoint run, env vars, agent's own SDK call back to the simulator, own process, session isolation and reuse, SSE streaming, agent exception -> 424 RuntimeClientError, version pinning via endpoints, StopRuntimeSession, unreadable code -> 424, inproc backend).
- Facilities e2e: component 3 all PASS (agent ran in a separate pid; route facilities+maintenance+analytics; tools kb_search, asset_status, create_work_order; second session = different pid). Totals unchanged otherwise: the 2 FAILs (ListFoundationModels naming, KMS encryption context) and BLOCKED (local LLM, S3->Lambda event) belong to other lanes.
- Existing suites still green: test_bedrock_agents_core, test_agentcore_facilities, test_ai_agent_runtimes.

## Declared limits
- Code deploy dependencies are NOT installed per runtime (no `requirements.txt` resolution): the host Python must already have them (langgraph, boto3). `VYOMI_RUNTIME_PYTHON` selects the interpreter.
- Code readability is checked at first invoke (424), not at CreateAgentRuntime.
- Streaming is buffered by the simulator when the transport does not stream; response bytes are the agent's own.
- `InvokeAgentRuntimeCommand` still unsupported. Docker backend and Pyodide run unverified.
- Agent endpoint scheme is http (Host header); set `VYOMI_SELF_ENDPOINT` when the simulator is behind a proxy/TLS.
