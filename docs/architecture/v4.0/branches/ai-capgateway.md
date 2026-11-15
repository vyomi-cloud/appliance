# v4/ai-capgateway

Owner: AI session (lane `capgateway`, round 6). Base: local v4/ai-integration (20c01eaa3). Purpose: close the "Dev Simplified" limits of
`bedrock.agentcore.gateway` and `bedrock.agentcore.runtime` (core/capabilities/aws/bedrock.json) instead of hiding the badges. Not merged.

## What changed
- `core/agentcore_gateway_targets.py` (new, mirrored to `wasm/core/`, listed in `wasm/build_cores.py` and `wasm/nano-boot.js`): inbound JWT validation,
  openApiSchema + mcpServer target execution, credential providers, runtime MCP/A2A JSON-RPC.
- `core/bedrock_agents_core.py` (additive): `_mcp` validates CUSTOM_JWT; `_mcp_tools` lists openApi / upstream-MCP tools; `tools/call` dispatches them;
  `_create_target` validates OpenAPI specs and referenced providers; `/identities/*` routed to the new module; `_invoke_runtime` branches on `serverProtocol` MCP/A2A.
- `core/aws_wire_router.py` (one-line, shared file): `/identities/oauth2/token` is no longer claimed by the Azure AD token route (`GetResourceOauth2Token`).
- Tests: `tests/conformance/test_agentcore_gateway_targets.py` (38 checks, real boto3 + plain HTTP, real upstream HTTP/MCP/OAuth servers),
  `tests/conformance/jwt_issuer.py` (RSA issuer + JWKS server). `test_agentcore_facilities.py` now mints real RS256 tokens (the old alg:none tokens are correctly rejected).

## OSS choices
| Component | Chosen | Substrate | Why / limit |
|---|---|---|---|
| JWT signature/claims | existing `core/gateway_common` (`jwt_validate`, `make_rs256_verifier`; `cryptography`, Apache-2.0/BSD) | Mesh/host; Nano only for in-process Cognito pools if `cryptography` loads | PyJWT not used: the verifier already exists and PyJWT is not in Pyodide. RS256 only; fails closed (401) when no verifier. |
| Cognito JWKS | `identity_core.local_jwks` (moto) | both | no network for this simulator's pools; other issuers via OIDC discovery of `discoveryUrl` (5 min cache) |
| OpenAPI parsing | stdlib json, PyYAML if importable (MIT) | both | no new dependency; `$ref` resolved, flat tool schema (params + body properties) |
| Outbound calls | stdlib urllib | Mesh/host | Nano browser has no egress: tools return isError (declared). The Nano allow-listed proxy is not wired for this path. |
| MCP proxy | minimal streamable-HTTP client (JSON or SSE replies), stateless initialize per call | Mesh/host | `mcp` SDK not added (Pyodide must load the same code) |
| Cedar / semantic search / memory | unchanged (previous lane) | | |

## Behaviour
- CUSTOM_JWT: Bearer in `Authorization` (or `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Authorization` for SigV4-signed callers). 401 = missing, malformed, bad signature (incl. same kid other key), expired, wrong issuer, undiscoverable issuer; 403 = audience / client / scope not in allowedAudience / allowedClients / allowedScopes.
- Credential providers: Create/Get/Update/Delete/List for ApiKey and Oauth2 (secrets never echoed); `GetResourceApiKey`, `GetResourceOauth2Token` (M2M). Gateway targets: `API_KEY` (header or query, prefix), `OAUTH` (client_credentials, basic or post auth, token cached to expiry-30s), `JWT_PASSTHROUGH`, `GATEWAY_IAM_ROLE` (none).
- Runtime protocol MCP: spec tools served as an MCP server. A2A: `message/send` (completed Task, contextId = session, memory hooks apply), `tasks/get`, `agent/getAuthenticatedExtendedCard`.

## Probe (aws_probe.py)
bedrock-agentcore-control routed 29.3% -> 37.4%; bedrock-agentcore 26.2% -> 29.2% (before = figures in ai-agentcore.md).

## Declared limits
- smithyModel targets registered, not callable. AWS_IAM gateways: header presence only (no SigV4 verification).
- Outbound HTTP (openApi, mcpServer, OAuth token exchange) is Mesh/host only. USER_FEDERATION OAuth, vendor-specific discovery, workload-identity token verification not implemented (token must be non-empty).
- Runtime inbound JWT is still decoded, not verified. A2A agent card is an RPC method (not `/.well-known/agent-card.json`), no streaming / push. InvokeAgentRuntimeCommand not done.
- Credential secrets live in the persisted account bag (not Secrets Manager).
