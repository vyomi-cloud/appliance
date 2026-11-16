# v4/ai-limauth

Owner: AI session (lane `limauth`). Base: `v4/ai-integration` (743ef3a64). Not merged; the orchestrator merges into v4/ai-integration.
Purpose: close the remaining AgentCore / Agents / Flows engineering gaps listed under "not closed" in ai-limgcpgw, ai-limagents, ai-limflows (ai-limvector had none open that this lane owns).

## Limit -> result
| Limit | Result |
|---|---|
| USER_FEDERATION OAuth (GetResourceOauth2Token with callback / session URI) | **closed** |
| InvokeAgentRuntimeCommand | **partly** (real event stream on the code sandbox; documented sh subset, no real shell) |
| A2A `message/stream` and InvokeAgentRuntime SSE per token | **closed on Mesh/appliance**; Nano's in-browser wire still delivers the response body whole |
| Cedar enforcement on Nano | **closed** (cedar-wasm) |
| KNOWLEDGE_BASE_RESPONSE_GENERATION prompt applied | **closed** |
| Flows InlineCode node | **closed**; Lex node **not closed** (no Lex NLU runtime exists to run an intent) |
| AWS_IAM SigV4 for ambient keys | **was already closed** at the base (IAM-held keys always verified); tests now pin it; unknown keys keep the documented unverified-admit behaviour |

## What changed
- `core/cedar_wasm_shim.py` (new, mirrored to `wasm/core`): a `cedarpy`-shaped facade. Mesh/host use the real `cedarpy`; under Pyodide it calls `globalThis.__vyomi_cedar_eval` synchronously. `core/agentcore_ext_core.py` imports it instead of `cedarpy`; an evaluator that failed to load still fails closed under ENFORCE.
- `wasm/cedar/` (new): `cedar_wasm.js` + `cedar_wasm_bg.wasm` (**@cedar-policy/cedar-wasm 4.14.0, web build, Apache-2.0, 4.4 MB**, unmodified, same-origin like the pypdf wheel) and `cedar-eval.mjs` (installs the global). Loaded in `wasm/nano-boot.js` and `wasm/relay/relay-shared-worker.js` next to the Kubescape evaluator; load failure only warns.
- `core/identity_core.py`: Cognito hosted-UI endpoints on moto, pool-scoped (`/{poolId}/oauth2/authorize`, `/{poolId}/login`, `/{poolId}/oauth2/token`, `/{poolId}/oauth2/userInfo`; the pool's `openid-configuration` advertises them): authorization-code grant with S256 PKCE, CallbackURLs check, client secret (Basic or post), single-use 5-minute codes, refresh_token grant. Sign-in is `InitiateAuth USER_PASSWORD_AUTH` on moto, tokens are moto's real RS256 JWTs. `core/aws_wire_router.py`: the Azure-Graph `/oauth2/(token|authorize)` route now skips `/{poolId}/...`; unsigned `/identities/oauth2/callback/{id}` and `/runtimes/.../commands` reach AgentCore.
- `core/agentcore_gateway_targets.py`: USER_FEDERATION (`GetResourceOauth2Token`, `CompleteResourceTokenAuth`, `GetWorkloadAccessToken[ForUserId|ForJWT]`), callback handler, `callbackUrl` built from the request Host (AWS host otherwise), token cache per (provider, user, scopes), `forceAuthentication`, `customState`, `resources` / `audiences` / `customParameters`; `runtime_a2a(..., run_stream)` token-level `message/stream`.
- `core/agent_spec_core.py`: `run_events(..., stream_tokens=True)` over `llm_core.chat_stream`; `core/agentcore_ext_core.py`: `run_context_iter` (tool context bound per generator step); `core/bedrock_agents_core.py`: SSE emits `token` events as produced (the stream is primed before the first byte so a dead model still answers 503).
- `core/agentcore_command_core.py` (new): InvokeAgentRuntimeCommand on `core/code_sandbox_core.py` (subprocess engine on Mesh, AST-gated in-process on Nano; both exercised).
- `core/bedrock_agents_core.py`: KB response generation (`_kb_response_generation`). `core/bedrock_build_core.py`: `InlineCode` node, Lex rejected with an explanation.
- Capability JSON (`aws/bedrock.json`, `gcp/vertex-ai.json`), `scopeHelp.js`, the GCP governance page note and `gcp_agentgov_core` header rewritten to match.
- `wasm/build_cores.py`: lists the new cores plus `agent_spec_core.py` and `agentcore_ext_core.py` (the Nano mirror of those two was not refreshed by the build before).

## OSS choices
| Piece | OSS | Substrate | Notes |
|---|---|---|---|
| Cedar on Nano | cedar-policy/cedar via @cedar-policy/cedar-wasm 4.14.0 (Apache-2.0), 4.4 MB wasm + 22 KB JS | Nano (page + relay worker); Mesh keeps cedarpy | No pure-Python Cedar exists. Parity with cedarpy tested on 10 policies + the whole Facilities AgentCore suite. |
| Hosted-UI authorization server | moto cognitoidp (Apache-2.0) for users, clients, tokens | Mesh/appliance (moto is not verified in the browser) | glue only: code store + PKCE check (stdlib) |
| Commands | existing code sandbox | both | no shell engine written beyond a small parser |
| InlineCode | existing code sandbox | both | |
| Streaming | existing `llm_core.chat_stream` | both seams | |

## Tests (real boto3 + plain HTTP)
`test_agentcore_auth_limits.py` (49: PKCE flow end to end, command stream, timed token streaming on A2A and SSE, SigV4), `test_agentcore_cedar_wasm.py` (cedar-wasm in Node through a fake Pyodide `js`), `test_bedrock_agents_limits.py` (+7 KB response generation), `test_bedrock_flows.py` (+8 InlineCode), `test_agentcore_limits.py` (A2A stream assertion updated). Run each as `PYTHONPATH=. python tests/conformance/<file>`.

## Declared limits
- USER_FEDERATION against the local pool needs moto (Mesh/appliance). On Nano use an external IdP through the egress relay, or the Mesh. The callback URL host is whatever Host the SDK called; a relay that rewrites it must be registered at the IdP. Workload access tokens are Vyomi-minted and **not signature-verified**; ON_BEHALF_OF_TOKEN_EXCHANGE and vendor-specific discovery are not implemented. The hosted UI is a plain form: no MFA, NEW_PASSWORD, social/SAML federation or scope enforcement.
- Commands: subset of sh (see `agentcore_command_core.py`), output per command not mid-process, files <= 1 MiB x 8 per call, no network, no pip/npm/git.
- Streaming: per token needs a streaming model backend (llama.cpp / Ollama or a registered streaming backend); prompt-translated tool steps and structured output are replayed in pieces. The Nano wire does not stream response bodies, so Nano callers receive the full SSE body at the end.
- Cedar: schema validation is off (`validateRequest: false`), as with cedarpy here. Not browser-tested in a real Chromium in this lane: Node ran the same module that `nano-boot.js` imports; the Pyodide-side call (`js.globalThis`) is the same pattern as the Kubescape evaluator.
- KB response generation only runs for an OVERRIDDEN prompt; the parser response shape (`generatedResponse.generatedResponseParts`) follows the AWS parser-Lambda documentation as recalled, not a captured payload.
- InlineCode: the last expression is the output (named by the node's first declared output, default `response`); stdlib only on Nano; 10 s limit. Lex nodes stay rejected.
