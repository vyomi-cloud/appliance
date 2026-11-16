# v4/ai-limgcpgw

Owner: AI session (lane `limgcpgw`). Base: local `v4/ai-integration` (5feeae0e6). Not merged; the orchestrator merges into v4/ai-integration.
Purpose: real GCP Agent Platform governance pages, Nano egress for AgentCore gateway targets, and the remaining AgentCore limits.

## What changed
- `core/gcp_agentgov_core.py` (new, vendored to wasm/core, listed in nano-boot.js and relay-shared-worker.js): Model Armor templates + sanitizeUserPrompt/ModelResponse,
  Provisioned Throughput bookkeeping, MCP server registry, agent gateways, agent policies. Wire adapters over AgentCore gateway, Cedar policy engines and Bedrock guardrails.
- `core/llm_core.py`: `http_request()` + an "http" kind in the `arun` NeedAsync replay, using the existing `globalThis.vyomiBackendFetch` egress bridge (no JS change).
- `core/agentcore_gateway_targets.py`: Nano no longer returns isError for openApi/mcpServer targets, OAuth token exchange, JWKS; smithyModel targets; SigV4 verification; A2A card + `message/stream`.
- `core/bedrock_agents_core.py`, `core/aws_wire_router.py`, `core/agentcore_ext_core.py`, `core/agent_spec_core.py`: wiring (smithy target kind, runtime inbound JWT, unsigned routing, webhook tools over the bridge).
- Console: `consoles/src/gcp/services/vertex-ai/GovernancePages.jsx` (Gateways + detail, MCP Servers, Policies, Security, Provisioned Throughput); five Not-in-scope entries removed; scopeHelp updated; capability JSONs (aws bedrock, gcp vertex-ai).

## OSS / engines
| Piece | Engine | Substrate |
|---|---|---|
| Model Armor | Bedrock guardrails engine (keyword/embedding + regex PII) | both |
| Gateway / MCP | AgentCore gateway (stdlib JSON-RPC) | both |
| Policies | cedarpy | Mesh/host only; Nano fails closed |
| SigV4 | stdlib hmac against IAM access keys | both |
| Egress | existing vyomiBackendFetch bridge (local tunnel or hosted allow-list relay) | Nano |

## Tests
`tests/conformance/test_agentcore_limits.py` (34), `test_gcp_agentgov_core.py` (46), `consoles/tests/smoke-limgcpgw.mjs` (16, Nano browser, real bridge to a local MCP server).

## Declared limits
- Google has no public API for Agent Gateway / Registry / Policies: resources are Vyomi extensions (`vyomiExtension`); a GCP gateway also appears in the AWS console (prefix `gcp-`).
- Cedar needs cedarpy: ENFORCE gateways deny everything on Nano.
- SigV4: IAM-held keys are verified; ambient keys (test/test) are admitted unverified unless `VYOMI_AGENTCORE_SIGV4_STRICT=1`. Relays that rewrite Host break signatures. No IAM policy evaluation for InvokeGateway.
- Smithy: awsJson1_0/1_1 and restJson1 only. A2A stream emits SSE after the run completes (not token level).
- Model Armor: malicious URI and advanced SDP are EXECUTION_SKIPPED; no floor settings. Provisioned Throughput reserves nothing.
- Still open: USER_FEDERATION OAuth, InvokeAgentRuntimeCommand. Hosted relay only reaches allow-listed public https origins.
