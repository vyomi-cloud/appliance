# v4/gateway-nano-aws-azure

Owner: conformance agent session - Started: 2026-11-12 - Base: origin/v4-on-main (2a48912d7) - Status: ready for integration

## Purpose
Nano API gateways forward HTTP integrations to a real backend for AWS API Gateway v1 (REST), v2 (HTTP) and Azure APIM, through the same bridge
(`wasm/gw-bridge.js` -> local relay `/gw-egress` backend map) that already serves GCP API Gateway.

## Architecture
- `core/gateway_common.py`: `Fetch` (one outbound hop, no I/O), `BackendUnavailable`, `drive()` (sync) and `adrive()` (awaited) run an engine GENERATOR to completion.
- Each engine is a resumable run: everything before the hop (route match, Lambda, MOCK, authorizers, throttle, usage plan / quota, policies, subscription key)
  runs ONCE inside the generator, which then yields a `gc.Fetch` and resumes with `(status, headers, body)`. Exceptions from the driver are thrown into the generator at the yield, so each engine keeps its own error mapping.
  - v2: `handle_steps` / `handle` (= drive) / `ahandle` in `core/apigatewayv2_gateway.py`
  - v1: `invoke_steps` / `invoke` / `ainvoke` and `_run_integration_steps` in `core/apigateway_core.py` (`core/apigateway_gateway.enforce` unchanged)
  - Azure APIM: `handle_steps` / `handle` / `ahandle` in `core/azure_apim_gateway_core.py`
- `core/aws_wire_router.py` `ahandle`: for `apigw-invoke`, `apigateway` (`_user_request_`) and `azure-apim-gw`, when the runtime has no sockets (or a host injects `async_backend_fetch`) `_agw_invoke` awaits the engine's async twin with the bridge hook. The sync `handle()` branches are untouched. APIM `vyomi-site://` backends stay in-process.
- Azure `validate-jwt` RS256 now verifies through `gateway_common.make_rs256_verifier()` when an issuer is discoverable and the runtime can verify; otherwise unchanged (claims-only + `jwt-signature-unverified`).

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Generator-based resumable run, one engine body | plan()/finish() as in GCP; re-running the handler with a recording fetch | Lambda invokers, throttle buckets and APIM policies interleave with the fetch; plan/finish would duplicate the body, re-running would consume counters twice. A generator is the single body and runs counters exactly once. |
| Router-level async twin (`_agw_invoke`) instead of a deferred value through `handle()` | sentinel returned through the telemetry front door | handle() records telemetry from the response; a sentinel would corrupt it. |

## Open issues
- [ ] COGNITO_USER_POOLS and RS256 JWTs still fail closed / unverified in a tab (no verifier on emscripten); JWKS fetch through the bridge not built.
- [ ] The async path skips the telemetry recorder in `handle()` (same as the GCP gateway async path).
- [ ] Console / service-worker path on :8099 and the SharedWorker path not browser-tested; only the nano-endpoint relay tab path (e2e-gateway.mjs).

## Testing
- Python (offline and Nano flat layout, `PYTHONPATH=wasm`): test_aws_apigateway_split, test_azure_apim_split (new), test_gcp_apigateway_split, plus the existing v2/v1/core/APIM/GCP suites, test_no_cloud_egress, test_nano_core_manifest.
- Real Chromium + Pyodide + local relay: `wasm/relay/e2e-gateway.mjs` proves real 2xx through GCP, AWS v2 HTTP_PROXY, AWS v1 HTTP_PROXY and Azure APIM, throttle / rate-limit once-only across the hop, unmapped backend refused, APIM key enforced.
- NOT run: Mesh / Docker appliance end-to-end, real Cloudflare relay.
