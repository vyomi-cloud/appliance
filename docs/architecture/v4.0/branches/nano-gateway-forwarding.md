# v4/nano-gateway-forwarding

Owner: nano-gateway-forwarding session - Started: 2026-11-12 - Base: origin/v4-on-main (c4c1a075a) - Status: built, pending browser console (SW) and shared-worker verification

## Purpose
Make the Nano GCP API Gateway reach a real backend (v4.0.0 blocker 1), following docs/architecture/v4.0/GATEWAY-NANO-FORWARDING.md and the owner decisions of 2026-11-12.

## Architecture
tab (Pyodide) `AwsWireRouter.ahandle` -> `gcp_apigateway_gateway.plan()` (route, auth, quota once) -> awaited `globalThis.vyomiBackendFetch` (`wasm/gw-bridge.js`, installed by nano-boot.js,
relay-shared-worker.js, nano-endpoint.html) -> local relay `GET /gw-token` + `POST /gw-egress` (`wasm/relay/gw-egress-node.mjs`, policy in `wasm/relay/gw-egress.mjs`) -> mapped backend;
fallback for public https: hosted relay `POST /gw-egress` (`wasm/relay/worker.js`). -> `finish()`.
CLI: `vyomi-tunnel gateway-backend <https origin>=<local origin> | --list | --remove <origin>` (`wasm/relay/mesh-cli.mjs`; map in `~/.vyomi/gateway-backends.json`, re-read per request).

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Split GCP only (`plan`/`finish`/`ahandle`); v1/v2/APIM keep inline `http_fetch` | Re-run-with-capture trick for all clouds | v2/v1 interleave Lambda invokers and throttle state with the fetch; a two-pass replay would count quota twice. Documented seam. |
| Local relay: per-process token from CORS-gated `GET /gw-token` + Origin allow-list (vyomi.cloud, localhost, `VYOMI_GW_ORIGINS`) + signed-in relay (`VYOMI_RELAY_AUTH=1` / the published CLI) | Open `/gw-egress` on loopback | Any web page can reach 127.0.0.1; only the Nano origin may get the token. A local non-browser process can forge Origin, but it is already local and is limited to mapped backends. |
| Redirects are never followed (3xx returned verbatim) | Re-validate each hop | ESPv2 does not follow either; removes the redirect-to-private class entirely. |
| Local target pinned to the DNS answer that was validated; metadata/link-local refused even when mapped; loopback/private allowed ONLY when mapped | Block private targets | Mapping to `127.0.0.1:3000` is the feature. |
| Hosted: https, 443 only, no IP literals / internal names, host allow-list (run.app, cloudfunctions.net, azurewebsites.net, execute-api, vercel/netlify/render/fly ...; `GW_EGRESS_ALLOW` overrides), 1 MiB / 4 MiB / 15 s, registered Nano session required (DO `has-tab`), `GW_LIMIT` binding + in-isolate limiter | Open public proxy | Abuse / SSRF / cost. |
| Gateway egress OFF in the appliance-bundled relay copy | On everywhere | Only the signed-in user CLI serves it. |

## Open issues
- [ ] The in-page path (nano-boot.js, console + service worker on :8099) and the SharedWorker path load the same bridge but were NOT browser-run; only nano-endpoint.html was (e2e-gateway.mjs). (owner: next session)
- [ ] Hosted relay route is unit-tested with mocks (no wrangler deploy / no real Cloudflare run). Not deployed. (owner: integrator)
- [ ] AWS API Gateway v1/v2 and Azure APIM still 503 on Nano: apply plan/finish there (seam in `apigatewayv2_gateway.handle`, `apigateway_core._run_integration`). (owner: next session)
- [ ] `packaging/tunnel/bin/*` is a GENERATED copy and was NOT regenerated; nothing published. Re-sync at the next tunnel release. (owner: release)
- [ ] Console UI hint for an unmapped backend (the 503 text names the command; no UI affordance). (owner: -)

## Testing
- `tests/conformance/test_gcp_apigateway_split.py` (offline + Nano PYTHONPATH): handle == plan+finish == ahandle on 7 cases, quota once per path, router async door. PASS.
- Existing `test_gcp_apigateway_gateway.py`, `test_gcp_apigateway_core.py` PASS unchanged.
- `wasm/relay/test-gw-egress.mjs` (43 checks): local gate (token, Origin, 401/403/501), mapped 2xx, unmapped 502, metadata/DNS block, redirect not followed, oversize req/resp 413, timeout 504, methods 405, rate limit, logging, address classification, hosted policy, Worker route, CLI, a real relay process incl. PNA preflight. PASS.
- `wasm/relay/e2e-gateway.mjs`: real Chromium + Pyodide on `nano-endpoint.html` + real local relay + real backend: API/config/gateway created in the tab, real 200 via the gateway, 401 enforced, quota 200/200/429 across the async hop, unmapped -> 503. PASS.
