# v4/ai-agentcore

Owner: AI session (lane `agentcore`). Base: origin/v4-on-main. Purpose: AgentCore Runtime / Gateway (+Cedar policy) / Memory slice for the
enterprise agentic reference app (`facilities-supervisor`, `facilities-gateway`, `facilities-memory`). Not merged; the orchestrator merges into v4/ai-integration.

## What changed
- `core/agentcore_ext_core.py` (new, mirrored to `wasm/core/`): Memory (control + data plane), Policy engines, gateway policy/semantic-search helpers, runtime tool kinds.
- `core/bedrock_agents_core.py` (small additive edits): dispatch hook for `/memories` + `/policy-engines`; gateway stores `policyEngineConfiguration` and honours
  `protocolConfiguration.mcp.searchType=SEMANTIC`; `_mcp` filters tools/list by policy, enforces Cedar on tools/call; `_invoke_runtime` extracts the caller JWT
  (Authorization or `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Authorization` Bearer), runs the agent with tool context, and reads/writes memory.
- `core/agent_spec_core.py`: `register_kind()` extension point (additive).
- `tests/conformance/test_agentcore_facilities.py`: 25 checks through real boto3 (bedrock-agentcore-control, bedrock-agentcore, lambda).

## OSS choices
| Component | Chosen | Substrate | Why / limit |
|---|---|---|---|
| C9 Memory long-term extraction | local model seam `llm_core.chat` (+ heuristic fallback) | both | no memory engine written. mem0 rejected: needs vector DB + LLM client stack, too heavy for Nano |
| C9 Memory retrieval | `llm_core.embed` + cosine over namespace-prefix filter (in-process lists) | both | MVP scale; not persisted beyond the store's account state |
| C4 Policy | cedarpy (Cedar, Apache-2.0, same engine as core/cedar_engine) | Mesh/host only | native Rust, not in Pyodide: on Nano an ENFORCE engine fails closed (denies all). cedar-wasm for Nano is open work |
| C4 Gateway MCP | existing stdlib JSON-RPC (streamable-HTTP JSON mode), semantic search via embeddings | both | `mcp` SDK not added: Pyodide/Nano must load the same code; a real `mcp` client works against JSON responses |
| C3 Runtime | Vyomi agent-spec runtime (existing) + new tool kinds `agent` (sub-agent, inline spec or other runtime), `gateway`, `memory` | both | see limits |

## Wire coverage
Control: Create/Get/List/Update/DeleteMemory, Create/Get/List/Update/DeletePolicyEngine, Create/Get/List/Update/DeletePolicy (Cedar validated, invalid -> ValidationException).
Data: CreateEvent, ListEvents, GetEvent, DeleteEvent, ListSessions, ListActors, RetrieveMemoryRecords, ListMemoryRecords, GetMemoryRecord, DeleteMemoryRecord, BatchDeleteMemoryRecords.
Policy model: principal `AgentCore::OAuthUser::<sub>` with JWT claims as Cedar tags (arrays comma-joined), action `AgentCore::Action::"<target>___<tool>"`,
resource `AgentCore::Gateway::<arn>`, `context.input` = tool arguments. ENFORCE = default deny; LOG_ONLY allows. Decisions are audited in account state.
Gateway call URL: `POST <endpoint>/gateways/<gatewayId>/mcp` (the fake `gatewayUrl` host is not routable).

## Probe (aws_probe.py, real SDK ops)
bedrock-agentcore 6% -> 26.2%; bedrock-agentcore-control 15% -> 29.3% routed (remaining: browsers, code interpreters, evaluators, credential providers, payments, etc.).

## Declared limits
- Runtimes do NOT host real containers / Strands / LangGraph: the agent is the Vyomi JSON spec over the local model. Real framework containers are Mesh-only and NOT built here.
- JWT claims are decoded, not signature-verified (Cognito lane issues tokens). Streaming runtime responses are buffered per call.
- Memory extraction is inline (real service is async); only conversational payloads are extracted; episodic/custom strategies use the generic extractor.
- Model router (C10) not done. Nano: memory/gateway/runtime spec work (pure Python); Cedar enforcement needs cedar-wasm.
